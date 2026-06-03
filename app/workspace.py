"""Worktree management — create and remove git worktrees for agent sessions."""

import fcntl
import json
import logging
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

WORKTREE_ROOT = Path(__file__).parent.parent / "worktrees"
PROJECT_FILES = ("CLAUDE.md", ".worktreeinclude", ".mcp.json", ".env")


@dataclass
class Worktree:
    path: str
    branch: str


def _slugify(s: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]", "-", s).strip("-")
    slug = re.sub(r"-+", "-", slug)
    return slug.lower()[:80]


_TASK_ID_RE = re.compile(r"^([A-Z]{2,5})-(\d+)$", re.IGNORECASE)
_TASK_ID_BARE = re.compile(r"^(\d+)$")


def _normalize_task_id(task_id: str) -> str:
    tid = task_id.strip().lstrip("#")
    m = _TASK_ID_RE.match(tid)
    if m:
        n = int(m.group(2))
        if n < 1:
            raise ValueError(f"Invalid task_id '{task_id}': number must be >= 1")
        return str(n)
    m = _TASK_ID_BARE.match(tid)
    if m:
        n = int(m.group(1))
        if n < 1:
            raise ValueError(f"Invalid task_id '{task_id}': number must be >= 1")
        return str(n)
    raise ValueError(f"Invalid task_id '{task_id}': expected number, #N, or PREFIX-N (legacy)")


def create_worktree(repo_path: str, name: str, scope: str, task_id: str = "",
                    base_branch: str = "main") -> Worktree:
    repo = Path(repo_path).resolve()
    if not repo.is_dir():
        raise ValueError(f"repo_path does not exist: {repo_path}")

    scope_slug = _slugify(scope)
    wt_dir = WORKTREE_ROOT / scope_slug
    wt_dir.mkdir(parents=True, exist_ok=True)
    wt_path = wt_dir / name

    if task_id:
        par = _normalize_task_id(task_id)
        branch = f"task-{par}/{name}"
    else:
        branch = f"feat/{scope_slug}/{name}"

    if wt_path.exists():
        raise ValueError(f"worktree already exists: {wt_path}. Remove session first.")

    ref_check = subprocess.run(
        ["git", "show-ref", "--verify", f"refs/heads/{branch}"],
        cwd=str(repo), capture_output=True, text=True,
    )

    fmt_check = subprocess.run(
        ["git", "check-ref-format", "--branch", branch],
        cwd=str(repo), capture_output=True, text=True,
    )
    if fmt_check.returncode != 0:
        raise ValueError(f"Invalid branch name '{branch}': {fmt_check.stderr.strip()}")

    if ref_check.returncode == 0:
        # ветка уже существует — допустимо только если не занята другим worktree
        if _is_branch_checked_out_elsewhere(str(repo), branch, wt_path):
            raise ValueError(f"Branch '{branch}' is checked out in another worktree.")
        # reuse: git worktree add <path> <branch> (без -b)
        result = subprocess.run(
            ["git", "worktree", "add", str(wt_path), branch],
            cwd=str(repo), capture_output=True, text=True,
        )
    else:
        # ветка новая — создаём через -b
        result = subprocess.run(
            ["git", "worktree", "add", str(wt_path), "-b", branch, base_branch],
            cwd=str(repo), capture_output=True, text=True,
        )
    if result.returncode != 0:
        raise RuntimeError(f"git worktree add failed: {result.stderr.strip()}")

    try:
        for fname in PROJECT_FILES:
            src = repo / fname
            if not src.exists():
                src = repo.parent / fname
            if src.exists():
                shutil.copy2(str(src), str(wt_path / fname))
    except Exception:
        subprocess.run(
            ["git", "worktree", "remove", str(wt_path), "--force"],
            cwd=str(repo), capture_output=True, text=True,
        )
        raise

    return Worktree(path=str(wt_path), branch=branch)


