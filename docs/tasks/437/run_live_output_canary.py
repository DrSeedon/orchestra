#!/usr/bin/env python3
"""Superseded #437 partial-coverage harness; live execution is fail-closed."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = ROOT / "docs/tasks/437/live-results.json"
OAUTH_USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
SCOPED_RAW_COEFFICIENT = 45.85196288955224
FABLE_SCOPED_CAP = 7.0
COMMON_WEEKLY_CAP = 15.0
CALLS = (
    ("fable-1", 24_235),
    ("fable-2", 24_235),
    ("fable-3", 24_234),
)
MODEL = "claude-fable-5-1"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def auth_token() -> str:
    credentials = json.loads((Path.home() / ".claude/.credentials.json").read_text())
    return credentials["claudeAiOauth"]["accessToken"]


def fresh_usage() -> dict:
    request = Request(
        OAUTH_USAGE_URL,
        headers={
            "Authorization": f"Bearer {auth_token()}",
            "anthropic-beta": "oauth-2025-04-20",
            "Accept": "application/json",
        },
    )
    with urlopen(request, timeout=20) as response:
        data = json.load(response)
    scoped = next(
        (
            limit for limit in data.get("limits") or []
            if limit.get("kind") == "weekly_scoped"
            and (((limit.get("scope") or {}).get("model") or {}).get("display_name") == "Fable")
        ),
        None,
    )
    if scoped is None:
        raise RuntimeError("fresh upstream has no Fable-scoped weekly counter")
    return {
        "ts": now_iso(),
        "five_hour": float(data["five_hour"]["utilization"]),
        "five_hour_resets_at": data["five_hour"]["resets_at"],
        "seven_day": float(data["seven_day"]["utilization"]),
        "seven_day_resets_at": data["seven_day"]["resets_at"],
        "fable_scoped": float(scoped["percent"]),
        "fable_scoped_resets_at": scoped["resets_at"],
    }


def output_prompt(repetitions: int) -> str:
    return (
        f"Produce one plain-text response containing exactly {repetitions} repetitions "
        "of the lowercase word z, separated by one ASCII space. No preface, no code "
        "fence, no punctuation, no tools. End immediately after the final z."
    )


def run_model(label: str, repetitions: int) -> dict:
    command = [
        "claude",
        "--print",
        "--model",
        MODEL,
        "--effort",
        "low",
        "--output-format",
        "stream-json",
        "--verbose",
        "--no-session-persistence",
        "--prompt-suggestions",
        "false",
        "--restricted",
        "--strict-mcp-config",
        "--disable-slash-commands",
        "--no-chrome",
        output_prompt(repetitions),
    ]
    load_before = list(os.getloadavg())
    started_at = now_iso()
    started = time.monotonic()
    completed = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=900,
        check=False,
    )
    wall_seconds = time.monotonic() - started
    load_after = list(os.getloadavg())

    events = []
    parse_errors = []
    for line_number, line in enumerate(completed.stdout.splitlines(), start=1):
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError as error:
            parse_errors.append(f"line {line_number}: {error}")
    assistant_turns = []
    for event in events:
        if event.get("type") != "assistant":
            continue
        message = event.get("message") or {}
        usage = message.get("usage") or {}
        assistant_turns.append(
            {
                "model": message.get("model"),
                "input_tokens": usage.get("input_tokens"),
                "cache_read_input_tokens": usage.get("cache_read_input_tokens"),
                "cache_creation_input_tokens": usage.get("cache_creation_input_tokens"),
                "output_tokens": usage.get("output_tokens"),
            }
        )
    result_event = next(
        (event for event in reversed(events) if event.get("type") == "result"),
        None,
    )
    result_text = result_event.get("result", "") if result_event else ""
    usage = (result_event or {}).get("usage") or {}
    model_usage = (result_event or {}).get("modelUsage") or {}
    actual_output_tokens = usage.get("output_tokens")
    if not isinstance(actual_output_tokens, int):
        actual_output_tokens = sum(
            int(item.get("outputTokens") or 0)
            for item in model_usage.values()
            if isinstance(item, dict)
        )
    assistant_models = [str(turn.get("model") or "") for turn in assistant_turns]
    opus_usage = {
        key: value for key, value in model_usage.items()
        if "opus" in key.lower() and int((value or {}).get("outputTokens") or 0) > 0
    }
    contaminated = (
        not assistant_models
        or any("fable-5-1" not in model.lower() for model in assistant_models)
        or bool(opus_usage)
    )
    words = result_text.split()
    return {
        "label": label,
        "requested_model": MODEL,
        "requested_repetitions": repetitions,
        "command": command[:-1] + ["<frozen output prompt>"],
        "started_at": started_at,
        "finished_at": now_iso(),
        "wall_seconds": wall_seconds,
        "loadavg_before": load_before,
        "loadavg_after": load_after,
        "returncode": completed.returncode,
        "stderr_tail": completed.stderr[-2000:],
        "parse_errors": parse_errors,
        "assistant_turns": assistant_turns,
        "model_usage": model_usage,
        "usage": usage,
        "actual_output_tokens": actual_output_tokens,
        "result_words": len(words),
        "result_all_z": bool(words) and all(word == "z" for word in words),
        "result_sha256": hashlib.sha256(result_text.encode()).hexdigest(),
        "contaminated_by_fallback": contaminated,
        "opus_usage_in_requested_fable": opus_usage,
        "output_tokens_per_second": (
            actual_output_tokens / wall_seconds if wall_seconds > 0 else None
        ),
    }


def same_resets(baseline: dict, current: dict) -> bool:
    return all(
        baseline[key] == current[key]
        for key in (
            "five_hour_resets_at",
            "seven_day_resets_at",
            "fable_scoped_resets_at",
        )
    )


def classify(result: dict) -> dict:
    excluded = []
    included = []
    for call in result["calls"]:
        if call.get("quota_after") is None:
            excluded.append({"label": call["label"], "reason": "missing fresh telemetry"})
            continue
        if call["contaminated_by_fallback"]:
            excluded.append(
                {
                    "label": call["label"],
                    "reason": "actual model/fallback mismatch",
                    "assistant_models": [turn["model"] for turn in call["assistant_turns"]],
                    "model_usage": list(call["model_usage"]),
                }
            )
            continue
        if call["returncode"] != 0 or call["parse_errors"]:
            excluded.append({"label": call["label"], "reason": "CLI/stream failure"})
            continue
        included.append(call)

    output_tokens = sum(call["actual_output_tokens"] for call in included)
    observed_delta = sum(
        call["quota_after"]["fable_scoped"] - call["quota_before"]["fable_scoped"]
        for call in included
    )
    predicted_raw = SCOPED_RAW_COEFFICIENT * output_tokens / 1_000_000
    predicted_price = 2 * predicted_raw
    raw_interval = [predicted_raw - 1, predicted_raw + 1]
    price_interval = [predicted_price - 1, predicted_price + 1]
    in_raw = raw_interval[0] <= observed_delta <= raw_interval[1]
    in_price = price_interval[0] <= observed_delta <= price_interval[1]
    if in_raw and not in_price:
        mapped_zone = "RAW_TOKEN_WEIGHT"
    elif in_price and not in_raw:
        mapped_zone = "API_PRICE_WEIGHT"
    elif in_raw and in_price:
        mapped_zone = "INCONCLUSIVE_OVERLAP"
    else:
        mapped_zone = "INCONCLUSIVE_NOISE"

    verdicts = []
    if predicted_price - predicted_raw < 3:
        verdicts.append("INCONCLUSIVE_UNDERPOWERED")
    if excluded:
        verdicts.append("INCONCLUSIVE_FALLBACK")
    stop_reasons = {stop["reason"] for stop in result["stops"]}
    if "quota_reset_changed" in stop_reasons:
        verdicts.append("INCONCLUSIVE_RESET")
    if "fresh_telemetry_error" in stop_reasons:
        verdicts.append("INCONCLUSIVE_TELEMETRY")
    if not verdicts:
        verdicts.append(mapped_zone)
    elif mapped_zone.startswith("INCONCLUSIVE") and mapped_zone not in verdicts:
        verdicts.append(mapped_zone)

    quota_rows = [
        call["quota_after"] for call in result["calls"] if call.get("quota_after")
    ]
    final_quota = quota_rows[-1] if quota_rows else result["baseline_quota"]
    return {
        "verdicts": verdicts,
        "mapped_zone": mapped_zone,
        "included_calls": [call["label"] for call in included],
        "excluded_calls": excluded,
        "actual_output_tokens": output_tokens,
        "observed_fable_scoped_delta": observed_delta,
        "predicted_raw": predicted_raw,
        "predicted_price": predicted_price,
        "raw_interval": raw_interval,
        "price_interval": price_interval,
        "budget": {
            "fable_scoped_spend_all_calls": (
                final_quota["fable_scoped"] - result["baseline_quota"]["fable_scoped"]
            ),
            "shared_weekly_start": result["baseline_quota"]["seven_day"],
            "shared_weekly_final": final_quota["seven_day"],
            "shared_weekly_spend": (
                final_quota["seven_day"] - result["baseline_quota"]["seven_day"]
            ),
            "fable_scoped_cap": FABLE_SCOPED_CAP,
            "shared_weekly_absolute_cap": COMMON_WEEKLY_CAP,
        },
    }


def self_test() -> None:
    baseline = {"fable_scoped": 1.0, "seven_day": 3.0}

    def scenario(tokens: int, delta: float) -> dict:
        return {
            "baseline_quota": baseline,
            "stops": [],
            "calls": [
                {
                    "label": "fable-1",
                    "actual_output_tokens": tokens,
                    "quota_before": baseline,
                    "quota_after": {"fable_scoped": 1.0 + delta, "seven_day": 4.0},
                    "contaminated_by_fallback": False,
                    "assistant_turns": [{"model": MODEL}],
                    "model_usage": {MODEL: {}},
                    "returncode": 0,
                    "parse_errors": [],
                }
            ],
        }

    assert classify(scenario(72_704, 3))["mapped_zone"] == "RAW_TOKEN_WEIGHT"
    assert classify(scenario(72_704, 7))["mapped_zone"] == "API_PRICE_WEIGHT"
    assert classify(scenario(72_704, 5))["mapped_zone"] == "INCONCLUSIVE_NOISE"
    assert "INCONCLUSIVE_UNDERPOWERED" in classify(scenario(40_000, 3))["verdicts"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        print("SELF_TEST_OK")
        return
    raise SystemExit(
        "SUPERSEDED: 72,704-token harness used the incomplete 142.225996 coefficient; "
        "no live Fable call is permitted"
    )


if __name__ == "__main__":
    main()
