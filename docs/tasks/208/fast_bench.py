#!/usr/bin/env python3
"""Bounded paired normal-vs-fast Codex app-server benchmark for #208.

The script changes no global config.  It launches one app-server with an isolated
temporary CODEX_HOME, passes serviceTier per thread/turn, and stores only metrics.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import queue
import random
import shutil
import sqlite3
import statistics
import subprocess
import tempfile
import threading
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MODEL = "gpt-5.6-sol"
EFFORT = "medium"
REPLICATES = 6
N_RECORDS = 1800
N_QUESTIONS = 24
MAX_PRIMARY_PP = 2
REFERENCE_USD_PER_PRIMARY_PP = 5.39
MAX_DIRECT_VIRTUAL_USD = MAX_PRIMARY_PP * REFERENCE_USD_PER_PRIMARY_PP
MAX_SINGLE_TURN_RESERVE_USD = 1.0
TURN_TIMEOUT_S = 300
OUT = Path(__file__).with_name("fast-mode-results.json")
DB_PATH = Path("/home/kesha/orchestra/data/orchestra.db")
PRICING_SOURCE_COMMIT = "d38f8785a73df506ef13fdfe8c8bf9911c050c8e"
PRICE_TABLE = {"input": 5.0, "cached": 0.5, "write": 6.25, "output": 30.0}
COST_PROVENANCE = (
    "locally computed Orchestra API-equivalent estimate from "
    f"app/backend_codex.py CODEX_TOKEN_PRICES/_codex_cost at {PRICING_SOURCE_COMMIT}; "
    "Codex/provider telemetry emits tokens and rate-limit percentages, not dollars"
)

ORDER = [
    (0, "normal"), (0, "fast"),
    (1, "fast"), (1, "normal"),
    (2, "normal"), (2, "fast"),
    (3, "fast"), (3, "normal"),
    (4, "normal"), (4, "fast"),
    (5, "fast"), (5, "normal"),
]

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "answers": {
            "type": "array",
            "minItems": N_QUESTIONS,
            "maxItems": N_QUESTIONS,
            "items": {
                "type": "object",
                "properties": {
                    "q": {"type": "integer"},
                    "final": {"type": "string"},
                    "sum": {"type": "integer"},
                },
                "required": ["q", "final", "sum"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["answers"],
    "additionalProperties": False,
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_fixture(replicate: int, nonce: str) -> tuple[str, str, list[dict], list[dict]]:
    rng = random.Random(208_000 + replicate)
    rows: list[dict[str, Any]] = []
    for i in range(N_RECORDS):
        rows.append({
            "id": f"R{i:04d}",
            "parent": f"R{rng.randrange(N_RECORDS):04d}",
            "weight": rng.randrange(1, 50),
            "code": f"C{rng.randrange(1_000_000):06d}",
            "zone": f"Z{rng.randrange(20):02d}",
            "note": f"N{rng.randrange(10**12):012d}",
        })

    def questions(offset: int) -> tuple[list[str], list[dict]]:
        starts = random.Random(208_900 + replicate * 10 + offset).sample(
            range(N_RECORDS), N_QUESTIONS
        )
        text: list[str] = []
        expected: list[dict] = []
        for q, start in enumerate(starts, 1):
            a = rows[start]
            b = rows[int(a["parent"][1:])]
            c = rows[int(b["parent"][1:])]
            text.append(f"Q{q:02d}: start={a['id']}; follow parent twice")
            expected.append({
                "q": q,
                "final": c["id"],
                "sum": a["weight"] + b["weight"] + c["weight"],
            })
        return text, expected

    q1, e1 = questions(1)
    q2, e2 = questions(2)
    records = "\n".join(
        f"{r['id']}|parent={r['parent']}|weight={r['weight']:02d}|"
        f"code={r['code']}|zone={r['zone']}|note={r['note']}"
        for r in rows
    )
    contract = (
        "Do not call tools. Use only RECORDS from this conversation. For each question, "
        "include start, its parent, and that parent's parent in sum; final is the last id. "
        "Return only the JSON object required by the output schema."
    )
    cold = (
        f"CACHE-BUSTER (not data): {nonce}\n{contract}\n\nRECORDS\n{records}\n"
        f"END RECORDS\n\nQUESTIONS\n" + "\n".join(q1)
    )
    warm = (
        f"{contract}\nUse the SAME RECORDS above for this independent second set.\n\n"
        "QUESTIONS\n" + "\n".join(q2)
    )
    return cold, warm, e1, e2


def grade(text: str, expected: list[dict]) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
    except Exception as exc:
        return {"pass": False, "reason": f"json:{type(exc).__name__}"}
    got = parsed.get("answers") if isinstance(parsed, dict) else None
    ok = got == expected
    return {"pass": ok, "reason": "exact" if ok else "answer_mismatch"}


def usage_snapshot() -> dict[str, Any]:
    token = os.environ.get("INTERNAL_TOKEN")
    if not token:
        raise RuntimeError("INTERNAL_TOKEN is missing")
    req = urllib.request.Request(
        "http://127.0.0.1:8888/api/usage",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(req, timeout=15) as response:
        data = json.load(response)["codex"]
    primary = data["primary"]
    return {
        "ts": utc_now(),
        "utilization": primary["utilization"],
        "window_minutes": primary["window_minutes"],
        "resets_at": primary["resets_at"],
    }


def virtual_cost(usage: dict[str, int] | None) -> float | None:
    if not usage:
        return None
    total_in = max(0, usage.get("inputTokens", 0))
    cached = min(max(0, usage.get("cachedInputTokens", 0)), total_in)
    writes = min(max(0, usage.get("cacheWriteInputTokens", 0)), total_in - cached)
    fresh = total_in - cached - writes
    output = max(0, usage.get("outputTokens", 0))
    return (
        fresh * PRICE_TABLE["input"]
        + cached * PRICE_TABLE["cached"]
        + writes * PRICE_TABLE["write"]
        + output * PRICE_TABLE["output"]
    ) / 1_000_000


def quota_delta_bounds(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Conservative bounds when each provider snapshot is quantized to an integer percent."""
    observed = after["utilization"] - before["utilization"]
    return {
        "observed_delta_pp": observed,
        "true_delta_pp_bounds_from_integer_quantization": [
            max(0.0, observed - 1.0),
            observed + 1.0,
        ],
        "assumption": "monotone counter; either floor or nearest-integer display",
    }


