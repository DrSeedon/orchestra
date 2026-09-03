#!/usr/bin/env python3
"""#255 retrospective Codex concurrency analysis from existing artifacts only."""

from __future__ import annotations

import bisect
import csv
import datetime as dtmod
import json
import math
import sqlite3
import statistics
import subprocess
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
DB = Path("/mnt/data/Projects/Python/orchestra/data/orchestra.db")
ROLLOUTS = Path.home() / ".codex/sessions"
CUTOFF = "2026-08-23T13:54:29.852026+00:00"  # #255 assignment updated_at
BUCKETS = ("1", "2-4", "5-9", "10-19", "20+")


def parse_ts(value: str) -> dtmod.datetime:
    return dtmod.datetime.fromisoformat(value.replace("Z", "+00:00"))


def epoch(value: str) -> float:
    return parse_ts(value).timestamp()


def bucket(value: int) -> str:
    if value == 1:
        return "1"
    if value <= 4:
        return "2-4"
    if value <= 9:
        return "5-9"
    if value <= 19:
        return "10-19"
    return "20+"


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    return sorted(values)[max(0, math.ceil(fraction * len(values)) - 1)]


def median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def fmt(value, digits: int = 3) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def load_usage() -> tuple[list[dict], dict, dict[str, list[float]], dict[str, list[float]], dict[str, float]]:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    query = """
    SELECT u.event_id, u.session_id, u.ts AS usage_ts,
           u.model, u.ok, u.stop_reason, u.input_tokens, u.cache_read_tokens,
           u.cache_create_tokens, u.output_tokens, u.task_id,
           u.quota_primary_pct, u.quota_sampled_at,
           s.name AS session_name, s.scope, s.role
    FROM turn_usage u
    JOIN sessions s ON s.id=u.session_id
    WHERE u.runtime='codex' AND u.ts <= ?
    ORDER BY u.ts
    """
    usage_rows = [dict(row) for row in conn.execute(query, (CUTOFF,))]
    all_start_count = conn.execute(
        "SELECT count(*) FROM logs WHERE type='status' AND content LIKE 'codex turn=% started' AND ts<=?",
        (CUTOFF,),
    ).fetchone()[0]

    messages: dict[str, list[float]] = defaultdict(list)
    for row in conn.execute(
        "SELECT session_id,ts FROM logs WHERE type='user_message' AND ts<=? ORDER BY session_id,ts",
        (CUTOFF,),
    ):
        messages[str(row[0])].append(epoch(str(row[1])))
    tool_times: dict[str, list[float]] = defaultdict(list)
    for row in conn.execute(
        "SELECT session_id,ts FROM logs WHERE type='tool' AND ts<=? ORDER BY session_id,ts",
        (CUTOFF,),
    ):
        tool_times[str(row[0])].append(epoch(str(row[1])))
    db_starts = {
        str(row[0]): epoch(str(row[1]))
        for row in conn.execute(
            "SELECT substr(content,12,36),ts FROM logs "
            "WHERE type='status' AND content LIKE 'codex turn=% started' AND ts<=?",
            (CUTOFF,),
        )
    }
    conn.close()
    return usage_rows, {
        "cutoff": CUTOFF,
        "codex_usage_rows": len(usage_rows),
        "codex_start_markers": all_start_count,
    }, messages, tool_times, db_starts