def _resolve_repo(worktree_path: str, fallback_repo: str) -> Path:
    wt = Path(worktree_path).resolve()
    git_common = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"],
        cwd=str(wt), capture_output=True, text=True,
    )
    if git_common.returncode == 0:
        git_dir = Path(git_common.stdout.strip())
        if not git_dir.is_absolute():
            git_dir = (wt / git_dir).resolve()
        return git_dir.parent
    return Path(fallback_repo).resolve()


def _ensure_repo_on_branch(repo: str, target_branch: str = "main") -> tuple[str | None, bool]:
    """Returns (error_or_None, did_stash).

    Выполняет stash (если репо грязный) и checkout target_branch.
    НЕ делает stash pop — это обязанность вызывающего кода в блоке finally.
    """
    did_stash = False
    repo_status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True,
    )
    if repo_status.stdout.strip():
        stash = subprocess.run(
            ["git", "stash", "--include-untracked"], cwd=repo, capture_output=True, text=True,
        )
        if stash.returncode != 0:
            return f"main repo dirty and stash failed: {stash.stderr.strip()}", False
        did_stash = True
        logger.info(f"Auto-stashed dirty repo: {repo}")
    head = subprocess.run(
        ["git", "symbolic-ref", "--short", "HEAD"], cwd=repo, capture_output=True, text=True,
    )
    if head.returncode != 0 or head.stdout.strip() != target_branch:
        checkout = subprocess.run(
            ["git", "checkout", target_branch], cwd=repo, capture_output=True, text=True,
        )
        if checkout.returncode != 0:
            # НЕ делаем stash pop здесь — did_stash=True сигнализирует finally в вызывающем коде
            return f"cannot checkout {target_branch} in repo: {checkout.stderr.strip()}", did_stash
    return None, did_stash


def _get_commit_messages(repo: str, branch: str, base: str) -> list[str]:
    """Return subject lines of commits in branch not in base."""
    log = subprocess.run(
        ["git", "log", f"{base}..{branch}", "--format=%s", "--reverse"],
        cwd=repo, capture_output=True, text=True,
    )
    if log.returncode != 0 or not log.stdout.strip():
        return []
    return [line for line in log.stdout.strip().splitlines() if line.strip()]


def _build_squash_message(branch: str, messages: list[str]) -> str:
    """Build squash commit message with task refs prefix and message list."""
    all_refs: list[str] = []
    seen: set[str] = set()
    for msg in messages:
        for m in _TASK_REF_RE.finditer(msg):
            if m.group(3):
                ref = f"#{m.group(3)}"
            else:
                ref = f"#{m.group(2)}"
            if ref not in seen:
                seen.add(ref)
                all_refs.append(ref)

    if messages:
        summary = messages[-1] if len(messages) == 1 else messages[0]
    else:
        summary = f"merge {branch}"

    prefix = ", ".join(all_refs) + ": " if all_refs else ""
    header = f"{prefix}{summary}"

    body_lines = "\n".join(f"- {m}" for m in messages)
    if len(messages) > 1:
        return f"{header}\n\nSquashed commits:\n{body_lines}"
    return header


def _cherry_pick_branch(repo: str, branch: str, old_head: str) -> dict:
    """Cherry-pick all commits from branch onto current HEAD.
    Fallback for unrelated histories where git merge refuses to work.
    """
    rev_list = subprocess.run(
        ["git", "rev-list", "--reverse", branch],
        cwd=repo, capture_output=True, text=True,
    )
    if rev_list.returncode != 0 or not rev_list.stdout.strip():
        return {"ok": False, "error": f"cannot list commits on {branch}: {rev_list.stderr.strip()}"}

    commits = rev_list.stdout.strip().splitlines()
    logger.info(f"cherry-pick fallback: {len(commits)} commits from {branch}")

    messages = _get_commit_messages(repo, branch, "")

    for i, sha in enumerate(commits):
        cp = subprocess.run(
            ["git", "cherry-pick", "--no-commit", sha],
            cwd=repo, capture_output=True, text=True,
        )
        if cp.returncode != 0:
            cp_err = cp.stderr.strip() or cp.stdout.strip()
            if "nothing to commit" in cp_err or "empty" in cp_err.lower():
                subprocess.run(["git", "reset"], cwd=repo, capture_output=True, text=True)
                continue
            subprocess.run(
                ["git", "cherry-pick", "--abort"],
                cwd=repo, capture_output=True, text=True,
            )
            return {"ok": False, "error": f"cherry-pick failed on commit {sha[:7]} ({i+1}/{len(commits)}): {cp_err}"}

    status = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=repo, capture_output=True, text=True,
    )
    if status.returncode != 0:
        commit_msg = _build_squash_message(branch, messages)
        subprocess.run(
            ["git", "commit", "-m", commit_msg],
            cwd=repo, capture_output=True, text=True,
        )

    merged_commits = _parse_merged_commits(repo, old_head) if old_head else {}
    return {
        "ok": True,
        "commits_merged": len(commits),
        "branch": branch,
        "strategy": "cherry-pick",
        "merged_commits": merged_commits,
    }


