"""TDD tests for db.py — written BEFORE implementation."""

import sqlite3
from datetime import datetime, timezone

import pytest


@pytest.fixture
def db(tmp_path, monkeypatch):
    """In-memory-like DB using tmp_path for isolation."""
    db_path = tmp_path / "test.db"
    monkeypatch.setattr("app.db.DB_PATH", db_path)
    from app.db import init_db
    init_db()
    return db_path


@pytest.fixture
def sample_session():
    return {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "name": "worker-1",
        "scope": "/mnt/data/Projects/Python/Parsing",
        "cwd": "/mnt/data/Projects/Python/orchestra/worktrees/parsing/worker-1",
        "model": "claude-sonnet-4-6",
        "system_prompt": "You are a worker.",
                "status": "starting",
        "session_id": None,
        "cost_usd": 0.0,
        "worktree_path": "/mnt/data/Projects/Python/orchestra/worktrees/parsing/worker-1",
        "branch": "feat/parsing/worker-1",
        "is_orchestrator": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
    }


class TestInitDb:
    def test_creates_tables(self, db):
        from app.db import _conn
        with _conn() as c:
            tables = {r[0] for r in c.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
        assert "sessions" in tables
        assert "logs" in tables

    def test_idempotent(self, db):
        from app.db import init_db
        init_db()
        init_db()


class TestConnection:
    def test_wal_mode(self, db):
        from app.db import _conn
        with _conn() as c:
            mode = c.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"

    def test_busy_timeout(self, db):
        from app.db import _conn
        with _conn() as c:
            timeout = c.execute("PRAGMA busy_timeout").fetchone()[0]
        assert timeout == 5000

    def test_foreign_keys_on(self, db):
        from app.db import _conn
        with _conn() as c:
            fk = c.execute("PRAGMA foreign_keys").fetchone()[0]
        assert fk == 1


class TestSaveAndGetSession:
    def test_round_trip(self, db, sample_session):
        from app.db import save_session, get_session
        save_session(sample_session)
        got = get_session(sample_session["id"])
        assert got is not None
        assert got["name"] == "worker-1"
        assert got["scope"] == sample_session["scope"]
        assert got["status"] == "starting"

    def test_get_nonexistent(self, db):
        from app.db import get_session
        assert get_session("nonexistent-uuid") is None

    def test_get_by_name(self, db, sample_session):
        from app.db import save_session, get_session_by_name
        save_session(sample_session)
        got = get_session_by_name("worker-1", sample_session["scope"])
        assert got is not None
        assert got["id"] == sample_session["id"]

    def test_get_by_name_wrong_scope(self, db, sample_session):
        from app.db import save_session, get_session_by_name
        save_session(sample_session)
        assert get_session_by_name("worker-1", "/other/scope") is None


class TestUniqueness:
    def test_same_name_scope_raises(self, db, sample_session):
        from app.db import save_session
        save_session(sample_session)
        dupe = {**sample_session, "id": "different-uuid"}
        with pytest.raises(sqlite3.IntegrityError):
            save_session(dupe)

    def test_same_name_different_scope(self, db, sample_session):
        from app.db import save_session, get_session
        save_session(sample_session)
        other = {
            **sample_session,
            "id": "660e8400-e29b-41d4-a716-446655440001",
            "scope": "/other/project",
        }
        save_session(other)
        assert get_session(sample_session["id"]) is not None
        assert get_session(other["id"]) is not None


class TestUpsert:
    def test_updates_mutable_fields(self, db, sample_session):
        from app.db import save_session, get_session
        save_session(sample_session)
        updated = {**sample_session, "status": "running", "cost_usd": 1.5, "session_id": "sdk-123"}
        save_session(updated)
        got = get_session(sample_session["id"])
        assert got["status"] == "running"
        assert got["cost_usd"] == 1.5
        assert got["session_id"] == "sdk-123"

    def test_preserves_immutable_fields(self, db, sample_session):
        from app.db import save_session, get_session
        save_session(sample_session)
        original_created = sample_session["created_at"]
        updated = {**sample_session, "status": "idle", "created_at": "2099-01-01T00:00:00"}
        save_session(updated)
        got = get_session(sample_session["id"])
        assert got["created_at"] == original_created


class TestGetAllSessions:
    def test_scope_filter(self, db, sample_session):
        from app.db import save_session, get_all_sessions
        save_session(sample_session)
        other = {
            **sample_session,
            "id": "other-uuid",
            "name": "worker-2",
            "scope": "/other/project",
        }
        save_session(other)
        parsing = get_all_sessions(scope=sample_session["scope"])
        assert len(parsing) == 1
        assert parsing[0]["name"] == "worker-1"

    def test_no_filter_returns_all(self, db, sample_session):
        from app.db import save_session, get_all_sessions
        save_session(sample_session)
        other = {
            **sample_session,
            "id": "other-uuid",
            "name": "worker-2",
            "scope": "/other/project",
        }
        save_session(other)
        all_sessions = get_all_sessions()
        assert len(all_sessions) == 2


class TestDeleteCascade:
    def test_delete_removes_session(self, db, sample_session):
        from app.db import save_session, delete_session, get_session
        save_session(sample_session)
        delete_session(sample_session["id"])
        assert get_session(sample_session["id"]) is None

    def test_delete_cascades_logs(self, db, sample_session):
        from app.db import save_session, add_log, delete_session, get_logs
        save_session(sample_session)
        sid = sample_session["id"]
        add_log(sid, datetime.now(timezone.utc), "text", "hello")
        add_log(sid, datetime.now(timezone.utc), "tool", "Bash: ls")
        assert len(get_logs(sid)) == 2
        delete_session(sid)
        assert len(get_logs(sid)) == 0


class TestLogs:
    def test_add_returns_id(self, db, sample_session):
        from app.db import save_session, add_log
        save_session(sample_session)
        id1 = add_log(sample_session["id"], datetime.now(timezone.utc), "text", "msg1")
        id2 = add_log(sample_session["id"], datetime.now(timezone.utc), "text", "msg2")
        assert id2 > id1

    def test_cursor_pagination(self, db, sample_session):
        from app.db import save_session, add_log, get_logs
        save_session(sample_session)
        sid = sample_session["id"]
        ids = [add_log(sid, datetime.now(timezone.utc), "text", f"msg{i}") for i in range(10)]
        after_5 = get_logs(sid, after_id=ids[4])
        assert len(after_5) == 5
        assert all(log["id"] > ids[4] for log in after_5)

    def test_limit(self, db, sample_session):
        from app.db import save_session, add_log, get_logs
        save_session(sample_session)
        sid = sample_session["id"]
        for i in range(20):
            add_log(sid, datetime.now(timezone.utc), "text", f"msg{i}")
        limited = get_logs(sid, limit=10)
        assert len(limited) == 10

    def test_log_types(self, db, sample_session):
        from app.db import save_session, add_log, get_logs
        save_session(sample_session)
        sid = sample_session["id"]
        for t in ("text", "tool", "error", "status", "user_message", "notification"):
            add_log(sid, datetime.now(timezone.utc), t, f"type-{t}")
        logs = get_logs(sid)
        types = {l["type"] for l in logs}
        assert types == {"text", "tool", "error", "status", "user_message", "notification"}


class TestOrchestrators:
    def test_returns_only_orchestrators(self, db, sample_session):
        from app.db import save_session, get_orchestrators
        save_session(sample_session)
        orch = {
            **sample_session,
            "id": "orch-uuid",
            "name": "orchestrator",
            "is_orchestrator": True,
            "session_id": "sdk-session-123",
            "status": "idle",
        }
        save_session(orch)
        result = get_orchestrators()
        assert len(result) == 1
        assert result[0]["name"] == "orchestrator"

    def test_excludes_stopped(self, db, sample_session):
        from app.db import save_session, get_orchestrators
        orch = {
            **sample_session,
            "id": "orch-uuid",
            "name": "orchestrator",
            "is_orchestrator": True,
            "session_id": "sdk-session-123",
            "status": "stopped",
        }
        save_session(orch)
        assert len(get_orchestrators()) == 0

    def test_includes_no_session_id(self, db, sample_session):
        from app.db import save_session, get_orchestrators
        orch = {
            **sample_session,
            "id": "orch-uuid",
            "name": "orchestrator",
            "is_orchestrator": True,
            "session_id": None,
            "status": "idle",
        }
        save_session(orch)
        assert len(get_orchestrators()) == 1

    def test_resumable_excludes_no_session_id(self, db, sample_session):
        from app.db import save_session, get_resumable_orchestrators
        orch = {
            **sample_session,
            "id": "orch-uuid",
            "name": "orchestrator",
            "is_orchestrator": True,
            "session_id": None,
            "status": "idle",
        }
        save_session(orch)
        assert len(get_resumable_orchestrators()) == 0


class TestMarkStaleSessions:
    def test_marks_running_non_orchestrators(self, db, sample_session):
        from app.db import save_session, mark_stale_sessions, get_session
        running = {**sample_session, "status": "running"}
        save_session(running)
        count = mark_stale_sessions(exclude_ids=[])
        assert count == 1
        got = get_session(sample_session["id"])
        assert got["status"] == "error"

    def test_excludes_given_ids(self, db, sample_session):
        from app.db import save_session, mark_stale_sessions, get_session
        running = {**sample_session, "status": "running"}
        save_session(running)
        count = mark_stale_sessions(exclude_ids=[sample_session["id"]])
        assert count == 0
        assert get_session(sample_session["id"])["status"] == "running"

    def test_skips_orchestrators(self, db, sample_session):
        from app.db import save_session, mark_stale_sessions, get_session
        orch = {**sample_session, "status": "running", "is_orchestrator": True}
        save_session(orch)
        count = mark_stale_sessions(exclude_ids=[])
        assert count == 0


class TestStats:
    def test_aggregation(self, db, sample_session):
        from app.db import save_session, get_stats, add_log
        s1 = {**sample_session, "status": "running", "cost_usd": 0.5}
        save_session(s1)
        s2 = {
            **sample_session,
            "id": "s2-uuid",
            "name": "worker-2",
            "status": "idle",
            "cost_usd": 1.2,
        }
        save_session(s2)
        add_log(s1["id"], datetime.now(timezone.utc), "text", "log1")
        add_log(s2["id"], datetime.now(timezone.utc), "text", "log2")

        stats = get_stats(scope=sample_session["scope"])
        assert stats["total_sessions"] == 2
        assert stats["active"] == 1
        assert stats["total_cost_usd"] == pytest.approx(1.7)
        assert stats["total_logs"] == 2
