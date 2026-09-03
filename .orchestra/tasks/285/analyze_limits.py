#!/usr/bin/env python3
"""Reproduce #285 quota metrics from a WAL-safe SQLite backup.

The input must be a finished ``sqlite3.Connection.backup`` destination, never the
live database file.  The output intentionally excludes log/message bodies.
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


UTC = timezone.utc
MAX_CONTIGUOUS_GAP_SECONDS = 15 * 60
THRESHOLDS = (80, 90, 95, 100)


def parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def iso(value: datetime | None) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value else None


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * q
    lo, hi = math.floor(index), math.ceil(index)
    if lo == hi:
        return ordered[lo]
    return ordered[lo] * (hi - index) + ordered[hi] * (index - lo)


def table_range(db: sqlite3.Connection, table: str, ts_col: str = "ts") -> dict[str, Any]:
    row = db.execute(
        f"SELECT count(*) n, min({ts_col}) first_ts, max({ts_col}) last_ts FROM {table}"
    ).fetchone()
    return {"rows": row["n"], "first_ts": row["first_ts"], "last_ts": row["last_ts"]}


def extract_series(db: sqlite3.Connection) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    rows = db.execute(
        "SELECT id, ts, five_hour_pct, seven_day_pct, five_hour_resets_at, "
        "seven_day_resets_at, provider_usage FROM usage_snapshots ORDER BY id"
    ).fetchall()
    series: dict[str, list[dict[str, Any]]] = defaultdict(list)
    provider_counts: Counter[str] = Counter()
    ambiguous_legacy_zero_rows = 0
    normalized_unavailable: Counter[str] = Counter()
    cadence_seconds: list[float] = []
    previous_ts: datetime | None = None

    for row in rows:
        at = parse_ts(row["ts"])
        if previous_ts and at:
            cadence_seconds.append((at - previous_ts).total_seconds())
        previous_ts = at
        try:
            providers = json.loads(row["provider_usage"] or "{}")
        except json.JSONDecodeError:
            providers = {}

        for provider in providers:
            provider_counts[provider] += 1

        anthropic = providers.get("anthropic")
        if isinstance(anthropic, dict) and anthropic.get("status") == "unavailable":
            normalized_unavailable["anthropic"] += 1
        elif isinstance(anthropic, dict):
            for window in anthropic.get("windows") or []:
                if window.get("id") not in {"five_hour", "seven_day"}:
                    continue
                used = window.get("utilization")
                if isinstance(used, (int, float)) and not isinstance(used, bool):
                    series[f"claude.{window['id']}"] .append({
                        "snapshot_id": row["id"], "ts": row["ts"],
                        "utilization": float(used), "resets_at": window.get("resets_at"),
                        "plan": "max", "quality": "normalized_provider_payload",
                    })
        else:
            # Before provider payloads existed, a simultaneous 0/0 cannot be
            # distinguished from a collector failure (#150).  Preserve the gap.
            five, seven = row["five_hour_pct"], row["seven_day_pct"]
            if not providers and five == 0 and seven == 0:
                ambiguous_legacy_zero_rows += 1
            else:
                for key, used, reset in (
                    ("claude.five_hour", five, row["five_hour_resets_at"]),
                    ("claude.seven_day", seven, row["seven_day_resets_at"]),
                ):
                    if isinstance(used, (int, float)):
                        series[key].append({
                            "snapshot_id": row["id"], "ts": row["ts"],
                            "utilization": float(used), "resets_at": reset,
                            "plan": "max", "quality": "legacy_columns",
                        })

        for provider_id, key in (("codex", "codex.primary"), ("codex_spark", "codex.spark"), ("grok", "grok.weekly")):
            provider = providers.get(provider_id)
            if isinstance(provider, dict) and provider.get("status") == "unavailable":
                normalized_unavailable[provider_id] += 1
                continue
            if not isinstance(provider, dict):
                continue
            windows = provider.get("windows") or []
            for window in windows:
                if window.get("id") != "primary":
                    continue
                used = window.get("utilization")
                if isinstance(used, (int, float)) and not isinstance(used, bool):
                    series[key].append({
                        "snapshot_id": row["id"], "ts": row["ts"],
                        "utilization": float(used), "resets_at": window.get("resets_at"),
                        "plan": provider.get("plan_type"),
                        "quality": "normalized_provider_payload",
                    })

    cadence = {
        "median_seconds": round(statistics.median(cadence_seconds), 3) if cadence_seconds else None,
        "p95_seconds": round(percentile(cadence_seconds, 0.95), 3) if cadence_seconds else None,
        "max_seconds": round(max(cadence_seconds), 3) if cadence_seconds else None,
        "gaps_gt_1h": sum(v > 3600 for v in cadence_seconds),
        "gaps_gt_6h": sum(v > 21600 for v in cadence_seconds),
        "crossing_resolution_note": "Threshold/reset times are bounded by adjacent snapshots; they are not exact event times.",
    }
    quality = {
        "provider_payload_rows": dict(provider_counts),
        "normalized_unavailable_rows": dict(normalized_unavailable),
        "ambiguous_legacy_double_zero_rows_excluded": ambiguous_legacy_zero_rows,
        "continuous_gap_cutoff_seconds": MAX_CONTIGUOUS_GAP_SECONDS,
    }
    return dict(series), {"cadence": cadence, "quality": quality}


def threshold_metrics(points: list[dict[str, Any]]) -> dict[str, Any]:
    parsed = [(parse_ts(p["ts"]), p) for p in points]
    parsed = [(t, p) for t, p in parsed if t]
    result: dict[str, Any] = {}
    for threshold in THRESHOLDS:
        known_seconds = 0.0
        blocks: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None
        for index, (at, point) in enumerate(parsed):
            previous_at, previous = parsed[index - 1] if index else (None, None)
            gap = (at - previous_at).total_seconds() if previous_at else None
            above = point["utilization"] >= threshold
            contiguous = bool(
                previous_at and gap is not None and gap <= MAX_CONTIGUOUS_GAP_SECONDS
                and previous and previous["utilization"] >= threshold
                and previous.get("plan") == point.get("plan")
            )
            if above and not contiguous:
                if current:
                    blocks.append(current)
                current = {
                    "first_observed_at": iso(at),
                    "last_confirmed_at": iso(at),
                    "duration_lower_bound_seconds": 0.0,
                    "entry_interval": {
                        "after": iso(previous_at),
                        "at_or_before": iso(at),
                    },
                    "plan": point.get("plan"),
                }
            elif above and current:
                current["last_confirmed_at"] = iso(at)
                current["duration_lower_bound_seconds"] += gap or 0
                known_seconds += gap or 0
            elif current:
                current["exit_interval"] = {"after": current["last_confirmed_at"], "at_or_before": iso(at)}
                blocks.append(current)
                current = None
        if current:
            current["open_at_snapshot_end"] = True
            blocks.append(current)
        result[str(threshold)] = {
            "known_duration_seconds": round(known_seconds, 3),
            "known_duration_hours": round(known_seconds / 3600, 3),
            "block_count": len(blocks),
            "longest_block_lower_bound_seconds": round(max((b["duration_lower_bound_seconds"] for b in blocks), default=0), 3),
            "blocks": blocks,
        }
    return result


def reset_events(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for before, after in zip(points, points[1:]):
        old_u, new_u = before["utilization"], after["utilization"]
        old_reset, new_reset = parse_ts(before.get("resets_at")), parse_ts(after.get("resets_at"))
        before_at, after_at = parse_ts(before["ts"]), parse_ts(after["ts"])
        plan_change = before.get("plan") != after.get("plan")
        drop = old_u - new_u
        anchor_shift_h = None
        if old_reset and new_reset:
            anchor_shift_h = (new_reset - old_reset).total_seconds() / 3600
        scheduled_crossing = bool(old_reset and before_at and after_at and before_at <= old_reset <= after_at)
        if not plan_change and drop < 20 and not (anchor_shift_h is not None and abs(anchor_shift_h) >= 6):
            continue
        if plan_change:
            kind = "plan_change_or_capacity_rescale"
        elif scheduled_crossing and drop >= 20:
            kind = "scheduled_reset_observed"
        elif drop >= 20 and anchor_shift_h is not None and abs(anchor_shift_h) >= 6:
            kind = "unscheduled_drop_with_anchor_shift"
        elif drop >= 20:
            kind = "counter_drop_same_or_unknown_anchor"
        else:
            kind = "reset_anchor_drift_without_large_drop"
        events.append({
            "interval_after": before["ts"], "interval_at_or_before": after["ts"],
            "kind": kind, "before_utilization": old_u, "after_utilization": new_u,
            "before_plan": before.get("plan"), "after_plan": after.get("plan"),
            "before_resets_at": before.get("resets_at"), "after_resets_at": after.get("resets_at"),
            "reset_anchor_shift_hours": round(anchor_shift_h, 3) if anchor_shift_h is not None else None,
        })
    return events


def compact_points(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep threshold/plan/reset changes plus one heartbeat per hour."""
    kept: list[dict[str, Any]] = []
    last_hour: str | None = None
    previous: dict[str, Any] | None = None
    raw_gap_since_keep = False

    def band(point: dict[str, Any]) -> int:
        value = point["utilization"]
        return 100 if value >= 100 else 95 if value >= 95 else 90 if value >= 90 else 80 if value >= 80 else 0

    for point in points:
        if previous:
            before, after = parse_ts(previous["ts"]), parse_ts(point["ts"])
            if before and after and (after - before).total_seconds() > MAX_CONTIGUOUS_GAP_SECONDS:
                raw_gap_since_keep = True
        hour = point["ts"][:13]
        old_reset = parse_ts(previous.get("resets_at")) if previous else None
        new_reset = parse_ts(point.get("resets_at"))
        reset_changed_materially = bool(
            old_reset and new_reset and abs((new_reset - old_reset).total_seconds()) >= 6 * 3600
        ) or bool(old_reset) != bool(new_reset)
        changed = not previous or band(point) != band(previous) or reset_changed_materially or any(
            point.get(field) != previous.get(field) for field in ("plan", "quality")
        )
        if changed or hour != last_hour:
            item = dict(point)
            item["break_before"] = bool(kept and raw_gap_since_keep)
            kept.append(item)
            last_hour = hour
            raw_gap_since_keep = False
        previous = point
    return kept


