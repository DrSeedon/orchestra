"""Tests for bg_jobs.py cron support (#26)."""

import asyncio
import json
import os
import signal
import sys
import threading
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.events import MessageProvenance
from app.pidfd_exec import group_signal_supported


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
    sess.id = "s-1"
    sess.send = AsyncMock()
    m.ensure_loaded = AsyncMock(return_value=sess)
    m.ensure_loaded_any = AsyncMock(return_value=sess)
    # #82: пробуждение идёт по неизменяемому id, а не по имени.
    m.ensure_loaded_by_id = AsyncMock(return_value=sess)

    async def deliver(_session_id, message, *, provenance):
        assert isinstance(provenance, MessageProvenance)
        assert provenance.senders
        await sess.send(message)

    m.send = AsyncMock(side_effect=deliver)
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

    def test_cron_command_requires_command_and_pattern(self):
        from app.bg_jobs import _validate_config

        assert _validate_config(
            "cron_command", {"cron_expr": "*/5 * * * *"}
        ) == "command is required"
        assert _validate_config(
            "cron_command",
            {"cron_expr": "*/5 * * * *", "command": "python monitor.py"},
        ) == "pattern is required"

    def test_cron_command_rejects_invalid_regex(self):
        from app.bg_jobs import _validate_config

        error = _validate_config("cron_command", {
            "cron_expr": "*/5 * * * *",
            "command": "python monitor.py",
            "pattern": "[",
        })

        assert error and "invalid regex" in error


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

    @pytest.mark.asyncio
    @pytest.mark.parametrize("job_type", ["file", "command", "ssh", "cron_command"])
    async def test_zero_timeout_means_forever_for_watchers(
        self, db, monkeypatch, job_type,
    ):
        from app.bg_jobs import BgJobManager
        from app.db import bg_get_active_all

        configs = {
            "file": {"path": "/tmp/watch.log", "pattern": "MATCH"},
            "command": {
                "command": "python monitor.py",
                "pattern": "MATCH",
                "interval_seconds": 60,
            },
            "ssh": {
                "host": "example",
                "command": "journalctl -f",
                "pattern": "MATCH",
            },
            "cron_command": {
                "cron_expr": "*/5 * * * *",
                "command": "python monitor.py",
                "pattern": "MATCH",
            },
        }
        mgr = BgJobManager()
        started = []
        monkeypatch.setattr(
            mgr, "_start_task", lambda *args, **kwargs: started.append(args),
        )

        result = await mgr.create(
            job_type, configs[job_type], "found",
            f"s-{job_type}", f"w-{job_type}", "/s", "orch",
            timeout_seconds=0,
        )

        row = next(
            job for job in bg_get_active_all()
            if job["id"] == result["id"]
        )
        assert json.loads(row["config"])["no_expiry"] is True
        assert started[0][7] == 0
        assert (
            datetime.fromisoformat(row["expires_at"])
            - datetime.now(timezone.utc)
        ).days > 1000

    @pytest.mark.asyncio
    async def test_no_expiry_reaches_cron_command_runner_as_none(self):
        from app.bg_jobs import BgJobManager

        mgr = BgJobManager()
        run_cron = AsyncMock()
        mgr._run_cron = run_cron

        mgr._start_task(
            "cron-command-forever",
            "cron_command",
            {
                "cron_expr": "*/5 * * * *",
                "command": "python monitor.py",
                "pattern": "MATCH",
                "no_expiry": True,
            },
            "found",
            "s-1",
            "w1",
            "/s",
            0,
        )
        await mgr._tasks["cron-command-forever"]

        assert run_cron.await_args.args[5] is None
        assert run_cron.await_args.kwargs == {
            "command": "python monitor.py",
            "pattern": "MATCH",
        }


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
        m.send.assert_awaited_once()
        assert m.send.await_args.args == ("s-1", "[Cron job fired] ping")
        provenance = m.send.await_args.kwargs["provenance"]
        assert provenance == MessageProvenance(
            origin="background_task", senders=("c1",), subtype="cron", ref="c1",
        )
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
        # #82: цель ищется по id — без этого мока тест зеленел бы на TypeError в except.
        m.ensure_loaded_by_id = AsyncMock(return_value=None)
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


