"""Dirty-worktree preservation for the forced #430 fleet migration."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

from app import orchestra_layout as layout


def _git(
    repository: Path, *args: str, check: bool = True
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repository), *args],
        text=True,
        capture_output=True,
        check=check,
    )


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "MISSING"


def test_t4_forced_dirty_migration_preserves_bytes_status_and_commit_scope(tmp_path: Path):
    assert hasattr(layout, "migrate_project_layout_preserving_dirty"), (
        "forced fleet migration must preserve dirty work instead of refusing it"
    )
    repository = tmp_path / "dirty"
    (repository / "docs/kb").mkdir(parents=True)
    (repository / "docs/kb/modified.md").write_text("BASE MODIFIED\n", encoding="utf-8")
    (repository / "docs/kb/deleted.md").write_text("BASE DELETED\n", encoding="utf-8")
    (repository / "docs/kb/clean.md").write_text("CLEAN\n", encoding="utf-8")
    _git(repository, "init", "-q")
    _git(repository, "config", "user.email", "task430@example.invalid")
    _git(repository, "config", "user.name", "task430")
    _git(repository, "add", "-A")
    _git(repository, "commit", "-qm", "old layout")

    (repository / "docs/kb/modified.md").write_text(
        "USER MODIFIED BYTES\n", encoding="utf-8"
    )
    (repository / "docs/kb/new.md").write_text(
        "USER UNTRACKED BYTES\n", encoding="utf-8"
    )
    (repository / "docs/kb/deleted.md").unlink()
    before_status = _git(repository, "status", "--short").stdout.splitlines()
    before_hashes = {
        "modified": _sha(repository / "docs/kb/modified.md"),
        "untracked": _sha(repository / "docs/kb/new.md"),
        "deleted": _sha(repository / "docs/kb/deleted.md"),
    }

    result = layout.migrate_project_layout_preserving_dirty(repository)

    after_status = _git(repository, "status", "--short").stdout.splitlines()
    after_hashes = {
        "modified": _sha(repository / ".orchestra/kb/modified.md"),
        "untracked": _sha(repository / ".orchestra/kb/new.md"),
        "deleted": _sha(repository / ".orchestra/kb/deleted.md"),
    }
    assert result["status"] == "migrated"
    assert before_hashes == after_hashes
    assert before_status == [
        " D docs/kb/deleted.md",
        " M docs/kb/modified.md",
        "?? docs/kb/new.md",
    ]
    assert after_status == [
        " D .orchestra/kb/deleted.md",
        " M .orchestra/kb/modified.md",
        "?? .orchestra/kb/new.md",
    ]
    assert result["dirty_status_before"] == before_status
    assert result["dirty_status_after"] == after_status

    assert _git(repository, "show", "HEAD:.orchestra/kb/modified.md").stdout == (
        "BASE MODIFIED\n"
    )
    assert _git(repository, "show", "HEAD:.orchestra/kb/deleted.md").stdout == (
        "BASE DELETED\n"
    )
    assert _git(
        repository, "cat-file", "-e", "HEAD:.orchestra/kb/new.md", check=False
    ).returncode != 0
    stat = _git(repository, "show", "--stat", "--oneline", "HEAD").stdout
    assert "docs => .orchestra" in stat
    assert "new.md" not in stat
    assert _git(repository, "rev-list", "--count", "HEAD").stdout.strip() == "2"
    assert _git(repository, "stash", "list").stdout == ""
    assert not layout._preserve_journal_path(repository).exists()


def test_t4_interrupted_dirty_restore_recovers_from_preserved_stash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repository = tmp_path / "interrupted"
    (repository / "docs/kb").mkdir(parents=True)
    (repository / "docs/kb/fact.md").write_text("BASE\n", encoding="utf-8")
    _git(repository, "init", "-q")
    _git(repository, "config", "user.email", "task430@example.invalid")
    _git(repository, "config", "user.name", "task430")
    _git(repository, "add", "-A")
    _git(repository, "commit", "-qm", "old layout")
    (repository / "docs/kb/fact.md").write_text("USER BYTES\n", encoding="utf-8")
    before_hash = _sha(repository / "docs/kb/fact.md")
    original_restore = layout._restore_preserved_stash

    class SimulatedProcessDeath(BaseException):
        pass

    def die_before_restore(*args, **kwargs):
        raise SimulatedProcessDeath

    monkeypatch.setattr(layout, "_restore_preserved_stash", die_before_restore)
    with pytest.raises(SimulatedProcessDeath):
        layout.migrate_project_layout_preserving_dirty(repository)
    monkeypatch.setattr(layout, "_restore_preserved_stash", original_restore)

    assert layout._preserve_journal_path(repository).is_file()
    assert _git(repository, "stash", "list").stdout
    assert (repository / ".orchestra/layout.json").is_file()
    recovered = layout.migrate_project_layout_preserving_dirty(repository)

    assert recovered["dirty_preserved"] is True
    assert _sha(repository / ".orchestra/kb/fact.md") == before_hash
    assert _git(repository, "status", "--short").stdout.splitlines() == [
        " M .orchestra/kb/fact.md"
    ]
    assert _git(repository, "stash", "list").stdout == ""
    assert not layout._preserve_journal_path(repository).exists()