def turn_totals(db: sqlite3.Connection) -> dict[str, Any]:
    rows = db.execute(
        "SELECT runtime, model, count(*) turns, sum(ok) successful_turns, "
        "sum(CASE WHEN cost_usd IS NOT NULL THEN 1 ELSE 0 END) priced_turns, "
        "sum(cost_unaccounted) unaccounted_turns, sum(coalesce(cost_usd, 0)) virtual_cost_usd, "
        "sum(input_tokens) input_tokens, sum(output_tokens) output_tokens, "
        "sum(cache_read_tokens) cache_read_tokens, sum(cache_create_tokens) cache_create_tokens "
        "FROM turn_usage GROUP BY runtime, model ORDER BY runtime, model"
    ).fetchall()
    models = []
    for row in rows:
        item = dict(row)
        item["virtual_cost_usd"] = round(item["virtual_cost_usd"], 6)
        item["real_payment_usd"] = None
        item["cost_semantics"] = "recorded virtual API-equivalent; subscription payment is not derived from tokens"
        models.append(item)
    by_runtime: dict[str, dict[str, Any]] = {}
    for item in models:
        runtime = item["runtime"]
        bucket = by_runtime.setdefault(runtime, {
            "turns": 0, "successful_turns": 0, "priced_turns": 0,
            "unaccounted_turns": 0, "virtual_cost_usd": 0.0,
            "input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cache_create_tokens": 0,
        })
        for field in bucket:
            bucket[field] += item[field]
    for bucket in by_runtime.values():
        bucket["virtual_cost_usd"] = round(bucket["virtual_cost_usd"], 6)
        bucket["real_payment_usd"] = None
    return {"by_model": models, "by_runtime": by_runtime}


