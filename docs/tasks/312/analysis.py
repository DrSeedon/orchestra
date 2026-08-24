#!/usr/bin/env python3
"""Retrospective #312 analysis using only the frozen SQLite backup and saved rollouts."""

from __future__ import annotations

import bisect
import csv
import datetime as dt
import hashlib
import json
import math
import re
import sqlite3
import statistics
import subprocess
from collections import Counter, defaultdict
from pathlib import Path


HERE = Path(__file__).resolve().parent
DB = HERE / "private" / "orchestra-20260824.sqlite"
MANIFEST = HERE / "backup-manifest.json"
ROLLOUTS = Path("/home/maxim/.codex/sessions")

# The old quota window reset at 07:26:39Z; the first persisted zero is the clean
# lower boundary. The config became effective on restart, proven by rollout metadata.
SCHEDULED_RESET = "2026-08-23T07:28:43.476971+00:00"
RESTART_RESTORED = "2026-08-23T09:04:11.935666+00:00"
FIRST_NEW_START = "2026-08-23T09:04:18.168000+00:00"
CUTOFF = "2026-08-24T06:54:34.857943+00:00"
NEW_RESET_FIRST_OBSERVED = "2026-08-24T03:47:54.383255+00:00"
OLD_RESET_LAST_OBSERVED = "2026-08-23T17:21:03.173296+00:00"

# Equal-duration immediate windows. They stay in the same plan/revision and avoid
# the later #240 benchmark burst, unplanned reset, and image-heavy incident.
CORE_PRE_START = SCHEDULED_RESET
CORE_PRE_END = FIRST_NEW_START
_CORE_DURATION = dt.datetime.fromisoformat(CORE_PRE_END) - dt.datetime.fromisoformat(CORE_PRE_START)
CORE_POST_START = FIRST_NEW_START
CORE_POST_END = (dt.datetime.fromisoformat(CORE_POST_START) + _CORE_DURATION).isoformat()

IMAGE_INCIDENT_SESSIONS = {
    "47f075de-28d3-482e-9513-c172a03b4a3e",  # COG oversized thread/resume
    "e6118c26-c52f-405e-8047-85bd839ba0f7",  # comfy image-heavy compact timeout
}
IMAGE_INCIDENT_START = "2026-08-24T05:14:41.248751+00:00"
DIAGNOSTIC_TASKS = {"240", "255", "312"}

WINDOW_OLD = 258_400
WINDOW_NEW = 828_400
RAW_OLD = 272_000
RAW_NEW = 872_000

# Current official ChatGPT credit rate card, credits per million tokens.
CREDIT_RATES = {
    "gpt-5.6-sol": (100.0, 10.0, 500.0),
    "gpt-5.6-luna": (5.0, 0.5, 30.0),
    "gpt-5.6-terra": (50.0, 5.0, 300.0),
}


