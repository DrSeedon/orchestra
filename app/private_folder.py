"""`.orchestra/private/` (V-1014): a plain folder git ignores, shared by all worktrees.

Workers run in separate worktrees, so a real folder in each would die with it. The one real
folder lives in the project's MAIN checkout; every worktree gets a symlink to it.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

PRIVATE_REL = ".orchestra/private"
# No trailing slash: in a worktree the entry is a symlink, which `private/` would not match.
EXCLUDE_PATTERN = f"/{PRIVATE_REL}"


def main_checkout(path: str | Path) -> Path:
    done = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--path-format=absolute", "--git-common-dir"],
        capture_output=True, text=True,
    )
    if done.returncode:
        raise RuntimeError(f"git-common-dir failed in {path}: {done.stderr.strip()}")
    return Path(done.stdout.strip()).parent


def shared_private_dir(path: str | Path) -> Path:
    """The single real folder for the project that owns `path` (main checkout or worktree)."""
    return main_checkout(path) / PRIVATE_REL


def ensure_private(wt_path: str | Path) -> Path | None:
    """Create the shared folder and link it into the worktree; None if the repo tracks it or has no `.orchestra/`.

    A tracked `.orchestra/private` belongs to the repo — never shadowed or ignored.
    """
    wt = Path(wt_path)
    tracked = subprocess.run(
        ["git", "-C", str(wt), "ls-files", "--", PRIVATE_REL], capture_output=True, text=True,
    )
    if tracked.returncode or tracked.stdout.strip():
        return None
    shared = shared_private_dir(wt)
    if not shared.parent.is_dir():
        return None  # no `.orchestra/` in the project: creating one would mark it Orchestra-managed
    shared.mkdir(parents=True, exist_ok=True)
    link = wt / PRIVATE_REL
    if wt.resolve() == shared.parent.parent.resolve():
        return shared  # main checkout: the real folder is already here
    if link.is_symlink() and link.resolve() == shared.resolve():
        return shared
    if link.exists() or link.is_symlink():
        if link.is_dir() and not link.is_symlink() and not any(link.iterdir()):
            link.rmdir()
        else:
            return None  # a real folder with content is never replaced
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(shared, target_is_directory=True)
    return shared
