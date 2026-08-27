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
    from app import main as app_main
    from app.deps import manager
    manager.end_drain()
    # Вторая половина того же класса, предсуществующая: `restart_server()` закрывает ЕЩЁ и
    # приём мутирующего HTTP, а фикстура возвращала только приём ходов. Утечка роняла
    # `test_fd_adopt.py::test_t6_real_middleware_counts_mutating_but_not_streams` — запрос
    # отвергался гейтом, и обработчик не выполнялся вовсе. Воспроизведено и на чистом main.
    app_main.open_mutating_admission()


@pytest.mark.asyncio
async def test_restart_endpoint_returns_preparation_then_defers_signal(monkeypatch):
    from app.routes import system

    restart = AsyncMock(return_value={
        "ok": True,
        "prepared": True,
        "waited_s": 0.25,
        "cut_turns": 0,
        "cut_names": [],
        "cut_ids": [],
    })
    signal_restart = AsyncMock(return_value={"ok": True})
    monkeypatch.setattr(system, "_restart_service_after_response", restart)
    monkeypatch.setattr(system, "_signal_restart_after_response", signal_restart)

    result = await system.restart_server()
    await asyncio.sleep(0)

    assert result["ok"] is True and result["scheduled"] is True
    assert result["waited_s"] == 0.25
    restart.assert_awaited_once_with(signal=False)
    signal_restart.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_http_background_signal_runs_only_after_response_lifecycle(monkeypatch):
    from fastapi import BackgroundTasks
    from app.routes import system

    monkeypatch.setattr(
        system,
        "_restart_service_after_response",
        AsyncMock(return_value={
            "ok": True,
            "prepared": True,
            "waited_s": 0.1,
            "cut_turns": 0,
            "cut_names": [],
            "cut_ids": [],
        }),
    )
    signal_restart = AsyncMock(return_value={"ok": True})
    monkeypatch.setattr(system, "_signal_restart_after_response", signal_restart)
    background = BackgroundTasks()

    result = await system.restart_server(background)

    assert result["scheduled"] is True
    signal_restart.assert_not_awaited()
    await background()
    signal_restart.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_signal_failure_is_exposed_on_restart_error_header(monkeypatch):
    from urllib.parse import unquote

    from app import main as app_main
    from app.routes import system

    monkeypatch.setattr(system, "_RESPONSE_FLUSH_PAUSE_S", 0)
    monkeypatch.setattr(
        "app.live_broker.broker.close_subscribers",
        MagicMock(side_effect=RuntimeError("synthetic signal failure")),
    )

    with pytest.raises(RuntimeError, match="synthetic signal failure"):
        await system._signal_restart_after_response()

    assert unquote(app_main.restart_failure_header()) == (
        "restart signal failed: RuntimeError: synthetic signal failure"
    )


@pytest.mark.asyncio
async def test_failed_handover_rollback_keeps_admission_fail_closed(monkeypatch):
    from urllib.parse import unquote

    from app import main as app_main
    from app.routes import system

    app_main.close_mutating_admission()
    system.manager.begin_drain()
    monkeypatch.setattr(system.restart_guard, "abort_guard", AsyncMock())
    monkeypatch.setattr(
        system.manager,
        "rollback_restart_handover",
        AsyncMock(side_effect=RuntimeError("resume and stop both failed")),
    )

    with pytest.raises(RuntimeError, match="resume and stop both failed"):
        await system._abort_restart("synthetic rollback failure")

    assert app_main.mutating_admission_open() is False
    assert system.manager.draining is True
    assert unquote(app_main.restart_failure_header()) == "synthetic rollback failure"


@pytest.mark.asyncio
async def test_restart_preparation_deadline_returns_a_reason(monkeypatch):
    from app.routes import system

    blocker = asyncio.Event()

    async def never_prepares():
        await blocker.wait()

    abort = AsyncMock()
    monkeypatch.setattr(system, "_do_restart_service", never_prepares)
    monkeypatch.setattr(system, "_abort_restart", abort)
    monkeypatch.setattr(system, "RESTART_PREPARATION_BUDGET_S", 0.01)

    result = await asyncio.wait_for(system._prepare_restart_service(), timeout=0.5)

    assert result["ok"] is False and result["phase"] == "preparation"
    assert result["waited_s"] == 0.01
    assert "deadline exceeded after 0.01s" in result["reason"]
    abort.assert_awaited_once_with(result["reason"])


@pytest.mark.asyncio
async def test_restart_preparation_deadline_also_bounds_abort_cleanup(monkeypatch):
    from app import main as app_main
    from app.deps import manager
    from app.routes import system

    work_blocker = asyncio.Event()
    cleanup_blocker = asyncio.Event()

    async def never_prepares():
        await work_blocker.wait()

    async def never_cleans(_reason):
        await cleanup_blocker.wait()

    monkeypatch.setattr(system, "_do_restart_service", never_prepares)
    monkeypatch.setattr(system, "_abort_restart", never_cleans)
    monkeypatch.setattr(system, "RESTART_PREPARATION_BUDGET_S", 0.01)
    monkeypatch.setattr(system, "RESTART_ABORT_CLEANUP_BUDGET_S", 0.01)
    monkeypatch.setattr(system, "RESTART_PREPARATION_CEILING_S", 0.02)
    manager.begin_drain()
    app_main.close_mutating_admission()

    started = asyncio.get_running_loop().time()
    result = await asyncio.wait_for(system._prepare_restart_service(), timeout=0.2)
    elapsed = asyncio.get_running_loop().time() - started

    assert elapsed < 0.1
    assert result["waited_s"] == 0.02
    assert "abort cleanup deadline exceeded after 0.01s" in result["reason"]
    assert manager.draining is False
    assert app_main.mutating_admission_open() is True


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
