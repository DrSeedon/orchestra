#!/usr/bin/env python3
"""Deterministic synthesis of the frozen #506 receipt extraction."""

from __future__ import annotations

import argparse
import json
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


# Manually verified against the receipt-time round text or the receipt verdict. This is deliberately
# explicit: negative verdicts and references to prior blockers make severity inference by regex unsafe.
MEASURED_OUTCOMES = {
    ("462", 1): "nothing",
    ("465", 2): "unclassified",
    ("465", 3): "blocking",
    ("465", 4): "nothing",
    ("466", 1): "blocking",
    ("466", 2): "nothing",
    ("472", 1): "suggestion-only",
    ("473", 2): "blocking",
    ("473", 3): "blocking",
    ("473", 4): "blocking",
    ("474", 1): "blocking",
    ("474", 2): "blocking",
    ("474", 3): "suggestion-only",
    ("478", 1): "suggestion-only",
    ("480", 2): "blocking",
    ("480", 3): "blocking",
    ("480", 4): "nothing",
    ("482", 1): "suggestion-only",
    ("487", 1): "blocking",
    ("487", 2): "blocking",
    ("487", 3): "blocking",
    ("488", 1): "blocking",
    ("488", 2): "suggestion-only",
    ("490", 3): "suggestion-only",
    ("490", 4): "blocking",
    ("490", 5): "nothing",
    ("491", 1): "nothing",
    ("493", 1): "blocking",
    ("493", 2): "blocking",
    ("493", 3): "blocking",
    ("494", 1): "blocking",
    ("494", 2): "blocking",
    ("494", 3): "blocking",
    ("497", 1): "blocking",
    ("497", 2): "nothing",
    ("499", 1): "blocking",
    ("499", 2): "blocking",
    ("499", 3): "nothing",
    ("500", 1): "blocking",
    ("500", 2): "suggestion-only",
    ("500", 3): "suggestion-only",
    ("502", 1): "blocking",
    ("502", 2): "nothing",
}

ROUND_THREE_OUTCOMES = {
    "review-receipt:f23d1025-99f8-46eb-bc8c-0053b0c9a396": "nothing",
    "review-receipt:e6cc8ae3-2f14-4259-aa1d-ac7b87383c7a": "nothing",
    "review-receipt:0a80ab2e-8da6-43d1-b104-cd558ef8ea05": "blocking",
    "review-receipt:54a2a4ca-08ad-450d-971c-0a314c7cdea0": "blocking",
    "review-receipt:05a1173b-c4cf-4b86-b9a9-b4103ce61a1b": "blocking",
    "review-receipt:27622e9e-767f-4b7b-a685-b2a60246c0d5": "blocking",
    "review-receipt:c8a331f3-ec9d-47b3-a702-47eafd943a05": "blocking",
    "review-receipt:bf6b8590-7cc2-4900-af45-d04e983aa25e": "blocking",
    "review-receipt:eca3210d-4afe-4739-a17a-e73d82037fdb": "blocking",
    "review-receipt:d14b80b3-a318-4f63-ae2c-205d21618c7f": "suggestion-only",
    "review-receipt:754bc7ab-04d4-4dd0-9b89-7b292ac5f80d": "unclassified",
    "review-receipt:e0383f51-79be-4e21-a6f5-5a7a5a67f637": "blocking",
    "review-receipt:53ab894b-ee9e-4c1f-84f3-5074e91c0fea": "blocking",
    "review-receipt:3e282344-aa96-4afe-bb77-03a82da684c0": "blocking",
    "review-receipt:d7734490-3e65-49ee-9f3f-ca1d8c051d8b": "blocking",
    "review-receipt:53365e1d-df43-488c-9181-2cc210ab9929": "suggestion-only",
    "review-receipt:3c69959c-6a3a-4f4b-9412-19678ee45de1": "suggestion-only",
    "review-receipt:1a85f75d-fc55-43c5-a895-d90ab8a68957": "nothing",
}

# Luna over Sol/Opus rounds with evidence of subsequent code change. The first eight have a later
# pinned implementation receipt with a non-empty production delta; #105 has a second review that
# explicitly lists all six code/harness findings as fixed and quotes the updated source.
CROSS_MODEL_PINNED_CODE_CHANGE = {
    "review-receipt:7840f9c4-83e9-4c37-88ba-05d4ab27911a",
    "review-receipt:0b736f75-7990-4991-b71c-2f8489b8ba1e",
    "review-receipt:da4af35a-4f4c-4d67-9115-09efba37f939",
    "review-receipt:98c74df6-931a-46e8-98ea-48453b6d92a4",
    "review-receipt:e0383f51-79be-4e21-a6f5-5a7a5a67f637",
    "review-receipt:de3f564b-0ddb-4ef0-aff0-70782d30ef8e",
    "review-receipt:de814406-eb6f-48f8-9d4e-c1b9a78354ac",
    "review-receipt:4e98ca5e-124e-42a5-b125-e47a36860715",
}

