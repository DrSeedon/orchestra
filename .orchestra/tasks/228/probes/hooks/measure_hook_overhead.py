#!/usr/bin/env python3
"""Measure CLI-observed PreToolUse latency for #228 without touching live config."""

import json
import statistics
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[5]
COUNT = 24


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(q * len(ordered) + 0.999999) - 1))
    return ordered[index]


def run(settings_name: str) -> dict:
    settings = Path(__file__).with_name(settings_name)
    prompt = (
        f"Emit exactly {COUNT} distinct Bash tool calls. Each call's command must be exactly "
        "`true`; do not combine commands. Set run_in_background=false. Emit all calls in one "
        "assistant message, then stop after their results."
    )
    args = [
        "claude", "-p", prompt,
        "--model", "claude-haiku-4-5",
        "--permission-mode", "default",
        "--settings", str(settings),
        "--setting-sources", "",
        "--include-hook-events",
        "--max-turns", "2",
        "--output-format", "stream-json",
        "--verbose",
    ]
    proc = subprocess.Popen(
        args,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    assert proc.stdout is not None
    hook_started: dict[str, float] = {}
    hook_ms: list[float] = []
    tool_use_at: float | None = None
    tool_result_at: float | None = None
    tool_uses = 0
    tool_results = 0
    result = None
    for line in proc.stdout:
        now = time.perf_counter()
        event = json.loads(line)
        if event.get("type") == "assistant":
            content = event.get("message", {}).get("content", [])
            uses = [item for item in content if item.get("type") == "tool_use"]
            if uses:
                tool_use_at = tool_use_at or now
                tool_uses += len(uses)
        elif event.get("type") == "user":
            content = event.get("message", {}).get("content", [])
            results = [item for item in content if item.get("type") == "tool_result"]
            if results:
                tool_result_at = now
                tool_results += len(results)
        elif event.get("subtype") == "hook_started":
            hook_started[event["hook_id"]] = now
        elif event.get("subtype") == "hook_response":
            start = hook_started.get(event["hook_id"])
            if start is not None:
                hook_ms.append((now - start) * 1000)
        elif event.get("type") == "result":
            result = {
                "is_error": event.get("is_error"),
                "stop_reason": event.get("stop_reason"),
                "num_turns": event.get("num_turns"),
            }
    stderr = proc.stderr.read() if proc.stderr is not None else ""
    returncode = proc.wait()
    batch_ms = None
    if tool_use_at is not None and tool_result_at is not None:
        batch_ms = (tool_result_at - tool_use_at) * 1000
    return {
        "settings": settings_name,
        "requested_calls": COUNT,
        "tool_uses": tool_uses,
        "tool_results": tool_results,
        "hook_samples": len(hook_ms),
        "hook_p50_ms": round(statistics.median(hook_ms), 3) if hook_ms else None,
        "hook_p95_ms": round(percentile(hook_ms, 0.95), 3) if hook_ms else None,
        "hook_min_ms": round(min(hook_ms), 3) if hook_ms else None,
        "hook_max_ms": round(max(hook_ms), 3) if hook_ms else None,
        "tool_batch_ms": round(batch_ms, 3) if batch_ms is not None else None,
        "result": result,
        "returncode": returncode,
        "stderr": stderr[-500:],
    }


if __name__ == "__main__":
    selected = sys.argv[1:] or ["baseline-settings.json", "settings.json"]
    for name in selected:
        print(json.dumps(run(name), ensure_ascii=False, sort_keys=True))
