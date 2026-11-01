#!/usr/bin/env python3
"""Hash the sanitized V-1162 fixture pack and create its frozen call order."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import random


ROOT = Path(__file__).resolve().parent
TASK_ROOT = ROOT.parent
SEED = 1162
TASKS = [
    {
        "id": "simple-199-t3",
        "complexity": "simple",
        "historical_origin": "#199 T3, GPT-5.6 Luna/Terra/Sol, medium, N=1/model",
        "validator_semantics": "nested explicit __cause__ chain is included in order; plain output preserved; implicit context excluded",
    },
    {
        "id": "simple-201-accounting",
        "complexity": "simple",
        "historical_origin": "#201 paired GPT-5.6 Luna/Sol arms, high, N=1/model; fixture uses synthetic rates",
        "validator_semantics": "fresh/cached/write/output channels count once; unpriced fixture model fails visibly",
    },
    {
        "id": "complex-v620-binding",
        "complexity": "complex",
        "historical_origin": "V-620 lifecycle task, GPT-5.6/GPT-6 arms at high, N=1/model; synthetic state + temporary Git",
        "validator_semantics": "clean release/complete, required note, dirty/unmerged fail-closed, atomic rollback, other-worker preservation, ordinary Git complete",
    },
    {
        "id": "complex-v543-pidfd",
        "complexity": "complex",
        "historical_origin": "V-543 descriptor ownership/cancel paths; reduced synthetic real-pidfd lifecycle fixture",
        "validator_semantics": "normal/timeout/cancel runs reap children and return open pidfd count to baseline",
    },
]
CONFIGS = [
    {"id": f"terra-{effort}", "model": "gpt-6.1-terra", "effort": effort}
    for effort in ("low", "medium", "high", "xhigh", "max")
] + [
    {"id": "sol-high", "model": "gpt-6.1-sol", "effort": "high"},
    {"id": "luna-high", "model": "gpt-6-luna", "effort": "high"},
]
MODEL_METADATA = {
    "gpt-6.1-terra": {
        "display_name": "GPT-6.1 Terra",
        "runtime": "codex",
        "provider": "openai",
        "stage_a_commit": "460d12c2",
        "manual_only": True,
        "quota_bucket": "codex",
        "quota_lane": "sol",
        "billing": "subscription",
        "api_equivalent_rates_per_million": {"fresh_input": 1.0, "cached_input": 0.05, "cache_write_30m": 1.25, "output": 5.0},
        "context_window": {"registry_fallback": 258400, "runtime_measured": False},
    },
    "gpt-6.1-sol": {
        "display_name": "GPT-6.1 Sol",
        "runtime": "codex",
        "provider": "openai",
        "stage_a_commit": "460d12c2",
        "manual_only": True,
        "quota_bucket": "codex",
        "quota_lane": "sol",
        "billing": "subscription",
        "api_equivalent_rates_per_million": {"fresh_input": 2.0, "cached_input": 0.1, "cache_write_30m": 2.5, "output": 10.0},
        "context_window": {"registry_fallback": 258400, "runtime_measured": False},
    },
    "gpt-6-luna": {
        "display_name": "GPT-6 Luna",
        "runtime": "codex",
        "provider": "openai",
        "stage_a_commit": "pre-existing",
        "manual_only": False,
        "quota_bucket": "codex",
        "quota_lane": "luna",
        "billing": "subscription",
        "api_equivalent_rates_per_million": {"fresh_input": 0.1, "cached_input": 0.01, "cache_write_30m": 0.125, "output": 0.5},
        "context_window": {"registry_fallback": 258400, "runtime_measured": False},
        "policy_note": "protected-local route is insufficient for this public fixture; exact V-1162 grant required",
    },
}
PRIMARY_METRICS = {
    "acceptance": "binary validator result per dispatched task invocation; failed, partial, lost and refused outcomes are not removed",
    "generated_tokens": "provider-reported output_tokens + distinct reasoning_output_tokens, counted once; cache-read is input and excluded",
    "time": "whole task invocation wall from dispatch through terminal validator outcome; request latency also retained where supplied",
    "cost": "actual subscription quota observation if exposed; API-equivalent cost is a separate proxy only, never converted to subscription percentage",
    "paired_unit": "task × repeat × exact model/effort configuration; matched N is reported per cell",
    "uncertainty": "N=2 is a pilot; report raw paired outcomes and ranges; do not claim a fleet-wide winner",
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n")


def relative_hashes(paths: list[Path]) -> dict[str, str]:
    return {
        str(path.relative_to(TASK_ROOT)): sha256(path.read_bytes())
        for path in sorted(paths)
    }


def main() -> None:
    write_json(ROOT / "model-configs.json", {
        "matrix_conditions": CONFIGS,
        "models": MODEL_METADATA,
        "billing": "subscription-only; API-credit fallback forbidden",
        "pricing_note": "API-equivalent Standard rates are metadata only, not subscription cost or a spending cap",
    })
    write_json(ROOT / "primary-metrics.json", PRIMARY_METRICS)

    rng = random.Random(SEED)
    blocks = [(task["id"], repeat) for task in TASKS for repeat in (1, 2)]
    rng.shuffle(blocks)
    run_rows = []
    sequence = 0
    for block_index, (task_id, repeat) in enumerate(blocks, 1):
        conditions = list(CONFIGS)
        rng.shuffle(conditions)
        for slot, condition in enumerate(conditions, 1):
            sequence += 1
            run_rows.append({
                "sequence": sequence,
                "block": block_index,
                "fixture_id": task_id,
                "repeat": repeat,
                "condition_id": condition["id"],
                "model": condition["model"],
                "effort": condition["effort"],
                "billing": "subscription",
                "attempt": 1,
            })
    with (ROOT / "run-order.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(run_rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(run_rows)

    controls_path = ROOT / "validation" / "controls.json"
    control_receipt = json.loads(controls_path.read_text())
    if len(control_receipt["controls"]) != 8 or any(x["outcome"] != "PASS" for x in control_receipt["controls"]):
        raise SystemExit("fixture RED/GREEN controls are incomplete or failed")
    controls = [
        {key: row[key] for key in ("fixture", "control", "expected", "actual", "returncode", "outcome")}
        for row in control_receipt["controls"]
    ]
    controls_path = ROOT / "control-summary.json"
    write_json(controls_path, {"controls": controls})

    files = []
    for task in TASKS:
        task_dir = ROOT / task["id"]
        public = [task_dir / "prompt.md", *sorted((task_dir / "seed").rglob("*"))]
        public = [p for p in public if p.is_file()]
        hidden = [*sorted((task_dir / "oracle").rglob("*")), *sorted((task_dir / "reference").rglob("*"))]
        hidden = [p for p in hidden if p.is_file()]
        files.append({
            **task,
            "model_input_files": relative_hashes(public),
            "hidden_validator_reference_files": relative_hashes(hidden),
        })

    root_files = [
        ROOT / "README.md",
        ROOT / "model-configs.json",
        ROOT / "primary-metrics.json",
        ROOT / "run-order.csv",
        ROOT / "build_manifest.py",
        controls_path,
    ]
    grant = {
        "task_id": "V-1162",
        "allowed_models_efforts": CONFIGS,
        "billing": "subscription",
        "api_credit_fallback": False,
        "max_task_invocations": 56,
        "max_generated_output_plus_reasoning_tokens": 500000,
        "max_wall_seconds": 5400,
        "retry_policy": "none",
        "max_concurrency": 1,
        "counting_note": "56 counts task invocations; internal provider turns are separately metered.",
    }
    manifest = {
        "version": 1,
        "task_id": "V-1162",
        "fixture_kind": "synthetic sanitized reproductions; no Git history or prior model output in model inputs",
        "dispatch_ready": False,
        "dispatch_blocker": "owner grant, live registry activation, and a hard generated-token cap/overshoot boundary are still required",
        "random_seed": SEED,
        "randomization": "shuffle eight (fixture,repeat) blocks; independently shuffle seven conditions within each block",
        "grant": grant,
        "tasks": files,
        "run_order_sha256": sha256((ROOT / "run-order.csv").read_bytes()),
        "root_artifact_hashes": relative_hashes(root_files),
        "fixture_controls": controls,
        "history_versions": {
            "simple-199-t3": "GPT-5.6 Luna/Terra/Sol, medium; historical N=1",
            "simple-201-accounting": "GPT-5.6 Luna/Sol, high; historical N=1; synthetic prices here",
            "complex-v620-binding": "GPT-5.6/GPT-6 and Opus 5.5, high; historical N=1",
            "complex-v543-pidfd": "Opus 5.5/Sonnet 5.5, low/medium/high/max; historical reports V-661/V-667/V-670",
        },
        "activation_dependency": "Stage A is merged; live compiled registry activation and one-shot admission grant are still required before any model call.",
    }
    digest = sha256(json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())
    manifest["manifest_sha256"] = digest
    write_json(ROOT / "manifest.json", manifest)
    (ROOT / "manifest.sha256").write_text(f"{digest}  manifest.json\n")
    print(f"manifest_sha256={digest}")
    print(f"matrix_rows={len(run_rows)} controls={len(controls)} all_controls_passed=true")


if __name__ == "__main__":
    main()