def scan_rollouts(target_ids: set[str]) -> tuple[dict[str, dict], dict]:
    found: dict[str, dict] = {}
    files = 0
    bytes_read = 0
    parsed_rows = 0
    conflicts = []
    too_large_relevant = 0
    markers = (
        b'"type":"task_started"', b'"type":"task_complete"', b'"type":"turn_context"'
    )
    for path in ROLLOUTS.rglob("*.jsonl"):
        files += 1
        try:
            with path.open("rb") as handle:
                for line in handle:
                    bytes_read += len(line)
                    head = line[:512]
                    if not any(marker in head for marker in markers):
                        continue
                    if len(line) > 8 * 1024 * 1024:
                        too_large_relevant += 1
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
                        if turn_id not in target_ids:
                            continue
                        parsed_rows += 1
                        values = {
                            "start_ts": row.get("timestamp"),
                            "model_context_window": payload.get("model_context_window"),
                            "rollout_path": str(path),
                        }
                    elif row_type == "event_msg" and payload_type == "task_complete":
                        turn_id = str(payload.get("turn_id") or "")
                        if turn_id not in target_ids:
                            continue
                        parsed_rows += 1
                        values = {
                            "ttft_s": (payload.get("time_to_first_token_ms") or 0) / 1000,
                            "rollout_duration_s": (payload.get("duration_ms") or 0) / 1000,
                            "end_ts": row.get("timestamp"),
                            "rollout_path": str(path),
                        }
                    elif row_type == "turn_context":
                        turn_id = str(payload.get("turn_id") or "")
                        if turn_id not in target_ids:
                            continue
                        parsed_rows += 1
                        values = {
                            "effort": payload.get("effort"),
                            "rollout_model": payload.get("model"),
                            "cwd": payload.get("cwd"),
                            "rollout_path": str(path),
                        }
                    else:
                        continue
                    slot = found.setdefault(turn_id, {})
                    for key, value in values.items():
                        if key in slot and slot[key] != value and key != "rollout_path":
                            conflicts.append((turn_id, key, slot[key], value))
                        slot[key] = value
        except OSError:
            continue
    return found, {
        "rollout_files": files,
        "rollout_bytes_read": bytes_read,
        "relevant_rows": parsed_rows,
        "turns_with_rollout_data": len(found),
        "conflicts": conflicts[:20],
        "too_large_relevant_rows": too_large_relevant,
    }


def proxy_snapshot() -> dict:
    frozen = HERE / "proxy-snapshot.json"
    if frozen.exists():
        return json.loads(frozen.read_text())
    captured = dtmod.datetime.now(dtmod.timezone.utc).isoformat()
    try:
        with urllib.request.urlopen("http://127.0.0.1:18109/api/status", timeout=2) as response:
            data = json.load(response)
    except Exception as exc:
        return {"captured_at": captured, "error": f"{type(exc).__name__}: {exc}"}
    gateway = data.get("gateway") or {}
    route = (gateway.get("routes") or {}).get(gateway.get("selected_route")) or {}
    health = (data.get("health") or {}).get(gateway.get("selected_route")) or {}
    result = {
        "captured_at": captured,
        "selected_route": gateway.get("selected_route"),
        "proxy_endpoint": gateway.get("proxy_endpoint"),
        "active_connections": gateway.get("active_connections"),
        "max_connections": gateway.get("max_connections"),
        "rejected_connections": gateway.get("rejected_connections"),
        "uptime_seconds": gateway.get("uptime_seconds"),
        "route_accepted": route.get("accepted"),
        "route_failed": route.get("failed"),
        "route_active": route.get("active"),
        "semantic": health.get("semantic"),
        "semantic_status": health.get("semantic_status"),
        "semantic_latency_ms": health.get("semantic_latency_ms"),
        "process": data.get("process"),
    }
    frozen.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return result


