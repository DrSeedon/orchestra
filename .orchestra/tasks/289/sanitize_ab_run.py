#!/usr/bin/env python3
"""Reduce A/B raw JSONL and WAL-safe snapshots to non-sensitive aggregates.

Raw JSONL and SQLite backups are intentionally not part of the research
artifact. This script records only usage, timings, hashes, provider counters,
and aggregate foreign turns. It never emits command text, log text, session
names, paths read by a model, or database payloads.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


PRICES = {
    # API-equivalent prices per million tokens at the experiment cutoff;
    # source: app/backend_codex.py CODEX_TOKEN_PRICES.
    "gpt-5.6-luna": {"input": 0.2, "cached": 0.02, "write": 0.25, "output": 1.2},
    "gpt-5.6-sol": {"input": 5.0, "cached": 0.5, "write": 6.25, "output": 30.0},
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def jsonl_aggregate(path: Path, model: str) -> dict[str, Any]:
    event_types: dict[str, int] = {}
    item_types: dict[str, int] = {}
    usage: dict[str, int] | None = None
    command_count = 0
    outside_path_pattern_count = 0
    agent_messages = 0
    error_events = 0

    with path.open(encoding="utf-8") as handle:
        for line in handle:
            event = json.loads(line)
            event_type = str(event.get("type"))
            event_types[event_type] = event_types.get(event_type, 0) + 1
            error_events += int(bool(event.get("error")))
            item = event.get("item") or {}
            item_type = item.get("type")
            if item_type:
                item_types[item_type] = item_types.get(item_type, 0) + 1
            if item_type == "agent_message":
                agent_messages += 1
            if item_type == "command_execution":
                command_count += 1
                command = str(item.get("command") or "")
                # Store only the count, never the command. Absolute paths and
                # parent traversal are sufficient to flag an obvious scope exit.
                if re.search(r"(?:^|\s)/(?:home|root|etc|var|proc|sys|mnt)/|(?:^|[\s/])\.\.(?:/|\s|$)", command):
                    outside_path_pattern_count += 1
            candidate = event.get("usage")
            if isinstance(candidate, dict):
                usage = {key: int(candidate.get(key) or 0) for key in (
                    "input_tokens",
                    "cached_input_tokens",
                    "cache_write_input_tokens",
                    "output_tokens",
                    "reasoning_output_tokens",
                )}

    if usage is None:
        raise ValueError(f"no usage event in {path.name}")
    prices = PRICES[model]
    cached = min(max(usage["cached_input_tokens"], 0), max(usage["input_tokens"], 0))
    written = min(
        max(usage["cache_write_input_tokens"], 0),
        max(usage["input_tokens"] - cached, 0),
    )
    fresh = max(usage["input_tokens"] - cached - written, 0)
    cost = (
        fresh * prices["input"]
        + cached * prices["cached"]
        + written * prices["write"]
        + max(usage["output_tokens"], 0) * prices["output"]
    ) / 1_000_000
    return {
        "model": model,
        "usage": usage,
        "api_equivalent_cost_usd": cost,
        "event_counts": event_types,
        "item_counts": item_types,
        "agent_message_events": agent_messages,
        "command_execution_events": command_count,
        "outside_path_pattern_count": outside_path_pattern_count,
        "error_events": error_events,
        "raw_jsonl_sha256": sha256(path),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--post-db", type=Path, required=True)
    parser.add_argument("--pre-summary", type=Path, required=True)
    parser.add_argument("--post-summary", type=Path, required=True)
    parser.add_argument("--luna-jsonl", type=Path, required=True)
    parser.add_argument("--sol-jsonl", type=Path, required=True)
    parser.add_argument("--luna-review", type=Path, required=True)
    parser.add_argument("--sol-review", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    pre = json.loads(args.pre_summary.read_text(encoding="utf-8"))
    post = json.loads(args.post_summary.read_text(encoding="utf-8"))
    runs = {
        "luna": jsonl_aggregate(args.luna_jsonl, "gpt-5.6-luna"),
        "sol": jsonl_aggregate(args.sol_jsonl, "gpt-5.6-sol"),
    }
    job_ids = {"luna": "bg-e27bc0414c", "sol": "bg-4e412ce4c3"}

    with sqlite3.connect(f"file:{args.post_db}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise ValueError(f"post snapshot integrity: {integrity}")
        for arm, job_id in job_ids.items():
            row = conn.execute(
                "SELECT status, created_at, triggered_at, error FROM bg_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"missing background job for {arm}")
            created = parse_ts(row["created_at"])
            triggered = parse_ts(row["triggered_at"])
            runs[arm]["job"] = {
                "status": row["status"],
                "created_at": row["created_at"],
                "triggered_at": row["triggered_at"],
                "wall_seconds": (triggered - created).total_seconds(),
                "error_present": row["error"] is not None,
                "exit_code": 0,
            }

        foreign_rows = conn.execute(
            """
            SELECT id, ts, runtime, model, input_tokens, cache_read_tokens,
                   output_tokens, cost_usd, session_id
            FROM turn_usage
            WHERE id > ? AND id <= ?
            ORDER BY id
            """,
            (pre["last_turn_usage_id"], post["last_turn_usage_id"]),
        ).fetchall()

    salt = "task-289-ab-foreign-session"
    foreign = []
    for row in foreign_rows:
        foreign.append({
            "id": row["id"],
            "ts": row["ts"],
            "runtime": row["runtime"],
            "model": row["model"],
            "input_tokens": row["input_tokens"],
            "cached_input_tokens": row["cache_read_tokens"],
            "output_tokens": row["output_tokens"],
            "api_equivalent_cost_usd": row["cost_usd"],
            "session_hash": hashlib.sha256((salt + str(row["session_id"])).encode()).hexdigest()[:12],
        })

    runs["luna"]["review_sha256"] = sha256(args.luna_review)
    runs["sol"]["review_sha256"] = sha256(args.sol_review)
    output = {
        "schema_version": 1,
        "pricing_source": "app/backend_codex.py CODEX_TOKEN_PRICES at cutoff",
        "pre": pre,
        "post": post,
        "provider_budget": {
            "reset_unchanged": pre["codex_resets_at"] == post["codex_resets_at"],
            "integer_utilization_delta_points": post["codex_main_utilization"] - pre["codex_main_utilization"],
            "foreign_turns": foreign,
            "foreign_turn_count": len(foreign),
            "attribution": "Direct ephemeral A/B calls are measured from their JSONL; all intervening turn_usage rows are foreign. The provider counter is global and integer-quantized.",
        },
        "runs": runs,
        "raw_retention": "Raw JSONL and SQLite snapshots were deleted after this aggregate was frozen.",
    }
    args.out.write_text(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "integer_delta": output["provider_budget"]["integer_utilization_delta_points"],
        "foreign_turns": len(foreign),
        "luna_wall_seconds": runs["luna"]["job"]["wall_seconds"],
        "sol_wall_seconds": runs["sol"]["job"]["wall_seconds"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
