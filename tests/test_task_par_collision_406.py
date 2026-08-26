from __future__ import annotations

import sqlite3

import pytest

from app.ia.task_store import IdentityConflictError


@pytest.fixture
def canonical_tasks(tmp_path, monkeypatch):
    from app import db, tm

    database = tmp_path / "orchestra.db"
    monkeypatch.setattr(db, "DB_PATH", database)
    db.init_db()
    with tm._conn() as connection:
        tm.ensure_project(connection, "orchestra", scope=str(tmp_path / "repo"))

    with tm.ia_task_store_mode(
        mode="canonical",
        canonical_root=tmp_path / "canonical",
        projection_path=tmp_path / "task-current.db",
        cutoff="2026-08-26T00:00:00+00:00",
        source_head="sha256:legacy-snapshot",
    ) as store:
        assert store is not None
        yield tm, store, database


def test_canonical_create_uses_one_agreed_number_in_both_stores(canonical_tasks):
    tm, store, database = canonical_tasks

    result = tm.api_create_task("orchestra", "agreed allocation")

    assert result["par"] == "1"
    assert store.task_get("1", project="orchestra")["title"] == "agreed allocation"
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT par_number,title FROM tm_tasks"
        ).fetchall() == [(1, "agreed allocation")]


def test_canonical_create_rejects_counter_drift_without_writing(canonical_tasks):
    tm, store, database = canonical_tasks
    with tm._conn() as connection:
        connection.execute("BEGIN IMMEDIATE")
        tm.create_task(connection, "orchestra", "legacy occupied", par_number=1)
        connection.commit()
    canonical_head = store.canonical_head

    with pytest.raises(IdentityConflictError, match="counter mismatch.*canonical=1.*legacy=2"):
        tm.api_create_task("orchestra", "must not be created")

    assert store.canonical_head == canonical_head
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT par_number,title FROM tm_tasks ORDER BY par_number"
        ).fetchall() == [(1, "legacy occupied")]