class AppServer:
    def __init__(self, cwd: Path):
        self.cwd = cwd
        self.temp_home = Path(tempfile.mkdtemp(prefix="codex-fast-home."))
        source_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
        auth = source_home / "auth.json"
        if not auth.exists():
            auth = Path.home() / ".codex" / "auth.json"
        if not auth.exists():
            raise RuntimeError("Codex auth.json not found")
        (self.temp_home / "auth.json").symlink_to(auth)
        env = os.environ.copy()
        env["CODEX_HOME"] = str(self.temp_home)
        self.proc = subprocess.Popen(
            [
                "codex", "app-server", "--stdio",
                "-c", "features.fast_mode=true",
                "-c", "analytics.enabled=false",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            cwd=cwd,
            env=env,
        )
        self.q: queue.Queue[tuple[int, dict[str, Any]]] = queue.Queue()
        self.stderr: list[str] = []
        threading.Thread(target=self._stdout_reader, daemon=True).start()
        threading.Thread(target=self._stderr_reader, daemon=True).start()
        self.next_id = 1
        self.request("initialize", {
            "clientInfo": {"name": "orchestra_fast_bench", "title": "#208 Fast bench", "version": "1"},
            "capabilities": {"experimentalApi": True},
        })
        self.send({"method": "initialized", "params": {}})

    def _stdout_reader(self) -> None:
        assert self.proc.stdout
        for line in self.proc.stdout:
            try:
                self.q.put((time.monotonic_ns(), json.loads(line)))
            except json.JSONDecodeError:
                self.stderr.append(f"NONJSON_STDOUT:{line[-300:]}")

    def _stderr_reader(self) -> None:
        assert self.proc.stderr
        for line in self.proc.stderr:
            self.stderr.append(line[-500:])
            if len(self.stderr) > 200:
                del self.stderr[:100]

    def send(self, obj: dict[str, Any]) -> int:
        assert self.proc.stdin
        sent = time.monotonic_ns()
        self.proc.stdin.write(json.dumps(obj, separators=(",", ":")) + "\n")
        self.proc.stdin.flush()
        return sent

    def request(self, method: str, params: dict[str, Any]) -> tuple[dict[str, Any], list[tuple[int, dict]]]:
        req_id = self.next_id
        self.next_id += 1
        self.send({"method": method, "id": req_id, "params": params})
        side: list[tuple[int, dict]] = []
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            ts, msg = self.q.get(timeout=max(0.1, deadline - time.monotonic()))
            if msg.get("id") == req_id:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg["result"], side
            side.append((ts, msg))
        raise TimeoutError(method)

    def start_thread(self, tier: str) -> tuple[str, dict[str, Any], list[tuple[int, dict]]]:
        result, side = self.request("thread/start", {
            "model": MODEL,
            "cwd": str(self.cwd),
            "approvalPolicy": "never",
            "sandbox": "read-only",
            "serviceTier": "fast" if tier == "fast" else None,
            "ephemeral": True,
            "experimentalRawEvents": True,
            "baseInstructions": (
                "You are in a controlled benchmark. Never call tools. Return only schema-valid JSON."
            ),
        })
        return result["thread"]["id"], result, side

    def run_turn(self, thread_id: str, tier: str, prompt: str) -> dict[str, Any]:
        req_id = self.next_id
        self.next_id += 1
        started_at = utc_now()
        started_ns = self.send({
            "method": "turn/start",
            "id": req_id,
            "params": {
                "threadId": thread_id,
                "input": [{"type": "text", "text": prompt}],
                "model": MODEL,
                "effort": EFFORT,
                "serviceTier": "fast" if tier == "fast" else None,
                "outputSchema": OUTPUT_SCHEMA,
            },
        })
        response_seen = False
        first_model_ns = None
        first_answer_ns = None
        completed_ns = None
        turn_id = None
        usage = None
        final_text = ""
        event_counts: dict[str, int] = {}
        tools: list[dict[str, Any]] = []
        errors: list[str] = []
        reroutes: list[dict[str, Any]] = []
        raw_service_tiers: set[str] = set()
        deadline = time.monotonic() + TURN_TIMEOUT_S

        def walk_tiers(value: Any) -> None:
            if isinstance(value, dict):
                for key, item in value.items():
                    if key in {"service_tier", "serviceTier"} and isinstance(item, str):
                        raw_service_tiers.add(item)
                    walk_tiers(item)
            elif isinstance(value, list):
                for item in value:
                    walk_tiers(item)

        while time.monotonic() < deadline:
            try:
                ts, msg = self.q.get(timeout=max(0.1, deadline - time.monotonic()))
            except queue.Empty as exc:
                raise TimeoutError("turn") from exc
            if msg.get("id") == req_id:
                if "error" in msg:
                    raise RuntimeError(f"turn/start: {msg['error']}")
                response_seen = True
                turn_id = msg["result"]["turn"]["id"]
                continue
            method = msg.get("method", "unknown")
            event_counts[method] = event_counts.get(method, 0) + 1
            params = msg.get("params", {})
            walk_tiers(params)
            if method in {
                "item/agentMessage/delta",
                "item/reasoning/summaryTextDelta",
                "item/reasoning/textDelta",
            } and params.get("delta"):
                if first_model_ns is None:
                    first_model_ns = ts
                if method == "item/agentMessage/delta" and first_answer_ns is None:
                    first_answer_ns = ts
            if method == "item/completed":
                item = params.get("item", {})
                kind = item.get("type")
                if kind in {"commandExecution", "mcpToolCall", "dynamicToolCall", "webSearch", "fileChange"}:
                    tools.append({"type": kind, "status": item.get("status")})
                if kind == "agentMessage" and item.get("text"):
                    final_text = item["text"]
            elif method == "thread/tokenUsage/updated":
                if not turn_id or params.get("turnId") == turn_id:
                    usage = params.get("tokenUsage", {}).get("last")
            elif method in {"error", "warning"}:
                errors.append(json.dumps(params, ensure_ascii=False)[:500])
            elif method == "model/rerouted":
                reroutes.append(params)
            elif method == "turn/completed":
                turn = params.get("turn", {})
                if turn_id is None:
                    turn_id = turn.get("id")
                if turn.get("id") == turn_id:
                    completed_ns = ts
                    status = turn.get("status")
                    if turn.get("error"):
                        errors.append(json.dumps(turn["error"], ensure_ascii=False)[:500])
                    break
        else:
            raise TimeoutError("turn/completed")

        return {
            "turn_id": turn_id,
            "status": status,
            "started_at": started_at,
            "completed_at": utc_now(),
            "response_seen": response_seen,
            "tt_first_model_delta_ms": None if first_model_ns is None else (first_model_ns - started_ns) / 1e6,
            "tt_first_answer_delta_ms": None if first_answer_ns is None else (first_answer_ns - started_ns) / 1e6,
            "wall_ms": None if completed_ns is None else (completed_ns - started_ns) / 1e6,
            "usage": usage,
            "virtual_cost_usd": virtual_cost(usage),
            "cost_provenance": COST_PROVENANCE,
            "documented_credit_multiplier_vs_standard": 2.5 if tier == "fast" else 1.0,
            "tool_calls": tools,
            "tool_errors": sum(x.get("status") in {"failed", "error", "declined"} for x in tools),
            "errors": errors,
            "reroutes": reroutes,
            "event_counts": event_counts,
            "raw_service_tiers": sorted(raw_service_tiers),
            "final_text_sha256": hashlib.sha256(final_text.encode()).hexdigest(),
            "final_text": final_text,
        }

    def close(self) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)
        shutil.rmtree(self.temp_home, ignore_errors=True)


