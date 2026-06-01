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
        "model": "claude-sonnet-4-6",
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
        sample_session["pipeline"] = "sapto-pm"
        save_session(sample_session)
        row = get_session(sample_session["id"])
        assert row["pipeline"] == "sapto-pm"

    def test_save_without_pipeline_defaults_empty(self, db, sample_session):
        from app.db import save_session, get_session
        sample_session.pop("pipeline", None)
        save_session(sample_session)
        row = get_session(sample_session["id"])
        assert row["pipeline"] == ""


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