def journal_summary(turns: list[dict]) -> dict:
    command = [
        "journalctl", "-u", "orchestra", "--no-pager", "--since", "2026-07-27",
        "--until", CUTOFF, "-o", "json",
    ]
    proc = subprocess.run(command, text=True, capture_output=True, check=False)
    failures: dict[str, set[str]] = defaultdict(set)
    first_ts = None
    last_ts = None
    lines = 0
    for line in proc.stdout.splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        lines += 1
        micros = int(row.get("__REALTIME_TIMESTAMP") or 0)
        timestamp = dtmod.datetime.fromtimestamp(micros / 1_000_000, tz=dtmod.timezone.utc)
        first_ts = min(first_ts, timestamp) if first_ts else timestamp
        last_ts = max(last_ts, timestamp) if last_ts else timestamp
        message = str(row.get("MESSAGE") or "")
        if "Codex usage fetch failed" not in message:
            continue
        normalized = message
        for prefix in ("WARNING:orchestra.system:", "INFO:orchestra.system:"):
            normalized = normalized.removeprefix(prefix)
        failures[timestamp.isoformat(timespec="seconds")].add(normalized)
    bursts = []
    for stamp, messages in sorted(failures.items()):
        instant = parse_ts(stamp).timestamp()
        active = sum(t["start_epoch"] <= instant < t["end_epoch"] for t in turns)
        bursts.append({"ts": stamp, "distinct_failures": len(messages), "exact_active_turns": active})
    return {
        "journal_lines": lines,
        "first_ts": first_ts.isoformat() if first_ts else None,
        "last_ts": last_ts.isoformat() if last_ts else None,
        "usage_fetch_failure_seconds": len(bursts),
        "usage_fetch_failure_bursts": bursts,
        "usage_fetch_failure_active_distribution": dict(
            sorted(Counter(item["exact_active_turns"] for item in bursts).items())
        ),
        "journal_rc": proc.returncode,
    }


def bucket_summary(turns: list[dict]) -> dict[str, dict]:
    result = {}
    for name in BUCKETS:
        rows = [turn for turn in turns if turn["bucket"] == name]
        durations = [turn["duration_s"] for turn in rows]
        ttfts = [turn["ttft_s"] for turn in rows if turn.get("ttft_s") is not None]
        dispatch = [
            turn["dispatch_to_start_s"] for turn in rows
            if turn.get("dispatch_to_start_s") is not None and 0 <= turn["dispatch_to_start_s"] <= 3600
        ]
        throughput = [
            turn["output_tokens"] / turn["duration_s"]
            for turn in rows if turn["duration_s"] > 0 and turn["output_tokens"] > 0
        ]
        result[name] = {
            "n": len(rows),
            "start_min": min((turn["start_ts"] for turn in rows), default=None),
            "start_max": max((turn["start_ts"] for turn in rows), default=None),
            "active_min": min((turn["active_turns"] for turn in rows), default=None),
            "active_max": max((turn["active_turns"] for turn in rows), default=None),
            "duration_median_s": median(durations),
            "duration_p90_s": percentile(durations, 0.90),
            "ttft_n": len(ttfts),
            "ttft_median_s": median(ttfts),
            "ttft_p90_s": percentile(ttfts, 0.90),
            "dispatch_n": len(dispatch),
            "dispatch_median_s": median(dispatch),
            "dispatch_p90_s": percentile(dispatch, 0.90),
            "tool_rounds_median": median([turn["tool_rounds"] for turn in rows]),
            "input_tokens_median": median([turn["input_tokens"] for turn in rows]),
            "output_tokens_median": median([turn["output_tokens"] for turn in rows]),
            "output_tokens_p90": percentile([turn["output_tokens"] for turn in rows], 0.90),
            "tokens_per_second_median": median(throughput),
            "error_n": sum(not turn["ok"] for turn in rows),
            "error_rate": sum(not turn["ok"] for turn in rows) / len(rows) if rows else None,
            "models": dict(Counter(turn["model"] for turn in rows)),
            "efforts": dict(Counter(str(turn.get("effort") or "unobserved") for turn in rows)),
            "roles": dict(Counter(str(turn.get("role") or "unknown") for turn in rows)),
            "task_ids_present": sum(bool(turn.get("task_id")) for turn in rows),
            "quota_primary_range": [
                min((turn["quota_primary_pct"] for turn in rows if turn["quota_primary_pct"] is not None), default=None),
                max((turn["quota_primary_pct"] for turn in rows if turn["quota_primary_pct"] is not None), default=None),
            ],
        }
    return result


