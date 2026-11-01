"""V-1045: startup notices acknowledge history without waking its senders."""

import json
import sqlite3
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app import message_deliveries as deliveries


NOW = datetime(2026, 10, 22, 14, tzinfo=timezone.utc)
FAILURES = (
    (False, "FAILED_BEFORE_SUBMIT"),
    (False, "DELIVERY_UNKNOWN_ORPHANED"),
    (True, "FAILED_BEFORE_SUBMIT"),
    (True, "DELIVERY_UNKNOWN"),
)


class FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)


class FailureNoticeBackfill(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.addCleanup(self.connection.close)
        self.connection.executescript("""
            CREATE TABLE sessions (id TEXT PRIMARY KEY, name TEXT, scope TEXT, status TEXT);
            INSERT INTO sessions VALUES ('source', 'sender', 'scope', 'idle');
            INSERT INTO sessions VALUES ('target', 'worker', 'scope', 'idle');
            CREATE TABLE logs (session_id TEXT, event_id TEXT);
            CREATE TABLE message_deliveries (
                delivery_id TEXT PRIMARY KEY, origin TEXT, state TEXT,
                source_session_id TEXT, target_session_id TEXT, target_name TEXT,
                error_json TEXT, updated_at TEXT, created_at TEXT
            );
            CREATE TABLE initial_deliveries (
                delivery_id TEXT PRIMARY KEY, origin TEXT, state TEXT,
                sender TEXT, scope TEXT, session_id TEXT, worker_name TEXT,
                error_json TEXT, updated_at TEXT, created_at TEXT
            );
        """)
        for patcher in (
            patch.object(deliveries.db, "_conn", lambda: self.connection),
            patch.object(deliveries, "datetime", FrozenDatetime),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.manager = SimpleNamespace(send=AsyncMock())

    def failure(self, *, initial=False, state="FAILED_BEFORE_SUBMIT", stamp=None):
        did = str(uuid.uuid4())
        stamp = stamp if stamp is not None else (NOW - timedelta(hours=1)).isoformat()
        error = json.dumps({
            "code": "DELIVERY_NOT_SUBMITTED", "message": "original failure",
            "outcome_unknown": "UNKNOWN" in state,
        })
        if initial:
            self.connection.execute(
                "INSERT INTO initial_deliveries VALUES (?, 'agent', ?, 'sender', 'scope', "
                "'target', 'worker', ?, ?, ?)",
                (did, state, error, stamp, NOW.isoformat()),
            )
        else:
            self.connection.execute(
                "INSERT INTO message_deliveries VALUES (?, 'agent', ?, 'source', "
                "'target', 'worker', ?, ?, ?)",
                (did, state, error, stamp, NOW.isoformat()),
            )
        return did

    def assert_skipped(self, did, reason):
        notice = deliveries._failure_notice(did)
        self.assertIsNotNone(notice)
        self.assertEqual(notice["delivered_at"], NOW.isoformat())
        details = json.loads(notice["error_json"])
        self.assertEqual(details["_notice_skipped_reason"], reason)
        self.assertEqual(details["message"], "original failure")
        self.assertIn("_notice_revision", details)

    async def test_old_failure_is_acknowledged_without_wake(self):
        ids = [self.failure(initial=initial, state=state,
                            stamp=(NOW - timedelta(days=50)).isoformat())
               for initial, state in FAILURES]
        self.assertEqual(await deliveries.recover_message_delivery_failure_notices(self.manager), 0)
        self.manager.send.assert_not_awaited()
        for did in ids:
            self.assert_skipped(did, "outside_recent_window")

    async def test_archived_target_is_acknowledged_without_wake(self):
        self.connection.execute("UPDATE sessions SET status='archived' WHERE id='target'")
        ids = [self.failure(initial=initial, state=state) for initial, state in FAILURES]
        self.assertEqual(await deliveries.recover_message_delivery_failure_notices(self.manager), 0)
        self.manager.send.assert_not_awaited()
        for did in ids:
            self.assert_skipped(did, "target_archived")

    async def test_missing_target_is_acknowledged_without_wake(self):
        self.connection.execute("DELETE FROM sessions WHERE id='target'")
        ids = [self.failure(initial=initial, state=state) for initial, state in FAILURES]
        self.assertEqual(await deliveries.recover_message_delivery_failure_notices(self.manager), 0)
        self.manager.send.assert_not_awaited()
        for did in ids:
            self.assert_skipped(did, "target_missing")

    async def test_fresh_failure_wakes_live_sender_exactly_once(self):
        for initial, state in FAILURES:
            with self.subTest(initial=initial, state=state):
                self.manager.send.reset_mock()
                did = self.failure(initial=initial, state=state)
                self.assertEqual(await deliveries.recover_message_delivery_failure_notices(self.manager), 1)
                self.manager.send.assert_awaited_once()
                sid, message = self.manager.send.call_args.args
                self.assertEqual(sid, "source")
                self.assertIn(did, message.text)
                self.assertIn("original failure", message.text)
                self.assertEqual("UNKNOWN" in message.text, "UNKNOWN" in state)
                notice = deliveries._failure_notice(did)
                self.assertTrue(notice["delivered_at"])
                self.assertNotIn("_notice_skipped_reason", json.loads(notice["error_json"]))
                self.assertEqual(await deliveries.recover_message_delivery_failure_notices(self.manager), 0)
                self.manager.send.assert_awaited_once()

    async def test_second_backfill_never_replays_skipped_or_delivered_rows(self):
        old = self.failure(stamp=(NOW - timedelta(days=50)).isoformat())
        fresh = self.failure(initial=True)
        self.assertEqual(await deliveries.recover_message_delivery_failure_notices(self.manager), 1)
        self.manager.send.reset_mock()
        self.assertEqual(await deliveries.recover_message_delivery_failure_notices(self.manager), 0)
        self.manager.send.assert_not_awaited()
        self.assert_skipped(old, "outside_recent_window")
        self.assertTrue(deliveries._failure_notice(fresh)["delivered_at"])

    async def test_existing_live_notice_is_not_filtered_by_backfill(self):
        self.connection.execute("UPDATE sessions SET status='archived' WHERE id='target'")
        for initial in (False, True):
            did = self.failure(initial=initial, stamp=(NOW - timedelta(days=50)).isoformat())
            table = "initial_deliveries" if initial else "message_deliveries"
            row = self.connection.execute(f"SELECT * FROM {table} WHERE delivery_id=?", (did,)).fetchone()
            deliveries.record_delivery_failure(self.connection, row, initial=initial)
            self.assertIsNone(deliveries._failure_notice(did)["delivered_at"])
            self.assertEqual(await deliveries.recover_message_delivery_failure_notices(self.manager), 1)
            self.assertTrue(deliveries._failure_notice(did)["delivered_at"])
            self.assertNotIn("_notice_skipped_reason", json.loads(deliveries._failure_notice(did)["error_json"]))
        self.assertEqual(self.manager.send.await_count, 2)

    async def test_old_pending_legacy_notice_is_screened_on_adoption(self):
        did = self.failure(stamp=(NOW - timedelta(days=50)).isoformat())
        deliveries._ensure_failure_notice_schema(self.connection)
        self.connection.execute(
            "INSERT INTO message_delivery_failure_notices VALUES (?, 'source', 'worker', ?, ?, NULL)",
            (did, json.dumps({"message": "original failure"}), NOW.isoformat()),
        )
        self.assertEqual(await deliveries.recover_message_delivery_failure_notices(self.manager), 0)
        self.assert_skipped(did, "outside_recent_window")
        self.manager.send.assert_not_awaited()

    async def test_skipped_revision_does_not_prevent_fresh_failure_of_same_id(self):
        did = self.failure(stamp=(NOW - timedelta(days=50)).isoformat())
        self.assertEqual(await deliveries.recover_message_delivery_failure_notices(self.manager), 0)
        self.assert_skipped(did, "outside_recent_window")
        self.connection.execute(
            "UPDATE message_deliveries SET updated_at=? WHERE delivery_id=?",
            ((NOW - timedelta(minutes=1)).isoformat(), did),
        )
        self.assertEqual(await deliveries.recover_message_delivery_failure_notices(self.manager), 1)
        self.manager.send.assert_awaited_once()
        self.assertNotIn("_notice_skipped_reason", json.loads(deliveries._failure_notice(did)["error_json"]))

    async def test_window_uses_updated_at_with_inclusive_24_hour_boundary(self):
        self.assertEqual(deliveries.FAILURE_NOTICE_BACKFILL_MAX_AGE, timedelta(hours=24))
        cutoff = NOW - timedelta(hours=24)
        inside = self.failure(stamp=cutoff.isoformat())
        outside = self.failure(stamp=(cutoff - timedelta(microseconds=1)).isoformat())
        self.assertEqual(await deliveries.recover_message_delivery_failure_notices(self.manager), 1)
        self.assertIn(inside, self.manager.send.call_args.args[1].text)
        self.assert_skipped(outside, "outside_recent_window")

    async def test_invalid_and_future_dates_are_acknowledged_without_wake(self):
        invalid = self.failure(stamp="not-a-date")
        future = self.failure(stamp=(NOW + timedelta(seconds=1)).isoformat())
        self.assertEqual(await deliveries.recover_message_delivery_failure_notices(self.manager), 0)
        self.assert_skipped(invalid, "invalid_updated_at")
        self.assert_skipped(future, "outside_recent_window")
        self.manager.send.assert_not_awaited()

    async def test_legacy_naive_utc_and_offset_dates_can_wake(self):
        stamp = NOW - timedelta(hours=1)
        self.failure(stamp=stamp.replace(tzinfo=None).isoformat())
        self.failure(initial=True, stamp=stamp.astimezone(timezone(timedelta(hours=3))).isoformat())
        self.assertEqual(await deliveries.recover_message_delivery_failure_notices(self.manager), 2)
        self.assertEqual(self.manager.send.await_count, 2)

    async def test_legacy_acknowledged_notice_keeps_ack_and_does_not_replay(self):
        did = self.failure()
        deliveries._ensure_failure_notice_schema(self.connection)
        delivered = (NOW - timedelta(minutes=30)).isoformat()
        self.connection.execute(
            "INSERT INTO message_delivery_failure_notices VALUES (?, 'source', 'worker', ?, ?, ?)",
            (did, json.dumps({"message": "original failure"}), delivered, delivered),
        )
        self.assertEqual(await deliveries.recover_message_delivery_failure_notices(self.manager), 0)
        self.assertEqual(deliveries._failure_notice(did)["delivered_at"], delivered)
        self.manager.send.assert_not_awaited()

    async def test_failed_recent_wake_is_retried_once_on_recovery(self):
        did = self.failure()
        self.manager.send.side_effect = RuntimeError("sender temporarily unavailable")
        self.assertEqual(await deliveries.recover_message_delivery_failure_notices(self.manager), 0)
        self.assertIsNone(deliveries._failure_notice(did)["delivered_at"])
        self.manager.send.reset_mock(side_effect=True)
        self.assertEqual(await deliveries.recover_message_delivery_failure_notices(self.manager), 1)
        self.assertEqual(await deliveries.recover_message_delivery_failure_notices(self.manager), 0)
        self.manager.send.assert_awaited_once()

    async def test_live_notice_path_ignores_backfill_age_and_target_filters(self):
        self.connection.execute("UPDATE sessions SET status='archived' WHERE id='target'")
        for initial in (False, True):
            did = self.failure(initial=initial, stamp=(NOW - timedelta(days=50)).isoformat())
            table = "initial_deliveries" if initial else "message_deliveries"
            row = self.connection.execute(f"SELECT * FROM {table} WHERE delivery_id=?", (did,)).fetchone()
            deliveries.record_delivery_failure(self.connection, row, initial=initial)
            await deliveries.notify_message_delivery_failure(did, manager=self.manager)
            await deliveries.notify_message_delivery_failure(did, manager=self.manager)
            self.assertTrue(deliveries._failure_notice(did)["delivered_at"])
        self.assertEqual(self.manager.send.await_count, 2)


if __name__ == "__main__":
    unittest.main()
