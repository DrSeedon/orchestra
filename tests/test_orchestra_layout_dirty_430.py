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

    repeated = layout.migrate_project_layout_preserving_dirty(repository)
    assert repeated["status"] == "already_current"
    assert _sha(repository / ".orchestra/kb/modified.md") == before_hashes["modified"]
    assert _git(repository, "stash", "list").stdout == ""


def test_restore_content_mismatch_keeps_the_preserved_stash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repository = tmp_path / "truncated"
    (repository / "docs/kb").mkdir(parents=True)
    (repository / "docs/kb/fact.md").write_text("BASE\n", encoding="utf-8")
    _git(repository, "init", "-q")
    _git(repository, "config", "user.email", "task629@example.invalid")
    _git(repository, "config", "user.name", "task629")
    _git(repository, "add", "-A")
    _git(repository, "commit", "-qm", "old layout")
    saved = b"complete user content\n"
    (repository / "docs/kb/fact.md").write_bytes(saved)

    original_restore = layout._restore_preserved_stash

    def restore_then_truncate(*args, **kwargs):
        original_restore(*args, **kwargs)
        (repository / ".orchestra/kb/fact.md").write_bytes(b"")

    monkeypatch.setattr(layout, "_restore_preserved_stash", restore_then_truncate)
    with pytest.raises(layout.LayoutMigrationError, match="preserved content changed"):
        layout.migrate_project_layout_preserving_dirty(repository)

    stash_lines = _git(repository, "stash", "list", "--format=%H").stdout.splitlines()
    assert len(stash_lines) == 1
    assert _git(repository, "show", f"{stash_lines[0]}:docs/kb/fact.md").stdout == (
        saved.decode()
    )
    assert (repository / ".orchestra/kb/fact.md").read_bytes() == b""
    assert layout._preserve_journal_path(repository).is_file()


def test_clean_mixed_layout_is_repaired_without_a_preserve_stash(tmp_path: Path):
    repository = tmp_path / "mixed-clean"
    for name in ("kb", "tasks", "workers"):
        (repository / "docs" / name).mkdir(parents=True)
        (repository / "docs" / name / f"{name}.md").write_text(name, encoding="utf-8")
    _git(repository, "init", "-q")
    _git(repository, "config", "user.email", "task629@example.invalid")
    _git(repository, "config", "user.name", "task629")
    _git(repository, "add", "-A")
    _git(repository, "commit", "-qm", "old layout")
    (repository / ".orchestra").mkdir()
    _git(repository, "mv", "docs/tasks", ".orchestra/tasks")
    _git(repository, "mv", "docs/workers", ".orchestra/workers")
    (repository / ".orchestra/layout.json").write_text(
        '{"schema_version":1,"layout":".orchestra",'
        '"managed_paths":["kb","tasks","workers"]}\n',
        encoding="utf-8",
    )
    _git(repository, "add", "-A")
    _git(repository, "commit", "-qm", "partial layout")

    result = layout.migrate_project_layout_preserving_dirty(repository)

    assert result["status"] == "repaired"
    assert (repository / ".orchestra/kb/kb.md").read_text(encoding="utf-8") == "kb"
    assert not (repository / "docs/kb").exists()
    assert _git(repository, "status", "--porcelain").stdout == ""
    assert _git(repository, "stash", "list").stdout == ""


def test_failed_restore_write_leaves_the_existing_file_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repository = tmp_path / "atomic-write"
    (repository / "docs/kb").mkdir(parents=True)
    destination = repository / "docs/kb/fact.md"
    destination.write_bytes(b"saved bytes")
    _git(repository, "init", "-q")
    _git(repository, "config", "user.email", "task629@example.invalid")
    _git(repository, "config", "user.name", "task629")
    _git(repository, "add", "-A")
    _git(repository, "commit", "-qm", "old layout")
    destination.write_bytes(b"live bytes")
    saved_entry = layout._tree_entry(repository, "HEAD", "docs/kb/fact.md")
    assert saved_entry is not None
    original_write_bytes = Path.write_bytes

    def fail_temp_write(path: Path, content: bytes) -> int:
        if path.name.startswith(".fact.md.") and path.name.endswith(".tmp"):
            original_write_bytes(path, b"")
            raise OSError("simulated interrupted write")
        return original_write_bytes(path, content)

    monkeypatch.setattr(Path, "write_bytes", fail_temp_write)
    with pytest.raises(OSError, match="simulated interrupted write"):
        layout._write_worktree_entry(repository, "docs/kb/fact.md", saved_entry)

    assert destination.read_bytes() == b"live bytes"
    assert not list(destination.parent.glob(".fact.md.*.tmp"))


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


def test_current_dirty_layout_skips_repeated_stash_transactions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repository = tmp_path / "current-dirty"
    (repository / "docs/kb").mkdir(parents=True)
    for name, content in (
        ("modified.md", "BASE\n"),
        ("deleted.md", "DELETE ME\n"),
        ("clean.md", "CLEAN\n"),
    ):
        (repository / "docs/kb" / name).write_text(content, encoding="utf-8")
    _git(repository, "init", "-q")
    _git(repository, "config", "user.email", "task629@example.invalid")
    _git(repository, "config", "user.name", "task629")
    _git(repository, "add", "-A")
    _git(repository, "commit", "-qm", "old layout")

    (repository / "docs/kb/modified.md").write_text("DIRTY BYTES\n", encoding="utf-8")
    (repository / "docs/kb/new.md").write_text("UNTRACKED BYTES\n", encoding="utf-8")
    (repository / "docs/kb/deleted.md").unlink()
    initial = layout.migrate_project_layout_preserving_dirty(repository)
    assert initial["status"] == "migrated"
    expected = {
        "modified": _sha(repository / ".orchestra/kb/modified.md"),
        "untracked": _sha(repository / ".orchestra/kb/new.md"),
        "deleted": _sha(repository / ".orchestra/kb/deleted.md"),
    }
    stash_before = _git(repository, "stash", "list", "--format=%H").stdout.splitlines()
    stash_operations: list[str] = []
    original_run = layout._run

    def count_stash_commands(repo: Path, *args: str, **kwargs):
        if args[:1] == ("stash",):
            stash_operations.append(" ".join(args[:2]))
        return original_run(repo, *args, **kwargs)

    monkeypatch.setattr(layout, "_run", count_stash_commands)
    for _ in range(3):
        result = layout.migrate_project_layout_preserving_dirty(repository)
        assert result["status"] == "already_current"
        assert _git(repository, "stash", "list", "--format=%H").stdout.splitlines() == stash_before
        assert {
            "modified": _sha(repository / ".orchestra/kb/modified.md"),
            "untracked": _sha(repository / ".orchestra/kb/new.md"),
            "deleted": _sha(repository / ".orchestra/kb/deleted.md"),
        } == expected

    assert stash_operations == []
