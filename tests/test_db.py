"""TDD tests for db.py — written BEFORE implementation."""

import sqlite3
from datetime import datetime, timedelta, timezone

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
        "model": "claude-sonnet-5[1m]",
        "system_prompt": "You are a worker.",
                "status": "starting",
        "session_id": None,
        "cost_usd": 0.0,
        "worktree_path": "/mnt/data/Projects/Python/orchestra/worktrees/parsing/worker-1",
        "branch": "feat/parsing/worker-1",
        "is_orchestrator": False,
        "color": "#818cf8",
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
        assert "voice_costs" in tables
        assert "tool_errors" in tables
        assert "improvement_rules" in tables
        assert "merge_operations" in tables

    def test_idempotent(self, db):
        from app.db import init_db
        init_db()
        init_db()

    def test_telemetry_collector_start_is_durable(self, db):
        from app.db import init_db, kv_get

        tool_started = kv_get("tool_error_collector_started_at")
        turn_started = kv_get("turn_usage_collector_started_at")
        init_db()

        assert tool_started
        assert turn_started
        assert kv_get("tool_error_collector_started_at") == tool_started
        assert kv_get("turn_usage_collector_started_at") == turn_started


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


class TestVoiceCosts:
    def test_add_and_total(self, db):
        from app.db import _conn, voice_cost_add, voice_cost_total_usd

        voice_cost_add("orch", "/scope", 90.0, 0.0078, "tg-file-1")
        voice_cost_add("orch", "/scope", 30.0, 0.0026, "tg-file-2")

        assert voice_cost_total_usd() == pytest.approx(0.0104)
        with _conn() as c:
            row = c.execute("SELECT * FROM voice_costs ORDER BY id LIMIT 1").fetchone()
        assert row["session_name"] == "orch"
        assert row["scope"] == "/scope"
        assert row["duration_sec"] == 90.0
        assert row["model"] == "nova-3"
        assert row["file_id"] == "tg-file-1"


class TestToolErrors:
    def test_add_and_recent(self, db):
        from app.db import tool_error_add, tool_errors_recent

        tool_error_add("worker-1", "/scope", "Read", "file not found")
        tool_error_add("worker-2", "/other", "Bash", "command failed")

        rows = tool_errors_recent(limit=1)
        assert len(rows) == 1
        assert rows[0]["session_name"] == "worker-2"
        assert rows[0]["scope"] == "/other"
        assert rows[0]["tool_name"] == "Bash"
        assert rows[0]["error_text"] == "command failed"

    def test_summary_groups_tools_and_ranks_errors(self, db):
        from app.db import tool_error_add, tool_errors_summary

        for error_text in ("missing arg", "timeout", "missing arg"):
            tool_error_add("worker", "/scope", "Read", error_text)
        tool_error_add("worker", "/scope", "Bash", "exit 1")

        assert tool_errors_summary() == [
            {
                "tool_name": "Read",
                "error_count": 3,
                "top_errors": ["missing arg", "timeout"],
            },
            {
                "tool_name": "Bash",
                "error_count": 1,
                "top_errors": ["exit 1"],
            },
        ]

    def test_summary_excludes_old_errors(self, db):
        from app.db import _conn, tool_error_add, tool_errors_summary

        tool_error_add("worker", "/scope", "Read", "old")
        with _conn() as c:
            c.execute(
                "UPDATE tool_errors SET ts = datetime('now', '-8 days') "
                "WHERE error_text = 'old'"
            )
        tool_error_add("worker", "/scope", "Bash", "recent")

        assert tool_errors_summary(days=7) == [
            {
                "tool_name": "Bash",
                "error_count": 1,
                "top_errors": ["recent"],
            }
        ]

    def test_stable_tool_identity_deduplicates_and_bounds_error_text(self, db):
        from app.db import _conn, tool_error_add

        assert tool_error_add(
            "worker",
            "/scope",
            "Read",
            "x" * 10_000,
            runtime="claude",
            tool_use_id="tool-1",
        ) is True
        assert tool_error_add(
            "worker",
            "/scope",
            "Read",
            "replayed",
            runtime="claude",
            tool_use_id="tool-1",
        ) is False
        assert tool_error_add(
            "worker",
            "/scope",
            "Read",
            "same provider id, separate runtime",
            runtime="codex",
            tool_use_id="tool-1",
        ) is True

        with _conn() as conn:
            rows = conn.execute(
                "SELECT * FROM tool_errors ORDER BY id"
            ).fetchall()
        assert len(rows) == 2
        assert rows[0]["runtime"] == "claude"
        assert rows[0]["tool_use_id"] == "tool-1"
        assert len(rows[0]["error_text"]) == 4000

    def test_migrates_legacy_tool_error_rows(self, tmp_path, monkeypatch):
        db_path = tmp_path / "legacy-tool-errors.db"
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """CREATE TABLE tool_errors (
                    id INTEGER PRIMARY KEY,
                    ts TEXT DEFAULT CURRENT_TIMESTAMP,
                    session_name TEXT,
                    scope TEXT,
                    tool_name TEXT,
                    error_text TEXT
                )"""
            )
            conn.execute(
                """INSERT INTO tool_errors
                   (session_name, scope, tool_name, error_text)
                   VALUES ('worker', '/scope', 'Read', 'legacy')"""
            )
        monkeypatch.setattr("app.db.DB_PATH", db_path)
        from app.db import _conn, init_db

        init_db()

        with _conn() as conn:
            row = conn.execute("SELECT * FROM tool_errors").fetchone()
        assert row["runtime"] == "unknown"
        assert row["tool_use_id"] == ""


