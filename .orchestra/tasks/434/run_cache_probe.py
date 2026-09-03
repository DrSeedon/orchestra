#!/usr/bin/env python3
"""Sequential Opus/Fable cache and subscription-window probe for task #434."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import time
from datetime import datetime, timezone
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "docs/tasks/434/cache-probe.jsonl"
OAUTH_USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
LOCAL_USAGE_URL = "http://127.0.0.1:8888/api/usage"
PROMPT = "Reply with exactly PONG and nothing else."
MODELS = [
    ("opus-1", "claude-opus-5[1m]"),
    ("fable-1", "claude-fable-5-1"),
    ("opus-2", "claude-opus-5[1m]"),
    ("fable-2", "claude-fable-5-1"),
    ("opus-3", "claude-opus-5[1m]"),
    ("fable-3", "claude-fable-5-1"),
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def append(row: dict) -> None:
    with OUT.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    print(json.dumps(row, ensure_ascii=False, sort_keys=True), flush=True)


def auth_token() -> str:
    credentials = json.loads((Path.home() / ".claude/.credentials.json").read_text())
    return credentials["claudeAiOauth"]["accessToken"]


def request_json(url: str, headers: dict[str, str]) -> dict:
    request = Request(url, headers=headers)
    with urlopen(request, timeout=20) as response:
        return json.load(response)


def slim_usage(data: dict) -> dict:
    scoped_fable = None
    for limit in data.get("limits") or []:
        model = ((limit.get("scope") or {}).get("model") or {})
        if limit.get("kind") == "weekly_scoped" and model.get("display_name") == "Fable":
            scoped_fable = limit.get("percent")
            break
    return {
        "five_hour": (data.get("five_hour") or {}).get("utilization"),
        "seven_day": (data.get("seven_day") or {}).get("utilization"),
        "seven_day_fable": scoped_fable,
        "five_hour_resets_at": (data.get("five_hour") or {}).get("resets_at"),
        "seven_day_resets_at": (data.get("seven_day") or {}).get("resets_at"),
    }


def snapshot(label: str, *, fetch_fresh: bool = True) -> dict:
    fresh = None
    fresh_error = None if fetch_fresh else "skipped_after_upstream_429"
    if fetch_fresh:
        token = auth_token()
        try:
            fresh = request_json(
                OAUTH_USAGE_URL,
                {
                    "Authorization": f"Bearer {token}",
                    "anthropic-beta": "oauth-2025-04-20",
                    "Accept": "application/json",
                },
            )
        except Exception as error:
            fresh_error = f"{type(error).__name__}: {error}"
    cached = request_json(
        LOCAL_USAGE_URL,
        {
            "Accept": "application/json",
        },
    )
    row = {
        "event": "usage",
        "label": label,
        "ts": now_iso(),
        "loadavg": list(os.getloadavg()),
        "fresh_upstream": slim_usage(fresh) if fresh is not None else None,
        "fresh_upstream_error": fresh_error,
        "get_api_usage": slim_usage(cached.get("anthropic") or {}),
    }
    append(row)
    return row


def run_model(label: str, model: str) -> dict:
    command = [
        "claude",
        "--print",
        "--model",
        model,
        "--effort",
        "high",
        "--output-format",
        "json",
        "--no-session-persistence",
        PROMPT,
    ]
    started = time.monotonic()
    completed = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=240,
        check=False,
    )
    elapsed = time.monotonic() - started
    payload = None
    parse_error = None
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        parse_error = f"{type(error).__name__}: {error}"
    row = {
        "event": "model",
        "label": label,
        "model_requested": model,
        "ts": now_iso(),
        "elapsed_seconds": round(elapsed, 3),
        "returncode": completed.returncode,
        "result": payload.get("result") if isinstance(payload, dict) else None,
        "usage": payload.get("usage") if isinstance(payload, dict) else None,
        "model_usage": payload.get("modelUsage") if isinstance(payload, dict) else None,
        "cost_usd_virtual": payload.get("total_cost_usd") if isinstance(payload, dict) else None,
        "parse_error": parse_error,
        "stderr_tail": completed.stderr[-1000:],
    }
    append(row)
    if completed.returncode != 0 or payload is None:
        raise RuntimeError(f"{label} failed: rc={completed.returncode}, parse={parse_error}")
    return row


def main() -> None:
    fetch_fresh = os.environ.get("PROBE_FRESH_USAGE", "1") != "0"
    existing = []
    if OUT.exists():
        existing = [json.loads(line) for line in OUT.read_text().splitlines()]
    else:
        append(
            {
                "event": "protocol",
                "ts": now_iso(),
                "sequence": MODELS,
                "prompt": PROMPT,
                "fable_five_hour_budget_pp": 3,
                "stop_rule": (
                    "sum positive fresh five_hour deltas observed across Fable call intervals; "
                    "after upstream 429, conservatively carry the largest observed Fable delta"
                ),
            }
        )
        snapshot("initial", fetch_fresh=fetch_fresh)
    completed_labels = {
        row["label"] for row in existing
        if row.get("event") == "model" and row.get("returncode") == 0
    }
    fable_deltas = [
        float(row.get("budget_accounted_pp", row.get("five_hour_delta_pp")))
        for row in existing
        if row.get("event") == "fable_budget"
    ]
    pending_before: dict | None = None

    for label, model in MODELS:
        if label in completed_labels:
            continue
        is_fable = label.startswith("fable")
        if is_fable and fable_deltas:
            cumulative = sum(fable_deltas)
            projected = cumulative + max(fable_deltas)
            if projected > 3:
                append(
                    {
                        "event": "budget_stop",
                        "ts": now_iso(),
                        "before": label,
                        "observed_fable_deltas": fable_deltas,
                        "cumulative_pp": cumulative,
                        "projected_pp": projected,
                    }
                )
                break

        pending_before = snapshot(f"before-{label}", fetch_fresh=fetch_fresh)
        run_model(label, model)
        time.sleep(2)
        after = snapshot(f"after-{label}", fetch_fresh=fetch_fresh)

        if is_fable:
            if pending_before["fresh_upstream"] and after["fresh_upstream"]:
                before_value = pending_before["fresh_upstream"]["five_hour"]
                after_value = after["fresh_upstream"]["five_hour"]
                observed_delta = max(0.0, float(after_value) - float(before_value))
                accounted_delta = observed_delta
                delta_source = "fresh_upstream"
            else:
                observed_delta = None
                accounted_delta = max(fable_deltas, default=3.0)
                delta_source = "conservative_carry_forward_after_upstream_429"
            fable_deltas.append(accounted_delta)
            append(
                {
                    "event": "fable_budget",
                    "ts": now_iso(),
                    "label": label,
                    "five_hour_delta_pp": observed_delta,
                    "budget_accounted_pp": accounted_delta,
                    "delta_source": delta_source,
                    "observed_fable_deltas": fable_deltas,
                    "cumulative_pp": sum(fable_deltas),
                }
            )
            if sum(fable_deltas) >= 3:
                append(
                    {
                        "event": "budget_stop",
                        "ts": now_iso(),
                        "after": label,
                        "observed_fable_deltas": fable_deltas,
                        "cumulative_pp": sum(fable_deltas),
                    }
                )
                break


if __name__ == "__main__":
    main()
