"""Durable completion barriers for a group of child workers."""

import asyncio
import logging
import sqlite3
import time
from pathlib import Path

from . import db
from app.events import MessageProvenance
from app.turn_markers import is_silent_turn_text


_TERMINAL_STATES = {"done", "failed", "timeout", "killed"}
_BYPASS_KINDS = {"out_of_scope", "false_premise", "blocked"}
_deadline_tasks: dict[str, asyncio.Task] = {}
logger = logging.getLogger("orchestra.fan_barrier")


def _report_body(body: str | None, state: str) -> str:
    if is_silent_turn_text(body):
        return (
            "ОТЧЁТА НЕТ: ход завершён служебным маркером тишины, "
            "а содержательный send_message родителю не сохранён."
        )
    if isinstance(body, str) and body.strip():
        return body
    return (
        f"ОТЧЁТА НЕТ: ребёнок завершился со статусом {state}, но не оставил "
        "содержательного send_message родителю или финального текста хода."
    )


def is_terminal_report(message_kind: str | None) -> bool:
    """Explicit completion kind only. Body text is not a signal (#276)."""
    return message_kind in _TERMINAL_STATES


def _persist_child_report(fan_id: str, child: str, body: str) -> str:
    """Write the child's report next to the DB. Manifest keeps only this path."""
    safe_fan = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in fan_id) or "fan"
    safe_child = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in child) or "child"
    directory = Path(db.DB_PATH).resolve().parent / "fan-reports" / safe_fan
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{safe_child}.md"
    tmp = path.with_name(f"{path.name}.{time.time_ns()}.tmp")
    try:
        tmp.write_text(body, encoding="utf-8")
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)
    return str(path)


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
    fan_id: str | None = None,
) -> bool:
    """`require_drained_scope` — #231: не считать ребёнка терминальным, пока у него
    есть невыданный вход в ящике.

    Проверка живёт ВНУТРИ той же транзакции, что и фиксация: между раздельными
    «посмотреть, что ящик пуст» и «записать терминал» успевает лечь `wake=False`,
    и веер отпустится по ребёнку, который своего сообщения ещё не видел.

    `summary` больше не выбрасывается: если `report_path` не задан, текст
    кладётся в файл, а в БД остаётся только путь. Иначе родитель видит
    `path=-` и отчёт потерян (#275).
    """
    if state not in _TERMINAL_STATES:
        return False
    with db._conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if require_drained_scope is not None:
            undelivered = conn.execute(
                """SELECT 1 FROM mailbox
                   WHERE recipient = ? AND scope = ? AND delivered_at IS NULL
                   LIMIT 1""",
                (child, require_drained_scope),
            ).fetchone()
            if undelivered is not None:
                return False
        fan_clause = " AND m.fan_id = ?" if fan_id else ""
        params = (child, fan_id) if fan_id else (child,)
        row = conn.execute(
            """SELECT m.fan_id, m.state, f.released, m.report_path
               FROM fan_members m
               JOIN fan_barriers f ON f.fan_id = m.fan_id
               WHERE m.child = ? AND f.released = 0"""
            + fan_clause
            + " LIMIT 1",
            params,
        ).fetchone()
        if row is None or row[1] is not None:
            return False
        fan_id = row[0]
        if not report_path:
            report_path = row[3] or _persist_child_report(
                fan_id, child, _report_body(summary, state),
            )
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
        _cancel_deadline(fan_id)
        return True