class TestImprovementRules:
    def test_propose_and_list(self, db):
        from app.db import rule_list, rule_propose

        rule_id = rule_propose(
            "When a tool fails, record the error",
            "repeated tool failure",
            "worker-1",
            "CLAUDE.md",
        )

        rules = rule_list()
        assert len(rules) == 1
        assert rules[0]["id"] == rule_id
        assert rules[0]["rule_text"] == "When a tool fails, record the error"
        assert rules[0]["source_signal"] == "repeated tool failure"
        assert rules[0]["proposed_by"] == "worker-1"
        assert rules[0]["target_file"] == "CLAUDE.md"
        assert rules[0]["status"] == "proposed"
        assert rules[0]["proposed_at"] is not None

    def test_approve_and_filter(self, db):
        from app.db import rule_approve, rule_list, rule_propose

        active_id = rule_propose("active rule", "signal", "worker")
        rule_propose("pending rule", "signal", "worker")
        rule_approve(active_id)

        active = rule_list(status="active")
        assert [rule["id"] for rule in active] == [active_id]
        assert active[0]["approved_at"] is not None
        assert active[0]["retired_at"] is None

    def test_retire(self, db):
        from app.db import rule_list, rule_propose, rule_retire

        rule_id = rule_propose("obsolete rule", "signal", "worker")
        rule_retire(rule_id)

        retired = rule_list(status="retired")
        assert [rule["id"] for rule in retired] == [rule_id]
        assert retired[0]["retired_at"] is not None


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

    def test_runtime_handoff_round_trip(self, db, sample_session):
        from app.db import get_session, save_session

        sample_session["runtime_handoff"] = "User:\ncontinue after runtime switch"
        save_session(sample_session)

        assert get_session(sample_session["id"])["runtime_handoff"] == sample_session["runtime_handoff"]

    def test_git_lifecycle_round_trip(self, db, sample_session):
        from app.db import get_session, save_session, update_session_lifecycle

        sample_session.update(
            base_branch="master",
            needs_switch=0,
            task_id="90",
        )
        save_session(sample_session)
        assert update_session_lifecycle(
            sample_session["id"],
            branch="task-90/worker-1",
            base_branch="master",
            task_id="",
            needs_switch=True,
        )

        row = get_session(sample_session["id"])
        assert row["branch"] == "task-90/worker-1"
        assert row["base_branch"] == "master"
        assert row["task_id"] == ""
        assert row["needs_switch"] == 1


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


