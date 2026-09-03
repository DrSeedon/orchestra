"""Measure the exact cold FTS delete seam on disposable #395 SQLite backups."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import tempfile
import time
from pathlib import Path


def _backup(source: Path, destination: Path) -> None:
    with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as src:
        with sqlite3.connect(destination) as dst:
            src.backup(dst)


def _drop_cache(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.posix_fadvise(descriptor, 0, 0, os.POSIX_FADV_DONTNEED)
    finally:
        os.close(descriptor)


def _once(source: Path, work_root: Path, arm: str, iteration: int) -> dict:
    descriptor, name = tempfile.mkstemp(
        prefix=f"fts-{arm}-{iteration}-", suffix=".db", dir=work_root,
    )
    os.close(descriptor)
    destination = Path(name)
    destination.unlink()
    try:
        _backup(source, destination)
        _drop_cache(destination)
        with sqlite3.connect(destination) as connection:
            record_key = str(connection.execute(
                "SELECT record_key FROM current_records "
                "WHERE record_type='task.state' ORDER BY record_key LIMIT 1"
            ).fetchone()[0])
            rowid = int(connection.execute(
                "SELECT rowid FROM current_records WHERE record_key=?", (record_key,)
            ).fetchone()[0])
            fts_key = str(connection.execute(
                "SELECT record_key FROM current_fts WHERE rowid=?", (rowid,)
            ).fetchone()[0])
            if fts_key != record_key:
                raise RuntimeError("current/FTS rowid binding is not exact")
            connection.execute("BEGIN IMMEDIATE")
            started = time.perf_counter()
            if arm == "record_key":
                connection.execute(
                    "DELETE FROM current_fts WHERE record_key=?", (record_key,)
                )
            else:
                connection.execute("DELETE FROM current_fts WHERE rowid=?", (rowid,))
            seconds = time.perf_counter() - started
            connection.rollback()
        return {
            "arm": arm,
            "iteration": iteration,
            "seconds": seconds,
            "current_projection_bytes": source.stat().st_size,
            "loadavg": list(os.getloadavg()),
            "rowid_binding": True,
        }
    finally:
        for suffix in ("", "-journal", "-wal", "-shm"):
            Path(f"{destination}{suffix}").unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--iterations", type=int, default=2)
    args = parser.parse_args()
    source = args.source.resolve()
    work_root = source.parent
    rows = []
    for iteration in range(1, args.iterations + 1):
        for arm in ("record_key", "rowid"):
            row = _once(source, work_root, arm, iteration)
            rows.append(row)
            print(json.dumps(row, sort_keys=True))
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n")
    print(json.dumps({"output": str(output), "rows": len(rows)}, sort_keys=True))


if __name__ == "__main__":
    main()