class TestCronCommand:
    @staticmethod
    def _job(job_id, now):
        return {
            "id": job_id,
            "type": "cron_command",
            "config": json.dumps({
                "cron_expr": "*/5 * * * *",
                "command": "python monitor.py",
                "pattern": "ALERT",
            }),
            "message": "monitor found work",
            "target_session_id": "s-1",
            "target_name": "w1",
            "target_scope": "/s",
            "created_by_name": "orch",
            "status": "active",
            "expires_at": (now + timedelta(hours=1)).isoformat(),
            "trigger_at": None,
            "created_at": now.isoformat(),
            "last_output": "",
        }

    @staticmethod
    def _proc(output=b"", error=b"", returncode=0):
        return type("Process", (), {
            "pid": 12345,
            "returncode": returncode,
            "output": output,
            "error": error,
        })()

    @pytest.mark.asyncio
    async def test_four_no_match_fires_do_not_wake_and_stay_active(
        self, db, mgr_mock, monkeypatch,
    ):
        import app.bg_jobs as module
        from app.bg_jobs import BgJobManager
        from app.db import bg_get_active_all, bg_save_job

        mgr = BgJobManager()
        manager, session = mgr_mock
        mgr.set_session_manager(manager)
        bg_save_job(self._job("cron-command-empty", datetime.now(timezone.utc)))
        processes = [
            self._proc(output=f"empty-{index}".encode())
            for index in range(4)
        ]
        create = AsyncMock(side_effect=processes)
        monkeypatch.setattr(module, "_spawn_bg_process", create)
        monkeypatch.setattr(module, "_kill_proc", AsyncMock())

        async def communicate(proc):
            return proc.output, proc.error

        monkeypatch.setattr(module, "_communicate_cron_command", communicate)

        for _ in range(4):
            await mgr._fire_cron_command(
                "cron-command-empty",
                "python monitor.py",
                "ALERT",
                "monitor found work",
                "w1",
                "/s",
            )

        assert create.await_count == 4
        manager.ensure_loaded.assert_not_awaited()
        session.send.assert_not_awaited()
        row = next(
            job for job in bg_get_active_all()
            if job["id"] == "cron-command-empty"
        )
        assert row["status"] == "active"
        assert row["last_output"] == "empty-3"

    @pytest.mark.asyncio
    async def test_completed_nonzero_match_wakes_and_remains_active(
        self, db, mgr_mock, monkeypatch,
    ):
        import app.bg_jobs as module
        from app.bg_jobs import BgJobManager
        from app.db import bg_get_active_all, bg_save_job

        mgr = BgJobManager()
        manager, session = mgr_mock
        session.parent_name = "parent-orchestrator"
        session.last_task_sender = ""
        mgr.set_session_manager(manager)
        bg_save_job(self._job("cron-command-match", datetime.now(timezone.utc)))
        proc = self._proc(output=b"ALERT: item 42\n", returncode=7)
        monkeypatch.setattr(module, "_spawn_bg_process", AsyncMock(return_value=proc))
        monkeypatch.setattr(module, "_kill_proc", AsyncMock())

        async def communicate(process):
            return process.output, process.error

        monkeypatch.setattr(module, "_communicate_cron_command", communicate)

        await mgr._fire_cron_command(
            "cron-command-match",
            "python monitor.py",
            "ALERT",
            "monitor found work",
            "w1",
            "/s",
        )

        sent = session.send.await_args.args[0]
        assert "monitor found work" in sent
        assert "ALERT: item 42" in sent
        assert "exit code 7" in sent
        assert session.last_task_sender == "parent-orchestrator"
        row = next(
            job for job in bg_get_active_all()
            if job["id"] == "cron-command-match"
        )
        assert row["status"] == "active"
        config = json.loads(row["config"])
        assert config["fire_count"] == 1
        assert "ALERT: item 42" in row["last_output"]

    @pytest.mark.asyncio
    async def test_empty_output_never_wakes_even_if_regex_matches_empty(
        self, db, mgr_mock, monkeypatch,
    ):
        import app.bg_jobs as module
        from app.bg_jobs import BgJobManager
        from app.db import bg_save_job

        mgr = BgJobManager()
        manager, session = mgr_mock
        mgr.set_session_manager(manager)
        bg_save_job(self._job("cron-command-empty-output", datetime.now(timezone.utc)))
        proc = self._proc()
        monkeypatch.setattr(module, "_spawn_bg_process", AsyncMock(return_value=proc))
        monkeypatch.setattr(module, "_kill_proc", AsyncMock())

        async def communicate(process):
            return process.output, process.error

        monkeypatch.setattr(module, "_communicate_cron_command", communicate)

        await mgr._fire_cron_command(
            "cron-command-empty-output",
            "python monitor.py",
            ".*",
            "monitor found work",
            "w1",
            "/s",
        )

        manager.ensure_loaded.assert_not_awaited()
        session.send.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_timeout_never_wakes_even_after_partial_match(
        self, db, mgr_mock, monkeypatch,
    ):
        import app.bg_jobs as module
        from app.bg_jobs import BgJobManager
        from app.db import bg_get_active_all, bg_save_job

        mgr = BgJobManager()
        manager, session = mgr_mock
        mgr.set_session_manager(manager)
        bg_save_job(self._job("cron-command-timeout", datetime.now(timezone.utc)))
        proc = self._proc(output=b"ALERT: partial\n", returncode=None)
        monkeypatch.setattr(module, "_spawn_bg_process", AsyncMock(return_value=proc))

        async def timeout(_process):
            raise asyncio.TimeoutError

        killed = AsyncMock()
        monkeypatch.setattr(module, "_communicate_cron_command", timeout)
        monkeypatch.setattr(module, "_kill_proc", killed)

        await mgr._fire_cron_command(
            "cron-command-timeout",
            "python monitor.py",
            "ALERT",
            "monitor found work",
            "w1",
            "/s",
        )

        manager.ensure_loaded.assert_not_awaited()
        session.send.assert_not_awaited()
        killed.assert_awaited_once_with(proc)
        row = next(
            job for job in bg_get_active_all()
            if job["id"] == "cron-command-timeout"
        )
        assert row["status"] == "active"
        assert "timed out after 30 seconds" in row["last_output"]

    @pytest.mark.asyncio
    async def test_cancellation_while_communicate_blocked_kills_process(
        self, db, mgr_mock, monkeypatch,
    ):
        import app.bg_jobs as module
        from app.bg_jobs import BgJobManager
        from app.db import bg_save_job

        mgr = BgJobManager()
        manager, _session = mgr_mock
        mgr.set_session_manager(manager)
        bg_save_job(self._job("cron-command-cancel", datetime.now(timezone.utc)))
        proc = self._proc(returncode=None)
        monkeypatch.setattr(module, "_spawn_bg_process", AsyncMock(return_value=proc))
        communicating = asyncio.Event()
        never = asyncio.Event()

        async def blocked(_process):
            communicating.set()
            await never.wait()

        killed = AsyncMock()
        monkeypatch.setattr(module, "_communicate_cron_command", blocked)
        monkeypatch.setattr(module, "_kill_proc", killed)
        task = asyncio.create_task(mgr._fire_cron_command(
            "cron-command-cancel",
            "python monitor.py",
            "ALERT",
            "monitor found work",
            "w1",
            "/s",
        ))
        await communicating.wait()

        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

        killed.assert_awaited_once_with(proc)
        assert "cron-command-cancel" not in mgr._procs


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
    async def test_completed_job_restores_parent_report_provenance(
        self, db, mgr_mock
    ):
        from app.bg_jobs import BgJobManager
        from app.db import bg_save_job

        mgr = BgJobManager()
        manager, session = mgr_mock
        session.parent_name = "parent-orchestrator"
        session.last_task_sender = ""
        mgr.set_session_manager(manager)
        bg_save_job(self._job("run-parent", datetime.now(timezone.utc)))

        await mgr._trigger(
            "run-parent",
            "review done",
            "w1",
            "/s",
            "review output",
        )

        assert session.last_task_sender == "parent-orchestrator"
        session.send.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_reports_child_that_keeps_stdout_open_before_safe_cleanup(
        self, db, mgr_mock, caplog, monkeypatch,
    ):
        from app.bg_jobs import BgJobManager
        from app.db import bg_get_jobs, bg_save_job

        caplog.set_level("WARNING", logger="app.bg_jobs")
        mgr = BgJobManager()
        manager, session = mgr_mock
        mgr.set_session_manager(manager)
        bg_save_job(self._job("run-open-pipe", datetime.now(timezone.utc)))

        await asyncio.wait_for(
            mgr._run_exec(
                "run-open-pipe",
                "/usr/bin/python3 -c 'import os,time; os.fork() and os._exit(0); time.sleep(3.5)'",
                "review done", "w1", "/s", 10,
            ),
            timeout=12,
        )

        row = next(j for j in bg_get_jobs(scope="/s") if j["id"] == "run-open-pipe")
        assert row["status"] == "triggered"
        session.send.assert_awaited_once()
        assert "orphan_tree=1" in caplog.text
        assert "oldest_process_age_seconds=" in caplog.text
        assert "observation_only=true" in caplog.text

    @pytest.mark.asyncio
    async def test_cancellation_after_leader_exit_closes_transport(
        self, db, mgr_mock, monkeypatch,
    ):
        from app.bg_jobs import BgJobManager
        from app.db import bg_save_job

        mgr = BgJobManager()
        manager, _ = mgr_mock
        mgr.set_session_manager(manager)
        bg_save_job(self._job("run-cancel-open-pipe", datetime.now(timezone.utc)))
        task = asyncio.create_task(mgr._run_exec(
            "run-cancel-open-pipe",
            "/usr/bin/python3 -c 'import os,time; os.fork() and os._exit(0); time.sleep(3.5)'",
            "review done", "w1", "/s", 10,
        ))

        for _ in range(100):
            proc = mgr._procs.get("run-cancel-open-pipe")
            if proc and proc.returncode is not None:
                break
            await asyncio.sleep(0.01)
        else:
            pytest.fail("job leader did not exit")

        transport = proc._transport
        close = MagicMock(wraps=transport.close)
        monkeypatch.setattr(transport, "close", close)
        task.cancel()
        await asyncio.wait_for(task, timeout=2)
        close.assert_called()

    @pytest.mark.asyncio
    async def test_orphan_scan_runs_off_event_loop(
        self, db, mgr_mock, monkeypatch,
    ):
        import app.bg_jobs as module
        from app.bg_jobs import BgJobManager
        from app.db import bg_save_job

        caller_thread = threading.get_ident()
        scan_threads = []

        def observe(_session_id):
            scan_threads.append(threading.get_ident())
            return 0, 0.0

        monkeypatch.setattr(module, "_orphan_session_stats", observe)
        mgr = BgJobManager()
        manager, _ = mgr_mock
        mgr.set_session_manager(manager)
        bg_save_job(self._job("run-threaded-observe", datetime.now(timezone.utc)))

        await mgr._run_exec(
            "run-threaded-observe", "true", "review done", "w1", "/s", 10,
        )

        assert scan_threads and scan_threads[0] != caller_thread

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

    @pytest.mark.asyncio
    async def test_exit_zero_blind_artifact_without_verdict_is_failed(
        self, db, mgr_mock, tmp_path,
    ):
        """#180 oracle: rc=0 + existing file is not a completed review.

        Fixture is the #174 opening: no ## Verdict, starts with the admission
        that the review never happened. Today's _run_exec treats this as success.
        """
        artifact = tmp_path / "codex-review-plan.md"
        artifact.write_text(
            "Unable to perform an evidence-backed review: "
            "the filesystem sandbox failed before every read-only command.\n",
            encoding="utf-8",
        )
        from app.bg_jobs import BgJobManager
        from app.db import bg_get_jobs, bg_save_job
        mgr = BgJobManager()
        manager, session = mgr_mock
        mgr.set_session_manager(manager)
        bg_save_job(self._job("run-blind", datetime.now(timezone.utc)))

        await mgr._run_exec(
            "run-blind", "true",
            "Codex review → .orchestra/tasks/174/codex-review-plan.md",
            "w1", "/s", 10,
            success_file=str(artifact),
        )

        row = next(j for j in bg_get_jobs(scope="/s") if j["id"] == "run-blind")
        assert row["status"] == "failed", row
        sent = session.send.await_args.args[0]
        assert "FAILED" in sent
        assert "completed" not in sent.lower()
        err = (row.get("error") or "").lower()
        assert "verdict" in err or "blind" in err or "unable" in err

    @pytest.mark.asyncio
    async def test_exit_zero_real_verdict_still_completes(self, db, mgr_mock, tmp_path):
        artifact = tmp_path / "CODEX_REVIEW.md"
        artifact.write_text("## Summary\nlooks good\n\n## Verdict\nAPPROVED\n")
        from app.bg_jobs import BgJobManager
        from app.db import bg_get_jobs, bg_save_job
        mgr = BgJobManager()
        manager, session = mgr_mock
        mgr.set_session_manager(manager)
        bg_save_job(self._job("run-ok", datetime.now(timezone.utc)))

        await mgr._run_exec(
            "run-ok", "true", "Codex review → CODEX_REVIEW.md",
            "w1", "/s", 10,
            success_file=str(artifact),
        )

        row = next(j for j in bg_get_jobs(scope="/s") if j["id"] == "run-ok")
        assert row["status"] == "triggered"
        assert "FAILED" not in session.send.await_args.args[0]

    @pytest.mark.asyncio
    async def test_exit_zero_verdict_with_bwrap_is_still_blind(
        self, db, mgr_mock, tmp_path,
    ):
        artifact = tmp_path / "codex-review-impl.md"
        artifact.write_text(
            "bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted\n\n"
            "## Verdict\nAPPROVED\n"
        )
        from app.bg_jobs import BgJobManager
        from app.db import bg_get_jobs, bg_save_job
        mgr = BgJobManager()
        manager, session = mgr_mock
        mgr.set_session_manager(manager)
        bg_save_job(self._job("run-bwrap", datetime.now(timezone.utc)))

        await mgr._run_exec(
            "run-bwrap", "true", "Codex review → .orchestra/tasks/179/codex-review-impl.md",
            "w1", "/s", 10,
            success_file=str(artifact),
        )

        row = next(j for j in bg_get_jobs(scope="/s") if j["id"] == "run-bwrap")
        assert row["status"] == "failed"
        assert "blind" in (row.get("error") or "").lower()

    @pytest.mark.asyncio
    async def test_exit_zero_verdict_mentioning_sandbox_is_not_blind(
        self, db, mgr_mock, tmp_path,
    ):
        artifact = tmp_path / "CODEX_REVIEW.md"
        artifact.write_text(
            "## Findings\nThe sandbox fails closed on unknown roles.\n\n"
            "## Verdict\nAPPROVED\n"
        )
        from app.bg_jobs import BgJobManager
        from app.db import bg_get_jobs, bg_save_job
        mgr = BgJobManager()
        manager, session = mgr_mock
        mgr.set_session_manager(manager)
        bg_save_job(self._job("run-sandbox-talk", datetime.now(timezone.utc)))

        await mgr._run_exec(
            "run-sandbox-talk", "true", "Codex review → CODEX_REVIEW.md",
            "w1", "/s", 10,
            success_file=str(artifact),
        )

        row = next(j for j in bg_get_jobs(scope="/s") if j["id"] == "run-sandbox-talk")
        assert row["status"] == "triggered"


