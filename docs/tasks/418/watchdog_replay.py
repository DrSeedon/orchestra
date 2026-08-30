#!/usr/bin/env python3
"""Dirty-state sensitivity replay for #418; it is not a historical stall counter."""

from __future__ import annotations

import argparse
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--db",
        type=Path,
        default=Path("/mnt/data/Projects/Python/orchestra/data/orchestra.db"),
    )
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--end", help="UTC ISO timestamp; default is current time")
    args = parser.parse_args()

    end = _dt(args.end) if args.end else datetime.now(timezone.utc)
    start = end - timedelta(days=args.days)
    connection = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row

    projects = {
        row["id"]: dict(row)
        for row in connection.execute(
            "SELECT id,scope FROM tm_projects "
            "WHERE NULLIF(TRIM(scope),'') IS NOT NULL"
        )
    }
    owners: dict[str, list[str]] = defaultdict(list)
    for row in connection.execute(
        "SELECT name,scope FROM sessions "
        "WHERE role='orchestrator' AND status!='archived'"
    ):
        owners[row["scope"].rstrip("/")].append(row["name"])

    tasks: dict[str, list[datetime]] = defaultdict(list)
    for row in connection.execute(
        "SELECT project_id,created_at FROM tm_tasks WHERE status='in_progress'"
    ):
        if row["project_id"] in projects:
            tasks[row["project_id"]].append(_dt(row["created_at"]))

    scopes = {
        project["scope"].rstrip("/")
        for project_id, project in projects.items()
        if project_id in tasks and len(owners[project["scope"].rstrip("/")]) == 1
    }
    sessions = {
        row["id"]: row["scope"].rstrip("/")
        for row in connection.execute("SELECT id,scope FROM sessions")
        if row["scope"].rstrip("/") in scopes
    }

    events: dict[str, list[tuple[datetime, str]]] = defaultdict(list)
    placeholders = ",".join("?" for _ in sessions)
    query = (
        "SELECT session_id,ts,type FROM logs WHERE ts>=? AND ts<=? "
        f"AND session_id IN ({placeholders}) "
        "AND (type='user_message' OR "
        "(type='status' AND content LIKE 'turn ended (%')) "
        "ORDER BY session_id,ts"
    )
    for row in connection.execute(query, [start.isoformat(), end.isoformat(), *sessions]):
        events[row["session_id"]].append((_dt(row["ts"]), row["type"]))

    intervals: dict[str, list[tuple[datetime, datetime]]] = defaultdict(list)
    for session_id, ordered in events.items():
        opened_at: datetime | None = None
        for timestamp, event_type in ordered:
            # A steered user_message does not open a second concurrent turn.
            if event_type == "user_message":
                if opened_at is None:
                    opened_at = timestamp
            elif opened_at is not None:
                intervals[sessions[session_id]].append((opened_at, timestamp))
                opened_at = None
        if opened_at is not None:
            intervals[sessions[session_id]].append((opened_at, end))

    print(f"db={args.db}")
    print(f"window={start.isoformat()}..{end.isoformat()}")
    print("task_model=current in_progress back-projected only from created_at")
    print("turn_pairing=first user_message while closed -> next 'turn ended (' by ts")
    print("known_bias=missing historical task transitions and background-job intervals")

    for minutes in (30, 60, 360, 1440):
        threshold = timedelta(minutes=minutes)
        total_edges = 0
        total_repeated = 0
        project_rows: list[tuple[str, int, int]] = []
        for project_id, project in sorted(projects.items()):
            if project_id not in tasks:
                continue
            scope = project["scope"].rstrip("/")
            if len(owners[scope]) != 1:
                continue

            tick = start
            runs: list[tuple[datetime, datetime]] = []
            run_start: datetime | None = None
            while tick <= end:
                task_open = any(created <= tick for created in tasks[project_id])
                active = any(left <= tick <= right for left, right in intervals[scope])
                eligible = task_open and not active
                if eligible and run_start is None:
                    run_start = tick
                elif not eligible and run_start is not None:
                    runs.append((run_start, tick))
                    run_start = None
                tick += timedelta(minutes=5)
            if run_start is not None:
                runs.append((run_start, end))

            qualifying = [(left, right) for left, right in runs if right - left >= threshold]
            edges = len(qualifying)
            repeated = sum(
                max(0, int((right - left - threshold) / timedelta(minutes=5)) + 1)
                for left, right in qualifying
            )
            if edges:
                project_rows.append((project_id, edges, repeated))
            total_edges += edges
            total_repeated += repeated

        print(
            f"threshold={minutes}m edge_triggers={total_edges} "
            f"repeated_5m_triggers={total_repeated} projects={len(project_rows)}"
        )
        print("  " + ", ".join(f"{pid}:{edge}/{repeat}" for pid, edge, repeat in project_rows))

    print(f"reconstructed_intervals={sum(map(len, intervals.values()))}")


if __name__ == "__main__":
    main()
