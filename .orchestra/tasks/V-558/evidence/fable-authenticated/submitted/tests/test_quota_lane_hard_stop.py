"""Отдельные жёсткие потолки полос (`QUOTA_LANE_HARD_STOP_PCT`).

Sol по умолчанию останавливается на 95%, чтобы хвост пула Codex достался дешёвой Luna;
общий `QUOTA_HARD_STOP_PCT` ограничивает потолок полосы сверху. Числа в ожиданиях —
литералы по спеке: тест обязан покраснеть, когда правило поменяют.
"""

from datetime import datetime, timezone

import pytest

import app.db as db
import app.quota_gate as quota_gate
import app.routes.system as system
from app.quota_gate import (
    QuotaPolicy,
    evaluate_worker_admission,
    line_limit,
    line_release_progress,
    quota_policy,
)

NOW = 2_000_000_000.0
WEEK = 10080
ENV = "QUOTA_LANE_HARD_STOP_PCT"


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


def _window(minutes, utilization, *, progress=1.0, window_id="primary", label="w"):
    return {
        "id": window_id, "label": label, "window_minutes": minutes,
        "utilization": utilization,
        "resets_at": _iso(NOW + minutes * 60 * (1.0 - progress)),
    }


def _codex(utilization, *, progress=1.0):
    return {"codex": {"label": "Codex", "windows": [_window(WEEK, utilization, progress=progress)]}}


def _decide(model, providers, *, policy=None):
    stamps = {bucket: NOW - 5 for bucket in ("anthropic", "codex", "codex_spark")}
    return evaluate_worker_admission(model, providers, stamps, now=NOW, policy=policy)


@pytest.fixture
def startup_env(monkeypatch):
    """Снимок окружения процесса, как его читает `quota_policy()`."""
    def configure(**overrides):
        monkeypatch.setattr(
            quota_gate, "_startup_quota_env",
            {name: overrides.get(name) for name in quota_gate._QUOTA_ENV_NAMES},
        )
    configure()
    return configure


# ── критерий приёмки ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("model", ["gpt-5.6-sol", "gpt-6-astra"])
def test_codex_at_96_blocks_the_sol_lane_but_admits_luna(model):
    sol = _decide(model, _codex(96.0))
    luna = _decide("gpt-5.6-luna", _codex(96.0))

    assert sol.lane == "sol" and sol.state == "blocked", sol.reason
    assert sol.hard_limit_pct == 95.0 and sol.limit_pct == 95.0
    assert sol.release_status == "at_reset"
    assert "hard stop 95%" in sol.reason
    assert luna.lane == "luna" and luna.state == "available", luna.reason
    assert luna.hard_limit_pct == 99.0


@pytest.mark.parametrize("model", ["gpt-5.6-sol", "gpt-6-astra", "gpt-5.6-luna"])
def test_codex_at_99_5_blocks_both_lanes(model):
    decision = _decide(model, _codex(99.5))
    assert decision.state == "blocked", decision.reason
    assert decision.release_status == "at_reset"


@pytest.mark.parametrize("model", ["gpt-5.6-sol", "gpt-6-astra", "gpt-5.6-luna"])
def test_codex_at_94_9_admits_all_three_models(model):
    decision = _decide(model, _codex(94.9))
    assert decision.state == "available", decision.reason
    assert decision.release_status == "open"


def test_defaults_sol_95_and_everyone_else_shares_99():
    policy = quota_policy()
    assert dict(policy.lane_hard_stop_pct) == {"sol": 95.0}
    assert policy.hard_stop_for("sol") == 95.0
    for lane in ("luna", "spark", "claude", "unknown-lane", None):
        assert policy.hard_stop_for(lane) == 99.0
    assert dict(quota_gate.LANE_HARD_STOP_PCT) == {"sol": 95.0}


