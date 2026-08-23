#!/usr/bin/env python3
"""Mechanical A/A gate and A/B comparison for #376."""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent


def load(stage: str, prefix: str) -> list[dict[str, Any]]:
    return [
        json.loads(path.read_text())
        for path in sorted((ROOT / "raw" / stage).glob(f"{prefix}*/summary.json"))
    ]


def client_overhead(run: dict[str, Any]) -> float:
    timing = run["timing_s"]
    if run["arm"] == "exec":
        return timing["process_handshake"] + timing["queue"] + timing["post_processing"]
    return timing["queue"] + timing["post_processing"]


def cache_ratio(run: dict[str, Any]) -> float:
    usage = run["usage"]
    total = usage.get("input_tokens", 0)
    return usage.get("cached_input_tokens", 0) / total if total else 0.0


def aa() -> dict[str, Any]:
    runs = load("aa", "aa-exec-")
    if len(runs) != 3:
        raise RuntimeError(f"expected 3 A/A runs, got {len(runs)}")
    overhead = [client_overhead(run) for run in runs]
    handshakes = [run["timing_s"]["process_handshake"] for run in runs]
    valid = all(run["ac_pass"] and run["tools"] == 0 for run in runs)
    noise = max(overhead) - min(overhead)
    expected = statistics.median(handshakes)
    result = {
        "metric": "client_overhead_s",
        "runs": [run["label"] for run in runs],
        "values_s": overhead,
        "noise_range_s": noise,
        "handshake_values_s": handshakes,
        "expected_removable_effect_s": expected,
        "all_ac_pass": valid,
        "pass": bool(valid and noise < expected),
        "rule": "pass iff all AC pass and client-overhead range < median exec process/handshake",
    }
    (ROOT / "aa-gate.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )
    return result


def ab() -> dict[str, Any]:
    gate = json.loads((ROOT / "aa-gate.json").read_text())
    if not gate["pass"]:
        raise RuntimeError("A/B was forbidden by A/A gate")
    apps = load("ab", "ab-app-")
    execs = load("ab", "ab-exec-")
    if len(apps) != 2 or len(execs) != 2:
        raise RuntimeError(f"expected 2+2 A/B runs, got {len(apps)}+{len(execs)}")
    runs = [apps[0], execs[0], apps[1], execs[1]]
    overhead_app = [client_overhead(run) for run in apps]
    overhead_exec = [client_overhead(run) for run in execs]
    paired = [client_overhead(b) - client_overhead(a) for a, b in zip(apps, execs)]
    base_hashes = {run["rollout"].get("base_instructions_sha256") for run in runs}
    prefix_hashes = {run["rollout"].get("model_visible_prefix_sha256") for run in runs}
    input_tokens = {run["usage"].get("input_tokens") for run in runs}
    cached = [cache_ratio(run) for run in runs]
    app_cache = statistics.median(cache_ratio(run) for run in apps)
    exec_cache = statistics.median(cache_ratio(run) for run in execs)
    invariant_checks = {
        "all_ac_pass": all(run["ac_pass"] for run in runs),
        "zero_tools": all(run["tools"] == 0 for run in runs),
        "same_calls": len({run["calls"] for run in runs}) == 1,
        "same_model_effort_task_schema_cwd": len({
            (run["model"], run["effort"], run["task_sha256"], run["schema_sha256"], run["cwd"])
            for run in runs
        }) == 1,
        "same_base_instructions_hash": len(base_hashes) == 1,
        "same_model_visible_prefix_hash": len(prefix_hashes) == 1,
        "same_input_tokens": len(input_tokens) == 1,
        "cache_arm_medians_within_2pp": abs(app_cache - exec_cache) <= 0.02,
        "cache_full_range_within_5pp": max(cached) - min(cached) <= 0.05,
    }
    valid = all(invariant_checks.values())
    effect = statistics.median(paired)
    exceeds_noise = abs(effect) > gate["noise_range_s"]
    if valid and exceeds_noise and effect > 0:
        verdict = "leave-app-server"
    elif valid and exceeds_noise and effect < 0:
        verdict = "switch-path"
    else:
        verdict = "no-path-verdict"
    result = {
        "order": [run["label"] for run in runs],
        "primary_metric": "client_overhead_s",
        "app_values_s": overhead_app,
        "exec_values_s": overhead_exec,
        "paired_exec_minus_app_s": paired,
        "median_effect_s": effect,
        "aa_noise_range_s": gate["noise_range_s"],
        "effect_exceeds_aa_noise": exceeds_noise,
        "cache_ratios": {run["label"]: cache_ratio(run) for run in runs},
        "invariant_checks": invariant_checks,
        "valid_causal_comparison": valid,
        "verdict": verdict,
    }
    (ROOT / "comparison.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("aa", "ab"))
    args = parser.parse_args()
    result = aa() if args.stage == "aa" else ab()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
