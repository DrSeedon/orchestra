"""GET /api/usage/readiness — источник состояния для гейта по квоте (#154).

Обе стороны решения проверяются на одном и том же снимке: закрыто для исчерпанного
бакета `codex` и одновременно ОТКРЫТО для `codex_spark`, который живёт в своём окне.
Гейт «по рантайму codex» прошёл бы первый тест и убил бы рабочий Spark.
"""

import pytest

from app.routes import system

FUTURE_RESET = "2026-08-08T05:53:45Z"

# Форма — из живого снимка usage_snapshots (2026-08-07): codex выбран, Spark на 1%.
LIVE_SNAPSHOT = {
    "codex": {
        "label": "Codex",
        "plan_type": "prolite",
        "windows": [{
            "id": "primary", "label": "7d", "utilization": 100,
            "window_minutes": 10080, "resets_at": FUTURE_RESET,
        }],
    },
    "codex_spark": {
        "label": "Codex Spark",
        "plan_type": "prolite",
        "windows": [{
            "id": "primary", "label": "7d", "utilization": 1,
            "window_minutes": 10080, "resets_at": "2026-08-09T07:04:58Z",
        }],
    },
    "anthropic": {
        "label": "Claude",
        "windows": [
            {"id": "five_hour", "label": "5h", "utilization": 65,
             "window_minutes": 300, "resets_at": "2026-08-07T09:00:00Z"},
            {"id": "seven_day", "label": "7d", "utilization": 85,
             "window_minutes": 10080, "resets_at": "2026-08-11T07:00:00Z"},
        ],
    },
}


@pytest.fixture
def exhausted_codex(monkeypatch):
    monkeypatch.setattr(system, "is_owner_mode", lambda: True)

    async def usage(*, provider="", force_refresh=False):
        assert force_refresh is False, "гейт обязан читать кеш, а не будить app-server"
        return LIVE_SNAPSHOT

    monkeypatch.setattr(system, "current_provider_usage", usage)


@pytest.mark.asyncio
async def test_exhausted_codex_model_is_closed_with_its_reset(exhausted_codex):
    result = await system.usage_readiness(model="gpt-5.6-sol")

    assert result["provider"] == "codex"
    assert result["state"] == "reset"
    assert result["reset_at"].startswith("2026-08-08T05:53:45")


@pytest.mark.asyncio
async def test_spark_stays_open_while_codex_is_exhausted(exhausted_codex):
    """Разные лимит-id: `codex` и `codex_bengalfox`. Один выбран, второй свободен."""
    result = await system.usage_readiness(model="gpt-5.3-codex-spark")

    assert result["provider"] == "codex_spark"
    assert result["state"] == "available"
    assert result["reset_at"] is None


@pytest.mark.asyncio
async def test_claude_model_is_unaffected_by_codex_exhaustion(exhausted_codex):
    result = await system.usage_readiness(model="claude-opus-5[1m]")

    assert result["provider"] == "anthropic"
    assert result["state"] == "available"


@pytest.mark.asyncio
async def test_aliases_resolve_to_their_own_buckets(exhausted_codex):
    """Алиасы `codex` и `spark` ведут в РАЗНЫЕ окна, и вердикт у них разный."""
    assert await system.usage_readiness(model="codex") == {
        "provider": "codex", "state": "reset",
        "reason": "provider capacity is exhausted",
        "reset_at": "2026-08-08T05:53:45+00:00",
    }
    spark = await system.usage_readiness(model="spark")
    assert (spark["provider"], spark["state"]) == ("codex_spark", "available")


@pytest.mark.asyncio
async def test_unknown_model_answers_unavailable_instead_of_raising(exhausted_codex):
    result = await system.usage_readiness(model="модели-такой-нет")

    assert result["state"] == "unavailable"
    assert "модели-такой-нет" in result["reason"]
    assert result["reset_at"] is None


@pytest.mark.asyncio
async def test_usage_failure_answers_unavailable_and_names_the_exception(monkeypatch):
    monkeypatch.setattr(system, "is_owner_mode", lambda: True)

    async def broken(*, provider="", force_refresh=False):
        raise TimeoutError("codex app-server closed")

    monkeypatch.setattr(system, "current_provider_usage", broken)

    result = await system.usage_readiness(model="gpt-5.6-sol")

    assert result["state"] == "unavailable"
    # Голый текст TimeoutError пуст — без имени класса отказ был бы безымянным.
    assert "TimeoutError" in result["reason"]


@pytest.mark.asyncio
async def test_client_installation_gets_no_quota_details(monkeypatch):
    monkeypatch.setattr(system, "is_owner_mode", lambda: False)

    async def unexpected(*, provider="", force_refresh=False):
        raise AssertionError("чужую инсталляцию нельзя пускать к нашим квотам")

    monkeypatch.setattr(system, "current_provider_usage", unexpected)

    result = await system.usage_readiness(model="gpt-5.6-sol")

    assert result["state"] == "unavailable"
    assert result["reset_at"] is None


@pytest.mark.asyncio
async def test_response_never_carries_an_error_key(exhausted_codex):
    """`_api` в MCP бросает на любом непустом `error` — «не знаю» стало бы исключением."""
    for model in ("gpt-5.6-sol", "модели-такой-нет"):
        assert "error" not in await system.usage_readiness(model=model)
