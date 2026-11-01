"""V-1057: startup owns cut-turn recovery, including a crash during startup."""

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch


class RestartCutRecoveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from app import db, manager, turn_signals
        from app.bg_jobs import bg_manager

        self.db = db
        self.manager_module = manager
        self.directory = tempfile.TemporaryDirectory(prefix="restart-1057-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.patch = self.enterContext
        self.patch(patch.object(db, "DB_PATH", self.root / "test.db"))
        db.init_db()
        self.patch(patch.object(manager.SessionManager, "reconcile_live_colors", Mock()))
        self.patch(patch.object(manager, "list_latest_runtime_handoffs", return_value=[]))
        self.patch(patch.object(manager.asyncio, "sleep", AsyncMock()))
        self.active_jobs = self.patch(patch.object(bg_manager, "has_active_jobs", return_value=False))
        self.signals = self.patch(patch.object(turn_signals, "record_interrupted_by_restart"))
        self.coroutines = []
        self.addCleanup(lambda: [coro.close() for coro in self.coroutines])
        self.save()

    def save(self, status="running", native="saved-native"):
        with self.db._conn() as connection:
            connection.execute("DELETE FROM sessions")
            connection.execute(
                "INSERT INTO sessions(id,name,scope,cwd,model,created_at,status,session_id,"
                "parent_name,role,pipeline) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                ("worker-id", "worker", str(self.root), str(self.root),
                 "claude-sonnet-5-5[1m]", "2026-10-23", status, native, "parent", "worker", "default"),
            )

    def status(self, value=None):
        with self.db._conn() as connection:
            if value is not None:
                connection.execute("UPDATE sessions SET status=? WHERE id='worker-id'", (value,))
            return connection.execute("SELECT status FROM sessions WHERE id='worker-id'").fetchone()[0]

    def pending(self):
        with self.db._conn() as connection:
            return [row[0] for row in connection.execute("SELECT session_id FROM restart_cut_turns")]

    def session(self, status="idle"):
        session = SimpleNamespace(
            id="worker-id", name="worker", status=self.manager_module.AgentStatus(status),
            _drain_persist=AsyncMock(), _log=Mock(), _turns=Mock(),
            _cancel_precompact_timer=Mock(), _disconnect_backend=AsyncMock(),
            _manually_interrupted=False, _restart_cut_pending=False,
            _lifecycle_lock=asyncio.Lock(), _turn_start_cancel_gen=0,
            _backend=None, _compacting=False,
        )
        session._persist = lambda: self.status(session.status.value)
        return session

    async def resume(self, *, deliver=True, load_error=False):
        manager = self.manager_module.SessionManager()
        spawned = []

        async def load(row, *, recovery_handoff=None):
            if load_error:
                raise RuntimeError("offline load failed")
            # Production _load_from_db calls session.start(), which persists idle.
            session = self.session()
            session._persist()
            manager.sessions[session.id] = session
            return session

        async def send(session_id, text, *, provenance):
            self.assertEqual(session_id, "worker-id")
            self.assertEqual(provenance.subtype, "restart")
            self.assertIn("restarted while your turn was running", text)
            # Simulate an accepted continuation that finishes before another boot.
            self.status("idle")

        manager._load_from_db = AsyncMock(side_effect=load)
        manager.send = AsyncMock(side_effect=send)
        with patch.object(self.manager_module, "spawn_supervised",
                          side_effect=lambda coro, label: spawned.append(coro)):
            await manager.auto_resume_all()
        self.coroutines.extend(spawned)
        if deliver:
            for coro in spawned:
                await coro
        return manager, spawned

    async def test_abrupt_stop_running_is_resumed_once_without_cut_names(self):
        for native in ("saved-native", None):
            with self.subTest(native=native):
                self.save(native=native)
                if native is None:
                    # First-turn replay reads logs, without involving any provider.
                    from app import db
                    from app.events import MessageProvenance
                    from datetime import datetime, timezone
                    db.add_log("worker-id", datetime.now(timezone.utc), "user_message", "V-1057 task",
                               provenance=MessageProvenance(origin="agent", senders=("parent",)))
                manager, spawned = await self.resume()
                self.assertEqual(len(spawned), 1)
                manager.send.assert_awaited_once()
                self.assertEqual(self.pending(), [])
                later, spawned = await self.resume()
                self.assertEqual(spawned, [])
                later.send.assert_not_awaited()
        self.signals.assert_not_called()

    async def test_prepared_restart_resumes_once(self):
        from app import main
        from app.routes import system
        from app.session import AgentSession

        before = self.manager_module.SessionManager()
        session = self.session("running")
        session.is_busy = True
        session.stop = lambda: AgentSession.stop(session)
        before.sessions[session.id] = session
        with patch.object(system, "manager", before), \
                patch.object(system, "_drain_sessions", return_value=[session]), \
                patch.object(main, "drain_mutating_requests", AsyncMock()), \
                patch.object(main, "inflight_mutating_count", return_value=0), \
                patch.object(system, "_drain_restart_durable_state", AsyncMock(return_value={"ok": True})), \
                patch.object(system, "_record_restart_outcome_bounded", AsyncMock(return_value=None)), \
                patch.object(system, "_arm_supervisor_exit_guard"):
            outcome = await system._do_restart_service()
        self.assertEqual(outcome["cut_names"], ["worker"])
        self.assertEqual(outcome["restore_after_restart"], ["worker-id"])
        await before.shutdown_all()
        self.assertEqual(self.status(), "interrupted")
        after, spawned = await self.resume()
        self.assertEqual(len(spawned), 1)
        after.send.assert_awaited_once()
        self.assertEqual(self.pending(), [])
        later, spawned = await self.resume()
        self.assertEqual(spawned, [])
        later.send.assert_not_awaited()
        self.signals.assert_not_called()

    async def test_second_crash_before_staggered_notice_keeps_cut_turn(self):
        first, spawned = await self.resume(deliver=False)
        self.assertEqual(len(spawned), 1)
        first.send.assert_not_awaited()
        self.assertEqual(self.status(), "idle")
        self.assertEqual(self.pending(), ["worker-id"])
        spawned[0].close()  # Process dies before the coroutine runs.
        second, spawned = await self.resume()
        self.assertEqual(len(spawned), 1)
        second.send.assert_awaited_once()
        self.assertEqual(self.pending(), [])
        third, spawned = await self.resume()
        self.assertEqual(spawned, [])
        third.send.assert_not_awaited()

    async def test_crash_while_loading_retains_first_turn_without_native_id(self):
        self.save(native=None)
        manager = self.manager_module.SessionManager()
        manager._load_from_db = AsyncMock(side_effect=asyncio.CancelledError())
        with self.assertRaises(asyncio.CancelledError):
            await manager.auto_resume_all()
        self.assertEqual(self.status(), "idle")
        self.assertEqual(self.pending(), ["worker-id"])
        later, spawned = await self.resume()
        self.assertEqual(len(spawned), 1)
        later.send.assert_awaited_once()

    async def test_waiting_agent_is_not_cut_even_with_an_old_obligation(self):
        for stale in (False, True):
            with self.subTest(stale=stale):
                self.save(status="waiting")
                if stale:
                    with self.db._conn() as connection:
                        connection.execute("INSERT INTO restart_cut_turns VALUES ('worker-id')")
                self.active_jobs.return_value = True
                manager, spawned = await self.resume()
                self.assertEqual(spawned, [])
                manager.send.assert_not_awaited()
                self.assertEqual(self.status(), "waiting")
                self.assertEqual(self.pending(), [])
        self.signals.assert_not_called()

    async def test_load_failure_notifies_parent_once(self):
        manager, spawned = await self.resume(load_error=True)
        self.assertEqual(spawned, [])
        self.signals.assert_called_once()
        self.assertEqual(self.signals.call_args.args[0][0]["id"], "worker-id")
        self.assertEqual(self.pending(), [])
        await self.resume()
        self.signals.assert_called_once()

    async def test_failed_parent_notification_survives_another_boot(self):
        self.signals.side_effect = RuntimeError("signal database unavailable")
        await self.resume(load_error=True)
        self.assertEqual(self.pending(), ["worker-id"])
        self.signals.side_effect = None
        await self.resume(load_error=True)
        self.assertEqual(self.signals.call_count, 2)
        self.assertEqual(self.pending(), [])

    async def test_missing_working_directory_notifies_parent_once(self):
        with self.db._conn() as connection:
            connection.execute("UPDATE sessions SET cwd=? WHERE id='worker-id'",
                               (str(self.root / "missing"),))
        manager, spawned = await self.resume()
        self.assertEqual(spawned, [])
        manager._load_from_db.assert_not_awaited()
        self.signals.assert_called_once()
        self.assertEqual(self.pending(), [])
        await self.resume()
        self.signals.assert_called_once()

    async def test_archived_agent_does_not_keep_a_pending_wake(self):
        self.save(status="archived")
        with self.db._conn() as connection:
            connection.execute("INSERT INTO restart_cut_turns VALUES ('worker-id')")
        manager, spawned = await self.resume()
        self.assertEqual(spawned, [])
        manager._load_from_db.assert_not_awaited()
        self.assertEqual(self.pending(), [])
        self.assertEqual(self.status(), "archived")
        self.signals.assert_not_called()

    async def test_notice_failure_notifies_parent_once(self):
        manager, spawned = await self.resume(deliver=False)
        manager.send.side_effect = RuntimeError("provider not invoked")
        await spawned[0]
        self.signals.assert_called_once()
        self.assertEqual(self.pending(), [])
        await self.resume()
        self.signals.assert_called_once()

    async def test_cancellation_during_notice_does_not_acknowledge(self):
        manager, spawned = await self.resume(deliver=False)
        manager.send.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await spawned[0]
        self.assertEqual(self.pending(), ["worker-id"])
        self.signals.assert_not_called()
        later, _ = await self.resume()
        later.send.assert_awaited_once()
        self.assertEqual(self.pending(), [])

    async def test_acknowledgement_waits_for_session_persistence(self):
        manager, spawned = await self.resume(deliver=False)
        session = manager.sessions["worker-id"]

        async def drain():
            self.assertEqual(self.pending(), ["worker-id"])

        session._drain_persist.side_effect = drain
        await spawned[0]
        session._drain_persist.assert_awaited_once()
        self.assertEqual(self.pending(), [])

    async def test_manual_stop_cancels_pending_recovery_before_another_crash(self):
        from app.session import AgentSession

        manager, spawned = await self.resume(deliver=False)
        session = manager.sessions["worker-id"]
        await AgentSession.interrupt(session)
        self.assertEqual(self.pending(), [])
        spawned[0].close()
        later, spawned = await self.resume()
        self.assertEqual(spawned, [])
        later.send.assert_not_awaited()
        self.signals.assert_not_called()

    async def test_repeated_startup_in_same_manager_does_not_schedule_twice(self):
        manager, spawned = await self.resume(deliver=False)
        with patch.object(self.manager_module, "spawn_supervised") as spawn:
            await manager.auto_resume_all()
        spawn.assert_not_called()
        await spawned[0]
        manager.send.assert_awaited_once()

    async def test_recovery_schema_is_additive_idempotent_and_follows_session_deletion(self):
        with self.db._conn() as connection:
            self.db._ensure_restart_cut_turns_schema(connection)
            connection.execute("INSERT INTO restart_cut_turns VALUES ('worker-id')")
            self.db._ensure_restart_cut_turns_schema(connection)
        self.assertEqual(self.pending(), ["worker-id"])
        with self.db._conn() as connection:
            connection.execute("DELETE FROM sessions WHERE id='worker-id'")
        self.assertEqual(self.pending(), [])

    async def test_existing_database_gets_recovery_table_on_init(self):
        with self.db._conn() as connection:
            connection.execute("DROP TABLE restart_cut_turns")
        self.db.init_db()
        self.assertEqual(self.status(), "running")
        self.assertEqual(self.pending(), [])
        with self.db._conn() as connection:
            connection.execute("INSERT INTO restart_cut_turns VALUES ('worker-id')")
        self.db.init_db()
        self.assertEqual(self.pending(), ["worker-id"])


if __name__ == "__main__":
    unittest.main()
