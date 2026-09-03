import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.quota_controller import DispatchDecision
from app.quota_gate import QuotaDecision


def _static(state="available"):
    return QuotaDecision(
        state=state,
        model="gpt-5.6-codex",
        provider="codex",
        provider_label="Codex",
        weekly_utilization=1.0,
        observed_at=1.0,
        valid_until=9999999999.0,
        reset_at=None,
        alternatives=(),
        reason="test",
    )


class _Observer:
    def __init__(self, adaptive):
        self.adaptive = adaptive
        self.settled = []

    async def reserve_before_submit(self, _context, _static):
        return self.adaptive

    async def mark_submitted(self, reservation):
        return reservation

    async def mark_submit_failed(self, _reservation, _error):
        return None

    async def settle_shadow_dispatch(self, reservation, event_id, ended_at, **kwargs):
        self.settled.append((reservation, event_id, kwargs.get("status")))


def _adaptive_hold():
    return DispatchDecision(
        constraints=(),
        would_allow=False,
        binding_constraint=None,
        recommendation="indeterminate",
        zone="THROTTLE",
        confidence="operational",
        reasons=(),
        decision_id="shadow:test",
        context={"session_id": "test", "turn_gen": 1},
    )


def _adaptive_allow_unsafe():
    return DispatchDecision(
        constraints=(),
        would_allow=True,
        binding_constraint=None,
        recommendation="allow",
        zone="THROTTLE",
        confidence="operational",
        reasons=(),
        decision_id="shadow:test-allow",
        context={"session_id": "test", "turn_gen": 1},
    )


def _session(monkeypatch, role, observer, backend):
    from app.session import AgentSession

    monkeypatch.setattr("app.session.save_session", MagicMock())
    monkeypatch.setattr("app.session.add_log", MagicMock(return_value=1))
    monkeypatch.setenv("ORCHESTRA_ADAPTIVE_ENFORCEMENT", "1")
    session = AgentSession(
        id=f"{role}-test",
        name=f"{role}-test",
        role=role,
        scope="/test",
        cwd="/tmp",
        model="gpt-5.6-codex",
        backend_type="codex",
        system_prompt="test",
        created_at=datetime.now(timezone.utc),
        _quota_shadow_controller=observer,
    )
    session._admission_service = AsyncMock(return_value=_static())
    session._ensure_backend = AsyncMock(return_value=backend)
    backend.resume_failed = False
    session._build_runtime_handoff = AsyncMock(return_value="")
    session._persist = lambda: None
    session._log = lambda *_args, **_kwargs: None
    return session


def test_t314_worker_hold_prevents_provider_submit_and_records_hold(monkeypatch):
    async def run():
        backend = AsyncMock()
        observer = _Observer(_adaptive_hold())
        session = _session(monkeypatch, "worker", observer, backend)
        with pytest.raises(Exception, match="adaptive quota controller"):
            await session.send("new turn")
        await asyncio.sleep(0.05)
        return backend, observer

    backend, observer = asyncio.run(run())
    backend.send.assert_not_awaited()
    assert observer.settled and observer.settled[0][2] == "adaptive_hold"


def test_t314_orchestrator_is_exempt_and_provider_submit_still_occurs(monkeypatch):
    async def run():
        backend = AsyncMock()
        observer = _Observer(_adaptive_hold())
        session = _session(monkeypatch, "orchestrator", observer, backend)
        await session.send("orchestrator turn")
        return backend

    backend = asyncio.run(run())
    backend.send.assert_awaited_once_with("orchestrator turn")


def test_t314_luna_fast_is_not_disabled_on_real_session_path(monkeypatch):
    async def run():
        backend = AsyncMock()
        session = _session(monkeypatch, "worker", _Observer(_adaptive_allow_unsafe()), backend)
        session.model = "gpt-5.6-luna"
        await session.send("fast turn")
        return backend

    backend = asyncio.run(run())
    backend.send.assert_awaited_once_with("fast turn")


def test_t314_noncritical_sol_is_held_before_luna_on_real_session_path(monkeypatch):
    async def run():
        backend = AsyncMock()
        session = _session(monkeypatch, "noncritical", _Observer(_adaptive_allow_unsafe()), backend)
        session.model = "gpt-5.6-sol"
        with pytest.raises(Exception, match="noncritical_sol_before_luna"):
            await session.send("noncritical turn")
        return backend

    backend = asyncio.run(run())
    backend.send.assert_not_awaited()


def test_t314_task_class_field_cannot_spoof_server_role(monkeypatch):
    async def run():
        backend = AsyncMock()
        session = _session(monkeypatch, "worker", _Observer(_adaptive_allow_unsafe()), backend)
        session.model = "gpt-5.6-sol"
        session.task_class = "noncritical"  # caller-shaped field must not alter admission
        await session.send("ordinary turn")
        return backend

    backend = asyncio.run(run())
    backend.send.assert_awaited_once_with("ordinary turn")


def test_t314_concurrent_worker_holds_do_not_submit(monkeypatch):
    async def run():
        backends = [AsyncMock(), AsyncMock()]
        sessions = [
            _session(monkeypatch, "worker", _Observer(_adaptive_hold()), backend)
            for backend in backends
        ]
        results = await asyncio.gather(
            *(session.send("new turn") for session in sessions),
            return_exceptions=True,
        )
        assert all(isinstance(result, Exception) for result in results)
        return backends

    backends = asyncio.run(run())

    assert all(not backend.send.await_args_list for backend in backends)
