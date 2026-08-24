#!/usr/bin/env python3
"""Aggregate provider-emitted usage and mechanical acceptance for valid #346 Luna runs."""

from __future__ import annotations

import argparse
import json
import re
import statistics
from collections import Counter
from pathlib import Path
from typing import Any


def elapsed_seconds(text: str) -> float | None:
    match = re.search(r"Elapsed \(wall clock\) time .*?:\s*([0-9:.]+)", text)
    if not match:
        return None
    value = match.group(1)
    parts = [float(part) for part in value.split(":")]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return parts[0]


def acceptance(text: str) -> dict[str, Any]:
    values = {key: int(value) for key, value in re.findall(r"^([A-Z0-9_]+_EXIT)=([0-9]+)$", text, re.M)}
    e1 = (
        values.get("E1_OLD_SYMBOL_EXIT") == 1
        and values.get("E1_NEW_DEF_EXIT") == 0
        and values.get("E1_ALIAS_EXIT") == 0
        and values.get("E1_TESTS_EXIT") == 0
        and values.get("DIFF_CHECK_EXIT") == 0
    )
    e2 = (
        values.get("E2_OLD_SYMBOL_EXIT") == 1
        and values.get("E2_NEW_DEF_EXIT") == 0
        and values.get("E2_REPORT_GUARD_EXIT") == 0
        and values.get("E2_TESTS_EXIT") == 0
        and values.get("DIFF_CHECK_EXIT") == 0
    )
    return {"raw_exit_codes": values, "e1": e1, "e2": e2, "accepted": int(e1) + int(e2)}


def run_row(raw: Path, run: str, arm: str) -> dict[str, Any]:
    events = [json.loads(line) for line in (raw / f"luna-{run}.jsonl").read_text().splitlines() if line.strip()]
    completed = [event["item"] for event in events if event.get("type") == "item.completed"]
    item_types = Counter(str(item.get("type")) for item in completed)
    tool_types = {"command_execution", "file_change", "mcp_tool_call", "web_search"}
    tool_calls = sum(count for name, count in item_types.items() if name in tool_types)
    turn = next(event for event in reversed(events) if event.get("type") == "turn.completed")
    usage = turn["usage"]
    acceptance_row = acceptance((raw / f"luna-{run}-acceptance.txt").read_text())
    metadata = (raw / f"luna-{run}-metadata.txt").read_text()
    codex_exit = int(re.search(r"^codex_exit=(\d+)$", metadata, re.M).group(1))
    stderr = (raw / f"luna-{run}.stderr").read_text()
    diffstat = (raw / f"luna-{run}-diffstat.txt").read_text()
    return {
        "run": run,
        "arm": arm,
        "codex_exit": codex_exit,
        "acceptance": acceptance_row,
        "item_types": dict(sorted(item_types.items())),
        "tool_calls": tool_calls,
        "mcp_tool_calls": item_types.get("mcp_tool_call", 0),
        "input_tokens": usage["input_tokens"],
        "cached_input_tokens": usage["cached_input_tokens"],
        "cache_write_input_tokens": usage.get("cache_write_input_tokens", 0),
        "output_tokens": usage["output_tokens"],
        "reasoning_output_tokens": usage.get("reasoning_output_tokens", 0),
        "cache_le_input": usage["cached_input_tokens"] <= usage["input_tokens"],
        "wall_seconds": elapsed_seconds(stderr),
        "diffstat": diffstat,
    }


def median_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    keys = [
        "tool_calls", "mcp_tool_calls", "input_tokens", "cached_input_tokens",
        "output_tokens", "reasoning_output_tokens", "wall_seconds",
    ]
    result = {key: statistics.median(row[key] for row in rows) for key in keys}
    result["runs"] = len(rows)
    result["accepted_tasks"] = sum(row["acceptance"]["accepted"] for row in rows)
    result["possible_tasks"] = len(rows) * 2
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", required=True)
    args = parser.parse_args()
    raw = Path(args.raw)
    specs = [
        ("a1-valid", "A"), ("b1-valid", "B"), ("a2-valid", "A"), ("b2-valid", "B"),
        ("a3-valid", "A"), ("c1-valid", "C"), ("a4-valid", "A"), ("c2-valid", "C"),
    ]
    rows = [run_row(raw, run, arm) for run, arm in specs]
    groups = {arm: [row for row in rows if row["arm"] == arm] for arm in "ABC"}
    out = {
        "runs": rows,
        "groups": {arm: median_rows(group) for arm, group in groups.items()},
        "paired_deltas": {
            "B_minus_A": [
                {key: b[key] - a[key] for key in ("tool_calls", "input_tokens", "cached_input_tokens", "output_tokens", "wall_seconds")}
                for a, b in ((rows[0], rows[1]), (rows[2], rows[3]))
            ],
            "C_minus_A": [
                {key: c[key] - a[key] for key in ("tool_calls", "input_tokens", "cached_input_tokens", "output_tokens", "wall_seconds")}
                for a, c in ((rows[4], rows[5]), (rows[6], rows[7]))
            ],
        },
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

