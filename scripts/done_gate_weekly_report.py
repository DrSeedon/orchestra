#!/usr/bin/env python3
"""V-614: count `done_gate_verdict` shadow flags for the last N days and cross-check
against `merge_operations` rows that a real merge gate turned back with
TEST_GATE_FAILED/TEST_GATE_INCONCLUSIVE.

Read-only: opens the given DB path directly with sqlite3 (a `backup()` copy is safer
than pointing this at the live file while Orchestra is writing to it, but both work
since SQLite WAL allows concurrent readers).

Usage:
    python scripts/done_gate_weekly_report.py --db data/orchestra.db --days 7
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from datetime import datetime, timedelta, timezone


def _rows(conn: sqlite3.Connection, since: str) -> list[dict]:
    cur = conn.execute(
        "SELECT session_id, ts, content FROM logs "
        "WHERE type='done_gate_verdict' AND ts >= ? ORDER BY id",
        (since,),
    )
    out = []
    for row in cur.fetchall():
        try:
            payload = json.loads(row["content"])
        except (TypeError, ValueError):
            continue
        payload["ts"] = row["ts"]
        out.append(payload)
    return out


def _test_gate_failures(conn: sqlite3.Connection, since: str) -> list[dict]:
    cur = conn.execute(
        "SELECT operation_id, scope, worker_name, session_id, state, result_json, "
        "created_at FROM merge_operations WHERE created_at >= ? "
        "AND (result_json LIKE '%TEST_GATE_FAILED%' OR result_json LIKE '%TEST_GATE_INCONCLUSIVE%')",
        (since,),
    )
    return [dict(row) for row in cur.fetchall()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="path to orchestra.db (or a backup() copy)")
    parser.add_argument("--days", type=int, default=7)
    args = parser.parse_args(argv)

    since_dt = datetime.now(timezone.utc) - timedelta(days=args.days)
    since = since_dt.isoformat()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        verdicts = _rows(conn, since)
        failures = _test_gate_failures(conn, since)
    finally:
        conn.close()

    total = len(verdicts)
    flagged = [v for v in verdicts if v.get("flag")]
    by_scope = Counter(v.get("scope", "") for v in flagged)
    by_worker = Counter((v.get("scope", ""), v.get("worker_name", "")) for v in flagged)

    flagged_sessions = {v["session_id"] for v in flagged}
    failure_sessions = {f["session_id"] for f in failures}
    overlap_sessions = flagged_sessions & failure_sessions

    print(json.dumps({
        "since": since,
        "done_verdicts_total": total,
        "done_verdicts_flagged": len(flagged),
        "flagged_by_scope": dict(by_scope.most_common()),
        "flagged_by_scope_worker": {f"{s}::{w}": n for (s, w), n in by_worker.most_common(20)},
        "merge_test_gate_failures_total": len(failures),
        "sessions_with_both_flag_and_test_gate_failure": sorted(overlap_sessions),
        "sessions_with_flag_no_test_gate_failure": sorted(flagged_sessions - failure_sessions),
        "sessions_with_test_gate_failure_no_flag": sorted(failure_sessions - flagged_sessions),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
