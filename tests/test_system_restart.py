"""Restart endpoint behavior."""

import asyncio
import os
import signal
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture(autouse=True)
def _restore_drain_gate():
    """Гейт дренажа — состояние ЖИВОГО синглтона `manager`, а не фикстуры.

    Прод рассчитывает, что после `begin_drain()` процесс умрёт, поэтому сам гейт
    обратно не открывается. В тестах `os.kill` подменён — без этой уборки
    `manager.draining` утекает в следующие файлы, и там всё падает на
    `DrainingRefused` (поймано pre-mortem: 2 упавших теста при прогоне
    test_system_restart.py перед test_hot_apply.py).
    """
    yield
    from app.deps import manager
    manager.end_drain()


@pytest.mark.asyncio
async def test_restart_endpoint_responds_before_scheduling_service_restart(monkeypatch):
    from app.routes import system

    restart = AsyncMock()
    monkeypatch.setattr(system, "_restart_service_after_response", restart)

    result = await system.restart_server()
    await asyncio.sleep(0)

    assert result == {"ok": True, "scheduled": True}
    restart.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_deferred_restart_signals_current_process_after_response(monkeypatch):
    """Контракт СМЕНИЛСЯ в #220 T3: между ответом и сигналом теперь дренаж.

    Было: `sleep.assert_awaited_once_with(0.5)` — «единственное ожидание перед
    сигналом это сброс HTTP-ответа». Это утверждение стало неверным по существу:
    рестарт ждёт живые ходы до `_DRAIN_DEADLINE_S`. Формально ассерт остался бы
    зелёным на пустом реестре сессий (цикл выходит сразу), то есть проверял бы
    ровно то, чего больше нет, — поэтому он заменён, а не подогнан.

    Что проверяется теперь: сигнал по-прежнему уходит, и уходит ПОСЛЕ дренажа,
    а не вместо него. Ожидание живого хода закрыто отдельно в
    `tests/test_hot_apply.py::test_t3_restart_drains_before_signalling`.
    """
    from app.routes import system

    kill = MagicMock()
    monkeypatch.setattr(system.os, "kill", kill)
    monkeypatch.setattr(system, "_drain_sessions", lambda: [], raising=False)

    outcome = await system._restart_service_after_response()

    kill.assert_called_once_with(os.getpid(), signal.SIGINT)
    assert outcome["cut_turns"] == 0, "дренаж на пустом реестре никого не режет"
    assert outcome["waited_s"] >= 0
