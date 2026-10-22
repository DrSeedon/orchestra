"""V-1020: the restart log drain must never spin or block the event loop."""

import asyncio
import logging
import types

import pytest

from app import session as session_mod
from app.session import AgentSession


def _stub():
    stub = types.SimpleNamespace(
        name="stub",
        _log_futures=set(),
        _failed_log_writes={},
        _log_write_failure_generation=0,
        _log_write_failure="",
    )

    async def no_persist():
        return None

    stub._drain_persist = no_persist
    stub._await_log_futures = types.MethodType(AgentSession._await_log_futures, stub)
    return stub


@pytest.mark.asyncio
@pytest.mark.timeout(20)
async def test_finished_future_left_in_the_set_does_not_hang_the_drain():
    stub = _stub()
    stuck = asyncio.get_running_loop().create_future()
    stuck.set_result(None)
    stub._log_futures.add(stuck)  # its discard callback never ran

    result = await asyncio.wait_for(AgentSession._drain_handoff_log_writes(stub), 5)

    assert result["ok"] is True
    assert stub._log_futures == set()


@pytest.mark.asyncio
@pytest.mark.timeout(20)
async def test_hung_write_degrades_to_a_warning_and_is_not_cancelled(monkeypatch, caplog):
    monkeypatch.setattr(session_mod, "_LOG_FUTURES_DRAIN_BUDGET_S", 0.05)
    stub = _stub()
    hung = asyncio.get_running_loop().create_future()
    stub._log_futures.add(hung)

    with caplog.at_level(logging.WARNING, logger=session_mod.logger.name):
        await asyncio.wait_for(AgentSession._drain_handoff_log_writes(stub), 5)

    assert "still pending" in caplog.text
    assert not hung.cancelled()


@pytest.mark.asyncio
@pytest.mark.timeout(20)
async def test_producers_that_keep_logging_cannot_extend_the_drain():
    stub = _stub()
    loop = asyncio.get_running_loop()
    running = True

    async def producer():
        while running:
            future = loop.create_future()
            stub._log_futures.add(future)
            loop.call_later(0.01, future.set_result, None)
            await asyncio.sleep(0.001)

    task = asyncio.create_task(producer())
    await asyncio.sleep(0.05)
    try:
        await asyncio.wait_for(AgentSession._drain_handoff_log_writes(stub), 5)
    finally:
        running = False
        await task