class TestDeleteArchivedSession:
    def test_frees_slot_for_respawn(self, db, sample_session):
        """kill (archive) → re-spawn same name+scope must not hit UNIQUE(name,scope)."""
        from app.db import (
            save_session, archive_session, delete_archived_session, get_session_by_name,
        )
        save_session(sample_session)
        archive_session(sample_session["id"])
        # archived row is invisible to get_session_by_name but still holds the slot
        assert get_session_by_name("worker-1", sample_session["scope"]) is None
        delete_archived_session("worker-1", sample_session["scope"])
        respawn = {**sample_session, "id": "different-uuid", "status": "starting"}
        save_session(respawn)  # must not raise IntegrityError
        got = get_session_by_name("worker-1", sample_session["scope"])
        assert got["id"] == "different-uuid"

    def test_scope_isolated(self, db, sample_session):
        """Cleanup for one scope must not delete archived rows in another scope."""
        from app.db import save_session, archive_session, delete_archived_session, _conn
        other = {**sample_session, "id": "other-uuid", "scope": "/other/project"}
        save_session(other)
        archive_session(other["id"])
        delete_archived_session("worker-1", sample_session["scope"])  # different scope
        with _conn() as c:
            n = c.execute(
                "SELECT count(*) FROM sessions WHERE id=?", (other["id"],)
            ).fetchone()[0]
        assert n == 1

    def test_noop_when_no_archived(self, db, sample_session):
        """No archived row → no-op, live row untouched."""
        from app.db import save_session, delete_archived_session, get_session
        save_session(sample_session)
        delete_archived_session("worker-1", sample_session["scope"])
        assert get_session(sample_session["id"]) is not None


class TestPublishReadySession:
    def test_atomically_replaces_archived_identity(self, db, sample_session):
        from app.db import (
            add_log, archive_session, get_logs, get_session,
            publish_ready_session, save_session,
        )

        save_session(sample_session)
        add_log(sample_session["id"], datetime.now(timezone.utc), "text", "old")
        archive_session(sample_session["id"])
        ready = {
            **sample_session,
            "id": "ready-session",
            "status": "idle",
        }

        publish_ready_session(ready)

        assert get_session(sample_session["id"]) is None
        assert get_logs(sample_session["id"]) == []
        assert get_session("ready-session")["status"] == "idle"

    def test_failed_insert_preserves_archived_row_and_logs(self, db, sample_session):
        from app.db import (
            add_log, archive_session, get_logs, get_session,
            publish_ready_session, save_session,
        )

        save_session(sample_session)
        add_log(sample_session["id"], datetime.now(timezone.utc), "text", "keep")
        archive_session(sample_session["id"])
        invalid = {
            **sample_session,
            "id": "invalid-ready-session",
            "model": None,
            "status": "idle",
        }

        with pytest.raises(sqlite3.IntegrityError):
            publish_ready_session(invalid)

        assert get_session(sample_session["id"])["status"] == "archived"
        assert [row["content"] for row in get_logs(sample_session["id"])] == ["keep"]
        assert get_session("invalid-ready-session") is None


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

    def test_turn_log_preserves_provider_event_id(self, db, sample_session):
        from app.db import add_log, get_logs, save_session

        save_session(sample_session)
        add_log(
            sample_session["id"],
            datetime.now(timezone.utc),
            "status",
            "turn ended",
            event_id="result-uuid-1",
        )

        assert get_logs(sample_session["id"])[0]["event_id"] == "result-uuid-1"

    def test_migrates_legacy_logs_for_provider_event_id(self, tmp_path, monkeypatch):
        db_path = tmp_path / "legacy-logs.db"
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """CREATE TABLE logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    ts TEXT NOT NULL,
                    type TEXT NOT NULL,
                    content TEXT NOT NULL
                )"""
            )
            conn.execute(
                """INSERT INTO logs (session_id, ts, type, content)
                   VALUES ('old-worker', '2026-07-01T00:00:00+00:00',
                           'status', 'turn ended')"""
            )
        monkeypatch.setattr("app.db.DB_PATH", db_path)
        from app.db import _conn, init_db

        init_db()

        with _conn() as conn:
            row = conn.execute("SELECT event_id FROM logs").fetchone()
            index = conn.execute(
                """SELECT name FROM sqlite_master
                   WHERE type='index' AND name='idx_logs_event_id'"""
            ).fetchone()
        assert row["event_id"] == ""
        assert index["name"] == "idx_logs_event_id"

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