def intercept_delivery_report(
    child: str,
    target_name: str,
    target_scope: str,
    message: str,
    message_kind: str | None,
    require_drained_scope: str,
    delivery_id: str | None = None,
) -> dict | None:
    """Capture a durable ``send_message`` report before it wakes the fan parent.

    Live MCP clients predating #407 do not send ``message_kind``.  Inside an active
    fan, their message to that fan's parent is a report candidate; turn completion is
    the terminal signal and the last candidate wins.  New clients may name a terminal
    state; known non-terminal kinds keep their normal direct-delivery behaviour.
    """
    if message_kind is not None and not is_terminal_report(message_kind):
        return None
    state = message_kind or "done"
    with db._conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """SELECT m.fan_id, m.state, m.report_path, f.parent_name, f.scope,
                      f.reducer, f.complete
               FROM fan_members m
               JOIN fan_barriers f ON f.fan_id = m.fan_id
               WHERE m.child = ? AND f.released = 0
               ORDER BY f.created_at DESC LIMIT 1""",
            (child,),
        ).fetchone()
        if row is None:
            return None
        fan_id, member_state, report_path, parent_name, scope, reducer, complete = row
        recipients = {parent_name}
        if reducer:
            recipients.add(reducer)
        if target_scope.rstrip("/") != scope.rstrip("/") or target_name not in recipients:
            return None
        substantive = (
            isinstance(message, str)
            and bool(message.strip())
            and not is_silent_turn_text(message)
        )
        if message_kind is None:
            if (
                member_state is None
                and not complete
                and (substantive or not report_path)
            ):
                report_path = _persist_child_report(
                    fan_id,
                    child,
                    message if substantive else _report_body(message, state),
                )
                conn.execute(
                    """UPDATE fan_members SET report_path = ?
                       WHERE fan_id = ? AND child = ?""",
                    (report_path, fan_id, child),
                )
            return {
                "fan_id": fan_id,
                "released": False,
                "recipient": reducer or parent_name,
                "manifest": None,
            }
        if member_state is not None:
            pending = conn.execute(
                "SELECT 1 FROM fan_members WHERE fan_id = ? AND state IS NULL LIMIT 1",
                (fan_id,),
            ).fetchone()
            if complete and pending is None:
                conn.execute(
                    "UPDATE fan_barriers SET released = 1 WHERE fan_id = ? AND released = 0",
                    (fan_id,),
                )
                manifest = _manifest_text_connection(conn, fan_id)
                if delivery_id:
                    conn.execute(
                        """UPDATE message_deliveries
                           SET message=?, rendered_message=?
                           WHERE delivery_id=? AND state IN ('QUEUED', 'PREPARING')""",
                        (manifest, manifest, delivery_id),
                    )
                _cancel_deadline(fan_id)
                return {
                    "fan_id": fan_id,
                    "released": True,
                    "recipient": reducer or parent_name,
                    "manifest": manifest,
                }
            return {
                "fan_id": fan_id,
                "released": False,
                "recipient": reducer or parent_name,
                "manifest": None,
            }
        if not report_path:
            report_path = _persist_child_report(
                fan_id, child, _report_body(message, state),
            )
            conn.execute(
                """UPDATE fan_members SET report_path = ?
                   WHERE fan_id = ? AND child = ? AND state IS NULL""",
                (report_path, fan_id, child),
            )
        undelivered = conn.execute(
            """SELECT 1 FROM mailbox
               WHERE recipient = ? AND scope = ? AND delivered_at IS NULL
               LIMIT 1""",
            (child, require_drained_scope),
        ).fetchone()
        if undelivered is not None:
            return {
                "fan_id": fan_id,
                "released": False,
                "recipient": reducer or parent_name,
            }
        conn.execute(
            """UPDATE fan_members SET state = ?
               WHERE fan_id = ? AND child = ? AND state IS NULL""",
            (state, fan_id, child),
        )
        pending = conn.execute(
            "SELECT 1 FROM fan_members WHERE fan_id = ? AND state IS NULL LIMIT 1",
            (fan_id,),
        ).fetchone()
        released = pending is None
        manifest = None
        if released:
            conn.execute(
                """UPDATE fan_barriers
                   SET released = 1, complete = 1, partial_reason = NULL
                   WHERE fan_id = ? AND released = 0""",
                (fan_id,),
            )
            manifest = _manifest_text_connection(conn, fan_id)
            if delivery_id:
                conn.execute(
                    """UPDATE message_deliveries
                       SET message=?, rendered_message=?
                       WHERE delivery_id=? AND state='QUEUED'""",
                    (manifest, manifest, delivery_id),
                )
            _cancel_deadline(fan_id)
        return {
            "fan_id": fan_id,
            "released": released,
            "recipient": reducer or parent_name,
            "manifest": manifest,
        }


