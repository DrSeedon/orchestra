"""Persistent per-task worker checklists and the one-week reminder experiment."""

from __future__ import annotations

from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import uuid

from app import db


REMINDER_DELAY_SECONDS = 300.0
REMINDER_CUTOFF = date(2026, 10, 22)
REMINDER_FLAG = "ORCHESTRA_CHECKLIST_REMINDERS"
BOOT_ID = uuid.uuid4().hex

_DDL = """
CREATE TABLE IF NOT EXISTS session_checklists (
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    task_id TEXT NOT NULL DEFAULT '',
    items_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(session_id, task_id)
);
CREATE TABLE IF NOT EXISTS checklist_turns (
    turn_key TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    task_id TEXT NOT NULL DEFAULT '',
    turn_gen INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    reminded_at TEXT NOT NULL DEFAULT '',
    updated_after_reminder_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_checklist_turns_reminders
    ON checklist_turns(reminded_at) WHERE reminded_at!='';
"""

_SCHEMA_READY: set[str] = set()


def ensure_schema(connection: sqlite3.Connection | None = None) -> bool:
    if connection is None:
        path = str(Path(db.DB_PATH).resolve())
        if path in _SCHEMA_READY:
            return True
        with db._conn() as owned:
            if not owned.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='sessions'"
            ).fetchone():
                return False
            owned.executescript(_DDL)
        _SCHEMA_READY.add(path)
        return True
    if not connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='sessions'"
    ).fetchone():
        return False
    connection.executescript(_DDL)
    return True


def reminders_enabled(now: datetime | None = None) -> bool:
    flag = os.environ.get(REMINDER_FLAG, "1").strip().casefold()
    if flag in {"0", "false", "no", "off"}:
        return False
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).date() <= REMINDER_CUTOFF


def make_turn_key(session_id: str, turn_gen: int) -> str:
    return f"{session_id}:{BOOT_ID}:{turn_gen}"


def register_turn(session_id: str, task_id: str, turn_gen: int, turn_key: str) -> bool:
    if not ensure_schema():
        return False
    now = datetime.now(timezone.utc).isoformat()
    with db._conn() as connection:
        connection.execute(
            """INSERT OR IGNORE INTO checklist_turns
               (turn_key,session_id,task_id,turn_gen,started_at)
               VALUES(?,?,?,?,?)""",
            (turn_key, session_id, task_id or "", turn_gen, now),
        )
        return connection.execute(
            "SELECT 1 FROM checklist_turns WHERE turn_key=?", (turn_key,),
        ).fetchone() is not None


def claim_reminder(turn_key: str) -> bool:
    now = datetime.now(timezone.utc).isoformat()
    with db._conn() as connection:
        cursor = connection.execute(
            """UPDATE checklist_turns SET reminded_at=?
               WHERE turn_key=? AND reminded_at=''""",
            (now, turn_key),
        )
        return cursor.rowcount == 1


def validate_items(items: list[str], completed: list[int], current: int | None) -> list[dict]:
    if not isinstance(items, list) or not items:
        raise ValueError("items must contain at least one step")
    normalized = []
    for index, raw in enumerate(items):
        if not isinstance(raw, str):
            raise ValueError(f"items[{index}] must be text")
        text = raw.strip()
        if not text:
            raise ValueError(f"items[{index}] must not be empty")
        normalized.append(text)
    if not isinstance(completed, list) or any(
        isinstance(index, bool) or not isinstance(index, int) for index in completed
    ):
        raise ValueError("completed must be a list of zero-based item indexes")
    if len(set(completed)) != len(completed) or any(i < 0 or i >= len(normalized) for i in completed):
        raise ValueError("completed contains a duplicate or out-of-range item index")
    if current is not None and (
        isinstance(current, bool) or not isinstance(current, int) or current < 0 or current >= len(normalized)
    ):
        raise ValueError("current must be a valid zero-based item index or null")
    done = set(completed)
    if current in done:
        raise ValueError("current step cannot also be completed")
    if current is None:
        current = next((i for i in range(len(normalized)) if i not in done), None)
    return [
        {"text": text, "done": i in done, "current": i == current}
        for i, text in enumerate(normalized)
    ]


