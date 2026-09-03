#!/usr/bin/env python3
"""Build the sanitized #285 telemetry evidence from a WAL-safe SQLite backup."""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import socket
import sqlite3
import statistics
import subprocess
import urllib.request


UTC = dt.timezone.utc
THRESHOLDS = (80, 90, 95, 100)
GAP_BREAK_SECONDS = 900.0
YESTERDAY_START = "2026-08-15T00:00:00+00:00"
YESTERDAY_END = "2026-08-16T00:00:00+00:00"


def parse_ts(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def iso_now() -> str:
    return dt.datetime.now(UTC).isoformat()


def quantile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    point = (len(ordered) - 1) * fraction
    lower = math.floor(point)
    upper = math.ceil(point)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (point - lower)


def rounded(value: float | None, digits: int = 6) -> float | None:
    return None if value is None else round(value, digits)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def command(*args: str) -> str:
    return subprocess.run(
        args, check=True, text=True, stdout=subprocess.PIPE
    ).stdout.strip()


def valid_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def reset_cycle(reset_at: str | None, window_minutes: int) -> str | None:
    """Canonical cycle label; removes provider sub-second jitter only."""
    if not reset_at:
        return None
    value = parse_ts(reset_at)
    if window_minutes >= 1440:
        return value.date().isoformat()
    # Session reset timestamps fluctuate around :59.5/:00.5. Nearest minute keeps
    # those observations in one cycle while retaining each actual 5h anchor.
    value += dt.timedelta(seconds=30)
    return value.replace(second=0, microsecond=0).isoformat()


def normalized_observations(connection: sqlite3.Connection) -> list[dict]:
    observations: list[dict] = []
    rows = connection.execute(
        "SELECT id, ts, five_hour_pct, seven_day_pct, five_hour_resets_at, "
        "seven_day_resets_at, provider_usage FROM usage_snapshots ORDER BY ts, id"
    )
    for row in rows:
        providers = json.loads(row["provider_usage"] or "{}")
        seen: set[tuple[str, str]] = set()
        for provider, payload in providers.items():
            if not isinstance(payload, dict):
                continue
            for window in payload.get("windows") or []:
                utilization = window.get("utilization")
                minutes = window.get("window_minutes")
                window_id = window.get("id")
                if (
                    not valid_number(utilization)
                    or not isinstance(minutes, int)
                    or minutes <= 0
                    or not isinstance(window_id, str)
                ):
                    continue
                observations.append({
                    "row_id": row["id"],
                    "ts": row["ts"],
                    "provider": provider,
                    "window_id": window_id,
                    "window_minutes": minutes,
                    "utilization": float(utilization),
                    "resets_at": window.get("resets_at"),
                    "plan_type": payload.get("plan_type"),
                    "origin": "provider_usage",
                })
                seen.add((provider, window_id))

        fake_legacy_zero = (
            row["five_hour_pct"] == 0
            and row["seven_day_pct"] == 0
            and not (row["five_hour_resets_at"] or "")
            and not (row["seven_day_resets_at"] or "")
        )
        if fake_legacy_zero:
            continue
        for window_id, pct_key, reset_key, minutes in (
            ("five_hour", "five_hour_pct", "five_hour_resets_at", 300),
            ("seven_day", "seven_day_pct", "seven_day_resets_at", 10080),
        ):
            if ("anthropic", window_id) in seen or row[pct_key] is None:
                continue
            observations.append({
                "row_id": row["id"],
                "ts": row["ts"],
                "provider": "anthropic",
                "window_id": window_id,
                "window_minutes": minutes,
                "utilization": float(row[pct_key]),
                "resets_at": row[reset_key] or None,
                "plan_type": None,
                "origin": "legacy_column",
            })
    observations.sort(key=lambda item: (item["ts"], item["row_id"], item["provider"], item["window_id"]))
    return observations


def group_observations(observations: list[dict]) -> dict[tuple[str, str], list[dict]]:
    grouped: dict[tuple[str, str], list[dict]] = collections.defaultdict(list)
    for observation in observations:
        grouped[(observation["provider"], observation["window_id"])].append(observation)
    return dict(grouped)


def latest_observations(grouped: dict[tuple[str, str], list[dict]]) -> list[dict]:
    result = []
    for (provider, window_id), rows in sorted(grouped.items()):
        row = rows[-1]
        result.append({key: row[key] for key in (
            "row_id", "ts", "provider", "window_id", "window_minutes",
            "utilization", "resets_at", "plan_type", "origin",
        )})
    return result


def reset_events(grouped: dict[tuple[str, str], list[dict]]) -> list[dict]:
    events: dict[tuple[str, str, int, int], dict] = {}
    for (provider, window_id), rows in sorted(grouped.items()):
        for before, after in zip(rows, rows[1:]):
            drop = before["utilization"] - after["utilization"]
            if drop < 20:
                continue
            key = (provider, window_id, before["row_id"], after["row_id"])
            events[key] = {
                "provider": provider,
                "window_id": window_id,
                "window_minutes": before["window_minutes"],
                "reasons": ["drop_gte_20pp"],
                "drop_pp": round(drop, 6),
                "gap_seconds": rounded((parse_ts(after["ts"]) - parse_ts(before["ts"])).total_seconds()),
                "before": source_quota_row(before),
                "after": source_quota_row(after),
            }

        prior_with_reset: dict | None = None
        for current in rows:
            current_cycle = reset_cycle(current["resets_at"], current["window_minutes"])
            if current_cycle is None:
                continue
            if prior_with_reset is not None:
                prior_cycle = reset_cycle(
                    prior_with_reset["resets_at"], prior_with_reset["window_minutes"]
                )
                if current_cycle != prior_cycle:
                    key = (
                        provider, window_id,
                        prior_with_reset["row_id"], current["row_id"],
                    )
                    event = events.setdefault(key, {
                        "provider": provider,
                        "window_id": window_id,
                        "window_minutes": current["window_minutes"],
                        "reasons": [],
                        "drop_pp": round(
                            prior_with_reset["utilization"] - current["utilization"], 6
                        ),
                        "gap_seconds": rounded(
                            (parse_ts(current["ts"]) - parse_ts(prior_with_reset["ts"])).total_seconds()
                        ),
                        "before": source_quota_row(prior_with_reset),
                        "after": source_quota_row(current),
                    })
                    event["reasons"].append("reset_cycle_changed")
                    event["reset_cycle_before"] = prior_cycle
                    event["reset_cycle_after"] = current_cycle
                    event["reset_delta_seconds"] = rounded(
                        (parse_ts(current["resets_at"]) - parse_ts(prior_with_reset["resets_at"])).total_seconds()
                    )
            prior_with_reset = current

    return sorted(events.values(), key=lambda item: (
        item["after"]["ts"], item["provider"], item["window_id"], item["before"]["row_id"]
    ))


def source_quota_row(row: dict) -> dict:
    return {key: row[key] for key in (
        "row_id", "ts", "utilization", "resets_at", "plan_type", "origin",
    )}


def threshold_segments(grouped: dict[tuple[str, str], list[dict]]) -> list[dict]:
    result: list[dict] = []
    for (provider, window_id), rows in sorted(grouped.items()):
        for threshold in THRESHOLDS:
            current: dict | None = None
            for index, row in enumerate(rows):
                next_row = rows[index + 1] if index + 1 < len(rows) else None
                qualifies = row["utilization"] >= threshold
                if qualifies and current is None:
                    current = {
                        "provider": provider,
                        "window_id": window_id,
                        "window_minutes": row["window_minutes"],
                        "threshold_pct": threshold,
                        "start_ts_inclusive": row["ts"],
                        "start_row_id": row["row_id"],
                        "last_qualifying_row_id": row["row_id"],
                        "end_ts_exclusive": row["ts"],
                        "end_boundary_row_id": None,
                        "observation_count": 0,
                        "min_utilization": row["utilization"],
                        "max_utilization": row["utilization"],
                        "observed_duration_seconds": 0.0,
                        "open_at_snapshot_end": False,
                        "ended_by_gap_gt_900s": False,
                    }
                if qualifies and current is not None:
                    current["last_qualifying_row_id"] = row["row_id"]
                    current["observation_count"] += 1
                    current["min_utilization"] = min(current["min_utilization"], row["utilization"])
                    current["max_utilization"] = max(current["max_utilization"], row["utilization"])

                    if next_row is None:
                        current["end_ts_exclusive"] = row["ts"]
                        current["open_at_snapshot_end"] = True
                        result.append(current)
                        current = None
                        continue

                    gap = (parse_ts(next_row["ts"]) - parse_ts(row["ts"])).total_seconds()
                    if gap > GAP_BREAK_SECONDS:
                        current["end_ts_exclusive"] = row["ts"]
                        current["ended_by_gap_gt_900s"] = True
                        result.append(current)
                        current = None
                        continue

                    current["observed_duration_seconds"] += gap
                    current["end_ts_exclusive"] = next_row["ts"]
                    current["end_boundary_row_id"] = next_row["row_id"]
                    if next_row["utilization"] < threshold:
                        result.append(current)
                        current = None

            if current is not None:
                result.append(current)

    for segment in result:
        segment["observed_duration_seconds"] = rounded(segment["observed_duration_seconds"])
    return result


def cadence(rows: list[dict], *, top_n: int = 5) -> dict:
    gaps = []
    for before, after in zip(rows, rows[1:]):
        seconds = (parse_ts(after["ts"]) - parse_ts(before["ts"])).total_seconds()
        gaps.append((seconds, before, after))
    values = [item[0] for item in gaps]
    largest = sorted(gaps, key=lambda item: item[0], reverse=True)[:top_n]
    return {
        "observation_count": len(rows),
        "first_ts": rows[0]["ts"] if rows else None,
        "last_ts": rows[-1]["ts"] if rows else None,
        "median_seconds": rounded(quantile(values, 0.5)),
        "p95_seconds": rounded(quantile(values, 0.95)),
        "max_seconds": rounded(max(values) if values else None),
        "gaps_gt_600s": sum(value > 600 for value in values),
        "gaps_gt_900s": sum(value > 900 for value in values),
        "gaps_gt_1800s": sum(value > 1800 for value in values),
        "largest_gaps": [{
            "seconds": rounded(seconds),
            "before_row_id": before["row_id"],
            "before_ts": before["ts"],
            "after_row_id": after["row_id"],
            "after_ts": after["ts"],
        } for seconds, before, after in largest],
    }


def aggregate_turn_rows(rows: list[sqlite3.Row]) -> dict:
    costs = [row["cost_usd"] for row in rows if row["cost_usd"] is not None]
    return {
        "rows": len(rows),
        "ok_rows": sum(row["ok"] for row in rows),
        "error_rows": sum(not row["ok"] for row in rows),
        "cost_accounted_rows": len(costs),
        "cost_unaccounted_rows": sum(row["cost_unaccounted"] for row in rows),
        "cost_usd_sum": rounded(sum(costs)),
        "input_tokens": sum(row["input_tokens"] for row in rows),
        "output_tokens": sum(row["output_tokens"] for row in rows),
        "cache_read_tokens": sum(row["cache_read_tokens"] for row in rows),
        "cache_create_tokens": sum(row["cache_create_tokens"] for row in rows),
        "first_ts": min((row["ts"] for row in rows), default=None),
        "last_ts": max((row["ts"] for row in rows), default=None),
    }


def turn_aggregates(connection: sqlite3.Connection) -> dict:
    predicate = "NOT (scope = '/test' OR session_id LIKE 'test-%')"
    all_rows = list(connection.execute(f"SELECT * FROM turn_usage WHERE {predicate} ORDER BY ts, id"))
    grouped: dict[tuple[str, str], list[sqlite3.Row]] = collections.defaultdict(list)
    yesterday: dict[tuple[str, str], list[sqlite3.Row]] = collections.defaultdict(list)
    for row in all_rows:
        grouped[(row["runtime"], row["model"])].append(row)
        if YESTERDAY_START <= row["ts"] < YESTERDAY_END:
            yesterday[(row["runtime"], row["model"])].append(row)

    all_output = []
    for (runtime, model), rows in sorted(grouped.items()):
        all_output.append({"runtime": runtime, "model": model, **aggregate_turn_rows(rows)})
    yesterday_output = []
    for (runtime, model), rows in sorted(yesterday.items()):
        yesterday_output.append({"runtime": runtime, "model": model, **aggregate_turn_rows(rows)})

    claude_yesterday = [row for row in all_rows if (
        row["runtime"] == "claude" and YESTERDAY_START <= row["ts"] < YESTERDAY_END
    )]
    fable_rows = [row for row in claude_yesterday if "fable" in row["model"].lower()]
    opus_rows = [row for row in claude_yesterday if "opus" in row["model"].lower()]

    sampling = []
    for runtime in sorted({row["runtime"] for row in all_rows}):
        runtime_rows = [row for row in all_rows if row["runtime"] == runtime]
        ages = [
            (parse_ts(row["ts"]) - parse_ts(row["quota_sampled_at"])).total_seconds()
            for row in runtime_rows if row["quota_sampled_at"]
        ]
        sampling.append({
            "runtime": runtime,
            "rows": len(runtime_rows),
            "quota_sampled_at_nonnull": len(ages),
            "quota_sampled_at_null": len(runtime_rows) - len(ages),
            "age_seconds_min": rounded(min(ages) if ages else None),
            "age_seconds_median": rounded(quantile(ages, 0.5)),
            "age_seconds_p95": rounded(quantile(ages, 0.95)),
            "age_seconds_max": rounded(max(ages) if ages else None),
            "negative_age_rows": sum(value < 0 for value in ages),
            "five_hour_pct_nonnull": sum(row["quota_five_hour_pct"] is not None for row in runtime_rows),
            "seven_day_pct_nonnull": sum(row["quota_seven_day_pct"] is not None for row in runtime_rows),
            "primary_pct_nonnull": sum(row["quota_primary_pct"] is not None for row in runtime_rows),
        })

    return {
        "production_filter": predicate,
        "all_production_by_runtime_model": all_output,
        "yesterday_utc": {
            "start_inclusive": YESTERDAY_START,
            "end_exclusive": YESTERDAY_END,
            "by_runtime_model": yesterday_output,
            "claude_fable": aggregate_turn_rows(fable_rows),
            "claude_opus": aggregate_turn_rows(opus_rows),
        },
        "quota_sampling_age_at_turn_end": sampling,
    }


def test_filter_measurement(connection: sqlite3.Connection) -> dict:
    row = connection.execute(
        "SELECT COUNT(*) AS total, "
        "SUM(CASE WHEN scope = '/test' THEN 1 ELSE 0 END) AS scope_test, "
        "SUM(CASE WHEN session_id LIKE 'test-%' THEN 1 ELSE 0 END) AS session_test, "
        "SUM(CASE WHEN scope = '/test' OR session_id LIKE 'test-%' THEN 1 ELSE 0 END) AS excluded "
        "FROM turn_usage"
    ).fetchone()
    return {
        "predicate": "scope = '/test' OR session_id LIKE 'test-%'",
        "total_rows": row["total"],
        "scope_test_rows": row["scope_test"],
        "session_id_test_rows": row["session_test"],
        "excluded_union_rows": row["excluded"],
        "retained_rows": row["total"] - row["excluded"],
    }


def rounding_measurement(connection: sqlite3.Connection, observations: list[dict]) -> dict:
    legacy = {}
    for column in ("five_hour_pct", "seven_day_pct"):
        values = [row[0] for row in connection.execute(
            f"SELECT {column} FROM usage_snapshots WHERE {column} IS NOT NULL"
        )]
        legacy[column] = {
            "nonnull": len(values),
            "null": connection.execute(
                f"SELECT COUNT(*) FROM usage_snapshots WHERE {column} IS NULL"
            ).fetchone()[0],
            "zero": sum(value == 0 for value in values),
            "integer_valued": sum(float(value).is_integer() for value in values),
            "fractional": sum(not float(value).is_integer() for value in values),
        }
    return {
        "legacy_columns": legacy,
        "normalized_provider_windows": {
            "observations": len(observations),
            "integer_valued": sum(item["utilization"].is_integer() for item in observations),
            "fractional": sum(not item["utilization"].is_integer() for item in observations),
            "zero": sum(item["utilization"] == 0 for item in observations),
        },
    }


def active_sessions(connection: sqlite3.Connection) -> list[dict]:
    return [dict(row) for row in connection.execute(
        "SELECT backend_type, model, status, COUNT(*) AS rows, "
        "SUM(CASE WHEN active_turn_id != '' THEN 1 ELSE 0 END) AS active_turn_id_nonempty "
        "FROM sessions WHERE status IN ('running', 'starting') OR active_turn_id != '' "
        "GROUP BY backend_type, model, status ORDER BY backend_type, model, status"
    )]


def live_usage(url: str | None) -> dict:
    if not url:
        return {"queried": False}
    token = os.environ.get("INTERNAL_TOKEN")
    if not token:
        return {"queried": False, "reason": "INTERNAL_TOKEN absent"}
    started = iso_now()
    request = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {token}"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = json.load(response)
        status = response.status
    completed = iso_now()

    anthropic = raw.get("anthropic") or {}
    limits = []
    for limit in anthropic.get("limits") or []:
        scope = limit.get("scope")
        model_display_name = None
        model_id_is_null = None
        surface = None
        if isinstance(scope, dict):
            model = scope.get("model")
            if isinstance(model, dict):
                model_display_name = model.get("display_name")
                model_id_is_null = model.get("id") is None
            surface = scope.get("surface")
        limits.append({
            "kind": limit.get("kind"),
            "group": limit.get("group"),
            "is_active": limit.get("is_active"),
            "percent": limit.get("percent"),
            "resets_at": limit.get("resets_at"),
            "severity": limit.get("severity"),
            "scope_model_display_name": model_display_name,
            "scope_model_id_is_null": model_id_is_null,
            "scope_surface": surface,
        })
    extra = anthropic.get("extra_usage") or {}

    codex = raw.get("codex") or {}
    credits = codex.get("credits") or {}
    spark = codex.get("spark") or {}
    return {
        "queried": True,
        "url": url,
        "http_status": status,
        "request_started_at_utc": started,
        "response_completed_at_utc": completed,
        "response_has_observed_at": "observed_at" in raw,
        "anthropic": {
            "five_hour": sanitized_window(anthropic.get("five_hour")),
            "seven_day": sanitized_window(anthropic.get("seven_day")),
            "limits": limits,
            "extra_usage": {
                "is_enabled": extra.get("is_enabled"),
                "spend_limit_reached": extra.get("spend_limit_reached"),
                "used_credits": extra.get("used_credits"),
                "utilization": extra.get("utilization"),
                "monthly_limit_present": extra.get("monthly_limit") is not None,
                "monthly_limit_value_omitted": True,
            },
        },
        "codex": {
            "plan_type": codex.get("plan_type"),
            "primary": sanitized_window(codex.get("primary")),
            "secondary": sanitized_window(codex.get("secondary")),
            "credits": {
                "has_credits": credits.get("has_credits"),
                "unlimited": credits.get("unlimited"),
                "balance_is_null": credits.get("balance") is None,
                "balance_value_omitted": credits.get("balance") is not None,
            },
            "reset_credits": codex.get("reset_credits"),
            "spark": {
                "limit_id": spark.get("limit_id"),
                "plan_type": spark.get("plan_type"),
                "primary": sanitized_window(spark.get("primary")),
                "secondary": sanitized_window(spark.get("secondary")),
            },
        },
    }


def sanitized_window(value: object) -> dict | None:
    if not isinstance(value, dict):
        return None
    return {key: value.get(key) for key in (
        "utilization", "window_minutes", "resets_at",
    )}


def codex_transition(
    connection: sqlite3.Connection,
    grouped: dict[tuple[str, str], list[dict]],
) -> dict:
    primary = grouped.get(("codex", "primary"), [])
    transition_index = None
    prior_plan = None
    for index, row in enumerate(primary):
        plan = row["plan_type"]
        if plan == "pro" and prior_plan == "prolite":
            transition_index = index
            break
        if plan is not None:
            prior_plan = plan
    if transition_index is None:
        return {"found": False, "from": "prolite", "to": "pro"}

    transition_row = primary[transition_index]
    ids = [row["row_id"] for row in primary[
        max(0, transition_index - 3): transition_index + 4
    ]]
    source_rows = []
    for row_id in ids:
        snapshot = connection.execute(
            "SELECT id, ts, provider_usage FROM usage_snapshots WHERE id = ?", (row_id,)
        ).fetchone()
        providers = json.loads(snapshot["provider_usage"] or "{}")
        selected = {"row_id": snapshot["id"], "ts": snapshot["ts"]}
        for provider in ("codex", "codex_spark"):
            payload = providers.get(provider) or {}
            window = next(
                (item for item in payload.get("windows") or [] if item.get("id") == "primary"),
                None,
            )
            selected[provider] = {
                "plan_type": payload.get("plan_type"),
                "primary": sanitized_window(window),
            }
        source_rows.append(selected)

    center = parse_ts(transition_row["ts"])
    start = (center - dt.timedelta(hours=1)).isoformat()
    end = (center + dt.timedelta(hours=1)).isoformat()
    turns = [dict(row) for row in connection.execute(
        "SELECT id AS row_id, ts, runtime, model, ok, stop_reason, cost_usd, "
        "cost_unaccounted, input_tokens, output_tokens, cache_read_tokens, "
        "cache_create_tokens, quota_primary_pct, quota_sampled_at "
        "FROM turn_usage WHERE ts >= ? AND ts < ? "
        "AND NOT (scope = '/test' OR session_id LIKE 'test-%') ORDER BY ts, id",
        (start, end),
    )]
    return {
        "found": True,
        "from": "prolite",
        "to": "pro",
        "first_pro_row_id": transition_row["row_id"],
        "first_pro_ts": transition_row["ts"],
        "snapshot_rows": source_rows,
        "turn_window": {"start_inclusive": start, "end_exclusive": end},
        "turn_rows": turns,
    }


def table_inventory(connection: sqlite3.Connection) -> dict:
    inventory = {}
    for table in ("usage_snapshots", "turn_usage"):
        row = connection.execute(
            f"SELECT COUNT(*) AS rows, MIN(id) AS min_id, MAX(id) AS max_id, "
            f"MIN(ts) AS first_ts, MAX(ts) AS last_ts FROM {table}"
        ).fetchone()
        inventory[table] = dict(row)
    inventory["sessions"] = {
        "rows": connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    }
    return inventory


def build_markdown(evidence: dict) -> str:
    inventory = evidence["contour_inventory"]
    tables = inventory["frozen_backup"]["tables"]
    latest = evidence["quota_observations"]["frozen_latest"]
    live = evidence["quota_observations"]["live_endpoint"]
    turns = evidence["turn_aggregates"]["yesterday_utc"]
    transition = evidence["codex_prolite_to_pro"]
    reset_summary = evidence["reset_or_drop_events"]["summary"]
    threshold_summary = evidence["threshold_intervals"]["summary"]
    quality = evidence["coverage_cadence_gaps_test_row_filtering"]

    lines = [
        "# #285 telemetry evidence slice",
        "",
        "All timestamps are UTC. This file contains source rows and measurements only.",
        "",
        "## Contour inventory",
        "",
        f"- Host: `{inventory['host']}`; contour label: `{inventory['contour_label']}`.",
        f"- Live SQLite source resolved to `{inventory['source_db']['realpath']}` on "
        f"`{inventory['source_db']['filesystem_type']}` (`{inventory['source_db']['size_bytes']}` bytes at stat time).",
        f"- Frozen backup: SQLite `backup()` from URI `mode=ro`; `PRAGMA quick_check={inventory['frozen_backup']['quick_check']}`; "
        f"SHA-256 `{inventory['frozen_backup']['sha256']}`.",
        f"- `usage_snapshots`: {tables['usage_snapshots']['rows']} rows, "
        f"{tables['usage_snapshots']['first_ts']} to {tables['usage_snapshots']['last_ts']}.",
        f"- `turn_usage`: {tables['turn_usage']['rows']} rows, "
        f"{tables['turn_usage']['first_ts']} to {tables['turn_usage']['last_ts']}.",
        "",
        "## Quota observations",
        "",
        "| source | provider | window | utilization | resets_at | plan | row/time |",
        "|---|---|---|---:|---|---|---|",
    ]
    for row in latest:
        lines.append(
            f"| frozen SQLite | {row['provider']} | {row['window_id']} | {row['utilization']} | "
            f"{row['resets_at']} | {row['plan_type']} | {row['row_id']} / {row['ts']} |"
        )
    if live.get("queried"):
        for provider, window_name, window, plan in (
            ("anthropic", "five_hour", live["anthropic"]["five_hour"], None),
            ("anthropic", "seven_day", live["anthropic"]["seven_day"], None),
            ("codex", "primary", live["codex"]["primary"], live["codex"]["plan_type"]),
            ("codex_spark", "primary", live["codex"]["spark"]["primary"], live["codex"]["spark"]["plan_type"]),
        ):
            if window is None:
                continue
            lines.append(
                f"| authenticated GET /api/usage | {provider} | {window_name} | "
                f"{window['utilization']} | {window['resets_at']} | {plan} | "
                f"response completed {live['response_completed_at_utc']} |"
            )

    fable_limit = next((item for item in live.get("anthropic", {}).get("limits", [])
                        if item.get("kind") == "weekly_scoped"), None)
    weekly_limit = next((item for item in live.get("anthropic", {}).get("limits", [])
                         if item.get("kind") == "weekly_all"), None)
    lines += [
        "",
        "## Claude weekly-all and scoped Fable evidence",
        "",
        f"- Live `weekly_all`: `{json.dumps(weekly_limit, sort_keys=True)}`.",
        f"- Live `weekly_scoped`: `{json.dumps(fable_limit, sort_keys=True)}`.",
        f"- 2026-08-15 UTC completed Claude Fable rows: {turns['claude_fable']['rows']}; "
        f"Opus rows: {turns['claude_opus']['rows']}.",
        f"- Persisted normalized `weekly_scoped` observations: "
        f"{evidence['claude_scoped_fable']['persisted_weekly_scoped_observations']}; "
        f"recent persisted `weekly_all >=100` intervals: "
        f"{len(evidence['claude_scoped_fable']['recent_weekly_all_100_intervals'])}.",
        f"- Frozen backup running/starting session groups: `{json.dumps(evidence['claude_scoped_fable']['in_flight_session_groups'], sort_keys=True)}`.",
        f"- Turn quota-sample age rows: `{json.dumps(evidence['turn_aggregates']['quota_sampling_age_at_turn_end'], sort_keys=True)}`.",
        f"- Live endpoint cache TTL in `app/routes/system.py`: {evidence['claude_scoped_fable']['staleness_and_precision']['usage_cache_ttl_seconds']} seconds; "
        f"live response exposes `observed_at`: {live.get('response_has_observed_at')}.",
        f"- Persisted utilization precision counts: `{json.dumps(quality['rounding_and_null_zero'], sort_keys=True)}`.",
        f"- Sanitized credit states: `{json.dumps(evidence['claude_scoped_fable']['usage_credit_states'], sort_keys=True)}`.",
        "",
        "## Codex prolite to pro source rows",
        "",
        f"First `pro` row after `prolite`: id `{transition.get('first_pro_row_id')}`, "
        f"timestamp `{transition.get('first_pro_ts')}`.",
        "",
        "| id | ts | main plan/util/reset | Spark plan/util/reset |",
        "|---:|---|---|---|",
    ]
    for row in transition.get("snapshot_rows", []):
        main = row["codex"]
        spark = row["codex_spark"]
        lines.append(
            f"| {row['row_id']} | {row['ts']} | {main['plan_type']} / "
            f"{(main['primary'] or {}).get('utilization')} / {(main['primary'] or {}).get('resets_at')} | "
            f"{spark['plan_type']} / {(spark['primary'] or {}).get('utilization')} / "
            f"{(spark['primary'] or {}).get('resets_at')} |"
        )

    lines += [
        "",
        "## Reset/drop events",
        "",
        f"Candidate rule: adjacent drop >=20 pp OR canonical reset cycle change. "
        f"Counts: `{json.dumps(reset_summary, sort_keys=True)}`.",
        "Raw source rows for every candidate are in `evidence.json`.",
        "",
        "## Threshold intervals",
        "",
        "Step convention: observation `i` applies on `[ts_i, ts_(i+1))`; intervals break rather than carry across gaps >900 seconds; no duration is extrapolated after the final observation.",
        "",
        "| provider/window | threshold | intervals | observed seconds |",
        "|---|---:|---:|---:|",
    ]
    for row in threshold_summary:
        lines.append(
            f"| {row['provider']}/{row['window_id']} | {row['threshold_pct']} | "
            f"{row['intervals']} | {row['observed_duration_seconds']} |"
        )

    lines += [
        "",
        "## Turn aggregates",
        "",
        "The production predicate is `NOT (scope = '/test' OR session_id LIKE 'test-%')`.",
        "",
        "| period | runtime | model | rows | ok | cost USD | input | output | cache read | cache create |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for period, rows in (
        ("all frozen", evidence["turn_aggregates"]["all_production_by_runtime_model"]),
        ("2026-08-15 UTC", turns["by_runtime_model"]),
    ):
        for row in rows:
            lines.append(
                f"| {period} | {row['runtime']} | {row['model']} | {row['rows']} | "
                f"{row['ok_rows']} | {row['cost_usd_sum']} | {row['input_tokens']} | "
                f"{row['output_tokens']} | {row['cache_read_tokens']} | {row['cache_create_tokens']} |"
            )

    cadence_all = quality["cadence"]["usage_snapshots_all_rows"]
    lines += [
        "",
        "## Coverage, cadence, gaps, filtering",
        "",
        f"- All-snapshot cadence: median {cadence_all['median_seconds']} s, p95 "
        f"{cadence_all['p95_seconds']} s, max {cadence_all['max_seconds']} s; "
        f">900 s gaps: {cadence_all['gaps_gt_900s']}.",
        f"- Test-row filter measurement: `{json.dumps(quality['test_row_filtering'], sort_keys=True)}`.",
        f"- Event-id duplicate measurement: {quality['duplicate_event_ids']} duplicate ids.",
        "- Per-window cadence, largest source-row gaps, NULL/zero counts, all threshold intervals, all reset candidates, and transition-adjacent turn rows are in `evidence.json`.",
        "",
        "## Reproduction commands",
        "",
        "```bash",
        *evidence["commands"],
        "```",
        "",
        "The collector reads the auth token only from `INTERNAL_TOKEN`, sanitizes the live response in memory, omits subscription cost and account/payment fields, and never writes the raw endpoint response.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--source-path", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-md", type=Path, required=True)
    parser.add_argument("--live-url")
    args = parser.parse_args()

    db_path = args.db.resolve()
    source_path = args.source_path.resolve()
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    quick_check = connection.execute("PRAGMA quick_check").fetchone()[0]
    observations = normalized_observations(connection)
    grouped = group_observations(observations)
    live = live_usage(args.live_url)
    thresholds = threshold_segments(grouped)
    resets = reset_events(grouped)

    source_stat = source_path.stat()
    filesystem = command("findmnt", "-no", "FSTYPE", "--target", str(source_path))
    all_snapshot_rows = [
        {"row_id": row["id"], "ts": row["ts"]}
        for row in connection.execute("SELECT id, ts FROM usage_snapshots ORDER BY ts, id")
    ]
    per_window_cadence = []
    for (provider, window_id), rows in sorted(grouped.items()):
        per_window_cadence.append({
            "provider": provider,
            "window_id": window_id,
            **cadence(rows),
        })

    reset_counts: dict[tuple[str, str], dict] = collections.defaultdict(
        lambda: {"events": 0, "drop_gte_20pp": 0, "reset_cycle_changed": 0}
    )
    for event in resets:
        count = reset_counts[(event["provider"], event["window_id"])]
        count["events"] += 1
        for reason in event["reasons"]:
            count[reason] += 1
    reset_summary = [
        {"provider": key[0], "window_id": key[1], **value}
        for key, value in sorted(reset_counts.items())
    ]

    threshold_counts: dict[tuple[str, str, int], dict] = collections.defaultdict(
        lambda: {"intervals": 0, "observed_duration_seconds": 0.0}
    )
    for segment in thresholds:
        key = (segment["provider"], segment["window_id"], segment["threshold_pct"])
        count = threshold_counts[key]
        count["intervals"] += 1
        count["observed_duration_seconds"] += segment["observed_duration_seconds"]
    threshold_summary = [
        {
            "provider": key[0], "window_id": key[1], "threshold_pct": key[2],
            "intervals": value["intervals"],
            "observed_duration_seconds": rounded(value["observed_duration_seconds"]),
        }
        for key, value in sorted(threshold_counts.items())
    ]

    transition = codex_transition(connection, grouped)
    turns = turn_aggregates(connection)
    recent_weekly_all_100 = [
        segment for segment in thresholds
        if segment["provider"] == "anthropic"
        and segment["window_id"] == "seven_day"
        and segment["threshold_pct"] == 100
    ][-4:]
    live_extra = live.get("anthropic", {}).get("extra_usage")
    live_codex_credits = live.get("codex", {}).get("credits")
    live_reset_credits = live.get("codex", {}).get("reset_credits")
    evidence = {
        "schema_version": "285.telemetry.v1",
        "generated_at_utc": iso_now(),
        "contour_inventory": {
            "host": socket.gethostname(),
            "contour_label": "local VPS checkout",
            "worktree": str(Path.cwd()),
            "git_commit": command("git", "rev-parse", "HEAD"),
            "source_db": {
                "requested_path": str(args.source_path),
                "realpath": str(source_path),
                "size_bytes": source_stat.st_size,
                "mtime_utc": dt.datetime.fromtimestamp(source_stat.st_mtime, UTC).isoformat(),
                "filesystem_type": filesystem,
            },
            "frozen_backup": {
                "method": "sqlite3.Connection.backup from source URI mode=ro",
                "scratch_path_not_committed": str(args.db),
                "size_bytes": db_path.stat().st_size,
                "mtime_utc": dt.datetime.fromtimestamp(db_path.stat().st_mtime, UTC).isoformat(),
                "sha256": sha256(db_path),
                "quick_check": quick_check,
                "tables": table_inventory(connection),
            },
        },
        "quota_observations": {
            "frozen_latest": latest_observations(grouped),
            "live_endpoint": live,
        },
        "reset_or_drop_events": {
            "candidate_rule": "adjacent utilization drop >=20pp OR canonical reset timestamp cycle changes between consecutive non-NULL resets",
            "reset_cycle_canonicalization": "weekly windows: UTC reset date; sub-day windows: reset timestamp rounded to nearest minute",
            "summary": reset_summary,
            "events": resets,
        },
        "threshold_intervals": {
            "thresholds_pct": list(THRESHOLDS),
            "comparison": "utilization >= threshold",
            "step_convention": "left endpoint hold: observation i applies on [ts_i, ts_(i+1))",
            "gap_break_seconds": GAP_BREAK_SECONDS,
            "snapshot_end_extrapolation": False,
            "summary": threshold_summary,
            "intervals": thresholds,
        },
        "turn_aggregates": turns,
        "codex_prolite_to_pro": transition,
        "claude_scoped_fable": {
            "live_weekly_all": next((item for item in live.get("anthropic", {}).get("limits", [])
                                     if item.get("kind") == "weekly_all"), None),
            "live_weekly_scoped": next((item for item in live.get("anthropic", {}).get("limits", [])
                                        if item.get("kind") == "weekly_scoped"), None),
            "yesterday_actual_turns": {
                "period_start_inclusive": YESTERDAY_START,
                "period_end_exclusive": YESTERDAY_END,
                "fable": turns["yesterday_utc"]["claude_fable"],
                "opus": turns["yesterday_utc"]["claude_opus"],
            },
            "persisted_weekly_scoped_observations": sum(
                item["provider"] == "anthropic" and item["window_id"] == "weekly_scoped"
                for item in observations
            ),
            "recent_weekly_all_100_intervals": recent_weekly_all_100,
            "in_flight_session_groups": active_sessions(connection),
            "staleness_and_precision": {
                "usage_cache_ttl_seconds": 300,
                "source": "app/routes/system.py:_USAGE_CACHE_TTL",
                "live_response_has_observed_at": live.get("response_has_observed_at"),
                "turn_quota_sampling_age": turns["quota_sampling_age_at_turn_end"],
                "rounding_measurement": rounding_measurement(connection, observations),
            },
            "usage_credit_states": {
                "anthropic_extra_usage": live_extra,
                "codex_credits": live_codex_credits,
                "codex_reset_credits": live_reset_credits,
            },
        },
        "coverage_cadence_gaps_test_row_filtering": {
            "cadence": {
                "usage_snapshots_all_rows": cadence(all_snapshot_rows, top_n=10),
                "per_provider_window": per_window_cadence,
            },
            "rounding_and_null_zero": rounding_measurement(connection, observations),
            "test_row_filtering": test_filter_measurement(connection),
            "duplicate_event_ids": connection.execute(
                "SELECT COUNT(*) FROM (SELECT event_id FROM turn_usage GROUP BY event_id HAVING COUNT(*) > 1)"
            ).fetchone()[0],
        },
        "commands": [
            "python3 - <<'PY'  # WAL-safe backup; exact body is below",
            "import sqlite3",
            "src = sqlite3.connect('file:/home/kesha/orchestra/data/orchestra.db?mode=ro', uri=True)",
            "dst = sqlite3.connect('docs/tasks/285/parts/telemetry/.scratch-live.db')",
            "src.backup(dst)",
            "dst.close(); src.close()",
            "PY",
            "python3 docs/tasks/285/parts/telemetry/collect.py --db docs/tasks/285/parts/telemetry/.scratch-live.db --source-path /home/kesha/orchestra/data/orchestra.db --output-json docs/tasks/285/parts/telemetry/evidence.json --output-md docs/tasks/285/parts/telemetry/evidence.md --live-url http://127.0.0.1:8888/api/usage",
            "rm -- docs/tasks/285/parts/telemetry/.scratch-live.db",
        ],
    }
    args.output_json.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    args.output_md.write_text(build_markdown(evidence))


if __name__ == "__main__":
    main()
