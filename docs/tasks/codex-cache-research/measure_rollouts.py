#!/usr/bin/env python3
"""Aggregate Codex rollout token metadata without reading message contents."""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


DEFAULT_CUTOFF = "2026-07-18T07:43:00Z"
ALLOWED_ORIGINATORS = {"codex_exec", "codex-tui", "orchestra"}


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def bucket(minutes: float) -> str | None:
    if minutes < 5:
        return "<5m"
    if minutes < 10:
        return "5-10m"
    if minutes < 30:
        return "10-30m"
    if minutes < 60:
        return "30-60m"
    if 120 <= minutes < 360:
        return "2-6h"
    if 720 <= minutes < 1_440:
        return "12-24h"
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.home() / ".codex/sessions/2026/07")
    parser.add_argument("--cutoff", default=DEFAULT_CUTOFF)
    args = parser.parse_args()
    cutoff = parse_time(args.cutoff)

    events_by_session: dict[str, list[dict]] = defaultdict(list)
    files_with_usage: set[Path] = set()

    for path in sorted(args.root.glob("**/*.jsonl")):
        metadata = None
        rows = []
        with path.open(encoding="utf-8", errors="replace") as source:
            for line in source:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                timestamp = row.get("timestamp")
                if not timestamp or parse_time(timestamp) > cutoff:
                    continue
                if row.get("type") == "session_meta":
                    metadata = row.get("payload") or {}
                rows.append(row)

        if not metadata or metadata.get("cli_version") != "0.144.5":
            continue
        if metadata.get("originator") not in ALLOWED_ORIGINATORS:
            continue

        session_id = metadata.get("id") or metadata.get("session_id")
        model = None
        for line_number, row in enumerate(rows):
            payload = row.get("payload") or {}
            if row.get("type") == "turn_context":
                model = payload.get("model", model)
                events_by_session[session_id].append(
                    {
                        "timestamp": parse_time(row["timestamp"]),
                        "order": 0,
                        "path": path,
                        "line": line_number,
                        "kind": "model",
                        "model": model,
                    }
                )
            elif row.get("type") == "event_msg" and payload.get("type") == "thread_settings_applied":
                model = (payload.get("thread_settings") or {}).get("model", model)
                events_by_session[session_id].append(
                    {
                        "timestamp": parse_time(row["timestamp"]),
                        "order": 0,
                        "path": path,
                        "line": line_number,
                        "kind": "model",
                        "model": model,
                    }
                )
            elif row.get("type") == "event_msg" and payload.get("type") == "context_compacted":
                events_by_session[session_id].append(
                    {
                        "timestamp": parse_time(row["timestamp"]),
                        "order": 1,
                        "path": path,
                        "line": line_number,
                        "kind": "compact",
                    }
                )
            elif row.get("type") == "event_msg" and payload.get("type") == "token_count":
                usage = (payload.get("info") or {}).get("last_token_usage") or {}
                total_usage = (payload.get("info") or {}).get("total_token_usage") or {}
                events_by_session[session_id].append(
                    {
                        "timestamp": parse_time(row["timestamp"]),
                        "order": 2,
                        "path": path,
                        "line": line_number,
                        "kind": "call",
                        "model": model,
                        "input": usage.get("input_tokens", 0),
                        "cached": usage.get("cached_input_tokens", 0),
                        "output": usage.get("output_tokens", 0),
                        "plan": (payload.get("rate_limits") or {}).get("plan_type") or "unknown",
                        "dedupe_key": (
                            row["timestamp"],
                            total_usage.get("input_tokens", 0),
                            total_usage.get("cached_input_tokens", 0),
                            total_usage.get("output_tokens", 0),
                            total_usage.get("reasoning_output_tokens", 0),
                        ),
                    }
                )

    sessions: dict[str, list[dict]] = {}
    duplicate_events = 0
    for session_id, events in events_by_session.items():
        current_model = None
        model_epoch = 0
        compact_epoch = 0
        seen_calls = set()
        calls = []
        for event in sorted(events, key=lambda item: (item["timestamp"], item["order"], str(item["path"]), item["line"])):
            if event["kind"] == "model":
                if event.get("model") and event["model"] != current_model:
                    current_model = event["model"]
                    model_epoch += 1
                continue
            if event["kind"] == "compact":
                compact_epoch += 1
                continue
            if event["model"] != "gpt-5.6-sol":
                continue
            if event["dedupe_key"] in seen_calls:
                duplicate_events += 1
                continue
            seen_calls.add(event["dedupe_key"])
            calls.append(
                {
                    "timestamp": event["timestamp"],
                    "model_epoch": model_epoch,
                    "compact_epoch": compact_epoch,
                    "input": event["input"],
                    "cached": event["cached"],
                    "output": event["output"],
                    "plan": event["plan"],
                }
            )
            files_with_usage.add(event["path"])
        if calls:
            sessions[session_id] = calls

    calls = [call for session_calls in sessions.values() for call in session_calls]
    total_input = sum(call["input"] for call in calls)
    total_cached = sum(call["cached"] for call in calls)
    total_output = sum(call["output"] for call in calls)
    first_calls = [session_calls[0] for session_calls in sessions.values()]

    gaps: dict[str, list[dict]] = defaultdict(list)
    long_gaps = []
    for session_calls in sessions.values():
        for previous, current in zip(session_calls, session_calls[1:]):
            if previous["model_epoch"] != current["model_epoch"]:
                continue
            if previous["compact_epoch"] != current["compact_epoch"]:
                continue
            minutes = (current["timestamp"] - previous["timestamp"]).total_seconds() / 60
            ratio = current["cached"] / current["input"] * 100 if current["input"] else 0
            item = {"minutes": minutes, "ratio": ratio, **current}
            if label := bucket(minutes):
                gaps[label].append(item)
            if minutes >= 30:
                long_gaps.append(item)

    plan_calls = Counter(call["plan"] for call in calls)
    plan_input = Counter()
    plan_cached = Counter()
    for call in calls:
        plan_input[call["plan"]] += call["input"]
        plan_cached[call["plan"]] += call["cached"]

    def gap_summary(items: list[dict]) -> dict:
        ratios = [item["ratio"] for item in items]
        return {
            "n": len(items),
            "hits": sum(item["cached"] > 0 for item in items),
            "median_pct": round(statistics.median(ratios), 2),
            "min_pct": round(min(ratios), 2),
            "max_pct": round(max(ratios), 2),
        }

    result = {
        "cutoff": args.cutoff,
        "filters": {
            "cli_version": "0.144.5",
            "model": "gpt-5.6-sol",
            "originators": sorted(ALLOWED_ORIGINATORS),
            "message_content_read": False,
        },
        "files_with_usage": len(files_with_usage),
        "duplicate_events_removed": duplicate_events,
        "sessions": len(sessions),
        "calls": len(calls),
        "tokens": {"input": total_input, "cached": total_cached, "output": total_output},
        "weighted_cache_pct": round(total_cached / total_input * 100, 2),
        "first_calls": {
            "n": len(first_calls),
            "hits": sum(call["cached"] > 0 for call in first_calls),
            "median_pct": round(
                statistics.median(call["cached"] / call["input"] * 100 if call["input"] else 0 for call in first_calls),
                2,
            ),
        },
        "plans": {
            plan: {
                "calls": plan_calls[plan],
                "input": plan_input[plan],
                "cached": plan_cached[plan],
                "cache_pct": round(plan_cached[plan] / plan_input[plan] * 100, 2),
            }
            for plan in sorted(plan_calls)
        },
        "gaps": {label: gap_summary(gaps[label]) for label in ("<5m", "5-10m", "10-30m", "30-60m", "2-6h", "12-24h")},
        "long_gaps": [
            {
                "minutes": round(item["minutes"], 1),
                "plan": item["plan"],
                "input": item["input"],
                "cached": item["cached"],
                "cache_pct": round(item["ratio"], 2),
            }
            for item in sorted(long_gaps, key=lambda value: value["minutes"])
        ],
    }
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
