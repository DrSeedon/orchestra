"""Отдельные жёсткие потолки полос: Sol упирается раньше Luna в общем пуле Codex."""

import os
from datetime import datetime, timezone

import pytest

import app.quota_gate as quota_gate
from app.quota_gate import (
    QuotaPolicy,
    _parse_lane_hard_stops,
    evaluate_worker_admission,
    line_limit,
    quota_policy,
)

NOW = 1_770_000_000.0
CODEX_WINDOW_MINUTES = 300


def _iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()


def _providers(codex: float, progress: float = 1.0) -> dict:
    return {
        "codex": {
            "label": "Codex",
            "windows": [{
                "id": "primary",
                "label": "primary",
                "window_minutes": CODEX_WINDOW_MINUTES,
                "utilization": codex,
                "resets_at": _iso(NOW + CODEX_WINDOW_MINUTES * 60 * (1.0 - progress)),
            }],
        }
    }


def _decide(model: str, codex: float, *, progress: float = 1.0, policy=None):
    stamps = {bucket: NOW for bucket in ("anthropic", "codex", "codex_spark")}
    return evaluate_worker_admission(
        model, _providers(codex, progress), stamps, now=NOW, policy=policy,
    )


# ── приёмка ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("model", ["gpt-5.6-sol", "gpt-6-astra"])
def test_sol_lane_is_blocked_at_96_pct_while_luna_passes(model):
    assert _decide(model, 96.0).state == "blocked"
    assert _decide("gpt-5.6-luna", 96.0).state == "available"


@pytest.mark.parametrize("model", ["gpt-5.6-sol", "gpt-6-astra", "gpt-5.6-luna"])
def test_both_lanes_are_blocked_at_995_pct(model):
    assert _decide(model, 99.5).state == "blocked"


@pytest.mark.parametrize("model", ["gpt-5.6-sol", "gpt-6-astra", "gpt-5.6-luna"])
def test_all_models_pass_below_the_sol_cap(model):
    assert _decide(model, 94.9).state == "available"


def test_default_policy_caps_sol_at_95_and_others_at_99():
    policy = quota_policy()
    assert dict(policy.lane_hard_stop_pct) == {"sol": 95.0}
    assert policy.hard_stop_for("sol") == 95.0
    assert policy.hard_stop_for("luna") == 99.0
    assert policy.hard_stop_for("claude") == 99.0
    assert policy.hard_stop_for("spark") == 99.0
    assert policy.hard_stop_for(None) == 99.0


def test_decision_fields_follow_the_lane_cap():
    decision = _decide("gpt-5.6-sol", 96.0)
    assert decision.hard_limit_pct == 95.0
    assert decision.limit_pct == 95.0
    assert decision.release_status == "at_reset"
    assert "95%" in decision.reason
    luna = _decide("gpt-5.6-luna", 96.0)
    assert luna.hard_limit_pct == 99.0


def test_line_limit_is_capped_by_the_lane_stop():
    policy = quota_policy()
    assert line_limit(1.0, "sol", policy) == 95.0
    assert line_limit(1.0, "claude", policy) == 99.0
    assert line_limit(1.0, None, policy) == 99.0


def test_global_hard_stop_caps_the_lane_stop_from_above():
    policy = QuotaPolicy(
        hard_stop_pct=90.0,
        tolerance_start_pp=10.0,
        tolerance_end_pp=1.0,
        curve_exponent=2.5,
        gated_lanes=frozenset({"sol"}),
        curved_lanes=frozenset({"sol"}),
        lane_hard_stop_pct={"sol": 95.0},
    )
    assert policy.hard_stop_for("sol") == 90.0
    assert _decide("gpt-5.6-sol", 92.0, policy=policy).state == "blocked"


def test_policy_accepts_plain_mapping_and_exposes_mapping():
    policy = QuotaPolicy(
        hard_stop_pct=99.0,
        tolerance_start_pp=10.0,
        tolerance_end_pp=1.0,
        curve_exponent=2.5,
        gated_lanes=frozenset({"sol"}),
        curved_lanes=frozenset({"sol"}),
        lane_hard_stop_pct={"SOL": 95},
    )
    assert dict(policy.lane_hard_stop_pct) == {"sol": 95.0}
    assert policy.lane_hard_stop_pct["sol"] == 95.0


# ── разбор конфигурации ───────────────────────────────────────────────────────


