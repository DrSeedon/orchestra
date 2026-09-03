#!/usr/bin/env python3
"""Reproduce #262 from a SQLite backup capped by measurement-inputs.json."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sqlite3
import statistics
import uuid
from datetime import datetime, timezone
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
INPUTS = json.loads((HERE / "measurement-inputs.json").read_text())


def as_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def api_equivalent(row: dict) -> float | None:
    prices = INPUTS["prices_per_million_usd"].get(row["model"])
    if prices is None:
        return None
    if row["runtime"] == "claude":
        return (
            row["input_tokens"] * prices["input"]
            + row["cache_read_tokens"] * prices["input"] * 0.1
            + row["cache_create_tokens"] * prices["input"] * 1.25
            + row["output_tokens"] * prices["output"]
        ) / 1_000_000
    if row["runtime"] == "codex":
        cached = min(max(0, row["cache_read_tokens"]), max(0, row["input_tokens"]))
        written = min(
            max(0, row["cache_create_tokens"]),
            max(0, row["input_tokens"] - cached),
        )
        fresh = max(0, row["input_tokens"] - cached - written)
        return (
            fresh * prices["input"]
            + cached * prices["cached"]
            + written * prices["write"]
            + max(0, row["output_tokens"]) * prices["output"]
        ) / 1_000_000
    return None


def window(payload: str, bucket: str, window_id: str):
    provider = json.loads(payload).get(bucket)
    if not provider:
        return None
    for item in provider.get("windows") or []:
        if item.get("id") == window_id and item.get("utilization") is not None:
            return float(item["utilization"]), item.get("resets_at")
    return None


def split_segments(points, drop_pp: float):
    result, current, peak = [], [], -math.inf
    for point in points:
        if current and peak - point[1] >= drop_pp:
            result.append(current)
            current, peak = [], -math.inf
        current.append(point)
        peak = max(peak, point[1])
    if current:
        result.append(current)
    return result


def segment_stats(segment):
    minimum = min(point[1] for point in segment)
    baseline = [point for point in segment if point[1] == minimum][-1]
    positive = sum(
        max(0.0, right[1] - left[1])
        for left, right in zip(segment, segment[1:])
    )
    return {
        "start": segment[0][0],
        "end": segment[-1][0],
        "baseline_at": baseline[0],
        "baseline_pct": baseline[1],
        "last_pct": segment[-1][1],
        "range_pp": max(point[1] for point in segment) - minimum,
        "raw_positive_pp": positive,
        "reset_ids": {point[2] for point in segment if point[2]},
    }


def end_record(path: Path) -> dict:
    result = None
    for line in path.read_text().splitlines():
        row = json.loads(line)
        if row.get("type") == "end":
            result = row
    if result is None:
        raise ValueError(f"No end record in {path}")
    return result


def uuid7_time(value: str) -> datetime:
    raw = uuid.UUID(value).hex
    return datetime.fromtimestamp(int(raw[:12], 16) / 1000, timezone.utc)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("db", type=Path)
    args = parser.parse_args()

    frozen = INPUTS["snapshot"]
    if sha256(args.db) != frozen["sha256"]:
        raise SystemExit("snapshot SHA256 differs from measurement-inputs.json")

    source_revision = INPUTS["source_revision"]
    source_hashes = {
        ROOT / "app/models.py": source_revision["app_models_sha256"],
        ROOT / "app/backend_codex.py": source_revision["app_backend_codex_sha256"],
        ROOT / INPUTS["grok"]["score_path"]: INPUTS["grok"]["score_sha256"],
        ROOT / "docs/tasks/249/research.md": INPUTS["antigravity"]["source_sha256"],
    }
    source_hashes.update(zip(
        (ROOT / path for path in INPUTS["grok"]["pilot_paths"]),
        INPUTS["grok"]["pilot_sha256"],
    ))
    for path, expected_hash in source_hashes.items():
        if sha256(path) != expected_hash:
            raise SystemExit(f"source SHA256 differs from manifest: {path}")

    connection = sqlite3.connect(args.db)
    connection.row_factory = sqlite3.Row
    assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    all_turns = [
        dict(row) for row in connection.execute(
            "SELECT * FROM turn_usage WHERE id <= ? ORDER BY ts, id",
            (frozen["turn_usage_max_id"],),
        )
    ]
    snapshots = list(connection.execute(
        "SELECT id, ts, provider_usage FROM usage_snapshots "
        "WHERE id <= ? ORDER BY ts, id",
        (frozen["usage_snapshots_max_id"],),
    ))
    assert len(all_turns) == frozen["turn_usage_rows"]
    assert len(snapshots) == frozen["usage_snapshots_rows"]

    excluded = [
        row for row in all_turns
        if row["scope"] == "/test" or row["session_id"].startswith("test-")
    ]
    assert len(excluded) == INPUTS["test_row_exclusion"]["expected_rows"]
    turns = [row for row in all_turns if row not in excluded]
    print("DENOMINATORS")
    print(json.dumps({
        "excluded_test_rows": len(excluded),
        "excluded_recorded_cost": sum(float(row["cost_usd"] or 0) for row in excluded),
        "production_rows": len(turns),
    }, sort_keys=True))

    print("\nTURN_ECONOMICS")
    for runtime in ("claude", "codex"):
        rows = [row for row in turns if row["runtime"] == runtime]
        usage_rows = [
            row for row in rows
            if float(row["cost_usd"] or 0) > 0
            or row["input_tokens"] > 0
            or row["output_tokens"] > 0
            or row["cache_read_tokens"] > 0
        ]
        costs = [api_equivalent(row) for row in rows]
        assert all(cost is not None for cost in costs)
        span_days = (
            as_utc(usage_rows[-1]["ts"]) - as_utc(usage_rows[0]["ts"])
        ).total_seconds() / 86400
        print(json.dumps({
            "runtime": runtime,
            "terminal_rows": len(rows),
            "usage_rows": len(usage_rows),
            "first_usage": usage_rows[0]["ts"],
            "last_usage": usage_rows[-1]["ts"],
            "active_utc_days": len({row["ts"][:10] for row in usage_rows}),
            "span_days": span_days,
            "mean": statistics.mean(costs),
            "median": statistics.median(costs),
            "sum": sum(costs),
            "per_7d": sum(costs) * 7 / span_days,
            "cache_le_input": sum(
                row["cache_read_tokens"] <= row["input_tokens"] for row in rows
            ),
            "cache_gt_input": sum(
                row["cache_read_tokens"] > row["input_tokens"] for row in rows
            ),
        }, sort_keys=True))

    quota = {}
    for bucket, window_id, threshold in (
        ("anthropic", "seven_day", 5.0),
        ("anthropic", "five_hour", 5.0),
        ("codex", "primary", 10.0),
        ("codex_spark", "primary", 10.0),
        ("grok", "primary", 10.0),
    ):
        points = []
        for row in snapshots:
            found = window(row["provider_usage"], bucket, window_id)
            if found:
                points.append((as_utc(row["ts"]), found[0], found[1]))
        quota[(bucket, window_id)] = [
            segment_stats(item) for item in split_segments(points, threshold)
        ]

    print("\nPOOL_API_EQ")
    runtime_for = {"anthropic": "claude", "codex": "codex"}
    full_pools = {"anthropic": [], "codex": []}
    for bucket, window_id in (("anthropic", "seven_day"), ("codex", "primary")):
        for index, segment in enumerate(quota[(bucket, window_id)], 1):
            delta = segment["last_pct"] - segment["baseline_pct"]
            rows = [
                row for row in turns
                if row["runtime"] == runtime_for[bucket]
                and segment["baseline_at"] <= as_utc(row["ts"]) <= segment["end"]
            ]
            costs = [api_equivalent(row) for row in rows]
            costs = [cost for cost in costs if cost is not None]
            full_pool_api_eq = sum(costs) * 100 / delta if delta else None
            full_pools[bucket].append(full_pool_api_eq)
            print(json.dumps({
                "bucket": bucket,
                "segment": index,
                "baseline_at": segment["baseline_at"].isoformat(),
                "end": segment["end"].isoformat(),
                "delta_pp": delta,
                "turns": len(rows),
                "api_eq": sum(costs),
                "full_pool_api_eq": full_pool_api_eq,
                "raw_positive_pp": segment["raw_positive_pp"],
                "range_pp": segment["range_pp"],
            }, sort_keys=True))

    print("\nCURRENT_RUNWAY")
    now = as_utc(snapshots[-1]["ts"])
    for bucket, window_id in (
        ("anthropic", "seven_day"),
        ("anthropic", "five_hour"),
        ("codex", "primary"),
        ("grok", "primary"),
    ):
        item = quota[(bucket, window_id)][-1]
        elapsed = (now - item["baseline_at"]).total_seconds() / 3600
        delta = item["last_pct"] - item["baseline_pct"]
        pace = delta / elapsed if elapsed and delta > 0 else None
        print(json.dumps({
            "bucket": bucket,
            "window": window_id,
            "current_pct": item["last_pct"],
            "elapsed_hours": elapsed,
            "pace_pp_hour": pace,
            "eta_hours": (100 - item["last_pct"]) / pace if pace else None,
        }, sort_keys=True))

    grok = INPUTS["grok"]
    score = json.loads((ROOT / grok["score_path"]).read_text())
    grok_costs = [float(row["cost_usd"]) for row in score["rows"]]
    pilot_ends = [end_record(ROOT / path) for path in grok["pilot_paths"]]
    grok_costs += [float(row["total_cost_usd"]) for row in pilot_ends]
    print("\nGROK")
    print(json.dumps({
        "n": len(grok_costs),
        "mean": statistics.mean(grok_costs),
        "median": statistics.median(grok_costs),
        "sum": sum(grok_costs),
        "pilot_start_min": min(uuid7_time(row["sessionId"]) for row in pilot_ends).isoformat(),
        "full_pool_if_4pp": sum(grok_costs) * 25,
        "full_pool_if_5pp": sum(grok_costs) * 20,
    }, sort_keys=True))

    antigravity = INPUTS["antigravity"]
    prices = INPUTS["prices_per_million_usd"]["gemini-3.6-flash"]
    fresh = antigravity["input_tokens"] - antigravity["cache_read_tokens"]
    ag_cost = (
        fresh * prices["input"]
        + antigravity["cache_read_tokens"] * prices["cached"]
        + antigravity["output_tokens"] * prices["output"]
    ) / 1_000_000
    consumed = 100 * (
        antigravity["remaining_before"] - antigravity["remaining_after"]
    )
    print("\nANTIGRAVITY")
    print(json.dumps({
        "n": antigravity["results"],
        "sum": ag_cost,
        "mean": ag_cost / antigravity["results"],
        "consumed_pp": consumed,
        "full_pool_api_eq": ag_cost * 100 / consumed,
        "full_pool_results": antigravity["results"] * 100 / consumed,
        "cache_subset": (
            antigravity["input_tokens"] + antigravity["output_tokens"]
            == antigravity["total_tokens"]
        ),
    }, sort_keys=True))

    weeks_per_month = 365.2425 / 12 / 7
    subscriptions = INPUTS["subscriptions"]
    claude_completed = full_pools["anthropic"][1]
    claude_current = full_pools["anthropic"][-1]
    codex_recent = full_pools["codex"][-3:]
    grok_full_pools = [sum(grok_costs) * 20, sum(grok_costs) * 25]
    jio_total_usd = (
        subscriptions["jio_acquisition_rub_total"]
        / subscriptions["cbr_rub_per_usd_2026_08_13"]
    )
    print("\nSUBSCRIPTION_ECONOMICS")
    print(json.dumps({
        "weeks_per_month": weeks_per_month,
        "claude_completed": {
            "weekly_api_eq": claude_completed,
            "monthly_api_eq": claude_completed * weeks_per_month,
            "api_eq_per_subscription_usd": (
                claude_completed * weeks_per_month
                / subscriptions["claude_usd_month"]
            ),
        },
        "claude_current_provisional": {
            "weekly_api_eq": claude_current,
            "monthly_api_eq": claude_current * weeks_per_month,
            "api_eq_per_subscription_usd": (
                claude_current * weeks_per_month
                / subscriptions["claude_usd_month"]
            ),
        },
        "codex_main_recent_range": {
            "weekly_api_eq": [min(codex_recent), max(codex_recent)],
            "monthly_api_eq": [
                min(codex_recent) * weeks_per_month,
                max(codex_recent) * weeks_per_month,
            ],
            "api_eq_per_subscription_usd": [
                min(codex_recent) * weeks_per_month
                / subscriptions["codex_usd_month"],
                max(codex_recent) * weeks_per_month
                / subscriptions["codex_usd_month"],
            ],
        },
        "grok_conditional_range": {
            "weekly_api_eq": [min(grok_full_pools), max(grok_full_pools)],
            "monthly_api_eq": [
                min(grok_full_pools) * weeks_per_month,
                max(grok_full_pools) * weeks_per_month,
            ],
            "api_eq_per_subscription_usd": [
                min(grok_full_pools) * weeks_per_month
                / subscriptions["grok_usd_month"],
                max(grok_full_pools) * weeks_per_month
                / subscriptions["grok_usd_month"],
            ],
        },
        "antigravity_unknown_tier": {
            "weekly_api_eq": ag_cost * 100 / consumed,
            "monthly_api_eq": ag_cost * 100 / consumed * weeks_per_month,
            "api_eq_per_subscription_usd": None,
        },
        "jio_acquisition": {
            "usd_total": jio_total_usd,
            "usd_month_amortized": (
                jio_total_usd / subscriptions["jio_offer_months"]
            ),
            "api_eq_per_subscription_usd": None,
        },
    }, sort_keys=True))

    print("\nPHYSICAL_CHECKS")
    claude = quota[("anthropic", "seven_day")]
    grok_segments = quota[("grok", "primary")]
    print(json.dumps({
        "claude_calendar_windows": 3,
        "claude_observed_pp": sum(item["range_pp"] for item in claude),
        "claude_independent_ceiling_pp": 300,
        "grok_distinct_reset_ids": len(set().union(*(item["reset_ids"] for item in grok_segments))),
        "grok_observed_pp": sum(item["range_pp"] for item in grok_segments),
        "grok_independent_ceiling_pp": 100,
        "antigravity_observed_pp": consumed,
        "antigravity_independent_ceiling_pp": 100,
        "codex_independent_ceiling": None,
        "codex_reason": "reset-credit consumption is not persisted",
        "codex_raw_positive_pp": sum(
            item["raw_positive_pp"] for item in quota[("codex", "primary")]
        ),
        "codex_range_pp": sum(
            item["range_pp"] for item in quota[("codex", "primary")]
        ),
    }, sort_keys=True))
    connection.close()


if __name__ == "__main__":
    main()
