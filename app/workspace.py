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


def create_worktree(repo_path: str, name: str, scope: str) -> Worktree:
    repo = Path(repo_path).resolve()
    if not repo.is_dir():
        raise ValueError(f"repo_path does not exist: {repo_path}")

    scope_slug = _slugify(scope)
    wt_dir = WORKTREE_ROOT / scope_slug
    wt_dir.mkdir(parents=True, exist_ok=True)
    wt_path = wt_dir / name
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


def merge_worktree_to_main(worktree_path: str, repo_path: str) -> dict:
    repo = Path(repo_path).resolve()
    wt = Path(worktree_path).resolve()
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

            merge = subprocess.run(
                ["git", "merge", "--no-edit", branch],
                cwd=str(repo), capture_output=True, text=True,
            )
            if merge.returncode != 0:
                err = merge.stderr.strip() or merge.stdout.strip() or f"git merge exit code {merge.returncode}"
                logger.error(f"merge_worktree failed: repo={repo} branch={branch} err={err}")
                return {"ok": False, "error": err}

            return {"ok": True, "commits_merged": commits_merged, "branch": branch}
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