@pytest.mark.parametrize("model, key, utilization, state", [
    ("claude-opus-5[1m]", "anthropic", 98.9, "available"),
    ("claude-opus-5[1m]", "anthropic", 99.0, "blocked"),
    ("gpt-5.3-codex-spark", "codex_spark", 98.9, "available"),
    ("gpt-5.3-codex-spark", "codex_spark", 99.0, "blocked"),
])
def test_claude_and_spark_keep_the_common_hard_stop(model, key, utilization, state):
    providers = {key: {"label": key, "windows": [_window(WEEK, utilization)]}}
    decision = _decide(model, providers)
    assert decision.state == state, decision.reason
    assert decision.hard_limit_pct == 99.0


# ── конфигурация ─────────────────────────────────────────────────────────────


def test_env_sets_several_lanes(startup_env):
    startup_env(QUOTA_LANE_HARD_STOP_PCT="sol=95,luna=90")
    policy = quota_policy()
    assert dict(policy.lane_hard_stop_pct) == {"sol": 95.0, "luna": 90.0}
    assert policy.hard_stop_for("luna") == 90.0
    luna = _decide("gpt-5.6-luna", _codex(90.0))
    assert luna.state == "blocked" and luna.hard_limit_pct == 90.0


def test_the_configured_set_replaces_the_default_one(startup_env):
    """Полоса, которой в строке нет, возвращается к общему потолку."""
    startup_env(QUOTA_LANE_HARD_STOP_PCT="luna=90")
    policy = quota_policy()
    assert dict(policy.lane_hard_stop_pct) == {"luna": 90.0}
    assert policy.hard_stop_for("sol") == 99.0
    # Sol снова идёт до общего потолка: 96% у сброса под линией 99 — допуск.
    sol = _decide("gpt-5.6-sol", _codex(96.0))
    assert sol.state == "available" and sol.hard_limit_pct == 99.0 and sol.limit_pct == 99.0
    assert _decide("gpt-5.6-sol", _codex(98.9)).state == "available"
    assert _decide("gpt-5.6-sol", _codex(99.0)).state == "blocked"


def test_empty_string_means_no_lane_ceilings(startup_env):
    startup_env(QUOTA_LANE_HARD_STOP_PCT="")
    policy = quota_policy()
    assert dict(policy.lane_hard_stop_pct) == {}
    assert policy.hard_stop_for("sol") == 99.0
    assert _decide("gpt-5.6-sol", _codex(98.9)).state == "available"


@pytest.mark.parametrize("raw", [
    "sol", "sol=abc", "sol=101", "=95", "sol=95,", ",sol=95", "sol=95,,luna=90",
    "sol=0", "sol=-5", "sol=", "sol=nan", "sol=inf", "sol==95", "sol=95;luna=90",
])
def test_invalid_items_raise_with_the_variable_name(startup_env, raw):
    startup_env(QUOTA_LANE_HARD_STOP_PCT=raw)
    with pytest.raises(ValueError, match=ENV):
        quota_policy()


@pytest.mark.parametrize("raw", ["1", "100", "99.5", "1.0"])
def test_boundary_percentages_are_accepted(startup_env, raw):
    startup_env(QUOTA_LANE_HARD_STOP_PCT=f"sol={raw}")
    assert quota_policy().lane_hard_stop_pct["sol"] == float(raw)


def test_lane_names_are_case_insensitive_and_whitespace_tolerant(startup_env):
    startup_env(QUOTA_LANE_HARD_STOP_PCT=" Sol = 90 , LUNA=80 ")
    assert dict(quota_policy().lane_hard_stop_pct) == {"sol": 90.0, "luna": 80.0}


def test_common_hard_stop_bounds_the_lane_ceiling_from_above(startup_env):
    startup_env(QUOTA_HARD_STOP_PCT="90", QUOTA_LANE_HARD_STOP_PCT="sol=95,luna=80")
    policy = quota_policy()
    assert policy.hard_stop_for("sol") == 90.0
    assert policy.hard_stop_for("luna") == 80.0
    assert policy.hard_stop_for(None) == 90.0
    sol = _decide("gpt-5.6-sol", _codex(91.0))
    assert sol.state == "blocked" and sol.hard_limit_pct == 90.0


