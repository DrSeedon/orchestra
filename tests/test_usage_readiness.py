import asyncio
from datetime import datetime, timezone

import pytest

from app.routes import system


NOW = 2_000_000_000.0


def _anthropic(utilization=20):
    return {
        "five_hour": {"utilization": 1},
        "seven_day": {"utilization": utilization},
    }


def _codex(utilization=20, spark=10):
    return {
        "primary": {"utilization": 1, "window_minutes": 300},
        "secondary": {"utilization": utilization, "window_minutes": 10080},
        "spark": {
            "primary": {"utilization": 1, "window_minutes": 300},
            "secondary": {"utilization": spark, "window_minutes": 10080},
        },
    }


@pytest.fixture
def isolated_usage(monkeypatch):
    monkeypatch.setattr(system, "_usage_cache", {"data": _anthropic(), "ts": NOW - 400, "token": None})
    monkeypatch.setattr(system, "_codex_usage_cache", {"data": _codex(), "ts": NOW - 400})
    monkeypatch.setattr(system, "_grok_usage_cache", {"data": None, "ts": 0.0})
    monkeypatch.setattr(system, "_quota_refresh_locks", {
        "anthropic": asyncio.Lock(), "codex": asyncio.Lock(),
    })
    monkeypatch.setattr(system.time, "time", lambda: NOW)
    monkeypatch.setattr(system, "_save_usage_cache", lambda: None)
    monkeypatch.setattr(system, "_get_agents_cost", lambda: {})
    monkeypatch.setattr(system, "_get_voice_cost_usd", lambda: 0.0)
    monkeypatch.setattr(system, "_read_oauth_credentials", lambda: ("token", None, None))
    monkeypatch.setattr(system, "_read_grok_token", lambda: None)


@pytest.mark.asyncio
async def test_anthropic_refresh_is_target_isolated_and_singleflight(isolated_usage, monkeypatch):
    calls = {"anthropic": 0, "codex": 0}

    async def fetch_anthropic(_token):
        calls["anthropic"] += 1
        await asyncio.sleep(0)
        return _anthropic(94)

    async def fetch_codex():
        calls["codex"] += 1
        return _codex()

    monkeypatch.setattr(system, "_fetch_anthropic_usage", fetch_anthropic)
    monkeypatch.setattr(system, "_fetch_codex_usage", fetch_codex)

    results = await asyncio.gather(*[
        system.current_quota_observation(required_provider="anthropic", now=NOW)
        for _ in range(8)
    ])

    assert calls == {"anthropic": 1, "codex": 0}
    assert all(item["observed_at_by_provider"]["anthropic"] == NOW for item in results)


@pytest.mark.asyncio
async def test_singleflight_waiters_recheck_clock_after_newer_refresh(
    isolated_usage, monkeypatch,
):
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    def clock():
        return NOW if calls == 0 else NOW + 2

    async def refresh(*, force_refresh, required_provider):
        nonlocal calls
        assert force_refresh is True
        assert required_provider == "anthropic"
        started.set()
        await release.wait()
        calls += 1
        system._usage_cache["data"] = _anthropic(94)
        system._usage_cache["ts"] = NOW + 1

    monkeypatch.setattr(system.time, "time", clock)
    monkeypatch.setattr(system, "_get_usage_data", refresh)
    tasks = [
        asyncio.create_task(system.current_quota_observation(
            required_provider="anthropic",
        ))
        for _ in range(8)
    ]
    await started.wait()
    for _ in range(20):
        waiters = system._quota_refresh_locks["anthropic"]._waiters or ()
        if len(waiters) == 7:
            break
        await asyncio.sleep(0)
    assert len(system._quota_refresh_locks["anthropic"]._waiters or ()) == 7
    release.set()

    results = await asyncio.gather(*tasks)

    assert calls == 1
    assert all(
        item["observed_at_by_provider"]["anthropic"] == NOW + 1
        for item in results
    )


