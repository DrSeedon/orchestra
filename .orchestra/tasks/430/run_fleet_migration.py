#!/usr/bin/env python3
"""Run the approved #430 fleet migration one registered repository at a time."""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from app.orchestra_layout import (
    LayoutMigrationError,
    _layout_state,
    _mapped_status_records,
    _status_records,
    migrate_project_layout_preserving_dirty,
)


def git(repository: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repository), *args],
        text=True,
        capture_output=True,
        check=check,
    )


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)

    with sqlite3.connect(f"file:{args.database.resolve().as_posix()}?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute(
            "SELECT id,scope FROM tm_projects WHERE scope IS NOT NULL AND trim(scope)!='' "
            "ORDER BY id"
        ).fetchall()

    receipts = []
    for index, row in enumerate(rows, start=1):
        project_id = str(row["id"])
        repository = Path(str(row["scope"])).expanduser().resolve()
        stem = f"{index:02d}-{project_id.replace('/', '_').replace(':', '_')}"
        receipt = {"project_id": project_id, "repository": str(repository)}
        try:
            before_head = git(repository, "rev-parse", "HEAD").stdout.strip()
            before_status = git(repository, "status", "--short").stdout
            before_records = _status_records(repository)
            write(output / f"{stem}-before.txt", before_status)

            result = migrate_project_layout_preserving_dirty(repository)

            after_head = git(repository, "rev-parse", "HEAD").stdout.strip()
            after_status = git(repository, "status", "--short").stdout
            after_records = sorted(
                _status_records(repository),
                key=lambda item: (item["path"], item["xy"], item.get("original", "")),
            )
            expected_records = _mapped_status_records(before_records)
            state, managed = _layout_state(repository)
            equivalent = after_records == expected_records
            write(output / f"{stem}-after.txt", after_status)
            commit_stat = (
                git(repository, "show", "--stat", "--oneline", after_head).stdout
                if after_head != before_head
                else "no migration commit created\n"
            )
            write(output / f"{stem}-commit-stat.txt", commit_stat)
            receipt.update(
                {
                    "outcome": str(result["status"]),
                    "before_head": before_head,
                    "after_head": after_head,
                    "before_dirty_files": len(before_records),
                    "after_dirty_files": len(after_records),
                    "status_equivalent_after_path_mapping": equivalent,
                    "layout_state": state,
                    "managed_paths": managed,
                    "result": result,
                }
            )
            if state != "current" or not equivalent:
                receipt["outcome"] = "verification_failed"
        except (LayoutMigrationError, OSError, subprocess.CalledProcessError) as error:
            receipt.update(
                {
                    "outcome": "failed",
                    "error_type": type(error).__name__,
                    "error": str(error),
                }
            )
            if repository.exists():
                write(
                    output / f"{stem}-after.txt",
                    git(repository, "status", "--short", check=False).stdout,
                )
        write(
            output / f"{stem}-receipt.json",
            json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )
        receipts.append(receipt)
        print(f"{index}/{len(rows)} {project_id}: {receipt['outcome']}", flush=True)

    summary = {
        "schema_version": 1,
        "database": str(args.database.resolve()),
        "projects": len(receipts),
        "current": sum(item.get("layout_state") == "current" for item in receipts),
        "failed": sum(item["outcome"] in {"failed", "verification_failed"} for item in receipts),
        "outcomes": {item["project_id"]: item["outcome"] for item in receipts},
    }
    write(output / "summary.json", json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True), flush=True)
    return 0 if summary["projects"] == 13 and summary["current"] == 13 and not summary["failed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
