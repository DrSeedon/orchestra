"""Worktree management — create and remove git worktrees for agent sessions."""

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
