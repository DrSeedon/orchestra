"""Frozen RED for #249 T2: quota wire shape, cache and independent routing buckets."""

import asyncio
import importlib
import math
from pathlib import Path

import pytest

from app import quota_gate
from app.routes import system

_ANTIGRAVITY_BACKEND = Path(__file__).resolve().parents[1] / "app" / "backend_antigravity.py"
pytestmark = pytest.mark.skipif(
    not _ANTIGRAVITY_BACKEND.is_file(),
    reason="#249 phase 2 not implemented (no app/backend_antigravity.py); follow-up #279",
)


NOW = 2_000_000_000.0
RESET_GEMINI = "2033-05-20T04:33:20Z"
RESET_3P = "2033-05-23T04:33:20Z"


def _raw_quota(*, gemini=0.62, third_party=0.17):
    return {
        "conversation_id": "",
        "status": "SUCCESS",
        "response": "",
        "usage": {
            "input_tokens": 0,
            "output_tokens": 0,
            "thinking_tokens": 0,
            "cache_read_tokens": 0,
            "total_tokens": 0,
        },
        "command": {
            "name": "usage",
            "data": {
                "groups": [
                    {
                        "name": "Gemini Models",
                        "buckets": [{
                            "id": "gemini-weekly",
                            "window": "weekly",
                            "remaining_fraction": gemini,
                            "reset_time": RESET_GEMINI,
                        }],
                    },
                    {
                        "name": "Claude and GPT models",
                        "buckets": [{
                            "id": "3p-weekly",
                            "window": "weekly",
                            "remaining_fraction": third_party,
                            "reset_time": RESET_3P,
                        }],
                    },
                ],
            },
        },
    }


def _normalize():
    try:
        antigravity = importlib.import_module("app.backend_antigravity")
    except ModuleNotFoundError:
        antigravity = None

    normalize = getattr(antigravity, "normalize_antigravity_quota", None)
    assert callable(normalize), "Antigravity quota normalization is missing"
    return normalize


def test_t2_quota_wire_shape_preserves_remaining_fraction_and_exact_keys():
    normalize = _normalize()

    assert normalize(_raw_quota()) == {
        "gemini-weekly": {
            "remaining_fraction": 0.62,
            "reset_time": RESET_GEMINI,
        },
        "3p-weekly": {
            "remaining_fraction": 0.17,
            "reset_time": RESET_3P,
        },
    }


@pytest.mark.parametrize(
    "mutate,invalid_key",
    [
        (lambda raw: raw["command"]["data"].update(groups=[]), "gemini-weekly"),
        (
            lambda raw: raw["command"]["data"]["groups"][0]["buckets"][0].update(
                remaining_fraction=float("nan")
            ),
            "gemini-weekly",
        ),
        (
            lambda raw: raw["command"]["data"]["groups"][0]["buckets"][0].update(
                remaining_fraction=1.01
            ),
            "gemini-weekly",
        ),
        (
            lambda raw: raw["command"]["data"]["groups"][1]["buckets"][0].update(
                remaining_fraction=-0.01
            ),
            "3p-weekly",
        ),
        (
            lambda raw: raw["command"]["data"]["groups"][1]["buckets"][0].update(
                remaining_fraction=True
            ),
            "3p-weekly",
        ),
        (lambda raw: raw.update(status="ERROR", error="credentials expired"), "3p-weekly"),
    ],
)
def test_t2_missing_or_malformed_quota_is_null_never_guessed_zero(mutate, invalid_key):
    normalize = _normalize()
    raw = _raw_quota()
    mutate(raw)

    result = normalize(raw)

    assert list(result) == ["gemini-weekly", "3p-weekly"]
    assert result[invalid_key] is None
    for value in result.values():
        if value is None:
            continue
        fraction = value["remaining_fraction"]
        assert math.isfinite(fraction)
        assert 0 <= fraction <= 1


def test_t2_provider_snapshot_keeps_two_independent_weekly_buckets():
    normalized = _normalize()(_raw_quota())

    providers = system._provider_usage_snapshot(None, None, None, normalized)

    assert providers["antigravity_gemini"] == {
        "label": "Antigravity Gemini",
        "windows": [{
            "id": "gemini-weekly",
            "label": "7d",
            "utilization": pytest.approx(38),
            "window_minutes": 10080,
            "resets_at": RESET_GEMINI,
        }],
    }
    assert providers["antigravity_3p"] == {
        "label": "Antigravity Claude/GPT",
        "windows": [{
            "id": "3p-weekly",
            "label": "7d",
            "utilization": pytest.approx(83),
            "window_minutes": 10080,
            "resets_at": RESET_3P,
        }],
    }


