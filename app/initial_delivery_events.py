"""Durable parent notifications for quota-held initial worker tasks."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid

from app import db
from app.errtext import err_text
from app.events import MessageProvenance

logger = logging.getLogger("orchestra.initial_delivery_events")

_DDL = """
CREATE TABLE IF NOT EXISTS initial_delivery_events (
    event_id TEXT PRIMARY KEY,
    delivery_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    worker_name TEXT NOT NULL,
    scope TEXT NOT NULL,
    event_type TEXT NOT NULL CHECK(event_type IN ('WAITING_QUOTA','SUBMITTED')),
    reason TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL CHECK(state IN ('pending','delivered','covered_by_receipt')),
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at REAL NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    delivered_at REAL
);
CREATE INDEX IF NOT EXISTS idx_initial_delivery_events_pending
    ON initial_delivery_events(next_attempt_at) WHERE state='pending';
"""

RETRY_BASE_S = 30.0
RETRY_MAX_S = 900.0
SEND_TIMEOUT_S = 120.0
_inflight: set[str] = set()
_runner_task: asyncio.Task | None = None


def ensure_schema(connection=None) -> None:
    if connection is None:
        with db._conn() as owned:
            owned.executescript(_DDL)
    else:
        connection.executescript(_DDL)


def record_waiting(
    connection,
    row,
    reason: str,
    *,
    covered_by_receipt: bool,
) -> str:
    event_id = str(uuid.uuid4())
    now = time.time()
    connection.execute(
        """INSERT INTO initial_delivery_events
           (event_id, delivery_id, session_id, worker_name, scope, event_type,
            reason, state, created_at, delivered_at)
           VALUES (?, ?, ?, ?, ?, 'WAITING_QUOTA', ?, ?, ?, ?)""",
        (
            event_id, row["delivery_id"], row["session_id"], row["worker_name"],
            row["scope"], reason, "covered_by_receipt" if covered_by_receipt else "pending",
            now, now if covered_by_receipt else None,
        ),
    )
    return event_id


def record_submitted(connection, row) -> str | None:
    waiting = connection.execute(
        """SELECT 1 FROM initial_delivery_events
           WHERE delivery_id=? AND event_type='WAITING_QUOTA' LIMIT 1""",
        (row["delivery_id"],),
    ).fetchone()
    if waiting is None:
        return None
    event_id = str(uuid.uuid4())
    connection.execute(
        """INSERT INTO initial_delivery_events
           (event_id, delivery_id, session_id, worker_name, scope, event_type,
            reason, state, created_at)
           VALUES (?, ?, ?, ?, ?, 'SUBMITTED', '', 'pending', ?)""",
        (
            event_id, row["delivery_id"], row["session_id"], row["worker_name"],
            row["scope"], time.time(),
        ),
    )
    return event_id


def _due() -> list[dict]:
    ensure_schema()
    with db._conn() as connection:
        rows = connection.execute(
            """SELECT * FROM initial_delivery_events
               WHERE state='pending' AND next_attempt_at<=? ORDER BY created_at,event_id""",
            (time.time(),),
        ).fetchall()
    return [dict(row) for row in rows if row["event_id"] not in _inflight]


def _already_in_parent_log(parent_id: str, event_id: str) -> bool:
    with db._conn() as connection:
        return connection.execute(
            """SELECT 1 FROM logs WHERE session_id=? AND type='user_message'
               AND origin='platform' AND origin_detail LIKE ? LIMIT 1""",
            (parent_id, f'%"ref":"{event_id}"%'),
        ).fetchone() is not None


async def _resolve_parent(manager, row: dict):
    worker = db.get_session(row["session_id"]) or {}
    if worker.get("parent_id"):
        return await manager.ensure_loaded_by_id(worker["parent_id"])
    if worker.get("parent_name"):
        return await manager.ensure_loaded(worker["parent_name"], row["scope"])
    try:
        name = manager._find_orchestrator_name(row["scope"])
    except ValueError:
        name = None
    return await manager.ensure_loaded(name, row["scope"]) if name else None


def _message(row: dict) -> str:
    if row["event_type"] == "WAITING_QUOTA":
        return (
            f"Initial task for worker '{row['worker_name']}' is WAITING_QUOTA; "
            f"delivery_id={row['delivery_id']}. Reason: {row['reason']}"
        )
    return (
        f"Initial task for worker '{row['worker_name']}' is SUBMITTED after its "
        f"quota wait; delivery_id={row['delivery_id']}."
    )


def _finish(event_id: str, error: str = "") -> None:
    with db._conn() as connection:
        connection.execute(
            """UPDATE initial_delivery_events
               SET state='delivered',last_error=?,delivered_at=?
               WHERE event_id=? AND state='pending'""",
            (error, time.time(), event_id),
        )


def _retry_later(event_id: str, error: BaseException) -> None:
    with db._conn() as connection:
        row = connection.execute(
            "SELECT attempts FROM initial_delivery_events WHERE event_id=? AND state='pending'",
            (event_id,),
        ).fetchone()
        if row is None:
            return
        attempts = row["attempts"] + 1
        delay = min(RETRY_BASE_S * (2 ** (attempts - 1)), RETRY_MAX_S)
        connection.execute(
            """UPDATE initial_delivery_events
               SET attempts=?,next_attempt_at=?,last_error=?
               WHERE event_id=? AND state='pending'""",
            (attempts, time.time() + delay, err_text(error), event_id),
        )


async def deliver_due(manager) -> int:
    rows = _due()
    delivered = 0
    _inflight.update(row["event_id"] for row in rows)
    try:
        for row in rows:
            event_id = row["event_id"]
            try:
                parent = await _resolve_parent(manager, row)
                if parent is None:
                    raise LookupError("parent session is unavailable")
                if _already_in_parent_log(parent.id, event_id):
                    _finish(event_id, "found in parent log")
                    delivered += 1
                    continue
                await asyncio.wait_for(
                    manager.send(
                        parent.id,
                        _message(row),
                        provenance=MessageProvenance(
                            origin="platform", senders=("Orchestra",),
                            subtype="initial_delivery_event", ref=event_id,
                        ),
                    ),
                    timeout=SEND_TIMEOUT_S,
                )
                _finish(event_id)
                delivered += 1
            except asyncio.CancelledError:
                raise
            except Exception as error:
                try:
                    _retry_later(event_id, error)
                except Exception:
                    logger.exception("initial delivery event %s retry state failed", event_id)
                else:
                    logger.warning(
                        "initial delivery event %s not delivered: %s",
                        event_id, err_text(error),
                    )
    finally:
        _inflight.difference_update(row["event_id"] for row in rows)
    return delivered


def ensure_runner(manager) -> asyncio.Task:
    global _runner_task
    if _runner_task is not None and not _runner_task.done():
        return _runner_task
    task = asyncio.create_task(deliver_due(manager), name="initial-delivery-events")
    _runner_task = task

    def observe(done: asyncio.Task) -> None:
        global _runner_task
        if _runner_task is done:
            _runner_task = None
        if done.cancelled():
            return
        try:
            done.result()
        except Exception:
            logger.exception("initial delivery event runner failed")
        try:
            if _due():
                ensure_runner(manager)
        except Exception:
            logger.exception("could not reschedule pending initial delivery events")

    task.add_done_callback(observe)
    return task
