"""Stage-1 compatibility while fleet projects migrate at different times."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


def _git(repository: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repository), *args],
        text=True,
        capture_output=True,
        check=True,
    )


def _repository(tmp_path: Path, name: str, state: str) -> Path:
    repository = tmp_path / name
    repository.mkdir()
    _git(repository, "init", "-q")
    _git(repository, "config", "user.email", "task430@example.invalid")
    _git(repository, "config", "user.name", "task430")
    if state == "old":
        (repository / "docs/kb").mkdir(parents=True)
        (repository / "docs/workers").mkdir(parents=True)
        (repository / "docs/kb/README.md").write_text("# old\n", encoding="utf-8")
        (repository / f"docs/workers/{name}.md").write_text(
            "OLD PERSONAL MEMORY\n", encoding="utf-8"
        )
    elif state == "partial":
        (repository / ".orchestra/kb").mkdir(parents=True)
        (repository / "docs/workers").mkdir(parents=True)
        (repository / ".orchestra/kb/README.md").write_text(
            "# partial\n", encoding="utf-8"
        )
        (repository / f"docs/workers/{name}.md").write_text(
            "PARTIAL PERSONAL MEMORY\n", encoding="utf-8"
        )
    elif state == "migrated":
        (repository / ".orchestra/kb").mkdir(parents=True)
        (repository / ".orchestra/workers").mkdir(parents=True)
        (repository / ".orchestra/layout.json").write_text(
            '{"layout":".orchestra","managed_paths":["kb","workers"],"schema_version":1}\n',
            encoding="utf-8",
        )
        (repository / ".orchestra/kb/README.md").write_text(
            "# migrated\n", encoding="utf-8"
        )
        (repository / f".orchestra/workers/{name}.md").write_text(
            "NEW PERSONAL MEMORY\n", encoding="utf-8"
        )
    else:
        raise AssertionError(state)
    _git(repository, "add", "-A")
    _git(repository, "commit", "-qm", state)
    return repository


@pytest.mark.asyncio
async def test_t4_only_migrated_layout_creates_session_after_fleet_cutover(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from app import db
    from app.manager import SessionManager

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "sessions.db")
    db.init_db()
    manager = SessionManager()
    from app.orchestra_layout import LayoutMigrationError

    for state in ("old", "partial"):
        name = f"{state}-agent"
        repository = _repository(tmp_path, name, state)
        with pytest.raises(LayoutMigrationError, match="ORCHESTRA_LAYOUT_MISSING.*--repair"):
            await manager.create_session(
                name=name,
                scope=str(repository),
                cwd=str(repository),
                model="claude-opus-5[1m]",
                role="orchestrator",
                planned_initial_turn=False,
            )

    name = "migrated-agent"
    repository = _repository(tmp_path, name, "migrated")
    session = await manager.create_session(
        name=name,
        scope=str(repository),
        cwd=str(repository),
        model="claude-opus-5[1m]",
        role="orchestrator",
        planned_initial_turn=False,
    )
    assert "NEW PERSONAL MEMORY" in session.system_prompt
    assert manager.get_by_name(name, str(repository)) is session
    assert len(manager.sessions) == 1
    assert len(db.get_all_sessions()) == 1
