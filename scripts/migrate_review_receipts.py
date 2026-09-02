#!/usr/bin/env python3
"""One-shot import of historical review metadata into structured receipts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _classify(item: dict) -> dict:
    row = dict(item)
    source = row.get("model_source", "unknown")
    if source == "inferred_historical_default":
        source = "derived"
    elif source not in {"direct", "derived"}:
        source = "unknown"
    row["model_source"] = source
    if row.get("outcome") not in {"accepted", "disputed", "partial"}:
        row["outcome"] = "unknown"
        row["outcome_source"] = "unknown"
    elif row.get("outcome_source") != "direct":
        row["outcome_source"] = "derived"
    return row


def _load_manifest(path: Path) -> tuple[dict, list[dict]]:
    with path.open(encoding="utf-8") as source:
        manifest = json.load(source)
    if not isinstance(manifest, dict) or not isinstance(manifest.get("artifacts"), list):
        raise ValueError("manifest must contain an artifacts list")
    return manifest, [_classify(item) for item in manifest["artifacts"]]


def _check_drift(root: Path, manifest: dict, items: list[dict]) -> None:
    for item in items:
        path = root / item["path"]
        if not path.is_file():
            raise ValueError(f"manifest artifact is missing: {path}")
        data = path.read_bytes()
        expected_size = item.get("size_bytes")
        expected_sha = item.get("sha256")
        if expected_size is not None and len(data) != expected_size:
            raise ValueError(f"manifest drift (size): {path}")
        if expected_sha and hashlib.sha256(data).hexdigest() != expected_sha:
            raise ValueError(f"manifest drift (sha256): {path}")


def _validate_integrity_fields(items: list[dict]) -> None:
    for item in items:
        path = str(item.get("path") or "")
        size = item.get("size_bytes")
        digest = item.get("sha256")
        if not isinstance(size, int) or size < 0:
            raise ValueError(f"manifest size_bytes is required: {path}")
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-fA-F]{64}", digest) is None:
            raise ValueError(f"manifest sha256 is required: {path}")


def _receipt(item: dict) -> dict:
    path = str(item["path"])
    round_key = str(item.get("round") if item.get("round") is not None else "unknown")
    receipt_id = "legacy-review:" + hashlib.sha256(
        f"{path}\0{round_key}".encode()
    ).hexdigest()
    return {
        "receipt_id": receipt_id,
        "schema_version": 1,
        "runtime": item.get("runtime", "codex"),
        "reviewer_model": item.get("model", ""),
        "model_source": item.get("model_source", "unknown"),
        "session_id": item.get("session_id", ""),
        "worker_name": item.get("worker_name", ""),
        "scope": item.get("scope", ""),
        "task_id": item.get("task_id", ""),
        "task_source": item.get("task_source", "unknown"),
        "artifact_path": path,
        "mode": item.get("mode", "unknown"),
        "round": item.get("round"),
        "job_id": item.get("job_id", ""),
        "usage_event_id": item.get("usage_event_id", ""),
        "requested_at": item.get("requested_at", "1970-01-01T00:00:00+00:00"),
        "status": item.get("status", "completed"),
        "return_code": item.get("return_code"),
        "failure_code": item.get("failure_code", ""),
        "artifact_exists": item.get("artifact_exists", True),
        "artifact_bytes": item.get("artifact_bytes", item.get("size_bytes")),
        "artifact_sha256": item.get("sha256", ""),
        "verdict_present": item.get("verdict_present", False),
        "verdict_value": item.get("verdict_value", ""),
        "jsonl_response_present": item.get("jsonl_response_present", False),
        "recovery_source": item.get("recovery_source", ""),
        "author_outcome": item.get("outcome", "unknown"),
        "outcome_source": item.get("outcome_source", "unknown"),
        "outcome_evidence_ref": item.get("outcome_evidence_ref", ""),
        "notification_event_id": item.get("notification_event_id", ""),
    }


def _backup_database(db_path: Path, backup_path: Path) -> None:
    if not db_path.is_file():
        return
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
    source = sqlite3.connect(str(db_path))
    target = sqlite3.connect(str(backup_path))
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()


def _apply_receipts(db_path: Path, backup_path: Path, receipts: list[dict]) -> None:
    """Snapshot with SQLite backup, then insert the batch in one transaction."""
    os.environ["ORCHESTRA_DB_PATH"] = str(db_path)
    from app.db import _REVIEW_RECEIPT_COLUMNS, init_db

    _backup_database(db_path, backup_path)
    init_db()
    source = sqlite3.connect(str(db_path))
    snapshot = sqlite3.connect(":memory:")
    placeholders = ", ".join("?" for _ in _REVIEW_RECEIPT_COLUMNS)
    columns = ", ".join(_REVIEW_RECEIPT_COLUMNS)
    try:
        source.backup(snapshot)
        source.execute("BEGIN IMMEDIATE")
        for receipt in receipts:
            cursor = source.execute(
                f"INSERT INTO review_receipts ({columns}) VALUES ({placeholders}) "
                "ON CONFLICT(receipt_id) DO NOTHING",
                tuple(receipt.get(key) for key in _REVIEW_RECEIPT_COLUMNS),
            )
            if cursor.rowcount == 0:
                existing = source.execute(
                    "SELECT * FROM review_receipts WHERE receipt_id=?",
                    (receipt["receipt_id"],),
                ).fetchone()
                incoming = tuple(receipt.get(key) for key in _REVIEW_RECEIPT_COLUMNS)
                if existing is None or tuple(existing) != incoming:
                    raise ValueError(
                        "receipt id conflicts with existing provenance: "
                        + receipt["receipt_id"]
                    )
        source.commit()
    except Exception:
        source.rollback()
        raise
    finally:
        snapshot.close()
        source.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-live", action="store_true")
    parser.add_argument("--backup-path", type=Path)
    args = parser.parse_args(argv)
    if args.dry_run == args.apply:
        parser.error("choose exactly one of --dry-run or --apply")
    try:
        manifest, items = _load_manifest(args.manifest)
        if args.apply:
            if not args.confirm_live:
                raise ValueError("--apply requires --confirm-live")
            _validate_integrity_fields(items)
            _check_drift(args.root, manifest, items)
        receipts = [_receipt(item) for item in items]
        if args.apply:
            backup_path = args.backup_path or args.db.with_name(
                args.db.name + ".review-receipts.backup"
            )
            _apply_receipts(args.db, backup_path, receipts)
        print(json.dumps({"schema_version": 1, "artifacts": items,
                          "receipts": receipts if args.apply else []},
                         ensure_ascii=False, sort_keys=True))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"migration failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