def wilson(successes: int, n: int) -> list[float] | None:
    if not n:
        return None
    z = 1.959963984540054
    p = successes / n
    den = 1 + z * z / n
    center = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return [center - half, center + half]


def bootstrap_ratio(rows: list[dict], metric: str, phase: str) -> dict[str, Any] | None:
    by_rep: dict[int, dict[str, float]] = {}
    for row in rows:
        turn = row.get(phase)
        if not turn:
            continue
        value = turn.get(metric)
        if value is not None:
            by_rep.setdefault(row["replicate"], {})[row["tier"]] = value
    pairs = [v for v in by_rep.values() if set(v) == {"normal", "fast"}]
    if not pairs:
        return None
    ratios = [p["normal"] / p["fast"] for p in pairs]
    rng = random.Random(208)
    samples = []
    for _ in range(20_000):
        draw = [rng.choice(ratios) for _ in ratios]
        samples.append(statistics.median(draw))
    samples.sort()
    return {
        "n_pairs": len(ratios),
        "median_speedup_normal_over_fast": statistics.median(ratios),
        "bootstrap_95pct": [samples[499], samples[19_499]],
        "pair_ratios": ratios,
    }


def summarize(rows: list[dict]) -> dict[str, Any]:
    out: dict[str, Any] = {"layer_a_api_equivalent": {"cells": {}}, "paired": {}}
    for tier in ("normal", "fast"):
        for phase in ("cold", "warm"):
            turns = [r[phase] for r in rows if r["tier"] == tier and r.get(phase)]
            key = f"{tier}_{phase}"
            passes = sum(bool(t["grade"]["pass"]) for t in turns)
            total_cost = sum(t["virtual_cost_usd"] or 0 for t in turns)
            total_wall_s = sum((t["wall_ms"] or 0) / 1000 for t in turns)
            answer_latencies = [
                t["tt_first_answer_delta_ms"]
                for t in turns if t["tt_first_answer_delta_ms"] is not None
            ]
            wall_latencies = [t["wall_ms"] for t in turns if t["wall_ms"] is not None]
            out["layer_a_api_equivalent"]["cells"][key] = {
                "n": len(turns),
                "successes": passes,
                "success_wilson_95pct": wilson(passes, len(turns)),
                "median_tt_first_answer_ms": (
                    statistics.median(answer_latencies) if answer_latencies else None
                ),
                "median_wall_ms": statistics.median(wall_latencies) if wall_latencies else None,
                "virtual_cost_usd": total_cost,
                "virtual_usd_per_exact_pass": total_cost / passes if passes else None,
                "wall_seconds_total": total_wall_s,
                "wall_seconds_per_exact_pass": total_wall_s / passes if passes else None,
                "input_tokens": sum((t["usage"] or {}).get("inputTokens", 0) for t in turns),
                "cached_input_tokens": sum((t["usage"] or {}).get("cachedInputTokens", 0) for t in turns),
                "cache_write_input_tokens": sum(
                    (t["usage"] or {}).get("cacheWriteInputTokens", 0) for t in turns
                ),
                "output_tokens": sum((t["usage"] or {}).get("outputTokens", 0) for t in turns),
                "reasoning_output_tokens": sum(
                    (t["usage"] or {}).get("reasoningOutputTokens", 0) for t in turns
                ),
                "tool_calls": sum(len(t["tool_calls"]) for t in turns),
                "tool_errors": sum(t["tool_errors"] for t in turns),
                "errors": sum(len(t["errors"]) for t in turns),
                "reroutes": sum(len(t["reroutes"]) for t in turns),
            }
    for phase in ("cold", "warm"):
        out["paired"][f"{phase}_ttft"] = bootstrap_ratio(rows, "tt_first_answer_delta_ms", phase)
        out["paired"][f"{phase}_wall"] = bootstrap_ratio(rows, "wall_ms", phase)
    return out


