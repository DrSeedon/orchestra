"""Audit 2026-09-01: turn-completion signalling, honest stop, drain gate ordering."""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def mock_db(monkeypatch):
    monkeypatch.setattr("app.session.save_session", MagicMock())
    monkeypatch.setattr("app.session.add_log", MagicMock(return_value=1))
    monkeypatch.setattr("app.bg_jobs.bg_manager", None)


def _make_session(name="w1"):
    from app.session import AgentSession

    return AgentSession(
        id=f"audit-{name}", name=name, scope="/test", cwd="/tmp",
        model="claude-sonnet-5[1m]", system_prompt="test",
        created_at=datetime.now(timezone.utc),
    )


async def _run_one_heartbeat_pass(monkeypatch, session):
    """Drive heartbeat_loop through exactly one iteration, then cancel it."""
    import app.session_hibernate as module
    from app.session_hibernate import HibernateManager

    real_sleep = asyncio.sleep
    monkeypatch.setattr(
        module.asyncio, "sleep",
        AsyncMock(side_effect=[None, asyncio.CancelledError()]),
    )
    try:
        await HibernateManager(session).heartbeat_loop()
    finally:
        monkeypatch.setattr(module.asyncio, "sleep", real_sleep)


@pytest.mark.asyncio
async def test_heartbeat_recovery_releases_the_turn_waiter(mock_db, monkeypatch):
    """RUNNING→IDLE without publish strands wait_for_turn_completion under the session lock.

    switch/merge park on `_turn_finished_event` inside `wait_for_session_lock`; a
    transition that skips the publish holds that lock until the process restarts.
    """
    from app.session import AgentStatus

    real_sleep = asyncio.sleep
    session = _make_session()
    session._backend = SimpleNamespace(reconnect=AsyncMock(), send=AsyncMock())
    session._listen_task = SimpleNamespace(done=lambda: True)
    session._reconnect_backend = AsyncMock(side_effect=RuntimeError("CLI is gone"))
    session._log = MagicMock()
    session._persist = MagicMock()
    session._last_msg_time = 0
    session._turns.bump_turn_gen()
    session.status = AgentStatus.RUNNING

    waiter = asyncio.create_task(session.wait_for_turn_completion())
    await real_sleep(0)
    assert waiter.done() is False

    await _run_one_heartbeat_pass(monkeypatch, session)

    assert session.status is AgentStatus.IDLE
    assert session._turn_finished_event.is_set() is True, (
        "heartbeat recovery went RUNNING→IDLE without publish_turn_finished"
    )
    assert await asyncio.wait_for(waiter, timeout=1) is True

    # The next call site that forgets to publish must not be a permanent lock either.
    monkeypatch.setattr("app.session.TURN_COMPLETION_RECHECK", 0.05)
    session._turns.bump_turn_gen()
    session.status = AgentStatus.RUNNING
    stranded = asyncio.create_task(session.wait_for_turn_completion())
    await real_sleep(0)
    session.status = AgentStatus.IDLE  # no publish at all
    assert await asyncio.wait_for(stranded, timeout=2) is True


@pytest.mark.asyncio
async def test_heartbeat_dead_process_recovery_publishes(mock_db, monkeypatch):
    """Second of the three recovery branches: process-backed runtime found dead.

    Its own seam — `process_liveness` + `_process_runtime_dead` — is unreachable for the
    failed-reconnect test above, which pins `_last_msg_time = 0`.
    """
    from app.session import AgentStatus

    session = _make_session("codex-dead")
    session.backend_type = "codex"
    session._log = MagicMock()
    session._persist = MagicMock()
    session._disconnect_backend = AsyncMock()
    session._backend = SimpleNamespace(is_alive=False)
    session._listen_task = SimpleNamespace(done=lambda: True)
    session._turns.bump_turn_gen()
    session.status = AgentStatus.RUNNING
    session._last_msg_time = asyncio.get_event_loop().time() - 10_000

    await _run_one_heartbeat_pass(monkeypatch, session)

    assert session._disconnect_backend.await_count == 1
    assert session.status is AgentStatus.IDLE
    assert session._turn_finished_event.is_set() is True, (
        "dead-process recovery went RUNNING→IDLE without publish_turn_finished"
    )


@pytest.mark.asyncio
async def test_heartbeat_zombie_without_backend_publishes(mock_db, monkeypatch):
    """Third recovery branch: persistent runtime silent past the zombie timeout, backend gone.

    Reached only by a runtime with `process_liveness=False` and a persistent event stream,
    so neither of the other two branch tests can stand in for it.
    """
    from app.session import AgentStatus

    session = _make_session("claude-zombie")
    session._log = MagicMock()
    session._persist = MagicMock()
    session._backend = None
    session._listen_task = SimpleNamespace(done=lambda: True)
    session._turns.bump_turn_gen()
    session.status = AgentStatus.RUNNING
    session._last_msg_time = asyncio.get_event_loop().time() - 10_000

    await _run_one_heartbeat_pass(monkeypatch, session)

    assert session.status is AgentStatus.IDLE
    assert session._turn_finished_event.is_set() is True, (
        "zombie recovery went RUNNING→IDLE without publish_turn_finished"
    )


@pytest.mark.asyncio
async def test_drain_landing_during_stale_cli_release_refuses_the_turn(mock_db, monkeypatch):
    """No await may sit between the drain gate and status=RUNNING (#237 T3 class).

    `_refresh_stale_backend` really awaits `old.disconnect()` for an adopted CLI, so a
    restart's drain snapshot can be taken inside that window and miss the turn.
    """
    from app.session import AgentStatus, DrainingRefused

    session = _make_session("adopted")
    session._log = MagicMock()
    session._persist = MagicMock()
    fake_manager = SimpleNamespace(draining=False)
    monkeypatch.setattr("app.deps.manager", fake_manager)

    class StaleBackend:
        async def disconnect(self):
            await asyncio.sleep(0)
            fake_manager.draining = True  # begin_drain lands while the CLI is released

        async def send(self, message):
            raise AssertionError("turn started after the drain snapshot")

    session._backend = StaleBackend()
    session.tools_are_stale = True
    session.status = AgentStatus.IDLE
    session._ensure_backend = AsyncMock(
        side_effect=AssertionError("turn started after the drain snapshot")
    )

    with pytest.raises(DrainingRefused):
        from app.events import MessageProvenance
        await session.send(
            "go", provenance=MessageProvenance(origin="user", senders=("user",)),
        )

    assert session.status is AgentStatus.IDLE