def _reset_worktree_to_ref(worktree_path: str, ref: str, repo_path: str) -> None:
    wt = Path(worktree_path).resolve()
    repo = _resolve_repo(worktree_path, repo_path)
    rev = subprocess.run(
        ["git", "rev-parse", ref],
        cwd=str(repo), capture_output=True, text=True,
    )
    if rev.returncode != 0:
        logger.warning(f"_reset_worktree_to_ref: cannot resolve {ref}: {rev.stderr.strip()}")
        return
    target_sha = rev.stdout.strip()
    reset = subprocess.run(
        ["git", "reset", "--hard", target_sha],
        cwd=str(wt), capture_output=True, text=True,
    )
    if reset.returncode != 0:
        logger.warning(f"_reset_worktree_to_ref: reset failed in {wt}: {reset.stderr.strip()}")
    else:
        logger.info(f"_reset_worktree_to_ref: {wt} reset to {ref} ({target_sha[:8]})")


def merge_worktree_to_main(worktree_path: str, repo_path: str, target_branch: str = "main") -> dict:
    wt = Path(worktree_path).resolve()
    repo = _resolve_repo(str(wt), repo_path)
    lock_path = repo / ".git" / "orchestra-merge.lock"

    original_branch = None   # инициализируем ДО try/with — finally видит всегда
    did_stash = False         # инициализируем ДО try — иначе UnboundLocalError в finally
    result = None             # инициализируем ДО try — возврат по умолчанию при любом пути

    with open(lock_path, "w") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        try:
            # Сохраняем исходную ветку ДО любого checkout
            original_branch_result = subprocess.run(
                ["git", "symbolic-ref", "--short", "HEAD"],
                cwd=str(repo), capture_output=True, text=True,
            )
            original_branch = original_branch_result.stdout.strip() if original_branch_result.returncode == 0 else None

            branch_result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=str(wt), capture_output=True, text=True,
            )
            if branch_result.returncode != 0:
                result = {"ok": False, "error": f"cannot get branch: {branch_result.stderr.strip()}"}
            else:
                branch = branch_result.stdout.strip()

                status = subprocess.run(
                    ["git", "status", "--porcelain"],
                    cwd=str(wt), capture_output=True, text=True,
                )
                if status.stdout.strip():
                    result = {"ok": False, "error": "dirty working tree — commit or discard changes first"}
                else:
                    # Edge-case: проверяем target_branch перед checkout
                    ref_verify = subprocess.run(
                        ["git", "show-ref", "--verify", f"refs/heads/{target_branch}"],
                        cwd=str(repo), capture_output=True, text=True,
                    )
                    if ref_verify.returncode != 0:
                        result = {"ok": False, "error": f"target branch '{target_branch}' does not exist"}
                    elif _is_branch_checked_out_elsewhere(str(repo), target_branch, Path(repo).resolve()):
                        result = {"ok": False, "error": f"target branch '{target_branch}' is checked out in another worktree"}
                    else:
                        main_err, did_stash = _ensure_repo_on_branch(str(repo), target_branch)
                        if main_err:
                            result = {"ok": False, "error": main_err}
                        else:
                            merge_base = subprocess.run(
                                ["git", "merge-base", target_branch, branch],
                                cwd=str(repo), capture_output=True, text=True,
                            )
                            unrelated = merge_base.returncode != 0

                            precheck_ok = True
                            if not unrelated:
                                precheck = subprocess.run(
                                    ["git", "merge-tree", "--write-tree", target_branch, branch],
                                    cwd=str(repo), capture_output=True, text=True,
                                )
                                if precheck.returncode != 0:
                                    conflict_files = []
                                    for line in precheck.stdout.splitlines():
                                        if line.startswith("CONFLICT"):
                                            parts = line.split()
                                            if parts:
                                                conflict_files.append(parts[-1])
                                    if not conflict_files:
                                        err = precheck.stderr.strip() or precheck.stdout.strip() or f"merge-tree exit code {precheck.returncode}"
                                        logger.error(f"merge-tree failed: repo={repo} branch={branch} err={err}")
                                        result = {"ok": False, "error": f"merge precheck failed: {err}"}
                                    else:
                                        result = {"ok": False, "conflicts": conflict_files}
                                    precheck_ok = False

                            if precheck_ok:
                                old_head_result = subprocess.run(
                                    ["git", "rev-parse", "HEAD"],
                                    cwd=str(repo), capture_output=True, text=True,
                                )
                                old_head = old_head_result.stdout.strip() if old_head_result.returncode == 0 else ""

                                if unrelated:
                                    logger.info(f"unrelated histories for {branch} — using cherry-pick")
                                    result = _cherry_pick_branch(str(repo), branch, old_head)
                                    if result and result.get("ok"):
                                        _reset_worktree_to_ref(str(wt), target_branch, str(repo))
                                else:
                                    commits_result = subprocess.run(
                                        ["git", "rev-list", "--count", f"{target_branch}..{branch}"],
                                        cwd=str(repo), capture_output=True, text=True,
                                    )
                                    commits_merged = int(commits_result.stdout.strip() or "0")

                                    messages = _get_commit_messages(str(repo), branch, target_branch)
                                    merge = subprocess.run(
                                        ["git", "merge", "--squash", branch],
                                        cwd=str(repo), capture_output=True, text=True,
                                    )
                                    if merge.returncode != 0:
                                        subprocess.run(
                                            ["git", "reset", "--merge"],
                                            cwd=str(repo), capture_output=True, text=True,
                                        )
                                        err = merge.stderr.strip() or merge.stdout.strip() or f"git merge exit code {merge.returncode}"
                                        logger.error(f"merge_worktree squash failed: repo={repo} branch={branch} err={err}")
                                        result = {"ok": False, "error": err}
                                    else:
                                        staged = subprocess.run(
                                            ["git", "diff", "--cached", "--quiet"],
                                            cwd=str(repo), capture_output=True, text=True,
                                        )
                                        if staged.returncode != 0:
                                            commit_msg = _build_squash_message(branch, messages)
                                            commit = subprocess.run(
                                                ["git", "commit", "-m", commit_msg],
                                                cwd=str(repo), capture_output=True, text=True,
                                            )
                                            if commit.returncode != 0:
                                                err = commit.stderr.strip() or commit.stdout.strip()
                                                result = {"ok": False, "error": f"squash commit failed: {err}"}
                                            else:
                                                merged_commits = _parse_merged_commits(str(repo), old_head) if old_head else {}
                                                result = {"ok": True, "commits_merged": commits_merged, "branch": branch, "merged_commits": merged_commits}
                                        else:
                                            result = {"ok": True, "commits_merged": 0, "branch": branch, "merged_commits": {}}

                                        if result and result.get("ok"):
                                            _reset_worktree_to_ref(str(wt), target_branch, str(repo))
        finally:
            # ПОРЯДОК КРИТИЧЕН: сначала restore исходной ветки, ПОТОМ stash pop.
            restore_ok = True
            if original_branch and original_branch != target_branch:
                restore = subprocess.run(
                    ["git", "checkout", original_branch],
                    cwd=str(repo), capture_output=True, text=True,
                )
                if restore.returncode != 0:
                    restore_ok = False
                    logger.error(f"restore branch failed: {restore.stderr.strip()}")
                    result = {"ok": False, "state": "restore_failed",
                              "error": f"cannot restore branch '{original_branch}': {restore.stderr.strip()}"}
            # ЕДИНСТВЕННЫЙ stash pop — и ТОЛЬКО после успешного restore
            if did_stash and restore_ok:
                pop = subprocess.run(
                    ["git", "stash", "pop"], cwd=str(repo), capture_output=True, text=True,
                )
                if pop.returncode != 0:
                    logger.error(f"stash pop failed: {pop.stderr.strip()} — repo state may be dirty")
                    result = {"ok": False, "state": "stash_pop_failed",
                              "error": f"stash pop failed after merge: {pop.stderr.strip()}"}
            elif did_stash and not restore_ok:
                logger.error("skipping stash pop: HEAD restore failed; stash kept to avoid wrong-branch apply")
            fcntl.flock(lock_file, fcntl.LOCK_UN)
    return result if result is not None else {"ok": False, "error": "merge produced no result"}