def parse_ts(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def epoch(value: str) -> float:
    return parse_ts(value).timestamp()


def median(values):
    clean = [value for value in values if value is not None]
    return statistics.median(clean) if clean else None


def percentile(values, fraction: float):
    clean = sorted(value for value in values if value is not None)
    if not clean:
        return None
    return clean[max(0, math.ceil(len(clean) * fraction) - 1)]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_database():
    db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    usage = [
        dict(row)
        for row in db.execute(
            """
            SELECT u.*, s.name AS worker, s.role, s.pipeline,
                   s.scope AS session_scope
            FROM turn_usage u
            LEFT JOIN sessions s ON s.id=u.session_id
            WHERE u.runtime='codex' AND u.ts>=? AND u.ts<=?
            ORDER BY u.ts
            """,
            (SCHEDULED_RESET, CUTOFF),
        )
    ]

    logs: dict[str, list[dict]] = defaultdict(list)
    for row in db.execute(
        """
        SELECT session_id,ts,type,content
        FROM logs
        WHERE ts>=? AND ts<=?
          AND type IN ('status','error','warning','text','user_message','tool')
        ORDER BY session_id,ts
        """,
        (SCHEDULED_RESET, CUTOFF),
    ):
        logs[str(row[0])].append(
            {"ts": str(row[1]), "epoch": epoch(str(row[1])), "type": str(row[2]), "content": str(row[3])}
        )

    projects = [dict(row) for row in db.execute("SELECT id,name,scope FROM tm_projects")]
    project_by_scope = {
        str(row["scope"] or "").casefold(): str(row["id"])
        for row in projects
        if row["scope"]
    }
    project_by_scope["/mnt/data/projects/python/orchestra"] = "orchestra"
    tasks = {
        (str(row["project_id"]), str(row["par_number"])): dict(row)
        for row in db.execute(
            "SELECT project_id,par_number,status,title,created_at,updated_at,completed_at FROM tm_tasks"
        )
    }

    snapshots = []
    for row in db.execute(
        "SELECT ts,provider_usage FROM usage_snapshots WHERE ts>=? AND ts<=? ORDER BY ts",
        (SCHEDULED_RESET, CUTOFF),
    ):
        try:
            codex = (json.loads(str(row[1])) or {}).get("codex") or {}
        except json.JSONDecodeError:
            codex = {}
        windows = codex.get("windows") or []
        primary = windows[0] if windows else {}
        snapshots.append(
            {
                "ts": str(row[0]),
                "epoch": epoch(str(row[0])),
                "plan_type": codex.get("plan_type"),
                "utilization": primary.get("utilization"),
                "resets_at": primary.get("resets_at"),
                "window_minutes": primary.get("window_minutes"),
                "valid": bool(primary) and primary.get("utilization") is not None,
            }
        )
    return db, usage, logs, project_by_scope, tasks, snapshots


def scan_rollouts(target_ids: set[str]):
    found: dict[str, dict] = defaultdict(dict)
    files = bytes_read = relevant = 0
    conflicts = []
    markers = (
        b'"type":"task_started"',
        b'"type":"task_complete"',
        b'"type":"turn_context"',
        b'"type":"token_count"',
    )
    for path in ROLLOUTS.rglob("*.jsonl"):
        files += 1
        active_turn = None
        try:
            with path.open("rb") as handle:
                for line in handle:
                    bytes_read += len(line)
                    if not any(marker in line[:512] for marker in markers):
                        continue
                    if len(line) > 8 * 1024 * 1024:
                        continue
                    try:
                        row = json.loads(line)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        continue
                    payload = row.get("payload") or {}
                    row_type = row.get("type")
                    payload_type = payload.get("type")
                    if row_type == "event_msg" and payload_type == "task_started":
                        turn_id = str(payload.get("turn_id") or "")
                        active_turn = turn_id if turn_id in target_ids else None
                        if active_turn:
                            relevant += 1
                            found[turn_id].update(
                                start_ts=row.get("timestamp"),
                                configured_effective_ceiling=payload.get("model_context_window"),
                                rollout_path=str(path),
                            )
                    elif row_type == "turn_context":
                        turn_id = str(payload.get("turn_id") or "")
                        if turn_id in target_ids:
                            relevant += 1
                            found[turn_id].update(
                                effort=payload.get("effort"),
                                rollout_model=payload.get("model"),
                                cwd=payload.get("cwd"),
                                rollout_path=str(path),
                            )
                    elif row_type == "event_msg" and payload_type == "token_count" and active_turn:
                        info = payload.get("info") or {}
                        last = info.get("last_token_usage") or {}
                        slot = found[active_turn]
                        relevant += 1
                        if last.get("input_tokens") is not None:
                            candidate = int(last["input_tokens"])
                            if candidate >= int(slot.get("max_request_input_tokens") or -1):
                                slot["max_request_input_tokens"] = candidate
                                slot["max_request_cached_tokens"] = last.get("cached_input_tokens")
                                slot["max_request_output_tokens"] = last.get("output_tokens")
                                slot["max_request_reasoning_tokens"] = last.get("reasoning_output_tokens")
                        slot["token_count_context_window"] = info.get("model_context_window")
                    elif row_type == "event_msg" and payload_type == "task_complete":
                        turn_id = str(payload.get("turn_id") or "")
                        if turn_id in target_ids:
                            relevant += 1
                            slot = found[turn_id]
                            values = {
                                "end_ts": row.get("timestamp"),
                                "wall_seconds": (payload.get("duration_ms") or 0) / 1000,
                                "ttft_seconds": (payload.get("time_to_first_token_ms") or 0) / 1000,
                                "rollout_path": str(path),
                            }
                            for key, value in values.items():
                                if key in slot and slot[key] != value and key != "rollout_path":
                                    conflicts.append([turn_id, key, slot[key], value])
                                slot[key] = value
                        if active_turn == turn_id:
                            active_turn = None
        except OSError:
            continue
    return dict(found), {
        "files": files,
        "bytes_read": bytes_read,
        "relevant_records": relevant,
        "turns_found": len(found),
        "conflicts": conflicts[:20],
    }


def classify_status(events: list[dict], kind: str) -> str:
    counts = Counter()
    for event in events:
        if kind == "resume":
            if event["type"] not in {"status", "error", "warning", "user_message"}:
                continue
        elif event["type"] not in {"status", "error", "warning"}:
            continue
        content = event["content"].casefold()
        if kind == "precompact":
            if "precompact timer" not in content:
                continue
            for key in ("scheduled", "cancelled", "compacted", "failed"):
                if key in content:
                    counts[key] += 1
                    break
        elif kind == "compact":
            if "precompact" in content:
                continue
            mapping = (
                ("native codex compact failed", "failed"),
                ("compact started", "started"),
                ("compact done", "done"),
                ("codex compacting context", "started"),
                ("codex context compacted", "done"),
            )
            for needle, key in mapping:
                if needle in content:
                    counts[key] += 1
                    break
        elif kind == "resume":
            if "server restarted" in content:
                counts["server_restored"] += 1
            elif "resum" in content:
                counts["resume_marker"] += 1
        elif kind == "connect":
            if "connect failed" in content or "backend connect failed" in content:
                counts["failed"] += 1
            elif "reconnect" in content:
                counts["reconnect"] += 1
        elif kind == "reader":
            if "reader failure" in content or "oversized jsonl" in content:
                counts["failed"] += 1
        elif kind == "timeout":
            if "timeout" in content or "timed out" in content or "exceeded 120" in content:
                counts["timeout"] += 1
        elif kind == "error":
            if event["type"] == "error":
                counts["log_error"] += 1
            elif "server_error" in content:
                counts["server_error"] += 1
            elif "usage limit" in content or "rate limit" in content:
                counts["limit"] += 1
    return ";".join(f"{key}={counts[key]}" for key in sorted(counts)) or "none"


def credit_equivalent(row: dict) -> float | None:
    rates = CREDIT_RATES.get(str(row.get("model")))
    if not rates:
        return None
    input_rate, cached_rate, output_rate = rates
    total_input = int(row.get("input_tokens") or 0)
    cached = int(row.get("cache_read_tokens") or 0)
    uncached = max(0, total_input - cached)
    output = int(row.get("output_tokens") or 0)
    return (uncached * input_rate + cached * cached_rate + output * output_rate) / 1_000_000


def reset_cause(resets_at: str | None) -> str:
    if resets_at == "2026-08-30T07:28:42Z":
        return "scheduled_reset_2026-08-23_same_pro_revision"
    if resets_at == "2026-08-31T00:51:01Z":
        return "unscheduled_provider_side_reset_cause_UNKNOWN"
    return "UNKNOWN"


def build_rows(usage, rollout, logs, project_by_scope, tasks, snapshots):
    snap_epochs = [item["epoch"] for item in snapshots]
    rows = []
    per_session_previous_end: dict[str, float] = {}
    # Native start order is the event order. Missing rollouts fall back to usage completion order.
    enriched = []
    for item in usage:
        extra = rollout.get(str(item["event_id"]), {})
        enriched.append({**item, **extra})
    enriched.sort(key=lambda row: epoch(row.get("start_ts") or row["ts"]))

    for row in enriched:
        sid = str(row["session_id"])
        start_epoch = epoch(row.get("start_ts") or row["ts"])
        end_epoch = epoch(row.get("end_ts") or row["ts"])
        envelope_start = per_session_previous_end.get(sid, max(epoch(SCHEDULED_RESET), start_epoch - 1800))
        per_session_previous_end[sid] = max(end_epoch, per_session_previous_end.get(sid, 0))
        session_events = logs.get(sid, [])
        event_epochs = [event["epoch"] for event in session_events]
        left = bisect.bisect_right(event_epochs, envelope_start)
        right = bisect.bisect_right(event_epochs, end_epoch)
        envelope = session_events[left:right]
        during_left = bisect.bisect_left(event_epochs, start_epoch)
        during = session_events[during_left:right]

        scope = str(row.get("scope") or row.get("session_scope") or row.get("cwd") or "")
        project_id = project_by_scope.get(scope.casefold(), "")
        task_key = (project_id, str(row.get("task_id") or ""))
        task = tasks.get(task_key) or {}

        snap_pos = bisect.bisect_right(snap_epochs, end_epoch) - 1
        snapshot = snapshots[snap_pos] if snap_pos >= 0 else {}
        configured = row.get("configured_effective_ceiling")
        raw_ceiling = RAW_OLD if configured == WINDOW_OLD else RAW_NEW if configured == WINDOW_NEW else None
        assistant_bytes = sum(len(event["content"].encode()) for event in during if event["type"] == "text")
        tool_rounds = sum(event["type"] == "tool" for event in during)
        if row.get("ok") and str(row.get("stop_reason")) == "end_turn":
            final_proxy = "completed_with_assistant" if assistant_bytes else "completed_no_logged_assistant"
        elif str(row.get("stop_reason")) == "interrupted":
            final_proxy = "interrupted"
        else:
            final_proxy = "error_or_other"

        ts_for_window = row.get("start_ts") or row["ts"]
        if CORE_PRE_START <= ts_for_window < CORE_PRE_END:
            core = "core_pre"
        elif CORE_POST_START <= ts_for_window < CORE_POST_END:
            core = "core_post"
        else:
            core = "outside_core"
        if ts_for_window < FIRST_NEW_START:
            window = "pre_258400"
        elif ts_for_window < NEW_RESET_FIRST_OBSERVED:
            window = "post_828400_before_unscheduled_reset"
        else:
            window = "post_828400_after_unscheduled_reset"

        exclusion = []
        if sid in IMAGE_INCIDENT_SESSIONS:
            exclusion.append("image_incident_session_sensitivity")
        if str(row.get("task_id") or "") in DIAGNOSTIC_TASKS:
            exclusion.append("context_or_latency_diagnostic_task")
        if not row.get("start_ts") or not row.get("end_ts"):
            exclusion.append("missing_complete_rollout_interval")
        row.update(
            project=project_id or scope,
            task_pipeline_class=f"{row.get('role') or 'unknown'}:{row.get('pipeline') or 'unknown'}",
            task_status_at_cutoff=task.get("status") or "unobserved",
            task_title_present=bool(task.get("title")),
            start_ts=row.get("start_ts"),
            end_ts=row.get("end_ts"),
            usage_ts=row.get("ts"),
            configured_raw_ceiling=raw_ceiling,
            configured_effective_ceiling=configured,
            actual_input_tokens_total=int(row.get("input_tokens") or 0),
            actual_cached_input_tokens=int(row.get("cache_read_tokens") or 0),
            actual_uncached_input_tokens=max(
                0, int(row.get("input_tokens") or 0) - int(row.get("cache_read_tokens") or 0)
            ),
            actual_output_tokens=int(row.get("output_tokens") or 0),
            credit_equivalent=credit_equivalent(row),
            api_virtual_usd=row.get("cost_usd"),
            precompact_outcome=classify_status(envelope, "precompact"),
            compact_outcome=classify_status(envelope, "compact"),
            resume_outcome=classify_status(envelope, "resume"),
            connect_outcome=classify_status(envelope, "connect"),
            reader_outcome=classify_status(envelope, "reader"),
            timeout_outcome=classify_status(envelope, "timeout"),
            error_outcome=classify_status(envelope, "error"),
            tool_rounds=tool_rounds,
            assistant_text_bytes=assistant_bytes,
            final_outcome_proxy=final_proxy,
            quota_plan=snapshot.get("plan_type") if snapshot.get("valid") else None,
            quota_utilization=snapshot.get("utilization") if snapshot.get("valid") else row.get("quota_primary_pct"),
            quota_revision=snapshot.get("resets_at") if snapshot.get("valid") else None,
            quota_reset_cause=reset_cause(snapshot.get("resets_at") if snapshot.get("valid") else None),
            machine_account_coverage="VPS_turn_usage_only__shared_account_and_direct_CLI_unobserved",
            analysis_window=window,
            core_cohort=core,
            sensitivity_exclusion=";".join(exclusion) or "none",
            image_incident_period=(sid in IMAGE_INCIDENT_SESSIONS and ts_for_window >= IMAGE_INCIDENT_START),
        )
        rows.append(row)
    return rows


def cohort_stats(rows: list[dict]):
    return {
        "n": len(rows),
        "complete_rollout_n": sum(bool(row.get("start_ts") and row.get("end_ts")) for row in rows),
        "ok_n": sum(bool(row.get("ok")) for row in rows),
        "end_turn_n": sum(row.get("stop_reason") == "end_turn" for row in rows),
        "completion_rate": sum(row.get("stop_reason") == "end_turn" for row in rows) / len(rows) if rows else None,
        "ttft_median_s": median(row.get("ttft_seconds") for row in rows),
        "ttft_p90_s": percentile((row.get("ttft_seconds") for row in rows), 0.90),
        "wall_median_s": median(row.get("wall_seconds") for row in rows),
        "wall_p90_s": percentile((row.get("wall_seconds") for row in rows), 0.90),
        "tool_rounds_median": median(row.get("tool_rounds") for row in rows),
        "max_request_input_median": median(row.get("max_request_input_tokens") for row in rows),
        "max_request_input_p90": percentile((row.get("max_request_input_tokens") for row in rows), 0.90),
        "turn_input_median": median(row.get("actual_input_tokens_total") for row in rows),
        "turn_output_median": median(row.get("actual_output_tokens") for row in rows),
        "input_sum": sum(row.get("actual_input_tokens_total") or 0 for row in rows),
        "cached_sum": sum(row.get("actual_cached_input_tokens") or 0 for row in rows),
        "output_sum": sum(row.get("actual_output_tokens") or 0 for row in rows),
        "credit_equivalent_sum": sum(row.get("credit_equivalent") or 0 for row in rows),
        "api_virtual_usd_sum": sum(row.get("api_virtual_usd") or 0 for row in rows),
        "configured_windows": dict(Counter(str(row.get("configured_effective_ceiling") or "unobserved") for row in rows)),
        "models": dict(Counter(str(row.get("model") or "unobserved") for row in rows)),
        "efforts": dict(Counter(str(row.get("effort") or "unobserved") for row in rows)),
        "roles": dict(Counter(str(row.get("role") or "unobserved") for row in rows)),
        "tasks": dict(Counter(str(row.get("task_id") or "no_task") for row in rows)),
        "projects": dict(Counter(str(row.get("project") or "unobserved") for row in rows)),
        "precompact_non_none": sum(row.get("precompact_outcome") != "none" for row in rows),
        "compact_non_none": sum(row.get("compact_outcome") != "none" for row in rows),
        "connect_non_none": sum(row.get("connect_outcome") != "none" for row in rows),
        "reader_non_none": sum(row.get("reader_outcome") != "none" for row in rows),
        "timeout_non_none": sum(row.get("timeout_outcome") != "none" for row in rows),
        "error_non_none": sum(row.get("error_outcome") != "none" for row in rows),
    }


def quota_span(snapshots: list[dict], start: str, end: str):
    valid = [row for row in snapshots if row["valid"]]
    start_epoch = epoch(start)
    end_epoch = epoch(end)
    before = [row for row in valid if row["epoch"] <= start_epoch]
    inside_end = [row for row in valid if row["epoch"] < end_epoch]
    if not before or not inside_end:
        return {"status": "unobserved"}
    first = before[-1]
    last = inside_end[-1]
    same_revision = first["resets_at"] == last["resets_at"] and first["plan_type"] == last["plan_type"]
    duration_hours = (end_epoch - start_epoch) / 3600
    delta = last["utilization"] - first["utilization"] if same_revision else None
    return {
        "start_requested": start,
        "end_requested": end,
        "start_anchor": first,
        "end_anchor": last,
        "same_plan_revision": same_revision,
        "delta_percentage_points": delta,
        "requested_duration_hours": duration_hours,
        "pp_per_requested_hour": delta / duration_hours if delta is not None else None,
    }


def matched_sessions(rows: list[dict]):
    pre = defaultdict(list)
    post = defaultdict(list)
    for row in rows:
        key = (row["session_id"], row.get("model"), row.get("effort"), row.get("role"))
        if row["core_cohort"] == "core_pre":
            pre[key].append(row)
        elif row["core_cohort"] == "core_post":
            post[key].append(row)
    result = []
    for key in sorted(set(pre) & set(post)):
        a, b = pre[key], post[key]
        result.append(
            {
                "session_id": key[0],
                "worker": a[0].get("worker"),
                "model": key[1],
                "effort": key[2],
                "role": key[3],
                "pre_n": len(a),
                "post_n": len(b),
                "pre_ttft_median_s": median(row.get("ttft_seconds") for row in a),
                "post_ttft_median_s": median(row.get("ttft_seconds") for row in b),
                "pre_wall_median_s": median(row.get("wall_seconds") for row in a),
                "post_wall_median_s": median(row.get("wall_seconds") for row in b),
                "pre_max_request_input_median": median(row.get("max_request_input_tokens") for row in a),
                "post_max_request_input_median": median(row.get("max_request_input_tokens") for row in b),
                "pre_tools_median": median(row.get("tool_rounds") for row in a),
                "post_tools_median": median(row.get("tool_rounds") for row in b),
                "pre_completion_rate": sum(row.get("stop_reason") == "end_turn" for row in a) / len(a),
                "post_completion_rate": sum(row.get("stop_reason") == "end_turn" for row in b) / len(b),
            }
        )
    return result


def request_size_strata(rows: list[dict]):
    result = {}
    for side in ("core_pre", "core_post"):
        for label, predicate in (
            ("at_or_below_old_ceiling", lambda value: value <= WINDOW_OLD),
            ("above_old_ceiling", lambda value: value > WINDOW_OLD),
        ):
            cohort = [
                row for row in rows
                if row["core_cohort"] == side
                and row.get("model") == "gpt-5.6-sol"
                and row.get("effort") == "xhigh"
                and row.get("max_request_input_tokens") is not None
                and predicate(int(row["max_request_input_tokens"]))
            ]
            result[f"{side}|{label}|sol|xhigh"] = cohort_stats(cohort)
    return result


def interruption_clusters(rows: list[dict]):
    interrupted = [
        row for row in rows
        if row["analysis_window"] == "post_828400_before_unscheduled_reset"
        and row.get("stop_reason") != "end_turn"
    ]
    clusters = Counter()
    for row in interrupted:
        stamp = str(row.get("usage_ts") or "")
        if stamp.startswith("2026-08-23T11:21") or stamp.startswith("2026-08-23T11:22") or stamp.startswith("2026-08-23T11:24"):
            clusters["fleet_server_error_11:21-11:24"] += 1
        elif stamp.startswith("2026-08-23T16:42"):
            clusters["fleet_server_or_restart_cluster_16:42"] += 1
        else:
            clusters["other"] += 1
    return {"total": len(interrupted), "clusters": dict(clusters)}


def direct_240_evidence():
    rows = []
    for path in sorted((HERE.parent / "240").glob("raw*.jsonl")):
        for line in path.read_text().splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("input_tokens") is not None:
                rows.append({**row, "source": str(path.relative_to(HERE.parents[2]))})
    review_usage = []
    with sqlite3.connect(f"file:{DB}?mode=ro", uri=True) as db:
        for ts, content in db.execute(
            """
            SELECT ts,content FROM logs
            WHERE type='user_message' AND ts>=? AND ts<=?
              AND content LIKE '%docs/tasks/240/review-research.md%'
              AND content LIKE '%\"type\":\"turn.completed\"%'
            ORDER BY ts
            """,
            (FIRST_NEW_START, CUTOFF),
        ):
            match = re.search(r'\"usage\":\{\"input_tokens\":(\d+),\"cached_input_tokens\":(\d+).*?\"output_tokens\":(\d+)', content)
            if match:
                review_usage.append(
                    {
                        "ts": ts,
                        "input_tokens": int(match.group(1)),
                        "cached_input_tokens": int(match.group(2)),
                        "output_tokens": int(match.group(3)),
                    }
                )
    return {
        "raw_token_bearing_calls": len(rows),
        "raw_input_tokens": sum(row.get("input_tokens") or 0 for row in rows),
        "raw_cached_tokens_known": sum(row.get("cached_tokens") or 0 for row in rows),
        "raw_cached_missing_n": sum(row.get("cached_tokens") is None for row in rows),
        "raw_output_tokens": sum(row.get("output_tokens") or 0 for row in rows),
        "review_calls": len(review_usage),
        "review_usage": review_usage,
        "review_input_tokens": sum(row["input_tokens"] for row in review_usage),
        "review_cached_tokens": sum(row["cached_input_tokens"] for row in review_usage),
        "review_output_tokens": sum(row["output_tokens"] for row in review_usage),
        "unmeasured_reconnect_warmups": 2,
        "coverage_note": "#240 measured 28 benchmark model turns: 26 token-bearing raw rows plus 2 reconnect warmups without token fields; two later reviewer calls are separate.",
    }


def incident_evidence(db):
    rows = []
    for row in db.execute(
        """
        SELECT ts,type,session_id,content FROM logs
        WHERE ts>=? AND ts<=?
          AND session_id IN (?,?)
          AND (content LIKE '%oversized JSONL%' OR content LIKE 'compact started%'
               OR content LIKE 'compact done%' OR content LIKE 'native Codex compact failed:%')
        ORDER BY ts
        """,
        (IMAGE_INCIDENT_START, CUTOFF, *sorted(IMAGE_INCIDENT_SESSIONS)),
    ):
        content = str(row[3])
        if "oversized JSONL" in content:
            category = "oversized_reader_failure"
        elif content.startswith("compact started"):
            category = "compact_started"
        elif content.startswith("compact done"):
            category = "compact_done"
        else:
            category = "compact_failed_blank_detail"
        rows.append({"ts": row[0], "type": row[1], "session_id": row[2], "category": category})
    return rows


def write_csv(rows: list[dict], matched: list[dict]):
    fields = [
        "session_id", "event_id", "worker", "usage_ts", "start_ts", "end_ts", "project",
        "model", "effort", "role", "task_id", "task_pipeline_class", "task_status_at_cutoff",
        "configured_raw_ceiling", "configured_effective_ceiling", "actual_input_tokens_total",
        "actual_cached_input_tokens", "actual_uncached_input_tokens", "actual_output_tokens",
        "max_request_input_tokens", "max_request_cached_tokens", "max_request_output_tokens",
        "max_request_reasoning_tokens", "precompact_outcome", "compact_outcome", "resume_outcome",
        "connect_outcome", "reader_outcome", "timeout_outcome", "error_outcome", "tool_rounds",
        "assistant_text_bytes", "ok", "stop_reason", "final_outcome_proxy", "wall_seconds",
        "ttft_seconds", "credit_equivalent", "api_virtual_usd", "quota_plan", "quota_utilization",
        "quota_revision", "quota_reset_cause", "machine_account_coverage", "analysis_window",
        "core_cohort", "sensitivity_exclusion", "image_incident_period", "rollout_path",
    ]
    with (HERE / "turns.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    if matched:
        with (HERE / "matched-sessions.csv").open("w", newline="") as handle:
            writer = csv.DictWriter(handle, list(matched[0]), lineterminator="\n")
            writer.writeheader()
            writer.writerows(matched)


def write_change_point(rollout: dict):
    starts = sorted(
        (
            (str(row.get("start_ts")), int(row.get("configured_effective_ceiling")))
            for row in rollout.values()
            if row.get("start_ts") and row.get("configured_effective_ceiling") in {WINDOW_OLD, WINDOW_NEW}
        ),
        key=lambda item: item[0],
    )
    last_old = max((item for item in starts if item[1] == WINDOW_OLD), default=None)
    first_new = min((item for item in starts if item[1] == WINDOW_NEW), default=None)
    commit = subprocess.run(
        ["git", "show", "-s", "--format=%H%n%aI%n%cI%n%s", "c3e66f162ce324877e245d4c75b298a229a68672"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.splitlines()
    evidence = {
        "implementation_commit": {
            "sha": commit[0], "author_date": commit[1], "commit_date": commit[2], "subject": commit[3]
        },
        "last_completed_old_window_task_start": last_old,
        "restart_user_request_log": "2026-08-23T09:02:34.711302+00:00",
        "restart_action_text_log": "2026-08-23T09:03:34.834024+00:00",
        "restart_restored_system_message": RESTART_RESTORED,
        "first_new_window_task_start": first_new,
        "gap_last_old_to_first_new_seconds": epoch(first_new[0]) - epoch(last_old[0]) if first_new and last_old else None,
        "journal_limit": "The current journal starts at boot 2026-08-23T11:25:42Z, so the 09:03 systemd Started line is no longer retained; DB restoration and native rollout metadata bound the change point.",
        "config_semantics": {
            "old_raw": RAW_OLD,
            "old_effective": WINDOW_OLD,
            "new_raw": RAW_NEW,
            "new_effective": WINDOW_NEW,
            "new_auto_compact": 784_800,
        },
    }
    (HERE / "change-point.json").write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n")


def main():
    manifest = json.loads(MANIFEST.read_text())
    if sha256(DB) != manifest["sha256"]:
        raise SystemExit("frozen DB hash mismatch")
    db, usage, logs, project_by_scope, tasks, snapshots = load_database()
    rollout, rollout_meta = scan_rollouts({str(row["event_id"]) for row in usage})
    rows = build_rows(usage, rollout, logs, project_by_scope, tasks, snapshots)
    matched = matched_sessions(rows)
    write_csv(rows, matched)
    write_change_point(rollout)

    cohorts = {
        "core_pre_all": [row for row in rows if row["core_cohort"] == "core_pre"],
        "core_post_all": [row for row in rows if row["core_cohort"] == "core_post"],
        "core_pre_sensitivity": [
            row for row in rows if row["core_cohort"] == "core_pre" and row["sensitivity_exclusion"] == "none"
        ],
        "core_post_sensitivity": [
            row for row in rows if row["core_cohort"] == "core_post" and row["sensitivity_exclusion"] == "none"
        ],
        "all_pre": [row for row in rows if row["analysis_window"] == "pre_258400"],
        "all_post_before_unscheduled_reset": [
            row for row in rows if row["analysis_window"] == "post_828400_before_unscheduled_reset"
        ],
        "all_post_after_unscheduled_reset": [
            row for row in rows if row["analysis_window"] == "post_828400_after_unscheduled_reset"
        ],
    }
    strata = {}
    for role in ("orchestrator", "full-cycle", "worker"):
        for effort in ("high", "xhigh"):
            for side in ("core_pre", "core_post"):
                key = f"{side}|role={role}|effort={effort}|sol"
                strata[key] = cohort_stats(
                    [
                        row for row in rows
                        if row["core_cohort"] == side and row.get("role") == role
                        and row.get("effort") == effort and row.get("model") == "gpt-5.6-sol"
                    ]
                )

    quota = {
        "core_pre": quota_span(snapshots, CORE_PRE_START, CORE_PRE_END),
        "core_post": quota_span(snapshots, CORE_POST_START, CORE_POST_END),
        "post_until_last_old_revision": quota_span(snapshots, CORE_POST_START, OLD_RESET_LAST_OBSERVED),
        "resets": [
            {
                "first_observed": SCHEDULED_RESET,
                "resets_at": "2026-08-30T07:28:42Z",
                "cause": "scheduled weekly reset; plan_type=pro",
            },
            {
                "first_observed": NEW_RESET_FIRST_OBSERVED,
                "resets_at": "2026-08-31T00:51:01Z",
                "cause": "UNKNOWN unscheduled provider-side reset; no redemption evidence in retained user logs",
            },
        ],
    }
    artifact = {
        "meta": {
            "db_sha256": manifest["sha256"],
            "cutoff": CUTOFF,
            "rows": len(rows),
            "rollout_complete_rows": sum(bool(row.get("start_ts") and row.get("end_ts")) for row in rows),
            "core_pre": [CORE_PRE_START, CORE_PRE_END],
            "core_post": [CORE_POST_START, CORE_POST_END],
            "core_duration_seconds": _CORE_DURATION.total_seconds(),
            "rollout": rollout_meta,
        },
        "cohorts": {key: cohort_stats(value) for key, value in cohorts.items()},
        "strata": strata,
        "matched_sessions": matched,
        "request_size_strata": request_size_strata(rows),
        "post_interruption_clusters": interruption_clusters(rows),
        "quota": quota,
        "direct_240": direct_240_evidence(),
        "image_incident": incident_evidence(db),
    }
    (HERE / "summary.json").write_text(json.dumps(artifact, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    db.close()
    print(
        json.dumps(
            {
                "rows": len(rows),
                "rollout_complete": artifact["meta"]["rollout_complete_rows"],
                "core_pre_n": artifact["cohorts"]["core_pre_all"]["n"],
                "core_post_n": artifact["cohorts"]["core_post_all"]["n"],
                "matched_sessions": len(matched),
                "db_sha256": manifest["sha256"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