def foreign_codex_turns(start: str, end: str) -> list[dict[str, Any]]:
    if not DB_PATH.exists():
        return []
    fd, snap_name = tempfile.mkstemp(prefix="fast-bench-db.", suffix=".sqlite")
    os.close(fd)
    snap = Path(snap_name)
    src = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    dst = sqlite3.connect(snap)
    try:
        src.backup(dst)
        rows = dst.execute(
            "SELECT s.name,t.session_id,t.task_id,t.model,t.ts,t.cost_usd,"
            "t.input_tokens,t.cache_read_tokens,t.cache_create_tokens,t.output_tokens,"
            "t.quota_primary_pct,t.quota_sampled_at FROM turn_usage t "
            "LEFT JOIN sessions s ON s.id=t.session_id "
            "WHERE t.runtime='codex' AND t.ts>=? AND t.ts<=? ORDER BY t.ts",
            (start, end),
        ).fetchall()
        return [
            {
                "agent": r[0],
                "session_id": r[1],
                "task_id": r[2],
                "model": r[3],
                "ts": r[4],
                "virtual_cost_usd": r[5],
                "input_tokens": r[6],
                "cache_read_tokens": r[7],
                "cache_create_tokens": r[8],
                "output_tokens": r[9],
                "quota_primary_pct": r[10],
                "quota_sampled_at": r[11],
                "mode": "unknown_foreign",
                "cost_provenance": "Orchestra turn_usage.cost_usd; local API-equivalent estimate",
            }
            for r in rows
        ]
    finally:
        src.close()
        dst.close()
        snap.unlink(missing_ok=True)