@pytest.mark.asyncio
async def test_spark_refresh_uses_one_codex_fetch_but_keeps_buckets_separate(
    isolated_usage, monkeypatch,
):
    calls = {"anthropic": 0, "codex": 0}

    async def fetch_anthropic(_token):
        calls["anthropic"] += 1
        return _anthropic()

    async def fetch_codex():
        calls["codex"] += 1
        await asyncio.sleep(0)
        return _codex(95, 1)

    monkeypatch.setattr(system, "_fetch_anthropic_usage", fetch_anthropic)
    monkeypatch.setattr(system, "_fetch_codex_usage", fetch_codex)

    results = await asyncio.gather(*[
        system.current_quota_observation(required_provider="codex_spark", now=NOW)
        for _ in range(8)
    ])

    assert calls == {"anthropic": 0, "codex": 1}
    providers = results[0]["providers"]
    assert providers["codex"]["windows"][-1]["utilization"] == 95
    assert providers["codex_spark"]["windows"][-1]["utilization"] == 1
    assert results[0]["observed_at_by_provider"]["codex"] == NOW
    assert results[0]["observed_at_by_provider"]["codex_spark"] == NOW


@pytest.mark.asyncio
async def test_refresh_failure_preserves_stale_observation_timestamp(
    isolated_usage, monkeypatch,
):
    async def fail(_token):
        raise RuntimeError("offline")

    monkeypatch.setattr(system, "_fetch_anthropic_usage", fail)
    result = await system.current_quota_observation(
        required_provider="anthropic", now=NOW, timeout=0.1,
    )
    assert result["observed_at_by_provider"]["anthropic"] == NOW - 400


@pytest.mark.asyncio
async def test_fresh_cache_does_not_fetch_at_age_299_9(isolated_usage, monkeypatch):
    system._codex_usage_cache["ts"] = NOW - 299.9

    async def fail_if_called():
        raise AssertionError("fresh cache must not fetch")

    monkeypatch.setattr(system, "_fetch_codex_usage", fail_if_called)
    result = await system.current_quota_observation(required_provider="codex", now=NOW)
    assert result["observed_at_by_provider"]["codex"] == NOW - 299.9


@pytest.mark.asyncio
async def test_age_300_refreshes_exactly_at_boundary(isolated_usage, monkeypatch):
    system._codex_usage_cache["ts"] = NOW - 300
    calls = 0

    async def fetch_codex():
        nonlocal calls
        calls += 1
        return _codex(3, 4)

    monkeypatch.setattr(system, "_fetch_codex_usage", fetch_codex)
    result = await system.current_quota_observation(required_provider="codex", now=NOW)
    assert calls == 1
    assert result["observed_at_by_provider"]["codex"] == NOW


@pytest.mark.asyncio
async def test_readiness_endpoint_returns_the_execution_time_decision(isolated_usage):
    """95% без разбираемого `resets_at` — линию считать нечем, действует жёсткий стоп."""
    system._usage_cache.update({"data": _anthropic(95), "ts": NOW})
    result = await system.usage_readiness("claude-opus-5[1m]")
    assert result["provider"] == "anthropic"
    assert result["lane"] == "claude" and result["gated"] is True
    assert result["state"] == "available" and result["allowed"] is True
    assert result["progress"] is None and result["limit_pct"] is None
    assert result["hard_limit_pct"] == 99.0


@pytest.mark.asyncio
async def test_readiness_endpoint_blocks_above_the_line(isolated_usage):
    data = _anthropic(95)
    # Ровно середина недельного окна: линия 55.5%, факт 95% — выше неё.
    data["seven_day"]["resets_at"] = datetime.fromtimestamp(
        NOW + 10080 * 60 / 2, timezone.utc,
    ).isoformat()
    system._usage_cache.update({"data": data, "ts": NOW})
    result = await system.usage_readiness("claude-opus-5[1m]")
    assert result["state"] == "blocked" and result["allowed"] is False
    assert result["limit_pct"] == pytest.approx(55.5)


@pytest.mark.asyncio
async def test_unknown_model_endpoint_fails_open_without_refresh(isolated_usage, monkeypatch):
    async def fail(**_kwargs):
        raise AssertionError("unknown model must not refresh an arbitrary provider")

    monkeypatch.setattr(system, "current_quota_observation", fail)
    result = await system.usage_readiness("future-unknown-model")
    # Неизвестная модель — `unknown`, и это ПРОПУСКАЕТ (#343): отказ здесь давал
    # мёртвую сессию, которую первый же `/send` отбивал 429.
    assert result["state"] == "unknown" and result["allowed"] is True
