"""V-1035: a platform cut resumes work without impersonating a user refusal."""

import asyncio
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from app import db, limit_wake, manager as manager_module
from app.events import MessageProvenance
from app.session_state import AgentStatus, platform_interruption_notice


class IsolatedDatabase:
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="v1035-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.db_patch = patch.object(db, "DB_PATH", self.root / "test.db")
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        db.init_db()

    def save_worker(self, *, status="running", native=None, task="V-1035"):
        with db._conn() as connection:
            connection.execute(
                "INSERT INTO sessions(id,name,scope,cwd,model,created_at,status,session_id,"
                "task_id,parent_name) VALUES (?,?,?,?,?,?,?,?,?,?)",
                ("worker-id", "worker", str(self.root), str(self.root),
                 "claude-sonnet-5-5[1m]", "2026-10-22", status, native, task, "parent"),
            )
        return db.get_session("worker-id")

    def log(self, content, *, kind="user_message", subtype="", origin="agent"):
        return db.add_log(
            "worker-id", datetime.now(timezone.utc), kind, content,
            provenance=MessageProvenance(origin=origin, senders=("parent",), subtype=subtype),
        )


class NoticeTests(IsolatedDatabase, unittest.TestCase):
    def assert_honest(self, text, reason, task="V-1035"):
        self.assertIn(f"interrupted by the platform ({reason})", text)
        self.assertIn("not stopped by anyone", text)
        self.assertIn("not a user refusal", text)
        self.assertIn("The user doesn't want to take this action right now", text)
        self.assertIn("not by the user", text)
        self.assertIn("may or may not have run", text)
        self.assertIn("check its effect before repeating it", text)
        self.assertIn(f"Check your working tree and continue task #{task}", text)
        self.assertIn("without waiting for your orchestrator", text)

    def test_saved_restart_explains_cli_refusal_before_restored_conversation(self):
        text = manager_module.restart_notice_text({"session_id": "native", "task_id": "V-1035"})
        self.assert_honest(text, "Orchestra restart")
        self.assertIn("saved conversation was restored", text)
        self.assertIn("bg_create keep running", text)
        self.assertNotIn("Commands running inside the turn were stopped", text)

    def test_unsaved_restart_replays_only_the_cut_turn_in_order(self):
        row = self.save_worker()
        self.log("old task")
        self.log("turn ended (end_turn, 1 turns)", kind="status")
        self.log("first instruction")
        self.log("second instruction")
        text = manager_module.restart_notice_text(row)
        self.assert_honest(text, "Orchestra restart")
        self.assertNotIn("old task", text)
        self.assertLess(text.index("first instruction"), text.index("second instruction"))
        self.assertLess(text.index("not a user refusal"), text.index("first instruction"))

    def test_legacy_row_without_task_binding_does_not_invent_an_id(self):
        row = self.save_worker(task="")
        text = manager_module.restart_notice_text(row)
        self.assertIn("continue your current task", text)
        self.assertNotIn("task #", text)
        self.assertNotIn("None", text)

    def test_backend_disconnect_is_honest_too(self):
        self.assert_honest(platform_interruption_notice("backend disconnect", "1035"),
                           "backend disconnect", "1035")

    def test_recovery_after_limit_is_not_filtered_as_an_incidental_system_notice(self):
        for subtype in ("restart", "runtime_reconnect", "limit_wake", "rules_link", ""):
            for origin in ("system", "platform"):
                with self.subTest(subtype=subtype, origin=origin):
                    rows = self.limited_rows(origin, subtype)
                    found = limit_wake._latest_limit_turn(rows)
                    expected = origin == "system" and subtype in {
                        "restart", "runtime_reconnect", "limit_wake",
                    }
                    self.assertEqual(found is not None, expected)

    @staticmethod
    def limited_rows(origin="agent", subtype=""):
        return [
            {"id": 1, "type": "user_message", "content": "continue", "origin": origin,
             "origin_detail": {"subtype": subtype}},
            {"id": 2, "type": "provider_limit", "content": json.dumps({
                "status": "rejected", "rate_limit_type": "five_hour",
            })},
            {"id": 3, "type": "status", "content": "turn ended (stop_sequence, 1 turns)"},
        ]

    def test_manual_stop_still_blocks_limit_recovery(self):
        rows = self.limited_rows("system", "restart")
        rows.append({"id": 4, "type": "status", "content": "interrupt requested"})
        self.assertIsNone(limit_wake._latest_limit_turn(rows))

    def test_invalid_legacy_provenance_does_not_break_limit_scan(self):
        for detail in (None, "bad json", [], {"subtype": []}, {"subtype": {}}):
            with self.subTest(detail=detail):
                rows = self.limited_rows("system")
                rows[0]["origin_detail"] = detail
                self.assertIsNone(limit_wake._latest_limit_turn(rows))

    def test_legacy_limit_error_is_still_recoverable_after_restart(self):
        rows = self.limited_rows("system", "restart")
        rows[1] = {"id": 2, "type": "error",
                   "content": "subscription limit — ждём сброса квоты. НЕ ретраим"}
        self.assertEqual(limit_wake._latest_limit_turn(rows), ("timed", 3))