_TASK_REF_RE = re.compile(r"(?:\b([A-Z]{2,5})-(\d+)\b|#(\d+)\b)")


def _parse_merged_commits(repo: str, old_head: str) -> dict[str, list[dict]]:
    log = subprocess.run(
        ["git", "log", f"{old_head}..HEAD", "--format=%H%x00%s%x00%ad", "--date=short"],
        cwd=repo, capture_output=True, text=True,
    )
    if log.returncode != 0 or not log.stdout.strip():
        return {}

    by_par: dict[str, list[dict]] = {}
    for line in log.stdout.strip().splitlines():
        parts = line.split("\x00", 2)
        if len(parts) < 3:
            continue
        full_hash, message, date = parts
        short_hash = full_hash[:7]

        refs: list[str] = []
        seen_refs: set[str] = set()
        for m in _TASK_REF_RE.finditer(message):
            ref = m.group(3) if m.group(3) else f"{m.group(1)}-{m.group(2)}"
            if ref not in seen_refs:
                seen_refs.add(ref)
                refs.append(ref)
        if not refs:
            continue

        stat = subprocess.run(
            ["git", "diff-tree", "--numstat", "--root", "-m", "--first-parent", full_hash],
            cwd=repo, capture_output=True, text=True,
        )
        files_changed = insertions = deletions = 0
        for stat_line in (stat.stdout.strip().splitlines() if stat.returncode == 0 else []):
            stat_parts = stat_line.split("\t")
            if len(stat_parts) == 3:
                try:
                    ins = int(stat_parts[0]) if stat_parts[0] != "-" else 0
                    dels = int(stat_parts[1]) if stat_parts[1] != "-" else 0
                    insertions += ins
                    deletions += dels
                    files_changed += 1
                except ValueError:
                    continue

        commit = {
            "hash": short_hash,
            "message": message,
            "date": date,
            "files": files_changed,
            "insertions": insertions,
            "deletions": deletions,
        }
        for ref in refs:
            by_par.setdefault(ref, []).append(commit)

    return by_par


