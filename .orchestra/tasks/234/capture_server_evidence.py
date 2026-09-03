#!/usr/bin/env python3
"""Capture bounded read-only journal/SQLite evidence for #234 markers."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import time
from datetime import datetime
from pathlib import Path

from probe_quota_map import MAIN_ROOT, SSH_BASE


HERE = Path(__file__).resolve().parent
INPUTS = [HERE / "http-baseline.json", HERE / "browser-baseline.json", HERE / "browser-controls.json"]


def timestamps() -> tuple[float, float]:
    starts, finishes = [], []
    for path in INPUTS:
        data = json.loads(path.read_text())
        starts.append(datetime.fromisoformat(data["started_at"]).timestamp())
        finishes.append(datetime.fromisoformat(data["finished_at"]).timestamp())
    return min(starts) - 60, max(finishes) + 120


def markers(value) -> set[str]:
    out = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "marker" and isinstance(item, str) and item.startswith("q234-"):
                out.add(item)
            out.update(markers(item))
    elif isinstance(value, list):
        for item in value:
            out.update(markers(item))
    return out


def journal(command_prefix: list[str], start: float, finish: float) -> str:
    command = command_prefix + [
        "journalctl", "-u", "orchestra", "--since", f"@{start:.3f}",
        "--until", f"@{finish:.3f}", "-o", "short-iso-precise", "--no-pager",
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=20, check=True)
    keep = (
        "q234-", "quota-map trace:",
        "HTTP Request: GET https://api.anthropic.com/api/oauth/usage",
        "HTTP Request: GET https://cli-chat-proxy.grok.com/v1/billing",
        "Codex usage", "Grok usage", "usage snapshot:",
    )
    return "".join(line + "\n" for line in result.stdout.splitlines() if any(token in line for token in keep))


def db_stats(path: str) -> dict:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        total = connection.execute("SELECT COUNT(*) FROM usage_snapshots").fetchone()[0]
        now = time.time()
        start = now - 7 * 86400
        start_iso = datetime.fromtimestamp(start).astimezone().isoformat()
        end_iso = datetime.fromtimestamp(now).astimezone().isoformat()
        sql = """SELECT ts, five_hour_pct, seven_day_pct, five_hour_resets_at,
                        seven_day_resets_at, provider_usage
                 FROM usage_snapshots
                 WHERE ((ts >= ? AND ts <= ?)
                    OR ((ts NOT LIKE '%-%' AND ts NOT LIKE '%T%')
                        AND (CAST(ts AS REAL) BETWEEN ? AND ?)))
                 ORDER BY ts ASC"""
        plan = [tuple(row) for row in connection.execute(
            "EXPLAIN QUERY PLAN " + sql, (start_iso, end_iso, start, now)
        ).fetchall()]
        samples = []
        count = None
        for _ in range(3):
            t0 = time.perf_counter()
            rows = connection.execute(sql, (start_iso, end_iso, start, now)).fetchall()
            samples.append(round((time.perf_counter() - t0) * 1000, 3))
            count = len(rows)
        return {
            "path": path, "journal_mode": connection.execute("PRAGMA journal_mode").fetchone()[0],
            "total_rows": total, "seven_day_rows": count, "query_ms": samples,
            "query_plan": plan,
        }
    finally:
        connection.close()


def remote_db_stats() -> dict:
    # Keep the remote operation minimal and read-only instead of importing the local project.
    remote = r'''
import json, sqlite3, time
from datetime import datetime
path = "/home/kesha/orchestra/data/orchestra.db"
c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
now=time.time(); start=now-7*86400
start_iso=datetime.fromtimestamp(start).astimezone().isoformat(); end_iso=datetime.fromtimestamp(now).astimezone().isoformat()
sql="""SELECT ts, five_hour_pct, seven_day_pct, five_hour_resets_at, seven_day_resets_at, provider_usage
FROM usage_snapshots WHERE ((ts >= ? AND ts <= ?) OR ((ts NOT LIKE '%-%' AND ts NOT LIKE '%T%') AND (CAST(ts AS REAL) BETWEEN ? AND ?))) ORDER BY ts ASC"""
args=(start_iso,end_iso,start,now)
plan=[tuple(x) for x in c.execute("EXPLAIN QUERY PLAN "+sql,args).fetchall()]
times=[]; count=None
for _ in range(3):
 t=time.perf_counter(); rows=c.execute(sql,args).fetchall(); times.append(round((time.perf_counter()-t)*1000,3)); count=len(rows)
print(json.dumps({"path":path,"journal_mode":c.execute("PRAGMA journal_mode").fetchone()[0],"total_rows":c.execute("SELECT COUNT(*) FROM usage_snapshots").fetchone()[0],"seven_day_rows":count,"query_ms":times,"query_plan":plan}))
c.close()
'''
    result = subprocess.run(
        SSH_BASE + ["python3", "-"], input=remote, capture_output=True,
        text=True, timeout=20, check=True,
    )
    return json.loads(result.stdout.splitlines()[-1])


def main() -> None:
    start, finish = timestamps()
    local_text = journal([], start, finish)
    remote_text = journal(SSH_BASE, start, finish)
    (HERE / "journal-local.txt").write_text(local_text)
    (HERE / "journal-remote.txt").write_text(remote_text)

    all_markers = set()
    for path in INPUTS:
        all_markers.update(markers(json.loads(path.read_text())))
    correlation = []
    for marker in sorted(all_markers):
        source = local_text if "-local-" in marker else remote_text
        matches = [line for line in source.splitlines() if marker in line]
        correlation.append({"marker": marker, "server_completion_lines": len(matches), "lines": matches})
    output = {
        "schema": 1, "window_epoch": [start, finish], "correlation": correlation,
        "db": {
            "local": db_stats(str(MAIN_ROOT / "data" / "orchestra.db")),
            "remote": remote_db_stats(),
        },
    }
    (HERE / "server-correlation.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({
        "markers": len(correlation),
        "markers_with_server_completion": sum(item["server_completion_lines"] > 0 for item in correlation),
        "local_journal_lines": len(local_text.splitlines()),
        "remote_journal_lines": len(remote_text.splitlines()),
        "db": output["db"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
