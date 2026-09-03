#!/usr/bin/env python3
"""Take a WAL-safe DB backup and emit a sanitized Codex budget snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def codex_window(raw: str) -> tuple[float | None, str | None]:
    try:
        windows = (json.loads(raw).get("codex") or {}).get("windows") or []
        window = windows[0] if windows and isinstance(windows[0], dict) else {}
        value = window.get("utilization")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None, None
        return float(value), window.get("resets_at")
    except (json.JSONDecodeError, AttributeError, TypeError):
        return None, None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--summary-out", type=Path, required=True)
    args = parser.parse_args()

    with sqlite3.connect(f"file:{args.source}?mode=ro", uri=True) as source:
        with sqlite3.connect(args.backup) as destination:
            source.backup(destination, pages=4096)

    with sqlite3.connect(f"file:{args.backup}?mode=ro", uri=True) as conn:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        row = conn.execute(
            """
            SELECT ts,provider_usage FROM usage_snapshots
            WHERE provider_usage LIKE '%codex%' ORDER BY ts DESC LIMIT 1
            """
        ).fetchone()
        utilization, resets_at = codex_window(row[1]) if row else (None, None)
        last_turn = conn.execute(
            "SELECT COALESCE(MAX(id),0),MAX(ts) FROM turn_usage"
        ).fetchone()
        summary = {
            "taken_at": datetime.now(timezone.utc).isoformat(),
            "integrity_check": integrity,
            "backup_sha256": hashlib.sha256(args.backup.read_bytes()).hexdigest(),
            "backup_bytes": args.backup.stat().st_size,
            "provider_sample_ts": row[0] if row else None,
            "codex_main_utilization": utilization,
            "codex_resets_at": resets_at,
            "last_turn_usage_id": int(last_turn[0]),
            "last_turn_usage_ts": last_turn[1],
        }
    args.summary_out.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "integrity_check": integrity,
        "codex_main_utilization": utilization,
        "provider_sample_ts": row[0] if row else None,
        "last_turn_usage_id": int(last_turn[0]),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