def _is_branch_checked_out_elsewhere(repo: str, branch: str, current_wt: Path) -> bool:
    wt_list = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=repo, capture_output=True, text=True,
    )
    current_path = ""
    for line in wt_list.stdout.splitlines():
        if line.startswith("worktree "):
            current_path = line[len("worktree "):]
        elif line == f"branch refs/heads/{branch}":
            if current_path and Path(current_path).resolve() != current_wt:
                return True
    return False


def switch_worktree_branch(worktree_path: str, new_branch: str,
                           from_ref: str = "refs/heads/main") -> dict:
    wt = Path(worktree_path).resolve()
    repo = _resolve_repo(str(wt), str(wt))
    lock_path = repo / ".git" / "orchestra-merge.lock"

    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=str(wt), capture_output=True, text=True,
    )
    if status.stdout.strip():
        return {"ok": False, "error": "dirty working tree — commit or discard changes first"}

    reset = subprocess.run(
        ["git", "reset", "--hard", from_ref],
        cwd=str(wt), capture_output=True, text=True,
    )
    if reset.returncode != 0:
        return {"ok": False, "error": f"reset to {from_ref} failed: {reset.stderr.strip()}"}

    with open(lock_path, "w") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        try:
            ref_check = subprocess.run(
                ["git", "show-ref", "--verify", f"refs/heads/{new_branch}"],
                cwd=str(repo), capture_output=True, text=True,
            )
            if ref_check.returncode == 0:
                if _is_branch_checked_out_elsewhere(str(repo), new_branch, wt):
                    return {"ok": False, "error": f"branch '{new_branch}' is checked out in another worktree"}

                checkout = subprocess.run(
                    ["git", "checkout", new_branch], cwd=str(wt), capture_output=True, text=True,
                )
                if checkout.returncode != 0:
                    return {"ok": False, "error": f"checkout failed: {checkout.stderr.strip()}"}

                merge_main = subprocess.run(
                    ["git", "merge", from_ref, "--no-edit"],
                    cwd=str(wt), capture_output=True, text=True,
                )
                if merge_main.returncode != 0:
                    conflict_files = []
                    status_out = subprocess.run(
                        ["git", "diff", "--name-only", "--diff-filter=U"],
                        cwd=str(wt), capture_output=True, text=True,
                    )
                    if status_out.stdout.strip():
                        conflict_files = status_out.stdout.strip().splitlines()
                    return {"ok": False, "branch": new_branch, "conflicts": conflict_files,
                            "state": "conflict",
                            "error": f"merge conflict with {from_ref} — resolve or abort"}
            else:
                checkout = subprocess.run(
                    ["git", "checkout", "-b", new_branch, from_ref],
                    cwd=str(wt), capture_output=True, text=True,
                )
                if checkout.returncode != 0:
                    return {"ok": False, "error": f"branch create failed: {checkout.stderr.strip()}"}

            return {"ok": True, "branch": new_branch}
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)


