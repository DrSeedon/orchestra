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


def test_scoped_task_identity_selects_duplicate_number_in_session_project(db):
    from app import tm

    scope_a = str(db / "repo-a")
    scope_b = str(db / "repo-b")
    with tm._conn() as conn:
        tm.ensure_project(conn, "project-a", scope=scope_a, prefix="PRA")
        tm.ensure_project(conn, "project-b", scope=scope_b, prefix="PRB")
        task_a = tm.create_task(conn, "project-a", "A", par_number=7)
        task_b = tm.create_task(conn, "project-b", "B", par_number=7)

    identity = tm.resolve_scoped_task_identity(scope_b, "#7")
    assert tm.resolve_scoped_task_identity(scope_b, "task-7") == identity
    result = tm.api_update_task_if_current(identity, status="in_progress")

    assert identity == {
        "id": task_b["id"],
        "project_id": "project-b",
        "par_number": 7,
        "sync_revision": 0,
    }
    assert result["ok"] is True
    with tm._conn() as conn:
        assert tm.get_task_by_id(conn, task_a["id"])["status"] == "new"
        assert tm.get_task_by_id(conn, task_b["id"])["status"] == "in_progress"


def test_scoped_task_identity_rejects_unmapped_scope_and_wrong_prefix(db):
    from app import tm

    scope = str(db / "repo")
    with tm._conn() as conn:
        tm.ensure_project(conn, "project", scope=scope, prefix="PRJ")
        tm.create_task(conn, "project", "task", par_number=3)

    with pytest.raises(ValueError, match="no task project"):
        tm.resolve_scoped_task_identity(str(db / "missing"), "3")
    with pytest.raises(ValueError, match="belongs to project"):
        tm.resolve_scoped_task_identity(scope, "ALT-3")


def test_conditional_task_update_rejects_revision_change(db):
    from app import tm

    scope = str(db / "repo")
    with tm._conn() as conn:
        tm.ensure_project(conn, "project", scope=scope)
        task = tm.create_task(conn, "project", "task", par_number=4)
    identity = tm.resolve_scoped_task_identity(scope, "4")
    with tm._conn() as conn:
        conn.execute(
            "UPDATE tm_tasks SET title='changed', sync_revision=sync_revision+1 WHERE id=?",
            (task["id"],),
        )

    result = tm.api_update_task_if_current(identity, status="in_progress")

    assert result["ok"] is False
    assert "revision" in result["error"]
    with tm._conn() as conn:
        assert tm.get_task_by_id(conn, task["id"])["status"] == "new"


def test_conditional_task_update_does_not_touch_reused_number(db):
    from app import tm

    scope = str(db / "repo")
    with tm._conn() as conn:
        tm.ensure_project(conn, "project", scope=scope)
        old_task = tm.create_task(conn, "project", "old", par_number=5)
    identity = tm.resolve_scoped_task_identity(scope, "5")
    with tm._conn() as conn:
        conn.execute("DELETE FROM tm_tasks WHERE id=?", (old_task["id"],))
        replacement = tm.create_task(conn, "project", "replacement", par_number=5)

    result = tm.api_update_task_if_current(identity, status="in_progress")

    assert result["ok"] is False
    assert "no longer exists" in result["error"]
    with tm._conn() as conn:
        assert tm.get_task_by_id(conn, replacement["id"])["status"] == "new"