def _manifest_text_connection(conn: sqlite3.Connection, fan_id: str) -> str:
    fan = conn.execute(
        """SELECT complete, partial_reason FROM fan_barriers WHERE fan_id = ?""",
        (fan_id,),
    ).fetchone()
    if fan is None:
        raise KeyError(fan_id)
    members = conn.execute(
        """SELECT child, state, report_path FROM fan_members
           WHERE fan_id = ? ORDER BY rowid""",
        (fan_id,),
    ).fetchall()
    lines = [
        f"fan={fan_id} complete={str(bool(fan[0])).lower()}"
        + (f" partial_reason={fan[1]}" if fan[1] else "")
    ]
    lines.extend(
        f"{member[0]}={member[1] or 'pending'} path={member[2] or '-'}"
        for member in members
    )
    return "\n".join(lines)


def rearm_wake(fan_id: str) -> None:
    """Known pre-submit failure: keep the completed fan waiting for its one wake."""
    with db._conn() as conn:
        updated = conn.execute(
            """UPDATE fan_barriers SET released = 0
               WHERE fan_id = ? AND released = 1 AND complete = 1""",
            (fan_id,),
        )
    if updated.rowcount:
        schedule_deadline(fan_id)


def _cancel_deadline(fan_id: str) -> None:
    task = _deadline_tasks.pop(fan_id, None)
    if task is not None and task is not asyncio.current_task() and not task.done():
        task.cancel()


def _release_deadline(fan_id: str) -> bool:
    with db._conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT released, deadline_at, complete FROM fan_barriers WHERE fan_id = ?",
            (fan_id,),
        ).fetchone()
        if row is None or row[0] or row[1] > time.time():
            return False
        already_complete = bool(row[2])
        if not already_complete:
            conn.execute(
                """UPDATE fan_members SET state = 'timeout'
                   WHERE fan_id = ? AND state IS NULL""",
                (fan_id,),
            )
        updated = conn.execute(
            """UPDATE fan_barriers
               SET released = 1,
                   complete = CASE WHEN complete = 1 THEN 1 ELSE 0 END,
                   partial_reason = CASE WHEN complete = 1 THEN NULL ELSE 'deadline' END
               WHERE fan_id = ? AND released = 0""",
            (fan_id,),
        )
        return updated.rowcount == 1


async def _deadline_waiter(fan_id: str, delay: float) -> None:
    try:
        await asyncio.sleep(max(0.0, delay))
        if not _release_deadline(fan_id):
            return
        target = parent_of(fan_id)
        if target is None:
            return
        from app.deps import manager

        recipient = reducer_of(fan_id) or target[0]
        destination = await manager.ensure_loaded(recipient, target[1])
        if destination is not None:
            provenance = MessageProvenance(
                origin="platform", senders=("Orchestra",),
                subtype="fan_manifest", ref=fan_id,
            )
            await manager.send(
                destination.id, manifest_text(fan_id), provenance=provenance,
            )
    except asyncio.CancelledError:
        raise
    except Exception as error:
        logger.error("fan %s deadline wake failed: %s: %s", fan_id,
                     type(error).__name__, error)
    finally:
        if _deadline_tasks.get(fan_id) is asyncio.current_task():
            _deadline_tasks.pop(fan_id, None)


def schedule_deadline(fan_id: str) -> None:
    with db._conn() as conn:
        row = conn.execute(
            "SELECT deadline_at, released FROM fan_barriers WHERE fan_id = ?",
            (fan_id,),
        ).fetchone()
    if row is None or row[1]:
        return
    _cancel_deadline(fan_id)
    _deadline_tasks[fan_id] = asyncio.create_task(
        _deadline_waiter(fan_id, row[0] - time.time())
    )


def recover_deadlines() -> None:
    with db._conn() as conn:
        rows = conn.execute(
            "SELECT fan_id FROM fan_barriers WHERE released = 0"
        ).fetchall()
    for row in rows:
        schedule_deadline(row[0])


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
    with db._conn() as conn:
        rows = conn.execute(
            "SELECT fan_id FROM fan_barriers WHERE released = 0 AND deadline_at <= ?",
            (time.time(),),
        ).fetchall()
    released = [row[0] for row in rows if _release_deadline(row[0])]
    for fan_id in released:
        _cancel_deadline(fan_id)
    return released


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
