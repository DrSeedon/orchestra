"""Lane ceilings: configuration replacement and consistent admission/API metadata."""
from dataclasses import replace
import math
import os

import pytest

import app.quota_gate as gate

NOW = 2_000_000_000.0
NAME = "QUOTA_LANE_HARD_STOP_PCT"


@pytest.fixture
def live_policy(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    monkeypatch.setattr(gate, "_DOTENV_PATH", path)
    monkeypatch.setattr(gate, "_startup_quota_env", dict.fromkeys(gate._QUOTA_ENV_NAMES))
    monkeypatch.setattr(gate, "_dotenv_loaded", False)

    def write(contents):
        previous = path.stat().st_mtime_ns if path.exists() else 0
        path.write_text(contents)
        stamp = max(path.stat().st_mtime_ns, previous + 1)
        os.utime(path, ns=(stamp, stamp))
        return gate.quota_policy()

    return write


def decision(model, usage, policy, *, progress=1, reset=True):
    window = {"window_minutes": 10080, "utilization": usage}
    if reset:
        window["resets_at"] = NOW + 10080 * 60 * (1 - progress)
    providers = {bucket: {"windows": [window]} for bucket in ("codex", "anthropic", "codex_spark")}
    return gate.evaluate_worker_admission(model, providers, dict.fromkeys(providers, NOW), now=NOW, policy=policy)


@pytest.mark.parametrize("usage,allowed", [(96, (False, False, True)), (99.5, (False, False, False)), (94.9, (True, True, True))])
def test_acceptance(live_policy, usage, allowed):
    policy = live_policy("")
    for model, expected in zip(("gpt-5.6-sol", "gpt-6-astra", "gpt-5.6-luna"), allowed):
        result = decision(model, usage, policy)
        assert result.allowed is expected
        assert result.hard_limit_pct == (99 if result.lane == "luna" else 95)
        assert result.release_status == ("open" if expected else "at_reset")


def test_configuration_replaces_and_clears(live_policy):
    assert live_policy("").lane_hard_stop_pct == {"sol": 95}
    assert live_policy(f"{NAME}=sol=95,luna=90\n").lane_hard_stop_pct == {"sol": 95, "luna": 90}
    policy = live_policy(f"{NAME}=luna=90\n")
    assert policy.hard_stop_for("sol") == 99
    assert policy.hard_stop_for("luna") == 90
    policy = live_policy(f"{NAME}=\n")
    assert policy.lane_hard_stop_pct == {}
    assert policy.hard_stop_for("sol") == 99
    assert live_policy("").hard_stop_for("sol") == 95


@pytest.mark.parametrize("raw", ["sol", "sol=abc", "sol=101", "=95", "sol=95,", "sol=nan", "sol=inf", "sol=-inf", "sol=0", "sol=", "sol=95,,luna=90"])
def test_invalid_dotenv(live_policy, raw):
    with pytest.raises(ValueError, match=NAME):
        live_policy(f"{NAME}={raw}\n")


def test_invalid_bare_dotenv(live_policy):
    with pytest.raises(ValueError, match=NAME):
        live_policy(NAME + "\n")


def test_environment_precedence(live_policy, monkeypatch):
    monkeypatch.setitem(gate._startup_quota_env, NAME, "luna=90")
    assert live_policy(f"{NAME}=sol=80\n").lane_hard_stop_pct == {"luna": 90}
    monkeypatch.setitem(gate._startup_quota_env, NAME, "")
    assert gate.quota_policy().lane_hard_stop_pct == {}
    monkeypatch.setitem(gate._startup_quota_env, NAME, "sol=abc")
    with pytest.raises(ValueError, match=NAME):
        gate.quota_policy()


def test_contract_and_global_cap(live_policy):
    policy = replace(live_policy(""), hard_stop_pct=89, lane_hard_stop_pct={"sol": 95, "luna": 90})
    for lane in (None, "sol", "luna", "claude", "spark", "other"):
        assert policy.hard_stop_for(lane) == 89
        assert gate.line_limit(1, lane, policy) == 89
        assert math.isinf(gate.line_release_progress(89, lane, policy))
    assert decision("gpt-5.6-luna", 89, policy).state == "blocked"


def test_release_and_unknown(live_policy):
    policy = live_policy(f"{NAME}=sol=95,luna=90\n")
    result = decision("gpt-5.6-sol", 96, policy, progress=.9)
    assert result.release_status == "at_reset"
    assert result.release_in_seconds == pytest.approx(60480)
    assert result.limit_pct == 95
    assert decision("gpt-5.6-luna", 90, policy, reset=False).state == "blocked"
    unknown = gate.evaluate_worker_admission("gpt-5.6-sol", {}, {}, now=NOW, policy=policy)
    assert unknown.allowed and unknown.state == "unknown"
    assert unknown.hard_limit_pct == 95
    for model in ("gpt-5.3-codex-spark", "claude-sonnet-4-6"):
        result = decision(model, 96, policy)
        assert result.state == "available"
        assert result.hard_limit_pct == 99


@pytest.mark.asyncio
async def test_map(live_policy, monkeypatch, tmp_path):
    import app.db as db
    import app.routes.system as system

    live_policy(f"{NAME}=sol=95,luna=90\n")
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "map.db")
    monkeypatch.setattr(system, "is_owner_mode", lambda: True)
    monkeypatch.setattr(system.time, "time", lambda: NOW)
    monkeypatch.setattr(system, "_quota_observation_from_cache", lambda: {
        "providers": {"codex": {"windows": [{"window_minutes": 300, "resets_at": NOW, "utilization": 94}]}},
        "observed_at_by_provider": {"codex": NOW},
    })
    payload = await system.build_quota_map()
    assert payload["rule"]["lane_hard_stop_pct"] == {"sol": 95, "luna": 90}
    pool = next(pool for pool in payload["buckets"] if pool["bucket"] == "codex")
    for lane in pool["lanes"]:
        assert lane["hard_limit_pct"] == {"sol": 95, "luna": 90}[lane["lane"]]
        assert lane["blocked"] is (lane["lane"] == "luna")
    for model in pool["models"]:
        assert model["hard_limit_pct"] == {"sol": 95, "luna": 90}[model["lane"]]
        assert model["allowed"] is (model["lane"] == "sol")


@pytest.mark.parametrize("raw,expected", [("sol=1,luna=100", {"sol": 1, "luna": 100}), (" SOL = 95.5 , luna = 90 ", {"sol": 95.5, "luna": 90})])
def test_valid_percentages(live_policy, raw, expected):
    assert live_policy(f"{NAME}={raw}\n").lane_hard_stop_pct == expected


def test_release_below_ceiling_and_reset(live_policy):
    policy = live_policy("")
    for lane in ("sol", "claude"):
        progress = gate.line_release_progress(70, lane, policy)
        assert 0 < progress < 1
        assert gate.line_limit(progress, lane, policy) == pytest.approx(70)
    assert decision("gpt-5.6-sol", 96, policy).state == "blocked"
    assert decision("gpt-5.6-sol", 0, policy, progress=0).state == "available"
