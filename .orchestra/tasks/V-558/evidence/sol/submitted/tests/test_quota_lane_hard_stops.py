from datetime import datetime, timezone
import os

import pytest

import app.db as db
import app.quota_gate as quota_gate
import app.routes.system as system


NOW = 2_000_000_000.0


def _observation(utilization: float) -> dict:
    reset = datetime.fromtimestamp(NOW, timezone.utc).isoformat()
    return {
        "providers": {
            "codex": {
                "label": "Codex",
                "windows": [{
                    "id": "primary",
                    "window_minutes": 300,
                    "utilization": utilization,
                    "resets_at": reset,
                }],
            },
        },
        "observed_at_by_provider": {"codex": NOW},
    }


def _decision(model: str, utilization: float):
    observation = _observation(utilization)
    return quota_gate.evaluate_worker_admission(
        model,
        observation["providers"],
        observation["observed_at_by_provider"],
        now=NOW,
    )


def test_default_lane_stops_split_codex_models_at_completed_window():
    assert quota_gate.quota_policy().lane_hard_stop_pct == {"sol": 95.0}

    expected = {
        94.9: (True, True, True),
        96.0: (False, False, True),
        99.5: (False, False, False),
    }
    for utilization, allowed in expected.items():
        decisions = [
            _decision(model, utilization)
            for model in ("gpt-5.6-sol", "gpt-6-astra", "gpt-5.6-luna")
        ]
        assert tuple(item.allowed for item in decisions) == allowed
        assert tuple(item.hard_limit_pct for item in decisions) == (95.0, 95.0, 99.0)


def test_common_stop_caps_lane_stop_and_none_uses_common_stop():
    policy = quota_gate.QuotaPolicy(
        hard_stop_pct=80.0,
        tolerance_start_pp=10.0,
        tolerance_end_pp=1.0,
        curve_exponent=2.5,
        gated_lanes=frozenset({"sol"}),
        curved_lanes=frozenset({"sol"}),
        lane_hard_stop_pct={"sol": 95.0, "luna": 70.0},
    )

    assert policy.hard_stop_for(None) == 80.0
    assert policy.hard_stop_for("sol") == 80.0
    assert policy.hard_stop_for("luna") == 70.0
    assert policy.hard_stop_for("spark") == 80.0
    assert quota_gate.line_limit(1.0, "sol", policy) == 80.0


@pytest.mark.parametrize("raw", ["sol", "sol=abc", "sol=101", "=95", "sol=95,"])
def test_invalid_lane_stop_items_name_the_environment_variable(raw):
    with pytest.raises(ValueError, match="QUOTA_LANE_HARD_STOP_PCT"):
        quota_gate._parse_lane_hard_stops(raw, "QUOTA_LANE_HARD_STOP_PCT")


def test_live_dotenv_lane_set_replaces_previous_set(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    monkeypatch.setattr(quota_gate, "_DOTENV_PATH", env_file)
    monkeypatch.setattr(
        quota_gate,
        "_startup_quota_env",
        {name: None for name in quota_gate._QUOTA_ENV_NAMES},
    )
    monkeypatch.setattr(quota_gate, "_dotenv_loaded", False)
    monkeypatch.setattr(quota_gate, "_dotenv_mtime_ns", None)
    monkeypatch.setattr(quota_gate, "_dotenv_values", {})
    monkeypatch.setattr(quota_gate, "_dotenv_quota_keys", frozenset())

    forced_mtime = 0

    def rewrite(value: str) -> quota_gate.QuotaPolicy:
        nonlocal forced_mtime
        env_file.write_text(f"QUOTA_LANE_HARD_STOP_PCT={value}\n")
        stat = env_file.stat()
        forced_mtime = max(stat.st_mtime_ns, forced_mtime + 1)
        os.utime(env_file, ns=(stat.st_atime_ns, forced_mtime))
        return quota_gate.quota_policy()

    assert rewrite("sol=90,luna=91").lane_hard_stop_pct == {"sol": 90.0, "luna": 91.0}
    replaced = rewrite("luna=92")
    assert replaced.lane_hard_stop_pct == {"luna": 92.0}
    assert replaced.hard_stop_for("sol") == 99.0
    empty = rewrite("")
    assert empty.lane_hard_stop_pct == {}
    assert empty.hard_stop_for("sol") == 99.0


@pytest.mark.asyncio
async def test_quota_map_uses_and_reports_lane_hard_stop(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "quota-map.db")
    db.init_db()
    monkeypatch.setattr(system, "is_owner_mode", lambda: True)
    monkeypatch.setattr(system.time, "time", lambda: NOW)
    monkeypatch.setattr(system, "_quota_observation_from_cache", lambda: _observation(96.0))

    payload = await system.build_quota_map()
    codex = next(item for item in payload["buckets"] if item["bucket"] == "codex")
    sol = next(item for item in codex["lanes"] if item["lane"] == "sol")
    luna = next(item for item in codex["lanes"] if item["lane"] == "luna")

    assert payload["rule"]["lane_hard_stop_pct"] == {"sol": 95.0}
    assert (sol["hard_limit_pct"], sol["limit_pct"], sol["blocked"]) == (95.0, 95.0, True)
    assert sol["release_status"] == "at_reset"
    assert (luna["hard_limit_pct"], luna["limit_pct"], luna["blocked"]) == (99.0, None, False)
    assert luna["release_status"] == "open"