class TestTestLock:
    def test_acquire_succeeds_when_free(self, db):
        from app.db import acquire_test_lock, get_test_lock
        ok, holder = acquire_test_lock(scope="/s", holder="coder-auth", reason="full suite")
        assert ok is True
        assert holder is None  # никто не держал
        row = get_test_lock("/s")
        assert row["holder"] == "coder-auth"
        assert row["reason"] == "full suite"
        assert row["acquired_at"]

    def test_acquire_fails_when_held(self, db):
        from app.db import acquire_test_lock
        acquire_test_lock(scope="/s", holder="coder-a", reason="r1")
        ok, holder = acquire_test_lock(scope="/s", holder="coder-b", reason="r2")
        assert ok is False
        assert holder == "coder-a"  # текущий держатель

    def test_reacquire_by_same_holder_idempotent(self, db):
        from app.db import acquire_test_lock, get_test_lock
        acquire_test_lock(scope="/s", holder="coder-a", reason="r1")
        ok, holder = acquire_test_lock(scope="/s", holder="coder-a", reason="r1-again")
        assert ok is True  # тот же держатель повторно — ок (не отказ)
        assert get_test_lock("/s")["holder"] == "coder-a"

    def test_release_by_holder(self, db):
        from app.db import acquire_test_lock, release_test_lock, get_test_lock
        acquire_test_lock(scope="/s", holder="coder-a", reason="r1")
        ok = release_test_lock(scope="/s", holder="coder-a")
        assert ok is True
        assert get_test_lock("/s") is None

    def test_release_by_wrong_holder_denied(self, db):
        from app.db import acquire_test_lock, release_test_lock, get_test_lock
        acquire_test_lock(scope="/s", holder="coder-a", reason="r1")
        ok = release_test_lock(scope="/s", holder="coder-b")
        assert ok is False  # не держатель — не освобождает
        assert get_test_lock("/s")["holder"] == "coder-a"

    def test_lock_isolated_by_scope(self, db):
        from app.db import acquire_test_lock
        assert acquire_test_lock(scope="/a", holder="x", reason="")[0] is True
        assert acquire_test_lock(scope="/b", holder="y", reason="")[0] is True  # другой scope свободен


def _save_bg(job_id="bg-1", type="cron", config=None, status="active",
             expires_offset_s=3600):
    import json
    from app.db import bg_save_job
    now = datetime.now(timezone.utc)
    bg_save_job({
        "id": job_id, "type": type, "config": json.dumps(config or {}),
        "message": "ping", "target_session_id": "s-1", "target_name": "w1",
        "target_scope": "/s", "created_by_name": "orch", "status": status,
        "expires_at": (now + timedelta(seconds=expires_offset_s)).isoformat(),
        "trigger_at": None, "created_at": now.isoformat(), "last_output": "",
    })


