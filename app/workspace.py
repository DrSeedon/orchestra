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


def create_worktree(repo_path: str, name: str, scope: str, task_id: str | None = None) -> Worktree:
    repo = Path(repo_path).resolve()
    if not repo.is_dir():
        raise ValueError(f"repo_path does not exist: {repo_path}")

    scope_slug = _slugify(scope)
    wt_dir = WORKTREE_ROOT / scope_slug
    wt_dir.mkdir(parents=True, exist_ok=True)
    wt_path = wt_dir / name
    if task_id:
        par_label = task_id.upper() if task_id.upper().startswith("PAR-") else f"PAR-{task_id}"
        branch = f"feat/{par_label}-{name}"
    else:
        branch = f"feat/{scope_slug}/{name}"

    if wt_path.exists():
        raise ValueError(f"worktree already exists: {wt_path}. Remove session first.")

    result = subprocess.run(
        ["git", "worktree", "add", str(wt_path), "-b", branch],
        cwd=str(repo), capture_output=True, text=True,
    )
    if result.returncode != 0:
        subprocess.run(["git", "branch", "-D", branch], cwd=str(repo), capture_output=True)
        result = subprocess.run(
            ["git", "worktree", "add", str(wt_path), "-b", branch],
            cwd=str(repo), capture_output=True, text=True,
        )
        if result.returncode != 0:
            result = subprocess.run(
                ["git", "worktree", "add", str(wt_path), branch],
                cwd=str(repo), capture_output=True, text=True,
            )
            if result.returncode != 0:
                raise RuntimeError(f"git worktree add failed: {result.stderr}")

    for fname in PROJECT_FILES:
        src = repo / fname
        if not src.exists():
            src = repo.parent / fname
        if src.exists():
            shutil.copy2(str(src), str(wt_path / fname))

    return Worktree(path=str(wt_path), branch=branch)


def merge_worktree_to_main(worktree_path: str, repo_path: str, task_id: str | None = None) -> dict:
    wt = Path(worktree_path).resolve()
    git_common = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"],
        cwd=str(wt), capture_output=True, text=True,
    )
    if git_common.returncode == 0:
        git_dir = Path(git_common.stdout.strip())
        if not git_dir.is_absolute():
            git_dir = (wt / git_dir).resolve()
        repo = git_dir.parent
    else:
        repo = Path(repo_path).resolve()
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
                commit = subprocess.run(
                    ["git", "add", "-A"],
                    cwd=str(wt), capture_output=True, text=True,
                )
                if commit.returncode == 0:
                    subprocess.run(
                        ["git", "commit", "-m", f"auto-save: {branch}"],
                        cwd=str(wt), capture_output=True, text=True,
                    )

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

            if old_head and task_id:
                all_commits = _collect_commits(str(repo), old_head)
                par_num = int(task_id.upper().replace("PAR-", ""))
                merged_commits = {par_num: all_commits} if all_commits else {}
            elif old_head:
                merged_commits = _parse_merged_commits(str(repo), old_head)
            else:
                merged_commits = {}
            return {"ok": True, "commits_merged": commits_merged, "branch": branch, "merged_commits": merged_commits}
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)


_PAR_RE = re.compile(r"\bPAR-(\d+)\b", re.IGNORECASE)


def _collect_commits(repo: str, old_head: str) -> list[dict]:
    log = subprocess.run(
        ["git", "log", f"{old_head}..HEAD", "--format=%H%x00%s%x00%ad", "--date=short"],
        cwd=repo, capture_output=True, text=True,
    )
    if log.returncode != 0 or not log.stdout.strip():
        return []

    commits = []
    for line in log.stdout.strip().splitlines():
        parts = line.split("\x00", 2)
        if len(parts) < 3:
            continue
        full_hash, message, date = parts

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

        commits.append({
            "hash": full_hash[:7],
            "message": message,
            "date": date,
            "files": files_changed,
            "insertions": insertions,
            "deletions": deletions,
        })
    return commits


def _parse_merged_commits(repo: str, old_head: str) -> dict[int, list[dict]]:
    by_par: dict[int, list[dict]] = {}
    for commit in _collect_commits(repo, old_head):
        m = _PAR_RE.search(commit["message"])
        if m:
            by_par.setdefault(int(m.group(1)), []).append(commit)
    return by_par


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
