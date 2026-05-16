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
PROJECT_FILES = ("CLAUDE.md", ".worktreeinclude")


@dataclass
class Worktree:
    path: str
    branch: str


def _slugify(s: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]", "-", s).strip("-")
    slug = re.sub(r"-+", "-", slug)
    return slug.lower()[:80]


_TASK_ID_RE = re.compile(r"^(?:PAR-)?(\d+)$", re.IGNORECASE)


def _normalize_task_id(task_id: str) -> str:
    m = _TASK_ID_RE.match(task_id.strip())
    if not m:
        raise ValueError(f"Invalid task_id '{task_id}': expected PAR-N or N")
    n = int(m.group(1))
    if n < 1:
        raise ValueError(f"Invalid task_id '{task_id}': PAR number must be >= 1")
    return f"PAR-{n}"


def create_worktree(repo_path: str, name: str, scope: str, task_id: str = "") -> Worktree:
    repo = Path(repo_path).resolve()
    if not repo.is_dir():
        raise ValueError(f"repo_path does not exist: {repo_path}")

    scope_slug = _slugify(scope)
    wt_dir = WORKTREE_ROOT / scope_slug
    wt_dir.mkdir(parents=True, exist_ok=True)
    wt_path = wt_dir / name

    if task_id:
        par = _normalize_task_id(task_id)
        branch = f"{par}/{name}"
    else:
        branch = f"feat/{scope_slug}/{name}"

    if wt_path.exists():
        raise ValueError(f"worktree already exists: {wt_path}. Remove session first.")

    ref_check = subprocess.run(
        ["git", "show-ref", "--verify", f"refs/heads/{branch}"],
        cwd=str(repo), capture_output=True, text=True,
    )
    if ref_check.returncode == 0:
        raise ValueError(f"Branch '{branch}' already exists. Use a different name or clean up.")

    fmt_check = subprocess.run(
        ["git", "check-ref-format", "--branch", branch],
        cwd=str(repo), capture_output=True, text=True,
    )
    if fmt_check.returncode != 0:
        raise ValueError(f"Invalid branch name '{branch}': {fmt_check.stderr.strip()}")

    result = subprocess.run(
        ["git", "worktree", "add", str(wt_path), "-b", branch, "main"],
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


def _ensure_repo_on_main(repo: str) -> str | None:
    repo_status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True,
    )
    if repo_status.stdout.strip():
        return "main repo has uncommitted changes"
    head = subprocess.run(
        ["git", "symbolic-ref", "--short", "HEAD"], cwd=repo, capture_output=True, text=True,
    )
    if head.returncode != 0 or head.stdout.strip() != "main":
        checkout = subprocess.run(
            ["git", "checkout", "main"], cwd=repo, capture_output=True, text=True,
        )
        if checkout.returncode != 0:
            return f"cannot checkout main in repo: {checkout.stderr.strip()}"
    return None


def merge_worktree_to_main(worktree_path: str, repo_path: str) -> dict:
    wt = Path(worktree_path).resolve()
    repo = _resolve_repo(str(wt), repo_path)
    lock_path = repo / ".git" / "orchestra-merge.lock"

    with open(lock_path, "w") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        try:
            branch_result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=str(wt), capture_output=True, text=True,
            )
            if branch_result.returncode != 0:
                return {"ok": False, "error": f"cannot get branch: {branch_result.stderr.strip()}"}
            branch = branch_result.stdout.strip()

            status = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=str(wt), capture_output=True, text=True,
            )
            if status.stdout.strip():
                return {"ok": False, "error": "dirty working tree — commit or discard changes first"}

            main_err = _ensure_repo_on_main(str(repo))
            if main_err:
                return {"ok": False, "error": main_err}

            precheck = subprocess.run(
                ["git", "merge-tree", "--write-tree", "main", branch],
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
                    return {"ok": False, "error": f"merge precheck failed: {err}"}
                return {"ok": False, "conflicts": conflict_files}

            commits_result = subprocess.run(
                ["git", "rev-list", "--count", f"main..{branch}"],
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
                err = merge.stderr.strip() or merge.stdout.strip() or f"git merge exit code {merge.returncode}"
                logger.error(f"merge_worktree failed: repo={repo} branch={branch} err={err}")
                return {"ok": False, "error": err}

            merged_commits = _parse_merged_commits(str(repo), old_head) if old_head else {}
            return {"ok": True, "commits_merged": commits_merged, "branch": branch, "merged_commits": merged_commits}
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)


_TASK_REF_RE = re.compile(r"\b([A-Z]{2,5})-(\d+)\b")


def _parse_merged_commits(repo: str, old_head: str) -> dict[int, list[dict]]:
    log = subprocess.run(
        ["git", "log", f"{old_head}..HEAD", "--format=%H%x00%s%x00%ad", "--date=short"],
        cwd=repo, capture_output=True, text=True,
    )
    if log.returncode != 0 or not log.stdout.strip():
        return {}

    by_par: dict[int, list[dict]] = {}
    for line in log.stdout.strip().splitlines():
        parts = line.split("\x00", 2)
        if len(parts) < 3:
            continue
        full_hash, message, date = parts
        short_hash = full_hash[:7]

        m = _TASK_REF_RE.search(message)
        if not m:
            continue
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
        ["git", "merge-base", "--is-ancestor", "HEAD", "refs/heads/main"],
        cwd=str(wt), capture_output=True, text=True,
    )
    if merged.returncode != 0:
        return {"ok": False, "error": "current branch has unmerged commits — merge_worker first"}

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
                    ["git", "merge", "refs/heads/main", "--no-edit"],
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
                            "error": "merge conflict with main — resolve or abort"}
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