class TestBgCron:
    def test_accepts_cron_type(self, db):
        # No CHECK error on type='cron' in the fresh schema.
        _save_bg(type="cron", config={"cron_expr": "*/5 * * * *"})
        from app.db import bg_get_active_all
        assert any(j["type"] == "cron" for j in bg_get_active_all())

    def test_should_fire_active(self, db):
        from app.db import bg_cron_should_fire
        _save_bg(job_id="bg-a", status="active", expires_offset_s=3600)
        assert bg_cron_should_fire("bg-a") is True

    def test_should_fire_false_when_cancelled(self, db):
        from app.db import bg_cron_should_fire, bg_cancel_job
        _save_bg(job_id="bg-b", status="active")
        bg_cancel_job("bg-b")
        assert bg_cron_should_fire("bg-b") is False

    def test_should_fire_false_when_expired_time(self, db):
        from app.db import bg_cron_should_fire
        _save_bg(job_id="bg-c", status="active", expires_offset_s=-10)
        assert bg_cron_should_fire("bg-c") is False

    def test_should_fire_false_when_missing(self, db):
        from app.db import bg_cron_should_fire
        assert bg_cron_should_fire("ghost") is False

    def test_record_fire_increments(self, db):
        import json
        from app.db import bg_cron_record_fire, bg_get_active_all
        _save_bg(job_id="bg-d", config={"cron_expr": "* * * * *"})
        bg_cron_record_fire("bg-d")
        bg_cron_record_fire("bg-d")
        job = next(j for j in bg_get_active_all() if j["id"] == "bg-d")
        cfg = json.loads(job["config"])
        assert cfg["fire_count"] == 2
        assert "last_fired_at" in cfg

    def test_record_fire_noop_when_not_active(self, db):
        import json
        from app.db import bg_cron_record_fire, bg_cancel_job, bg_get_jobs
        _save_bg(job_id="bg-e", config={"cron_expr": "* * * * *"})
        bg_cancel_job("bg-e")
        bg_cron_record_fire("bg-e")
        job = next(j for j in bg_get_jobs(scope="/s") if j["id"] == "bg-e")
        cfg = json.loads(job["config"])
        assert "fire_count" not in cfg