def remove_worktree(repo_path: str, worktree_path: str) -> None:
    wt = Path(worktree_path)
    if not wt.exists():
        return
    cwd = repo_path
    git_file = wt / ".git"
    if git_file.exists() and git_file.is_file():
        try:
            content = git_file.read_text().strip()
            if content.startswith("gitdir:"):
                git_dir = Path(content.split("gitdir:", 1)[1].strip()).resolve()
                for parent in git_dir.parents:
                    if (parent / ".git").is_dir():
                        cwd = str(parent)
                        break
        except Exception:
            pass
    lock_path = _resolve_repo(str(wt), repo_path) / ".git" / "orchestra-merge.lock"
    with open(lock_path, "w") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        try:
            result = subprocess.run(
                ["git", "worktree", "remove", str(wt), "--force"],
                cwd=cwd, capture_output=True, text=True,
            )
            if result.returncode != 0:
                logger.warning(f"worktree remove failed: {result.stderr}")
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)


def cleanup_stale_worktrees() -> list[str]:
    from app.db import get_all_sessions
    if not WORKTREE_ROOT.is_dir():
        return []

    alive_paths: set[str] = set()
    for s in get_all_sessions():
        wt = s.get("worktree_path")
        if wt:
            alive_paths.add(str(Path(wt).resolve()))

    removed: list[str] = []
    for scope_dir in WORKTREE_ROOT.iterdir():
        if not scope_dir.is_dir():
            continue
        for wt_dir in scope_dir.iterdir():
            if not wt_dir.is_dir():
                continue
            if str(wt_dir.resolve()) in alive_paths:
                continue
            git_file = wt_dir / ".git"
            if not (git_file.exists() and git_file.is_file()):
                continue
            dirty = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=str(wt_dir), capture_output=True, text=True,
            )
            if dirty.returncode != 0 or dirty.stdout.strip():
                logger.info(f"stale worktree skipped (dirty): {wt_dir}")
                continue
            repo_path = str(wt_dir)
            try:
                content = git_file.read_text().strip()
                if content.startswith("gitdir:"):
                    git_dir = Path(content.split("gitdir:", 1)[1].strip()).resolve()
                    for parent in git_dir.parents:
                        if (parent / ".git").is_dir():
                            repo_path = str(parent)
                            break
            except Exception:
                pass
            try:
                remove_worktree(repo_path, str(wt_dir))
                removed.append(str(wt_dir))
                logger.info(f"stale worktree removed: {wt_dir}")
            except Exception as e:
                logger.warning(f"stale worktree cleanup failed for {wt_dir}: {e}")

        if scope_dir.is_dir() and not any(scope_dir.iterdir()):
            try:
                scope_dir.rmdir()
                logger.info(f"empty scope dir removed: {scope_dir}")
            except Exception:
                pass

    return removed


