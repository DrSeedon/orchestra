#!/usr/bin/env python3
"""Evaluate the preregistered #170 fixed-workload A/B gate from redacted rows."""

from __future__ import annotations

import hashlib
import json
import statistics
import sys
from pathlib import Path


TARGET_METRICS = ("repeated_reads", "tool_result_bytes")


def _median(values: list[float]) -> float:
    return float(statistics.median(values))


def _split_half_noise(rows: list[dict], metric: str) -> float:
    by_workload: dict[str, list[float]] = {}
    for row in rows:
        by_workload.setdefault(row["workload_id"], []).append(float(row[metric]))
    differences = []
    for values in by_workload.values():
        left = values[::2]
        right = values[1::2]
        if left and right:
            differences.append(abs(_median(left) - _median(right)))
    return _median(differences) if differences else float("inf")


def _paired_gain(baseline: list[dict], candidate: list[dict], metric: str) -> float:
    keyed = lambda rows: {
        (row["workload_id"], row["repetition"]): float(row[metric]) for row in rows
    }
    before, after = keyed(baseline), keyed(candidate)
    shared = sorted(before.keys() & after.keys())
    return _median([before[key] - after[key] for key in shared]) if shared else float("-inf")


def evaluate(spec: dict, runs: dict) -> dict:
    workloads = {item["id"]: item["input_hash"] for item in spec["workloads"]}
    for item in spec["workloads"]:
        actual = hashlib.sha256(item["redacted_contract"].encode()).hexdigest()
        if actual != item["input_hash"]:
            return {"verdict": "NO_CHANGE", "reason": f"fixture hash mismatch: {item['id']}"}
    baseline = runs.get("baseline_runs") or []
    candidate = runs.get("candidate_runs") or []
    minimum = int(spec["decision_rule"]["minimum_runs_per_arm"])
    expected = len(workloads) * minimum
    counts = {
        arm: {
            workload: sum(row.get("workload_id") == workload for row in rows)
            for workload in workloads
        }
        for arm, rows in (("baseline", baseline), ("candidate", candidate))
    }
    if any(
        count < minimum
        for arm_counts in counts.values()
        for count in arm_counts.values()
    ):
        return {
            "verdict": "NO_CHANGE",
            "reason": "insufficient_comparable_runs",
            "required_per_arm": expected,
            "baseline_runs": len(baseline),
            "candidate_runs": len(candidate),
            "counts": counts,
            "collection_status": runs.get("collection_status"),
        }
    for arm, rows in (("baseline", baseline), ("candidate", candidate)):
        for row in rows:
            if workloads.get(row.get("workload_id")) != row.get("input_hash"):
                return {"verdict": "NO_CHANGE", "reason": f"{arm} workload hash mismatch"}
            if row.get("correct") is not True or row.get("lost_work") is not False:
                return {"verdict": "NO_CHANGE", "reason": f"{arm} correctness/no-loss failed"}
    metrics = {}
    passes = []
    for metric in TARGET_METRICS:
        noise = _split_half_noise(baseline, metric)
        gain = _paired_gain(baseline, candidate, metric)
        metrics[metric] = {"baseline_noise": noise, "paired_gain": gain}
        passes.append(gain > noise)
    return {
        "verdict": "PASS" if any(passes) else "NO_CHANGE",
        "reason": "gain_exceeds_noise" if any(passes) else "gain_not_above_noise",
        "metrics": metrics,
    }


def main() -> int:
    root = Path(__file__).resolve().parent
    spec = json.loads((root / "t5-workloads.json").read_text())
    runs = json.loads((root / "t5-runs.json").read_text())
    json.dump(evaluate(spec, runs), sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
