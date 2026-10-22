"""V-1036: durable delivery visibility; runnable with stdlib unittest offline."""

import asyncio
import json
import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, patch

from app import db, initial_deliveries as initial, initial_delivery_events, message_deliveries as direct
from app.events import MessageProvenance
from app.quota_queue import quota_wait_action, wait_error


class GateError(RuntimeError):
    def __init__(self, decision):
        self.decision = decision
        super().__init__(decision.reason)


def decision(seconds=3600, reset_at=None):
    return SimpleNamespace(
        provider="test", provider_label="Test", utilization=95,
        reason="gate closed", release_status="estimated", release_in_seconds=seconds,
        reset_at=reset_at,
    )


class DeliveryVisibility(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Keep all test artifacts inside the task's sandbox, including SQLite WAL.
        root = Path(".orchestra/tasks/V-1036")
        root.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.tmp.cleanup)
        self.patchers = []
        self.use(patch.object(db, "DB_PATH", Path(self.tmp.name) / "test.db"))
        db.init_db()
        with db._conn() as c:
            for sid, name, scope in (
                ("source", "sender", "scope"), ("other", "other-sender", "scope"),
                ("target", "worker", "scope"), ("alien", "sender", "other-scope"),
            ):
                c.execute(
                    """INSERT INTO sessions(id,name,scope,cwd,model,status,created_at)
                       VALUES(?,?,?,'fixture','test-model','idle',?)""",
                    (sid, name, scope, datetime.now(timezone.utc).isoformat()),
                )
        self.use(patch.object(direct, "ensure_target_runner"))
        self.use(patch.object(initial, "ensure_delivery_runner"))
        self.use(patch.object(initial_delivery_events, "ensure_runner"))
        fan = ModuleType("app.fan_barrier")
        fan.intercept_delivery_report = lambda *_args: None
        codex = ModuleType("app.backend_codex")
        codex.CodexWriterConflictError = type("CodexWriterConflictError", (Exception,), {})
        quota = ModuleType("app.quota_gate")
        quota.QuotaGateError = GateError
        self.use(patch.dict("sys.modules", {
            "app.fan_barrier": fan, "app.backend_codex": codex, "app.quota_gate": quota,
        }))
        self.manager = SimpleNamespace(send=AsyncMock())

    def use(self, patcher):
        self.patchers.append(patcher)
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    async def accept(self, *, first=False, parked=False, source="source", text="urgent " + "x" * 100, did=None):
        did = did or str(uuid.uuid4())
        prov = MessageProvenance(origin="agent", senders=("sender",), subtype="test", ref=did)
        quota = decision() if parked else None
        if first:
            receipt, status = await initial.accept_initial_delivery(
                delivery_id=did, session_id="target", worker_name="worker", scope="scope",
                sender="sender", message=text, provenance=prov, quota_wait=quota,
            )
        else:
            receipt, status = await direct.accept_message_delivery(
                delivery_id=did, source_session_id=source, source_name="sender",
                source_scope="scope", target_session_id="target", target_name="worker",
                target_scope="scope", target_generation="generation", message=text,
                rendered_message=text, provenance=prov, quota_wait=quota,
            )
        self.assertEqual(status, 202)
        return receipt

    async def induce_failure(self, did, *, first=False, after_submit=False, cancel=False):
        async def send(_sid, _message, *, delivery, **_kwargs):
            if after_submit:
                await delivery.before_submit()
            if cancel:
                raise asyncio.CancelledError("turn interrupted")
            raise RuntimeError("LayoutMigrationError: original\nsecond line")

        self.manager.send_initial_delivery = send
        self.manager.send_message_delivery = send
        run = initial.run_initial_delivery if first else direct.run_message_delivery
        with self.assertRaises(asyncio.CancelledError if cancel else RuntimeError):
            await run(did, manager=self.manager)

    async def test_direct_failure_wakes_once_with_verbatim_error(self):
        receipt = await self.accept()
        did = receipt["delivery_id"]
        await self.induce_failure(did)
        self.manager.send.assert_awaited_once()
        notice = self.manager.send.call_args.args[1]
        self.assertIn("LayoutMigrationError: original\nsecond line", notice.text)
        self.assertIn(did, notice.text)
        self.assertIn("NOT delivered", notice.text)
        await direct.recover_message_delivery_failure_notices(self.manager)
        self.manager.send.assert_awaited_once()

    async def test_initial_failure_wakes_actual_sender(self):
        receipt = await self.accept(first=True)
        await self.induce_failure(receipt["delivery_id"], first=True)
        self.manager.send.assert_awaited_once()
        sid, notice = self.manager.send.call_args.args
        self.assertEqual(sid, "source")
        self.assertIn("Initial task", notice.text)
        self.assertIn("LayoutMigrationError: original\nsecond line", notice.text)
        self.assertIn(receipt["delivery_id"], notice.text)

    async def test_repeated_failure_record_is_idempotent(self):
        receipt = await self.accept()
        await self.induce_failure(receipt["delivery_id"])
        direct.mark_message_delivery_failed_before_submit(
            receipt["delivery_id"], RuntimeError("LayoutMigrationError: original\nsecond line"),
        )
        await direct.notify_message_delivery_failure(receipt["delivery_id"], manager=self.manager)
        self.manager.send.assert_awaited_once()

    async def test_cancelled_initial_runner_wakes_sender(self):
        receipt = await self.accept(first=True)
        await self.induce_failure(receipt["delivery_id"], first=True, cancel=True)
        self.assertIn("CancelledError: turn interrupted", self.manager.send.call_args.args[1].text)

    async def test_initial_ambiguous_dispatch_is_loud_without_false_non_delivery(self):
        receipt = await self.accept(first=True)
        await self.induce_failure(receipt["delivery_id"], first=True, after_submit=True)
        self.assertIn("UNKNOWN", self.manager.send.call_args.args[1].text)
        self.assertNotIn("NOT delivered", self.manager.send.call_args.args[1].text)

    async def test_failed_wake_survives_recovery_and_concurrent_drains(self):
        receipt = await self.accept(first=True)
        self.manager.send.side_effect = RuntimeError("sender offline")
        await self.induce_failure(receipt["delivery_id"], first=True)
        self.assertIsNone(direct._failure_notice(receipt["delivery_id"])["delivered_at"])
        self.manager.send.reset_mock(side_effect=True)
        await asyncio.gather(
            direct.recover_message_delivery_failure_notices(self.manager),
            direct.recover_message_delivery_failure_notices(self.manager),
        )
        self.manager.send.assert_awaited_once()

    async def test_retry_same_id_can_fail_loudly_again(self):
        async def log_notice(sid, notice, **_kwargs):
            with db._conn() as c:
                c.execute(
                    "INSERT INTO logs(session_id,ts,type,content,event_id) VALUES(?,?,'user_message',?,?)",
                    (sid, datetime.now(timezone.utc).isoformat(), notice.text, notice.event_id),
                )

        self.manager.send.side_effect = log_notice
        for first in (False, True):
            with self.subTest(first=first):
                self.manager.send.reset_mock()
                receipt = await self.accept(first=first)
                await self.induce_failure(receipt["delivery_id"], first=first)
                await self.accept(first=first, did=receipt["delivery_id"])
                await self.induce_failure(receipt["delivery_id"], first=first)
                self.assertEqual(self.manager.send.await_count, 2)
                await direct.recover_message_delivery_failure_notices(self.manager)
                self.assertEqual(self.manager.send.await_count, 2)

    async def test_logged_notice_with_lost_ack_does_not_wake_twice(self):
        async def lost_ack(sid, notice, **_kwargs):
            with db._conn() as c:
                c.execute(
                    "INSERT INTO logs(session_id,ts,type,content,event_id) VALUES(?,?,'user_message',?,?)",
                    (sid, datetime.now(timezone.utc).isoformat(), notice.text, notice.event_id),
                )
            raise RuntimeError("reply lost after durable log")

        self.manager.send.side_effect = lost_ack
        receipt = await self.accept(first=True)
        with self.assertLogs(initial.logger, level="ERROR"):
            await self.induce_failure(receipt["delivery_id"], first=True)
        self.manager.send.reset_mock(side_effect=True)
        await direct.recover_message_delivery_failure_notices(self.manager)
        self.manager.send.assert_not_awaited()
        self.assertTrue(direct._failure_notice(receipt["delivery_id"])["delivered_at"])

    async def test_success_and_quota_race_never_create_failure_wake(self):
        async def send(_sid, _message, *, delivery, **_kwargs):
            await delivery.before_submit()
            await delivery.mark_submitted("provider-turn")

        async def closed(*_args, **_kwargs):
            raise GateError(decision())

        for first in (False, True):
            receipt = await self.accept(first=first)
            self.manager.send_initial_delivery = send
            self.manager.send_message_delivery = send
            run = initial.run_initial_delivery if first else direct.run_message_delivery
            await run(receipt["delivery_id"], manager=self.manager)
            self.assertIsNone(direct._failure_notice(receipt["delivery_id"]))
            self.assertEqual(direct.list_pending_deliveries("source"), [])
            receipt = await self.accept(first=first)
            self.manager.send_initial_delivery = closed
            self.manager.send_message_delivery = closed
            await run(receipt["delivery_id"], manager=self.manager)
            pending = direct.list_pending_deliveries("source")
            self.assertIn(receipt["delivery_id"], {p["delivery_id"] for p in pending})
            module = initial if first else direct
            if first:
                module.cancel_initial_delivery(receipt["delivery_id"], "source")
            else:
                module.cancel_message_delivery(receipt["delivery_id"], "source")
        self.manager.send.assert_not_awaited()

    async def test_old_failure_without_notice_recovers(self):
        for first in (False, True):
            receipt = await self.accept(first=first)
            table = "initial_deliveries" if first else "message_deliveries"
            with db._conn() as c:
                c.execute(f"UPDATE {table} SET state='FAILED_BEFORE_SUBMIT',error_json=? WHERE delivery_id=?",
                          (json.dumps({"code": "DELIVERY_NOT_SUBMITTED", "message": "old exact error"}), receipt["delivery_id"]))
        await direct.recover_message_delivery_failure_notices(self.manager)
        self.assertEqual(self.manager.send.await_count, 2)
        self.assertTrue(all("old exact error" in call.args[1].text for call in self.manager.send.call_args_list))

    async def test_legacy_acknowledged_notice_does_not_replay(self):
        receipt = await self.accept()
        await self.induce_failure(receipt["delivery_id"])
        with db._conn() as c:
            c.execute("UPDATE message_delivery_failure_notices SET error_json=?",
                      (json.dumps({"code": "DELIVERY_NOT_SUBMITTED", "message": "old error"}),))
        await direct.recover_message_delivery_failure_notices(self.manager)
        self.manager.send.assert_awaited_once()

    async def test_orphaned_terminal_delivery_wakes_sender_on_recovery(self):
        receipt = await self.accept()
        direct.prepare_message_delivery(receipt["delivery_id"])
        direct.mark_message_delivery_dispatching(receipt["delivery_id"])
        with patch.dict("sys.modules", {"app.deps": SimpleNamespace(manager=self.manager)}):
            await direct.recover_message_deliveries()
        await direct.recover_message_delivery_failure_notices(self.manager)
        self.assertIn("UNKNOWN", self.manager.send.call_args.args[1].text)

    async def test_quota_error_receipt_and_action_include_id_and_eta(self):
        for first in (False, True):
            receipt = await self.accept(first=first, parked=True)
            did = receipt["delivery_id"]
            self.assertEqual(receipt["delivery_state"], "WAITING_QUOTA")
            self.assertEqual(receipt["error"]["delivery_id"], did)
            self.assertIn(did, receipt["error"]["message"])
            self.assertIn("ETA:", receipt["error"]["message"])
            self.assertEqual(receipt["next_action"]["delivery_id"], did)
            self.assertGreater(receipt["next_action"]["eta_at"], 0)
        self.manager.send.assert_not_awaited()

    async def test_pending_is_owned_filtered_80_chars_and_includes_initial(self):
        a = await self.accept(parked=True)
        b = await self.accept(first=True)
        await self.accept(parked=True, source="other")
        pending = direct.list_pending_deliveries("source", "worker")
        self.assertEqual({r["delivery_id"] for r in pending}, {a["delivery_id"], b["delivery_id"]})
        for row in pending:
            self.assertEqual(len(row["message_preview"]), 80)
            self.assertTrue(row["eta"])
            self.assertTrue(row["created_at"])
            self.assertEqual(row["target"], "worker")
        self.assertEqual(direct.list_pending_deliveries("alien"), [])
        self.assertEqual(direct.list_pending_deliveries("source", "another-worker"), [])
        direct.cancel_message_delivery(a["delivery_id"], "source")
        initial.cancel_initial_delivery(b["delivery_id"], "source")
        self.assertEqual(direct.list_pending_deliveries("source"), [])

    async def test_initial_cancel_owner_state_boundary_and_idempotency(self):
        for parked in (False, True):
            r = await self.accept(first=True, parked=parked)
            did = r["delivery_id"]
            self.assertEqual(initial.cancel_initial_delivery(did, "other")[1], 404)
            self.assertEqual(initial.cancel_initial_delivery(did, "alien")[1], 404)
            self.assertEqual(initial.cancel_initial_delivery(did, "source")[0]["delivery_state"], "CANCELLED")
            self.assertEqual(initial.cancel_initial_delivery(did, "source")[1], 200)
        r = await self.accept(first=True)
        initial.prepare_initial_delivery(r["delivery_id"])
        self.assertEqual(initial.cancel_initial_delivery(r["delivery_id"], "source")[1], 409)

    async def test_queued_behind_quota_has_eta(self):
        await self.accept(parked=True)
        r = await self.accept()
        self.assertEqual(r["next_action"]["code"], "BEHIND_QUOTA_WAIT")
        self.assertGreater(r["next_action"]["eta_at"], 0)
        own = {p["delivery_id"]: p for p in direct.list_pending_deliveries("source")}
        self.assertEqual(own[r["delivery_id"]]["eta_at"], r["next_action"]["eta_at"])

    async def test_eta_missing_estimate_is_explicit_and_old_rows_work(self):
        for seconds, reset in ((3600, None), (None, "2026-10-25T00:00Z"), (None, None)):
            error = wait_error(decision(seconds, reset), delivery_id="test-id", now=1000)
            action = quota_wait_action({"delivery_id": "test-id", "error_json": json.dumps(error)})
            self.assertTrue(action["eta"])
            if seconds:
                self.assertEqual(action["eta_at"], 4600)
            elif reset:
                self.assertIn(reset, action["eta"])
            else:
                self.assertIn("unknown", action["eta"])
        old = quota_wait_action({"delivery_id": "old-id", "error_json": None})
        self.assertEqual(old["delivery_id"], "old-id")
        self.assertIn("unknown", old["eta"])


if __name__ == "__main__":
    unittest.main()
