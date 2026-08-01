"""Hibernate and heartbeat health checks for process runtimes."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.session_hibernate import HibernateManager
from app.session_state import AgentStatus


def _session(*, backend=None, listener_done=False):
    listener = SimpleNamespace(done=lambda: listener_done)
    return SimpleNamespace(_backend=backend, _listen_task=listener)


def test_live_codex_process_and_listener_are_not_zombie():
    backend = SimpleNamespace(is_alive=True)
    assert HibernateManager._process_runtime_dead(_session(backend=backend)) is False


def test_dead_codex_process_is_zombie_even_with_live_listener():
    backend = SimpleNamespace(is_alive=False)
    assert HibernateManager._process_runtime_dead(_session(backend=backend)) is True


def test_missing_backend_or_dead_listener_is_zombie():
    assert HibernateManager._process_runtime_dead(_session(backend=None)) is True
    backend = SimpleNamespace(is_alive=True)
    assert HibernateManager._process_runtime_dead(
        _session(backend=backend, listener_done=True)
    ) is True


def _hibernate_session(*, backend, status=AgentStatus.IDLE):
    return SimpleNamespace(
        name="worker",
        backend_type="codex",
        is_orchestrator=False,
        status=status,
        session_id="thread-1",
        _backend=backend,
        _pending_messages=[],
        _compacting=False,
        _hibernated=False,
        _lifecycle_lock=asyncio.Lock(),
        _hibernate_task=None,
        _disconnect_backend=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_manual_hibernate_accepts_verified_codex_before_capability_flip():
    backend = SimpleNamespace(hibernate_safe=True)
    session = _hibernate_session(backend=backend)

    result = await HibernateManager(session).hibernate_now(manual=True)

    assert result == {"ok": True, "state": "hibernated"}
    session._disconnect_backend.assert_awaited_once_with()
    assert session._hibernated is True
    assert session.session_id == "thread-1"


@pytest.mark.asyncio
async def test_hibernate_refuses_unverified_codex_with_visible_reason():
    backend = SimpleNamespace(
        hibernate_safe=False,
        hibernate_unavailable_reason="RuntimeError: Linger=no",
    )
    session = _hibernate_session(backend=backend)

    result = await HibernateManager(session).hibernate_now(manual=True)

    assert result == {
        "ok": False,
        "reason": "unsafe_backend",
        "error": "RuntimeError: Linger=no",
    }
    session._disconnect_backend.assert_not_awaited()
    assert session._hibernated is False


@pytest.mark.asyncio
@pytest.mark.parametrize("blocked", ["running", "pending", "compacting"])
async def test_hibernate_refuses_active_session_state(blocked):
    session = _hibernate_session(backend=SimpleNamespace(hibernate_safe=True))
    if blocked == "running":
        session.status = AgentStatus.RUNNING
    elif blocked == "pending":
        session._pending_messages.append("deliver me")
    else:
        session._compacting = True

    result = await HibernateManager(session).hibernate_now(manual=True)

    assert result["ok"] is False
    session._disconnect_backend.assert_not_awaited()
    assert session._hibernated is False


@pytest.mark.asyncio
async def test_hibernate_teardown_failure_never_claims_success():
    session = _hibernate_session(backend=SimpleNamespace(hibernate_safe=True))
    session._disconnect_backend.side_effect = PermissionError("scope denied")

    with pytest.raises(PermissionError, match="scope denied"):
        await HibernateManager(session).hibernate_now(manual=True)

    assert session._hibernated is False


@pytest.mark.asyncio
async def test_automatic_teardown_failure_logs_exception_class(monkeypatch, caplog):
    import app.session_hibernate as module

    monkeypatch.setattr(module.asyncio, "sleep", AsyncMock())
    monkeypatch.setattr(
        module,
        "get_runtime",
        lambda _runtime: SimpleNamespace(
            capabilities=SimpleNamespace(hibernate=True),
        ),
    )
    session = _hibernate_session(backend=SimpleNamespace(hibernate_safe=True))
    session._disconnect_backend.side_effect = TimeoutError()

    with caplog.at_level("ERROR", logger="app.session"):
        await HibernateManager(session)._idle_hibernate(300)

    assert "automatic hibernate failed: TimeoutError:" in caplog.text
    assert session._hibernated is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("is_orchestrator", "expected_timeout"),
    [(False, 300), (True, 600)],
)
async def test_fake_idle_timer_uses_shared_verified_hibernate(
    monkeypatch, is_orchestrator, expected_timeout,
):
    import app.session_hibernate as module

    real_sleep = asyncio.sleep
    timer_started = asyncio.Event()
    release_timer = asyncio.Event()
    delays = []

    async def fake_sleep(delay):
        delays.append(delay)
        timer_started.set()
        await release_timer.wait()

    monkeypatch.setattr(module.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(
        module,
        "get_runtime",
        lambda _runtime: SimpleNamespace(
            capabilities=SimpleNamespace(hibernate=True),
        ),
    )
    session = _hibernate_session(backend=SimpleNamespace(hibernate_safe=True))
    session.is_orchestrator = is_orchestrator
    manager = HibernateManager(session)

    manager.schedule()
    await timer_started.wait()
    assert delays == [expected_timeout]
    release_timer.set()
    await real_sleep(0)
    await session._hibernate_task

    session._disconnect_backend.assert_awaited_once_with()
    assert session._hibernated is True
    assert session.session_id == "thread-1"
