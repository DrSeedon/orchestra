"""Restart retires runtime processes; only persisted conversations cross generations."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_shutdown_stops_every_session_even_when_backend_has_live_pipes():
    from app.manager import SessionManager

    manager = SessionManager()
    sessions = [SimpleNamespace(id=str(i), name=str(i), stop=AsyncMock()) for i in range(2)]
    manager.sessions = {s.id: s for s in sessions}
    manager._hand_over_backend = AsyncMock(return_value=True)
    await manager.shutdown_all()
    for session in sessions:
        session.stop.assert_awaited_once()
    assert not manager.sessions


def test_backends_cannot_adopt_previous_generation():
    from app.backend_codex import CodexBackend
    from app.backend_grok import GrokBackend
    from app.session import AgentSession

    assert not hasattr(CodexBackend, 'adopt')
    assert not hasattr(GrokBackend, 'adopt')
    assert not hasattr(AgentSession, 'adopt_backend')


def test_deployed_service_owns_descendants_and_does_not_store_agent_pipes():
    root = Path(__file__).resolve().parents[1]
    for name in ('orchestra.service', 'orchestra.service.template'):
        text = (root / 'deploy' / name).read_text()
        assert 'KillMode=control-group' in text
        assert 'FileDescriptorStoreMax=0' in text
        assert 'Delegate=yes' in text