def _provider(label, utilization):
    return {
        "label": label,
        "windows": [{
            "id": "weekly",
            "window_minutes": 10080,
            "utilization": utilization,
            "resets_at": "2033-05-25T04:33:20Z",
        }],
    }


def test_t2_gemini_and_third_party_models_use_independent_gate_buckets():
    assert quota_gate.quota_bucket_for_model(
        "antigravity/gemini-3.6-flash-low"
    ) == "antigravity_gemini"
    assert quota_gate.quota_bucket_for_model(
        "antigravity/claude-opus-4-6-thinking"
    ) == "antigravity_3p"
    assert quota_gate.quota_bucket_for_model(
        "antigravity/gpt-oss-120b-medium"
    ) == "antigravity_3p"

    providers = {
        "antigravity_gemini": _provider("Antigravity Gemini", 95),
        "antigravity_3p": _provider("Antigravity Claude/GPT", 17),
    }
    observed = {
        "antigravity_gemini": NOW - 1,
        "antigravity_3p": NOW - 1,
    }
    gemini = quota_gate.evaluate_worker_admission(
        "antigravity/gemini-3.6-flash-low", providers, observed, now=NOW
    )
    third_party = quota_gate.evaluate_worker_admission(
        "antigravity/claude-sonnet-4-6", providers, observed, now=NOW
    )

    assert gemini.state == "blocked"
    assert gemini.provider == "antigravity_gemini"
    assert {item["provider"] for item in gemini.alternatives} == {"antigravity_3p"}
    assert third_party.state == "available"
    assert third_party.provider == "antigravity_3p"
    assert quota_gate.evaluate_worker_admission(
        "antigravity/future-model", providers, observed, now=NOW
    ).state == "unknown"


@pytest.mark.asyncio
async def test_t2_antigravity_refresh_is_singleflight_for_both_group_consumers(
    monkeypatch,
):
    normalize = _normalize()
    calls = 0

    async def fetch():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return normalize(_raw_quota())

    monkeypatch.setattr(system, "_fetch_antigravity_usage", fetch)
    monkeypatch.setattr(system, "_antigravity_usage_cache", {"data": None, "ts": 0.0})
    monkeypatch.setattr(system, "_quota_refresh_locks", {
        **system._quota_refresh_locks,
        "antigravity": asyncio.Lock(),
    })
    monkeypatch.setattr(system.time, "time", lambda: NOW)

    results = await asyncio.gather(*[
        system.current_quota_observation(
            required_provider=(
                "antigravity_gemini" if index % 2 == 0 else "antigravity_3p"
            ),
            now=NOW,
        )
        for index in range(8)
    ])

    assert calls == 1
    assert all(
        result["observed_at_by_provider"]["antigravity_gemini"] == NOW
        and result["observed_at_by_provider"]["antigravity_3p"] == NOW
        for result in results
    )


@pytest.mark.asyncio
async def test_t2_failed_refresh_preserves_previous_data_and_observation_time(monkeypatch):
    normalize = _normalize()
    old_data = normalize(_raw_quota(gemini=0.71, third_party=0.44))
    old_ts = NOW - 900

    async def fail_fetch():
        raise RuntimeError("mock quota endpoint unavailable")

    monkeypatch.setattr(system, "_fetch_antigravity_usage", fail_fetch)
    monkeypatch.setattr(system, "_antigravity_usage_cache", {
        "data": old_data,
        "ts": old_ts,
    })
    monkeypatch.setattr(system, "_quota_refresh_locks", {
        **system._quota_refresh_locks,
        "antigravity": asyncio.Lock(),
    })
    monkeypatch.setattr(system.time, "time", lambda: NOW)

    result = await system.current_quota_observation(
        required_provider="antigravity_gemini",
        max_age=1,
        now=NOW,
    )

    assert result["observed_at_by_provider"]["antigravity_gemini"] == old_ts
    assert result["observed_at_by_provider"]["antigravity_3p"] == old_ts
    assert result["providers"]["antigravity_gemini"]["windows"][0][
        "utilization"
    ] == pytest.approx(29)
    assert result["providers"]["antigravity_3p"]["windows"][0][
        "utilization"
    ] == pytest.approx(56)


@pytest.mark.asyncio
async def test_t2_usage_data_always_exposes_exact_nullable_frontend_contract(monkeypatch):
    monkeypatch.setattr(system, "_antigravity_usage_cache", {
        "data": {"gemini-weekly": None, "3p-weekly": None},
        "ts": NOW,
    })
    monkeypatch.setattr(system.time, "time", lambda: NOW)

    data = await system._get_usage_data(required_provider="antigravity_gemini")

    assert data["antigravity"] == {
        "gemini-weekly": None,
        "3p-weekly": None,
    }