class TestBgMigration:
    def _make_old_schema_db(self, db_path):
        """Create a bg_jobs table WITH the old type CHECK + seed a row."""
        import sqlite3
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE bg_jobs (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL CHECK (type IN ('timer','file','command','ssh','run')),
                config TEXT NOT NULL DEFAULT '{}',
                message TEXT NOT NULL DEFAULT '',
                target_session_id TEXT NOT NULL,
                target_name TEXT NOT NULL,
                target_scope TEXT NOT NULL,
                created_by_name TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active','triggering','triggered','expired','cancelled','failed')),
                error TEXT,
                expires_at TEXT NOT NULL,
                trigger_at TEXT,
                created_at TEXT NOT NULL,
                triggered_at TEXT,
                last_output TEXT NOT NULL DEFAULT ''
            )
        """)
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO bg_jobs (id, type, config, target_session_id, target_name, "
            "target_scope, status, expires_at, created_at) "
            "VALUES ('old-1','timer','{}','s','n','/s','active',?,?)",
            (now, now),
        )
        conn.commit()
        conn.close()

    def test_migrate_drops_type_check(self, tmp_path, monkeypatch):
        import json
        db_path = tmp_path / "old.db"
        self._make_old_schema_db(db_path)
        monkeypatch.setattr("app.db.DB_PATH", db_path)
        from app.db import init_db, bg_save_job, bg_get_active_all
        init_db()  # runs _migrate, rebuilds bg_jobs without type CHECK
        # original row preserved
        ddl = None
        from app.db import _conn
        with _conn() as c:
            ddl = c.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='bg_jobs'"
            ).fetchone()[0]
            assert "type IN ('timer'" not in ddl
            cnt = c.execute("SELECT COUNT(*) FROM bg_jobs").fetchone()[0]
            assert cnt == 1
            old_exists = c.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='bg_jobs_old'"
            ).fetchone()
            assert old_exists is None
        # cron type now accepted
        now = datetime.now(timezone.utc)
        bg_save_job({
            "id": "cron-1", "type": "cron", "config": json.dumps({"cron_expr": "* * * * *"}),
            "message": "", "target_session_id": "s", "target_name": "n",
            "target_scope": "/s", "created_by_name": "", "status": "active",
            "expires_at": (now + timedelta(hours=1)).isoformat(),
            "trigger_at": None, "created_at": now.isoformat(), "last_output": "",
        })
        assert any(j["type"] == "cron" for j in bg_get_active_all())

    def test_migrate_idempotent_on_fresh_db(self, db):
        # Fresh DB already has no type CHECK; init_db again must not error.
        from app.db import init_db
        init_db()


# ── Этап 1: pipeline-колонка + round-trip ──

class TestPipelineColumn:
    def test_migrate_adds_pipeline_column(self, db):
        from app.db import _conn
        with _conn() as c:
            cols = {r[1] for r in c.execute("PRAGMA table_info(sessions)").fetchall()}
        assert "pipeline" in cols

    def test_save_and_load_pipeline(self, db, sample_session):
        from app.db import save_session, get_session
        sample_session["pipeline"] = "tasks-pm"
        save_session(sample_session)
        row = get_session(sample_session["id"])
        assert row["pipeline"] == "tasks-pm"

    def test_save_without_pipeline_defaults_empty(self, db, sample_session):
        from app.db import save_session, get_session
        sample_session.pop("pipeline", None)
        save_session(sample_session)
        row = get_session(sample_session["id"])
        assert row["pipeline"] == ""


class TestLifecycleColumns:
    def test_old_server_insert_uses_additive_defaults(self, db):
        from app.db import _conn

        with _conn() as c:
            c.execute(
                """INSERT INTO sessions
                   (id, name, scope, cwd, model, status, created_at)
                   VALUES ('old-server', 'old', '/scope', '/cwd', 'model',
                           'idle', '2026-07-26T00:00:00+00:00')"""
            )
            row = c.execute(
                "SELECT base_branch, needs_switch FROM sessions WHERE id='old-server'"
            ).fetchone()
        assert tuple(row) == ("", 0)

    def test_migration_adds_lifecycle_columns_idempotently(self, db):
        from app.db import _conn, init_db

        with _conn() as c:
            c.execute("ALTER TABLE sessions DROP COLUMN base_branch")
            c.execute("ALTER TABLE sessions DROP COLUMN needs_switch")
        init_db()
        init_db()
        with _conn() as c:
            cols = {r[1] for r in c.execute("PRAGMA table_info(sessions)").fetchall()}
        assert {"base_branch", "needs_switch"} <= cols


# ── Этап 6, чанк 1: профили Claude (таблица profiles + sessions.profile) ──

class TestProfilesMigration:
    def test_profiles_table_exists(self, db):
        from app.db import _conn
        with _conn() as c:
            tables = {r[0] for r in c.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
        assert "profiles" in tables

    def test_seed_personal_present(self, db):
        """Миграция авто-сидит профиль 'personal' с пустым config_dir."""
        from app.db import get_profile
        p = get_profile("personal")
        assert p is not None
        assert p["name"] == "personal"
        assert p["config_dir"] == ""

    def test_sessions_profile_column_exists(self, db):
        from app.db import _conn
        with _conn() as c:
            cols = {r[1] for r in c.execute("PRAGMA table_info(sessions)").fetchall()}
        assert "profile" in cols

    def test_migration_idempotent_no_duplicate_personal(self, db):
        """Повторный init не падает и не плодит дублей 'personal'."""
        from app.db import init_db, _conn
        init_db()
        init_db()
        with _conn() as c:
            n = c.execute(
                "SELECT COUNT(*) FROM profiles WHERE name='personal'"
            ).fetchone()[0]
        assert n == 1


class TestProfileColumnRoundTrip:
    def test_save_and_load_profile(self, db, sample_session):
        from app.db import save_session, get_session
        sample_session["profile"] = "work"
        save_session(sample_session)
        row = get_session(sample_session["id"])
        assert row["profile"] == "work"

    def test_save_without_profile_defaults_empty(self, db, sample_session):
        from app.db import save_session, get_session
        sample_session.pop("profile", None)
        save_session(sample_session)
        row = get_session(sample_session["id"])
        assert row["profile"] == ""


class TestProfilesCRUD:
    def test_upsert_and_list(self, db):
        from app.db import upsert_profile, list_profiles
        upsert_profile("work", "/home/user/.claude-work")
        names = {p["name"] for p in list_profiles()}
        assert "work" in names
        assert "personal" in names  # сид

    def test_list_sorted_by_name(self, db):
        from app.db import upsert_profile, list_profiles
        upsert_profile("zeta", "/z")
        upsert_profile("alpha", "/a")
        names = [p["name"] for p in list_profiles()]
        assert names == sorted(names)

    def test_get_profile(self, db):
        from app.db import upsert_profile, get_profile
        upsert_profile("work", "/home/user/.claude-work")
        p = get_profile("work")
        assert p == {"name": "work", "config_dir": "/home/user/.claude-work"}

    def test_get_nonexistent_profile(self, db):
        from app.db import get_profile
        assert get_profile("ghost") is None

    def test_upsert_updates_not_duplicates(self, db):
        from app.db import upsert_profile, get_profile, list_profiles
        upsert_profile("work", "/old/path")
        before = len(list_profiles())
        upsert_profile("work", "/new/path")
        after = len(list_profiles())
        assert before == after
        assert get_profile("work")["config_dir"] == "/new/path"

    def test_delete_profile(self, db):
        from app.db import upsert_profile, delete_profile, get_profile
        upsert_profile("work", "/x")
        delete_profile("work")
        assert get_profile("work") is None

    def test_delete_personal_raises(self, db):
        from app.db import delete_profile, get_profile
        with pytest.raises(ValueError):
            delete_profile("personal")
        # сид остаётся на месте
        assert get_profile("personal") is not None
class TestChangeScope:
    def _orch(self, scope="/old/proj", name="orch", sid="orch-uuid-1"):
        return {
            "id": sid, "name": name, "scope": scope, "cwd": scope,
            "model": "claude-opus-5", "system_prompt": "orch",
            "status": "idle", "session_id": "sdk-abc", "cost_usd": 0.0,
            "worktree_path": None, "branch": None, "is_orchestrator": True,
            "color": "", "created_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None, "role": "orchestrator",
        }

    def test_updates_scope_and_cwd(self, db):
        from app.db import save_session, get_session, change_scope
        save_session(self._orch())
        res = change_scope("orch-uuid-1", "/old/proj", "/new/proj", "/new/proj")
        assert res["ok"] is True
        got = get_session("orch-uuid-1")
        assert got["scope"] == "/new/proj"
        assert got["cwd"] == "/new/proj"

    def test_session_id_preserved(self, db):
        from app.db import save_session, get_session, change_scope
        save_session(self._orch())
        change_scope("orch-uuid-1", "/old/proj", "/new/proj", "/new/proj")
        got = get_session("orch-uuid-1")
        assert got["session_id"] == "sdk-abc"  # context resume token intact

    def test_name_collision_in_target_scope_rejected(self, db):
        from app.db import save_session, get_session, change_scope
        save_session(self._orch(scope="/old/proj", name="orch", sid="A"))
        # another agent with same name already lives in target scope
        save_session(self._orch(scope="/new/proj", name="orch", sid="B"))
        res = change_scope("A", "/old/proj", "/new/proj", "/new/proj")
        assert res.get("ok") is not True
        assert "error" in res
        # original untouched (rolled back)
        assert get_session("A")["scope"] == "/old/proj"

    def test_migrates_tm_project_scope(self, db):
        from app.db import save_session, change_scope, _conn
        from app.tm import ensure_project
        save_session(self._orch())
        with _conn() as c:
            ensure_project(c, "proj1", scope="/old/proj", prefix="OLD")
            c.commit()
        change_scope("orch-uuid-1", "/old/proj", "/new/proj", "/new/proj")
        with _conn() as c:
            row = c.execute("SELECT scope FROM tm_projects WHERE id='proj1'").fetchone()
        assert row["scope"] == "/new/proj"

    def test_tm_project_collision_keeps_session_change(self, db):
        from app.db import save_session, change_scope, get_session, _conn
        from app.tm import ensure_project
        save_session(self._orch())
        with _conn() as c:
            ensure_project(c, "p_old", scope="/old/proj", prefix="OLD")
            ensure_project(c, "p_new", scope="/new/proj", prefix="NEW")
            c.commit()
        # tm_projects.scope is UNIQUE — target taken. Session scope must still change.
        res = change_scope("orch-uuid-1", "/old/proj", "/new/proj", "/new/proj")
        assert res["ok"] is True
        assert get_session("orch-uuid-1")["scope"] == "/new/proj"
        with _conn() as c:
            old = c.execute("SELECT scope FROM tm_projects WHERE id='p_old'").fetchone()
        assert old["scope"] == "/old/proj"  # not migrated (collision)
        assert res.get("tm_project_migrated") is False

    def test_migrates_active_bg_jobs(self, db):
        from app.db import save_session, change_scope, bg_save_job, _conn
        save_session(self._orch())
        now = datetime.now(timezone.utc)
        common = {
            "config": "{}", "message": "", "target_session_id": "orch-uuid-1",
            "target_name": "orch", "target_scope": "/old/proj", "created_by_name": "",
            "expires_at": (now + timedelta(hours=1)).isoformat(),
            "trigger_at": None, "created_at": now.isoformat(), "last_output": "",
        }
        bg_save_job({**common, "id": "j-active", "type": "timer", "status": "active"})
        bg_save_job({**common, "id": "j-done", "type": "timer", "status": "triggered"})
        change_scope("orch-uuid-1", "/old/proj", "/new/proj", "/new/proj")
        with _conn() as c:
            a = c.execute("SELECT target_scope FROM bg_jobs WHERE id='j-active'").fetchone()
            d = c.execute("SELECT target_scope FROM bg_jobs WHERE id='j-done'").fetchone()
        assert a["target_scope"] == "/new/proj"
        assert d["target_scope"] == "/old/proj"  # terminal job not migrated

    def test_migrates_test_lock(self, db):
        from app.db import save_session, change_scope, acquire_test_lock, get_test_lock
        save_session(self._orch())
        acquire_test_lock("/old/proj", "orch", "running suite")
        change_scope("orch-uuid-1", "/old/proj", "/new/proj", "/new/proj")
        assert get_test_lock("/old/proj") is None
        moved = get_test_lock("/new/proj")
        assert moved is not None and moved["holder"] == "orch"

    def test_stale_old_scope_rejected(self, db):
        # session already moved to /new/proj; a retried request with stale
        # old_scope=/old/proj must NOT partially migrate related tables.
        from app.db import save_session, change_scope, get_session, acquire_test_lock, get_test_lock
        save_session(self._orch(scope="/new/proj"))  # already in target
        acquire_test_lock("/new/proj", "orch", "x")
        res = change_scope("orch-uuid-1", "/old/proj", "/new/proj", "/new/proj")
        assert res.get("ok") is not True
        assert "error" in res
        assert get_session("orch-uuid-1")["scope"] == "/new/proj"  # untouched
        assert get_test_lock("/new/proj") is not None  # lock not orphaned


class TestLastTurnMap:
    """get_last_turn_map() runs on every /api/sessions — it must not scan the logs table."""

    QUERY = (
        "SELECT session_id, MAX(ts) AS last_ts FROM logs "
        "WHERE type='status' AND content LIKE 'turn ended%' "
        "GROUP BY session_id"
    )

    def _session(self, sid, name):
        return {
            "id": sid, "name": name, "scope": "/proj", "cwd": "/proj",
            "model": "claude-opus-5[1m]", "system_prompt": "", "status": "idle",
            "session_id": None, "cost_usd": 0.0, "worktree_path": "", "branch": "",
            "is_orchestrator": False, "color": "#818cf8",
            "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
        }

    def test_returns_last_turn_per_session(self, db):
        from app.db import save_session, add_log, get_last_turn_map
        save_session(self._session("s-1", "w1"))
        save_session(self._session("s-2", "w2"))
        t0 = datetime(2026, 8, 4, 10, 0, tzinfo=timezone.utc)
        add_log("s-1", t0, "status", "turn ended (12 tools)")
        add_log("s-1", t0 + timedelta(minutes=5), "status", "turn ended (3 tools)")
        add_log("s-1", t0 + timedelta(minutes=9), "status", "turn started")
        add_log("s-2", t0 + timedelta(minutes=1), "text", "turn ended — not a status row")
        m = get_last_turn_map()
        assert m["s-1"] == (t0 + timedelta(minutes=5)).isoformat()
        assert "s-2" not in m

    def test_query_uses_status_index_not_full_scan(self, db):
        """Without idx_logs_status SQLite reads content of EVERY log row to LIKE-match it."""
        with sqlite3.connect(db) as c:
            plan = " ".join(str(r) for r in c.execute("EXPLAIN QUERY PLAN " + self.QUERY))
        assert "idx_logs_status" in plan, plan
