#!/usr/bin/env python3
"""Create a WAL-consistent private snapshot and a public provenance manifest."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


SOURCE = Path("/mnt/data/Projects/Python/orchestra/data/orchestra.db")
TASK_DIR = Path(__file__).resolve().parent
BACKUP = TASK_DIR / "private" / "orchestra-20260824.sqlite"
MANIFEST = TASK_DIR / "backup-manifest.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    BACKUP.parent.mkdir(parents=True, exist_ok=True)
    if BACKUP.exists():
        raise SystemExit(f"refusing to overwrite frozen backup: {BACKUP}")

    started = datetime.now(timezone.utc).isoformat()
    source_uri = f"file:{SOURCE}?mode=ro"
    with sqlite3.connect(source_uri, uri=True) as src, sqlite3.connect(BACKUP) as dst:
        src.backup(dst)
    completed = datetime.now(timezone.utc).isoformat()

    with sqlite3.connect(f"file:{BACKUP}?mode=ro", uri=True) as db:
        quick_check = db.execute("PRAGMA quick_check").fetchone()[0]
        tables = {
            row[0]: db.execute(f'SELECT COUNT(*) FROM "{row[0]}"').fetchone()[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        }
        maxima = {}
        for table, column in (
            ("logs", "ts"),
            ("turn_usage", "ts"),
            ("usage_snapshots", "ts"),
            ("sessions", "created_at"),
            ("tm_tasks", "updated_at"),
        ):
            maxima[f"{table}.{column}"] = db.execute(
                f'SELECT MAX("{column}") FROM "{table}"'
            ).fetchone()[0]
        page_count = db.execute("PRAGMA page_count").fetchone()[0]
        page_size = db.execute("PRAGMA page_size").fetchone()[0]

    source_files = {}
    for path in (SOURCE, Path(f"{SOURCE}-wal"), Path(f"{SOURCE}-shm")):
        if path.exists():
            stat = path.stat()
            source_files[path.name] = {
                "bytes_observed_after_backup": stat.st_size,
                "mtime_ns_observed_after_backup": stat.st_mtime_ns,
            }

    manifest = {
        "method": "Python sqlite3.Connection.backup from mode=ro source",
        "source": str(SOURCE),
        "backup_private_relative_path": str(BACKUP.relative_to(TASK_DIR)),
        "started_utc": started,
        "completed_utc": completed,
        "sha256": sha256(BACKUP),
        "bytes": BACKUP.stat().st_size,
        "page_count": page_count,
        "page_size": page_size,
        "quick_check": quick_check,
        "table_counts": tables,
        "maxima": maxima,
        "source_files_observed_after_backup": source_files,
        "publication": "Full backup is private/ignored because rows can contain credentials or user content; sanitized derived evidence is tracked separately.",
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
