#!/usr/bin/env python3
"""Measure Sol usage by Orchestra workers and codex_review.

The parser reads only rollout metadata, turn context, and token_count events.
It never reads prompt, tool, or assistant message bodies.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


SOL = "gpt-5.6-sol"
SOL_CREDITS_PER_MILLION = {
    "input": 125.0,
    "cached_input": 12.5,
    "output": 750.0,
}


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def summarize(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"n": 0, "median": None, "p25": None, "p75": None, "min": None, "max": None}
    return {
        "n": len(values),
        "median": round(statistics.median(values), 4),
        "p25": round(percentile(values, 0.25) or 0, 4),
        "p75": round(percentile(values, 0.75) or 0, 4),
        "min": round(min(values), 4),
        "max": round(max(values), 4),
    }


def sol_credits(usage: dict[str, int]) -> float:
    fresh = usage["input"] - usage["cached"]
    return (
        fresh * SOL_CREDITS_PER_MILLION["input"]
        + usage["cached"] * SOL_CREDITS_PER_MILLION["cached_input"]
        + usage["output"] * SOL_CREDITS_PER_MILLION["output"]
    ) / 1_000_000


def read_rollouts(root: Path, lower: datetime, upper: datetime) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()

    for path in sorted(root.glob("**/rollout-*.jsonl")):
        metadata: dict[str, Any] = {}
        model = ""
        effort = ""

        with path.open(encoding="utf-8", errors="replace") as source:
            for line_number, line in enumerate(source):
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                timestamp_raw = row.get("timestamp")
                if not timestamp_raw:
                    continue
                timestamp = parse_time(timestamp_raw)
                row_type = row.get("type")
                payload = row.get("payload") or {}

                if row_type == "session_meta":
                    metadata = payload
                    continue
                if row_type == "turn_context":
                    model = payload.get("model", model)
                    effort = payload.get("effort", effort)
                    continue
                if timestamp < lower or timestamp > upper:
                    continue
                if row_type != "event_msg" or payload.get("type") != "token_count":
                    continue

                info = payload.get("info") or {}
                last = info.get("last_token_usage") or {}
                total = info.get("total_token_usage") or {}
                if not last:
                    continue

                session_id = metadata.get("id") or metadata.get("session_id") or str(path)
                dedupe_key = (
                    session_id,
                    timestamp_raw,
                    total.get("input_tokens", 0),
                    total.get("cached_input_tokens", 0),
                    total.get("output_tokens", 0),
                    total.get("reasoning_output_tokens", 0),
                )
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)

                events.append(
                    {
                        "timestamp": timestamp,
                        "path": str(path),
                        "line": line_number,
                        "session_id": session_id,
                        "originator": metadata.get("originator", ""),
                        "cwd": metadata.get("cwd", ""),
                        "source": metadata.get("source", ""),
                        "cli_version": metadata.get("cli_version", ""),
                        "model": model,
                        "effort": effort,
                        "input": int(last.get("input_tokens", 0)),
                        "cached": int(last.get("cached_input_tokens", 0)),
                        "output": int(last.get("output_tokens", 0)),
                        "reasoning_output": int(last.get("reasoning_output_tokens", 0)),
                        "used_percent": (
                            ((payload.get("rate_limits") or {}).get("primary") or {}).get("used_percent")
                        ),
                    }
                )
    return events


def load_review_jobs_from_bg(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT b.id, b.created_at, b.triggered_at, b.message, b.created_by_name,
               b.target_name, b.target_scope,
               COALESCE(NULLIF(s.worktree_path, ''), s.cwd) AS cwd
        FROM bg_jobs b
        LEFT JOIN sessions s
          ON s.name = b.target_name AND s.scope = b.target_scope
        WHERE b.message LIKE 'Codex % done. Results in %'
          AND b.status = 'triggered' AND b.triggered_at IS NOT NULL
        ORDER BY b.created_at
        """
    ).fetchall()
    jobs = []
    for row in rows:
        action = row[3].split(maxsplit=2)[1].lower()
        jobs.append(
            {
                "id": row[0],
                "start": parse_time(row[1]),
                "end": parse_time(row[2]),
                "message": row[3],
                "created_by": row[4],
                "target": row[5],
                "scope": row[6],
                "cwd": row[7],
                "status": "completed",
                "mode": action,
                "output": row[3].partition("Results in ")[2],
            }
        )
    return jobs


