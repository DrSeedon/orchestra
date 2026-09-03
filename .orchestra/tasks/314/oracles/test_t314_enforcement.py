import asyncio
import time

import pytest

import app.quota_controller as quota_controller
from app.quota_controller import DispatchDecision
from app.quota_gate import QuotaDecision


def _static(state: str) -> QuotaDecision:
    return QuotaDecision(
        state=state,
        model="gpt-5.6-codex",
        provider="codex",
        provider_label="Codex",
        weekly_utilization=80.0,
        observed_at=1.0,
        valid_until=9999999999.0,
        reset_at=None,
        alternatives=(),
        reason=f"static_{state}",
    )


def _adaptive(would_allow, *, zone="TRACK", confidence="operational", reasons=()):
    return DispatchDecision(
        constraints=(),
        would_allow=would_allow,
        binding_constraint=None,
        recommendation="allow" if would_allow else "indeterminate",
        zone=zone,
        confidence=confidence,
        reasons=tuple(reasons),
    )


def _enforce(context, adaptive, static, *, enabled=True):
    assert hasattr(quota_controller, "enforce_new_worker_turn"), (
        "#314 enforcement seam is missing"
    )
    return quota_controller.enforce_new_worker_turn(
        context=context,
        adaptive=adaptive,
        static_decision=static,
        enforcement_enabled=enabled,
    )


def test_t314_orchestrator_exempt_from_adaptive_gate_even_with_spoofed_caller_flag():
    result = _enforce(
        {"server_role": "orchestrator", "is_orchestrator": False, "model": "codex"},
        _adaptive(False, zone="THROTTLE"),
        _static("available"),
    )
    assert result["action"] == "exempt"
    assert result["reason"] == "orchestrator_exempt"


def test_t314_fresh_known_worker_would_hold():
    result = _enforce(
        {"server_role": "worker", "model": "codex", "task_class": "worker"},
        _adaptive(False, zone="THROTTLE"),
        _static("available"),
    )
    assert result["action"] == "hold"
    assert result["reason"] == "adaptive_would_hold"


def test_t314_static_denial_cannot_be_overridden_by_adaptive_allow():
    result = _enforce(
        {"server_role": "worker", "model": "codex"},
        _adaptive(True),
        _static("blocked"),
    )
    assert result["action"] == "static_denial"
    assert result["reason"] == "static_gate_denied"


def test_t314_unknown_or_stale_adaptive_falls_back_to_static_allow():
    result = _enforce(
        {"server_role": "worker", "model": "codex"},
        _adaptive(None, zone="FAIL_SAFE", confidence="unknown", reasons=("telemetry_stale",)),
        _static("available"),
    )
    assert result["action"] == "static_allow"
    assert result["reason"] == "adaptive_indeterminate_static_fallback"


def test_t314_hot_disable_returns_to_static_immediately():
    result = _enforce(
        {"server_role": "worker", "model": "codex"},
        _adaptive(False, zone="THROTTLE"),
        _static("available"),
        enabled=False,
    )
    assert result["action"] == "static_allow"
    assert result["reason"] == "enforcement_hot_disabled"


@pytest.mark.parametrize(
    ("context", "adaptive", "reason"),
    [
        (
            {"server_role": "worker", "model": "codex_fast", "fast_mode": True},
            _adaptive(False, zone="RESERVE", confidence="operational"),
            "fast_disabled_zone",
        ),
        (
            {
                "server_role": "worker",
                "model": "gpt-5.6-sol",
                "task_class": "noncritical",
            },
            _adaptive(False, zone="THROTTLE", confidence="operational"),
            "noncritical_sol_before_luna",
        ),
    ],
)
def test_t314_fast_and_noncritical_sol_fail_safe_policy(context, adaptive, reason):
    result = _enforce(context, adaptive, _static("available"))
    assert result["action"] == "hold"
    assert result["reason"] == reason


def test_t314_luna_fast_remains_admissible_when_codex_runway_is_tight():
    result = _enforce(
        {"server_role": "worker", "model": "gpt-5.6-luna", "fast_mode": True},
        _adaptive(True, zone="RESERVE", confidence="operational"),
        _static("available"),
    )
    assert result["action"] == "adaptive_allow"
    assert result["reason"] == "adaptive_would_allow"


def test_t314_luna_fast_status_exposes_server_owned_sol_suppression():
    status = quota_controller.luna_fast_default_status(zone="THROTTLE", telemetry_available=True)
    assert status == {
        "luna_fast_default": True,
        "sol_suppressed": True,
        "sol_suppression_reason": "codex_runway_tight_route_luna_fast",
        "luna_fast_reason": "server_owned_default",
    }


@pytest.mark.parametrize(
    ("bucket", "model", "sample_age", "suppressed"),
    [
        ("codex:primary", "gpt-5.6-sol", 0, True),
        ("grok:primary", "grok-4.6", 0, False),
        ("codex:primary", "gpt-5.6-sol", 301, False),
    ],
)
def test_t314_sol_status_uses_fresh_codex_primary_only(
    monkeypatch, tmp_path, bucket, model, sample_age, suppressed,
):
    import app.db as db

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "controller.db")
    quota_controller._production_controller = None
    store = quota_controller.SQLiteControllerStore(db.DB_PATH)
    store.reserve_shadow_dispatch(
        decision_id="status-probe",
        constraints=[{
            "bucket": bucket,
            "regime_key": "r",
            "window_id": "w",
            "utilization": 98,
            "q95_next_turn_pp": 1,
            "guard_pp": 0.5,
            "reserve_pp": 0,
            "confidence": "operational",
            "observed_at": time.time() - sample_age,
        }],
        context={"model": model, "session_id": "s", "turn_gen": 1},
    )
    status = quota_controller.get_quota_controller().status()
    assert status["sol_suppressed"] is suppressed


def test_t314_spark_and_grok_use_their_own_adaptive_bucket():
    for model in ("codex_spark", "grok"):
        result = _enforce(
            {"server_role": "worker", "model": model},
            _adaptive(True),
            _static("available"),
        )
        assert result["action"] == "adaptive_allow"


@pytest.mark.asyncio
async def test_t314_concurrent_static_denials_remain_denials():
    results = await asyncio.gather(
        asyncio.to_thread(
            _enforce,
            {"server_role": "worker", "model": "codex"},
            _adaptive(True),
            _static("blocked"),
        ),
        asyncio.to_thread(
            _enforce,
            {"server_role": "worker", "model": "codex"},
            _adaptive(True),
            _static("blocked"),
        ),
    )
    assert [result["action"] for result in results] == ["static_denial", "static_denial"]