def test_dotenv_lane_ceilings_are_reloaded_live(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("QUOTA_LANE_HARD_STOP_PCT=sol=80\n")
    monkeypatch.setattr(quota_gate, "_DOTENV_PATH", env_file)
    monkeypatch.setattr(
        quota_gate, "_startup_quota_env", {name: None for name in quota_gate._QUOTA_ENV_NAMES},
    )
    monkeypatch.setattr(quota_gate, "_dotenv_loaded", False)
    monkeypatch.setattr(quota_gate, "_dotenv_mtime_ns", None)
    monkeypatch.setattr(quota_gate, "_dotenv_values", {})
    monkeypatch.setattr(quota_gate, "_dotenv_quota_keys", frozenset())

    assert quota_policy().hard_stop_for("sol") == 80.0
    assert _decide("gpt-5.6-sol", _codex(85.0)).state == "blocked"

    env_file.write_text("QUOTA_LANE_HARD_STOP_PCT=luna=70\n")
    quota_gate._dotenv_loaded = False
    policy = quota_policy()
    assert dict(policy.lane_hard_stop_pct) == {"luna": 70.0}
    assert policy.hard_stop_for("sol") == 99.0
    assert _decide("gpt-5.6-sol", _codex(85.0)).state == "available"

    env_file.write_text("QUOTA_LANE_HARD_STOP_PCT=sol\n")
    quota_gate._dotenv_loaded = False
    with pytest.raises(ValueError, match=ENV):
        quota_policy()


# ── контракт QuotaPolicy ─────────────────────────────────────────────────────


def _policy(**overrides):
    base = dict(
        hard_stop_pct=99.0, tolerance_start_pp=10.0, tolerance_end_pp=1.0,
        curve_exponent=2.5, gated_lanes=frozenset({"claude", "sol"}),
        curved_lanes=frozenset({"sol"}),
    )
    return QuotaPolicy(**{**base, **overrides})


def test_policy_accepts_and_exposes_a_mapping():
    policy = _policy(lane_hard_stop_pct={"sol": 95, "luna": 90})
    assert policy.lane_hard_stop_pct == {"sol": 95.0, "luna": 90.0}
    assert policy.lane_hard_stop_pct["sol"] == 95.0
    assert policy.hard_stop_for("sol") == 95.0
    assert policy.hard_stop_for("luna") == 90.0
    assert policy.hard_stop_for("claude") == 99.0
    assert policy.hard_stop_for(None) == 99.0
    with pytest.raises(TypeError):
        policy.lane_hard_stop_pct["sol"] = 50.0  # type: ignore[index]


def test_policy_without_the_mapping_uses_the_common_ceiling_only():
    policy = _policy()
    assert dict(policy.lane_hard_stop_pct) == {}
    assert policy.hard_stop_for("sol") == 99.0


@pytest.mark.parametrize("bad", [{"sol": 101}, {"sol": "abc"}, {"": 95}, {"sol": 0}])
def test_policy_rejects_invalid_mappings(bad):
    with pytest.raises(ValueError):
        _policy(lane_hard_stop_pct=bad)


def test_line_and_release_forecast_follow_the_lane_ceiling():
    policy = _policy(lane_hard_stop_pct={"sol": 95.0})
    assert line_limit(1.0, "sol", policy) == 95.0
    assert line_limit(1.0, "claude", policy) == 99.0
    assert line_limit(1.0, None, policy) == 99.0
    assert line_release_progress(96.0, "sol", policy) == float("inf")
    root = line_release_progress(94.9, "sol", policy)
    assert 0.0 < root < 1.0
    assert line_limit(root, "sol", policy) == pytest.approx(94.9, abs=1e-6)
    # Прямая (Claude) с потолком полосы ниже общего тоже не поднимается выше него.
    capped = _policy(lane_hard_stop_pct={"claude": 90.0})
    assert line_limit(1.0, "claude", capped) == 90.0
    assert line_release_progress(91.0, "claude", capped) == float("inf")


def test_release_forecast_at_reset_uses_the_lane_ceiling():
    sol = _decide("gpt-5.6-sol", _codex(96.0, progress=0.5))
    assert sol.state == "blocked" and sol.release_status == "at_reset"
    assert sol.release_in_seconds == pytest.approx(WEEK * 60 * 0.5)
    luna = _decide("gpt-5.6-luna", _codex(96.0, progress=0.5))
    assert luna.state == "available" and luna.release_status == "open"


def test_unknown_decision_reports_the_lane_ceiling():
    decision = evaluate_worker_admission("gpt-5.6-sol", {}, {}, now=NOW)
    assert decision.state == "unknown" and decision.allowed
    assert decision.hard_limit_pct == 95.0
    luna = evaluate_worker_admission("gpt-5.6-luna", {}, {}, now=NOW)
    assert luna.state == "unknown" and luna.hard_limit_pct == 99.0


# ── карта квот ───────────────────────────────────────────────────────────────


@pytest.fixture
def mapped(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "quota-map.db")
    monkeypatch.setattr(system, "is_owner_mode", lambda: True)

    async def no_refresh(*_args, **_kwargs):
        return {}

    monkeypatch.setattr(system, "_get_usage_data", no_refresh)
    monkeypatch.setattr(system.time, "time", lambda: NOW)

    async def run(observation):
        monkeypatch.setattr(system, "_quota_observation_from_cache", lambda: observation)
        return await system.quota_map()

    return run


def _observation(utilization):
    return {
        "providers": {"codex": {"label": "Codex", "windows": [_window(WEEK, utilization)]}},
        "observed_at_by_provider": {"codex": NOW - 10},
    }


def _lane(payload, bucket, lane):
    pool = next(item for item in payload["buckets"] if item["bucket"] == bucket)
    return next(item for item in pool["lanes"] if item["lane"] == lane)


@pytest.mark.asyncio
async def test_quota_map_rule_and_lanes_carry_the_lane_ceilings(mapped):
    payload = await mapped(_observation(96.0))

    assert payload["rule"]["hard_stop_pct"] == 99.0
    assert payload["rule"]["lane_hard_stop_pct"] == {"sol": 95.0}
    sol = _lane(payload, "codex", "sol")
    luna = _lane(payload, "codex", "luna")
    assert sol["blocked"] is True and sol["hard_stop_pct"] == 95.0
    assert sol["limit_pct"] == 95.0 and sol["release_status"] == "at_reset"
    assert luna["blocked"] is False and luna["hard_stop_pct"] == 99.0
    models = {item["model"]: item for item in
              next(b for b in payload["buckets"] if b["bucket"] == "codex")["models"]}
    assert models["gpt-5.6-sol"]["hard_limit_pct"] == 95.0
    assert models["gpt-5.6-luna"]["hard_limit_pct"] == 99.0


@pytest.mark.asyncio
async def test_quota_map_rule_reflects_overrides_and_the_common_cap(mapped, startup_env):
    startup_env(QUOTA_HARD_STOP_PCT="92", QUOTA_LANE_HARD_STOP_PCT="sol=95,luna=80")
    payload = await mapped(_observation(85.0))

    assert payload["rule"]["hard_stop_pct"] == 92.0
    assert payload["rule"]["lane_hard_stop_pct"] == {"luna": 80.0, "sol": 92.0}
    luna = _lane(payload, "codex", "luna")
    sol = _lane(payload, "codex", "sol")
    assert luna["blocked"] is True and luna["hard_stop_pct"] == 80.0
    # Потолок Sol срезан общим до 92: 85% у сброса под линией 92 — допуск.
    assert sol["blocked"] is False and sol["hard_stop_pct"] == 92.0 and sol["limit_pct"] == 92.0

    blocked = await mapped(_observation(92.0))
    assert _lane(blocked, "codex", "sol")["blocked"] is True
    assert _lane(blocked, "codex", "sol")["release_status"] == "at_reset"
