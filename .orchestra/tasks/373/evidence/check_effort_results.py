#!/usr/bin/env python3
"""Mechanical check for the frozen #373 effort experiment."""

import json
import statistics
from pathlib import Path


path = Path(__file__).with_name("effort-results.json")
data = json.loads(path.read_text())
rows = data["rows"]

assert data["meta"]["order"] == ["high", "high", "high", "xhigh", "high", "xhigh"]
assert data["meta"]["sequential"] is True
assert len(rows) == 6
assert all(row["status"] == "completed" for row in rows)
assert all(row["grade"]["score"] == row["grade"]["total"] == 14 for row in rows)
assert all(len(row["grade"]["items"]) == 14 for row in rows)
assert all(all(row["grade"]["items"].values()) for row in rows)
assert len({row["final_sha256"] for row in rows}) == 1

aa = rows[:2]
confirm = rows[2:]
assert all(row["phase"] == "aa_noise" and row["effort"] == "high" for row in aa)
assert [row["effort"] for row in confirm] == ["high", "xhigh", "high", "xhigh"]


def median(effort, field):
    selected = [row for row in confirm if row["effort"] == effort]
    if field == "total_ms":
        return statistics.median(row[field] for row in selected)
    return statistics.median(row["usage"][field] for row in selected)


summary = {
    "aa_wall_range_ms": max(row["total_ms"] for row in aa) - min(row["total_ms"] for row in aa),
    "high": {
        "score": 14,
        "total_ms": median("high", "total_ms"),
        "input_tokens": median("high", "input_tokens"),
        "cached_input_tokens": median("high", "cached_input_tokens"),
        "output_tokens": median("high", "output_tokens"),
        "reasoning_output_tokens": median("high", "reasoning_output_tokens"),
    },
    "xhigh": {
        "score": 14,
        "total_ms": median("xhigh", "total_ms"),
        "input_tokens": median("xhigh", "input_tokens"),
        "cached_input_tokens": median("xhigh", "cached_input_tokens"),
        "output_tokens": median("xhigh", "output_tokens"),
        "reasoning_output_tokens": median("xhigh", "reasoning_output_tokens"),
    },
}
summary["quality_delta_xhigh_minus_high"] = summary["xhigh"]["score"] - summary["high"]["score"]
summary["frozen_gate_supports_xhigh"] = summary["quality_delta_xhigh_minus_high"] >= 2
assert summary["frozen_gate_supports_xhigh"] is False
print(json.dumps(summary, ensure_ascii=False, indent=2))
