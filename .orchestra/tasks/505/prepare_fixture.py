#!/usr/bin/env python3
"""Freeze the completed #474 tests used as #505's independent oracle."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
FIX_COMMIT = "cb052ede731d0a0846a340b02b1992da549cf095"
ORACLE_FILES = (
    "tests/test_review_coverage_target_drift_474.py",
    "tests/test_merge_test_gate.py",
    "tests/test_acceptance.py",
    "tests/test_review_receipt_migration_436.py",
)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    task_dir = Path(__file__).resolve().parent
    oracle_dir = task_dir / "oracle_tests"
    oracle_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, object] = {
        "schema_version": 1,
        "fix_commit": FIX_COMMIT,
        "files": {},
    }
    for relative in ORACLE_FILES:
        data = subprocess.check_output(
            ["git", "show", f"{FIX_COMMIT}:{relative}"], cwd=ROOT
        )
        destination = oracle_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        manifest["files"][relative] = {"bytes": len(data), "sha256": digest(data)}
    (task_dir / "oracle_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"frozen {len(ORACLE_FILES)} oracle files from {FIX_COMMIT}")


if __name__ == "__main__":
    main()