def selected_turns(db: sqlite3.Connection) -> dict[str, Any]:
    # Successful Claude turns whose own turn-end quota sample said weekly=100.
    claude_after_100 = db.execute(
        "SELECT t.id, t.ts, t.session_id, s.name session_name, t.model, t.ok, t.stop_reason, "
        "t.cost_usd, t.input_tokens, t.output_tokens, t.cache_read_tokens, t.cache_create_tokens, "
        "t.quota_seven_day_pct, t.quota_sampled_at "
        "FROM turn_usage t LEFT JOIN sessions s ON s.id=t.session_id "
        "WHERE t.runtime='claude' AND t.ok=1 AND t.quota_seven_day_pct>=100 ORDER BY t.ts"
    ).fetchall()
    return {
        "successful_claude_turns_reported_at_weekly_100": [dict(row) for row in claude_after_100],
    }


def plan_transitions(series: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    points = series.get("codex.primary", [])
    transitions = []
    for before, after in zip(points, points[1:]):
        if before.get("plan") == after.get("plan"):
            continue
        transitions.append({
            "interval_after": before["ts"], "interval_at_or_before": after["ts"],
            "from_plan": before.get("plan"), "to_plan": after.get("plan"),
            "before_utilization": before["utilization"], "after_utilization": after["utilization"],
            "before_resets_at": before.get("resets_at"), "after_resets_at": after.get("resets_at"),
            "apparent_capacity_ratio_from_integer_percentages": (
                round(before["utilization"] / after["utilization"], 3)
                if after["utilization"] else None
            ),
        })
    return transitions


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("backup", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--captured-at", required=True, help="UTC timestamp of backup capture")
    parser.add_argument("--source-path", required=True, help="live source path copied with Connection.backup")
    parser.add_argument("--contour", required=True)
    args = parser.parse_args()

    db = sqlite3.connect(f"file:{args.backup}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    quick_check = db.execute("PRAGMA quick_check").fetchone()[0]
    series, extraction = extract_series(db)
    metrics = {
        key: {
            "samples": len(points),
            "first_ts": points[0]["ts"] if points else None,
            "last_ts": points[-1]["ts"] if points else None,
            "min_utilization": min((p["utilization"] for p in points), default=None),
            "max_utilization": max((p["utilization"] for p in points), default=None),
            "thresholds": threshold_metrics(points),
            "reset_and_drop_events": reset_events(points),
        }
        for key, points in series.items()
    }
    payload = {
        "schema_version": 1,
        "generated_at": iso(datetime.now(UTC)),
        "scope": {
            "contour": args.contour,
            "timezone_storage": "UTC (ISO-8601 Z or explicit offsets)",
            "display_timezone": "Europe/Berlin; CEST (UTC+02:00) at capture",
            "source_live_path": args.source_path,
            "backup_path": str(args.backup),
            "backup_method": "sqlite3.Connection.backup",
            "captured_at": args.captured_at,
            "quick_check": quick_check,
            "secrets_or_message_bodies_in_output": False,
        },
        "retention": {
            "usage_snapshots": table_range(db, "usage_snapshots"),
            "turn_usage": table_range(db, "turn_usage"),
            "sessions": table_range(db, "sessions", "created_at"),
            "logs": table_range(db, "logs"),
        },
        "sampling": extraction,
        "quota_metrics": metrics,
        "plan_transitions": plan_transitions(series),
        "turn_usage": turn_totals(db),
        "selected_evidence": selected_turns(db),
        "timeline_series": {key: compact_points(points) for key, points in series.items()},
        "live_read_only_capture": {},
        "controller_99": {},
        "official_claims": {},
        "benchmarks": {},
        "limitations": [],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    db.close()


if __name__ == "__main__":
    main()
