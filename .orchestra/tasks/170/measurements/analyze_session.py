#!/usr/bin/env python3
"""Produce a redacted timing/payload snapshot for one live Codex session.

The script reads SQLite in URI read-only mode and a Codex rollout JSONL.  It
never serializes prompt text, command text, tool results, MCP arguments, or MCP
results.  Output contains timestamps, durations, byte counts, safe operation
classes, and stable identifiers only.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sqlite3
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


DEFAULT_DB = Path("/home/kesha/orchestra/data/orchestra.db")
DEFAULT_ROLLOUT = Path(
    "/home/kesha/.codex/sessions/2026/08/09/"
    "rollout-2026-08-09T09-31-21-019fe56e-f44f-73a3-b92c-48b6ebde1dbc.jsonl"
)
DEFAULT_SCOPE = "/home/kesha/projects/seedon"
DEFAULT_NAME = "feat-groom-demo"
# Commit 8369737 reached the main checkout at 14:54:46 CEST.  The FastAPI
# process had already started on the previous day and did not reload its route.
DEFAULT_QUOTA_CUTOVER = "2026-08-08T12:54:46+00:00"
DEFAULT_EVIDENCE_CUTOFF = "2026-08-09T13:54:49.350+00:00"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--rollout", type=Path, default=DEFAULT_ROLLOUT)
    parser.add_argument("--scope", default=DEFAULT_SCOPE)
    parser.add_argument("--name", default=DEFAULT_NAME)
    parser.add_argument("--out-dir", type=Path, default=Path(__file__).parent)
    parser.add_argument("--quota-cutover", default=DEFAULT_QUOTA_CUTOVER)
    parser.add_argument("--evidence-cutoff", default=DEFAULT_EVIDENCE_CUTOFF)
    return parser.parse_args()


def dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def iso(value: datetime | None) -> str:
    return value.isoformat(timespec="milliseconds") if value else ""


def byte_len(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, bytes):
        return len(value)
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return len(value.encode("utf-8"))


def flattened_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
            else:
                parts.append(json.dumps(item, ensure_ascii=False, default=str))
        return "\n".join(parts)
    return json.dumps(value, ensure_ascii=False, default=str)


def percentile(values: Iterable[float], quantile: float) -> float | None:
    ordered = sorted(values)
    if not ordered:
        return None
    # Nearest-rank percentile: deterministic for the small forensic samples.
    index = min(len(ordered) - 1, math.ceil(quantile * len(ordered)) - 1)
    return ordered[index]


def stats(values: Iterable[float]) -> dict[str, float | int | None]:
    sample = list(values)
    return {
        "n": len(sample),
        "sum": round(sum(sample), 6),
        "p50": round(statistics.median(sample), 6) if sample else None,
        "p95": round(percentile(sample, 0.95), 6) if sample else None,
        "max": round(max(sample), 6) if sample else None,
    }


def pearson(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    left_mean = statistics.mean(left)
    right_mean = statistics.mean(right)
    numerator = sum((a - left_mean) * (b - right_mean) for a, b in zip(left, right))
    denominator = (
        sum((a - left_mean) ** 2 for a in left)
        * sum((b - right_mean) ** 2 for b in right)
    ) ** 0.5
    return round(numerator / denominator, 6) if denominator else None


def merge_intervals(
    intervals: Iterable[tuple[datetime, datetime]],
) -> list[tuple[datetime, datetime]]:
    ordered = sorted((start, end) for start, end in intervals if end >= start)
    if not ordered:
        return []
    merged: list[tuple[datetime, datetime]] = []
    current_start, current_end = ordered[0]
    for start, end in ordered[1:]:
        if start <= current_end:
            current_end = max(current_end, end)
        else:
            merged.append((current_start, current_end))
            current_start, current_end = start, end
    merged.append((current_start, current_end))
    return merged


def interval_union_seconds(intervals: Iterable[tuple[datetime, datetime]]) -> float:
    return sum((end - start).total_seconds() for start, end in merge_intervals(intervals))


def interval_intersection_seconds(
    left: Iterable[tuple[datetime, datetime]],
    right: Iterable[tuple[datetime, datetime]],
) -> float:
    a = merge_intervals(left)
    b = merge_intervals(right)
    total = 0.0
    i = j = 0
    while i < len(a) and j < len(b):
        start = max(a[i][0], b[j][0])
        end = min(a[i][1], b[j][1])
        if start < end:
            total += (end - start).total_seconds()
        if a[i][1] <= b[j][1]:
            i += 1
        else:
            j += 1
    return total


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def classify_exec(source: str) -> str:
    if "tools.apply_patch" in source:
        return "file_change"
    if "mcp__orchestra__" in source:
        return "mcp_wrapper"
    if "ALL_TOOLS" in source:
        return "tool_discovery"
    if "tools.exec_command" not in source:
        return "other_exec"
    if re.search(r"kill -0|pgrep -f", source) and "pytest" in source:
        return "test_poll"
    if "pytest" in source or "compileall" in source:
        return "test"
    if "playwright" in source or "chromium" in source:
        return "browser"
    if "curl " in source or "web__run" in source:
        return "network"
    if re.search(r"(?:\brg\s|sed -n|git (?:show|log|status|diff|ls|rev)|\bfind\s|\bwc\s)", source):
        return "read_search_git"
    return "shell_other"


def message_source(content: str) -> str:
    if content.startswith("[Background job"):
        return "background_job"
    if content.startswith("[from:seedon-orchestrator]"):
        return "seedon_orchestrator"
    if content.startswith("[from:"):
        return "other_agent"
    return "user_direct"


def safe_status_kind(content: str) -> tuple[str, str]:
    if content.startswith("codex turn=") and content.endswith(" started"):
        match = re.search(r"codex turn=([0-9a-f-]+)", content)
        return "turn_start", match.group(1) if match else ""
    if content.startswith("turn ended"):
        reason = re.search(r"turn ended \(([^,]+)", content)
        pct = re.search(r"ctx:(\d+)%", content)
        return "turn_end", f"reason={reason.group(1) if reason else ''};ctx_pct={pct.group(1) if pct else ''}"
    if content == "codex compacting context":
        return "context_compact_start", ""
    if content == "codex context compacted":
        return "context_compact_end", ""
    if content == "waiting for bg jobs":
        return "waiting_for_bg", ""
    if content.startswith("precompact timer scheduled"):
        return "precompact_scheduled", ""
    if content.startswith("precompact timer cancelled"):
        return "precompact_cancelled", ""
    if content == "message steered into active Codex turn":
        return "message_steered", ""
    if content.startswith("codex thread="):
        return "thread_started", content.split("=", 1)[1]
    return "other_status", ""


def warning_kind(content: str) -> str:
    lowered = content.lower()
    if "bubblewrap" in lowered:
        return "bubblewrap_system_missing_bundled_fallback"
    if "mcp" in lowered and "cancelled" in lowered:
        return "mcp_cancelled"
    return "other_warning"


def bg_phase(message: str) -> str:
    lowered = message.lower()
    if "implementation" in lowered:
        return "implementation_review"
    if "delta" in lowered:
        return "plan_delta_review"
    if "plan" in lowered:
        return "plan_review"
    if "research" in lowered or "second opinion" in lowered:
        return "research_review"
    return "other_review"


def turn_phase(turn_no: int) -> str:
    """A content-free phase label reconstructed from review/job boundaries."""
    labels = {
        1: "research_build_and_review_submit",
        2: "research_review_fallback_retry",
        3: "research_review_fix_r2",
        4: "research_review_fix_r3",
        5: "research_review_fix_r4",
        6: "research_pass_and_gate",
        7: "plan_build_and_review_r1",
        8: "plan_review_fix_r2",
        9: "plan_review_fix_r3",
        10: "plan_pass_and_gate",
        11: "plan_delta_build_and_review_d1",
        12: "plan_delta_fix_d2",
        13: "plan_delta_fix_d3",
        14: "plan_delta_fix_d4",
        15: "plan_delta_fix_d5",
        16: "plan_delta_fix_d6",
        17: "plan_delta_fix_d7",
        18: "plan_delta_pass_then_phase3_build_and_review_r1",
        19: "implementation_review_retry_and_r2_submit",
        20: "status_checkpoint_during_review",
        21: "credential_instruction_during_review",
        22: "dashboard_scope_expansion_during_review",
        23: "implementation_r2_fixes_tests_and_review_r3",
        24: "implementation_r3_fixes_tests_and_review_r4",
        25: "implementation_r4_fix_and_review_r5",
        26: "implementation_r5_pass_and_deploy_prep",
    }
    return labels.get(turn_no, "unclassified")


def error_category(text: str) -> str:
    lowered = text.lower()
    if "failures" in lowered or " failed" in lowered or text.lstrip().startswith("F"):
        return "test_failure"
    if "rejected" in lowered:
        return "command_rejected"
    if "unexpected eof" in lowered:
        return "shell_syntax"
    if "no such file" in lowered:
        return "missing_path"
    if "traceback" in lowered:
        return "python_exception"
    if "blank line at eof" in lowered:
        return "diff_check"
    return "other_stderr"


def main() -> None:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    session = conn.execute(
        "SELECT * FROM sessions WHERE name=? AND scope=?",
        (args.name, args.scope),
    ).fetchone()
    if session is None:
        raise SystemExit(f"session not found: {args.name!r} in {args.scope!r}")
    session = dict(session)
    session_id = session["id"]
    db_logs = [
        dict(row)
        for row in conn.execute(
            "SELECT id, ts, type, content, event_id FROM logs WHERE session_id=? ORDER BY ts, id",
            (session_id,),
        )
    ]
    usage = {
        row["event_id"]: dict(row)
        for row in conn.execute(
            "SELECT * FROM turn_usage WHERE session_id=? ORDER BY ts", (session_id,)
        )
    }
    rollout = [json.loads(line) for line in args.rollout.open(encoding="utf-8")]

    cli_version = ""
    context_window = None
    for row in rollout:
        payload = row.get("payload") or {}
        if row.get("type") == "session_meta":
            cli_version = str(payload.get("cli_version") or "")
        if row.get("type") == "event_msg" and payload.get("type") == "task_started":
            context_window = payload.get("model_context_window")
            break

    turns: list[dict[str, Any]] = []
    turns_by_id: dict[str, dict[str, Any]] = {}
    model_events_by_turn: dict[str, list[datetime]] = defaultdict(list)
    for row in rollout:
        payload = row.get("payload") or {}
        row_type = row.get("type")
        payload_type = payload.get("type")
        timestamp = dt(row["timestamp"])
        if row_type == "event_msg" and payload_type == "task_started":
            turn = {
                "turn_no": len(turns) + 1,
                "turn_id": payload["turn_id"],
                "start": timestamp,
                "end": None,
                "duration_s": None,
                "ttft_s": None,
                "first_model_event": None,
                "first_visible_event": None,
                "tool_intervals": [],
                "effective_tool_intervals": [],
                "tool_count": 0,
            }
            turns.append(turn)
            turns_by_id[turn["turn_id"]] = turn
        elif row_type == "event_msg" and payload_type == "task_complete":
            turn = turns_by_id.get(payload.get("turn_id"))
            if turn:
                turn["end"] = timestamp
                turn["duration_s"] = payload.get("duration_ms", 0) / 1000
                turn["ttft_s"] = payload.get("time_to_first_token_ms", 0) / 1000
        if row_type == "response_item" and payload_type in {
            "reasoning", "custom_tool_call", "function_call", "agent_message"
        }:
            turn_id = (payload.get("internal_chat_message_metadata_passthrough") or {}).get("turn_id")
            if turn_id:
                model_events_by_turn[turn_id].append(timestamp)
        if row_type == "response_item" and payload_type == "message" and payload.get("role") == "assistant":
            turn_id = (payload.get("internal_chat_message_metadata_passthrough") or {}).get("turn_id")
            if turn_id:
                model_events_by_turn[turn_id].append(timestamp)

    calls: dict[str, dict[str, Any]] = {}
    for row in rollout:
        payload = row.get("payload") or {}
        row_type = row.get("type")
        payload_type = payload.get("type")
        timestamp = dt(row["timestamp"])
        if row_type == "response_item" and payload_type in {"custom_tool_call", "function_call"}:
            turn_id = (payload.get("internal_chat_message_metadata_passthrough") or {}).get("turn_id", "")
            if payload_type == "function_call":
                name = str(payload.get("name") or "function")
                kind = "wait_resume" if name == "wait" else "native_subagent" if name in {
                    "spawn_agent", "followup_task", "list_agents"
                } else name
                raw_input = payload.get("arguments") or ""
            else:
                name = str(payload.get("name") or "exec")
                raw_input = payload.get("input") or ""
                kind = classify_exec(str(raw_input))
            calls[payload["call_id"]] = {
                "call_id_hash": hashlib.sha256(payload["call_id"].encode()).hexdigest()[:12],
                "turn_id": turn_id,
                "start": timestamp,
                "end": None,
                "effective_end": None,
                "kind": kind,
                "name": name,
                "input_bytes": byte_len(raw_input),
                "output_bytes": 0,
                "yielded_cell_id": "",
                "raw_input": str(raw_input),
            }
        elif row_type == "response_item" and payload_type in {
            "custom_tool_call_output", "function_call_output"
        }:
            call = calls.get(payload.get("call_id"))
            if call:
                call["end"] = timestamp
                call["effective_end"] = timestamp
                raw_output = payload.get("output") or ""
                call["output_bytes"] = byte_len(raw_output)
                match = re.search(r"Script running with cell ID ([^\s]+)", flattened_text(raw_output))
                if match:
                    call["yielded_cell_id"] = match.group(1)

    yielded = {
        call["yielded_cell_id"]: call for call in calls.values() if call["yielded_cell_id"]
    }
    for call in calls.values():
        if call["kind"] != "wait_resume" or call["end"] is None:
            continue
        try:
            cell_id = str(json.loads(call["raw_input"]).get("cell_id") or "")
        except (json.JSONDecodeError, TypeError):
            cell_id = ""
        origin = yielded.get(cell_id)
        if origin:
            origin["effective_end"] = max(origin["effective_end"], call["end"])

    tool_rows: list[dict[str, Any]] = []
    for call in sorted(calls.values(), key=lambda item: item["start"]):
        end = call["end"]
        effective_end = call["effective_end"]
        duration_s = (end - call["start"]).total_seconds() if end else None
        effective_duration_s = (
            (effective_end - call["start"]).total_seconds() if effective_end else None
        )
        tool_rows.append({
            "call_id_hash": call["call_id_hash"],
            "turn_id": call["turn_id"],
            "start_utc": iso(call["start"]),
            "end_utc": iso(end),
            "duration_s": round(duration_s, 6) if duration_s is not None else "",
            "effective_end_utc": iso(effective_end),
            "effective_duration_s": round(effective_duration_s, 6) if effective_duration_s is not None else "",
            "kind": call["kind"],
            "name": call["name"],
            "input_bytes": call["input_bytes"],
            "output_bytes": call["output_bytes"],
            "yielded": bool(call["yielded_cell_id"]),
        })
        turn = turns_by_id.get(call["turn_id"])
        if turn and end:
            turn["tool_count"] += 1
            turn["tool_intervals"].append((call["start"], end))
            turn["effective_tool_intervals"].append((call["start"], effective_end or end))

    turn_rows: list[dict[str, Any]] = []
    completed_turns: list[dict[str, Any]] = []
    for turn in turns:
        model_events = model_events_by_turn.get(turn["turn_id"], [])
        turn["first_model_event"] = min(model_events) if model_events else None
        usage_row = usage.get(turn["turn_id"], {})
        raw_union = interval_union_seconds(turn["tool_intervals"])
        effective_union = interval_union_seconds(turn["effective_tool_intervals"])
        duration = turn["duration_s"]
        row = {
            "turn_no": turn["turn_no"],
            "turn_id": turn["turn_id"],
            "phase": turn_phase(turn["turn_no"]),
            "start_utc": iso(turn["start"]),
            "end_utc": iso(turn["end"]),
            "complete": bool(turn["end"]),
            "duration_s": round(duration, 6) if duration is not None else "",
            "ttft_s": round(turn["ttft_s"], 6) if turn["ttft_s"] is not None else "",
            "first_model_event_s": round(
                (turn["first_model_event"] - turn["start"]).total_seconds(), 6
            ) if turn["first_model_event"] else "",
            "tool_count": turn["tool_count"],
            "tool_blocked_union_s": round(raw_union, 6),
            "effective_tool_union_s": round(effective_union, 6),
            "residual_s": round(max(0.0, duration - effective_union), 6) if duration is not None else "",
            "ok": usage_row.get("ok", ""),
            "stop_reason": usage_row.get("stop_reason", ""),
            "input_tokens": usage_row.get("input_tokens", ""),
            "cache_read_tokens": usage_row.get("cache_read_tokens", ""),
            "output_tokens": usage_row.get("output_tokens", ""),
            "cost_usd": usage_row.get("cost_usd", ""),
            "quota_primary_pct": usage_row.get("quota_primary_pct", ""),
            "trigger_source": "",
            "trigger_payload_bytes": "",
            "queue_to_start_ms": "",
            "steered_messages": 0,
        }
        turn_rows.append(row)
        if turn["end"]:
            completed_turns.append(row)

    # Map DB-side user messages to a new turn trigger or active-turn steering.
    db_turn_starts = [
        (dt(row["ts"]), safe_status_kind(row["content"])[1])
        for row in db_logs
        if row["type"] == "status" and safe_status_kind(row["content"])[0] == "turn_start"
    ]
    db_turn_ends = [
        dt(row["ts"]) for row in db_logs
        if row["type"] == "status" and safe_status_kind(row["content"])[0] == "turn_end"
    ]
    message_rows: list[dict[str, Any]] = []
    for row in [item for item in db_logs if item["type"] == "user_message"]:
        timestamp = dt(row["ts"])
        active_start = max((start for start, _ in db_turn_starts if start <= timestamp), default=None)
        active_end = min((end for end in db_turn_ends if active_start and end >= active_start), default=None)
        steered = bool(active_start and (active_end is None or timestamp < active_end))
        mapped_turn_id = ""
        latency_ms: float | str = ""
        delivery = "steered" if steered else "new_turn_trigger"
        if steered:
            mapped_turn_id = next(
                (turn_id for start, turn_id in reversed(db_turn_starts) if start == active_start), ""
            )
            next_event = min(
                (event for event in model_events_by_turn.get(mapped_turn_id, []) if event >= timestamp),
                default=None,
            )
            if next_event:
                latency_ms = round((next_event - timestamp).total_seconds() * 1000, 3)
        else:
            next_start = min(
                ((start, turn_id) for start, turn_id in db_turn_starts if start >= timestamp),
                default=None,
            )
            if next_start:
                latency_ms = round((next_start[0] - timestamp).total_seconds() * 1000, 3)
                mapped_turn_id = next_start[1]
        message_rows.append({
            "log_id": row["id"],
            "ts_utc": row["ts"],
            "source": message_source(row["content"]),
            "payload_bytes": byte_len(row["content"]),
            "delivery": delivery,
            "turn_id": mapped_turn_id,
            "delivery_or_next_model_ms": latency_ms,
        })

    turn_row_by_id = {row["turn_id"]: row for row in turn_rows}
    for message in message_rows:
        turn_row = turn_row_by_id.get(message["turn_id"])
        if not turn_row:
            continue
        if message["delivery"] == "new_turn_trigger":
            turn_row["trigger_source"] = message["source"]
            turn_row["trigger_payload_bytes"] = message["payload_bytes"]
            turn_row["queue_to_start_ms"] = message["delivery_or_next_model_ms"]
        else:
            turn_row["steered_messages"] += 1

    context_rows: list[dict[str, Any]] = []
    compact_starts: list[datetime] = []
    compact_durations: list[float] = []
    for row in db_logs:
        if row["type"] == "status":
            kind, details = safe_status_kind(row["content"])
            if kind == "other_status":
                continue
            timestamp = dt(row["ts"])
            if kind == "context_compact_start":
                compact_starts.append(timestamp)
            if kind == "context_compact_end" and compact_starts:
                compact_durations.append((timestamp - compact_starts[-1]).total_seconds())
            context_rows.append({
                "log_id": row["id"], "ts_utc": row["ts"], "kind": kind, "details": details
            })
        elif row["type"] == "warning":
            context_rows.append({
                "log_id": row["id"], "ts_utc": row["ts"],
                "kind": warning_kind(row["content"]), "details": "",
            })

    token_counts: list[tuple[datetime, int, int]] = []
    compact_rollout_times: list[datetime] = []
    for row in rollout:
        payload = row.get("payload") or {}
        if row.get("type") == "event_msg" and payload.get("type") == "token_count":
            info = payload.get("info") or {}
            last = info.get("last_token_usage") or {}
            input_tokens = last.get("input_tokens")
            window = info.get("model_context_window")
            if isinstance(input_tokens, int) and input_tokens > 0 and isinstance(window, int):
                token_counts.append((dt(row["timestamp"]), input_tokens, window))
        elif row.get("type") == "event_msg" and payload.get("type") == "context_compacted":
            compact_rollout_times.append(dt(row["timestamp"]))
    compact_token_rows: list[dict[str, Any]] = []
    for number, timestamp in enumerate(compact_rollout_times, 1):
        before = max((item for item in token_counts if item[0] < timestamp), default=None)
        after = min((item for item in token_counts if item[0] > timestamp), default=None)
        compact_token_rows.append({
            "compact_no": number,
            "completed_utc": iso(timestamp),
            "before_input_tokens": before[1] if before else "",
            "before_pct": round(100 * before[1] / before[2], 3) if before else "",
            "after_input_tokens": after[1] if after else "",
            "after_pct": round(100 * after[1] / after[2], 3) if after else "",
            "token_drop": before[1] - after[1] if before and after else "",
        })

    mcp_rows: list[dict[str, Any]] = []
    for row in rollout:
        payload = row.get("payload") or {}
        if row.get("type") != "event_msg" or payload.get("type") != "mcp_tool_call_end":
            continue
        invocation = payload.get("invocation") or {}
        duration = payload.get("duration") or {}
        duration_s = float(duration.get("secs") or 0) + float(duration.get("nanos") or 0) / 1e9
        result = payload.get("result") or {}
        mcp_rows.append({
            "ts_utc": row["timestamp"],
            "server": invocation.get("server", ""),
            "tool": invocation.get("tool", ""),
            "duration_s": round(duration_s, 9),
            "argument_bytes": byte_len(invocation.get("arguments")),
            "result_bytes": byte_len(result),
            "result_state": "error" if "Err" in result else "ok" if "Ok" in result else "unknown",
        })

    web_rows: list[dict[str, Any]] = []
    for row in rollout:
        payload = row.get("payload") or {}
        if row.get("type") == "event_msg" and payload.get("type") == "web_search_end":
            action = payload.get("action") or {}
            web_rows.append({
                "ts_utc": row["timestamp"],
                "call_id_hash": hashlib.sha256(str(payload.get("call_id", "")).encode()).hexdigest()[:12],
                "query_bytes": byte_len(payload.get("query")),
                "query_count": len(action.get("queries") or []),
                "result_count": len(payload.get("results") or []),
            })

    bg_rows: list[dict[str, Any]] = []
    for row in conn.execute(
        """SELECT id,type,status,created_at,triggered_at,config,message,last_output,error
           FROM bg_jobs WHERE target_session_id=? ORDER BY created_at""",
        (session_id,),
    ):
        row = dict(row)
        config = json.loads(row["config"] or "{}")
        duration_s = (
            (dt(row["triggered_at"]) - dt(row["created_at"])).total_seconds()
            if row["triggered_at"] else None
        )
        command = str(config.get("command") or "")
        sandbox_match = re.search(r"(?:--sandbox|-s)\s+(?:=\s*)?([\w-]+)", command)
        sandbox_mode = (
            sandbox_match.group(1)
            if sandbox_match
            else "bypass"
            if "--dangerously-bypass-approvals-and-sandbox" in command
            else "default"
        )
        bg_rows.append({
            "job_id": row["id"],
            "created_utc": row["created_at"],
            "completed_utc": row["triggered_at"] or "",
            "duration_s": round(duration_s, 6) if duration_s is not None else "",
            "status": row["status"],
            "phase": bg_phase(row["message"]),
            "round": int(match.group(1)) if (match := re.search(r"Round (\d+)", row["message"])) else 0,
            "fresh_codex_session": bool(re.search(r"\bcodex\s+exec\b", command)) and not bool(
                re.search(r"\bcodex\s+exec\s+resume\b", command)
            ),
            "sandbox_mode": sandbox_mode,
            "config_bytes": byte_len(row["config"]),
            "message_bytes": byte_len(row["message"]),
            "output_bytes": byte_len(row["last_output"]),
            "error_class": "ProcessExit2" if row["error"] and "exit code 2" in row["error"] else "",
        })

    error_rows: list[dict[str, Any]] = []
    for row in conn.execute(
        "SELECT id,ts,tool_name,error_text,runtime FROM tool_errors WHERE session_name=? AND scope=? ORDER BY ts",
        (args.name, args.scope),
    ):
        row = dict(row)
        error_rows.append({
            "id": row["id"], "ts_utc": row["ts"], "tool": row["tool_name"],
            "category": error_category(row["error_text"] or ""),
            "error_bytes": byte_len(row["error_text"]), "runtime": row["runtime"],
        })

    payload_rows: list[dict[str, Any]] = []
    for log_type in sorted({row["type"] for row in db_logs}):
        sizes = [byte_len(row["content"]) for row in db_logs if row["type"] == log_type]
        payload_rows.append({
            "type": log_type,
            "count": len(sizes),
            "total_bytes": sum(sizes),
            "p50_bytes": int(statistics.median(sizes)) if sizes else 0,
            "p95_bytes": int(percentile(sizes, 0.95) or 0),
            "max_bytes": max(sizes) if sizes else 0,
        })

    # High-volume results and read-counts are enough to identify repeated retrieval
    # without retaining command text or the retrieved content.
    heavy_rows: list[dict[str, Any]] = []
    read_counts: Counter[str] = Counter()
    last_tool: dict[str, Any] | None = None
    for row in db_logs:
        if row["type"] == "tool":
            last_tool = row
            if row["content"].startswith("Bash: "):
                try:
                    parsed = json.loads(row["content"][6:])
                except json.JSONDecodeError:
                    parsed = {}
                for action in parsed.get("command_actions") or []:
                    if action.get("type") == "read":
                        path = str(action.get("path") or action.get("name") or "unknown")
                        if path.startswith(session["cwd"] + "/"):
                            path = path[len(session["cwd"]) + 1:]
                        read_counts[path] += 1
        elif row["type"] == "tool_result" and byte_len(row["content"]) >= 16_384:
            tool_name = (last_tool["content"].split(":", 1)[0] if last_tool else "unknown")
            heavy_rows.append({
                "log_id": row["id"], "ts_utc": row["ts"], "bytes": byte_len(row["content"]),
                "preceding_tool": tool_name,
            })
    read_rows = [{"path": path, "read_actions": count} for path, count in read_counts.most_common()]

    review_rows: list[dict[str, Any]] = []
    cutover = dt(args.quota_cutover)
    review_calls = conn.execute(
        """
        SELECT l.id,l.ts,l.session_id,s.name,s.scope,
               (SELECT r.content FROM logs r
                WHERE r.session_id=l.session_id AND r.type='tool_result' AND r.id>l.id
                ORDER BY r.id LIMIT 1) AS result
        FROM logs l JOIN sessions s ON s.id=l.session_id
        WHERE l.type='tool' AND l.content LIKE 'mcp__orchestra__codex_review:%'
          AND l.ts <= ?
        ORDER BY l.ts
        """,
        (args.evidence_cutoff,),
    ).fetchall()
    for row in review_calls:
        result = row["result"] or ""
        outcome = (
            "blocked_legacy_readiness"
            if "weekly_quota_unknown" in result and "legacy readiness" in result
            else "job_started"
            if "Background job" in result or "Codex" in result
            else "other"
        )
        review_rows.append({
            "ts_utc": row["ts"], "period": "before_cutover" if dt(row["ts"]) < cutover else "after_cutover",
            "session_name": row["name"], "scope_hash": hashlib.sha256(row["scope"].encode()).hexdigest()[:12],
            "outcome": outcome,
        })

    write_csv(args.out_dir / "turns.csv", turn_rows, list(turn_rows[0]))
    write_csv(args.out_dir / "tool_calls.csv", tool_rows, list(tool_rows[0]))
    write_csv(args.out_dir / "messages.csv", message_rows, list(message_rows[0]))
    write_csv(args.out_dir / "context_events.csv", context_rows, list(context_rows[0]))
    write_csv(args.out_dir / "compactions.csv", compact_token_rows, list(compact_token_rows[0]))
    write_csv(args.out_dir / "mcp_calls.csv", mcp_rows, list(mcp_rows[0]))
    write_csv(args.out_dir / "web_searches.csv", web_rows, list(web_rows[0]))
    write_csv(args.out_dir / "background_jobs.csv", bg_rows, list(bg_rows[0]))
    write_csv(args.out_dir / "tool_errors.csv", error_rows, list(error_rows[0]))
    write_csv(args.out_dir / "payload_sizes.csv", payload_rows, list(payload_rows[0]))
    write_csv(args.out_dir / "heavy_results.csv", heavy_rows, list(heavy_rows[0]))
    write_csv(args.out_dir / "read_counts.csv", read_rows, list(read_rows[0]))
    write_csv(args.out_dir / "codex_review_cutover.csv", review_rows, list(review_rows[0]))

    durations = [float(row["duration_s"]) for row in completed_turns]
    ttfts = [float(row["ttft_s"]) for row in completed_turns]
    output_tokens = [float(row["output_tokens"]) for row in completed_turns if row["output_tokens"] != ""]
    correlated_durations = [
        float(row["duration_s"]) for row in completed_turns if row["output_tokens"] != ""
    ]
    tool_category_durations: dict[str, list[float]] = defaultdict(list)
    for row in tool_rows:
        if row["duration_s"] != "":
            tool_category_durations[row["kind"]].append(float(row["duration_s"]))
    completed_bg_durations = [float(row["duration_s"]) for row in bg_rows if row["duration_s"] != ""]
    delivery_groups: dict[str, list[float]] = defaultdict(list)
    for row in message_rows:
        if row["delivery_or_next_model_ms"] != "":
            delivery_groups[f"{row['delivery']}:{row['source']}"] .append(
                float(row["delivery_or_next_model_ms"])
            )
    mcp_groups: dict[str, list[float]] = defaultdict(list)
    for row in mcp_rows:
        mcp_groups[row["tool"]].append(float(row["duration_s"]))
    review_counts = Counter((row["period"], row["outcome"]) for row in review_rows)
    log_payload_total = sum(row["total_bytes"] for row in payload_rows)
    raw_tool_union = sum(float(row["tool_blocked_union_s"]) for row in completed_turns)
    effective_tool_union = sum(float(row["effective_tool_union_s"]) for row in completed_turns)
    active_intervals = [
        (dt(row["start_utc"]), dt(row["end_utc"])) for row in completed_turns
    ]
    review_intervals = [
        (dt(row["created_utc"]), dt(row["completed_utc"]))
        for row in bg_rows
        if row["completed_utc"]
    ]
    elapsed_s = (
        (max(end for _, end in active_intervals) - min(start for start, _ in active_intervals)).total_seconds()
        if active_intervals else 0.0
    )
    active_union_s = interval_union_seconds(active_intervals)
    review_union_s = interval_union_seconds(review_intervals)
    review_overlap_s = interval_intersection_seconds(active_intervals, review_intervals)
    aggregate = {
        "snapshot_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "evidence_cutoff_utc": args.evidence_cutoff,
        "session": {
            "id": session_id,
            "name": session["name"],
            "scope": session["scope"],
            "cwd": session["cwd"],
            "branch": session["branch"],
            "model": session["model"],
            "backend": session["backend_type"],
            "effort": session["effort"],
            "role": session["role"],
            "created_at": session["created_at"],
            "status": session["status"],
            "context_pct": session["context_pct"],
            "context_tokens": session["context_tokens"],
            "total_input_tokens": session["total_input_tokens"],
            "total_cache_read_tokens": session["total_cache_read_tokens"],
            "total_output_tokens": session["total_output_tokens"],
            "cost_usd": session["cost_usd"],
            "system_prompt_chars": len(session.get("system_prompt") or ""),
            "cli_version": cli_version,
            "model_context_window": context_window,
            "rollout_file": args.rollout.name,
            "rollout_bytes": args.rollout.stat().st_size,
            "rollout_lines": len(rollout),
        },
        "turns": {
            "started": len(turns),
            "completed": len(completed_turns),
            "incomplete": len(turns) - len(completed_turns),
            "duration_s": stats(durations),
            "ttft_s": stats(ttfts),
            "active_wall_s": round(sum(durations), 6),
            "tool_blocked_union_s": round(raw_tool_union, 6),
            "effective_tool_union_s": round(effective_tool_union, 6),
            "effective_tool_share_pct": round(100 * effective_tool_union / sum(durations), 3),
            "residual_share_pct": round(100 * (sum(durations) - effective_tool_union) / sum(durations), 3),
            "output_tokens_per_active_second": round(sum(output_tokens) / sum(durations), 6),
            "duration_output_token_pearson": pearson(correlated_durations, output_tokens),
            "ok_count": sum(int(row["ok"]) for row in completed_turns if row["ok"] != ""),
        },
        "wall_clock": {
            "first_turn_start_to_last_end_s": round(elapsed_s, 6),
            "active_turn_union_s": round(active_union_s, 6),
            "inactive_s": round(elapsed_s - active_union_s, 6),
            "completed_review_union_s": round(review_union_s, 6),
            "review_overlap_with_active_s": round(review_overlap_s, 6),
            "review_outside_active_s": round(review_union_s - review_overlap_s, 6),
        },
        "delivery_ms": {name: stats(values) for name, values in sorted(delivery_groups.items())},
        "tools": {
            "calls": len(tool_rows),
            "category_duration_s": {
                name: stats(values) for name, values in sorted(tool_category_durations.items())
            },
        },
        "mcp": {
            "calls": len(mcp_rows),
            "errors": sum(row["result_state"] == "error" for row in mcp_rows),
            "duration_s": stats(float(row["duration_s"]) for row in mcp_rows),
            "by_tool_duration_s": {name: stats(values) for name, values in sorted(mcp_groups.items())},
        },
        "background_reviews": {
            "jobs": len(bg_rows),
            "completed": len(completed_bg_durations),
            "failed": sum(row["status"] == "failed" for row in bg_rows),
            "fresh_codex_sessions": sum(row["fresh_codex_session"] for row in bg_rows),
            "duration_s": stats(completed_bg_durations),
        },
        "context": {
            "compactions": len(compact_durations),
            "compaction_duration_s": stats(compact_durations),
            "precompact_scheduled": sum(row["kind"] == "precompact_scheduled" for row in context_rows),
            "precompact_cancelled": sum(row["kind"] == "precompact_cancelled" for row in context_rows),
        },
        "payloads": {
            "db_log_rows": len(db_logs),
            "db_log_content_bytes": log_payload_total,
            "tool_result_bytes": sum(
                row["total_bytes"] for row in payload_rows if row["type"] == "tool_result"
            ),
            "tool_results_ge_16k": len(heavy_rows),
            "tool_results_ge_16k_bytes": sum(row["bytes"] for row in heavy_rows),
            "read_actions": sum(read_counts.values()),
            "unique_read_paths": len(read_counts),
        },
        "errors": {
            "warnings": dict(Counter(row["kind"] for row in context_rows if "warning" in row["kind"] or "fallback" in row["kind"] or "cancelled" in row["kind"])),
            "tool_errors": dict(Counter(row["category"] for row in error_rows)),
        },
        "codex_review_cutover": {
            "cutover_utc": args.quota_cutover,
            "counts": {f"{period}:{outcome}": count for (period, outcome), count in sorted(review_counts.items())},
        },
    }
    with (args.out_dir / "aggregate.json").open("w", encoding="utf-8") as handle:
        json.dump(aggregate, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps(aggregate, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