class TestRestartProcessSafety:
    @staticmethod
    def _job(job_id, job_type, config):
        now = datetime.now(timezone.utc)
        return {
            "id": job_id, "type": job_type, "config": json.dumps(config),
            "message": "background task", "target_session_id": "s-1",
            "target_name": "w1", "target_scope": "/s", "created_by_name": "orch",
            "status": "active", "expires_at": (now + timedelta(hours=1)).isoformat(),
            "trigger_at": None, "created_at": now.isoformat(), "last_output": "",
        }

    @pytest.mark.asyncio
    async def test_restore_marks_active_run_interrupted_without_restarting(
        self, db, mgr_mock, monkeypatch,
    ):
        import app.bg_jobs as module
        from app.bg_jobs import BgJobManager
        from app.db import bg_get_jobs, bg_save_job

        mgr = BgJobManager()
        manager, session = mgr_mock
        mgr.set_session_manager(manager)
        bg_save_job(self._job("run-restart", "run", {"command": "side-effect"}))
        started = MagicMock()
        monkeypatch.setattr(mgr, "_start_task", started)

        await mgr.restore_from_db()

        started.assert_not_called()
        row = next(j for j in bg_get_jobs(scope="/s") if j["id"] == "run-restart")
        assert row["status"] == "failed"
        reason = "Прерван рестартом сервиса, повторный запуск не выполнялся"
        assert reason in row["error"]
        session.send.assert_awaited_once()
        assert reason in session.send.await_args.args[0].text
        assert module.bg_get_active_all() == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("job_type", "config"),
        [
            ("timer", {"delay_seconds": 10}),
            ("file", {"path": "/tmp/events.log", "pattern": "MATCH"}),
            ("command", {"command": "printf MATCH", "pattern": "MATCH"}),
            ("ssh", {"host": "example", "command": "journalctl", "pattern": "MATCH"}),
            ("cron", {"cron_expr": "*/5 * * * *"}),
            ("cron_command", {
                "cron_expr": "*/5 * * * *", "command": "printf MATCH", "pattern": "MATCH",
            }),
        ],
    )
    async def test_restore_keeps_non_run_types_restartable(
        self, db, monkeypatch, job_type, config,
    ):
        from app.bg_jobs import BgJobManager
        from app.db import bg_save_job

        mgr = BgJobManager()
        bg_save_job(self._job(f"restore-{job_type}", job_type, config))
        started = MagicMock()
        monkeypatch.setattr(mgr, "_start_task", started)

        await mgr.restore_from_db()

        started.assert_called_once()
        assert started.call_args.args[1] == job_type

    @pytest.mark.asyncio
    async def test_cancel_during_spawn_kills_unregistered_process(
        self, db, monkeypatch,
    ):
        import app.bg_jobs as module
        from app.bg_jobs import BgJobManager
        from app.db import bg_save_job

        mgr = BgJobManager()
        bg_save_job(self._job("run-spawn-cancel", "run", {"command": "side-effect"}))
        spawned = asyncio.Event()
        release = asyncio.Event()
        proc = type("Process", (), {"pid": 123, "returncode": None})()

        async def spawn(*_args, **_kwargs):
            spawned.set()
            await release.wait()
            return proc

        killed = AsyncMock()
        monkeypatch.setattr(module, "_spawn_bg_process", spawn)
        monkeypatch.setattr(module, "_kill_proc", killed)
        task = asyncio.create_task(
            mgr._run_exec("run-spawn-cancel", "side-effect", "background task", "w1", "/s", 10)
        )
        await spawned.wait()
        task.cancel()
        release.set()
        await asyncio.gather(task, return_exceptions=True)

        killed.assert_awaited_once_with(proc)
        assert "run-spawn-cancel" not in mgr._procs

    @pytest.mark.asyncio
    async def test_shutdown_kill_failure_does_not_skip_other_processes(
        self, monkeypatch, caplog,
    ):
        import app.bg_jobs as module
        from app.bg_jobs import BgJobManager

        mgr = BgJobManager()
        first = object()
        second = object()
        mgr._procs = {"first": first, "second": second}
        killed = AsyncMock(side_effect=[RuntimeError("pidfd missing"), None])
        monkeypatch.setattr(module, "_kill_proc", killed)
        caplog.set_level("ERROR", logger="app.bg_jobs")

        await mgr.shutdown()

        assert killed.await_args_list == [
            ((first,),), ((second,),),
        ]
        assert "first" in caplog.text
        assert "RuntimeError" in caplog.text
        assert mgr._procs == {}


