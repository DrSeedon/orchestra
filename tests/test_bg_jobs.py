"""Tests for bg_jobs.py cron support (#26)."""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr("app.db.DB_PATH", db_path)
    from app.db import init_db
    init_db()
    return db_path


@pytest.fixture
def mgr_mock():
    m = MagicMock()
    sess = MagicMock()
    sess.send = AsyncMock()
    m.ensure_loaded = AsyncMock(return_value=sess)
    m.ensure_loaded_any = AsyncMock(return_value=sess)
    return m, sess


class TestValidateCron:
    def test_requires_expr(self):
        from app.bg_jobs import _validate_config
        assert _validate_config("cron", {}) == "cron_expr is required"

    def test_rejects_bad_expr(self):
        from app.bg_jobs import _validate_config
        err = _validate_config("cron", {"cron_expr": "not a cron"})
        assert err and "invalid cron" in err

    def test_accepts_valid(self):
        from app.bg_jobs import _validate_config
        assert _validate_config("cron", {"cron_expr": "*/5 * * * *"}) is None


def test_run_rejects_invalid_success_pattern():
    from app.bg_jobs import _validate_config
    error = _validate_config("run", {"command": "true", "success_pattern": "["})
    assert error and "success_pattern" in error


class TestCronCreate:
    @pytest.mark.asyncio
    async def test_no_timeout_means_forever(self, db, monkeypatch):
        from app.bg_jobs import BgJobManager
        from app.db import bg_get_active_all
        mgr = BgJobManager()
        # Don't actually start the asyncio loop (we only inspect persistence).
        monkeypatch.setattr(mgr, "_start_task", lambda *a, **k: None)
        res = await mgr.create(
            "cron", {"cron_expr": "* * * * *"}, "ping",
            "s-1", "w1", "/s", "orch", timeout_seconds=0,
        )
        assert res["status"] == "active"
        job = next(j for j in bg_get_active_all() if j["id"] == res["id"])
        cfg = json.loads(job["config"])
        assert cfg.get("no_expiry") is True
        # far-future expiry → never overdue
        exp = datetime.fromisoformat(job["expires_at"])
        assert (exp - datetime.now(timezone.utc)).days > 1000


class TestFireCron:
    @pytest.mark.asyncio
    async def test_fire_keeps_active_and_counts(self, db, mgr_mock):
        from app.bg_jobs import BgJobManager
        from app.db import bg_save_job, bg_get_active_all
        mgr = BgJobManager()
        m, sess = mgr_mock
        mgr.set_session_manager(m)
        now = datetime.now(timezone.utc)
        bg_save_job({
            "id": "c1", "type": "cron", "config": json.dumps({"cron_expr": "* * * * *"}),
            "message": "ping", "target_session_id": "s-1", "target_name": "w1",
            "target_scope": "/s", "created_by_name": "orch", "status": "active",
            "expires_at": (now + timedelta(hours=1)).isoformat(),
            "trigger_at": None, "created_at": now.isoformat(), "last_output": "",
        })
        await mgr._fire_cron("c1", "ping", "w1", "/s")
        sess.send.assert_awaited_once()
        job = next(j for j in bg_get_active_all() if j["id"] == "c1")
        assert job["status"] == "active"
        assert json.loads(job["config"])["fire_count"] == 1

    @pytest.mark.asyncio
    async def test_fire_missing_target_skips(self, db):
        from app.bg_jobs import BgJobManager
        from app.db import bg_save_job, bg_get_active_all
        mgr = BgJobManager()
        m = MagicMock()
        m.ensure_loaded = AsyncMock(return_value=None)
        m.ensure_loaded_any = AsyncMock(return_value=None)
        mgr.set_session_manager(m)
        now = datetime.now(timezone.utc)
        bg_save_job({
            "id": "c2", "type": "cron", "config": json.dumps({"cron_expr": "* * * * *"}),
            "message": "ping", "target_session_id": "s-1", "target_name": "w1",
            "target_scope": "/s", "created_by_name": "orch", "status": "active",
            "expires_at": (now + timedelta(hours=1)).isoformat(),
            "trigger_at": None, "created_at": now.isoformat(), "last_output": "",
        })
        await mgr._fire_cron("c2", "ping", "w1", "/s")  # no raise
        job = next(j for j in bg_get_active_all() if j["id"] == "c2")
        assert job["status"] == "active"
        assert "fire_count" not in json.loads(job["config"])

    @pytest.mark.asyncio
    async def test_fire_skips_when_should_fire_false(self, db, mgr_mock):
        from app.bg_jobs import BgJobManager
        from app.db import bg_save_job, bg_cancel_job
        mgr = BgJobManager()
        m, sess = mgr_mock
        mgr.set_session_manager(m)
        now = datetime.now(timezone.utc)
        bg_save_job({
            "id": "c3", "type": "cron", "config": json.dumps({"cron_expr": "* * * * *"}),
            "message": "ping", "target_session_id": "s-1", "target_name": "w1",
            "target_scope": "/s", "created_by_name": "orch", "status": "active",
            "expires_at": (now + timedelta(hours=1)).isoformat(),
            "trigger_at": None, "created_at": now.isoformat(), "last_output": "",
        })
        bg_cancel_job("c3")
        await mgr._fire_cron("c3", "ping", "w1", "/s")
        sess.send.assert_not_awaited()