def stratified_summary(turns: list[dict]) -> dict[str, dict]:
    result = {}
    for field, values in (
        ("effort", ("high", "xhigh")),
        ("role", ("worker", "full-cycle", "orchestrator")),
    ):
        for value in values:
            key = f"{field}={value}"
            result[key] = {}
            for name in BUCKETS:
                rows = [
                    turn for turn in turns
                    if turn["bucket"] == name and str(turn.get(field) or "") == value
                ]
                result[key][name] = {
                    "n": len(rows),
                    "ttft_median_s": median([turn["ttft_s"] for turn in rows]),
                    "duration_median_s": median([turn["duration_s"] for turn in rows]),
                    "output_tokens_median": median([turn["output_tokens"] for turn in rows]),
                    "tool_rounds_median": median([turn["tool_rounds"] for turn in rows]),
                    "tokens_per_second_median": median([
                        turn["output_tokens"] / turn["duration_s"]
                        for turn in rows if turn["duration_s"] > 0 and turn["output_tokens"] > 0
                    ]),
                }
    return result


def compact_cohort(rows: list[dict]) -> dict:
    return {
        "n": len(rows),
        "ttft_median_s": median([row["ttft_s"] for row in rows]),
        "duration_median_s": median([row["duration_s"] for row in rows]),
        "output_tokens_median": median([row["output_tokens"] for row in rows]),
        "tool_rounds_median": median([row["tool_rounds"] for row in rows]),
        "tokens_per_second_median": median([
            row["output_tokens"] / row["duration_s"]
            for row in rows if row["duration_s"] > 0 and row["output_tokens"] > 0
        ]),
    }


def interval_count(turns: list[dict], stamp: str) -> int:
    instant = epoch(stamp)
    return sum(turn["start_epoch"] <= instant < turn["end_epoch"] for turn in turns)


def write_csv(turns: list[dict]) -> None:
    fields = [
        "event_id", "session_id", "session_name", "scope", "role", "task_id", "start_ts",
        "end_ts", "duration_s", "active_turns", "bucket", "model", "effort", "tier",
        "ttft_s", "dispatch_to_start_s", "tool_rounds", "input_tokens", "cache_read_tokens",
        "output_tokens", "ok", "stop_reason", "quota_primary_pct", "rollout_path",
        "timestamp_duration_s", "duration_disagreement_s", "db_start_lag_s",
    ]
    with (HERE / "turns.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n"
        )
        writer.writeheader()
        for turn in turns:
            writer.writerow(turn)


