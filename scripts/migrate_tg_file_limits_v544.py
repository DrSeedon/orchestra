#!/usr/bin/env python3
"""Offline migration #V-544: widen the two CHECKs that cap durable TG file delivery.

Изменяются только ограничения, данные не трогаются:
  * tg_file_deliveries.size_bytes    <= 52 428 800  ->  <= 2 097 152 000
  * tg_file_delivery_targets.state   + 'FAILED'

Запускать при ОСТАНОВЛЕННОЙ Orchestra (SQLite перестраивает обе таблицы):
    python scripts/migrate_tg_file_limits_v544.py --db <path>/orchestra.db
Без --apply печатает текущее состояние и ничего не пишет.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

_NEW_DELIVERIES = """
CREATE TABLE tg_file_deliveries_v544 (
                accept_seq INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                schema_version INTEGER NOT NULL,
                source_session_id TEXT,
                source_name TEXT NOT NULL,
                source_scope TEXT NOT NULL,
                source_path TEXT NOT NULL,
                original_name TEXT NOT NULL,
                snapshot_path TEXT NOT NULL,
                size_bytes INTEGER NOT NULL CHECK(size_bytes > 0 AND size_bytes <= 2097152000),
                content_sha256 TEXT NOT NULL CHECK(length(content_sha256) = 64),
                caption TEXT NOT NULL,
                outbound_caption TEXT NOT NULL,
                as_document INTEGER NOT NULL CHECK(as_document IN (0,1)),
                payload_hash TEXT NOT NULL CHECK(length(payload_hash) = 64),
                orch_name TEXT,
                batch_id TEXT,
                batch_index INTEGER,
                batch_group INTEGER,
                batch_kind TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                snapshot_deleted_at TEXT,
                quarantined_at TEXT
            )
"""

_NEW_TARGETS = """
CREATE TABLE tg_file_delivery_targets_v544 (
                event_id TEXT NOT NULL REFERENCES tg_file_deliveries(event_id) ON DELETE CASCADE,
                target_kind TEXT NOT NULL CHECK(target_kind IN ('primary','mirror')),
                chat_id INTEGER NOT NULL,
                thread_id INTEGER,
                state TEXT NOT NULL CHECK(state IN
                    ('QUEUED','SUBMITTING','SENT','FAILED_BEFORE_SUBMIT','FAILED','UNKNOWN')),
                message_id INTEGER,
                attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count >= 0),
                lease_generation INTEGER NOT NULL DEFAULT 0 CHECK(lease_generation >= 0),
                error_json TEXT,
                submitted_at TEXT,
                sent_at TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(event_id, target_kind)
            )
"""

_TARGETS_INDEX = (
    "CREATE INDEX idx_tg_file_targets_chat_state "
    "ON tg_file_delivery_targets(chat_id, state, event_id)"
)


def _sql(connection: sqlite3.Connection, table: str) -> str:
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row[0] if row else ""


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
        migrated = (
            "2097152000" in _sql(connection, "tg_file_deliveries")
            and "'FAILED'," in _sql(connection, "tg_file_delivery_targets")
        )
        counts = {
            table: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in ("tg_file_deliveries", "tg_file_delivery_targets")
        }
        print(f"database={args.db}")
        print(f"rows={counts}")
        print(f"already_migrated={migrated}")
        if migrated or not args.apply:
            if not args.apply:
                print("dry run: pass --apply to rebuild both tables")
            return 0

        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(_NEW_DELIVERIES)
        connection.execute(
            "INSERT INTO tg_file_deliveries_v544 SELECT * FROM tg_file_deliveries"
        )
        connection.execute(_NEW_TARGETS)
        connection.execute(
            "INSERT INTO tg_file_delivery_targets_v544 "
            "SELECT * FROM tg_file_delivery_targets"
        )
        connection.execute("DROP TABLE tg_file_delivery_targets")
        connection.execute("DROP TABLE tg_file_deliveries")
        # Ссылки в схеме мы уже написали руками: переименование не должно
        # переписывать чужой SQL и не должно перечитывать схему целиком.
        connection.execute("PRAGMA legacy_alter_table=ON")
        connection.execute(
            "ALTER TABLE tg_file_deliveries_v544 RENAME TO tg_file_deliveries"
        )
        connection.execute(
            "ALTER TABLE tg_file_delivery_targets_v544 "
            "RENAME TO tg_file_delivery_targets"
        )
        connection.execute("PRAGMA legacy_alter_table=OFF")
        connection.execute(_TARGETS_INDEX)
        new_counts = {
            table: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in ("tg_file_deliveries", "tg_file_delivery_targets")
        }
        if new_counts != counts:
            connection.rollback()
            print(f"row count changed {counts} -> {new_counts}, rolled back", file=sys.stderr)
            return 1
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            connection.rollback()
            print(f"foreign key violations: {violations[:5]}", file=sys.stderr)
            return 1
        connection.commit()
        print(f"migrated rows={new_counts}")
        return 0
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
