"""Durable completion barriers for a group of child workers."""

import time

from . import db


_TERMINAL_STATES = {"done", "failed", "timeout", "killed"}
_BYPASS_KINDS = {"out_of_scope", "false_premise", "blocked"}


def open_fan(
    fan_id: str,
    parent_name: str,
    scope: str,
    children: list[str],
    deadline_seconds: float,
) -> None:
    now = time.time()
    members = list(dict.fromkeys(children))
    with db._conn() as conn:
        conn.execute(
            """INSERT INTO fan_barriers
               (fan_id, parent_name, scope, created_at, deadline_at)
               VALUES (?, ?, ?, ?, ?)""",
            (fan_id, parent_name, scope, now, now + deadline_seconds),
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
    with db._conn() as conn:
        row = conn.execute(
            """SELECT 1 FROM fan_members m
               JOIN fan_barriers f ON f.fan_id = m.fan_id
               WHERE m.child = ? AND f.released = 0
               LIMIT 1""",
            (child,),
        ).fetchone()
    return row is not None


def record_terminal(
    child: str,
    state: str,
    report_path: str | None = None,
    summary: str | None = None,
) -> bool:
    del summary
    if state not in _TERMINAL_STATES:
        return False
    with db._conn() as conn:
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
    return record_terminal(child, "killed")


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