def test_parses_multiple_lanes():
    assert _parse_lane_hard_stops("sol=95,luna=90", "QUOTA_LANE_HARD_STOP_PCT") == {
        "sol": 95.0, "luna": 90.0,
    }
    assert _parse_lane_hard_stops(" Sol = 95.5 ", "QUOTA_LANE_HARD_STOP_PCT") == {
        "sol": 95.5,
    }
    assert _parse_lane_hard_stops("", "QUOTA_LANE_HARD_STOP_PCT") == {}


@pytest.mark.parametrize(
    "value", ["sol", "sol=abc", "sol=101", "=95", "sol=95,", "sol=0", "sol=nan", ",", "sol=95,luna"],
)
def test_invalid_items_raise_with_the_variable_name(value):
    with pytest.raises(ValueError, match="QUOTA_LANE_HARD_STOP_PCT"):
        _parse_lane_hard_stops(value, "QUOTA_LANE_HARD_STOP_PCT")


def _isolate_dotenv(tmp_path, monkeypatch, text: str):
    env_file = tmp_path / ".env"
    env_file.write_text(text)
    monkeypatch.setattr(quota_gate, "_DOTENV_PATH", env_file)
    for name in quota_gate._QUOTA_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(
        quota_gate, "_startup_quota_env",
        {name: None for name in quota_gate._QUOTA_ENV_NAMES},
    )
    monkeypatch.setattr(quota_gate, "_dotenv_loaded", False)
    monkeypatch.setattr(quota_gate, "_dotenv_mtime_ns", None)
    monkeypatch.setattr(quota_gate, "_dotenv_values", {})
    monkeypatch.setattr(quota_gate, "_dotenv_quota_keys", frozenset())
    return env_file


def _rewrite(env_file, text: str):
    """Переписать `.env` так, чтобы mtime гарантированно изменился.

    Шаг в целую секунду, а не в наносекунду: два быстрых подряд перезаписа иначе
    попадают в один и тот же mtime и горячая перечитка честно их не замечает.
    """
    before = env_file.stat().st_mtime_ns
    env_file.write_text(text)
    stat = env_file.stat()
    os.utime(
        env_file,
        ns=(stat.st_atime_ns, max(stat.st_mtime_ns, before) + 1_000_000_000),
    )


def test_dotenv_lane_caps_are_hot_reloaded_and_replaced(tmp_path, monkeypatch):
    env_file = _isolate_dotenv(
        tmp_path, monkeypatch, "QUOTA_LANE_HARD_STOP_PCT=sol=95,luna=90\n",
    )
    policy = quota_gate.quota_policy()
    assert dict(policy.lane_hard_stop_pct) == {"sol": 95.0, "luna": 90.0}
    assert policy.hard_stop_for("luna") == 90.0

    # Набор заменяется целиком: исчезнувшая Luna возвращается к общему потолку.
    _rewrite(env_file, "QUOTA_LANE_HARD_STOP_PCT=sol=80\n")
    policy = quota_gate.quota_policy()
    assert dict(policy.lane_hard_stop_pct) == {"sol": 80.0}
    assert policy.hard_stop_for("luna") == policy.hard_stop_pct == 99.0

    # Пустая строка — специальных потолков нет вовсе.
    _rewrite(env_file, "QUOTA_LANE_HARD_STOP_PCT=\n")
    policy = quota_gate.quota_policy()
    assert dict(policy.lane_hard_stop_pct) == {}
    assert policy.hard_stop_for("sol") == 99.0

    # Строка исчезла — вернулось умолчание.
    _rewrite(env_file, "\n")
    assert dict(quota_gate.quota_policy().lane_hard_stop_pct) == {"sol": 95.0}


def test_invalid_dotenv_lane_caps_raise(tmp_path, monkeypatch):
    _isolate_dotenv(tmp_path, monkeypatch, "QUOTA_LANE_HARD_STOP_PCT=sol\n")
    with pytest.raises(ValueError, match="QUOTA_LANE_HARD_STOP_PCT"):
        quota_gate.quota_policy()


def test_env_overrides_dotenv(tmp_path, monkeypatch):
    _isolate_dotenv(tmp_path, monkeypatch, "QUOTA_LANE_HARD_STOP_PCT=sol=80\n")
    monkeypatch.setattr(
        quota_gate, "_startup_quota_env",
        {**{name: None for name in quota_gate._QUOTA_ENV_NAMES},
         "QUOTA_LANE_HARD_STOP_PCT": "sol=70"},
    )
    assert quota_gate.quota_policy().hard_stop_for("sol") == 70.0