class TestPidfdProcessLifecycle:
    @pytest.mark.asyncio
    async def test_shell_and_argv_modes_preserve_arguments(self):
        from app.bg_jobs import _kill_proc, _spawn_bg_process

        argv_proc = await _spawn_bg_process(
            ["/usr/bin/printf", "%s", "argv value"],
            shell=False,
            stdout=asyncio.subprocess.PIPE,
        )
        argv_output, _ = await argv_proc.communicate()
        await _kill_proc(argv_proc)

        shell_proc = await _spawn_bg_process(
            "printf '%s' 'shell value'",
            shell=True,
            stdout=asyncio.subprocess.PIPE,
        )
        shell_output, _ = await shell_proc.communicate()
        await _kill_proc(shell_proc)

        assert argv_output == b"argv value"
        assert shell_output == b"shell value"

    @pytest.mark.asyncio
    async def test_unsupported_group_signal_fails_before_target_exec(
        self, tmp_path, monkeypatch,
    ):
        import app.bg_jobs as module

        marker = tmp_path / "must-not-exist"
        monkeypatch.setattr(module, "pidfd_send_group", lambda _fd, _sig: False)

        with pytest.raises(RuntimeError, match="disappeared before exec ACK"):
            await module._spawn_bg_process(
                f"touch {marker}", shell=True,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )

        assert not marker.exists()

    @pytest.mark.asyncio
    async def test_cancelled_handshake_never_executes_target(
        self, tmp_path, monkeypatch,
    ):
        import app.bg_jobs as module

        marker = tmp_path / "must-not-exist"
        receiving = asyncio.Event()

        async def blocked_receive(_control):
            receiving.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(module, "_recv_pidfd", blocked_receive)
        task = asyncio.create_task(module._spawn_bg_process(
            f"touch {marker}", shell=True,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        ))
        await receiving.wait()
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task
        assert not marker.exists()

    @pytest.mark.asyncio
    async def test_concurrent_cleanup_is_single_and_cancellation_shielded(
        self, monkeypatch,
    ):
        import app.bg_jobs as module

        class Process:
            pid = 12345
            _orchestra_cleanup_task = None

        proc = Process()
        started = asyncio.Event()
        release = asyncio.Event()
        calls = 0

        async def cleanup(_proc):
            nonlocal calls
            calls += 1
            started.set()
            await release.wait()

        monkeypatch.setattr(module, "_cleanup_pidfd_group", cleanup)
        first = asyncio.create_task(module._kill_proc(proc))
        await started.wait()
        second = asyncio.create_task(module._kill_proc(proc))
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert not second.done()

        release.set()
        await second
        await module._kill_proc(proc)
        assert calls == 1

    @pytest.mark.asyncio
    async def test_live_leader_and_child_are_terminated_but_unrelated_survives(self):
        from app.bg_jobs import _kill_proc, _spawn_bg_process

        code = """
import os
import time
child = os.fork()
if child == 0:
    time.sleep(30)
    os._exit(0)
print(child, flush=True)
time.sleep(30)
"""
        proc = await _spawn_bg_process(
            [sys.executable, "-c", code],
            shell=False,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        child_pid = int((await asyncio.wait_for(proc.stdout.readline(), 2)).decode())
        unrelated = await asyncio.create_subprocess_exec(
            "/bin/sleep", "30", start_new_session=True,
        )
        try:
            await _kill_proc(proc)
            assert proc.returncode == -signal.SIGTERM
            assert not os.path.exists(f"/proc/{child_pid}")
            assert unrelated.returncode is None
        finally:
            if unrelated.returncode is None:
                unrelated.terminate()
            await unrelated.wait()

    @pytest.mark.skipif(
        not group_signal_supported(),
        reason=(
            "reaching a group AFTER its leader is reaped requires "
            "PIDFD_SIGNAL_PROCESS_GROUP (Linux 6.9+). Below that the pidfd is the only "
            "safe anchor and it goes blank on reaping, so the killpg fallback reports "
            "the group gone rather than signal a possibly recycled pgid. Deliberately "
            "weaker: leaking an orphan beats killing a stranger's process group."
        ),
    )
    @pytest.mark.asyncio
    async def test_reaped_leader_retains_group_identity_for_kill_escalation(
        self, tmp_path, monkeypatch,
    ):
        import app.bg_jobs as module

        child_file = tmp_path / "child.pid"
        code = f"""
import os
import signal
import time
child = os.fork()
if child == 0:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    with open({str(child_file)!r}, "w") as fh:
        fh.write(str(os.getpid()))
    while True:
        time.sleep(30)
os._exit(0)
"""
        proc = await module._spawn_bg_process(
            [sys.executable, "-c", code],
            shell=False,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.wait(), 2)
        # open(..., "w") creates the file before the pid is written — waiting on
        # existence alone reads an empty file on a loaded machine.
        for _ in range(500):
            recorded = (
                child_file.read_text() if child_file.exists() else ""
            ).strip()
            if recorded:
                break
            await asyncio.sleep(0.01)
        else:
            pytest.fail("TERM-ignoring child did not start")
        child_pid = int(recorded)
        unrelated = await asyncio.create_subprocess_exec(
            "/bin/sleep", "30", start_new_session=True,
        )
        sent = []
        real_send = module.pidfd_send_group

        def record_send(pidfd, sig):
            sent.append(sig)
            return real_send(pidfd, sig)

        monkeypatch.setattr(module, "pidfd_send_group", record_send)
        monkeypatch.setattr(module, "_PIDFD_TERM_GRACE", 0.05)
        monkeypatch.setattr(module, "_PIDFD_KILL_GRACE", 0.5)
        monkeypatch.setattr(module, "_PIDFD_POLL_INTERVAL", 0.01)
        try:
            await module._kill_proc(proc)
            assert signal.SIGTERM in sent
            assert signal.SIGKILL in sent
            assert not os.path.exists(f"/proc/{child_pid}")
            assert unrelated.returncode is None
        finally:
            if unrelated.returncode is None:
                unrelated.terminate()
            await unrelated.wait()


class TestWakeByImmutableId:
    """#82: имя цели могло смениться или уже принадлежать ДРУГОМУ агенту."""

    @staticmethod
    def _job(job_id, now, *, session_id="s-1", name="w1"):
        return {
            "id": job_id, "type": "run", "config": json.dumps({"command": "true"}),
            "message": "review done", "target_session_id": session_id,
            "target_name": name, "target_scope": "/s", "created_by_name": "orch",
            "status": "active",
            "expires_at": (now + timedelta(hours=1)).isoformat(),
            "trigger_at": None, "created_at": now.isoformat(), "last_output": "",
        }

    @pytest.mark.asyncio
    async def test_renamed_target_is_woken_by_id_not_by_stale_name(self, db, mgr_mock):
        from app.bg_jobs import BgJobManager
        from app.db import bg_save_job

        mgr = BgJobManager()
        manager, session = mgr_mock
        mgr.set_session_manager(manager)
        bg_save_job(self._job("wake-renamed", datetime.now(timezone.utc)))

        # Имя в джобе — то, что было при создании; сессия давно называется иначе.
        await mgr._trigger("wake-renamed", "review done", "old-name", "/s", "")

        manager.ensure_loaded_by_id.assert_awaited_once_with("s-1")
        manager.ensure_loaded.assert_not_awaited()
        session.send.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_missing_session_id_fails_loud_without_falling_back_to_name(
        self, db, mgr_mock, caplog,
    ):
        from app.bg_jobs import BgJobManager
        from app.db import bg_get_jobs, bg_save_job

        caplog.set_level("ERROR", logger="app.bg_jobs")
        mgr = BgJobManager()
        manager, session = mgr_mock
        mgr.set_session_manager(manager)
        bg_save_job(self._job("wake-no-id", datetime.now(timezone.utc), session_id=""))

        await mgr._trigger("wake-no-id", "review done", "w1", "/s", "")

        manager.ensure_loaded.assert_not_awaited()
        manager.ensure_loaded_by_id.assert_not_awaited()
        session.send.assert_not_awaited()
        row = [j for j in bg_get_jobs() if j["id"] == "wake-no-id"][0]
        assert row["status"] == "failed"
        assert "target_session_id" in row["error"]
        assert "refusing to wake by name" in caplog.text

    @pytest.mark.asyncio
    async def test_vanished_session_is_reported_with_both_id_and_name(
        self, db, mgr_mock, caplog,
    ):
        from app.bg_jobs import BgJobManager
        from app.db import bg_save_job

        caplog.set_level("WARNING", logger="app.bg_jobs")
        mgr = BgJobManager()
        manager, session = mgr_mock
        manager.ensure_loaded_by_id = AsyncMock(return_value=None)
        mgr.set_session_manager(manager)
        bg_save_job(self._job("wake-gone", datetime.now(timezone.utc), session_id="s-gone"))

        await mgr._trigger("wake-gone", "review done", "w1", "/s", "")

        assert "s-gone" in caplog.text and "w1" in caplog.text
        session.send.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_archived_session_is_not_woken_even_though_row_exists(self, db):
        """ensure_loaded_by_id на настоящем менеджере: архивную сессию не будим."""
        from app.manager import SessionManager
        from app.db import save_session

        save_session({
            "id": "arch-1", "name": "gone", "scope": "/s", "cwd": "/s", "model": "m",
            "system_prompt": "", "status": "archived", "session_id": None,
            "cost_usd": 0.0, "worktree_path": "", "branch": "", "base_branch": "main",
            "is_orchestrator": False, "color": "",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None, "task_id": "", "needs_switch": 0,
        })
        manager = SessionManager()

        assert await manager.ensure_loaded_by_id("arch-1") is None
        assert await manager.ensure_loaded_by_id("does-not-exist") is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "outcome,expected_status",
    [
        ("completed", "triggered"),
        ("failed", "failed"),
        ("timed_out", "expired"),
    ],
)
async def test_t2_385_real_bg_result_uses_immutable_provenance_through_history(
    db, outcome, expected_status,
):
    """RED #385 R3: real bg results carry app-owned provenance, never a heading."""
    from dataclasses import FrozenInstanceError

    from app.bg_jobs import BgJobManager
    from app.db import (
        bg_get_job,
        bg_save_job,
        get_history_logs,
        get_logs_sync,
        save_session,
    )
    from app.session import AgentSession, AgentStatus

    now = datetime.now(timezone.utc)
    job_id = f"bg-provenance-385-{outcome}"
    session = AgentSession(
        id=f"session-provenance-385-{outcome}",
        name=f"worker-provenance-385-{outcome}",
        scope="/scope-385",
        cwd="/scope-385",
        model="gpt-5.6-sol",
        system_prompt="test",
        created_at=now,
    )
    session.is_orchestrator = True
    session.backend_type = "codex"
    session.status = AgentStatus.IDLE
    session._prompt_injected = True
    save_session(session._to_db_dict())

    class FakeBackend:
        def __init__(self):
            self.sent = []
            self.never = asyncio.Event()

        async def send(self, message):
            self.sent.append(message)

        async def events(self):
            await self.never.wait()
            if False:
                yield None

    backend = FakeBackend()
    session._backend = backend
    session._ensure_backend = AsyncMock(return_value=backend)
    session._refresh_stale_backend = AsyncMock()
    session._apply_pending_identity_restart = AsyncMock()
    session._apply_manifest_effort = AsyncMock()
    session._notify_scope_running = AsyncMock()
    session._persist = MagicMock()
    session._hibernate.schedule = MagicMock()

    deliveries = []

    class FakeManager:
        async def ensure_loaded_by_id(self, session_id):
            assert session_id == session.id
            return session

        async def send(self, session_id, message, *, provenance):
            assert session_id == session.id
            assert provenance is message.provenance
            deliveries.append(message)
            await session.send(message, provenance=provenance)

    jobs = BgJobManager()
    jobs.set_session_manager(FakeManager())
    bg_save_job({
        "id": job_id,
        "type": "run",
        "config": json.dumps({"command": "true"}),
        "message": "Codex review",
        "target_session_id": session.id,
        "target_name": session.name,
        "target_scope": session.scope,
        "created_by_name": session.name,
        "status": "active",
        "expires_at": (now + timedelta(hours=1)).isoformat(),
        "trigger_at": None,
        "created_at": now.isoformat(),
        "last_output": "",
    })

    try:
        if outcome == "completed":
            await jobs._trigger(
                job_id, "Codex review\nExit code: 0", session.name, session.scope,
                "## Verdict\nNEEDS WORK",
            )
            # The active -> triggering CAS remains the duplicate guard in this scope.
            await jobs._trigger(
                job_id, "Codex review\nExit code: 0", session.name, session.scope,
                "## Verdict\nNEEDS WORK",
            )
        elif outcome == "failed":
            await jobs._fail_notify(
                job_id, "Codex review", session.name, session.scope,
                "Process exited with exit code 7", "review failed",
            )
        else:
            await jobs._expire_notify(
                job_id, "Codex review", session.name, session.scope,
                600, "review timed out",
            )

        if session._log_futures:
            await asyncio.gather(*tuple(session._log_futures))

        assert len(deliveries) == 1
        delivery = deliveries[0]
        assert not isinstance(delivery, str)
        assert delivery.text.startswith("[Background job")
        assert delivery.provenance.origin == "background_task"
        assert delivery.provenance.senders == (job_id,)
        assert delivery.provenance.subtype == outcome
        assert delivery.provenance.ref == job_id
        assert delivery.event_id == f"bgjob:v1:{job_id}:{outcome}"
        with pytest.raises((FrozenInstanceError, AttributeError)):
            delivery.provenance = delivery.provenance

        assert len(backend.sent) == 1
        assert isinstance(backend.sent[0], str)
        assert "Codex review" in backend.sent[0]

        _snapshot, history = get_history_logs(session.id)
        user_rows = [row for row in history if row["type"] == "user_message"]
        assert len(user_rows) == 1
        assert user_rows[0]["event_id"] == delivery.event_id
        synced = [
            row for row in get_logs_sync(after_id=0, tail=20)["logs"]
            if row["session_id"] == session.id and row["type"] == "user_message"
        ]
        assert len(synced) == 1
        assert synced[0]["event_id"] == delivery.event_id
        assert bg_get_job(job_id)["status"] == expected_status
    finally:
        if session._listen_task and not session._listen_task.done():
            session._listen_task.cancel()
            await asyncio.gather(session._listen_task, return_exceptions=True)


