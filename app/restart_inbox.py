"""Messages that arrived while Orchestra was restarting, delivered once it is back (#269).

The admission gate refuses MUTATING HTTP calls, but a Telegram message never travels over
HTTP: the bridge lives in this process and pushes straight into a CLI session. During a
restart that session is about to die, so the message was accepted, never answered and never
seen again — the user got silence.

The restart inbox hands each message to the normal durable message queue under a
stable ID. A failed acknowledgement of that handoff retries the same ID, not the
provider send. Provider submission and unknown outcomes belong to message_deliveries.

The queue is drained on every REOPENING of the gate, not on process start: a restart that
never happens (preflight refused, watchdog, failed restart path) leaves the process alive and
the promise "I will deliver it when I am back" unkept (#269 B1).
"""

import asyncio
import logging
import time
import uuid

from app import db
from app.events import MessageProvenance

logger = logging.getLogger(__name__)

#: A session that never came back (archived, killed, `session_id` cleared) would otherwise
#: keep the row forever: retried at every reopening, never delivered, user never told.
MAX_ATTEMPTS = 3
#: `session.send` can wait for `_ensure_backend()`. Per-row exceptions already cannot eat the
#: queue; a HANG could, and a regression that hangs instead of failing is the worse kind.
DELIVERY_TIMEOUT_S = 120.0


def enqueue(session_id: str, body: str, chat_id: int = 0, thread_id: int = 0) -> int:
    with db._conn() as connection:
        cursor = connection.execute(
            """
            INSERT INTO restart_inbox (session_id, body, chat_id, thread_id, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (session_id, body, int(chat_id), int(thread_id), time.time()),
        )
        return int(cursor.lastrowid)


def pending() -> list[dict]:
    """Rows still owed to their session: neither delivered nor given up on."""
    with db._conn() as connection:
        rows = connection.execute(
            """
            SELECT id, session_id, body, chat_id, thread_id, attempts
            FROM restart_inbox
            WHERE delivered_at IS NULL AND failed_at IS NULL
            ORDER BY id
            """
        ).fetchall()
    return [dict(row) for row in rows]


def mark_delivered(row_id: int) -> None:
    with db._conn() as connection:
        connection.execute(
            "UPDATE restart_inbox SET delivered_at = ? WHERE id = ?",
            (time.time(), int(row_id)),
        )


def mark_attempt(row_id: int) -> int:
    """Count one failed delivery and return how many there have been."""
    with db._conn() as connection:
        connection.execute(
            "UPDATE restart_inbox SET attempts = attempts + 1 WHERE id = ?", (int(row_id),)
        )
        row = connection.execute(
            "SELECT attempts FROM restart_inbox WHERE id = ?", (int(row_id),)
        ).fetchone()
    return int(row["attempts"]) if row else 0


def mark_given_up(row_id: int) -> None:
    with db._conn() as connection:
        connection.execute(
            "UPDATE restart_inbox SET failed_at = ? WHERE id = ?",
            (time.time(), int(row_id)),
        )


async def _tell_user_undeliverable(row: dict, detail: str) -> None:
    """Say it out loud instead of letting the row rot: we promised to deliver it."""
    if not row.get("chat_id"):
        logger.warning("restart inbox: giving up on %s with no chat to answer: %s",
                       row["session_id"], detail)
        return
    try:
        from app.tg_bridge import report_inbox_undeliverable

        await report_inbox_undeliverable(
            int(row["chat_id"]), int(row["thread_id"] or 0), row["body"], detail,
        )
    except Exception as error:
        logger.warning("restart inbox: could not tell the user about %s: %s: %s",
                       row["session_id"], type(error).__name__, error)


async def _transfer_to_message_queue(row: dict) -> None:
    from app.message_deliveries import accept_message_delivery, ensure_target_runner

    delivery_id = str(uuid.uuid5(uuid.NAMESPACE_URL,
                                f"orchestra:restart-inbox:{row['session_id']}:{row['id']}"))
    with db._conn() as connection:
        existing = connection.execute(
            "SELECT target_session_id,message FROM message_deliveries WHERE delivery_id=?",
            (delivery_id,),
        ).fetchone()
    if existing:
        if existing['target_session_id'] != row['session_id'] or existing['message'] != row['body']:
            raise ValueError('restart inbox delivery ID is bound to different content')
        ensure_target_runner(row['session_id'])
        return
    target = db.get_session(row['session_id'])
    if not target or target.get('status') == 'archived':
        raise ValueError('restart inbox target no longer exists')
    generation = (
        f"session={target['id']}|task={target.get('task_id') or ''}|"
        f"branch={target.get('branch') or ''}|needs_switch={int(bool(target.get('needs_switch')))}"
    )
    resource, status = await accept_message_delivery(
        delivery_id=delivery_id, source_principal='restart-inbox', source_name='user',
        source_scope=target['scope'], target_session_id=target['id'],
        target_name=target['name'], target_scope=target['scope'],
        target_task_id=target.get('task_id') or '', target_generation=generation,
        message=row['body'], rendered_message=row['body'], message_kind='user',
        provenance=MessageProvenance(origin='user', senders=('user',),
                                    subtype='tg_restart_inbox', ref=str(row['id'])),
    )
    if status != 202:
        raise RuntimeError(f"restart message was not accepted: {resource}")


async def deliver_pending(manager) -> int:
    """Transfer messages to the durable queue. Returns how many handoffs were accepted.

    One row at a time, and each is marked only after its own delivery: a session that no
    longer exists must not swallow the messages queued for the others.
    """
    try:
        rows = pending()
    except Exception:
        # The whole drain failing silently is the one outcome nobody would ever notice.
        logger.exception("restart inbox: could not read the queue")
        return 0

    delivered = 0
    for row in rows:
        try:
            await asyncio.wait_for(
                _transfer_to_message_queue(row),
                timeout=DELIVERY_TIMEOUT_S,
            )
        except Exception as error:
            detail = f"{type(error).__name__}: {error}"
            logger.warning("restart inbox: %s still undelivered: %s", row["session_id"], detail)
            try:
                if mark_attempt(row["id"]) >= MAX_ATTEMPTS:
                    mark_given_up(row["id"])
                    await _tell_user_undeliverable(row, detail)
            except Exception:
                logger.exception("restart inbox: could not record the failed attempt")
            continue
        try:
            mark_delivered(row["id"])
        except Exception:
            # The durable queue already owns this ID. The next drain can safely repeat
            # the handoff even if this acknowledgement was not saved.
            logger.exception("restart inbox: delivered %s but could not mark it", row["id"])
        delivered += 1
    if rows:
        logger.info("restart inbox: transferred %d of %d message(s) to durable delivery", delivered, len(rows))
    return delivered
