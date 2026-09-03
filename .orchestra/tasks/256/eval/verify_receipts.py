#!/usr/bin/env python3
"""Recompute #256 anchor flags from source IDs + chunk hashes in a read-only vec.db.

This does not make the baseline self-contained: the live DB is not committed. It proves
that, at verification time, every retained result hash resolved to a real indexed chunk
and that the runner's positive/stale flags recomputed from those chunks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def load_holdout(path: Path) -> dict[str, dict]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    return {row["id"]: row for row in rows}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--holdout", type=Path, required=True)
    parser.add_argument("--vec-db", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    holdout = load_holdout(args.holdout)
    conn = sqlite3.connect(f"file:{args.vec_db.resolve()}?mode=ro", uri=True)
    result_count = receipt_count = flag_match_count = 0
    item_receipts = []
    try:
        for item in baseline["items"]:
            case = holdout[item["id"]]
            receipts = []
            for result in item["results"]:
                result_count += 1
                if result["source"] == "file":
                    texts = [row[0] for row in conn.execute(
                        "SELECT fc.text FROM file_chunks fc JOIN files f USING(file_id) "
                        "WHERE f.project=? AND f.path=?",
                        (baseline["scope"], result["path"]),
                    )]
                else:
                    texts = [row[0] for row in conn.execute(
                        "SELECT text FROM log_chunks WHERE log_id=?", (result["log_id"],)
                    )]
                content = next((
                    text for text in texts
                    if hashlib.sha256(text.encode("utf-8")).hexdigest() == result["content_sha256"]
                ), None)
                resolved = content is not None
                receipt_count += resolved
                recomputed_gold = bool(content is not None and case["must_contain"] in content)
                recomputed_forbidden = sum(
                    content is not None and anchor in content
                    for anchor in case.get("must_not_contain") or []
                )
                flags_match = (
                    recomputed_gold == result["contains_gold_anchor"]
                    and recomputed_forbidden == result["forbidden_anchor_count"]
                )
                flag_match_count += flags_match
                receipts.append({
                    "rank": result["rank"],
                    "source": result["source"],
                    "path": result["path"],
                    "log_id": result["log_id"],
                    "content_sha256": result["content_sha256"],
                    "receipt_resolved": resolved,
                    "flags_recomputed_equal": flags_match,
                })
            item_receipts.append({"id": item["id"], "receipts": receipts})
    finally:
        conn.close()

    artifact = {
        "schema": "orchestra-kb-baseline-receipts-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "baseline_created_at": baseline["created_at"],
        "baseline_git_head": baseline["git_head"],
        "baseline_holdout_sha256": baseline["holdout_sha256"],
        "vec_db_path": str(args.vec_db.resolve()),
        "results": result_count,
        "receipts_resolved": receipt_count,
        "flags_recomputed_equal": flag_match_count,
        "all_receipts_resolved": receipt_count == result_count,
        "all_flags_equal": flag_match_count == result_count,
        "self_contained": False,
        "limitation": "The 610 MiB live vec.db snapshot is not committed. Future index updates may remove old chunks, so source IDs + hashes are receipts, not permanent embedded evidence.",
        "items": item_receipts,
    }
    args.output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