def load_review_jobs_from_logs(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    tool_rows = connection.execute(
        """
        SELECT l.session_id, l.ts, l.content, s.name, s.scope,
               COALESCE(NULLIF(s.worktree_path, ''), s.cwd) AS cwd
        FROM logs l
        JOIN sessions s ON s.id = l.session_id
        WHERE l.type = 'tool'
          AND l.content LIKE 'mcp__orchestra__codex_review:%'
        ORDER BY l.ts
        """
    ).fetchall()
    notification_rows = connection.execute(
        """
        SELECT session_id, ts, content
        FROM logs
        WHERE type = 'user_message'
          AND (
            content LIKE '[Background job completed] Codex % done.%'
            OR content LIKE '[Background job TIMED OUT] Codex % done.%'
            OR content LIKE '[Background job FAILED] Codex % done.%'
          )
        ORDER BY ts
        """
    ).fetchall()
    notifications: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for session_id, timestamp, content in notification_rows:
        notifications[session_id].append(
            {"end": parse_time(timestamp), "content": content, "used": False}
        )

    jobs = []
    for session_id, timestamp, content, name, scope, cwd in tool_rows:
        try:
            arguments = json.loads(content.partition(":")[2].strip())
        except json.JSONDecodeError:
            continue
        output = arguments.get("output", "CODEX_REVIEW.md")
        start = parse_time(timestamp)
        completion = next(
            (
                item
                for item in notifications.get(session_id, [])
                if not item["used"]
                and item["end"] >= start
                and f"Results in {output}" in item["content"]
            ),
            None,
        )
        if completion is None:
            continue
        completion["used"] = True
        message = completion["content"]
        if message.startswith("[Background job completed]"):
            status = "completed"
        elif message.startswith("[Background job TIMED OUT]"):
            status = "timed_out"
        else:
            status = "failed"
        mode = "resume" if arguments.get("resume") else arguments.get("mode", "review")
        jobs.append(
            {
                "id": f"{session_id}:{timestamp}",
                "start": start,
                "end": completion["end"],
                "message": f"{mode}: {output}",
                "created_by": name,
                "target": name,
                "scope": scope,
                "cwd": cwd,
                "status": status,
                "mode": mode,
                "output": output,
            }
        )
    return jobs


def load_worker_turns(
    connection: sqlite3.Connection, lower: datetime, upper: datetime
) -> list[dict[str, Any]]:
    sessions = connection.execute(
        """
        SELECT id, name, scope, created_at, COALESCE(NULLIF(worktree_path, ''), cwd)
        FROM sessions
        """,
    ).fetchall()
    turns: list[dict[str, Any]] = []

    for session_id, name, scope, created_at, cwd in sessions:
        logs = connection.execute(
            """
            SELECT ts, type, content
            FROM logs
            WHERE session_id = ?
              AND (type = 'user_message'
                   OR (type = 'status' AND content LIKE '%turn ended%'))
            ORDER BY ts
            """,
            (session_id,),
        ).fetchall()
        previous_end = parse_time(created_at)
        pending_messages: list[datetime] = []
        for timestamp_raw, log_type, _content in logs:
            timestamp = parse_time(timestamp_raw)
            if log_type == "user_message":
                if timestamp > previous_end:
                    pending_messages.append(timestamp)
                continue

            start = min(pending_messages) if pending_messages else previous_end
            if lower <= timestamp <= upper:
                turns.append(
                    {
                        "session_id": session_id,
                        "name": name,
                        "scope": scope,
                        "cwd": cwd,
                        "start": start,
                        "end": timestamp,
                    }
                )
            previous_end = timestamp
            pending_messages = []
    return turns


def usage_for(events: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "input": sum(event["input"] for event in events),
        "cached": sum(event["cached"] for event in events),
        "output": sum(event["output"] for event in events),
        "reasoning_output": sum(event["reasoning_output"] for event in events),
    }


def classify(
    events: list[dict[str, Any]],
    review_jobs: list[dict[str, Any]],
    worker_turns: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    review_results = []
    claimed: set[tuple[str, str, int]] = set()

    for job in review_jobs:
        matched = [
            event
            for event in events
            if event["model"] == SOL
            and event["originator"] == "codex_exec"
            and event["cwd"] == job["cwd"]
            and job["start"] <= event["timestamp"] <= job["end"]
            and (event["session_id"], event["path"], event["line"]) not in claimed
        ]
        for event in matched:
            claimed.add((event["session_id"], event["path"], event["line"]))
        usage = usage_for(matched)
        review_results.append(
            {
                **{key: value for key, value in job.items() if key not in {"start", "end"}},
                "start": job["start"].isoformat(),
                "end": job["end"].isoformat(),
                "duration_seconds": round((job["end"] - job["start"]).total_seconds(), 3),
                "api_calls": len(matched),
                "usage": usage,
                "credits": round(sol_credits(usage), 6),
                "efforts": sorted({event["effort"] for event in matched}),
                "models": sorted({event["model"] for event in matched}),
            }
        )

    worker_results = []
    for turn in worker_turns:
        matched = [
            event
            for event in events
            if event["model"] == SOL
            and event["originator"] == "orchestra"
            and event["cwd"] == turn["cwd"]
            and turn["start"] <= event["timestamp"] <= turn["end"]
            and (event["session_id"], event["path"], event["line"]) not in claimed
        ]
        for event in matched:
            claimed.add((event["session_id"], event["path"], event["line"]))
        usage = usage_for(matched)
        worker_results.append(
            {
                **{key: value for key, value in turn.items() if key not in {"start", "end"}},
                "start": turn["start"].isoformat(),
                "end": turn["end"].isoformat(),
                "duration_seconds": round((turn["end"] - turn["start"]).total_seconds(), 3),
                "api_calls": len(matched),
                "usage": usage,
                "credits": round(sol_credits(usage), 6),
                "efforts": sorted({event["effort"] for event in matched}),
                "models": sorted({event["model"] for event in matched}),
            }
        )

    other_events = [
        event
        for event in events
        if event["model"] == SOL
        and (event["session_id"], event["path"], event["line"]) not in claimed
    ]
    return review_results, worker_results, other_events


def category_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    nonempty = [item for item in items if item["api_calls"]]
    total_usage = usage_for(
        [
            {
                "input": item["usage"]["input"],
                "cached": item["usage"]["cached"],
                "output": item["usage"]["output"],
                "reasoning_output": item["usage"]["reasoning_output"],
            }
            for item in nonempty
        ]
    )
    return {
        "items": len(items),
        "items_with_usage": len(nonempty),
        "api_calls": sum(item["api_calls"] for item in nonempty),
        "duration_seconds": summarize([item["duration_seconds"] for item in nonempty]),
        "credits": {
            "total": round(sum(item["credits"] for item in nonempty), 6),
            **summarize([item["credits"] for item in nonempty]),
        },
        "usage": total_usage,
        "cache_pct": round(total_usage["cached"] / total_usage["input"] * 100, 4)
        if total_usage["input"]
        else None,
    }


def quota_snapshots(
    connection: sqlite3.Connection, lower: datetime, upper: datetime
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT ts, provider_usage
        FROM usage_snapshots
        WHERE ts BETWEEN ? AND ?
        ORDER BY ts
        """,
        (lower.isoformat(), upper.isoformat()),
    ).fetchall()
    snapshots = []
    previous: tuple[Any, Any] | None = None
    for timestamp, raw in rows:
        try:
            provider = json.loads(raw).get("codex") or {}
        except json.JSONDecodeError:
            continue
        windows = provider.get("windows") or []
        if not windows:
            continue
        window = windows[0]
        state = (window.get("utilization"), window.get("resets_at"))
        if state == previous:
            continue
        previous = state
        snapshots.append(
            {
                "timestamp": timestamp,
                "used_percent": state[0],
                "resets_at": state[1],
                "plan_type": provider.get("plan_type"),
            }
        )
    return snapshots


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--rollouts", type=Path, default=Path.home() / ".codex/sessions")
    parser.add_argument("--review-source", choices=("logs", "bg_jobs"), default="logs")
    parser.add_argument("--start", help="Inclusive ISO-8601 measurement start")
    parser.add_argument("--end", help="Inclusive ISO-8601 measurement end")
    args = parser.parse_args()
    if bool(args.start) != bool(args.end):
        parser.error("--start and --end must be provided together")

    connection = sqlite3.connect(args.db)
    review_jobs = (
        load_review_jobs_from_logs(connection)
        if args.review_source == "logs"
        else load_review_jobs_from_bg(connection)
    )
    if args.start:
        requested_lower = parse_time(args.start)
        requested_upper = parse_time(args.end)
        review_jobs = [
            job
            for job in review_jobs
            if job["start"] >= requested_lower and job["end"] <= requested_upper
        ]
    if not review_jobs:
        raise SystemExit("No completed codex_review jobs found")
    lower = parse_time(args.start) if args.start else min(job["start"] for job in review_jobs)
    upper = parse_time(args.end) if args.end else max(job["end"] for job in review_jobs)
    worker_turns = load_worker_turns(connection, lower, upper)
    events = read_rollouts(args.rollouts, lower, upper)
    reviews, workers, other_events = classify(events, review_jobs, worker_turns)
    unbounded_worker_events = [event for event in other_events if event["originator"] == "orchestra"]
    external_events = [event for event in other_events if event["originator"] != "orchestra"]
    unbounded_worker_usage = usage_for(unbounded_worker_events)
    external_usage = usage_for(external_events)
    other_groups = Counter((event["originator"], event["cwd"], event["effort"]) for event in other_events)

    review_summary = category_summary(reviews)
    worker_summary = category_summary(workers)
    unbounded_worker_credits = sol_credits(unbounded_worker_usage)
    external_credits = sol_credits(external_usage)
    orchestra_worker_credits = worker_summary["credits"]["total"] + unbounded_worker_credits
    orchestra_credits = review_summary["credits"]["total"] + orchestra_worker_credits
    all_credits = orchestra_credits + external_credits

    result = {
        "measurement_window": {
            "start": lower.isoformat(),
            "end": upper.isoformat(),
            "seconds": round((upper - lower).total_seconds(), 3),
        },
        "method": {
            "rollout_fields_read": ["session_meta", "turn_context", "token_count"],
            "message_bodies_read": False,
            "classification": "originator + cwd + timestamp",
            "model": SOL,
            "credit_formula_per_1m": SOL_CREDITS_PER_MILLION,
        },
        "quota_snapshots_on_change": quota_snapshots(connection, lower, upper),
        "summary": {
            "codex_review": review_summary,
            "worker_turn": worker_summary,
            "other_sol": {
                "api_calls": len(other_events),
                "unbounded_orchestra_worker": {
                    "api_calls": len(unbounded_worker_events),
                    "credits_total": round(unbounded_worker_credits, 6),
                    "usage": unbounded_worker_usage,
                },
                "external_originator": {
                    "api_calls": len(external_events),
                    "credits_total": round(external_credits, 6),
                    "usage": external_usage,
                },
                "groups": [
                    {"originator": key[0], "cwd": key[1], "effort": key[2], "api_calls": count}
                    for key, count in other_groups.most_common()
                ],
            },
            "credit_share_pct": {
                "within_orchestra_codex_review": round(
                    review_summary["credits"]["total"] / orchestra_credits * 100, 4
                )
                if orchestra_credits
                else None,
                "within_orchestra_worker": round(orchestra_worker_credits / orchestra_credits * 100, 4)
                if orchestra_credits
                else None,
                "all_account_codex_review": round(
                    review_summary["credits"]["total"] / all_credits * 100, 4
                )
                if all_credits
                else None,
                "all_account_orchestra_worker": round(orchestra_worker_credits / all_credits * 100, 4)
                if all_credits
                else None,
                "all_account_external": round(external_credits / all_credits * 100, 4)
                if all_credits
                else None,
            },
            "review_to_worker_median_credit_ratio": (
                round(
                    review_summary["credits"]["median"] / worker_summary["credits"]["median"],
                    4,
                )
                if review_summary["credits"]["median"] is not None
                and worker_summary["credits"]["median"] is not None
                and worker_summary["credits"]["median"] != 0
                else None
            ),
        },
        "review_jobs": reviews,
        "worker_turns": workers,
    }
    connection.close()
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
