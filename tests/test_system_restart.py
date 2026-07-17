"""Restart endpoint behavior."""

import asyncio
import os
import signal
from unittest.mock import AsyncMock, MagicMock

import pytest


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
    from app.routes import system

    sleep = AsyncMock()
    kill = MagicMock()
    monkeypatch.setattr(system.asyncio, "sleep", sleep)
    monkeypatch.setattr(system.os, "kill", kill)

    await system._restart_service_after_response()

    sleep.assert_awaited_once_with(0.5)
    kill.assert_called_once_with(os.getpid(), signal.SIGINT)
