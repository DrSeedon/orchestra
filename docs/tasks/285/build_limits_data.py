#!/usr/bin/env python3
"""Join the sanitized #285 evidence slices into the durable machine source."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--telemetry", type=Path, required=True)
    parser.add_argument("--official", type=Path, required=True)
    parser.add_argument("--grok", type=Path, required=True)
    parser.add_argument("--laptop", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    result = load(args.base)
    telemetry = load(args.telemetry)
    official = load(args.official)
    grok = load(args.grok)
    result["schema_version"] = 2
    result["generated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    result["canonical_sources"] = {
        "narrative": "docs/tasks/285/research.md",
        "machine": "docs/tasks/285/limits-data.json",
        "telemetry_rows": "docs/tasks/285/parts/telemetry/evidence.json",
        "official_primary_matrix": "docs/tasks/285/parts/official/evidence.json",
        "grok_rows": "docs/tasks/285/parts/grok/evidence.json",
        "html_view": "docs/artifacts/model-limits-source-of-truth.html",
    }
    result["scope"]["contours"] = [
        {
            "id": "vmi3407579",
            "label": "local VPS checkout",
            "source_db": "/home/kesha/orchestra/data/orchestra.db",
            "host_timezone": "Europe/Berlin (CEST UTC+02 at capture)",
            "database_timezone": "UTC",
            "backup_method": "sqlite3.Connection.backup from mode=ro URI",
            "quick_check": "ok",
            "status": "canonical measured series in this artifact",
        },
        {
            "id": "maxim-911aird",
            "label": "user laptop",
            "requested_path": "/home/kesha/orchestra/data/orchestra.db",
            "requested_path_status": "absent on laptop",
            "actual_source_db": "/mnt/data/Projects/Python/orchestra/data/orchestra.db",
            "host_timezone": "Asia/Krasnoyarsk (UTC+07)",
            "backup_method": "remote sqlite3.Connection.backup",
            "status": "measured only if laptop_evidence.status=available; never merged with VPS rows",
        },
    ]
    result["canonical_observed_thresholds"] = telemetry["threshold_intervals"]
    result["canonical_reset_and_drop_events"] = telemetry["reset_or_drop_events"]
    result["live_read_only_capture"] = telemetry["quota_observations"]["live_endpoint"]
    result["claude_fable"] = telemetry["claude_scoped_fable"]
    result["codex_plan_transition"] = telemetry["codex_prolite_to_pro"]
    result["turn_usage_canonical"] = telemetry["turn_aggregates"]
    result["official_claims"] = official
    result["official_claims_addenda"] = [
        {
            "provider": "OpenAI",
            "atomic_claim": "Codex Fast mode speeds supported models by 1.5x; GPT-5.6/5.5 consume 2.5x ChatGPT credits and GPT-5.4 consumes 2x.",
            "shared_or_separate": "service tier inside the regular model/pool; not a model or separate bucket",
            "source_url": "https://learn.chatgpt.com/docs/agent-configuration/speed.md",
            "accessed_date": "2026-08-16",
            "tier": "single-primary",
        },
        {
            "provider": "OpenAI",
            "atomic_claim": "Codex-Spark is a separate less-capable model with its own usage limits, unlike Fast mode.",
            "shared_or_separate": "separate Spark limit",
            "source_url": "https://learn.chatgpt.com/docs/agent-configuration/speed.md",
            "accessed_date": "2026-08-16",
            "tier": "single-primary",
        },
    ]
    result["grok_evidence"] = grok
    if args.laptop and args.laptop.exists():
        laptop = load(args.laptop)
        result["laptop_evidence"] = {"status": "available", "evidence": laptop}
    else:
        result["laptop_evidence"] = {
            "status": "unavailable",
            "reason": "reverse SSH transport did not deliver a validated evidence file before cutoff",
            "partial_backup_excluded": True,
        }
    result["controller_99"] = {
        "status": "proposed policy; not runtime implementation",
        "target_pct": 99,
        "nominal_safety_margin_pct": 1,
        "measurement_guard_formula": "max(0.5 pp integer-display guard, q95 pp/eligible-turn, drift guard)",
        "critical_reserve_formula": "q95 sum of declared critical demand before reset; release only in final max(2h,q95 lead time)",
        "headroom_formula": "H = 99 - utilization - measurement_guard - unreleased_critical_reserve",
        "required_rate_formula": "max(0,H / hours_to_reset)",
        "dispatch_gate": "utilization + q95(turn_pp) + guard <= 99 - unreleased_reserve",
        "forecast": "moving-block bootstrap by bucket+plan+phase; choose block length from autocorrelation, with 3h only as initial sensitivity; p50/p90/p95 plus scheduled queue",
        "zones": [
            {"id": "accelerate", "predicate": "p90 projected end <97 and fresh telemetry"},
            {"id": "track", "predicate": "p50 97..99, p90 <=99.5, early-exhaust risk <10%"},
            {"id": "throttle", "predicate": "p50 >99 or early-exhaust risk >=10%"},
            {"id": "reserve", "predicate": "p90 hits 100 before critical horizon, H<=0, or reported 100"},
            {"id": "fail_safe", "predicate": "sample >10m stale, plan/reset drift, unexplained drop, or insufficient history"},
        ],
        "minimum_history": {
            "cold_start": "<1 complete same-regime window; no automatic acceleration",
            "pilot": "1-2 complete windows; upper-bound dispatch only",
            "operational": ">=3 complete windows, >=20 non-overlapping blocks after thinning at estimated correlation length, effective sample size >=20, >=80% coverage",
        },
        "fast_mode": {"gpt_5_6_and_5_5_credit_multiplier": 2.5, "speed_claim": "1.5x", "separate_bucket": False},
        "fable_constraint": "min(Claude all-model remaining, Fable scoped remaining)",
    }
    result["benchmarks"] = {
        "spark_vs_luna_286": {
            "prereg_commit": "89d00a00",
            "evidence_commit": "43a138a8",
            "tasks": 2,
            "spark_pass": 2,
            "luna_pass": 2,
            "byte_identical_pair_diffs": 2,
            "spark_wall_seconds": 80.304,
            "luna_wall_seconds": 112.138,
            "spark_wall_delta_pct": -28.4,
            "spark_input_tokens": 268254,
            "luna_input_tokens": 331349,
            "spark_output_tokens": 5137,
            "luna_output_tokens": 3422,
            "luna_virtual_api_equivalent_usd": 0.017845,
            "spark_price_usd": None,
            "routing_boundary": "Spark only fully specified one-file leaf with frozen independent oracle; Luna otherwise",
        },
        "spark_missing_data_222": {"spark_invented": "2/2", "luna_stopped_and_asked": "2/2", "spark_164k_loud_fail": "2/2"},
        "normal_vs_fast_208": {
            "status": "not delivered before the research cutoff",
            "observed_multiplier": None,
            "official_claim_kept_separate": True,
            "official_speed_claim": "1.5x for GPT-5.6/5.5",
            "official_credit_multiplier": 2.5,
        },
    }
    result["research_fan_usage"] = {
        "captured_from": "fresh WAL-safe backup after child completion",
        "cost_semantics": "virtual API-equivalent; not real payment",
        "agents": [
            {"name": "limit285-telemetry", "model": "gpt-5.6-sol", "finalized_turns": 1, "input_tokens": 4836532, "output_tokens": 38243, "cache_read_tokens": 4636928, "cache_create_tokens": 0, "virtual_cost_usd": 4.463774},
            {"name": "limit285-official", "model": "gpt-5.6-sol", "finalized_turns": 1, "input_tokens": 8182150, "output_tokens": 47979, "cache_read_tokens": 7800064, "cache_create_tokens": 0, "virtual_cost_usd": 7.249832},
            {"name": "limit285-grok", "model": "gpt-5.6-sol", "finalized_turns": 1, "input_tokens": 10861442, "output_tokens": 47979, "cache_read_tokens": 10515456, "cache_create_tokens": 0, "virtual_cost_usd": 8.427028},
            {"name": "research-limit-truth", "model": "gpt-5.6-sol", "finalized_turns": 0, "in_flight": True, "tokens": None, "virtual_cost_usd": None, "unavailable_reason": "turn_usage is written only after the current terminal event"},
        ],
    }
    result["security_note"] = {
        "status": "findings recorded; no credential rotation or process/service restart performed",
        "bug_reports": [
            {
                "record_id": "20260816T090547.708704Z-1af71fae7df546a4a5b3b73e0d57b3f3.md",
                "title": "Live Codex app-server argv still exposes MCP credentials after secrets-to-file fix",
            },
            {
                "record_id": "20260816T092037.705786Z-9c2914c525644fba87d48c2d208ec7d4.md",
                "title": "Secret masker leaves credentials embedded in proxy URLs visible in tool stderr",
            },
        ],
        "rotation_set": [
            {
                "contour": "VPS legacy Codex app-server process",
                "credential_classes": [
                    "Orchestra bridge/session credential",
                    "YouGile account/API credentials",
                    "Google OAuth client credentials",
                    "OpenRouter API key",
                ],
                "credential_owner": "not safely identifiable from env-free process metadata",
            },
            {
                "contour": "laptop Orchestra",
                "credential_classes": ["HTTP(S) proxy URL userinfo credential"],
                "credential_owner": "not safely identifiable from DB-only evidence",
            },
        ],
        "legacy_process_safe_metadata": {
            "checked_at_utc": "2026-08-16T09:31:32Z",
            "live": True,
            "start_time_host": "Sun Aug 16 11:00:47 2026",
            "comm": "codex",
            "executable_class": "vendor Codex binary",
            "ephemeral_process_identifiers_published": False,
            "argv_cmdline_environ_inspected": False,
        },
        "owner_run_rotation_restart": [
            "Privately identify each active credential in its owning secret store; do not paste values into chat or logs.",
            "Rotate/revoke each listed credential at its provider, then replace it in the owning mode-0600 secret/config file.",
            "During an owner-approved maintenance window, reconnect the affected legacy Codex session and restart laptop Orchestra so old process state is gone.",
            "Validate the affected integrations with value-free health checks and safe process metadata; then revoke any still-valid predecessor.",
            "Re-run the shape-only scanner over task artifacts and selected commits without printing matches.",
        ],
        "scanner_command": "python3 docs/tasks/285/scan_artifacts.py --path docs/tasks/285 --path docs/tasks/286 --path docs/artifacts/model-limits-source-of-truth.html --commit HEAD",
    }
    result["confidence"] = [
        {"finding": "Claude 5h/weekly threshold durations", "level": "MEDIUM", "basis": "direct 5-minute snapshots with explicit gap breaks; integer percentages and retention gaps remain"},
        {"finding": "Fable is a scoped constraint inside overall weekly", "level": "CONFIRMED", "basis": "official primary documentation plus live all/scoped response"},
        {"finding": "two post-100 Opus turns were not Fable or usage credits", "level": "CONFIRMED", "basis": "completed turn_usage model rows plus live disabled/zero credit state"},
        {"finding": "reason Anthropic admitted post-100 turns", "level": "UNCERTAIN", "basis": "rounding, delayed/admission-time accounting, and another undocumented allowance are compatible; exact enforcement is not public"},
        {"finding": "current Codex pro runway", "level": "LOW", "basis": "structural plan break and less than one complete same-regime window"},
        {"finding": "laptop Grok was nearly exhausted", "level": "CONFIRMED", "basis": "fresh WAL-safe provider snapshot at 98%"},
        {"finding": "VPS datacenter-IP blocking", "level": "UNCERTAIN", "basis": "user report; retained journal has zero datacenter/IP markers"},
        {"finding": "controller will reliably finish at 99%", "level": "HYPOTHESIS", "basis": "policy and one replay example; not implemented or prospectively calibrated"},
    ]
    result["limitations"] = [
        "Primary measured series is vmi3407579; laptop path named in the request does not exist on the laptop.",
        "Threshold/reset event times are bounded by adjacent samples and gaps, not exact times.",
        "106 ambiguous legacy Claude double-zero rows are excluded as unknown.",
        "Historical provider_usage does not retain Claude scoped Fable.",
        "Grok has 0 turn_usage rows; recent real-turn token breakdown is unavailable, not zero.",
        "Codex pro history starts at the 2026-08-16 structural break; prolite runway is not transferred.",
        "Spark numeric capacity, reset schedule, and final price are not public.",
        "Parent research usage is in-flight and cannot be finalized inside its own terminal report.",
        "The bounded #208 normal-vs-Fast paired measurement was requested but not delivered before cutoff; only the official claim is used.",
    ]
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
