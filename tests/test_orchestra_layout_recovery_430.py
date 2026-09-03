"""Crash-recovery oracles for the #430 layout migration."""

from __future__ import annotations

import json
import shlex
import subprocess
from pathlib import Path

import pytest

from app import orchestra_layout as layout


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        capture_output=True,
        check=check,
    )


def _old_repo(tmp_path: Path, name: str) -> Path:
    repo = tmp_path / name
    (repo / "docs/kb").mkdir(parents=True)
    (repo / "docs/kb/fact.md").write_text("remember me\n", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "task430@example.invalid")
    _git(repo, "config", "user.name", "task430")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "old layout")
    return repo


def _run_repair(error: layout.LayoutMigrationError) -> dict[str, object]:
    command = shlex.split(error.repair_command)
    repaired = subprocess.run(command, text=True, capture_output=True)
    assert repaired.returncode == 0, repaired.stdout + repaired.stderr
    return json.loads(repaired.stdout)


def test_t4_journal_survives_kill_before_commit_and_repair_finishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repo = _old_repo(tmp_path, "journal-window")
    before = _git(repo, "rev-parse", "HEAD").stdout.strip()
    original_run = layout._run

    class SimulatedProcessDeath(BaseException):
        pass

    def die_before_commit(repository: Path, *args: str, **kwargs):
        if "commit" in args and "Orchestra: migrate project state to .orchestra" in args:
            raise SimulatedProcessDeath
        return original_run(repository, *args, **kwargs)

    monkeypatch.setattr(layout, "_run", die_before_commit)
    with pytest.raises(SimulatedProcessDeath):
        layout.migrate_project_layout(repo)
    monkeypatch.setattr(layout, "_run", original_run)

    assert (repo / layout.JOURNAL_FILE).is_file()
    assert _git(repo, "status", "--porcelain").stdout
    assert _git(repo, "rev-parse", "HEAD").stdout.strip() == before

    with pytest.raises(layout.LayoutMigrationError) as retry:
        layout.migrate_project_layout(repo)
    assert retry.value.code == "ORCHESTRA_LAYOUT_PARTIAL"
    result = _run_repair(retry.value)

    assert result["status"] == "repaired"
    assert not (repo / layout.JOURNAL_FILE).exists()
    assert _git(repo, "status", "--porcelain").stdout == ""
    assert _git(repo, "rev-parse", "HEAD").stdout.strip() != before
    assert (repo / ".orchestra/kb/fact.md").read_text(encoding="utf-8") == "remember me\n"


def test_t4_repair_recovers_staged_current_layout_without_journal(tmp_path: Path):
    repo = _old_repo(tmp_path, "legacy-window")
    before = _git(repo, "rev-parse", "HEAD").stdout.strip()
    (repo / ".orchestra").mkdir()
    _git(repo, "mv", "docs/kb", ".orchestra/kb")
    (repo / layout.LAYOUT_FILE).write_text(
        json.dumps(
            {"schema_version": 1, "layout": ".orchestra", "managed_paths": ["kb"]},
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    _git(repo, "add", "-A")

    assert layout._layout_state(repo) == ("current", ["kb"])
    assert not (repo / layout.JOURNAL_FILE).exists()
    assert _git(repo, "status", "--porcelain").stdout

    with pytest.raises(layout.LayoutMigrationError) as retry:
        layout.migrate_project_layout(repo)
    assert retry.value.code == "ORCHESTRA_LAYOUT_PARTIAL"
    result = _run_repair(retry.value)

    assert result["status"] == "repaired"
    assert _git(repo, "status", "--porcelain").stdout == ""
    assert _git(repo, "rev-parse", "HEAD").stdout.strip() != before
    assert (repo / ".orchestra/kb/fact.md").read_text(encoding="utf-8") == "remember me\n"
    assert not (repo / "docs/kb").exists()
