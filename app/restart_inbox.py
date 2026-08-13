"""Messages that arrived while Orchestra was restarting, delivered once it is back (#269).

The admission gate refuses MUTATING HTTP calls, but a Telegram message never travels over
HTTP: the bridge lives in this process and pushes straight into a CLI session. During a
restart that session is about to die, so the message was accepted, never answered and never
seen again — the user got silence.

Delivery is AT-LEAST-ONCE, deliberately, and for the same reason as `mailbox`: a row is
marked delivered only AFTER `manager.send` returned. A crash in between replays the message
(the user sees a duplicate and understands it); marking first would lose it exactly when the
process is least stable, and a lost message is indistinguishable from an agent ignoring you.
"""

import logging
import time

from app import db

logger = logging.getLogger(__name__)


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
    with db._conn() as connection:
        rows = connection.execute(
            """
            SELECT id, session_id, body, chat_id, thread_id
            FROM restart_inbox
            WHERE delivered_at IS NULL
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


async def deliver_pending(manager) -> int:
    """Hand every queued message to its session. Returns how many were delivered.

    One row at a time, and each is marked only after its own delivery: a session that no
    longer exists must not swallow the messages queued for the others.
    """
    rows = pending()
    delivered = 0
    for row in rows:
        try:
            await manager.send(row["session_id"], row["body"])
        except Exception as error:
            logger.warning(
                "restart inbox: %s still undelivered: %s: %s",
                row["session_id"], type(error).__name__, error,
            )
            continue
        mark_delivered(row["id"])
        delivered += 1
    if rows:
        logger.info("restart inbox: delivered %d of %d queued message(s)", delivered, len(rows))
    return delivered