def write_measurements(summary: dict, meta: dict, rollout_meta: dict, proxy: dict, journal: dict) -> None:
    lines = [
        "# #255 retrospective concurrency table",
        "",
        f"Cutoff: `{meta['cutoff']}`. Concurrency is reconstructed from native rollout "
        "`task_started→task_complete` intervals joined to `turn_usage.event_id`, ordered and "
        "overlapped by `ts`; it is exact inside the complete-rollout cohort and a lower bound for "
        "all attempts. Session/process counts are never substituted for active turns.",
        "",
        "| UTC start interval | active Codex turns | observable process snapshot/boundary | model / effort / tier / task class | TTFT median/p90 (n), s | final median/p90, s | tool rounds median | input/output median | host load/CPU/RSS | proxy endpoint + counters | provider error/rate evidence | negative/control traffic | source |",
        "|---|---:|---|---|---:|---:|---:|---:|---|---|---|---|---|",
    ]
    for name in BUCKETS:
        row = summary[name]
        if not row["n"]:
            interval = "not observed"
            process = "no exact active-turn intervals"
        else:
            interval = f"{row['start_min']} → {row['start_max']}"
            process = "not sampled synchronously"
            if name == "2-4":
                process = "#111 task-creation boundary 2026-08-01 06:49 UTC: 62 Codex-related processes / 109 sessions while exact active turns=4"
            elif name == "5-9":
                process = "#111 second snapshot 2026-08-01 06:56 UTC: 16 native + 16 Node + 17 helpers = 49 processes while exact active turns=8"
            elif name == "10-19":
                process = "not sampled synchronously; first Aug-01 exact active=10 starts 13 min after the 49-process/active=8 snapshot"
        model_cell = (
            f"{row['models']} / {row['efforts']} / tier unobserved / roles {row['roles']}"
            if row["n"] else "—"
        )
        host = "not sampled synchronously"
        if name == "2-4":
            host = "#111 task snapshot: RSS 3.4 GiB, swap 10 GiB, load up to 13; no CPU attribution"
        elif name == "5-9":
            host = "#111: load 3.53/2.75/4.22, RSS 3.324 GiB, swap 11 GiB; no CPU attribution"
        elif name == "10-19":
            host = "not sampled synchronously"
        proxy_cell = "historical counters unavailable; current manager began 2026-08-23"
        errors = f"{row['error_n']}/{row['n']} terminal errors; quota {row['quota_primary_range']}"
        control = (
            f"output median/p90 {fmt(row['output_tokens_median'],0)}/{fmt(row['output_tokens_p90'],0)}; "
            f"tokens/s median {fmt(row['tokens_per_second_median'])}"
            if row["n"] else "—"
        )
        lines.append(
            f"| {interval} | {name} (n={row['n']}, exact {row['active_min']}–{row['active_max']}) | {process} | "
            f"{model_cell} | {fmt(row['ttft_median_s'])}/{fmt(row['ttft_p90_s'])} (n={row['ttft_n']}) | "
            f"{fmt(row['duration_median_s'])}/{fmt(row['duration_p90_s'])} | {fmt(row['tool_rounds_median'])} | "
            f"{fmt(row['input_tokens_median'],0)}/{fmt(row['output_tokens_median'],0)} | {host} | {proxy_cell} | "
            f"{errors} | {control} | `turns.csv`, `bucket-summary.json` |"
        )
    lines += [
        "",
        "## Coverage and boundaries",
        "",
        f"- Codex usage rows: {meta['codex_usage_rows']}; exact rollout task_started→task_complete intervals: "
        f"{meta['exact_rollout_intervals']}; usage rows without a complete local rollout interval: "
        f"{meta['usage_without_rollout_interval']}.",
        f"- DB `codex turn=... started` markers are diagnostic only, not interval starts: n={meta['db_start_lag_n']}, "
        f"lag vs rollout start median/p90/max={fmt(meta['db_start_lag_median_s'])}/"
        f"{fmt(meta['db_start_lag_p90_s'])}/{fmt(meta['db_start_lag_max_s'])} s. "
        "Delayed replay after restart makes DB-marker intervals invalid.",
        f"- Rollout scan: {rollout_meta['rollout_files']} files / {rollout_meta['rollout_bytes_read']} bytes; "
        f"turns with rollout data: {rollout_meta['turns_with_rollout_data']}; TTFT rows are shown per bucket.",
        "- `tier` is not stored in historical `turn_usage` or `turn_context`; it is marked unobserved. "
        "Current managed config is Standard, but that fact is not projected backward.",
        "- Task class is the persisted Orchestra role plus task-id presence; prompt semantics are not reconstructed.",
        "",
        "## Current proxy-manager counter snapshot (not historical join evidence)",
        "",
        "```json",
        json.dumps(proxy, ensure_ascii=False, indent=2, sort_keys=True),
        "```",
        "",
        "The manager counters reset on process restart and have no time series; they cannot be joined to July/August turns.",
        "",
        "## Retained Orchestra journal boundary",
        "",
        "```json",
        json.dumps(journal, ensure_ascii=False, indent=2, sort_keys=True),
        "```",
    ]
    (HERE / "measurements.md").write_text("\n".join(lines) + "\n")


