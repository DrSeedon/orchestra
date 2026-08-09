from datetime import datetime, timezone

import pytest

from app.quota_gate import (
    QuotaGateError,
    evaluate_worker_admission,
    require_worker_admission,
    worker_readiness_envelope,
)


NOW = 2_000_000_000.0


def _provider(label: str, utilization=10, *, extra=None):
    windows = [
        {
            "id": "weekly",
            "window_minutes": 10080,
            "utilization": utilization,
            "resets_at": "2033-05-18T04:33:20+00:00",
        }
    ]
    if extra:
        windows.extend(extra)
    return {"label": label, "windows": windows}


def _snapshot(*, anthropic=10, codex=10, spark=10, timestamp=NOW - 10):
    return (
        {
            "anthropic": _provider("Claude", anthropic),
            "codex": _provider("Codex", codex),
            "codex_spark": _provider("Codex Spark", spark),
        },
        {"anthropic": timestamp, "codex": timestamp, "codex_spark": timestamp},
    )


@pytest.mark.parametrize(
    ("model", "bucket"),
    [
        ("claude-opus-5[1m]", "anthropic"),
        ("gpt-5.6-sol", "codex"),
        ("gpt-5.3-codex-spark", "codex_spark"),
    ],
)
def test_exact_weekly_threshold_for_each_bucket(model, bucket):
    providers, observed = _snapshot()
    providers[bucket] = _provider(providers[bucket]["label"], 94.9)
    assert evaluate_worker_admission(model, providers, observed, now=NOW).state == "available"

    providers[bucket] = _provider(providers[bucket]["label"], 95)
    decision = evaluate_worker_admission(model, providers, observed, now=NOW)
    assert decision.state == "blocked"
    assert decision.weekly_utilization == 95


def test_dual_envelope_preserves_exact_threshold_for_legacy_and_new_clients():
    providers, observed = _snapshot(codex=94.999)
    allowed = worker_readiness_envelope(
        evaluate_worker_admission("gpt-5.6-sol", providers, observed, now=NOW),
        now=NOW,
    )
    assert allowed["decision_state"] == "available"
    assert allowed["state"] == "available"
    assert allowed["wire_version"] == 2

    providers["codex"] = _provider("Codex", 95)
    blocked = worker_readiness_envelope(
        evaluate_worker_admission("gpt-5.6-sol", providers, observed, now=NOW),
        now=NOW,
    )
    assert blocked["decision_state"] == "blocked"
    assert blocked["state"] == "reset"
    assert blocked["decision_reset_at"] == "2033-05-18T04:33:20+00:00"
    assert blocked["reset_at"] == blocked["decision_reset_at"]


def test_dual_envelope_unknown_gets_only_synthetic_legacy_retry():
    providers, observed = _snapshot()
    observed["codex"] = None
    decision = evaluate_worker_admission("gpt-5.6-sol", providers, observed, now=NOW)

    payload = worker_readiness_envelope(decision, now=NOW)

    assert payload["decision_state"] == "unknown"
    assert payload["state"] == "reset"
    assert payload["decision_reset_at"] is None
    expected = datetime.fromtimestamp(
        NOW + 60, timezone.utc,
    ).isoformat()
    assert payload["reset_at"] == expected


def test_dual_envelope_not_applicable_has_no_synthetic_timestamps():
    decision = evaluate_worker_admission("grok-4.5", {}, {}, now=NOW)

    payload = worker_readiness_envelope(decision, now=NOW)

    assert payload["decision_state"] == "not_applicable"
    assert payload["state"] == "available"
    assert payload["observed_at"] is None
    assert payload["valid_until"] is None
    assert payload["decision_reset_at"] is None
    assert payload["reset_at"] is None


def test_short_window_does_not_block_weekly_headroom():
    providers, observed = _snapshot(anthropic=94)
    providers["anthropic"]["windows"].insert(0, {
        "id": "five_hour", "window_minutes": 300, "utilization": 100,
    })
    decision = evaluate_worker_admission(
        "claude-opus-5[1m]", providers, observed, now=NOW,
    )
    assert decision.state == "available"
    assert decision.weekly_utilization == 94


@pytest.mark.parametrize(
    "observed",
    [None, "bad", datetime(2033, 5, 18), NOW - 300, NOW + 1],
)
def test_missing_malformed_stale_and_future_observations_fail_closed(observed):
    providers, timestamps = _snapshot()
    timestamps["codex"] = observed
    decision = evaluate_worker_admission("gpt-5.6-sol", providers, timestamps, now=NOW)
    assert decision.state == "unknown"
    assert not decision.allowed