def parse_owned_dirs(raw) -> list[str]:
    """Normalize owned_dirs from any source (JSON string, list, None). Bad input → []."""
    if not raw:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return []
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for d in raw:
        if not isinstance(d, str):
            continue
        p = d.strip().strip("/")
        if p and p not in out:
            out.append(p)
    return out


def dirs_overlap(a: list[str], b: list[str]) -> list[str]:
    """Return overlapping dirs (prefix-aware): app/api conflicts with app/api/v1."""
    hits = []
    for x in a:
        for y in b:
            if x == y or x.startswith(y + "/") or y.startswith(x + "/"):
                hits.append(x if len(x) >= len(y) else y)
    return sorted(set(hits))


def simulate_conflict(repo_path: str, branch_a: str, branch_b: str) -> dict:
    """Dry-run merge of two existing branches. {ok:True, conflicts:[...]} = simulation ran.
    {ok:False, error} = couldn't run (missing branch / unrelated histories)."""
    repo = _resolve_repo(repo_path, repo_path)
    for ref in (branch_a, branch_b):
        v = subprocess.run(
            ["git", "rev-parse", "--verify", f"{ref}^{{commit}}"],
            cwd=str(repo), capture_output=True, text=True,
        )
        if v.returncode != 0:
            return {"ok": False, "error": f"branch '{ref}' not found"}
    mb = subprocess.run(
        ["git", "merge-base", branch_a, branch_b],
        cwd=str(repo), capture_output=True, text=True,
    )
    if mb.returncode != 0:
        return {"ok": False, "error": "unrelated histories — cannot simulate"}
    r = subprocess.run(
        ["git", "merge-tree", "--write-tree", branch_a, branch_b],
        cwd=str(repo), capture_output=True, text=True,
    )
    if r.returncode == 0:
        return {"ok": True, "conflicts": []}
    conflicts = []
    for line in r.stdout.splitlines():
        if not line.startswith("CONFLICT"):
            continue
        m = re.search(r"Merge conflict in (.+)$", line)
        if not m:
            m = re.search(r"CONFLICT \([^)]+\): (\S+) ", line)
        if m:
            path = m.group(1).strip()
            if path not in conflicts:
                conflicts.append(path)
    if conflicts:
        return {"ok": True, "conflicts": conflicts}
    return {"ok": False, "error": (r.stderr.strip() or r.stdout.strip() or "merge-tree failed")}


def branch_wip_status(worktree_path: str, base_ref: str = "refs/heads/main") -> dict:
    """Report uncommitted files + unmerged commit subjects for a worktree (relative to base_ref).
    Returns {"error": ...} if git status or the base_ref comparison fails — never a false 'clean'."""
    wt = Path(worktree_path).resolve()
    dirty = subprocess.run(
        ["git", "status", "--porcelain"], cwd=str(wt), capture_output=True, text=True,
    )
    if dirty.returncode != 0:
        return {"error": f"git status failed: {dirty.stderr.strip()}"}
    uncommitted = [l[3:] for l in dirty.stdout.strip().splitlines()] if dirty.stdout.strip() else []
    log = subprocess.run(
        ["git", "log", f"{base_ref}..HEAD", "--format=%s"],
        cwd=str(wt), capture_output=True, text=True,
    )
    if log.returncode != 0:
        return {"error": f"base_ref '{base_ref}' not found or comparison failed: {log.stderr.strip()}"}
    unmerged = [l for l in log.stdout.strip().splitlines() if l.strip()]
    return {"uncommitted": uncommitted, "unmerged_commits": unmerged}
