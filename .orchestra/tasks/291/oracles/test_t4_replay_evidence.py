import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]


def _replay_module():
    path = ROOT / "scripts" / "replay_quota_controller.py"
    assert path.exists(), "scripts/replay_quota_controller.py is not implemented"
    spec = importlib.util.spec_from_file_location("replay_quota_controller", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_t4_accepted_285_data_is_not_enforcement_evidence():
    replay = _replay_module()
    data = json.loads((ROOT / "docs/tasks/285/limits-data.json").read_text())

    result = replay.replay_limits_data(data)

    assert result["input_schema_version"] == 2
    assert result["eligible"] is False
    assert "not_prospective" in result["reasons"]
    assert "insufficient_stable_same_regime_windows" in result["reasons"]
    assert any(item["reason"] == "plan_transition" for item in result["regime_splits"])
    assert any(item["reason"] == "sliding_zero_anchor" for item in result["exclusions"])
    assert result["contours_merged"] is False


def _qualifying_metrics():
    return {
        "prospective": True,
        "corrupt_authoritative_decision_count": 0,
        "live_regime_matches": True,
        "enabled_strata": [
            "codex:primary/sol/normal/worker",
            "grok:primary/grok/normal/worker",
        ],
        "constraints": {
            bucket: {
                "stable_same_regime_windows": 3,
                "telemetry_coverage_pct_by_window": [90, 91, 92],
                "non_overlapping_blocks": 20,
                "effective_sample_size": 20,
                "unsafe_allow_count": 0,
                "qualified_window_drift_count": 0,
                "adaptive_early_exhaustion_hours": 0,
                "static_early_exhaustion_hours": 1,
                "adaptive_median_unused_headroom": 1,
                "static_median_unused_headroom": 4,
                "adaptive_false_holds": 0,
                "static_false_holds": 1,
            }
            for bucket in ("codex:primary", "grok:primary")
        },
        "strata": {
            "codex:primary/sol/normal/worker": {
                "constraints": ["codex:primary"],
                "settled_usable_outcomes": 20,
                "q95_empirical_coverage": 0.95,
                "q95_binomial_lower_95": 0.80,
            },
            "grok:primary/grok/normal/worker": {
                "constraints": ["grok:primary"],
                "settled_usable_outcomes": 20,
                "q95_empirical_coverage": 0.95,
                "q95_binomial_lower_95": 0.80,
            },
        },
    }


def test_t4_every_machine_gate_clause_has_a_named_failure():
    replay = _replay_module()
    good = _qualifying_metrics()
    assert replay.evaluate_evidence_metrics(good) == {
        "eligible": True,
        "eligible_strata": good["enabled_strata"],
        "reasons": [],
    }

    def mutate_global(metrics, field, value):
        metrics[field] = value

    def mutate_constraint(metrics, field, value):
        metrics["constraints"]["grok:primary"][field] = value

    def mutate_stratum(metrics, field, value):
        metrics["strata"]["grok:primary/grok/normal/worker"][field] = value

    mutations = (
        (mutate_global, "prospective", False, "not_prospective"),
        (mutate_global, "corrupt_authoritative_decision_count", 1,
         "corrupt_authoritative_decision"),
        (mutate_global, "live_regime_matches", False, "live_regime_mismatch"),
        (mutate_constraint, "stable_same_regime_windows", 2,
         "insufficient_stable_same_regime_windows:grok:primary"),
        (mutate_constraint, "telemetry_coverage_pct_by_window", [90, 89, 92],
         "insufficient_telemetry_coverage:grok:primary"),
        (mutate_constraint, "non_overlapping_blocks", 19,
         "insufficient_non_overlapping_blocks:grok:primary"),
        (mutate_constraint, "effective_sample_size", 19,
         "insufficient_effective_sample_size:grok:primary"),
        (mutate_constraint, "unsafe_allow_count", 1,
         "unsafe_allow_observed:grok:primary"),
        (mutate_constraint, "qualified_window_drift_count", 1,
         "qualified_window_has_drift:grok:primary"),
        (mutate_constraint, "adaptive_early_exhaustion_hours", 2,
         "worse_than_static_early_exhaustion:grok:primary"),
        (mutate_constraint, "adaptive_median_unused_headroom", 5,
         "worse_than_static_unused_headroom:grok:primary"),
        (mutate_constraint, "adaptive_false_holds", 2,
         "worse_than_static_false_holds:grok:primary"),
        (mutate_stratum, "settled_usable_outcomes", 19,
         "insufficient_settled_outcomes:grok:primary/grok/normal/worker"),
        (mutate_stratum, "q95_empirical_coverage", 0.90,
         "q95_undercoverage:grok:primary/grok/normal/worker"),
        (mutate_stratum, "q95_binomial_lower_95", 0.79,
         "q95_lower_bound:grok:primary/grok/normal/worker"),
    )
    for mutate, field, bad_value, reason in mutations:
        bad = json.loads(json.dumps(good))
        mutate(bad, field, bad_value)
        verdict = replay.evaluate_evidence_metrics(bad)
        assert verdict["eligible"] is False
        assert reason in verdict["reasons"]


def test_t4_missing_fields_and_cross_bucket_evidence_fail_closed():
    replay = _replay_module()
    good = _qualifying_metrics()

    missing_constraint = json.loads(json.dumps(good))
    del missing_constraint["constraints"]["grok:primary"]
    verdict = replay.evaluate_evidence_metrics(missing_constraint)
    assert verdict["eligible"] is False
    assert verdict["eligible_strata"] == ["codex:primary/sol/normal/worker"]
    assert "missing_constraint:grok:primary" in verdict["reasons"]

    missing_stratum = json.loads(json.dumps(good))
    del missing_stratum["strata"]["grok:primary/grok/normal/worker"]
    verdict = replay.evaluate_evidence_metrics(missing_stratum)
    assert verdict["eligible"] is False
    assert verdict["eligible_strata"] == ["codex:primary/sol/normal/worker"]
    assert "missing_stratum:grok:primary/grok/normal/worker" in verdict["reasons"]

    missing_q95 = json.loads(json.dumps(good))
    del missing_q95["strata"]["grok:primary/grok/normal/worker"]["q95_binomial_lower_95"]
    verdict = replay.evaluate_evidence_metrics(missing_q95)
    assert verdict["eligible"] is False
    assert "missing_field:q95_binomial_lower_95:grok:primary/grok/normal/worker" in verdict["reasons"]


def test_t4_replay_is_causal_before_future_rows_diverge():
    replay = _replay_module()
    prefix = [
        {
            "observed_at": "2030-01-01T00:00:00Z",
            "bucket": "codex:primary",
            "utilization": 50,
            "actual_turn_pp": 1.0,
            "regime_key": "r1",
        },
        {
            "observed_at": "2030-01-01T01:00:00Z",
            "bucket": "codex:primary",
            "utilization": 51,
            "actual_turn_pp": 2.0,
            "regime_key": "r1",
        },
    ]
    low_future = prefix + [{
        "observed_at": "2030-01-01T02:00:00Z",
        "bucket": "codex:primary",
        "utilization": 52,
        "actual_turn_pp": 0.5,
        "regime_key": "r1",
    }]
    high_future = prefix + [{
        "observed_at": "2030-01-01T02:00:00Z",
        "bucket": "codex:primary",
        "utilization": 95,
        "actual_turn_pp": 20.0,
        "regime_key": "r1",
    }]

    low = replay.replay_observation_series(low_future)
    high = replay.replay_observation_series(high_future)
    low_prefix = [d for d in low["decisions"] if d["evaluated_at"] < "2030-01-01T02:00:00Z"]
    high_prefix = [d for d in high["decisions"] if d["evaluated_at"] < "2030-01-01T02:00:00Z"]

    assert json.dumps(low_prefix, sort_keys=True) == json.dumps(high_prefix, sort_keys=True)
    assert low["decisions"][-1] != high["decisions"][-1]
