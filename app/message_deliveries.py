"""Durable, caller-keyed direct-message acceptance and dispatch (#380)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone

from app import db
from app.errtext import err_text
from app.events import MessageProvenance

logger = logging.getLogger("orchestra.message_deliveries")
SCHEMA_VERSION = 2
_target_runner_tasks: dict[str, asyncio.Task[bool]] = {}
_target_delivery_locks: dict[str, asyncio.Lock] = {}


class TargetTaskChangedError(RuntimeError):
    """The accepted target lifecycle generation no longer matches."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_id(value: str) -> str:
    value = str(value)
    return str(uuid.UUID(value))


def _payload_hash(**payload: object) -> str:
    encoded = json.dumps(
        {"protocol": "direct-message/v1", **payload},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _resource(row: sqlite3.Row | dict, *, acceptance: str = "ACCEPTED") -> dict:
    error = json.loads(row["error_json"]) if row["error_json"] else None
    return {
        "ok": True,
        "acceptance": acceptance,
        "delivery_id": row["delivery_id"],
        "delivery_state": row["state"],
        "payload_hash": row["payload_hash"],
        "accept_seq": row["accept_seq"],
        "status_url": f"/api/message-deliveries/{row['delivery_id']}",
        "provider_ref": row["provider_ref"],
        "error": error,
        "next_action": _next_action(row),
    }


def _queue_block(row: sqlite3.Row | dict) -> dict:
    """Почему принятое сообщение никуда не поедет: неразобранная голова очереди.

    Барьер `DELIVERY_UNKNOWN` намеренный (#380 R7), но молчать про него нельзя:
    отправитель получал бодрый `state=QUEUED` на каждое следующее сообщение, воркер
    выглядел живым и глухим, и так простояли 25 часов и три задания.
    """
    head = _next_target_delivery(row["target_session_id"])
    if (
        head is None
        or head["state"] != "DELIVERY_UNKNOWN"
        or head["delivery_id"] == row["delivery_id"]
    ):
        return {}
    return {
        "code": "TARGET_QUEUE_BLOCKED",
        "tool": "message_delivery_status",
        "arguments": {"delivery_id": head["delivery_id"]},
        "blocked_since": head["updated_at"],
        "retryable": False,
        "message": (
            f"Message accepted but NOT delivered: the target queue has been blocked "
            f"since {head['updated_at']} by delivery {head['delivery_id']}, whose "
            "provider outcome is still unknown. Nothing queued after it moves while "
            "that outcome could still change. Do not resend this message: the next "
                "operator can restart only the target CLI to release the queue; "
                "the ambiguous message will NOT be resent."
        ),
    }


def _next_action(row: sqlite3.Row | dict) -> dict:
    # Блокировка очереди едет в `next_action`, а не отдельным ключом: это единственное
    # поле receipt'а, которое читают потребители остальных доставок и мержей, — второй
    # носитель той же мысли просто никто бы не открыл.
    if row["state"] == "QUEUED":
        return _queue_block(row)
    if row["state"] in {"DISPATCHING", "DELIVERY_UNKNOWN"}:
        return {
            "code": "CHECK_DELIVERY_STATUS",
            "tool": "message_delivery_status",
            "arguments": {"delivery_id": row["delivery_id"]},
            "retryable": False,
            "message": (
                "Provider acceptance may have occurred. Check this delivery_id; "
                "do not resend the direct message automatically."
            ),
        }
    if row["state"] == "DELIVERY_UNKNOWN_ORPHANED":
        # Рестарт снимает БАРЬЕР, а не неизвестность: исход провайдера так и не выяснен.
        # Пустой `next_action` здесь читался бы отправителем как «доставлено» — ровно то
        # утверждение, которого у нас нет.
        return {
            "code": "DELIVERY_OUTCOME_UNRECONCILED",
            "retryable": False,
            "message": (
                "A restart settled this delivery: the process that could still have "
                "completed it is gone, so it no longer holds the queue. The provider "
                "outcome was never established — it may or may not have reached the "
                "target. Do not assume delivery, and do not resend automatically."
            ),
        }
    return {}


def _row(delivery_id: str) -> sqlite3.Row | None:
    with db._conn() as connection:
        return connection.execute(
            "SELECT * FROM message_deliveries WHERE delivery_id=?",
            (delivery_id,),
        ).fetchone()


def get_message_delivery(delivery_id: str, source_session_id: str) -> dict | None:
    delivery_id = _validate_id(delivery_id)
    with db._conn() as connection:
        row = connection.execute(
            "SELECT * FROM message_deliveries WHERE delivery_id=? AND source_session_id=?",
            (delivery_id, source_session_id),
        ).fetchone()
    return _resource(row, acceptance="ALREADY_ACCEPTED") if row else None


def _conflict(delivery_id: str) -> tuple[dict, int]:
    return {
        "ok": False,
        "delivery_id": delivery_id,
        "error": {
            "code": "IDEMPOTENCY_CONFLICT",
            "message": "delivery id is already bound to another payload",
            "outcome_unknown": False,
        },
    }, 409


async def accept_message_delivery(
    *,
    delivery_id: str,
    source_session_id: str | None = None,
    source_principal: str = "",
    source_name: str = "",
    source_scope: str,
    source_task_id: str = "",
    target_session_id: str,
    target_name: str,
    target_scope: str,
    target_task_id: str = "",
    target_generation: str,
    message: str,
    rendered_message: str,
    message_kind: str | None = None,
    wake: bool = True,
    provenance: MessageProvenance,
) -> tuple[dict, int]:
    """Commit one receipt, then best-effort wake its target runner."""
    delivery_id = _validate_id(delivery_id)
    origin, origin_detail = provenance.to_storage()
    payload_hash = _payload_hash(
        source_session_id=source_session_id,
        source_principal=source_principal,
        source_scope=source_scope,
        source_task_id=source_task_id,
        target_session_id=target_session_id,
        target_scope=target_scope,
        target_task_id=target_task_id,
        target_generation=target_generation,
        message=message,
        rendered_message=rendered_message,
        message_kind=message_kind,
        wake=bool(wake),
        origin=origin,
        origin_detail=json.loads(origin_detail),
    )
    now = _now()
    connection = db._conn()
    inserted = False
    retrying = False
    wake_runner = False
    resource: dict | None = None
    try:
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute(
            "SELECT * FROM message_deliveries WHERE delivery_id=?", (delivery_id,)
        ).fetchone()
        if existing is not None:
            if existing["payload_hash"] != payload_hash:
                connection.rollback()
                return _conflict(delivery_id)
            if existing["state"] == "FAILED_BEFORE_SUBMIT":
                connection.execute(
                    """UPDATE message_deliveries
                       SET state='PREPARING', error_json=NULL, updated_at=?
                       WHERE delivery_id=? AND state='FAILED_BEFORE_SUBMIT'""",
                    (now, delivery_id),
                )
                existing = connection.execute(
                    "SELECT * FROM message_deliveries WHERE delivery_id=?",
                    (delivery_id,),
                ).fetchone()
                retrying = True
            if not retrying:
                connection.commit()
                return _resource(existing, acceptance="ALREADY_ACCEPTED"), 202
            resource = _resource(existing, acceptance="ALREADY_ACCEPTED")
        if not retrying:
            connection.execute(
                """INSERT INTO message_deliveries (
                    delivery_id, schema_version, source_session_id, source_principal,
                    source_name, source_scope, source_task_id, target_session_id,
                    target_name, target_scope, target_task_id, target_generation,
                    message, rendered_message, message_kind, wake, payload_hash,
                    origin, origin_detail,
                    state, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'QUEUED', ?, ?)""",
                (
                    delivery_id, SCHEMA_VERSION, source_session_id, source_principal,
                    source_name, source_scope, source_task_id, target_session_id,
                    target_name, target_scope, target_task_id, target_generation,
                    message, rendered_message, message_kind, int(bool(wake)), payload_hash,
                    origin, origin_detail,
                    now, now,
                ),
            )
            inserted_row = connection.execute(
                "SELECT * FROM message_deliveries WHERE delivery_id=?", (delivery_id,)
            ).fetchone()
            resource = _resource(inserted_row)
            inserted = True
        connection.commit()
        wake_runner = inserted or retrying
    except Exception:
        try:
            connection.rollback()
        except Exception:
            pass
        # SQLite may have committed the transaction and lost only its acknowledgement.
        committed = _row(delivery_id)
        if committed is not None:
            if committed["payload_hash"] != payload_hash:
                return _conflict(delivery_id)
            resource = _resource(committed, acceptance="ALREADY_ACCEPTED")
            if retrying:
                wake_runner = committed["state"] == "PREPARING"
            else:
                inserted = True
                wake_runner = True
        else:
            raise
    finally:
        connection.close()

    if wake_runner:
        try:
            ensure_target_runner(target_session_id)
        except Exception as error:
            logger.warning("message delivery runner wake failed: %s", err_text(error))
    return resource, 202


def prepare_message_delivery(delivery_id: str) -> dict:
    delivery_id = _validate_id(delivery_id)
    with db._conn() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT * FROM message_deliveries WHERE delivery_id=?", (delivery_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"message delivery not found: {delivery_id}")
        if row["state"] == "QUEUED":

            cursor = connection.execute(
                """INSERT INTO logs (
                       session_id, ts, type, content, origin, origin_detail
                   ) VALUES (?, ?, 'user_message', ?, ?, ?)""",
                (
                    row["target_session_id"], _now(),
                    row["rendered_message"],
                    row["origin"], row["origin_detail"],
                ),
            )
            connection.execute(
                """UPDATE message_deliveries
                   SET state='PREPARING', user_log_id=?, updated_at=?
                   WHERE delivery_id=? AND state='QUEUED'""",
                (cursor.lastrowid, _now(), delivery_id),
            )
            row = connection.execute(
                "SELECT * FROM message_deliveries WHERE delivery_id=?", (delivery_id,)
            ).fetchone()
        if row["state"] != "PREPARING":
            return _resource(row)
        user_log = connection.execute(
            "SELECT content FROM logs WHERE id=?", (row["user_log_id"],)
        ).fetchone()
        return {
            **_resource(row),
            "user_log_id": row["user_log_id"],
            "history_user_message": user_log["content"] if user_log else row["rendered_message"],
            "provenance": MessageProvenance.from_storage(
                row["origin"], row["origin_detail"]
            ),
        }


def _update_state(delivery_id: str, state: str, *, provider_ref: str | None = None,
                  error: dict | None = None, clear_user_log: bool = False) -> dict:
    with db._conn() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT * FROM message_deliveries WHERE delivery_id=?", (delivery_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"message delivery not found: {delivery_id}")
        values = (provider_ref, json.dumps(error, ensure_ascii=False) if error else None,
                  _now(), delivery_id)
        connection.execute(
            "UPDATE message_deliveries SET state=?, provider_ref=?, error_json=?, updated_at=? WHERE delivery_id=?",
            (state, *values),
        )
        if clear_user_log and row["user_log_id"] is not None:
            connection.execute(
                "DELETE FROM logs WHERE id=? AND session_id=? AND type='user_message'",
                (row["user_log_id"], row["target_session_id"]),
            )
            connection.execute(
                "UPDATE message_deliveries SET user_log_id=NULL WHERE delivery_id=?",
                (delivery_id,),
            )
        row = connection.execute(
            "SELECT * FROM message_deliveries WHERE delivery_id=?", (delivery_id,)
        ).fetchone()
        return _resource(row)


def mark_message_delivery_dispatching(delivery_id: str) -> dict:
    row = _row(_validate_id(delivery_id))
    if row is None or row["state"] != "PREPARING":
        raise RuntimeError(f"message delivery {delivery_id} cannot dispatch")
    return _update_state(delivery_id, "DISPATCHING")


def mark_message_delivery_submitted(delivery_id: str, provider_ref: str | None = None) -> dict:
    row = _row(_validate_id(delivery_id))
    if row is not None and row["state"] == "SUBMITTED":
        return _resource(row)
    if row is None or row["state"] != "DISPATCHING":
        raise RuntimeError(f"message delivery {delivery_id} cannot submit")
    return _update_state(delivery_id, "SUBMITTED", provider_ref=provider_ref)


def _mark_message_delivery_fan_buffered(delivery_id: str, fan_id: str) -> dict:
    row = _row(_validate_id(delivery_id))
    if row is None or row["state"] != "PREPARING":
        raise RuntimeError(f"message delivery {delivery_id} cannot buffer")
    return _update_state(
        delivery_id,
        "SUBMITTED",
        provider_ref=f"fan:{fan_id}:buffered",
        clear_user_log=True,
    )


def _failure(error: BaseException) -> dict:
    if isinstance(error, TargetTaskChangedError):
        return {
            "code": "TARGET_TASK_CHANGED",
            "message": err_text(error),
            "retryable": False,
            "outcome_unknown": False,
        }
    return {
        "code": "DELIVERY_NOT_SUBMITTED",
        "message": f"Provider submission did not begin: {err_text(error)}",
        "retryable": True,
        "outcome_unknown": False,
    }


def mark_message_delivery_failed_before_submit(delivery_id: str, error: BaseException) -> dict:
    from app.quota_gate import QuotaGateError

    # A quota refusal is known before any provider work; retaining its prepared
    # user-log would make the dashboard claim that a turn was delivered.
    return _update_state(
        delivery_id,
        "FAILED_BEFORE_SUBMIT",
        error=_failure(error),
        clear_user_log=isinstance(error, QuotaGateError),
    )


def mark_message_delivery_unknown(delivery_id: str, error: BaseException, *, orphaned: bool = False) -> dict:
    error_json = json.dumps(
        {
            "code": "DELIVERY_OUTCOME_UNKNOWN",
            "message": (
                "Server restarted while provider acceptance was in flight; delivery may "
                "already have been accepted."
                if orphaned
                else "Provider acceptance may have occurred: " + err_text(error)
            ),
            "retryable": False,
            "outcome_unknown": True,
            "details": {
                "phase": "PROVIDER_CALL_STARTED",
                "exception_type": type(error).__name__,
            },
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    delivery_id = _validate_id(delivery_id)
    with db._conn() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT * FROM message_deliveries WHERE delivery_id=?", (delivery_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"message delivery not found: {delivery_id}")
        if row["state"] in {"DELIVERY_UNKNOWN", "SUBMITTED"}:
            return _resource(row)
        if row["state"] != "DISPATCHING":
            return _resource(row)
        connection.execute(
            """UPDATE message_deliveries
               SET state='DELIVERY_UNKNOWN', error_json=?, updated_at=?
               WHERE delivery_id=? AND state='DISPATCHING'""",
            (error_json, _now(), delivery_id),
        )
        row = connection.execute(
            "SELECT * FROM message_deliveries WHERE delivery_id=?", (delivery_id,)
        ).fetchone()
        return _resource(row)


class MessageDeliveryContext:
    allow_running = True

    def __init__(
        self, delivery_id: str, *, history_user_message: str,
        provenance: MessageProvenance,
    ):
        self.delivery_id = _validate_id(delivery_id)
        self.history_user_message = history_user_message
        self.provenance = provenance
        self.dispatched = False

    async def before_submit(self) -> None:
        mark_message_delivery_dispatching(self.delivery_id)
        self.dispatched = True

    async def mark_submitted(self, provider_ref: str | None = None) -> None:
        mark_message_delivery_submitted(self.delivery_id, provider_ref)

    async def mark_unknown(self, error: BaseException) -> None:
        if self.dispatched:
            mark_message_delivery_unknown(self.delivery_id, error)


# Голова очереди — первое НЕЗАВЕРШЁННОЕ сообщение. Раньше здесь стояло только
# `state != 'SUBMITTED'`, поэтому `FAILED_BEFORE_SUBMIT` (например от QuotaGateError)
# навсегда вставал во главе: `ensure_target_runner` видел «голова не QUEUED» и молча
# выходил, а всё пришедшее ПОСЛЕ не отправлялось никогда. Воркер выглядел живым и глухим —
# 26.08 так потерялись 6 заданий подряд, отправитель получал QUEUED на каждое.
#
# `DELIVERY_UNKNOWN` в этот набор НЕ входит и входить не должен: он означает «неизвестно,
# ушло ли», и барьер там СОЗНАТЕЛЬНЫЙ (#380 R7) — пропустив его, мы рискуем доставить
# следующее сообщение раньше, чем выяснится судьба предыдущего, то есть переставить
# порядок или продублировать. Отказ ДО отправки такой неоднозначности не создаёт.
# `DELIVERY_UNKNOWN_ORPHANED` ставит РЕСТАРТ, и барьером он не является: процесс,
# который мог дослать сообщение, мёртв, поэтому переставить порядок оно уже не может —
# а именно перестановки и дубля барьер и не допускает. Исход так и остался неизвестным,
# и запись об этом хранит состояние; блокировать очередь ему больше незачем.
_TERMINAL_DELIVERY_STATES = (
    "SUBMITTED", "FAILED_BEFORE_SUBMIT", "DELIVERY_UNKNOWN_ORPHANED",
)


def targets_with_uncertain_delivery() -> set[str]:
    """One batch projection for the session list, not one DB query per worker."""
    with db._conn() as connection:
        return {row[0] for row in connection.execute(
            "SELECT DISTINCT target_session_id FROM message_deliveries WHERE state='DELIVERY_UNKNOWN'"
        )}


def _next_target_delivery(target_session_id: str) -> sqlite3.Row | None:
    placeholders = ",".join("?" * len(_TERMINAL_DELIVERY_STATES))
    with db._conn() as connection:
        return connection.execute(
            f"""SELECT * FROM message_deliveries
               WHERE target_session_id=? AND state NOT IN ({placeholders})
               ORDER BY accept_seq LIMIT 1""",
            (target_session_id, *_TERMINAL_DELIVERY_STATES),
        ).fetchone()


async def run_message_delivery(delivery_id: str, manager=None) -> None:
    row = _row(_validate_id(delivery_id))
    if row is None:
        raise KeyError(f"message delivery not found: {delivery_id}")
    from app import fan_barrier

    intercepted = fan_barrier.intercept_delivery_report(
        row["source_name"],
        row["target_name"],
        row["target_scope"],
        row["message"],
        row["message_kind"],
        row["source_scope"],
        delivery_id,
    )
    prepared = prepare_message_delivery(delivery_id)
    if prepared["delivery_state"] != "PREPARING":
        return
    row = _row(delivery_id)
    if manager is None:
        from app.deps import manager as manager
    context = MessageDeliveryContext(
        delivery_id,
        history_user_message=prepared["history_user_message"],
        provenance=prepared["provenance"],
    )
    if intercepted and not intercepted["released"]:
        _mark_message_delivery_fan_buffered(delivery_id, intercepted["fan_id"])
        return
    try:
        await manager.send_message_delivery(
            row["target_session_id"], row["rendered_message"],
            delivery=context, target_generation=row["target_generation"],
            provenance=context.provenance,
        )
        if intercepted and intercepted["released"]:
            logger.info(
                "fan parent wake submitted: fan=%s target=%s delivery_id=%s",
                intercepted["fan_id"], row["target_name"], delivery_id,
            )
    except asyncio.CancelledError as error:
        if context.dispatched:
            mark_message_delivery_unknown(delivery_id, error)
        else:
            mark_message_delivery_failed_before_submit(delivery_id, error)
            if intercepted and intercepted["released"]:
                fan_barrier.rearm_wake(intercepted["fan_id"])
        raise
    except Exception as error:
        if context.dispatched:
            mark_message_delivery_unknown(delivery_id, error)
        else:
            mark_message_delivery_failed_before_submit(delivery_id, error)
            if intercepted and intercepted["released"]:
                fan_barrier.rearm_wake(intercepted["fan_id"])
        raise


async def run_target_message_deliveries(target_session_id: str, manager=None) -> bool:
    lock = _target_delivery_locks.setdefault(target_session_id, asyncio.Lock())
    async with lock:
        while True:
            head = _next_target_delivery(target_session_id)
            if head is None:
                return True
            if head["state"] not in {"QUEUED", "PREPARING"}:
                return False
            try:
                await run_message_delivery(head["delivery_id"], manager=manager)
            except Exception:
                current = _row(head["delivery_id"])
                if current is None or current["state"] not in _TERMINAL_DELIVERY_STATES:
                    raise
                continue
            current = _row(head["delivery_id"])
            # Терминальный ОТКАЗ этого сообщения не должен останавливать очередь: следующие
            # к нему отношения не имеют. Останавливаемся только если сообщение осталось
            # незавершённым — тогда повтор бессмысленен и его подхватит следующий заход.
            if current is not None and current["state"] not in _TERMINAL_DELIVERY_STATES:
                return False


def ensure_target_runner(target_session_id: str) -> None:
    current = _target_runner_tasks.get(target_session_id)
    if current is not None and not current.done():
        return
    head = _next_target_delivery(target_session_id)
    if head is None or head["state"] not in {"QUEUED", "PREPARING"}:
        return
    task = asyncio.create_task(run_target_message_deliveries(target_session_id))
    _target_runner_tasks[target_session_id] = task
    task.add_done_callback(_observe_target_runner)


def _observe_target_runner(task: asyncio.Task[bool]) -> None:
    target = None
    for target, current in list(_target_runner_tasks.items()):
        if current is task:
            _target_runner_tasks.pop(target, None)
            break
    else:
        target = None

    drained = False
    if not task.cancelled():
        try:
            drained = task.result()
        except Exception:
            logger.exception("message delivery runner failed")
    if target is None or not drained:
        return
    head = _next_target_delivery(target)
    if head is not None and head["state"] in {"QUEUED", "PREPARING"}:
        ensure_target_runner(target)


def _recover_message_deliveries(target_session_id: str | None) -> tuple[set[str], int]:
    if target_session_id == "":
        raise ValueError("target session id must not be empty")
    with db._conn() as connection:
        connection.execute("BEGIN IMMEDIATE")
        orphan_error = RuntimeError("orphaned provider dispatch")
        orphan_error_json = json.dumps(
            {
                "code": "DELIVERY_OUTCOME_UNKNOWN",
                "message": (
                    "Dispatch runtime was stopped while provider acceptance was uncertain; delivery may "
                    "already have been accepted."
                ),
                "retryable": False,
                "outcome_unknown": True,
                "details": {
                    "phase": "PROVIDER_CALL_STARTED",
                    "exception_type": type(orphan_error).__name__,
                },
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        scope_sql = " AND target_session_id=?" if target_session_id is not None else ""
        scope_args = (target_session_id,) if target_session_id is not None else ()
        settled = connection.execute(
            """UPDATE message_deliveries
               SET state='DELIVERY_UNKNOWN_ORPHANED', error_json=?, updated_at=?
               WHERE state IN ('DISPATCHING','DELIVERY_UNKNOWN')""" + scope_sql,
            (orphan_error_json, _now(), *scope_args),
        ).rowcount
        rows = connection.execute(
            """SELECT target_session_id FROM message_deliveries
               WHERE state IN ('QUEUED','PREPARING')""" + scope_sql + " ORDER BY accept_seq",
            scope_args,
        ).fetchall()
        targets = {row["target_session_id"] for row in rows}
    return targets, settled


async def recover_message_deliveries(*, target_session_id: str | None = None) -> int:
    """After runtime teardown, release ambiguous barriers without retrying their payloads.

    Targeted callers must exclude dispatch and new sends until teardown and this
    transaction finish. The unscoped caller is startup, before dispatch starts.
    """
    targets, settled = await asyncio.to_thread(_recover_message_deliveries, target_session_id)
    for target in targets:
        ensure_target_runner(target)
    return settled
