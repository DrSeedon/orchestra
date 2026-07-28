"""Unit tests for app.tm task-number allocation."""

import pytest


@pytest.fixture
def db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr("app.db.DB_PATH", db_path)
    from app.db import init_db
    init_db()
    return tmp_path


def test_next_par_skips_existing_docs_tasks_dir(db):
    """Occupied docs/tasks/<n>/ must not be issued even when free in DB."""
    from app import tm

    repo = db / "repo"
    occupied = repo / "docs" / "tasks" / "1"
    occupied.mkdir(parents=True)

    with tm._conn() as conn:
        tm.ensure_project(conn, "proj", scope=str(repo))
        # DB empty → MAX+1 would be 1, but dir 1 exists
        task = tm.create_task(conn, "proj", "fresh research")
        assert task["par_number"] == 2


def test_next_par_skips_dir_beyond_db_max(db):
    """After DB max N, skip N+1 if that directory already exists on disk."""
    from app import tm

    repo = db / "repo"
    (repo / "docs" / "tasks" / "2").mkdir(parents=True)

    with tm._conn() as conn:
        tm.ensure_project(conn, "proj", scope=str(repo))
        tm.create_task(conn, "proj", "first", par_number=1)
        task = tm.create_task(conn, "proj", "second auto")
        assert task["par_number"] == 3


def test_next_par_ignores_db_absence_of_dir_task(db):
    """Directory occupancy is filesystem fact, not a DB row."""
    from app import tm

    repo = db / "repo"
    # dirs 1 and 2 exist; no tm_tasks rows
    for n in (1, 2):
        (repo / "docs" / "tasks" / str(n)).mkdir(parents=True)

    with tm._conn() as conn:
        tm.ensure_project(conn, "proj", scope=str(repo))
        task = tm.create_task(conn, "proj", "only fs matters")
        assert task["par_number"] == 3


def test_explicit_par_number_still_honoured(db):
    """Caller-supplied par_number is not rewritten by dir checks."""
    from app import tm

    repo = db / "repo"
    (repo / "docs" / "tasks" / "5").mkdir(parents=True)

    with tm._conn() as conn:
        tm.ensure_project(conn, "proj", scope=str(repo))
        task = tm.create_task(conn, "proj", "import", par_number=5)
        assert task["par_number"] == 5
