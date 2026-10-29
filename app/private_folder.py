"""`.orchestra/private/` (V-1014): a plain folder git ignores, shared by all worktrees.

Workers run in separate worktrees, so a real folder in each would die with it. The one real
folder lives in the project's MAIN checkout; every worktree gets a symlink to it.
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

PRIVATE_REL = ".orchestra/private"
# No trailing slash: in a worktree the entry is a symlink, which `private/` would not match.
EXCLUDE_PATTERN = f"/{PRIVATE_REL}"


def has_worker_memory_project_state(base: Path) -> bool:
    """Reports alone do not establish managed memory or require private bootstrap."""
    # LEGACY_PATH_FIXTURE: old roots signal migration, never memory fallbacks.
    if any((base / path).exists() or (base / path).is_symlink() for path in (
        "docs/kb", "docs/tasks", "docs/workers", "docs/archive", "pipelines",
    )):
        return True
    state = base / ".orchestra"
    if not state.exists() and not state.is_symlink():
        return False
    if not state.is_dir() or state.is_symlink():
        return True
    # Unknown entries, migration journals and broken links remain project state.
    return any(
        entry.name != "tasks" or not entry.is_dir() or entry.is_symlink()
        for entry in state.iterdir()
    )


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


def filter_worktree_status(path: str | Path, status: str, *, nul: bool = False) -> str:
    """Remove only the platform's untracked shared-private link from porcelain v1.

    Callers must request --untracked-files=all: a collapsed directory could also contain
    user files. Ignore files are only a convenience; checkout/reset can replace the local
    generated .gitignore with a tracked one. Tracked changes always remain visible.
    Inspection failures leave status untouched (fail closed).
    """
    separator = "\0" if nul else "\n"
    candidate = f"?? {PRIVATE_REL}"
    if candidate not in status.split(separator):
        return status
    wt = Path(path)
    link = wt / PRIVATE_REL
    try:
        if not link.is_symlink():
            return status
        shared = shared_private_dir(wt)
        if (wt.resolve() == shared.parent.parent.resolve()
                or not shared.is_dir() or link.resolve() != shared.resolve()):
            return status
    except (OSError, RuntimeError, subprocess.SubprocessError):
        return status
    records = iter(status.split(separator))
    kept = []
    for record in records:
        if record != candidate:
            kept.append(record)
        # In -z format rename/copy source paths are separate tokens, not status records.
        if nul and ("R" in record[:2] or "C" in record[:2]):
            kept.append(next(records, ""))
    return separator.join(kept)


def _ignore_private(wt: Path) -> None:
    # info/exclude is shared by linked worktrees, but a project's .gitignore
    # (notably !.orchestra/**) wins over it. A deeper ignore file wins in turn.
    try:
        ignored = subprocess.run(
            ["git", "-C", str(wt), "check-ignore", "-q", "--", PRIVATE_REL],
            capture_output=True, text=True,
        )
        if ignored.returncode == 0:
            return
        if ignored.returncode != 1:
            raise RuntimeError(f"private ignore check failed: {ignored.stderr.strip()}")
        ignore = wt / ".orchestra" / ".gitignore"
        tracked = subprocess.run(
            ["git", "-C", str(wt), "ls-files", "--", ".orchestra/.gitignore"],
            capture_output=True, text=True,
        )
        if tracked.returncode:
            raise RuntimeError(f"private ignore tracking check failed: {tracked.stderr.strip()}")
        if tracked.stdout.strip() or ignore.is_symlink():
            raise RuntimeError(f"{ignore} is tracked or a symlink; cannot modify it")
        previous = ignore.read_text() if ignore.exists() else ""
        separator = "\n" if previous and not previous.endswith("\n") else ""
        # The generated file must also stay out of status; keep any existing rules.
        ignore.write_text(previous + separator + "/private\n/.gitignore\n")
    except (OSError, RuntimeError, UnicodeError) as error:
        # Ignore metadata must not roll back an otherwise usable worker worktree.
        logger.warning("Could not exclude %s from Git: %s", wt / PRIVATE_REL, error)


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
    _ignore_private(shared.parent.parent)
    link = wt / PRIVATE_REL
    if wt.resolve() == shared.parent.parent.resolve():
        return shared  # main checkout: the real folder is already here
    if link.is_symlink() and link.resolve() == shared.resolve():
        _ignore_private(wt)  # also repair worktrees created before V-1031
        return shared
    if link.exists() or link.is_symlink():
        if link.is_dir() and not link.is_symlink() and not any(link.iterdir()):
            link.rmdir()
        else:
            return None  # a real folder with content is never replaced
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(shared, target_is_directory=True)
    _ignore_private(wt)
    return shared