CROSS_MODEL_FOLLOWUP_SUPPORTED_CHANGE = {
    "review-receipt:c67246bf-b1e0-41ef-bdfb-2b73b2c62df0",
}

CROSS_MODEL_DELTA_EVIDENCE = {
    "review-receipt:7840f9c4-83e9-4c37-88ba-05d4ab27911a": {
        "task": "466", "next_round": 2,
        "numstat": ["14\t0\tapp/merge_operations.py", "7\t2\tapp/review_coverage.py"],
    },
    "review-receipt:0b736f75-7990-4991-b71c-2f8489b8ba1e": {
        "task": "474", "next_round": 2,
        "numstat": ["62\t23\tapp/merge_operations.py", "6\t1\tapp/merge_test_gate.py", "16\t6\tapp/review_coverage.py"],
    },
    "review-receipt:da4af35a-4f4c-4d67-9115-09efba37f939": {
        "task": "474", "next_round": 3,
        "numstat": ["7\t3\tapp/db.py", "36\t1\tapp/merge_operations.py", "7\t3\tapp/review_coverage.py"],
    },
    "review-receipt:98c74df6-931a-46e8-98ea-48453b6d92a4": {
        "task": "480", "next_round": 3, "numstat": ["30\t12\tapp/fan_barrier.py"],
    },
    "review-receipt:e0383f51-79be-4e21-a6f5-5a7a5a67f637": {
        "task": "480", "next_round": 4, "numstat": ["5\t1\tapp/fan_barrier.py"],
    },
    "review-receipt:de3f564b-0ddb-4ef0-aff0-70782d30ef8e": {
        "task": "499", "next_round": 2,
        "numstat": ["4\t4\tapp/ia/task_store.py", "95\t45\tapp/routes/sessions.py", "28\t0\tapp/tm.py"],
    },
    "review-receipt:de814406-eb6f-48f8-9d4e-c1b9a78354ac": {
        "task": "499", "next_round": 3,
        "numstat": ["1\t1\tapp/routes/sessions.py", "31\t26\tapp/tm.py"],
    },
    "review-receipt:4e98ca5e-124e-42a5-b125-e47a36860715": {
        "task": "502", "next_round": 2, "numstat": ["6\t1\tapp/merge_operations.py"],
    },
    "review-receipt:c67246bf-b1e0-41ef-bdfb-2b73b2c62df0": {
        "task": "105", "next_round": 2,
        "artifact_evidence": "next verdict says all six previous findings are fixed and quotes canonical REFERENCE_ROOT",
    },
}


def artifact_task(row: dict) -> str:
    if row["task_id"]:
        return str(row["task_id"])
    match = re.search(r"/tasks/(\d+)/", row["artifact_path"])
    return match.group(1) if match else ""


