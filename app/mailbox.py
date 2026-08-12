"""Durable, non-waking message mailbox."""

import time

from app import db


def enqueue(recipient: str, scope: str, sender: str, body: str) -> int:
    """Store a message and return its durable identifier."""
    with db._conn() as connection:
        cursor = connection.execute(
            """
            INSERT INTO mailbox (recipient, scope, sender, body, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (recipient, scope, sender, body, time.time()),
        )
        return int(cursor.lastrowid)


def pending(recipient: str, scope: str) -> list[dict]:
    """Return undelivered messages without changing their delivery state."""
    with db._conn() as connection:
        rows = connection.execute(
            """
            SELECT id, sender, body
            FROM mailbox
            WHERE recipient = ? AND scope = ? AND delivered_at IS NULL
            ORDER BY id
            """,
            (recipient, scope),
        ).fetchall()
    return [dict(row) for row in rows]


def mark_delivered(ids: list[int]) -> None:
    """Mark exactly the supplied message identifiers as delivered."""
    if not ids:
        return
    placeholders = ", ".join("?" for _ in ids)
    with db._conn() as connection:
        connection.execute(
            f"UPDATE mailbox SET delivered_at = ? WHERE id IN ({placeholders})",
            (time.time(), *ids),
        )


# Семантика доставки объявлена явно: AT-LEAST-ONCE.
# Выбор между «потерять» и «повторить» сделан в пользу повтора: агент, прочитавший
# сообщение дважды, теряет центы, а молча потерянное сообщение стоит работы (#158).
# Аренда ниже гасит не повтор после краха, а ОДНОВРЕМЕННЫЕ выдачи.
CLAIM_LEASE_SECONDS = 300.0


def claim(recipient: str, scope: str, lease_seconds: float = CLAIM_LEASE_SECONDS) -> list[dict]:
    """Забрать невыданные строки в АРЕНДУ одной транзакцией.

    `pending()` остаётся чистым чтением (на нём стоит замороженный оракул), а забирает
    строки только эта функция. Два одновременных конца хода не отправят одно и то же:
    второй получит пустой список. Протухшая аренда (владелец умер) переоткрывается
    по истечении `lease_seconds`.
    """
    now = time.time()
    stale = now - lease_seconds
    with db._conn() as conn:
        rows = conn.execute(
            """SELECT id, sender, body FROM mailbox
               WHERE recipient = ? AND scope = ? AND delivered_at IS NULL
                 AND (claimed_at IS NULL OR claimed_at < ?)
               ORDER BY id""",
            (recipient, scope, stale),
        ).fetchall()
        if not rows:
            return []
        ids = [r[0] for r in rows]
        placeholders = ",".join("?" * len(ids))
        conn.execute(
            f"""UPDATE mailbox SET claimed_at = ?
                WHERE id IN ({placeholders}) AND delivered_at IS NULL""",
            (now, *ids),
        )
        return [{"id": r[0], "sender": r[1], "body": r[2]} for r in rows]


def release_claim(ids: list[int]) -> None:
    """Вернуть строки в ящик после неудачной выдачи — иначе они ждали бы протухания
    аренды впустую."""
    if not ids:
        return
    placeholders = ",".join("?" * len(ids))
    with db._conn() as conn:
        conn.execute(
            f"UPDATE mailbox SET claimed_at = NULL WHERE id IN ({placeholders})",
            tuple(ids),
        )