def quota_attribution(
    result: dict[str, Any], foreign: list[dict[str, Any]], quiet_window: bool
) -> dict[str, Any]:
    """Partition the full experiment into consecutive provider-snapshot intervals."""
    snapshots: dict[str, dict[str, Any]] = {
        result["baseline_usage"]["ts"]: result["baseline_usage"],
        result["final_usage"]["ts"]: result["final_usage"],
    }
    direct_by_interval: dict[tuple[str, str], dict[str, Any]] = {}
    for sample in result["pilot"] + result["confirmatory"]:
        for phase in ("cold", "warm"):
            turn = sample.get(phase)
            if not turn:
                continue
            before = turn["provider_usage_before"]
            after = turn["provider_usage_after"]
            snapshots[before["ts"]] = before
            snapshots[after["ts"]] = after
            direct_by_interval[(before["ts"], after["ts"])] = {
                "sequence": sample["sequence"],
                "replicate": sample["replicate"],
                "pilot": sample["pilot"],
                "tier": sample["tier"],
                "phase": phase,
                "virtual_cost_usd": turn["virtual_cost_usd"] or 0.0,
            }

    intervals: list[dict[str, Any]] = []
    ordered = [snapshots[key] for key in sorted(snapshots)]
    for before, after in zip(ordered, ordered[1:]):
        direct = direct_by_interval.get((before["ts"], after["ts"]))
        background = [row for row in foreign if before["ts"] < row["ts"] <= after["ts"]]
        direct_cost = direct["virtual_cost_usd"] if direct else 0.0
        foreign_cost = sum(row["virtual_cost_usd"] or 0.0 for row in background)
        cumulative_cost = direct_cost + foreign_cost
        bounds = quota_delta_bounds(before, after)
        low, high = bounds["true_delta_pp_bounds_from_integer_quantization"]
        intervals.append({
            "sequence": direct["sequence"] if direct else None,
            "replicate": direct["replicate"] if direct else None,
            "pilot": direct["pilot"] if direct else None,
            "tier": direct["tier"] if direct else None,
            "phase": direct["phase"] if direct else "background_gap",
            "provider_usage_before": before,
            "provider_usage_after": after,
            "direct_harness_virtual_cost_usd": direct_cost,
            "foreign_orchestra_virtual_cost_usd": foreign_cost,
            "cumulative_virtual_cost_usd": cumulative_cost,
            "foreign_orchestra_turns": background,
            "foreign_orchestra_turn_count": len(background),
            **bounds,
            "pp_per_cumulative_virtual_usd_bounds": (
                [low / cumulative_cost, high / cumulative_cost]
                if cumulative_cost > 0 else None
            ),
            "attribution": (
                "quiet_no_orchestra_background"
                if quiet_window and not background
                else "confounded_or_not_declared_quiet"
            ),
        })

    baseline = result["baseline_usage"]
    final = result["final_usage"]
    total_bounds = quota_delta_bounds(baseline, final)
    direct_cost = sum(
        direct["virtual_cost_usd"] for direct in direct_by_interval.values()
    )
    foreign_cost = sum(row["virtual_cost_usd"] or 0.0 for row in foreign)
    cumulative_cost = direct_cost + foreign_cost
    low, high = total_bounds["true_delta_pp_bounds_from_integer_quantization"]
    reset_stable = baseline["resets_at"] == final["resets_at"]
    identifiable = quiet_window and not foreign and reset_stable
    successes = sum(
        int(bool(turn["grade"]["pass"]))
        for sample in result["confirmatory"]
        for turn in (sample.get("cold"), sample.get("warm"))
        if turn
    )
    foreign_by_session: dict[str, dict[str, Any]] = {}
    for row in foreign:
        key = row["session_id"]
        group = foreign_by_session.setdefault(key, {
            "session_id": key,
            "agent": row["agent"],
            "model": row["model"],
            "turns": 0,
            "virtual_cost_usd": 0.0,
            "input_tokens": 0,
            "cache_read_tokens": 0,
            "cache_create_tokens": 0,
            "output_tokens": 0,
        })
        group["turns"] += 1
        group["virtual_cost_usd"] += row["virtual_cost_usd"] or 0.0
        for key_name in (
            "input_tokens", "cache_read_tokens", "cache_create_tokens", "output_tokens"
        ):
            group[key_name] += row[key_name] or 0
    direct_by_mode: dict[str, dict[str, Any]] = {}
    for direct in direct_by_interval.values():
        sample_kind = "pilot" if direct["pilot"] else "confirmatory"
        key = f"{sample_kind}_{direct['tier']}_{direct['phase']}"
        group = direct_by_mode.setdefault(key, {
            "sample": sample_kind,
            "tier": direct["tier"],
            "phase": direct["phase"],
            "turns": 0,
            "virtual_cost_usd": 0.0,
        })
        group["turns"] += 1
        group["virtual_cost_usd"] += direct["virtual_cost_usd"]
    confirm_before = result.get("confirmatory_baseline_usage")
    confirm_bounds = quota_delta_bounds(confirm_before, final) if confirm_before else None
    foreign_confirm = (
        [row for row in foreign if confirm_before["ts"] < row["ts"] <= final["ts"]]
        if confirm_before else []
    )
    confirm_direct_cost = sum(
        direct["virtual_cost_usd"]
        for direct in direct_by_interval.values()
        if not direct["pilot"]
    )
    confirm_foreign_cost = sum(row["virtual_cost_usd"] or 0.0 for row in foreign_confirm)
    confirm_cost = confirm_direct_cost + confirm_foreign_cost
    confirm_identifiable = bool(confirm_before) and quiet_window and not foreign_confirm and reset_stable
    confirm_pp_per_cost = None
    confirm_quota_per_pass = None
    if confirm_bounds and confirm_cost > 0:
        confirm_low, confirm_high = confirm_bounds[
            "true_delta_pp_bounds_from_integer_quantization"
        ]
        confirm_pp_per_cost = [confirm_low / confirm_cost, confirm_high / confirm_cost]
        if confirm_identifiable and successes:
            confirm_quota_per_pass = [confirm_low / successes, confirm_high / successes]
    return {
        "cost_provenance": COST_PROVENANCE,
        "quiet_window_declared": quiet_window,
        "reset_stable": reset_stable,
        "intervals": intervals,
        "direct_harness_virtual_cost_usd": direct_cost,
        "foreign_orchestra_virtual_cost_usd": foreign_cost,
        "cumulative_virtual_cost_usd": cumulative_cost,
        "foreign_orchestra_turn_count": len(foreign),
        "direct_by_mode": direct_by_mode,
        "foreign_by_session": foreign_by_session,
        **total_bounds,
        "pp_per_cumulative_virtual_usd_bounds": (
            [low / cumulative_cost, high / cumulative_cost] if cumulative_cost > 0 else None
        ),
        "identifiable": identifiable,
        "verdict": "IDENTIFIABLE" if identifiable else "UNIDENTIFIED",
        "confirmatory": {
            "provider_usage_before": confirm_before,
            "provider_usage_after": final if confirm_before else None,
            "direct_harness_virtual_cost_usd": confirm_direct_cost,
            "foreign_orchestra_virtual_cost_usd": confirm_foreign_cost,
            "cumulative_virtual_cost_usd": confirm_cost,
            "foreign_orchestra_turn_count": len(foreign_confirm),
            "identifiable": confirm_identifiable,
            "quota_delta": confirm_bounds,
            "pp_per_cumulative_virtual_usd_bounds": confirm_pp_per_cost,
            "quota_pp_per_exact_pass_bounds": confirm_quota_per_pass,
        },
    }


