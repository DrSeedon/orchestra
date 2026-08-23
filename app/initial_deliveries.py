"""Durable acceptance and dispatch for initial worker deliveries (#311)."""

import asyncio
import hashlib
import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone

from app import db
from app.errtext import err_text


SCHEMA_VERSION = 1
_runner_tasks: dict[str, asyncio.Task[None]] = {}
logger = logging.getLogger("orchestra.initial_deliveries")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _next_action(row: sqlite3.Row | dict) -> dict | None:
    state = row["state"]
    delivery_id = row["delivery_id"]
    if state in {"QUEUED", "PREPARING"}:
        return {
            "code": "WAIT_FOR_DELIVERY",
            "tool": "delivery_status",
            "arguments": {"delivery_id": delivery_id},
            "retryable": False,
            "message": "Wait for this accepted delivery and check the same delivery_id.",
        }
    if state == "FAILED_BEFORE_SUBMIT":
        return {
            "code": "RETRY_SAME_DELIVERY",
            "tool": "retry_initial_delivery",
            "arguments": {
                "name": row["worker_name"],
                "task": row["message"],
                "delivery_id": delivery_id,
            },
            "retryable": True,
            "message": "Retry only this known-not-submitted delivery with the same id.",
        }
    if state in {"DISPATCHING", "DELIVERY_UNKNOWN"}:
        return {
            "code": "CHECK_DELIVERY_STATUS",
            "tool": "delivery_status",
            "arguments": {"delivery_id": delivery_id},
            "retryable": False,
            "message": (
                "Provider acceptance may have occurred. Check this delivery_id; "
                "do not resend the initial task automatically."
            ),
        }
    if state == "SUBMITTED":
        return {
            "code": "NONE",
            "tool": None,
            "arguments": {},
            "retryable": False,
            "message": "Provider submission is recorded; no retry is allowed.",
        }
    return {
        "code": "QUARANTINED_DELIVERY_STATE",
        "tool": None,
        "arguments": {"delivery_id": delivery_id},
        "retryable": False,
        "message": (
            f"Delivery state {state!r} is unsupported; do not retry automatically."
        ),
    }


def _payload_hash(
    *,
    session_id: str,
    worker_name: str,
    scope: str,
    sender: str,
    message: str,
) -> str:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "session_id": session_id,
        "worker_name": worker_name,
        "scope": scope,
        "sender": sender,
        "message": message,
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_delivery_id(delivery_id: str) -> str:
    value = str(delivery_id)
    uuid.UUID(value)
    return value


def _resource(row: sqlite3.Row | dict) -> dict:
    error = json.loads(row["error_json"]) if row["error_json"] else None
    return {
        "ok": True,
        "delivery_id": row["delivery_id"],
        "delivery_state": row["state"],
        "payload_hash": row["payload_hash"],
        "status_url": f"/api/initial-deliveries/{row['delivery_id']}",
        "provider_ref": row["provider_ref"],
        "error": error,
        "next_action": _next_action(row),
    }


def get_initial_delivery(delivery_id: str, scope: str) -> dict | None:
    """Return one delivery only when its scope matches the caller's scope."""
    delivery_id = _validate_delivery_id(delivery_id)
    with db._conn() as connection:
        row = connection.execute(
            "SELECT * FROM initial_deliveries WHERE delivery_id=? AND scope=?",
            (delivery_id, scope),
        ).fetchone()
    return _resource(row) if row else None


def ensure_delivery_runner(delivery_id: str) -> None:
    """Start at most one local runner for a committed delivery."""
    current = _runner_tasks.get(delivery_id)
    if current is not None and not current.done():
        return
    task = asyncio.create_task(
        run_initial_delivery(delivery_id),
        name=f"initial-delivery:{delivery_id}",
    )
    _runner_tasks[delivery_id] = task
    task.add_done_callback(_observe_runner)


