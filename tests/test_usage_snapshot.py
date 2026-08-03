"""Снимок истории квот не должен врать.

Три состояния провайдера обязаны быть различимы в `provider_usage`:
не настроен → ключа нет; спросили и молчит → `status="unavailable"`;
ответил → окна с числами (в том числе честные 100% на исчерпанном лимите).
"""
import json

import pytest

from app.routes import system


@pytest.fixture
def saved(monkeypatch):
    """Перехватываем запись снимка — БД для этих проверок не нужна."""
    calls = []
    import app.db

    def _capture(*args, **kwargs):
        calls.append(kwargs.get("providers") or {})

    monkeypatch.setattr(app.db, "usage_save_snapshot", _capture)
    monkeypatch.setattr(system, "_save_usage_cache", lambda: None)
    # кеши — глобальные: без сброса значение из прошлого теста утечёт в следующий
    monkeypatch.setattr(system, "_usage_cache", {"data": None, "ts": 0.0, "token": None})
    monkeypatch.setattr(system, "_codex_usage_cache", {"data": None, "ts": 0.0})
    monkeypatch.setattr(system, "_grok_usage_cache", {"data": None, "ts": 0.0})
    monkeypatch.setattr(system, "_read_oauth_credentials", lambda: ("token", None, None))
    monkeypatch.setattr(system, "_read_grok_token", lambda: "")
    return calls


def _anthropic_ok(monkeypatch):
    async def _fetch(_token):
        return {"five_hour": {"utilization": 12, "resets_at": "2026-08-03T08:00:00Z"}}

    monkeypatch.setattr(system, "_fetch_anthropic_usage", _fetch)


def _codex(monkeypatch, result=None, error=None):
    async def _fetch():
        if error:
            raise error
        return result

    monkeypatch.setattr(system, "_fetch_codex_usage", _fetch)
    monkeypatch.setattr("shutil.which", lambda _b: "/usr/local/bin/codex")


@pytest.mark.asyncio
async def test_silent_provider_is_marked_not_dropped(monkeypatch, saved):
    """Codex спросили, он упал → метка, а не молчаливое отсутствие ключа."""
    _anthropic_ok(monkeypatch)
    _codex(monkeypatch, error=RuntimeError("app-server failed"))

    await system._collect_usage_snapshot()

    codex = saved[0]["codex"]
    assert codex["status"] == "unavailable"
    assert codex["windows"] == []
    assert "RuntimeError" in codex["error"]


@pytest.mark.asyncio
async def test_silent_provider_never_restamps_stale_value(monkeypatch, saved):
    """Главный баг: молчащий провайдер получал прошлое значение с новым ts."""
    _anthropic_ok(monkeypatch)
    _codex(monkeypatch, result={
        "plan_type": "pro",
        "primary": {"utilization": 100, "window_minutes": 10080},
    })
    await system._collect_usage_snapshot()
    assert saved[0]["codex"]["windows"][0]["utilization"] == 100

    _codex(monkeypatch, error=RuntimeError("limit"))
    await system._collect_usage_snapshot()

    assert saved[1]["codex"]["windows"] == []
    assert saved[1]["codex"]["status"] == "unavailable"


@pytest.mark.asyncio
async def test_exhausted_limit_is_data_not_absence(monkeypatch, saved):
    """100% — это ответ провайдера, а не «нет данных». Не терять."""
    _anthropic_ok(monkeypatch)
    _codex(monkeypatch, result={
        "plan_type": "prolite",
        "primary": {"utilization": 100, "window_minutes": 10080},
    })

    await system._collect_usage_snapshot()

    codex = saved[0]["codex"]
    assert "status" not in codex
    assert codex["windows"][0]["utilization"] == 100


@pytest.mark.asyncio
async def test_unconfigured_provider_has_no_key_at_all(monkeypatch, saved):
    """Grok без токена не спрашивали → ключа нет. Не путать с «молчит»."""
    _anthropic_ok(monkeypatch)
    _codex(monkeypatch, result={"primary": {"utilization": 5, "window_minutes": 10080}})

    await system._collect_usage_snapshot()

    assert "grok" not in saved[0]


@pytest.mark.asyncio
async def test_codex_not_installed_is_not_marked_unavailable(monkeypatch, saved):
    """Нет бинарника — провайдера тут просто нет; вечная метка была бы шумом."""
    _anthropic_ok(monkeypatch)

    async def _fetch():
        raise FileNotFoundError("codex")

    monkeypatch.setattr(system, "_fetch_codex_usage", _fetch)
    monkeypatch.setattr("shutil.which", lambda _b: None)

    await system._collect_usage_snapshot()

    assert "codex" not in saved[0]


@pytest.mark.asyncio
async def test_snapshot_still_written_when_only_codex_answers(monkeypatch, saved):
    """Молчание Anthropic не должно отменять запись снимка целиком."""
    async def _fail(_token):
        raise RuntimeError("anthropic down")

    monkeypatch.setattr(system, "_fetch_anthropic_usage", _fail)
    _codex(monkeypatch, result={"primary": {"utilization": 7, "window_minutes": 10080}})

    await system._collect_usage_snapshot()

    assert saved, "снимок не записан — история потеряна"
    assert saved[0]["anthropic"]["status"] == "unavailable"
    assert saved[0]["codex"]["windows"][0]["utilization"] == 7


def test_history_row_roundtrips_unavailable_marker():
    """Метка должна доезжать до графика через usage_get_history."""
    from app.db import _usage_providers_from_row

    marker = {"codex": {"label": "Codex", "windows": [], "status": "unavailable"}}
    row = {"five_hour_pct": 0, "provider_usage": json.dumps(marker)}

    assert _usage_providers_from_row(row)["codex"]["status"] == "unavailable"
