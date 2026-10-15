"""Persistent per-task worker checklists and the one-week reminder experiment."""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import date, datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import sqlite3
from statistics import median
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
CREATE TABLE IF NOT EXISTS checklist_step_metrics (
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    task_id TEXT NOT NULL DEFAULT '',
    step_id TEXT NOT NULL,
    step_text TEXT NOT NULL,
    estimate_minutes REAL,
    actual_seconds REAL,
    active_since REAL,
    model TEXT NOT NULL DEFAULT '',
    project TEXT NOT NULL DEFAULT '',
    completed_at TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    PRIMARY KEY(session_id, task_id, step_id)
);
CREATE INDEX IF NOT EXISTS idx_checklist_step_metrics_completed
    ON checklist_step_metrics(completed_at) WHERE completed_at!='';
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


def validate_items(
    items: list[str], completed: list[int], current: int | None,
    estimates_minutes: list[float | None] | None = None,
    previous_items: list[dict] | None = None,
) -> list[dict]:
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
    if estimates_minutes is not None and (
        not isinstance(estimates_minutes, list) or len(estimates_minutes) != len(normalized)
    ):
        raise ValueError("estimates_minutes must be a list with one value per item")
    estimates = estimates_minutes if estimates_minutes is not None else [None] * len(normalized)
    normalized_estimates = []
    for index, estimate in enumerate(estimates):
        if estimate is None:
            normalized_estimates.append(None)
            continue
        if isinstance(estimate, bool) or not isinstance(estimate, (int, float)):
            raise ValueError(f"estimates_minutes[{index}] must be a positive number of minutes")
        try:
            numeric_estimate = float(estimate)
        except (OverflowError, ValueError):
            numeric_estimate = math.inf
        if not math.isfinite(numeric_estimate) or numeric_estimate <= 0:
            raise ValueError(f"estimates_minutes[{index}] must be a positive number of minutes")
        normalized_estimates.append(numeric_estimate)
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
    previous: dict[str, deque[tuple[str, float | None]]] = defaultdict(deque)
    for item in previous_items or []:
        text = item.get("text") if isinstance(item, dict) else None
        step_id = item.get("step_id") if isinstance(item, dict) else None
        if isinstance(text, str) and isinstance(step_id, str) and step_id:
            previous[text].append((step_id, item.get("estimate_minutes")))
    steps = []
    missing = []
    for i, text in enumerate(normalized):
        step_id, kept = previous[text].popleft() if previous[text] else (uuid.uuid4().hex, None)
        estimate = normalized_estimates[i]
        if estimate is None and isinstance(kept, (int, float)) and kept > 0:
            estimate = float(kept)
        if estimate is None:
            missing.append(f"items[{i}] {text!r}")
        steps.append({
            "step_id": step_id, "text": text, "done": i in done,
            "current": i == current, "estimate_minutes": estimate,
        })
    if missing:
        raise ValueError(
            "every step needs a positive estimate in minutes; missing for new or changed steps: "
            + "; ".join(missing)
            + ". Resend update_checklist with estimates_minutes holding one positive number per item "
            "(null is accepted only for steps whose text is unchanged since your last update)"
        )
    return steps