@pytest.mark.parametrize("utilization", [None, "95", float("nan"), float("inf"), -1, True])
def test_malformed_weekly_utilization_fails_closed(utilization):
    providers, observed = _snapshot()
    providers["codex"] = _provider("Codex", utilization)
    assert evaluate_worker_admission(
        "gpt-5.6-sol", providers, observed, now=NOW,
    ).state == "unknown"


def test_missing_weekly_window_fails_closed_even_with_five_hour_data():
    providers, observed = _snapshot()
    providers["codex"] = {
        "label": "Codex",
        "windows": [{"window_minutes": 300, "utilization": 0}],
    }
    assert evaluate_worker_admission(
        "gpt-5.6-sol", providers, observed, now=NOW,
    ).state == "unknown"


def test_codex_and_spark_are_independent_buckets():
    providers, observed = _snapshot(codex=95, spark=1)
    sol = evaluate_worker_admission("gpt-5.6-sol", providers, observed, now=NOW)
    spark = evaluate_worker_admission("gpt-5.3-codex-spark", providers, observed, now=NOW)
    assert sol.state == "blocked"
    assert spark.state == "available"

    providers, observed = _snapshot(codex=2, spark=95)
    assert evaluate_worker_admission(
        "gpt-5.6-sol", providers, observed, now=NOW,
    ).state == "available"
    assert evaluate_worker_admission(
        "gpt-5.3-codex-spark", providers, observed, now=NOW,
    ).state == "blocked"


def test_only_positively_resolved_grok_is_exempt_and_unknown_model_fails_closed():
    grok = evaluate_worker_admission("grok-4.5", {}, {}, now=NOW)
    unknown = evaluate_worker_admission("grok-future-unknown", {}, {}, now=NOW)
    assert grok.state == "not_applicable"
    assert grok.allowed
    assert unknown.state == "unknown"
    assert not unknown.allowed


def test_alternatives_require_fresh_available_weekly_bucket():
    providers, observed = _snapshot(anthropic=95, codex=2, spark=1)
    observed["codex"] = NOW - 300
    decision = evaluate_worker_admission(
        "claude-opus-5[1m]", providers, observed, now=NOW,
    )
    assert decision.state == "blocked"
    assert decision.alternatives == ({"provider": "codex_spark", "label": "Codex Spark"},)


def test_multiple_weekly_windows_block_on_any_and_keep_latest_future_reset():
    providers, observed = _snapshot()
    providers["codex"] = _provider("Codex", 10, extra=[
        {
            "window_minutes": 10080,
            "utilization": 97,
            "resets_at": "2034-01-01T00:00:00+00:00",
        }
    ])
    decision = evaluate_worker_admission("gpt-5.6-sol", providers, observed, now=NOW)
    assert decision.state == "blocked"
    assert decision.weekly_utilization == 97
    assert decision.reset_at == "2034-01-01T00:00:00+00:00"


def test_blocked_reset_ignores_later_reset_from_available_weekly_window():
    providers, observed = _snapshot()
    providers["codex"] = _provider("Codex", 95, extra=[
        {
            "window_minutes": 10080,
            "utilization": 10,
            "resets_at": "2034-01-01T00:00:00+00:00",
        }
    ])

    decision = evaluate_worker_admission("gpt-5.6-sol", providers, observed, now=NOW)

    assert decision.state == "blocked"
    assert decision.reset_at == "2033-05-18T04:33:20+00:00"


def test_non_string_model_is_unknown_not_exempt():
    decision = evaluate_worker_admission(None, {}, {}, now=NOW)

    assert decision.state == "unknown"
    assert decision.provider == ""


def test_quota_error_is_non_retryable_and_names_dynamic_alternative():
    providers, observed = _snapshot(anthropic=95, codex=2, spark=95)
    decision = evaluate_worker_admission(
        "claude-opus-5[1m]", providers, observed, now=NOW,
    )
    with pytest.raises(QuotaGateError) as caught:
        require_worker_admission(decision)
    assert caught.value.code == "weekly_quota_blocked"
    assert caught.value.retryable is False
    assert "Codex" in str(caught.value)
    assert caught.value.envelope()["error"]["details"]["provider"] == "anthropic"