async def accept_initial_delivery(
    *,
    delivery_id: str,
    session_id: str,
    worker_name: str,
    scope: str,
    sender: str,
    message: str,
) -> tuple[dict, int]:
    """Atomically accept an idempotent delivery, then wake its runner once."""
    delivery_id = _validate_delivery_id(delivery_id)
    payload_hash = _payload_hash(
        session_id=session_id,
        worker_name=worker_name,
        scope=scope,
        sender=sender,
        message=message,
    )
    now = _now()
    connection = db._conn()
    wake_runner = False
    resource = None
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT * FROM initial_deliveries WHERE delivery_id=?",
            (delivery_id,),
        ).fetchone()
        if row:
            if row["payload_hash"] != payload_hash:
                connection.rollback()
                return {
                    "ok": False,
                    "delivery_id": delivery_id,
                    "error": {
                        "code": "IDEMPOTENCY_CONFLICT",
                        "message": "delivery id is already bound to another payload",
                    },
                }, 409
            if row["state"] == "FAILED_BEFORE_SUBMIT":
                cursor = connection.execute(
                    """UPDATE initial_deliveries
                       SET state='PREPARING', error_json=NULL, updated_at=?
                       WHERE delivery_id=? AND state='FAILED_BEFORE_SUBMIT'""",
                    (now, delivery_id),
                )
                row = connection.execute(
                    "SELECT * FROM initial_deliveries WHERE delivery_id=?",
                    (delivery_id,),
                ).fetchone()
                resource = _resource(row)
                connection.commit()
                wake_runner = cursor.rowcount == 1
            else:
                connection.commit()
                return _resource(row), 202
        else:
            connection.execute(
                """INSERT INTO initial_deliveries (
                       delivery_id, schema_version, session_id, worker_name, scope,
                       sender, message, payload_hash, state, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'QUEUED', ?, ?)""",
                (
                    delivery_id,
                    SCHEMA_VERSION,
                    session_id,
                    worker_name,
                    scope,
                    sender,
                    message,
                    payload_hash,
                    now,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM initial_deliveries WHERE delivery_id=?",
                (delivery_id,),
            ).fetchone()
            resource = _resource(row)
            connection.commit()
            wake_runner = True
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    if wake_runner:
        ensure_delivery_runner(delivery_id)
    return resource, 202


def prepare_initial_delivery(delivery_id: str) -> dict:
    """Commit the sole user log and QUEUED -> PREPARING atomically."""
    delivery_id = _validate_delivery_id(delivery_id)
    with db._conn() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT * FROM initial_deliveries WHERE delivery_id=?",
            (delivery_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"initial delivery not found: {delivery_id}")
        if row["state"] == "QUEUED":
            from app.secret_mask import mask_secrets

            cursor = connection.execute(
                """INSERT INTO logs (session_id, ts, type, content)
                   VALUES (?, ?, 'user_message', ?)""",
                (row["session_id"], _now(), mask_secrets(row["message"])),
            )
            user_log_id = cursor.lastrowid
            connection.execute(
                """UPDATE initial_deliveries
                   SET state='PREPARING', user_log_id=?, error_json=NULL, updated_at=?
                   WHERE delivery_id=? AND state='QUEUED'""",
                (user_log_id, _now(), delivery_id),
            )
            row = connection.execute(
                "SELECT * FROM initial_deliveries WHERE delivery_id=?",
                (delivery_id,),
            ).fetchone()
        elif row["state"] != "PREPARING":
            return {**_resource(row), "user_log_id": row["user_log_id"]}

        if row["user_log_id"] is None:
            raise RuntimeError(
                f"PREPARING delivery has no immutable user log: {delivery_id}"
            )
        user_log = connection.execute(
            "SELECT content FROM logs WHERE id=? AND session_id=?",
            (row["user_log_id"], row["session_id"]),
        ).fetchone()
        if user_log is None:
            raise RuntimeError(
                f"PREPARING delivery user log is missing: {delivery_id}"
            )
        return {
            **_resource(row),
            "user_log_id": row["user_log_id"],
            "history_user_message": user_log["content"],
        }


def mark_initial_delivery_dispatching(delivery_id: str) -> dict:
    """Commit the fail-closed boundary immediately before provider submission."""
    delivery_id = _validate_delivery_id(delivery_id)
    with db._conn() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT * FROM initial_deliveries WHERE delivery_id=?",
            (delivery_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"initial delivery not found: {delivery_id}")
        if row["state"] != "PREPARING" or row["user_log_id"] is None:
            raise RuntimeError(
                f"initial delivery {delivery_id} cannot dispatch from {row['state']}"
            )
        connection.execute(
            """UPDATE initial_deliveries
               SET state='DISPATCHING', updated_at=?
               WHERE delivery_id=? AND state='PREPARING'""",
            (_now(), delivery_id),
        )
        row = connection.execute(
            "SELECT * FROM initial_deliveries WHERE delivery_id=?",
            (delivery_id,),
        ).fetchone()
        return _resource(row)


def mark_initial_delivery_submitted(
    delivery_id: str, *, provider_ref: str | None = None,
) -> dict:
    """Record that the backend submission call returned successfully."""
    delivery_id = _validate_delivery_id(delivery_id)
    provider_ref = provider_ref if isinstance(provider_ref, str) and provider_ref else None
    with db._conn() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT * FROM initial_deliveries WHERE delivery_id=?",
            (delivery_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"initial delivery not found: {delivery_id}")
        if row["state"] == "SUBMITTED":
            return _resource(row)
        if row["state"] != "DISPATCHING":
            raise RuntimeError(
                f"initial delivery {delivery_id} cannot submit from {row['state']}"
            )
        connection.execute(
            """UPDATE initial_deliveries
               SET state='SUBMITTED', provider_ref=?, error_json=NULL, updated_at=?
               WHERE delivery_id=? AND state='DISPATCHING'""",
            (provider_ref, _now(), delivery_id),
        )
        row = connection.execute(
            "SELECT * FROM initial_deliveries WHERE delivery_id=?",
            (delivery_id,),
        ).fetchone()
        return _resource(row)


def _unknown_error(error: BaseException, *, orphaned: bool = False) -> dict:
    return {
        "code": "DELIVERY_OUTCOME_UNKNOWN",
        "message": (
            "Server restarted while provider acceptance was in flight; delivery may "
            "already have been accepted."
            if orphaned
            else f"Provider acceptance outcome is unknown: {err_text(error)}"
        ),
        "retryable": False,
        "outcome_unknown": True,
        "details": {
            "phase": "PROVIDER_CALL_STARTED",
            "exception_type": type(error).__name__,
        },
    }


def _not_submitted_error(error: BaseException) -> dict:
    return {
        "code": "DELIVERY_NOT_SUBMITTED",
        "message": f"Provider submission did not begin: {err_text(error)}",
        "retryable": True,
        "outcome_unknown": False,
        "details": {
            "phase": "PRE_PROVIDER",
            "exception_type": type(error).__name__,
        },
    }


def mark_initial_delivery_failed_before_submit(
    delivery_id: str, error: BaseException,
) -> dict:
    """Record a committed delivery whose provider call provably did not begin."""
    delivery_id = _validate_delivery_id(delivery_id)
    error_json = json.dumps(
        _not_submitted_error(error),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    with db._conn() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT * FROM initial_deliveries WHERE delivery_id=?",
            (delivery_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"initial delivery not found: {delivery_id}")
        if row["state"] == "FAILED_BEFORE_SUBMIT":
            return _resource(row)
        if row["state"] != "PREPARING":
            return _resource(row)
        connection.execute(
            """UPDATE initial_deliveries
               SET state='FAILED_BEFORE_SUBMIT', error_json=?, updated_at=?
               WHERE delivery_id=? AND state='PREPARING'""",
            (error_json, _now(), delivery_id),
        )
        row = connection.execute(
            "SELECT * FROM initial_deliveries WHERE delivery_id=?",
            (delivery_id,),
        ).fetchone()
        return _resource(row)


def mark_initial_delivery_unknown(
    delivery_id: str, error: BaseException, *, orphaned: bool = False,
) -> dict:
    """Quarantine an ambiguous dispatch without making it replayable."""
    delivery_id = _validate_delivery_id(delivery_id)
    error_json = json.dumps(
        _unknown_error(error, orphaned=orphaned),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    with db._conn() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT * FROM initial_deliveries WHERE delivery_id=?",
            (delivery_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"initial delivery not found: {delivery_id}")
        if row["state"] in {"DELIVERY_UNKNOWN", "SUBMITTED"}:
            return _resource(row)
        if row["state"] != "DISPATCHING":
            return _resource(row)
        connection.execute(
            """UPDATE initial_deliveries
               SET state='DELIVERY_UNKNOWN', error_json=?, updated_at=?
               WHERE delivery_id=? AND state='DISPATCHING'""",
            (error_json, _now(), delivery_id),
        )
        row = connection.execute(
            "SELECT * FROM initial_deliveries WHERE delivery_id=?",
            (delivery_id,),
        ).fetchone()
        return _resource(row)


class InitialDeliveryContext:
    """Session-side persistence hooks for one prepared initial delivery."""

    def __init__(self, delivery_id: str, *, history_user_message: str):
        self.delivery_id = _validate_delivery_id(delivery_id)
        self.history_user_message = history_user_message
        self.dispatched = False

    async def before_submit(self) -> None:
        if self.dispatched:
            raise RuntimeError(f"initial delivery already dispatching: {self.delivery_id}")
        mark_initial_delivery_dispatching(self.delivery_id)
        self.dispatched = True

    async def mark_submitted(self, provider_ref: str | None = None) -> None:
        mark_initial_delivery_submitted(
            self.delivery_id,
            provider_ref=provider_ref,
        )

    async def mark_unknown(self, error: BaseException) -> None:
        if self.dispatched:
            mark_initial_delivery_unknown(self.delivery_id, error)


async def run_initial_delivery(delivery_id: str, *, manager=None) -> None:
    """Prepare and submit one delivery, never replaying an ambiguous dispatch."""
    prepared = prepare_initial_delivery(delivery_id)
    if prepared["delivery_state"] != "PREPARING":
        return
    if manager is None:
        from app.deps import manager as session_manager

        manager = session_manager
    context = InitialDeliveryContext(
        delivery_id,
        history_user_message=prepared["history_user_message"],
    )
    payload = _delivery_payload(delivery_id)
    try:
        await manager.send_initial_delivery(
            payload["session_id"],
            payload["message"],
            delivery=context,
        )
    except asyncio.CancelledError as error:
        if context.dispatched:
            mark_initial_delivery_unknown(delivery_id, error)
        else:
            mark_initial_delivery_failed_before_submit(delivery_id, error)
        raise
    except Exception as error:
        if context.dispatched:
            mark_initial_delivery_unknown(delivery_id, error)
        else:
            mark_initial_delivery_failed_before_submit(delivery_id, error)
        raise


def _delivery_payload(delivery_id: str) -> sqlite3.Row:
    with db._conn() as connection:
        row = connection.execute(
            "SELECT * FROM initial_deliveries WHERE delivery_id=?",
            (delivery_id,),
        ).fetchone()
    if row is None:
        raise KeyError(f"initial delivery not found: {delivery_id}")
    return row


def _observe_runner(task: asyncio.Task[None]) -> None:
    for delivery_id, current in list(_runner_tasks.items()):
        if current is task:
            _runner_tasks.pop(delivery_id, None)
            break
    if task.cancelled():
        return
    try:
        task.result()
    except Exception:
        logger.exception("initial delivery runner failed")


async def recover_initial_deliveries() -> None:
    """Quarantine orphan dispatches and schedule only proven pre-submit states."""
    orphan_error = RuntimeError("orphaned provider dispatch")
    with db._conn() as connection:
        connection.execute("BEGIN IMMEDIATE")
        dispatching = connection.execute(
            "SELECT delivery_id FROM initial_deliveries WHERE state='DISPATCHING'"
        ).fetchall()
        error_json = json.dumps(
            _unknown_error(orphan_error, orphaned=True),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        for row in dispatching:
            connection.execute(
                """UPDATE initial_deliveries
                   SET state='DELIVERY_UNKNOWN', error_json=?, updated_at=?
                   WHERE delivery_id=? AND state='DISPATCHING'""",
                (error_json, _now(), row["delivery_id"]),
            )
        replayable = connection.execute(
            """SELECT delivery_id FROM initial_deliveries
               WHERE state IN ('QUEUED', 'PREPARING') ORDER BY created_at, delivery_id"""
        ).fetchall()

    for row in replayable:
        ensure_delivery_runner(row["delivery_id"])
