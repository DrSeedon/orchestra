"""Pair real task_create ReadTimeouts with tasks in a SQLite backup."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _sha(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def _arguments(content: str) -> dict:
    start = content.find("{")
    if start < 0:
        raise ValueError("task_create tool row has no JSON object")
    value = json.loads(content[start:])
    if not isinstance(value, dict):
        raise ValueError("task_create arguments are not an object")
    return value


def _project_id(connection: sqlite3.Connection, selector: str, session_id: str) -> str:
    value = selector.strip()
    if not value:
        row = connection.execute("SELECT scope FROM sessions WHERE id=?", (session_id,)).fetchone()
        value = str(row[0] if row else "").rstrip("/")
    exact_id = connection.execute("SELECT id FROM tm_projects WHERE id=?", (value,)).fetchone()
    exact_scope = connection.execute(
        "SELECT id FROM tm_projects WHERE scope=?", (value,)
    ).fetchone()
    if exact_id and exact_scope and exact_id[0] != exact_scope[0]:
        raise ValueError(f"project selector {value!r} has conflicting exact id and scope")
    if exact_id or exact_scope:
        return str((exact_id or exact_scope)[0])
    folded = connection.execute("SELECT id FROM tm_projects").fetchall()
    matches = [row for row in folded if str(row[0]).casefold() == value.casefold()]
    if len(matches) != 1:
        raise ValueError(f"project selector {value!r} resolved to {len(matches)} rows")
    return str(matches[0][0])


def analyze(database: Path, since: str) -> dict:
    with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        results = connection.execute(
            """SELECT id,session_id,ts,tool_use_id,content
               FROM logs
               WHERE type='tool_result'
                 AND tool_name='mcp__orchestra__task_create'
                 AND content='transport_timeout: ReadTimeout'
                 AND ts>=?
               ORDER BY ts""",
            (since,),
        ).fetchall()
        rows = []
        for result in results:
            call = connection.execute(
                """SELECT id,session_id,ts,tool_use_id,content
                   FROM logs
                   WHERE type='tool' AND tool_use_id=?
                     AND tool_name='mcp__orchestra__task_create'
                   ORDER BY ts LIMIT 1""",
                (result["tool_use_id"],),
            ).fetchone()
            if call is None:
                raise ValueError(f"missing task_create call for {result['tool_use_id']}")
            arguments = _arguments(str(call["content"]))
            title = str(arguments.get("title") or "")
            project_id = _project_id(
                connection,
                str(arguments.get("project") or ""),
                str(call["session_id"]),
            )
            candidates = connection.execute(
                """SELECT id,par_number,project_id,title,created_at
                   FROM tm_tasks WHERE project_id=? AND title=? ORDER BY created_at""",
                (project_id, title),
            ).fetchall()
            call_ts = _dt(str(call["ts"]))
            result_ts = _dt(str(result["ts"]))
            in_result_window = [
                dict(task)
                for task in candidates
                if -2 <= (_dt(str(task["created_at"])) - call_ts).total_seconds()
                <= (result_ts - call_ts).total_seconds() + 2
            ]
            rows.append({
                "tool_use_id": result["tool_use_id"],
                "call_ts": call["ts"],
                "timeout_ts": result["ts"],
                "seconds_to_timeout": (result_ts - call_ts).total_seconds(),
                "session_id": call["session_id"],
                "project_id": project_id,
                "title": title,
                "tasks_created_before_logged_result": in_result_window,
                "tasks_assigned_to_call": [],
                "all_exact_title_matches": len(candidates),
            })
        groups: dict[tuple[str, str], list[dict]] = {}
        for row in rows:
            groups.setdefault((row["project_id"], row["title"]), []).append(row)
        for (project_id, title), calls in groups.items():
            tasks = connection.execute(
                """SELECT id,par_number,project_id,title,created_at
                   FROM tm_tasks WHERE project_id=? AND title=? ORDER BY created_at""",
                (project_id, title),
            ).fetchall()
            for task in tasks:
                task_ts = _dt(str(task["created_at"]))
                eligible = [
                    row for row in calls
                    if -2 <= (task_ts - _dt(str(row["call_ts"]))).total_seconds() <= 300
                ]
                if not eligible:
                    continue
                owner = max(eligible, key=lambda row: _dt(str(row["call_ts"])))
                assigned = dict(task)
                assigned["seconds_after_call"] = (
                    task_ts - _dt(str(owner["call_ts"]))
                ).total_seconds()
                owner["tasks_assigned_to_call"].append(assigned)
    sanitized_rows = []
    for row in rows:
        sanitized_rows.append({
            "call_sha256": _sha(str(row["tool_use_id"])),
            "session_sha256": _sha(str(row["session_id"])),
            "project_title_sha256": _sha(row["project_id"] + "\0" + row["title"]),
            "call_ts": row["call_ts"],
            "timeout_ts": row["timeout_ts"],
            "seconds_to_timeout": row["seconds_to_timeout"],
            "all_exact_title_matches": row["all_exact_title_matches"],
            "tasks_created_before_logged_result": [
                {
                    "task_identity_sha256": _sha(
                        f"{task['id']}\0{task['project_id']}\0{task['par_number']}"
                    ),
                    "created_at": task["created_at"],
                }
                for task in row["tasks_created_before_logged_result"]
            ],
            "tasks_assigned_to_call": [
                {
                    "task_identity_sha256": _sha(
                        f"{task['id']}\0{task['project_id']}\0{task['par_number']}"
                    ),
                    "created_at": task["created_at"],
                    "seconds_after_call": task["seconds_after_call"],
                }
                for task in row["tasks_assigned_to_call"]
            ],
        })
    duplicate_project_titles = sorted({
        row["project_title_sha256"]
        for row in sanitized_rows
        if row["all_exact_title_matches"] > 1
    })
    return {
        "source": str(database),
        "since": since,
        "counting_rules": {
            "preregistered": (
                "logs.type='tool_result' AND tool_name='mcp__orchestra__task_create' AND "
                "content='transport_timeout: ReadTimeout'; pair by tool_use_id; outcome exists "
                "iff exactly one tm_tasks row has resolved project_id + exact title and created_at "
                "between call_ts-2s and timeout_ts+2s"
            ),
            "exploratory_followup": (
                "After the preregistered rule missed one known task, group by resolved project_id "
                "+ exact title; assign each matching tm_tasks row created from call_ts-2s through "
                "call_ts+300s to the latest preceding call"
            ),
        },
        "timeout_calls": len(rows),
        "preregistered_timeouts_with_exactly_one_created_task": sum(
            len(row["tasks_created_before_logged_result"]) == 1 for row in rows
        ),
        "preregistered_timeouts_with_zero_created_tasks": sum(
            not row["tasks_created_before_logged_result"] for row in rows
        ),
        "preregistered_timeouts_with_multiple_created_tasks": sum(
            len(row["tasks_created_before_logged_result"]) > 1 for row in rows
        ),
        "exploratory_timeouts_with_exactly_one_created_task": sum(
            len(row["tasks_assigned_to_call"]) == 1 for row in rows
        ),
        "exploratory_timeouts_with_zero_created_tasks": sum(
            not row["tasks_assigned_to_call"] for row in rows
        ),
        "exploratory_timeouts_with_multiple_created_tasks": sum(
            len(row["tasks_assigned_to_call"]) > 1 for row in rows
        ),
        "duplicate_project_title_sha256": duplicate_project_titles,
        "rows": sanitized_rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--since", default="2026-08-25T00:00:00+00:00")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = analyze(args.database.resolve(), args.since)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key != "rows"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
