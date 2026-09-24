"""V-635: a worker worktree left in the old layout catches up when the worker is raised.

V-634 found 22 worker worktrees whose branch predated their base checkout's migration; each
failed with ORCHESTRA_LAYOUT_MISSING until migrated by hand. `refresh_worker_memory` is the
call resume, auto-switch and the first message all go through, so it is exercised directly.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app import orchestra_layout as layout
from app.prompting import refresh_worker_memory


def _git(repository: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repository), *args], text=True, capture_output=True, check=True,
    ).stdout


def _commit_count(repository: Path) -> int:
    return int(_git(repository, "rev-list", "--count", "HEAD").strip())


def _old_base(tmp_path: Path) -> Path:
    base = tmp_path / "base"
    (base / "docs/tasks").mkdir(parents=True)
    (base / "docs/tasks/1.md").write_text("task\n", encoding="utf-8")
    (base / "docs/workers").mkdir(parents=True)
    (base / "docs/workers/w.md").write_text("remember this\n", encoding="utf-8")
    _git(base, "init", "-q", "-b", "main")
    _git(base, "config", "user.email", "v635@example.invalid")
    _git(base, "config", "user.name", "v635")
    _git(base, "add", "-A")
    _git(base, "commit", "-qm", "old layout")
    _git(base, "branch", "old-worker")
    return base


def _raise_worker(base: Path, worktree: Path) -> str:
    return refresh_worker_memory(
        "prompt", "w", "worker", str(base), str(worktree), allow_absent_project=True,
    )


@pytest.fixture
def repos(tmp_path: Path) -> tuple[Path, Path]:
    base = _old_base(tmp_path)
    layout.migrate_project_layout(base)
    worktree = tmp_path / "wt"
    _git(base, "worktree", "add", "-q", str(worktree), "old-worker")
    return base, worktree


def test_clean_old_worktree_is_migrated_with_a_commit(repos):
    base, worktree = repos
    head_before = _git(worktree, "rev-parse", "HEAD").strip()

    prompt = _raise_worker(base, worktree)

    layout.require_project_layout(worktree)
    assert not (worktree / "docs/tasks").exists()
    assert (worktree / ".orchestra/tasks/1.md").read_text(encoding="utf-8") == "task\n"
    assert _git(worktree, "rev-parse", "HEAD~1").strip() == head_before
    assert _git(worktree, "log", "-1", "--format=%s").strip() == (
        "Orchestra: migrate project state to .orchestra"
    )
    assert _git(worktree, "rev-parse", "--abbrev-ref", "HEAD").strip() == "old-worker"
    assert _git(worktree, "status", "--porcelain") == ""
    assert "remember this" in prompt


def test_dirty_old_worktree_is_refused_and_left_untouched(repos):
    base, worktree = repos
    (worktree / "docs/tasks/1.md").write_text("edited\n", encoding="utf-8")
    (worktree / "notes.txt").write_text("untracked\n", encoding="utf-8")
    head_before = _git(worktree, "rev-parse", "HEAD").strip()
    status_before = _git(worktree, "status", "--porcelain")
    stashes_before = _git(base, "stash", "list")

    with pytest.raises(layout.LayoutMigrationError) as excinfo:
        _raise_worker(base, worktree)

    error = excinfo.value
    assert error.code == "ORCHESTRA_LAYOUT_DIRTY"
    assert error.repository == worktree.resolve()
    assert str(worktree.resolve()) in str(error)
    assert str(worktree.resolve()) in error.repair_command
    assert _git(worktree, "rev-parse", "HEAD").strip() == head_before
    assert _git(worktree, "status", "--porcelain") == status_before
    assert _git(base, "stash", "list") == stashes_before
    assert (worktree / "docs/tasks/1.md").read_text(encoding="utf-8") == "edited\n"
    assert not (worktree / ".orchestra").exists()


def test_the_dirty_error_command_fixes_the_worktree(repos):
    base, worktree = repos
    (worktree / "docs/tasks/1.md").write_text("edited\n", encoding="utf-8")
    with pytest.raises(layout.LayoutMigrationError) as excinfo:
        _raise_worker(base, worktree)

    subprocess.run(
        excinfo.value.repair_command, shell=True, check=True, capture_output=True,
        cwd=Path(__file__).resolve().parents[1],
    )

    layout.require_project_layout(worktree)
    assert (worktree / ".orchestra/tasks/1.md").read_text(encoding="utf-8") == "edited\n"


def test_current_worktree_is_not_touched(tmp_path: Path):
    base = _old_base(tmp_path)
    layout.migrate_project_layout(base)
    worktree = tmp_path / "wt"
    _git(base, "worktree", "add", "-q", "-b", "fresh", str(worktree), "main")
    count_before = _commit_count(worktree)

    _raise_worker(base, worktree)

    assert _commit_count(worktree) == count_before
    assert _git(worktree, "status", "--porcelain") == ""


def test_old_base_is_left_to_the_v611_error(tmp_path: Path):
    """Migrating a branch off an old base is throwaway work (V-611); the base is named."""
    base = _old_base(tmp_path)
    worktree = tmp_path / "wt"
    _git(base, "worktree", "add", "-q", str(worktree), "old-worker")
    count_before = _commit_count(worktree)

    with pytest.raises(layout.LayoutMigrationError) as excinfo:
        _raise_worker(base, worktree)

    assert excinfo.value.code == "ORCHESTRA_LAYOUT_MISSING"
    assert excinfo.value.repository == base.resolve()
    assert _commit_count(worktree) == count_before
    assert (worktree / "docs/tasks").is_dir()
