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
