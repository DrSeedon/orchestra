"""Focused fleet/VPS coverage for the #430 migration engine."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from app import db
from app import orchestra_layout as layout


class _Connection:
    def __init__(self, rows):
        self.rows = rows
        self.sql = ""

    def execute(self, sql):
        self.sql = sql
        return self

    def fetchall(self):
        return self.rows


def test_vps_startup_wrapper_reads_every_registered_canonical_scope(monkeypatch, tmp_path: Path):
    rows = [
        {"id": "orchestra", "scope": str(tmp_path / "orchestra")},
        {"id": "cog", "scope": str(tmp_path / "cog")},
        {"id": "comfy", "scope": str(tmp_path / "comfy")},
    ]
    connection = _Connection(rows)

    @contextmanager
    def fake_connection():
        yield connection

    observed = {}
    options = {}

    def fake_migrate(project_roots, *, preserve_dirty=False, live_session_ids=None):
        observed.update(project_roots)
        options["preserve_dirty"] = preserve_dirty
        return {name: {"status": "migrated"} for name in project_roots}

    monkeypatch.setattr(db, "_conn", fake_connection)
    monkeypatch.setattr(layout, "migrate_registered_projects", fake_migrate)

    result = layout.migrate_registered_project_layouts()

    assert set(result) == {"orchestra", "cog", "comfy"}
    assert observed == {
        "orchestra": tmp_path / "orchestra",
        "cog": tmp_path / "cog",
        "comfy": tmp_path / "comfy",
    }
    assert options == {"preserve_dirty": True}
    assert "FROM tm_projects" in connection.sql
    assert "scope IS NOT NULL" in connection.sql


def test_fleet_failure_does_not_stop_later_project(monkeypatch, tmp_path: Path):
    calls = []

    def fake_one(repository, *, repair=False, live_session_ids=None):
        calls.append(repository.name)
        if repository.name == "broken":
            raise layout.LayoutMigrationError("ORCHESTRA_LAYOUT_DIRTY", repository, "dirty")
        return {"status": "migrated", "repository": str(repository)}

    monkeypatch.setattr(layout, "migrate_project_layout", fake_one)
    (tmp_path / "broken").mkdir()
    (tmp_path / "healthy").mkdir()
    result = layout.migrate_registered_projects(
        {
            "a-broken": tmp_path / "broken",
            "b-healthy": tmp_path / "healthy",
        }
    )

    assert calls == ["broken", "healthy"]
    assert result["a-broken"]["status"] == "failed"
    assert result["a-broken"]["code"] == "ORCHESTRA_LAYOUT_DIRTY"
    assert result["b-healthy"]["status"] == "migrated"


def test_fleet_isolates_a_raw_git_failure_from_a_broken_checkout(monkeypatch, tmp_path: Path):
    """Boot loop of 15.09.2026: one empty object killed every Orchestra startup.

    `_run_bytes` raises a bare RuntimeError, not LayoutMigrationError, so the
    preserve-dirty recovery escaped the per-project guard and took the lifespan
    down with it — 849 restarts over a repository Orchestra does not even own.
    """
    calls = []

    def fake_one(repository, live_session_ids=None):
        calls.append(repository.name)
        if repository.name == "broken":
            raise RuntimeError(
                "git diff --name-only -z --no-renames HEAD stash^2 failed: "
                "error: object file .git/objects/4f/25fc30 is empty"
            )
        return {"status": "migrated", "repository": str(repository)}

    monkeypatch.setattr(layout, "migrate_project_layout_preserving_dirty", fake_one)
    (tmp_path / "broken").mkdir()
    (tmp_path / "healthy").mkdir()
    result = layout.migrate_registered_projects(
        {
            "a-broken": tmp_path / "broken",
            "b-healthy": tmp_path / "healthy",
        },
        preserve_dirty=True,
    )

    assert calls == ["broken", "healthy"]
    assert result["a-broken"]["status"] == "failed"
    assert result["a-broken"]["code"] == "ORCHESTRA_LAYOUT_GIT_ERROR"
    assert "is empty" in result["a-broken"]["error"]
    assert str(tmp_path / "broken") in result["a-broken"]["repair_command"]
    assert result["b-healthy"]["status"] == "migrated"


def test_fleet_skips_a_scope_that_is_not_on_this_machine(monkeypatch, tmp_path: Path):
    """V-634: the laptop's tm_projects carries VPS scopes from the shared catalog.

    Before the fix each of them was reported as ORCHESTRA_LAYOUT_GIT_ERROR on every start.
    """
    calls = []

    def fake_one(repository, live_session_ids=None):
        calls.append(repository.name)
        return {"status": "migrated", "repository": str(repository)}

    monkeypatch.setattr(layout, "migrate_project_layout_preserving_dirty", fake_one)
    (tmp_path / "local").mkdir()
    result = layout.migrate_registered_projects(
        {"other-machine": tmp_path / "home" / "kesha" / "seedon", "local": tmp_path / "local"},
        preserve_dirty=True,
    )

    assert calls == ["local"]
    assert result["other-machine"]["status"] == "absent"
    assert result["local"]["status"] == "migrated"