def main() -> None:
    HERE.mkdir(parents=True, exist_ok=True)
    usage_rows, meta, messages, tool_times, db_starts = load_usage()
    rollout, rollout_meta = scan_rollouts({turn["event_id"] for turn in usage_rows})
    turns = []
    cutoff_epoch = epoch(CUTOFF)
    for usage in usage_rows:
        extra = rollout.get(usage["event_id"], {})
        if not extra.get("start_ts") or not extra.get("end_ts"):
            continue
        turn = {**usage, **extra}
        turn["start_epoch"] = epoch(turn["start_ts"])
        turn["end_epoch"] = epoch(turn["end_ts"])
        if turn["end_epoch"] > cutoff_epoch:
            continue
        timestamp_duration = turn["end_epoch"] - turn["start_epoch"]
        rollout_duration = float(turn.get("rollout_duration_s") or 0)
        turn["duration_s"] = rollout_duration if rollout_duration > 0 else timestamp_duration
        turn["timestamp_duration_s"] = timestamp_duration
        turn["duration_disagreement_s"] = abs(turn["duration_s"] - timestamp_duration)
        db_start = db_starts.get(turn["event_id"])
        turn["db_start_lag_s"] = db_start - turn["start_epoch"] if db_start else None
        own_messages = messages.get(turn["session_id"], [])
        pos = bisect.bisect_right(own_messages, turn["start_epoch"])
        turn["dispatch_to_start_s"] = (
            turn["start_epoch"] - own_messages[pos - 1] if pos else None
        )
        own_tools = tool_times.get(turn["session_id"], [])
        left = bisect.bisect_left(own_tools, turn["start_epoch"])
        right = bisect.bisect_right(own_tools, turn["end_epoch"])
        turn["tool_rounds"] = right - left
        turn["tier"] = "unobserved"
        turns.append(turn)
    turns.sort(key=lambda turn: turn["start_epoch"])
    for turn in turns:
        instant = turn["start_epoch"]
        turn["active_turns"] = sum(
            other["start_epoch"] <= instant < other["end_epoch"] for other in turns
        )
        turn["bucket"] = bucket(turn["active_turns"])
    meta["exact_rollout_intervals"] = len(turns)
    meta["usage_without_rollout_interval"] = len(usage_rows) - len(turns)
    lags = [turn["db_start_lag_s"] for turn in turns if turn.get("db_start_lag_s") is not None]
    meta["db_start_lag_n"] = len(lags)
    meta["db_start_lag_median_s"] = median(lags)
    meta["db_start_lag_p90_s"] = percentile(lags, 0.90)
    meta["db_start_lag_max_s"] = max(lags) if lags else None
    meta["duration_disagreement_max_s"] = max(
        (turn["duration_disagreement_s"] for turn in turns), default=None
    )
    summary = bucket_summary(turns)
    strata = stratified_summary(turns)
    aug1 = {
        name: compact_cohort([
            turn for turn in turns
            if turn["bucket"] == name
            and "2026-08-01T06:00:00Z" <= turn["start_ts"] < "2026-08-01T09:00:00Z"
        ])
        for name in BUCKETS
    }
    snapshot_alignment = {
        "2026-08-01T06:49:12+00:00_task_111_created": interval_count(
            turns, "2026-08-01T06:49:12+00:00"
        ),
        "2026-08-01T06:56:00+00:00_second_snapshot": interval_count(
            turns, "2026-08-01T06:56:00+00:00"
        ),
    }
    proxy = proxy_snapshot()
    journal = journal_summary(turns)
    write_csv(turns)
    artifact = {
        "meta": meta,
        "rollout": rollout_meta,
        "buckets": summary,
        "strata": strata,
        "aug1_0600_0900": aug1,
        "snapshot_active_turns": snapshot_alignment,
        "proxy_snapshot": proxy,
        "journal": journal,
    }
    (HERE / "bucket-summary.json").write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    write_measurements(summary, meta, rollout_meta, proxy, journal)
    print(json.dumps({
        "turns": len(turns),
        "max_concurrency": max(turn["active_turns"] for turn in turns),
        "ttft": sum(turn.get("ttft_s") is not None for turn in turns),
        "rollout_bytes": rollout_meta["rollout_bytes_read"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
