"""Durable completion barriers for a group of child workers."""

import sqlite3
import time

from . import db


_TERMINAL_STATES = {"done", "failed", "timeout", "killed"}
_BYPASS_KINDS = {"out_of_scope", "false_premise", "blocked"}


def _schema_is_missing(error: sqlite3.OperationalError) -> bool:
    prefix = "no such table:"
    message = str(error).lower()
    if not message.startswith(prefix):
        return False
    table = message.removeprefix(prefix).strip().rsplit(".", 1)[-1]
    return table in {"fan_barriers", "fan_members"}


def open_fan(
    fan_id: str,
    parent_name: str,
    scope: str,
    children: list[str],
    deadline_seconds: float,
    reducer: str = "",
) -> None:
    now = time.time()
    members = list(dict.fromkeys(children))
    with db._conn() as conn:
        conn.execute(
            """INSERT INTO fan_barriers
               (fan_id, parent_name, scope, created_at, deadline_at, reducer)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (fan_id, parent_name, scope, now, now + deadline_seconds, reducer or ""),
        )
        conn.executemany(
            "INSERT INTO fan_members (fan_id, child) VALUES (?, ?)",
            [(fan_id, child) for child in members],
        )
        if not members:
            conn.execute(
                "UPDATE fan_barriers SET released = 1, complete = 1 WHERE fan_id = ?",
                (fan_id,),
            )


def should_buffer(child: str, message_kind: str | None = None) -> bool:
    if message_kind in _BYPASS_KINDS:
        return False
    try:
        with db._conn() as conn:
            row = conn.execute(
                """SELECT 1 FROM fan_members m
                   JOIN fan_barriers f ON f.fan_id = m.fan_id
                   WHERE m.child = ? AND f.released = 0
                   LIMIT 1""",
                (child,),
            ).fetchone()
    except sqlite3.OperationalError as error:
        if _schema_is_missing(error):
            return False
        raise
    return row is not None


def record_terminal(
    child: str,
    state: str,
    report_path: str | None = None,
    summary: str | None = None,
    require_drained_scope: str | None = None,
) -> bool:
    """`require_drained_scope` — #231: не считать ребёнка терминальным, пока у него
    есть невыданный вход в ящике.

    Проверка живёт ВНУТРИ той же транзакции, что и фиксация: между раздельными
    «посмотреть, что ящик пуст» и «записать терминал» успевает лечь `wake=False`,
    и веер отпустится по ребёнку, который своего сообщения ещё не видел.
    """
    del summary
    if state not in _TERMINAL_STATES:
        return False
    with db._conn() as conn:
        if require_drained_scope is not None:
            undelivered = conn.execute(
                """SELECT 1 FROM mailbox
                   WHERE recipient = ? AND scope = ? AND delivered_at IS NULL
                   LIMIT 1""",
                (child, require_drained_scope),
            ).fetchone()
            if undelivered is not None:
                return False
        row = conn.execute(
            """SELECT m.fan_id, m.state, f.released
               FROM fan_members m
               JOIN fan_barriers f ON f.fan_id = m.fan_id
               WHERE m.child = ? AND f.released = 0
               LIMIT 1""",
            (child,),
        ).fetchone()
        if row is None or row[1] is not None:
            return False
        fan_id = row[0]
        conn.execute(
            """UPDATE fan_members SET state = ?, report_path = ?
               WHERE fan_id = ? AND child = ? AND state IS NULL""",
            (state, report_path, fan_id, child),
        )
        pending = conn.execute(
            "SELECT 1 FROM fan_members WHERE fan_id = ? AND state IS NULL LIMIT 1",
            (fan_id,),
        ).fetchone()
        if pending is not None:
            return False
        conn.execute(
            """UPDATE fan_barriers
               SET released = 1, complete = 1, partial_reason = NULL
               WHERE fan_id = ? AND released = 0""",
            (fan_id,),
        )
        return True


def on_child_killed(child: str) -> bool:
    try:
        return record_terminal(child, "killed")
    except sqlite3.OperationalError as error:
        if _schema_is_missing(error):
            return False
        raise


def is_released(fan_id: str) -> bool:
    with db._conn() as conn:
        row = conn.execute(
            "SELECT released FROM fan_barriers WHERE fan_id = ?", (fan_id,)
        ).fetchone()
    return bool(row and row[0])


def release_expired() -> list[str]:
    now = time.time()
    with db._conn() as conn:
        rows = conn.execute(
            "SELECT fan_id FROM fan_barriers WHERE released = 0 AND deadline_at <= ?",
            (now,),
        ).fetchall()
        fan_ids = [row[0] for row in rows]
        for fan_id in fan_ids:
            conn.execute(
                """UPDATE fan_members SET state = 'timeout'
                   WHERE fan_id = ? AND state IS NULL""",
                (fan_id,),
            )
            conn.execute(
                """UPDATE fan_barriers
                   SET released = 1, complete = 0, partial_reason = 'deadline'
                   WHERE fan_id = ? AND released = 0""",
                (fan_id,),
            )
        return fan_ids


def manifest(fan_id: str) -> dict:
    with db._conn() as conn:
        fan = conn.execute(
            """SELECT fan_id, parent_name, scope, complete, partial_reason
               FROM fan_barriers WHERE fan_id = ?""",
            (fan_id,),
        ).fetchone()
        if fan is None:
            raise KeyError(fan_id)
        members = conn.execute(
            """SELECT child, state, report_path FROM fan_members
               WHERE fan_id = ? ORDER BY rowid""",
            (fan_id,),
        ).fetchall()
    return {
        "fan_id": fan[0],
        "parent_name": fan[1],
        "scope": fan[2],
        "complete": bool(fan[3]) if fan[3] is not None else False,
        "partial_reason": fan[4],
        "members": [
            {"child": row[0], "state": row[1], "report_path": row[2]}
            for row in members
        ],
    }


def manifest_text(fan_id: str) -> str:
    data = manifest(fan_id)
    lines = [
        f"fan={data['fan_id']} complete={str(data['complete']).lower()}"
        + (f" partial_reason={data['partial_reason']}" if data["partial_reason"] else "")
    ]
    for member in data["members"]:
        path = member["report_path"] or "-"
        state = member["state"] or "pending"
        lines.append(f"{member['child']}={state} path={path}")
    return "\n".join(lines)


def fan_id_for_child(child: str, *, include_released: bool = False) -> str | None:
    """Веер ребёнка. `include_released` нужен гейтам: манифест забирается уже
    ПОСЛЕ снятия барьера, когда `released = 1`."""
    where = "" if include_released else " AND f.released = 0"
    with db._conn() as conn:
        row = conn.execute(
            f"""SELECT m.fan_id FROM fan_members m
                JOIN fan_barriers f ON f.fan_id = m.fan_id
                WHERE m.child = ?{where}
                ORDER BY f.created_at DESC LIMIT 1""",
            (child,),
        ).fetchone()
    return row[0] if row else None


def parent_of(fan_id: str) -> tuple[str, str] | None:
    """(parent_name, scope) — кого будить манифестом."""
    with db._conn() as conn:
        row = conn.execute(
            "SELECT parent_name, scope FROM fan_barriers WHERE fan_id = ?",
            (fan_id,),
        ).fetchone()
    return (row[0], row[1]) if row else None


def reducer_of(fan_id: str) -> str:
    """#231 T6: кому адресован релиз. Пусто → родителю, как было до редьюсера."""
    with db._conn() as conn:
        row = conn.execute(
            "SELECT reducer FROM fan_barriers WHERE fan_id = ?", (fan_id,)
        ).fetchone()
    return (row[0] if row else "") or ""


def peek_summary(name: str, scope: str) -> str | None:
    """Веер, сводку которого этот агент ещё не отдавал. ЧИСТОЕ чтение.

    Первая редакция гасила признак прямо здесь, и ревью реализации справедливо
    назвало это потерей: любой сбой между «пометили» и «доставили» уничтожал манифест
    навсегда. Это ровно грабля #158, и я закрыл её в ящике, но не здесь.
    Гасит теперь `mark_summarised`, и только после успешной доставки.
    """
    try:
        with db._conn() as conn:
            row = conn.execute(
                """SELECT fan_id FROM fan_barriers
                   WHERE reducer = ? AND scope = ? AND released = 1 AND summarised = 0
                   ORDER BY created_at DESC LIMIT 1""",
                (name, scope),
            ).fetchone()
    except sqlite3.OperationalError as error:
        if _schema_is_missing(error):
            return None
        raise
    return row[0] if row else None


def mark_summarised(fan_id: str) -> None:
    with db._conn() as conn:
        conn.execute(
            "UPDATE fan_barriers SET summarised = 1 WHERE fan_id = ?", (fan_id,)
        )


def fan_id_for_reducer(name: str, scope: str) -> str | None:
    """Веер, чью сводку собирает этот агент. Нужен, чтобы приклеить манифест к его
    собственному сообщению родителю: полнота обязана держаться на коде, а не на том,
    что редьюсер ничего не забыл (#231, blocking 8 ревью плана)."""
    with db._conn() as conn:
        row = conn.execute(
            """SELECT fan_id FROM fan_barriers
               WHERE reducer = ? AND scope = ? ORDER BY created_at DESC LIMIT 1""",
            (name, scope),
        ).fetchone()
    return row[0] if row else None