@pytest.mark.asyncio
async def test_t2_385_running_bg_delivery_logs_provenance_once_then_queues_text(db):
    """RED #385: a real bg result racing deferred interrupt keeps one provenanced row."""
    from app.bg_jobs import BgJobManager
    from app.db import bg_save_job, get_history_logs, get_logs_sync, save_session
    from app.session import AgentSession, AgentStatus

    now = datetime.now(timezone.utc)
    job_id = "bg-provenance-385-queued"
    session = AgentSession(
        id="session-provenance-385-queued",
        name="worker-provenance-385-queued",
        scope="/scope-385",
        cwd="/scope-385",
        model="gpt-5.6-sol",
        system_prompt="test",
        created_at=now,
    )
    session.is_orchestrator = True
    session.backend_type = "codex"
    session.status = AgentStatus.RUNNING
    session._prompt_injected = True
    save_session(session._to_db_dict())

    class FakeBackend:
        def __init__(self):
            self.deferred_interrupt_pending = True
            self.sent = []
            self.never = asyncio.Event()

        async def send(self, message):
            self.sent.append(message)

        async def events(self):
            await self.never.wait()
            if False:
                yield None

    backend = FakeBackend()
    session._backend = backend
    session._ensure_backend = AsyncMock(return_value=backend)
    session._refresh_stale_backend = AsyncMock()
    session._apply_pending_identity_restart = AsyncMock()
    session._apply_manifest_effort = AsyncMock()
    session._persist = MagicMock()
    session._hibernate.schedule = MagicMock()

    deliveries = []

    class FakeManager:
        async def ensure_loaded_by_id(self, session_id):
            assert session_id == session.id
            return session

        async def send(self, session_id, message, *, provenance):
            assert session_id == session.id
            assert provenance is message.provenance
            deliveries.append(message)
            await session.send(message, provenance=provenance)

    jobs = BgJobManager()
    jobs.set_session_manager(FakeManager())
    bg_save_job({
        "id": job_id,
        "type": "run",
        "config": json.dumps({"command": "true"}),
        "message": "Codex review",
        "target_session_id": session.id,
        "target_name": session.name,
        "target_scope": session.scope,
        "created_by_name": session.name,
        "status": "active",
        "expires_at": (now + timedelta(hours=1)).isoformat(),
        "trigger_at": None,
        "created_at": now.isoformat(),
        "last_output": "",
    })

    try:
        await jobs._trigger(
            job_id, "Codex review\nExit code: 0", session.name, session.scope,
            "## Verdict\nNEEDS WORK",
        )
        if session._log_futures:
            await asyncio.gather(*tuple(session._log_futures))

        assert len(deliveries) == 1
        delivery = deliveries[0]
        assert not isinstance(delivery, str)
        assert delivery.event_id == f"bgjob:v1:{job_id}:completed"
        assert session._pending_messages == [delivery.text]
        assert backend.sent == []

        _snapshot, before = get_history_logs(session.id)
        before_users = [row for row in before if row["type"] == "user_message"]
        assert len(before_users) == 1
        assert before_users[0]["event_id"] == delivery.event_id

        backend.deferred_interrupt_pending = False
        session.status = AgentStatus.IDLE
        await session._flush_pending()
        if session._log_futures:
            await asyncio.gather(*tuple(session._log_futures))

        assert session._pending_messages == []
        assert backend.sent == [delivery.text]
        _snapshot, after = get_history_logs(session.id)
        after_users = [row for row in after if row["type"] == "user_message"]
        assert after_users == before_users
        synced = [
            row for row in get_logs_sync(after_id=0, tail=20)["logs"]
            if row["session_id"] == session.id and row["type"] == "user_message"
        ]
        assert len(synced) == 1
        assert synced[0]["event_id"] == delivery.event_id
    finally:
        if session._listen_task and not session._listen_task.done():
            session._listen_task.cancel()
            await asyncio.gather(session._listen_task, return_exceptions=True)