class TestRunCron:
    @pytest.mark.asyncio
    async def test_computes_next_and_fires_then_cancels(self, db, monkeypatch):
        from app.bg_jobs import BgJobManager
        import app.bg_jobs as bj
        mgr = BgJobManager()
        fired = {"n": 0}

        async def fake_fire(job_id, message, target_name, target_scope):
            fired["n"] += 1
            if fired["n"] >= 2:
                # simulate cancellation arriving — _run_cron must swallow it cleanly
                raise asyncio.CancelledError()

        slept = []

        async def fake_sleep(s):
            slept.append(s)

        monkeypatch.setattr(mgr, "_fire_cron", fake_fire)
        monkeypatch.setattr(bj.asyncio, "sleep", fake_sleep)
        # _run_cron swallows CancelledError → returns without raising
        await mgr._run_cron("c4", "* * * * *", "ping", "w1", "/s", None)
        assert fired["n"] == 2
        # sleep was called with the computed next-fire delay (<= 60s for * * * * *)
        assert slept and all(0 <= s <= 60 for s in slept)


class TestRunExecOutcome:
    @staticmethod
    def _job(job_id, now):
        return {
            "id": job_id, "type": "run", "config": json.dumps({"command": "true"}),
            "message": "review done", "target_session_id": "s-1", "target_name": "w1",
            "target_scope": "/s", "created_by_name": "orch", "status": "active",
            "expires_at": (now + timedelta(hours=1)).isoformat(),
            "trigger_at": None, "created_at": now.isoformat(), "last_output": "",
        }

    @pytest.mark.asyncio
    async def test_nonzero_exit_is_failed_not_completed(self, db, mgr_mock):
        from app.bg_jobs import BgJobManager
        from app.db import bg_get_jobs, bg_save_job
        mgr = BgJobManager()
        manager, session = mgr_mock
        mgr.set_session_manager(manager)
        bg_save_job(self._job("run-fail", datetime.now(timezone.utc)))

        await mgr._run_exec("run-fail", "exit 7", "review done", "w1", "/s", 10)

        row = next(j for j in bg_get_jobs(scope="/s") if j["id"] == "run-fail")
        assert row["status"] == "failed"
        assert "exit code 7" in row["error"].lower()
        sent = session.send.await_args.args[0]
        assert "FAILED" in sent
        assert "completed" not in sent.lower()

    @pytest.mark.asyncio
    async def test_finishes_when_child_keeps_stdout_open(self, db, mgr_mock):
        from app.bg_jobs import BgJobManager
        from app.db import bg_get_jobs, bg_save_job
        mgr = BgJobManager()
        manager, session = mgr_mock
        mgr.set_session_manager(manager)
        bg_save_job(self._job("run-open-pipe", datetime.now(timezone.utc)))

        await asyncio.wait_for(
            mgr._run_exec(
                "run-open-pipe",
                "/usr/bin/python3 -c 'import os,time; os.fork() and os._exit(0); time.sleep(30)'",
                "review done", "w1", "/s", 10,
            ),
            timeout=12,
        )

        row = next(j for j in bg_get_jobs(scope="/s") if j["id"] == "run-open-pipe")
        assert row["status"] == "triggered"
        session.send.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_exit_zero_requires_declared_artifact(self, db, mgr_mock, tmp_path):
        from app.bg_jobs import BgJobManager
        from app.db import bg_get_jobs, bg_save_job
        mgr = BgJobManager()
        manager, session = mgr_mock
        mgr.set_session_manager(manager)
        bg_save_job(self._job("run-no-artifact", datetime.now(timezone.utc)))

        await mgr._run_exec(
            "run-no-artifact", "true", "review done", "w1", "/s", 10,
            success_file=str(tmp_path / "missing.md"),
        )

        row = next(j for j in bg_get_jobs(scope="/s") if j["id"] == "run-no-artifact")
        assert row["status"] == "failed"
        assert "artifact" in row["error"].lower()
        assert "FAILED" in session.send.await_args.args[0]