def save_checklist(
    session_id: str, task_id: str, turn_key: str, *,
    items: list[str], completed: list[int], current: int | None,
) -> dict:
    steps = validate_items(items, completed, current)
    now = datetime.now(timezone.utc).isoformat()
    raw = json.dumps(steps, ensure_ascii=False, separators=(",", ":"))
    with db._conn() as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """INSERT INTO session_checklists(session_id,task_id,items_json,updated_at)
               VALUES(?,?,?,?)
               ON CONFLICT(session_id,task_id) DO UPDATE SET
                 items_json=excluded.items_json, updated_at=excluded.updated_at""",
            (session_id, task_id or "", raw, now),
        )
        connection.execute(
            """UPDATE checklist_turns SET updated_after_reminder_at=?
               WHERE turn_key=? AND reminded_at!='' AND updated_after_reminder_at=''""",
            (now, turn_key),
        )
    return {"items": steps, "completed": len(completed), "total": len(steps), "updated_at": now}


def get_checklist(session_id: str, task_id: str = "") -> dict | None:
    with db._conn() as connection:
        row = connection.execute(
            """SELECT c.items_json,c.updated_at,
                      (SELECT reminded_at FROM checklist_turns t
                       WHERE t.session_id=c.session_id AND t.task_id=c.task_id
                       ORDER BY t.started_at DESC LIMIT 1) AS reminded_at
               FROM session_checklists c WHERE c.session_id=? AND c.task_id=?""",
            (session_id, task_id or ""),
        ).fetchone()
    if row is None:
        return None
    try:
        items = json.loads(row["items_json"])
    except (TypeError, json.JSONDecodeError):
        items = []
    return _view(items, row["updated_at"], row["reminded_at"] or "")


def _view(items: list[dict], updated_at: str, reminded_at: str = "") -> dict:
    if not isinstance(items, list):
        items = []
    valid = [item for item in items if isinstance(item, dict) and isinstance(item.get("text"), str)]
    completed = sum(1 for item in valid if item.get("done") is True)
    current = next((item.get("text", "") for item in valid if item.get("current") is True), "")
    return {
        "items": valid,
        "completed": completed,
        "total": len(valid),
        "current": current,
        "updated_at": updated_at,
        "reminded_at": reminded_at,
    }


def summaries_for_sessions(sessions: list[dict]) -> dict[str, dict]:
    pairs = {
        (str(row.get("id") or ""), str(row.get("task_id") or ""))
        for row in sessions if row.get("id")
    }
    if not pairs:
        return {}
    ids = list({session_id for session_id, _task in pairs})
    marks = ",".join("?" for _ in ids)
    with db._conn() as connection:
        rows = connection.execute(
            f"SELECT session_id,task_id,items_json,updated_at FROM session_checklists WHERE session_id IN ({marks})",
            ids,
        ).fetchall()
    result = {}
    for row in rows:
        key = (row["session_id"], row["task_id"])
        if key not in pairs:
            continue
        try:
            view = _view(json.loads(row["items_json"]), row["updated_at"])
        except (TypeError, json.JSONDecodeError):
            continue
        result[row["session_id"]] = {
            "completed": view["completed"], "total": view["total"],
            "current": view["current"], "updated_at": view["updated_at"],
        }
    return result


def reminder_effect_counts(*, since: str = "") -> dict[str, int]:
    """Measure reminder count and reminders followed by a checklist change in that turn."""
    with db._conn() as connection:
        row = connection.execute(
            """SELECT COUNT(*) AS reminders,
                      SUM(CASE WHEN updated_after_reminder_at!='' THEN 1 ELSE 0 END) AS followed
               FROM checklist_turns WHERE reminded_at!='' AND (?='' OR reminded_at>=?)""",
            (since, since),
        ).fetchone()
    return {"reminders": int(row["reminders"] or 0), "followed_by_update": int(row["followed"] or 0)}