def percentile(values: list[float], index: int) -> float | None:
    if not values:
        return None
    return statistics.quantiles(values, n=4, method="inclusive")[index]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    raw = json.loads(Path(args.input).read_text())
    reviews = raw["reviews"]

    measurable = []
    for row in reviews:
        if row["mode"] != "implementation" or not row["size"]["measurable"]:
            continue
        key = (artifact_task(row), int(row["round"] or 0))
        outcome = MEASURED_OUTCOMES[key]
        measurable.append({
            "task": key[0],
            "round": key[1],
            "lines": row["size"]["lines"],
            "files": row["size"]["files"],
            "outcome": outcome,
            "receipt_id": row["receipt_id"],
        })

    thresholds = []
    for lines, files in ((20, 1), (40, 3), (50, 3), (75, 3), (100, 3), (150, 3), (250, 5), (500, 5)):
        selected = [
            row for row in measurable
            if row["lines"] <= lines and row["files"] <= files and row["outcome"] != "unclassified"
        ]
        thresholds.append({
            "max_lines": lines,
            "max_files": files,
            "classified": len(selected),
            "outcomes": dict(Counter(row["outcome"] for row in selected)),
        })

    round_three = []
    for row in reviews:
        if row["round"] != 3:
            continue
        round_three.append({
            "task": artifact_task(row),
            "mode": row["mode"],
            "reviewer_model": row["reviewer_model"],
            "outcome": ROUND_THREE_OUTCOMES[row["receipt_id"]],
            "verdict": row["verdict_value"],
            "receipt_id": row["receipt_id"],
        })

    groups: dict[str, list[dict]] = defaultdict(list)
    for row in reviews:
        groups[row["artifact_path"]].append(row)
    followups = []
    for rows in groups.values():
        rows.sort(key=lambda row: row["requested_at"])
        prior_thread = ""
        for row in rows:
            usage = row["usage_rows"]
            thread = ""
            if usage:
                suffix = usage[-1]["event_id"][len(row["usage_event_id"]) + 1 :]
                thread = suffix.rsplit(":", 1)[0]
            if prior_thread and thread:
                kind = "resumed" if thread == prior_thread else "fresh"
                duration = (
                    datetime.fromisoformat(row["completed_at"])
                    - datetime.fromisoformat(row["requested_at"])
                ).total_seconds()
                followups.append({
                    "task": artifact_task(row),
                    "round": row["round"],
                    "kind": kind,
                    "duration_seconds": duration,
                    "thread": thread,
                    "prior_thread": prior_thread,
                })
            if thread:
                prior_thread = thread

    cross_model = [
        row for row in reviews
        if row["reviewer_model"] == "gpt-5.6-luna"
        and ("sol" in row["author_model"] or "opus" in row["author_model"])
    ]
    typed_cross_model = [row for row in cross_model if row["mode"] == "implementation"]
    usage_rows = [usage for row in reviews for usage in row["usage_rows"]]
    historical = raw["historical_review_usage"]
    result = {
        "snapshot": {
            key: raw[key]
            for key in (
                "extracted_at_utc",
                "database_max_review_requested_at",
                "database_max_review_usage_ts",
                "completed_review_receipts",
                "completed_receipts_with_prefix_usage",
            )
        },
        "threshold_population": {
            "completed_implementation_receipts": sum(row["mode"] == "implementation" for row in reviews),
            "production_paths_measurable": len(measurable),
            "outcomes": dict(Counter(row["outcome"] for row in measurable)),
            "candidate_thresholds": thresholds,
            "rows": measurable,
        },
        "round_three": {
            "total": len(round_three),
            "outcomes": dict(Counter(row["outcome"] for row in round_three)),
            "typed_implementation_outcomes": dict(Counter(
                row["outcome"] for row in round_three if row["mode"] == "implementation"
            )),
            "rows": round_three,
        },
        "resume": {
            "identity_classified_followups": len(followups),
            "counts": dict(Counter(row["kind"] for row in followups)),
            "resumed_median_seconds": statistics.median(
                row["duration_seconds"] for row in followups if row["kind"] == "resumed"
            ),
            "resumed_p75_seconds": percentile(
                [row["duration_seconds"] for row in followups if row["kind"] == "resumed"], 2
            ),
            "fresh_median_seconds": statistics.median(
                row["duration_seconds"] for row in followups if row["kind"] == "fresh"
            ),
            "fresh_p75_seconds": percentile(
                [row["duration_seconds"] for row in followups if row["kind"] == "fresh"], 2
            ),
            "rows": followups,
        },
        "usage": {
            "exact_join_matches": 0,
            "prefix_joined_completed_receipts": sum(bool(row["usage_rows"]) for row in reviews),
            "prefix_joined_usage_rows": len(usage_rows),
            "prefix_joined_input_tokens": sum(row["input_tokens"] for row in usage_rows),
            "prefix_joined_cache_read_tokens": sum(row["cache_read_tokens"] for row in usage_rows),
            "prefix_joined_output_tokens": sum(row["output_tokens"] for row in usage_rows),
            "prefix_joined_cost_usd": sum(row["cost_usd"] or 0 for row in usage_rows),
            "historical_rows": sum(row["runs"] for row in historical),
            "historical_input_tokens": sum(row["input_tokens"] for row in historical),
            "historical_cache_read_tokens": sum(row["cache_read_tokens"] for row in historical),
            "historical_output_tokens": sum(row["output_tokens"] for row in historical),
            "historical_cost_usd": sum(row["cost_usd"] or 0 for row in historical),
            "by_model": historical,
        },
        "cross_model_value": {
            "completed_luna_over_sol_or_opus": len(cross_model),
            "completed_typed_implementation_luna_over_sol_or_opus": len(typed_cross_model),
            "pinned_code_change_blocker_rounds": len(CROSS_MODEL_PINNED_CODE_CHANGE),
            "followup_supported_code_change_blocker_rounds": len(CROSS_MODEL_FOLLOWUP_SUPPORTED_CHANGE),
            "typed_implementation_pinned_code_change_blocker_rounds": sum(
                row["receipt_id"] in CROSS_MODEL_PINNED_CODE_CHANGE for row in typed_cross_model
            ),
            "pinned_code_change_tasks": sorted({
                artifact_task(row) for row in cross_model if row["receipt_id"] in CROSS_MODEL_PINNED_CODE_CHANGE
            }),
            "pinned_receipt_ids": sorted(CROSS_MODEL_PINNED_CODE_CHANGE),
            "followup_supported_receipt_ids": sorted(CROSS_MODEL_FOLLOWUP_SUPPORTED_CHANGE),
            "evidence": CROSS_MODEL_DELTA_EVIDENCE,
        },
    }
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
