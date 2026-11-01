"""Report hub workers with a known idle-state anchor older than a day."""
import datetime as dt
import os
import sqlite3
import sys
from collections import defaultdict
from contextlib import closing
from pathlib import Path

IDLE_MINUTES = 24 * 60
ORCHESTRATOR_ROLES = {"orchestrator", "sub-orchestrator"}


def _aware_datetime(value):
    parsed = dt.datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("log timestamp has no timezone")
    return parsed


def inferred_idle_since(logs):
    """Infer only from logged transitions; an unknown event invalidates the anchor."""
    state = "unknown"
    idle_since = None
    for event in logs:
        event_type = event["type"]
        content = event["content"]
        if event_type == "status":
            if content.startswith("turn ended"):
                state = "idle"
                idle_since = _aware_datetime(event["ts"])
            elif content.startswith("waiting for bg jobs"):
                state = "waiting"
                idle_since = None
            elif "stopped (server shutdown)" in content:
                state = "interrupted"
                idle_since = None
            elif "stopped (manual interrupt)" in content:
                if state != "idle":
                    idle_since = _aware_datetime(event["ts"])
                state = "idle"
            elif content.startswith(("context unknown", "auto-report skipped")):
                continue
            else:
                state = "unknown"
                idle_since = None
        else:
            state = "active" if event_type in {"user_message", "text", "tool", "tool_result"} else "unknown"
            idle_since = None
    return idle_since if state == "idle" else None


def idle_hub_workers(sessions, session_logs, now, idle_minutes=IDLE_MINUTES):
    by_id = {row["id"]: row for row in sessions}
    owners = defaultdict(list)
    threshold = dt.timedelta(minutes=idle_minutes)

    for worker in sessions:
        if worker["status"] != "idle" or not worker["model"].startswith("hub-"):
            continue
        events = session_logs.get(worker["id"], ())
        idle_since = inferred_idle_since(events)
        if idle_since is None:
            continue
        if now - idle_since <= threshold:
            continue

        parent_id = worker.get("parent_id")
        seen = set()
        while parent_id and parent_id not in seen:
            seen.add(parent_id)
            parent = by_id.get(parent_id)
            if parent is None:
                break
            if parent.get("is_orchestrator") or parent.get("role") in ORCHESTRATOR_ROLES:
                owners[parent["name"]].append((worker["name"], idle_since))
                break
            parent_id = parent.get("parent_id")

    return owners


def render_hub_idle(owners, now):
    lines = []
    for owner, workers in sorted(owners.items()):
        details = []
        for name, ended in sorted(workers):
            minutes = (now - ended).total_seconds() / 60
            details.append(f"{name} ({minutes:.2f} min)")
        lines.append(f"HUB_IDLE {owner}: " + "; ".join(details))
    return "\n".join(lines)


def main():
    try:
        idle_minutes = int(sys.argv[1]) if len(sys.argv) > 1 else IDLE_MINUTES
        configured = os.environ.get("ORCHESTRA_DB_PATH", "").strip()
        if not configured:
            raise RuntimeError("ORCHESTRA_DB_PATH is unset")
        path = Path(configured)
        if not path.is_absolute():
            path = Path(__file__).resolve().parents[1] / path
        with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)) as db:
            db.execute("PRAGMA query_only=ON")
            db.execute("BEGIN")
            db.row_factory = sqlite3.Row
            db.execute("select session_id, ts, type, content from logs limit 0")
            if db.execute("select 1 from logs limit 1").fetchone() is None:
                raise RuntimeError("logs table is empty")
            sessions = [dict(row) for row in db.execute(
                "select id, name, status, model, parent_id, role, is_orchestrator from sessions"
            )]
            if not sessions:
                raise RuntimeError("sessions table is empty")
            session_logs = {}
            for row in sessions:
                if row["status"] == "idle" and row["model"].startswith("hub-"):
                    events = db.execute(
                        "select ts, type, substr(content, 1, 120) as content "
                        "from logs where session_id=? order by id",
                        (row["id"],),
                    ).fetchall()
                    session_logs[row["id"]] = [dict(event) for event in events]
            now = dt.datetime.now(dt.timezone.utc)
            owners = idle_hub_workers(sessions, session_logs, now, idle_minutes)
            if owners:
                print(render_hub_idle(owners, now))
        return 0
    except Exception as exc:
        print(f"HUB_IDLE_ERROR: {type(exc).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
