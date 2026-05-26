"""Worktree management — create and remove git worktrees for agent sessions."""

import fcntl
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

    for fname in PROJECT_FILES:
        src = repo / fname
        if not src.exists():
            src = repo.parent / fname
        if src.exists():
            shutil.copy2(str(src), str(wt_path / fname))

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


# Алиас для обратной совместимости
_ensure_repo_on_main = _ensure_repo_on_branch


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
                            else:
                                commits_result = subprocess.run(
                                    ["git", "rev-list", "--count", f"{target_branch}..{branch}"],
                                    cwd=str(repo), capture_output=True, text=True,
                                )
                                commits_merged = int(commits_result.stdout.strip() or "0")

                                old_head_result = subprocess.run(
                                    ["git", "rev-parse", "HEAD"],
                                    cwd=str(repo), capture_output=True, text=True,
                                )
                                old_head = old_head_result.stdout.strip() if old_head_result.returncode == 0 else ""

                                merge = subprocess.run(
                                    ["git", "merge", "--no-edit", branch],
                                    cwd=str(repo), capture_output=True, text=True,
                                )
                                if merge.returncode != 0:
                                    # Пытаемся прибрать за собой — best-effort
                                    abort = subprocess.run(
                                        ["git", "merge", "--abort"],
                                        cwd=str(repo), capture_output=True, text=True,
                                    )
                                    # Собираем conflicted files
                                    conflict_files = []
                                    if abort.returncode != 0:
                                        status_out = subprocess.run(
                                            ["git", "diff", "--name-only", "--diff-filter=U"],
                                            cwd=str(repo), capture_output=True, text=True,
                                        )
                                        conflict_files = status_out.stdout.strip().splitlines() if status_out.stdout.strip() else []
                                    err = merge.stderr.strip() or merge.stdout.strip() or f"git merge exit code {merge.returncode}"
                                    logger.error(f"merge_worktree failed: repo={repo} branch={branch} err={err}")
                                    if conflict_files:
                                        result = {"ok": False, "state": "conflict", "conflicts": conflict_files,
                                                  "error": "merge conflict — manual resolution required"}
                                    else:
                                        result = {"ok": False, "error": err}
                                    # НЕ return — управление уйдёт в finally (stash pop + restore HEAD)
                                else:
                                    merged_commits = _parse_merged_commits(str(repo), old_head) if old_head else {}
                                    result = {"ok": True, "commits_merged": commits_merged, "branch": branch, "merged_commits": merged_commits}
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

        m = _TASK_REF_RE.search(message)
        if not m:
            continue
        if m.group(3):
            task_ref = m.group(3)
        else:
            task_ref = f"{m.group(1)}-{m.group(2)}"

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
        by_par.setdefault(task_ref, []).append(commit)

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

    merged = subprocess.run(
        ["git", "merge-base", "--is-ancestor", "HEAD", from_ref],
        cwd=str(wt), capture_output=True, text=True,
    )
    if merged.returncode != 0:
        return {"ok": False, "error": f"current branch has unmerged commits — merge_worker first (relative to {from_ref})"}

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
    result = subprocess.run(
        ["git", "worktree", "remove", str(wt), "--force"],
        cwd=cwd, capture_output=True, text=True,
    )
    if result.returncode != 0:
        logger.warning(f"worktree remove failed: {result.stderr}")