def checkpoint(result: dict[str, Any]) -> None:
    temp = OUT.with_suffix(".json.tmp")
    temp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    os.replace(temp, OUT)


def run(quiet_window: bool) -> int:
    scratch = Path(tempfile.mkdtemp(prefix="fast-bench-cwd."))
    result: dict[str, Any] = {
        "schema_version": 1,
        "protocol": {
            "model": MODEL,
            "effort": EFFORT,
            "replicates": REPLICATES,
            "records": N_RECORDS,
            "questions_per_turn": N_QUESTIONS,
            "order": ORDER,
            "fast_credit_multiplier_documented": 2.5,
            "max_primary_pp": MAX_PRIMARY_PP,
            "reference_usd_per_primary_pp": REFERENCE_USD_PER_PRIMARY_PP,
            "max_direct_virtual_usd": MAX_DIRECT_VIRTUAL_USD,
            "max_single_turn_reserve_usd": MAX_SINGLE_TURN_RESERVE_USD,
            "quiet_window_declared": quiet_window,
            "price_table_usd_per_million_tokens": PRICE_TABLE,
            "pricing_source_commit": PRICING_SOURCE_COMMIT,
            "cost_provenance": COST_PROVENANCE,
            "cli_version": subprocess.check_output(["codex", "--version"], text=True).strip(),
        },
        "started_at": utc_now(),
        "baseline_usage": usage_snapshot(),
        "pilot": [],
        "confirmatory": [],
        "confirmatory_baseline_usage": None,
        "stop_reason": None,
    }
    baseline = result["baseline_usage"]
    last_after = baseline
    direct_virtual_spent = 0.0
    server = AppServer(scratch)
    try:
        schedule = [(999, "normal", True), (999, "fast", True)] + [
            (rep, tier, False) for rep, tier in ORDER
        ]
        for sequence, (replicate, tier, pilot) in enumerate(schedule):
            before = usage_snapshot()
            if before["resets_at"] != baseline["resets_at"]:
                result["stop_reason"] = "primary_window_changed"
                break
            if quiet_window and before["utilization"] - baseline["utilization"] >= MAX_PRIMARY_PP:
                result["stop_reason"] = "primary_budget_reached_before_batch"
                break
            if quiet_window and before["utilization"] != last_after["utilization"]:
                result["stop_reason"] = "unexpected_primary_drift_before_turn"
                break
            if not pilot and result["confirmatory_baseline_usage"] is None:
                result["confirmatory_baseline_usage"] = before
            if direct_virtual_spent > MAX_DIRECT_VIRTUAL_USD - MAX_SINGLE_TURN_RESERVE_USD:
                result["stop_reason"] = "direct_virtual_usd_reserve_gate"
                break
            nonce = hashlib.sha256(f"208:{sequence}:{replicate}:{tier}".encode()).hexdigest()[:24]
            cold_prompt, warm_prompt, e1, e2 = make_fixture(replicate, nonce)
            thread_id, thread_meta, start_side = server.start_thread(tier)
            if tier == "fast" and thread_meta.get("serviceTier") != "priority":
                result["stop_reason"] = "fast_service_tier_not_applied"
                break
            if tier == "normal" and thread_meta.get("serviceTier") != "default":
                result["stop_reason"] = "normal_service_tier_not_applied"
                break
            if thread_meta.get("model") not in {None, MODEL}:
                result["stop_reason"] = "thread_model_mismatch"
                break

            cold = server.run_turn(thread_id, tier, cold_prompt)
            cold["grade"] = grade(cold.pop("final_text"), e1)
            direct_virtual_spent += cold["virtual_cost_usd"] or 0.0
            result["direct_virtual_spent_usd"] = direct_virtual_spent
            after_cold = usage_snapshot()
            cold["provider_usage_before"] = before
            cold["provider_usage_after"] = after_cold
            row = {
                "sequence": sequence,
                "replicate": replicate,
                "tier": tier,
                "pilot": pilot,
                "nonce_sha256": hashlib.sha256(nonce.encode()).hexdigest(),
                "thread_id_sha256": hashlib.sha256(thread_id.encode()).hexdigest(),
                "thread_service_tier": thread_meta.get("serviceTier"),
                "thread_model": thread_meta.get("model"),
                "instruction_sources": thread_meta.get("instructionSources"),
                "start_side_event_count": len(start_side),
                "usage_before": before,
                "usage_after": after_cold,
                "pre_batch_drift_pp": before["utilization"] - last_after["utilization"],
                "cold": cold,
                "warm": None,
            }
            (result["pilot"] if pilot else result["confirmatory"]).append(row)
            last_after = after_cold
            checkpoint(result)
            if cold["reroutes"]:
                result["stop_reason"] = "model_rerouted"
                break
            if after_cold["resets_at"] != baseline["resets_at"]:
                result["stop_reason"] = "primary_window_changed"
                break
            if pilot and (
                cold["status"] != "completed" or cold["usage"] is None
                or cold["tt_first_answer_delta_ms"] is None
            ):
                result["stop_reason"] = "pilot_instrumentation_failed"
                break
            if (cold["virtual_cost_usd"] or 0.0) > MAX_SINGLE_TURN_RESERVE_USD:
                result["stop_reason"] = "single_turn_exceeded_virtual_usd_reserve"
                break
            if quiet_window and after_cold["utilization"] - baseline["utilization"] >= MAX_PRIMARY_PP:
                result["stop_reason"] = "primary_budget_reached_after_cold_turn"
                break
            if direct_virtual_spent >= MAX_DIRECT_VIRTUAL_USD:
                result["stop_reason"] = "direct_virtual_usd_cap_reached_after_cold_turn"
                break
            if direct_virtual_spent > MAX_DIRECT_VIRTUAL_USD - MAX_SINGLE_TURN_RESERVE_USD:
                result["stop_reason"] = "direct_virtual_usd_reserve_gate_before_warm"
                break

            warm = server.run_turn(thread_id, tier, warm_prompt)
            warm["grade"] = grade(warm.pop("final_text"), e2)
            direct_virtual_spent += warm["virtual_cost_usd"] or 0.0
            result["direct_virtual_spent_usd"] = direct_virtual_spent
            after_warm = usage_snapshot()
            warm["provider_usage_before"] = after_cold
            warm["provider_usage_after"] = after_warm
            row["warm"] = warm
            row["usage_after"] = after_warm
            last_after = after_warm
            checkpoint(result)
            if warm["reroutes"]:
                result["stop_reason"] = "model_rerouted"
                break
            if after_warm["resets_at"] != baseline["resets_at"]:
                result["stop_reason"] = "primary_window_changed"
                break
            if pilot and (
                warm["status"] != "completed" or warm["usage"] is None
                or warm["tt_first_answer_delta_ms"] is None
            ):
                result["stop_reason"] = "pilot_instrumentation_failed"
                break
            if (warm["virtual_cost_usd"] or 0.0) > MAX_SINGLE_TURN_RESERVE_USD:
                result["stop_reason"] = "single_turn_exceeded_virtual_usd_reserve"
                break
            if quiet_window and after_warm["utilization"] - baseline["utilization"] >= MAX_PRIMARY_PP:
                result["stop_reason"] = "primary_budget_reached_after_warm_turn"
                break
            if direct_virtual_spent >= MAX_DIRECT_VIRTUAL_USD:
                result["stop_reason"] = "direct_virtual_usd_cap_reached_after_warm_turn"
                break
    finally:
        server.close()
        shutil.rmtree(scratch, ignore_errors=True)

    result["final_usage"] = usage_snapshot()
    result["ended_at"] = result["final_usage"]["ts"]
    result["foreign_orchestra_codex_turns"] = foreign_codex_turns(
        result["baseline_usage"]["ts"], result["final_usage"]["ts"]
    )
    result["summary"] = summarize(result["confirmatory"])
    result["quota"] = quota_attribution(
        result, result["foreign_orchestra_codex_turns"], quiet_window
    )
    result["summary"]["layer_b_provider_primary"] = result["quota"]
    checkpoint(result)
    return 0 if result["stop_reason"] is None else 2


