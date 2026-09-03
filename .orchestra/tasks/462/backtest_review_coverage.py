#!/usr/bin/env python3
"""Read-only backtest for the #462 review-coverage admission predicate."""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
from pathlib import Path


MAPPED_FILE_THRESHOLD = 1
PRODUCTION_PATH_THRESHOLD = 1
RECEIPT_DEPLOY_TASK = "436"


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())
    return proc.stdout


def _diffstat(repo: Path, before: str, after: str) -> dict:
    paths: list[str] = []
    insertions = deletions = 0
    for line in _git(repo, "diff", "--numstat", before, after).splitlines():
        added, removed, path = line.split("\t", 2)
        paths.append(path)
        if added != "-":
            insertions += int(added)
        if removed != "-":
            deletions += int(removed)
    return {
        "files": len(paths),
        "insertions": insertions,
        "deletions": deletions,
        "paths": paths,
        # Both existing merge-test selectors use this exact production prefix.
        "production_paths": [path for path in paths if path.startswith("app/")],
    }


def _receipt_is_completed(row: sqlite3.Row, *, before: str) -> bool:
    # Coverage only: the verdict's quality/value is deliberately not calibrated here.
    return (
        row["status"] == "completed"
        and row["return_code"] == 0
        and row["artifact_exists"] == 1
        and int(row["artifact_bytes"] or 0) > 0
        and row["jsonl_response_present"] == 1
        and bool(row["completed_at"])
        and row["completed_at"] <= before
    )


def run(repo: Path, database: Path) -> dict:
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    scope = str(repo.resolve())

    deploy = connection.execute(
        """SELECT operation_id, created_at, finished_at, result_json
             FROM merge_operations
            WHERE state='SUCCEEDED' AND scope=? AND accepted_task_id=?
            ORDER BY created_at DESC LIMIT 1""",
        (scope, RECEIPT_DEPLOY_TASK),
    ).fetchone()
    if deploy is None:
        raise RuntimeError("successful #436 merge was not found")
    cutoff = deploy["finished_at"] or deploy["created_at"]
    deploy_result = json.loads(deploy["result_json"] or "{}")

    rows = connection.execute(
        """SELECT operation_id, session_id, worker_name, accepted_task_id,
                  created_at, finished_at, result_json
             FROM merge_operations
            WHERE state='SUCCEEDED' AND scope=? AND created_at>?
            ORDER BY created_at""",
        (scope, cutoff),
    ).fetchall()

    measured: list[dict] = []
    for row in rows:
        result = json.loads(row["result_json"] or "{}")
        admission = result.get("admission") or {}
        mapped_files = list(admission.get("mapped_files") or [])
        git = result.get("git") or {}
        diffstat = _diffstat(repo, git["target_before"], git["target_after"])
        receipts = connection.execute(
            """SELECT receipt_id, status, return_code, artifact_exists,
                      artifact_bytes, jsonl_response_present, requested_at,
                      completed_at
                 FROM review_receipts
                WHERE session_id=? AND task_id=? AND requested_at<=?
                ORDER BY requested_at""",
            (row["session_id"], str(row["accepted_task_id"]), row["created_at"]),
        ).fetchall()
        completed = [
            receipt for receipt in receipts
            if _receipt_is_completed(receipt, before=row["created_at"])
        ]
        production_diff = len(diffstat["production_paths"]) >= PRODUCTION_PATH_THRESHOLD
        # No structured skip receipt exists in the #436 schema. Report prose is not proof.
        structured_skip = False
        rejected = production_diff and not completed and not structured_skip
        measured.append({
            "task": str(row["accepted_task_id"]),
            "worker": row["worker_name"],
            "operation_id": row["operation_id"],
            "created_at": row["created_at"],
            "target_before": git["target_before"],
            "target_after": git["target_after"],
            "mapped_files_count": len(mapped_files),
            "production_diff": production_diff,
            "diffstat": {
                "files": diffstat["files"],
                "insertions": diffstat["insertions"],
                "deletions": diffstat["deletions"],
                "production_files": len(diffstat["production_paths"]),
            },
            "completed_review_receipts": [receipt["receipt_id"] for receipt in completed],
            "noncompleted_review_receipts": [
                receipt["receipt_id"] for receipt in receipts if receipt not in completed
            ],
            "structured_skip": structured_skip,
            "predicate_rejects": rejected,
        })

    production = [row for row in measured if row["production_diff"]]
    rejected = [row for row in production if row["predicate_rejects"]]
    accepted = [row for row in production if not row["predicate_rejects"]]
    mapped_nonproduction = [
        row for row in measured
        if row["mapped_files_count"] >= MAPPED_FILE_THRESHOLD
        and not row["production_diff"]
    ]
    production_unmapped = [
        row for row in production
        if row["mapped_files_count"] < MAPPED_FILE_THRESHOLD
    ]
    return {
        "predicate": {
            "mapped_file_threshold": MAPPED_FILE_THRESHOLD,
            "production_path_threshold": PRODUCTION_PATH_THRESHOLD,
            "production_diff": "changed_paths contains at least 1 app/** path",
            "completed_review_receipt": (
                "same session_id+task_id; requested_at and completed_at before merge; "
                "status=completed; return_code=0; "
                "artifact_exists=1; artifact_bytes>0; jsonl_response_present=1"
            ),
            "structured_skip": "none representable by the current #436 receipt schema",
        },
        "cutoff": {
            "rule": "strictly after the successful merge that deployed #436 receipts",
            "task": RECEIPT_DEPLOY_TASK,
            "operation_id": deploy["operation_id"],
            "timestamp": cutoff,
            "target_after": (deploy_result.get("git") or {}).get("target_after", ""),
        },
        "summary": {
            "successful_merges_after_cutoff": len(rows),
            "mapped_merges": sum(
                row["mapped_files_count"] >= MAPPED_FILE_THRESHOLD for row in measured
            ),
            "mapped_but_no_app_paths": len(mapped_nonproduction),
            "production_but_no_mapped_files": len(production_unmapped),
            "production_merges": len(production),
            "predicate_rejections": len(rejected),
            "predicate_acceptances": len(production) - len(rejected),
        },
        "rejected": rejected,
        "accepted": accepted,
        "mapped_nonproduction_controls": mapped_nonproduction,
        "production_unmapped_controls": production_unmapped,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.repo, args.database), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
