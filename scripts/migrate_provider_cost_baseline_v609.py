#!/usr/bin/env python3
"""Offline migration V-609: persist the provider cumulative-cost baseline.

Run with Orchestra stopped.  Without ``--apply`` this only inspects the selected
database.  The migration adds one nullable-independent REAL column with a zero
default; existing session and turn history is not rewritten.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path


_COLUMN = "provider_cost_baseline_usd"
_SCHEMA_VERSION = 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not args.db.is_file():
        print(f"no such database: {args.db}", file=sys.stderr)
        return 2

    connection = sqlite3.connect(str(args.db))
    try:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(sessions)").fetchall()
        }
        if "id" not in columns:
            print("database has no sessions table", file=sys.stderr)
            return 2
        if _COLUMN in columns:
            print(f"already migrated: schema_version={version}")
            return 0
        if version not in (1,):
            print(
                f"unsupported schema version {version}; expected 1 before V-609",
                file=sys.stderr,
            )
            return 2
        if not args.apply:
            print(f"database={args.db}")
            print(f"schema_version={version}")
            print(f"missing_column={_COLUMN}")
            print("dry run: pass --apply while Orchestra is stopped")
            return 0

        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            f"ALTER TABLE sessions ADD COLUMN {_COLUMN} REAL DEFAULT 0.0"
        )
        connection.execute(f"PRAGMA user_version={_SCHEMA_VERSION}")
        connection.commit()
        print(f"migrated {args.db}: schema_version={_SCHEMA_VERSION}")
        return 0
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
