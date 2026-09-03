#!/usr/bin/env python3
"""Reconcile #251 headless usage with xAI's published token and X-search rates."""

from __future__ import annotations

import collections
import json
from pathlib import Path


RAW = Path(__file__).parent / "raw"


def main() -> None:
    rows = []
    for path in sorted(RAW.glob("[ABC]-*.jsonl")):
        x_calls = 0
        x_batches = set()
        end = None
        for line in path.read_text(encoding="utf-8").splitlines():
            event = json.loads(line)
            if event.get("type") == "tool_call_update" and event.get("status") == "completed":
                raw = event.get("rawOutput") or {}
                if raw.get("name", "").startswith("x_"):
                    x_calls += 1
                    call_id = raw.get("call_id", "")
                    x_batches.add(call_id.rsplit("-", 1)[0] if call_id else "")
            elif event.get("type") == "end":
                end = event
        assert end is not None
        usage = next(iter(end["modelUsage"].values()))
        model = path.name.split("-")[1] + "-" + path.name.split("-")[2]
        cache_rate = 0.30 if model == "grok-4.5" else 0.50
        prompt_tokens = usage["inputTokens"] + usage["cacheReadInputTokens"]
        multiplier = 2 if prompt_tokens >= 200_000 else 1
        token_cost = multiplier * (
            usage["inputTokens"] * 2
            + usage["cacheReadInputTokens"] * cache_rate
            + usage["outputTokens"] * 6
        ) / 1_000_000
        expected = token_cost + x_calls * 0.005
        observed = float(usage["costUSD"])
        rows.append({
            "run": path.stem,
            "prompt_tokens": prompt_tokens,
            "tariff_multiplier": multiplier,
            "completed_x_calls": x_calls,
            "x_call_batches": len(x_batches),
            "reported_model_calls": usage["modelCalls"],
            "expected_cost_if_every_completed_x_call_is_billable": round(expected, 10),
            "reported_cost": observed,
            "residual_reported_minus_expected": round(observed - expected, 10),
        })
    residuals = collections.Counter(row["residual_reported_minus_expected"] for row in rows)
    result = {
        "rows": rows,
        "summary": {
            "runs": len(rows),
            "reported_model_calls": sum(row["reported_model_calls"] for row in rows),
            "x_call_batches": sum(row["x_call_batches"] for row in rows),
            "completed_x_calls": sum(row["completed_x_calls"] for row in rows),
            "reported_cost": round(sum(row["reported_cost"] for row in rows), 10),
            "expected_cost_if_every_completed_x_call_is_billable": round(
                sum(row["expected_cost_if_every_completed_x_call_is_billable"] for row in rows), 10
            ),
            "residuals": {str(key): value for key, value in residuals.items()},
        },
        "interpretation_limit": (
            "An X call-id batch is not documented as a modelCall. The single -$0.05 residual "
            "proves disagreement with the published per-completed-call formula, but without "
            "an exact account billing delta it does not prove whether the trace omitted spend "
            "or the first ten completed searches were non-billable."
        ),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