class DeliveryTests(IsolatedDatabase, unittest.IsolatedAsyncioTestCase):
    async def test_reconnected_listener_sends_honest_continuation_with_provenance(self):
        from app.session import AgentSession

        attempts = 0

        async def events():
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("control channel disconnected")
            for event in ():
                yield event

        session = SimpleNamespace(
            name="worker", backend_type="claude", task_id="V-1035",
            status=AgentStatus.RUNNING, _backend=SimpleNamespace(events=events),
            _turn_gen=1, _turn_start_cancel_gen=0, _manually_interrupted=False,
            MAX_CONSECUTIVE_FAILURES=3, _log=Mock(), _reconnect_backend=AsyncMock(),
        )

        async def sent(*_args, **_kwargs):
            session.status = AgentStatus.IDLE

        session.send = AsyncMock(side_effect=sent)
        await AgentSession._persistent_event_loop(session)
        session.send.assert_awaited_once()
        args, kwargs = session.send.await_args
        self.assertIn("platform (backend disconnect)", args[0])
        self.assertIn("not a user refusal", args[0])
        self.assertIn("continue task #V-1035", args[0])
        self.assertEqual(kwargs["provenance"].subtype, "runtime_reconnect")
        self.assertEqual(kwargs["retry_generation"], (1, 0))

    async def test_heartbeat_reconnect_uses_same_honest_notice(self):
        from app import session_hibernate

        session = SimpleNamespace(
            name="worker", task_id="V-1035", status=AgentStatus.RUNNING,
            backend_type="claude", _last_msg_time=0, _listen_task=None,
            _backend=SimpleNamespace(send=AsyncMock()), _log=Mock(),
            _reconnect_backend=AsyncMock(), _persistent_event_loop=AsyncMock(),
            _on_task_done=Mock(),
        )
        hibernate = session_hibernate.HibernateManager(session)
        hibernate._signal_silence_once = AsyncMock()
        with patch.object(session_hibernate.asyncio, "sleep",
                          AsyncMock(side_effect=[None, asyncio.CancelledError()])), \
                patch.object(session_hibernate, "get_runtime", return_value=SimpleNamespace(
                    capabilities=SimpleNamespace(reconnect=True),
                )):
            await hibernate.heartbeat_loop()
        await session._listen_task
        session._backend.send.assert_awaited_once()
        text = session._backend.send.await_args.args[0]
        self.assertIn("platform (backend disconnect)", text)
        self.assertIn("not a user refusal", text)
        self.assertIn("continue task #V-1035", text)

    async def test_heartbeat_without_task_metadata_still_delivers_continuation(self):
        from app import session_hibernate

        backend = SimpleNamespace(send=AsyncMock())
        session = SimpleNamespace(
            name="worker", status=AgentStatus.RUNNING, backend_type="claude",
            _last_msg_time=0, _listen_task=None, _backend=backend, _log=Mock(),
            _reconnect_backend=AsyncMock(), _persistent_event_loop=AsyncMock(),
            _on_task_done=Mock(), _persist=Mock(), _turns=Mock(),
        )
        hibernate = session_hibernate.HibernateManager(session)
        hibernate._signal_silence_once = AsyncMock()
        with patch.object(session_hibernate.asyncio, "sleep",
                          AsyncMock(side_effect=[None, asyncio.CancelledError()])), \
                patch.object(session_hibernate, "get_runtime", return_value=SimpleNamespace(
                    capabilities=SimpleNamespace(reconnect=True),
                )), \
                patch.object(session_hibernate, "platform_interruption_notice",
                             return_value="continuation payload") as notice:
            await hibernate.heartbeat_loop()
        backend.send.assert_awaited_once_with("[system] continuation payload")
        notice.assert_called_once_with("backend disconnect", "")
        session._reconnect_backend.assert_awaited_once()
        self.assertIs(session._backend, backend)
        self.assertEqual(session.status, AgentStatus.RUNNING)
        await session._listen_task

    async def test_restart_routes_to_cut_worker_without_parent_or_native_session(self):
        for status, native in (("running", None), ("interrupted", "native")):
            with self.subTest(status=status, native=native):
                with db._conn() as connection:
                    connection.execute("DELETE FROM sessions")
                self.save_worker(status=status, native=native)
                manager = manager_module.SessionManager()
                manager.send = AsyncMock()
                manager.reconcile_live_colors = Mock()
                manager._signal_restart_cut_turns = Mock()
                session = SimpleNamespace(id="worker-id", name="worker", _drain_persist=AsyncMock())
                manager._load_from_db = AsyncMock(return_value=session)
                spawned = []
                with patch.object(manager_module, "spawn_supervised",
                                  side_effect=lambda coro, label: spawned.append(coro)), \
                        patch.object(manager_module, "list_latest_runtime_handoffs", return_value=[]), \
                        patch.object(manager_module.asyncio, "sleep", AsyncMock()):
                    await manager.auto_resume_all()
                    self.assertEqual(len(spawned), 1)
                    await spawned[0]
                manager.send.assert_awaited_once()
                args, kwargs = manager.send.await_args
                self.assertEqual(args[0], "worker-id")
                self.assertIn("continue task #V-1035", args[1])
                self.assertIn("not a user refusal", args[1])
                self.assertEqual(kwargs["provenance"].origin, "system")
                self.assertEqual(kwargs["provenance"].subtype, "restart")
                manager._signal_restart_cut_turns.assert_called_once_with([])

    async def test_idle_worker_is_not_told_it_was_cut(self):
        self.save_worker(status="idle", native="saved")
        manager = manager_module.SessionManager()
        manager.reconcile_live_colors = Mock()
        manager._load_from_db = AsyncMock()
        manager._signal_restart_cut_turns = Mock()
        with patch.object(manager_module, "list_latest_runtime_handoffs", return_value=[]), \
                patch.object(manager_module, "spawn_supervised") as spawn:
            await manager.auto_resume_all()
        spawn.assert_not_called()

    async def test_manual_stop_during_restart_stagger_cancels_automatic_continuation(self):
        manager = manager_module.SessionManager()
        manager.send = AsyncMock()
        session = SimpleNamespace(id="worker-id", name="worker", _manually_interrupted=False)

        async def manual_stop(_delay):
            session._manually_interrupted = True

        with patch.object(manager_module.asyncio, "sleep", side_effect=manual_stop):
            await manager._inject_restart_notice(session, {
                "session_id": "native", "task_id": "V-1035",
            })
        manager.send.assert_not_awaited()

    async def test_restart_delivery_failure_still_reports_the_blocked_worker(self):
        manager = manager_module.SessionManager()
        manager.send = AsyncMock(side_effect=RuntimeError("backend unavailable"))
        manager._signal_restart_cut_turns = Mock()
        row = {"session_id": "native", "task_id": "V-1035"}
        with patch.object(manager_module.asyncio, "sleep", AsyncMock()):
            await manager._inject_restart_notice(SimpleNamespace(id="worker-id", name="worker"), row)
        manager._signal_restart_cut_turns.assert_called_once_with([row])

    async def run_limit_wake(self, *, provider="anthropic", manual=False, deliveries=None,
                             token_seen=False, stale=False):
        from app.routes import system

        target = {"id": "worker-id", "name": "worker", "scope": str(self.root),
                  "limit_turn_id": 10}  # Old persisted timers have no task_id.
        candidate = {**target, "provider": provider, "task_id": "V-1035"}
        if stale:
            candidate["limit_turn_id"] = 11
        session = SimpleNamespace(id="worker-id", name="worker", status=AgentStatus.IDLE,
                                  _manually_interrupted=manual)
        manager = SimpleNamespace(ensure_loaded=AsyncMock(return_value=session), send=AsyncMock())
        config = {"provider": provider, "agents": [target], "deliveries": deliveries or {}}
        windows = [{"id": name, "utilization": 0} for name in ("five_hour", "seven_day")]
        with patch.object(limit_wake, "bg_claim_trigger", return_value=True), \
                patch.object(limit_wake, "bg_finish_trigger") as finish, \
                patch.object(limit_wake, "_persist_deliveries"), \
                patch.object(limit_wake, "_load_limit_stopped_agents", return_value=[candidate]), \
                patch.object(limit_wake, "_wake_token_seen", return_value=token_seen), \
                patch.object(system, "current_provider_usage", AsyncMock(return_value={
                    provider: {"windows": windows},
                })):
            await limit_wake.run_wake_job("test-job", config, manager, stagger_seconds=0)
        finish.assert_called_once()
        return manager, config

    async def test_limit_reset_resumes_worker_directly_with_current_task_for_both_providers(self):
        for provider in ("anthropic", "openai"):
            with self.subTest(provider=provider):
                manager, config = await self.run_limit_wake(provider=provider)
                manager.ensure_loaded.assert_awaited_once_with("worker", str(self.root))
                manager.send.assert_awaited_once()
                args, kwargs = manager.send.await_args
                self.assertEqual(args[0], "worker-id")
                self.assertIn("platform (subscription limit)", args[1])
                self.assertIn("not stopped by anyone", args[1])
                self.assertIn("not a user refusal", args[1])
                self.assertIn("check its effect before repeating it", args[1])
                self.assertIn("Check your working tree and continue task #V-1035", args[1])
                self.assertIn("without waiting for your orchestrator", args[1])
                self.assertEqual(kwargs["provenance"].origin, "system")
                self.assertEqual(kwargs["provenance"].subtype, "limit_wake")
                self.assertEqual(config["deliveries"]["worker-id"]["state"], "delivered")

    async def test_limit_reset_does_not_override_manual_stop_or_newer_turn(self):
        for kwargs in ({"manual": True}, {"stale": True}):
            with self.subTest(kwargs=kwargs):
                manager, _ = await self.run_limit_wake(**kwargs)
                manager.send.assert_not_awaited()

    async def test_replayed_claim_is_reconciled_without_another_wake(self):
        manager, config = await self.run_limit_wake(
            deliveries={"worker-id": {"state": "claimed", "token": "seen"}}, token_seen=True,
        )
        manager.send.assert_not_awaited()
        self.assertEqual(config["deliveries"]["worker-id"]["state"], "delivered")

    async def test_unseen_claim_is_retried_once(self):
        manager, config = await self.run_limit_wake(
            deliveries={"worker-id": {"state": "claimed", "token": "unseen"}},
        )
        manager.send.assert_awaited_once()
        self.assertNotEqual(config["deliveries"]["worker-id"]["token"], "unseen")


if __name__ == "__main__":
    unittest.main()
