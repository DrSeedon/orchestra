"""V-611: LAYOUT_MISSING repair must target the base checkout, not the worker's worktree.

Reproduces the loop from bug-inbox 20260922T094017 (project seedon, worker seo-cro):
auto-switch branches a worker's worktree off `base_branch`; if that base lacks a migrated
`.orchestra/layout.json`, every fresh branch inherits the same missing state. Repairing the
throwaway worktree branch (as `_repair_command` used to suggest) never touches `base_branch`,
so the very next auto-switch reproduces the identical failure — see commits 86e5291, ccb0a93,
0dfaad4 in the seedon site repo, three repairs landed on three abandoned branches.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app import orchestra_layout as layout


def _git(repository: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repository), *args],
        text=True,
        capture_output=True,
        check=check,
    )


def _init_base_repo(base: Path) -> None:
    (base / "docs/tasks").mkdir(parents=True)
    (base / "docs/tasks/1.md").write_text("old-style task\n", encoding="utf-8")
    _git(base, "init", "-q", "-b", "main")
    _git(base, "config", "user.email", "v611@example.invalid")
    _git(base, "config", "user.name", "v611")
    _git(base, "add", "-A")
    _git(base, "commit", "-qm", "old layout: docs/tasks")


def _add_worktree(base: Path, worktree: Path, branch: str) -> None:
    _git(base, "worktree", "add", "-q", "-b", branch, str(worktree), "main")


def test_repair_hint_points_at_base_checkout_not_worktree(tmp_path: Path):
    base = tmp_path / "base"
    base.mkdir()
    _init_base_repo(base)
    worktree = tmp_path / "worker-wt"
    _add_worktree(base, worktree, "adhoc-1")

    with pytest.raises(layout.LayoutMigrationError) as excinfo:
        layout.require_project_layout(worktree)

    exc = excinfo.value
    assert exc.code == "ORCHESTRA_LAYOUT_MISSING"
    assert exc.repository == base.resolve(), (
        "repair must target the checkout that owns base_branch, not the ephemeral worktree"
    )
    assert str(base.resolve()) in exc.repair_command
    assert str(worktree.resolve()) not in exc.repair_command


def test_repairing_only_the_worktree_reproduces_the_loop(tmp_path: Path):
    """The bug as observed: fixing the throwaway branch does not break the cycle."""
    base = tmp_path / "base"
    base.mkdir()
    _init_base_repo(base)
    worktree_1 = tmp_path / "worker-wt-1"
    _add_worktree(base, worktree_1, "adhoc-1")

    with pytest.raises(layout.LayoutMigrationError):
        layout.require_project_layout(worktree_1)

    # Old, buggy repair target: migrate the worktree's own throwaway branch.
    layout.migrate_project_layout(worktree_1, repair=True)
    assert (worktree_1 / ".orchestra/layout.json").is_file()

    # Next auto-switch: a fresh branch off the still-unmigrated base_branch.
    worktree_2 = tmp_path / "worker-wt-2"
    _add_worktree(base, worktree_2, "adhoc-2")
    with pytest.raises(layout.LayoutMigrationError):
        layout.require_project_layout(worktree_2)


def test_repairing_the_base_checkout_breaks_the_loop(tmp_path: Path):
    base = tmp_path / "base"
    base.mkdir()
    _init_base_repo(base)
    worktree_1 = tmp_path / "worker-wt-1"
    _add_worktree(base, worktree_1, "adhoc-1")

    with pytest.raises(layout.LayoutMigrationError) as excinfo:
        layout.require_project_layout(worktree_1)
    repaired_target = excinfo.value.repository

    layout.migrate_project_layout(repaired_target, repair=True)
    assert (base / ".orchestra/layout.json").is_file()

    # Next auto-switch: a fresh branch off the now-migrated base_branch succeeds.
    worktree_2 = tmp_path / "worker-wt-2"
    _add_worktree(base, worktree_2, "adhoc-2")
    layout.require_project_layout(worktree_2)  # must not raise