def save_checklist(
    session_id: str, task_id: str, turn_key: str, *,
    items: list[str], completed: list[int], current: int | None,
    estimates_minutes: list[float | None] | None = None,
    model: str = "", project: str = "", now: datetime | None = None,
) -> dict:
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    now_text = moment.astimezone(timezone.utc).isoformat()
    now_epoch = moment.timestamp()
    task_id = task_id or ""
    with db._conn() as connection:
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute(
            "SELECT items_json FROM session_checklists WHERE session_id=? AND task_id=?",
            (session_id, task_id),
        ).fetchone()
        previous_items = []
        if existing is not None:
            try:
                parsed = json.loads(existing["items_json"])
                previous_items = parsed if isinstance(parsed, list) else []
            except (TypeError, json.JSONDecodeError):
                previous_items = []
        steps = validate_items(
            items, completed, current, estimates_minutes, previous_items,
        )
        other_active_rows = connection.execute(
            """SELECT task_id,step_id,active_since FROM checklist_step_metrics
               WHERE session_id=? AND task_id<>? AND active_since IS NOT NULL""",
            (session_id, task_id),
        ).fetchall()
        for row in other_active_rows:
            elapsed = max(0.0, now_epoch - float(row["active_since"]))
            connection.execute(
                """UPDATE checklist_step_metrics
                   SET actual_seconds=COALESCE(actual_seconds,0)+?,active_since=NULL
                   WHERE session_id=? AND task_id=? AND step_id=?""",
                (elapsed, session_id, row["task_id"], row["step_id"]),
            )
        previous_by_id = {
            item["step_id"]: item for item in previous_items
            if isinstance(item, dict) and isinstance(item.get("step_id"), str)
        }
        session_row = connection.execute(
            "SELECT model,scope FROM sessions WHERE id=?", (session_id,),
        ).fetchone()
        if session_row is not None:
            model = model or str(session_row["model"] or "")
            if not project and session_row["scope"]:
                project_row = connection.execute(
                    "SELECT id FROM tm_projects WHERE RTRIM(scope,'/')=RTRIM(?,'/') ORDER BY id LIMIT 1",
                    (session_row["scope"],),
                ).fetchone()
                project = str(project_row["id"]) if project_row else ""

        for step in steps:
            previous = previous_by_id.get(step["step_id"], {})
            metric = connection.execute(
                """SELECT estimate_minutes,completed_at FROM checklist_step_metrics
                   WHERE session_id=? AND task_id=? AND step_id=?""",
                (session_id, task_id, step["step_id"]),
            ).fetchone()
            initial_estimate = (
                metric["estimate_minutes"] if metric is not None and metric["estimate_minutes"] is not None
                else step["estimate_minutes"]
            )
            step["estimate_minutes"] = initial_estimate
            just_completed = step["done"] and previous.get("done") is not True
            completed_at = now_text if step["done"] and (
                just_completed or metric is None or not metric["completed_at"]
            ) else ""
            connection.execute(
                """INSERT OR IGNORE INTO checklist_step_metrics
                   (session_id,task_id,step_id,step_text,estimate_minutes,model,project,completed_at,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (session_id, task_id, step["step_id"], step["text"], step["estimate_minutes"],
                 model, project, completed_at, now_text),
            )
            if step["estimate_minutes"] is not None:
                connection.execute(
                    """UPDATE checklist_step_metrics SET estimate_minutes=COALESCE(estimate_minutes,?)
                       WHERE session_id=? AND task_id=? AND step_id=?""",
                    (step["estimate_minutes"], session_id, task_id, step["step_id"]),
                )
            if step["done"] and completed_at:
                connection.execute(
                    """UPDATE checklist_step_metrics SET completed_at=?
                       WHERE session_id=? AND task_id=? AND step_id=?""",
                    (completed_at, session_id, task_id, step["step_id"]),
                )
            connection.execute(
                """UPDATE checklist_step_metrics
                   SET model=CASE WHEN model='' THEN ? ELSE model END,
                       project=CASE WHEN project='' THEN ? ELSE project END
                   WHERE session_id=? AND task_id=? AND step_id=?""",
                (model, project, session_id, task_id, step["step_id"]),
            )

        active_step = next((step for step in steps if step["current"]), None)
        active_step_id = active_step["step_id"] if active_step else ""
        active_rows = connection.execute(
            """SELECT step_id,active_since FROM checklist_step_metrics
               WHERE session_id=? AND task_id=? AND active_since IS NOT NULL""",
            (session_id, task_id),
        ).fetchall()
        for row in active_rows:
            if row["step_id"] == active_step_id:
                continue
            elapsed = max(0.0, now_epoch - float(row["active_since"]))
            connection.execute(
                """UPDATE checklist_step_metrics
                   SET actual_seconds=COALESCE(actual_seconds,0)+?,active_since=NULL
                   WHERE session_id=? AND task_id=? AND step_id=?""",
                (elapsed, session_id, task_id, row["step_id"]),
            )
        if active_step_id:
            connection.execute(
                """UPDATE checklist_step_metrics SET active_since=?,actual_seconds=COALESCE(actual_seconds,0)
                   WHERE session_id=? AND task_id=? AND step_id=? AND active_since IS NULL""",
                (now_epoch, session_id, task_id, active_step_id),
            )

        raw = json.dumps(steps, ensure_ascii=False, separators=(",", ":"))
        connection.execute(
            """INSERT INTO session_checklists(session_id,task_id,items_json,updated_at)
               VALUES(?,?,?,?)
               ON CONFLICT(session_id,task_id) DO UPDATE SET
                 items_json=excluded.items_json, updated_at=excluded.updated_at""",
            (session_id, task_id, raw, now_text),
        )
        connection.execute(
            """UPDATE checklist_turns SET updated_after_reminder_at=?
               WHERE turn_key=? AND reminded_at!='' AND updated_after_reminder_at=''""",
            (now_text, turn_key),
        )
    return get_checklist(session_id, task_id) or {
        "items": steps, "completed": len(completed), "total": len(steps), "updated_at": now_text,
    }


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
        metrics = connection.execute(
            """SELECT step_id,estimate_minutes,actual_seconds,active_since
               FROM checklist_step_metrics WHERE session_id=? AND task_id=?""",
            (session_id, task_id or ""),
        ).fetchall()
    if row is None:
        return None
    try:
        items = json.loads(row["items_json"])
    except (TypeError, json.JSONDecodeError):
        items = []
    metrics_by_id = {metric["step_id"]: dict(metric) for metric in metrics}
    return _view(items, row["updated_at"], row["reminded_at"] or "", metrics_by_id)


def _view(
    items: list[dict], updated_at: str, reminded_at: str = "",
    metrics_by_id: dict[str, dict] | None = None,
) -> dict:
    if not isinstance(items, list):
        items = []
    metrics_by_id = metrics_by_id or {}
    valid = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("text"), str):
            continue
        metric = metrics_by_id.get(str(item.get("step_id") or ""), {})
        valid.append({
            **item,
            "estimate_minutes": (
                metric["estimate_minutes"] if metric.get("estimate_minutes") is not None
                else item.get("estimate_minutes")
            ),
            "actual_seconds": (
                float(metric["actual_seconds"]) if metric.get("actual_seconds") is not None else None
            ),
            "active_since": metric.get("active_since"),
        })
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


def reminder_delay_seconds(checklist: dict | None, *, now: float | None = None) -> float:
    delay = estimated_reminder_delay_seconds(checklist, now=now)
    return REMINDER_DELAY_SECONDS if delay is None else delay


def estimated_reminder_delay_seconds(
    checklist: dict | None, *, now: float | None = None,
) -> float | None:
    if not checklist:
        return None
    current = next((item for item in checklist.get("items", []) if item.get("current")), None)
    estimate = current.get("estimate_minutes") if current else None
    if estimate is None:
        return None
    elapsed = float(current.get("actual_seconds") or 0)
    active_since = current.get("active_since")
    if active_since is not None:
        current_time = now if now is not None else datetime.now(timezone.utc).timestamp()
        elapsed += max(0.0, current_time - float(active_since))
    return max(0.0, float(estimate) * 60.0 - elapsed)


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


def estimate_accuracy_report(*, since: str = "", until: str = "", project: str = "") -> dict:
    since = _period_bound(since)
    until = _period_bound(until, end_of_date=True)
    clauses = ["completed_at!=''"]
    params: list[str] = []
    if since:
        clauses.append("completed_at>=?")
        params.append(since)
    if until:
        clauses.append("completed_at<=?")
        params.append(until)
    if project:
        clauses.append("project=?")
        params.append(project)
    with db._conn() as connection:
        rows = connection.execute(
            f"""SELECT model,project,estimate_minutes,actual_seconds
                FROM checklist_step_metrics WHERE {' AND '.join(clauses)}
                ORDER BY model,project,completed_at,task_id,step_id""",
            params,
        ).fetchall()
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[str(row["model"] or "unknown")].append(dict(row))
    result = {}
    for model, steps in sorted(grouped.items()):
        measured = [step for step in steps if step["actual_seconds"] is not None]
        estimated = [step for step in measured if step["estimate_minutes"] is not None]
        ratios = [
            float(step["actual_seconds"]) / (float(step["estimate_minutes"]) * 60.0)
            for step in estimated if float(step["estimate_minutes"]) > 0
        ]
        p25 = _percentile(ratios, 0.25)
        p75 = _percentile(ratios, 0.75)
        result[model] = {
            "steps": len(steps),
            "measured_steps": len(measured),
            "estimated_steps": len(estimated),
            "unestimated_steps": len(measured) - len(estimated),
            "unmeasured_steps": len(steps) - len(measured),
            "zero_estimate_steps": sum(1 for step in estimated if float(step["estimate_minutes"]) == 0),
            "ratio_sample_steps": len(ratios),
            "median_actual_estimate_ratio": median(ratios) if ratios else None,
            "ratio_p25": p25,
            "ratio_p75": p75,
            "ratio_iqr": p75 - p25 if p25 is not None and p75 is not None else None,
            "projects": sorted({str(step["project"]) for step in steps if step["project"]}),
        }
    return {"since": since, "until": until, "project": project, "by_model": result}


def _period_bound(value: str, *, end_of_date: bool = False) -> str:
    if not value:
        return ""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    if end_of_date and len(value) == 10:
        parsed = parsed + timedelta(days=1) - timedelta(microseconds=1)
    return parsed.astimezone(timezone.utc).isoformat()


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * fraction
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)