def self_test() -> None:
    c1, w1, e1, e2 = make_fixture(0, "a")
    c2, w2, f1, f2 = make_fixture(0, "b")
    assert e1 == f1 and e2 == f2
    assert c1 != c2 and w1 == w2
    assert len(e1) == len(e2) == N_QUESTIONS
    assert grade(json.dumps({"answers": e1}), e1)["pass"]
    assert not grade("{}", e1)["pass"]
    assert math.isclose(virtual_cost({
        "inputTokens": 1000,
        "cachedInputTokens": 700,
        "cacheWriteInputTokens": 200,
        "outputTokens": 10,
    }) or 0, 0.0024)
    assert quota_delta_bounds(
        {"utilization": 7}, {"utilization": 8}
    )["true_delta_pp_bounds_from_integer_quantization"] == [0.0, 2.0]
    print(json.dumps({
        "self_test": "PASS",
        "cold_chars": len(c1),
        "warm_chars": len(w1),
        "fixture_answers_sha256": hashlib.sha256(json.dumps([e1, e2]).encode()).hexdigest(),
    }))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument(
        "--quiet-window",
        action="store_true",
        help="record that the operator declared an externally quiet Codex window",
    )
    args = parser.parse_args()
    if args.self_test:
        self_test()
    elif args.run:
        raise SystemExit(run(args.quiet_window))
    else:
        parser.error("choose --self-test or --run")
