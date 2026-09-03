#!/usr/bin/env python3
"""Mechanically verify the pilot runner's recorded A/B interleaving."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path


ARMS = ("append", "state", "append_repeat")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", required=True)
    parser.add_argument("--cases", required=True)
    args = parser.parse_args()
    summary = json.loads(Path(args.summary).read_text(encoding="utf-8"))
    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))["cases"]
    order = summary["request_order"]
    sequences = [row["sequence"] for row in order]
    contiguous = sequences == list(range(1, len(sequences) + 1))
    grouped: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for row in order:
        grouped[(row["case_id"], int(row["step"]))].append(row)
    checks = []
    for case_index, case in enumerate(cases):
        for step in range(1, len(case["observations"]) + 1):
            rows = grouped.get((case["case_id"], step), [])
            labels = [row["arm"] for row in rows]
            if "append" not in labels or "state" not in labels:
                continue
            rotation = (case_index + step - 1) % len(ARMS)
            expected = ARMS[rotation:] + ARMS[:rotation]
            expected_primary = [arm for arm in expected if arm in ("append", "state")]
            actual_primary = [arm for arm in labels if arm in ("append", "state")]
            checks.append({
                "case_id": case["case_id"],
                "step": step,
                "expected_primary_order": expected_primary,
                "actual_primary_order": actual_primary,
                "ok": actual_primary == expected_primary,
            })
    result = {
        "schema": "skillstate430-order-audit-v1",
        "summary": args.summary,
        "requests": len(order),
        "sequence_contiguous": contiguous,
        "request_count_by_arm": dict(Counter(row["arm"] for row in order)),
        "comparable_step_order_checks": checks,
        "all_comparable_steps_follow_rotating_ab_order": contiguous and all(row["ok"] for row in checks),
        "rendered_surface_hashes_captured": False,
        "rendered_surface_gap": "pilot raw did not record system/action-schema/tool/controller hashes; full benchmark must fail preflight without them",
    }
    if not result["all_comparable_steps_follow_rotating_ab_order"]:
        raise RuntimeError(json.dumps(result, ensure_ascii=False))
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
