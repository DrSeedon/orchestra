#!/usr/bin/env python3
"""Backfill structured message provenance in one explicitly selected database."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.events import MESSAGE_ORIGINS, MessageProvenance
from app.initial_deliveries import _payload_hash as _initial_payload_hash
from app.message_deliveries import _payload_hash as _message_payload_hash


_MIGRATION_ID = "message-provenance-433-v1"
_B1_RECEIPT_SCHEMA = 2
_FROZEN_MAX_LOG_ID = 562_928
_RULE_MANIFEST: dict[str, Any] = {
    "migration_id": _MIGRATION_ID,
    "max_log_id": _FROZEN_MAX_LOG_ID,
    "receipt_precedence": [
        "message_deliveries.user_log_id",
        "initial_deliveries.user_log_id",
    ],
    "receipt_rules": {
        "message_deliveries": {
            "operator:*": "user",
            "mcp:*": "agent",
            "other": "unknown",
        },
        "initial_deliveries": {
            "same_scope_live_sender": "agent",
            "other": "unknown",
        },
        "schema_version>=2": "immutable",
    },
    "prefix_rules": {
        "[HH:MM]": "user",
        "[from TG:": "user",
        "[from:": "agent",
        "[Background job completed]": "background_task",
        "[Orchestra platform note:": "platform",
    },
    "explicit_rules": {
        "[system]": "system",
        "[system wake:": "system",
        "[PREVIOUS CONTEXT SUMMARY": "platform",
        "НЕДОСТАВКА:": "platform",
        "BUG REPORT платформы:": "platform",
        "fan=": "platform",
        "[Cron job fired]": "background_task",
        "[Cron command matched]": "background_task",
        "LIVE-USER-": "unknown",
    },
    "remainder": "unknown",
}
_MANIFEST_JSON = json.dumps(
    _RULE_MANIFEST, ensure_ascii=False, sort_keys=True, separators=(",", ":")
)
_MANIFEST_SHA256 = hashlib.sha256(_MANIFEST_JSON.encode()).hexdigest()
_USER_TIMESTAMP = re.compile(r"^\[\d{2}:\d{2}\]")


@dataclass(frozen=True)
class PlannedUpdate:
    log_id: int
    origin: str
    origin_detail: str


def _provenance(
    origin: str,
    sender: str,
    *,
    subtype: str = "",
    ref: str = "",
) -> MessageProvenance:
    return MessageProvenance(
        origin=origin,
        senders=(sender or "unknown",),
        subtype=subtype,
        ref=ref,
    )


def _validate_manifest(path: Path | None) -> None:
    if path is None:
        return
    supplied = json.loads(path.read_text(encoding="utf-8"))
    supplied_json = json.dumps(
        supplied, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    if hashlib.sha256(supplied_json.encode()).hexdigest() != _MANIFEST_SHA256:
        raise ValueError(
            "manifest drift: supplied classification rules do not match "
            f"{_MIGRATION_ID}"
        )


def _require_schema(connection: sqlite3.Connection) -> None:
    required = {
        "logs": {"id", "type", "content", "origin", "origin_detail"},
        "sessions": {"id", "name", "scope"},
        "initial_deliveries": {
            "delivery_id", "schema_version", "session_id", "worker_name", "scope",
            "sender", "message", "user_log_id", "origin", "origin_detail", "payload_hash",
        },
        "message_deliveries": {
            "delivery_id", "schema_version", "source_session_id", "source_principal",
            "source_name", "source_scope", "source_task_id", "target_session_id",
            "target_name", "target_scope", "target_task_id", "target_generation",
            "message", "rendered_message", "message_kind", "wake", "user_log_id",
            "origin", "origin_detail", "payload_hash",
        },
    }
    for table, expected in required.items():
        actual = {
            str(row[1])
            for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        missing = expected - actual
        if missing:
            raise ValueError(
                f"target schema is missing {table} columns: {', '.join(sorted(missing))}"
            )


def _stored_receipt_provenance(row: sqlite3.Row) -> MessageProvenance:
    return MessageProvenance.from_storage(row["origin"], row["origin_detail"])


def _message_receipt_provenance(row: sqlite3.Row) -> MessageProvenance:
    if int(row["schema_version"]) >= _B1_RECEIPT_SCHEMA:
        return _stored_receipt_provenance(row)
    delivery_id = str(row["delivery_id"])
    principal = str(row["source_principal"] or "")
    if principal.startswith("operator:"):
        return _provenance(
            "user", "user", subtype="direct_message", ref=delivery_id,
        )
    if principal.startswith("mcp:"):
        sender = str(row["source_name"] or principal.removeprefix("mcp:")).strip()
        if sender:
            return _provenance(
                "agent", sender, subtype="direct_message", ref=delivery_id,
            )
    return _provenance(
        "unknown", "unknown", subtype="legacy_direct_untrusted", ref=delivery_id,
    )


def _message_receipt(
    connection: sqlite3.Connection, log_id: int,
) -> MessageProvenance | None:
    row = connection.execute(
        "SELECT * FROM message_deliveries WHERE user_log_id=?",
        (log_id,),
    ).fetchone()
    return _message_receipt_provenance(row) if row is not None else None


def _initial_receipt_provenance(
    connection: sqlite3.Connection, row: sqlite3.Row,
) -> MessageProvenance:
    if int(row["schema_version"]) >= _B1_RECEIPT_SCHEMA:
        return _stored_receipt_provenance(row)
    delivery_id = str(row["delivery_id"])
    sender = str(row["sender"] or "").strip()
    matched = connection.execute(
        "SELECT 1 FROM sessions WHERE name=? AND scope=? LIMIT 1",
        (sender, row["scope"]),
    ).fetchone()
    if sender and matched is not None:
        return _provenance(
            "agent", sender, subtype="initial_delivery", ref=delivery_id,
        )
    return _provenance(
        "unknown", "unknown", subtype="legacy_initial_untrusted", ref=delivery_id,
    )


def _initial_receipt(
    connection: sqlite3.Connection, log_id: int,
) -> MessageProvenance | None:
    row = connection.execute(
        "SELECT * FROM initial_deliveries WHERE user_log_id=?",
        (log_id,),
    ).fetchone()
    return _initial_receipt_provenance(connection, row) if row is not None else None


def _from_text(content: str) -> MessageProvenance:
    timestamp = _USER_TIMESTAMP.match(content)
    if timestamp is not None:
        remainder = content[timestamp.end():].lstrip()
        if remainder.startswith("[from:"):
            sender = remainder[len("[from:"):].split("]", 1)[0].strip()
            if sender:
                return _provenance("agent", sender, subtype="agent_message")
        return _provenance("user", "user", subtype="dashboard")
    if content.startswith("[from TG:"):
        return _provenance("user", "telegram", subtype="telegram")
    if content.startswith("[from:"):
        sender = content[len("[from:"):].split("]", 1)[0].strip()
        if sender:
            return _provenance("agent", sender, subtype="agent_message")
        return _provenance("unknown", "unknown", subtype="malformed_legacy_prefix")
    if content.startswith("[Background job completed]"):
        return _provenance("background_task", "background_task", subtype="completed")
    if content.startswith("[Orchestra platform note:"):
        return _provenance("platform", "orchestra", subtype="platform_note")

    if content.startswith("[system]"):
        return _provenance("system", "orchestra", subtype="system_message")
    if content.startswith("[system wake:"):
        ref = content[len("[system wake:"):].split("]", 1)[0].strip()
        return _provenance("system", "orchestra", subtype="limit_wake", ref=ref)
    if content.startswith("[PREVIOUS CONTEXT SUMMARY"):
        return _provenance("platform", "orchestra", subtype="compact_summary")
    if content.startswith("НЕДОСТАВКА:"):
        return _provenance("platform", "orchestra", subtype="undelivered")
    if content.startswith("BUG REPORT платформы:"):
        return _provenance("platform", "orchestra", subtype="bug_report")
    if content.startswith("fan="):
        return _provenance("platform", "orchestra", subtype="fan_barrier")
    if content.startswith("[Cron job fired]"):
        return _provenance("background_task", "background_task", subtype="cron_job")
    if content.startswith("[Cron command matched]"):
        return _provenance("background_task", "background_task", subtype="cron_command")
    if content.startswith("LIVE-USER-"):
        return _provenance("unknown", "unknown", subtype="test_artifact")
    return _provenance("unknown", "unknown")


def _classify(
    connection: sqlite3.Connection, log_id: int, content: str,
) -> MessageProvenance:
    message_receipt = _message_receipt(connection, log_id)
    initial_receipt = _initial_receipt(connection, log_id)
    if message_receipt is not None and initial_receipt is not None:
        raise ValueError(f"log {log_id} is linked to two delivery receipts")
    return message_receipt or initial_receipt or _from_text(content)


def _plan(
    connection: sqlite3.Connection,
) -> tuple[list[PlannedUpdate], dict[str, int], int, int, int]:
    rows = connection.execute(
        """SELECT id, content, origin, origin_detail
             FROM logs
            WHERE type='user_message' AND id<=?
            ORDER BY id"""
        , (_FROZEN_MAX_LOG_ID,)
    ).fetchall()
    counts = {origin: 0 for origin in sorted(MESSAGE_ORIGINS)}
    updates: list[PlannedUpdate] = []
    invalid = 0
    for row in rows:
        provenance = _classify(connection, int(row["id"]), str(row["content"]))
        origin, detail = provenance.to_storage()
        counts[origin] += 1
        try:
            MessageProvenance.from_storage(origin, detail)
        except ValueError:
            invalid += 1
        if row["origin"] != origin or row["origin_detail"] != detail:
            updates.append(PlannedUpdate(int(row["id"]), origin, detail))
    sessions = int(connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0])
    return updates, counts, invalid, len(rows), sessions


def _check_manifest_receipt(connection: sqlite3.Connection) -> bool:
    exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name='message_provenance_migrations'"
    ).fetchone()
    if exists is None:
        return False
    row = connection.execute(
        "SELECT manifest_sha256 FROM message_provenance_migrations WHERE migration_id=?",
        (_MIGRATION_ID,),
    ).fetchone()
    if row is not None and row[0] != _MANIFEST_SHA256:
        raise ValueError(
            f"manifest drift: stored digest for {_MIGRATION_ID} is {row[0]!r}, "
            f"expected {_MANIFEST_SHA256!r}"
        )
    return row is not None


def _current_state(
    connection: sqlite3.Connection,
) -> tuple[dict[str, int], int, int]:
    counts = {origin: 0 for origin in sorted(MESSAGE_ORIGINS)}
    rows = connection.execute(
        """SELECT origin, origin_detail FROM logs
            WHERE type='user_message' AND id<=?""",
        (_FROZEN_MAX_LOG_ID,),
    ).fetchall()
    for row in rows:
        provenance = MessageProvenance.from_storage(
            row["origin"], row["origin_detail"],
        )
        counts[provenance.origin] += 1
    sessions = int(connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0])
    return counts, len(rows), sessions


def _legacy_receipt_count(connection: sqlite3.Connection) -> int:
    return sum(
        int(connection.execute(
            f"SELECT COUNT(*) FROM {table} WHERE schema_version<?",
            (_B1_RECEIPT_SCHEMA,),
        ).fetchone()[0])
        for table in ("initial_deliveries", "message_deliveries")
    )


def _expected_initial_receipt_hash(
    row: sqlite3.Row, provenance: MessageProvenance,
) -> str:
    return _initial_payload_hash(
        session_id=row["session_id"], worker_name=row["worker_name"],
        scope=row["scope"], sender=row["sender"], message=row["message"],
        provenance=provenance,
    )


def _expected_message_receipt_hash(
    row: sqlite3.Row, provenance: MessageProvenance,
) -> str:
    origin, detail = provenance.to_storage()
    return _message_payload_hash(
        source_session_id=row["source_session_id"],
        source_principal=row["source_principal"],
        source_scope=row["source_scope"],
        source_task_id=row["source_task_id"],
        target_session_id=row["target_session_id"],
        target_scope=row["target_scope"],
        target_task_id=row["target_task_id"],
        target_generation=row["target_generation"],
        message=row["message"], rendered_message=row["rendered_message"],
        message_kind=row["message_kind"], wake=bool(row["wake"]),
        origin=origin, origin_detail=json.loads(detail),
    )


def _upgrade_legacy_receipts(connection: sqlite3.Connection) -> int:
    updated = 0
    for row in connection.execute(
        "SELECT * FROM initial_deliveries WHERE schema_version<? ORDER BY delivery_id",
        (_B1_RECEIPT_SCHEMA,),
    ).fetchall():
        provenance = _initial_receipt_provenance(connection, row)
        origin, detail = provenance.to_storage()
        payload_hash = _expected_initial_receipt_hash(row, provenance)
        cursor = connection.execute(
            """UPDATE initial_deliveries
                  SET schema_version=?, origin=?, origin_detail=?, payload_hash=?
                WHERE delivery_id=? AND schema_version<?""",
            (
                _B1_RECEIPT_SCHEMA, origin, detail, payload_hash,
                row["delivery_id"], _B1_RECEIPT_SCHEMA,
            ),
        )
        if cursor.rowcount != 1:
            raise ValueError(f"initial receipt upgrade lost {row['delivery_id']}")
        updated += 1

    for row in connection.execute(
        "SELECT * FROM message_deliveries WHERE schema_version<? ORDER BY delivery_id",
        (_B1_RECEIPT_SCHEMA,),
    ).fetchall():
        provenance = _message_receipt_provenance(row)
        origin, detail = provenance.to_storage()
        payload_hash = _expected_message_receipt_hash(row, provenance)
        cursor = connection.execute(
            """UPDATE message_deliveries
                  SET schema_version=?, origin=?, origin_detail=?, payload_hash=?
                WHERE delivery_id=? AND schema_version<?""",
            (
                _B1_RECEIPT_SCHEMA, origin, detail, payload_hash,
                row["delivery_id"], _B1_RECEIPT_SCHEMA,
            ),
        )
        if cursor.rowcount != 1:
            raise ValueError(f"message receipt upgrade lost {row['delivery_id']}")
        updated += 1
    return updated


def _validate_receipt_hashes(connection: sqlite3.Connection) -> None:
    for row in connection.execute(
        "SELECT * FROM initial_deliveries WHERE schema_version>=?",
        (_B1_RECEIPT_SCHEMA,),
    ).fetchall():
        provenance = _stored_receipt_provenance(row)
        expected = _expected_initial_receipt_hash(row, provenance)
        if row["payload_hash"] != expected:
            raise ValueError(f"initial receipt payload hash mismatch: {row['delivery_id']}")
    for row in connection.execute(
        "SELECT * FROM message_deliveries WHERE schema_version>=?",
        (_B1_RECEIPT_SCHEMA,),
    ).fetchall():
        provenance = _stored_receipt_provenance(row)
        expected = _expected_message_receipt_hash(row, provenance)
        if row["payload_hash"] != expected:
            raise ValueError(f"message receipt payload hash mismatch: {row['delivery_id']}")


def _backup_database(db_path: Path, backup_path: Path) -> None:
    db_real = os.path.realpath(db_path)
    backup_real = os.path.realpath(backup_path)
    if db_real == backup_real:
        raise ValueError("backup path aliases the database path")
    if os.path.lexists(backup_path):
        try:
            db_stat = os.stat(db_path)
            backup_stat = os.stat(backup_path)
            if (db_stat.st_dev, db_stat.st_ino) == (backup_stat.st_dev, backup_stat.st_ino):
                raise ValueError("backup path aliases the database inode")
        except FileNotFoundError:
            pass
        raise ValueError(f"backup path already exists: {backup_path}")

    backup_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{backup_path.name}.", suffix=".tmp", dir=backup_path.parent
    )
    os.close(descriptor)
    temp_path = Path(temp_name)
    source = sqlite3.connect(str(db_path))
    target = sqlite3.connect(str(temp_path))
    try:
        source.backup(target)
        target.close()
        target = None
        try:
            os.link(temp_path, backup_path)
        except FileExistsError as error:
            raise ValueError(f"backup path already exists: {backup_path}") from error
    finally:
        if target is not None:
            target.close()
        source.close()
        temp_path.unlink(missing_ok=True)


def _summary(
    *,
    mode: str,
    target: Path,
    rows_before: int,
    rows_after: int,
    sessions_before: int,
    sessions_after: int,
    counts: dict[str, int],
    invalid: int,
    would_update: int,
    updated: int,
) -> dict[str, Any]:
    return {
        "mode": mode,
        "target": str(target.resolve()),
        "rows_before": rows_before,
        "rows_after": rows_after,
        "sessions_before": sessions_before,
        "sessions_after": sessions_after,
        "counts": counts,
        "invalid": invalid,
        "would_update": would_update,
        "updated": updated,
    }


def migrate_database(
    db_path: Path,
    *,
    apply: bool,
    backup_path: Path | None = None,
) -> dict[str, Any]:
    target = db_path.resolve()
    if not target.is_file():
        raise ValueError(f"target database does not exist: {target}")
    if backup_path is not None and not apply:
        raise ValueError("--backup is valid only with --apply")
    production_target = (_REPO_ROOT / "data/orchestra.db").resolve()
    if apply and target == production_target and backup_path is None:
        raise ValueError("production --apply requires --backup")

    connection = sqlite3.connect(str(target), timeout=30)
    connection.row_factory = sqlite3.Row
    try:
        _require_schema(connection)
        already_applied = _check_manifest_receipt(connection)
        if already_applied:
            _validate_receipt_hashes(connection)
            counts, rows, sessions = _current_state(connection)
            if _legacy_receipt_count(connection):
                raise ValueError("matching migration receipt has legacy delivery receipts")
            return _summary(
                mode="apply" if apply else "dry-run", target=target,
                rows_before=rows, rows_after=rows,
                sessions_before=sessions, sessions_after=sessions,
                counts=counts, invalid=0, would_update=0, updated=0,
            )
        if not apply:
            updates, counts, invalid, rows_before, sessions_before = _plan(connection)
            receipt_updates = _legacy_receipt_count(connection)
            return _summary(
                mode="dry-run", target=target,
                rows_before=rows_before, rows_after=rows_before,
                sessions_before=sessions_before, sessions_after=sessions_before,
                counts=counts, invalid=invalid,
                would_update=len(updates) + receipt_updates, updated=0,
            )

        connection.execute("BEGIN IMMEDIATE")
        try:
            if _check_manifest_receipt(connection):
                _validate_receipt_hashes(connection)
                if _legacy_receipt_count(connection):
                    raise ValueError(
                        "matching migration receipt has legacy delivery receipts"
                    )
                counts, rows, sessions = _current_state(connection)
                connection.rollback()
                return _summary(
                    mode="apply", target=target,
                    rows_before=rows, rows_after=rows,
                    sessions_before=sessions, sessions_after=sessions,
                    counts=counts, invalid=0, would_update=0, updated=0,
                )
            if backup_path is not None:
                _backup_database(target, backup_path)
            connection.execute(
                """CREATE TABLE IF NOT EXISTS message_provenance_migrations (
                       migration_id TEXT PRIMARY KEY,
                       manifest_sha256 TEXT NOT NULL,
                       applied_at TEXT NOT NULL
                   )"""
            )
            updates, counts, invalid, rows_before, sessions_before = _plan(connection)
            receipt_updates = _legacy_receipt_count(connection)
            upgraded_receipts = _upgrade_legacy_receipts(connection)
            if upgraded_receipts != receipt_updates:
                raise ValueError(
                    f"receipt upgrade count mismatch: {upgraded_receipts}!={receipt_updates}"
                )
            _validate_receipt_hashes(connection)
            updated = 0
            for item in updates:
                cursor = connection.execute(
                    "UPDATE logs SET origin=?, origin_detail=? WHERE id=?",
                    (item.origin, item.origin_detail, item.log_id),
                )
                updated += cursor.rowcount
            if updated != len(updates):
                raise ValueError(
                    f"log update count mismatch: {updated}!={len(updates)}"
                )
            after_updates, after_counts, after_invalid, rows_after, sessions_after = _plan(
                connection
            )
            if after_updates or _legacy_receipt_count(connection) or after_invalid:
                raise ValueError(
                    "migration validation failed before commit: "
                    f"logs={len(after_updates)}, receipts={_legacy_receipt_count(connection)}, "
                    f"invalid={after_invalid}"
                )
            connection.execute(
                """INSERT INTO message_provenance_migrations(
                       migration_id, manifest_sha256, applied_at
                   ) VALUES(?,?,?)
                   ON CONFLICT(migration_id) DO NOTHING""",
                (
                    _MIGRATION_ID,
                    _MANIFEST_SHA256,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            # Final receipt invariant: no trigger-capable write may follow this check.
            _validate_receipt_hashes(connection)  # final post-trigger validation
            connection.commit()
        except Exception:
            connection.rollback()
            raise

        return _summary(
            mode="apply", target=target,
            rows_before=rows_before, rows_after=rows_after,
            sessions_before=sessions_before, sessions_after=sessions_after,
            counts=after_counts, invalid=after_invalid,
            would_update=len(updates) + receipt_updates,
            updated=updated + upgraded_receipts,
        )
    finally:
        connection.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup", type=Path)
    parser.add_argument(
        "--manifest", type=Path,
        help="optional exact copy of the frozen classification manifest",
    )
    args = parser.parse_args(argv)
    try:
        _validate_manifest(args.manifest)
        result = migrate_database(
            args.db,
            apply=args.apply,
            backup_path=args.backup,
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    except (OSError, ValueError, sqlite3.Error, json.JSONDecodeError) as error:
        print(f"migration failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
