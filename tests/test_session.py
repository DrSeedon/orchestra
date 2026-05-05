"""TDD tests for session.py — AgentSession."""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_sdk():
    client = AsyncMock()
    client.connect = AsyncMock()
    client.disconnect = AsyncMock()
    client.query = AsyncMock()

    async def fake_receive():
        from claude_agent_sdk import ResultMessage
        yield ResultMessage(subtype="result", duration_ms=0, duration_api_ms=0,
                           is_error=False, num_turns=1, session_id="sdk-001", total_cost_usd=0.05)

    client.receive_messages = fake_receive
    return client


@pytest.fixture
def mock_db(monkeypatch):
    monkeypatch.setattr("app.session.save_session", MagicMock())
    monkeypatch.setattr("app.session.add_log", MagicMock(return_value=1))


@pytest.fixture
def session(mock_db):
    from app.session import AgentSession
    return AgentSession(
        id="test-001", name="w1", scope="/test", cwd="/tmp",
        model="claude-sonnet-4-6", system_prompt="test",
        created_at=datetime.now(timezone.utc),
    )


class TestStart:
    @pytest.mark.asyncio
    async def test_no_message_idle(self, session):
        from app.session import AgentStatus
        await session.start()
        assert session.status == AgentStatus.IDLE

    @pytest.mark.asyncio
    async def test_with_message(self, session, mock_sdk):
        from app.session import AgentStatus
        with patch("app.session.AgentSession._make_client", return_value=mock_sdk):
            await session.start("hi")
            if session._turn_task:
                await session._turn_task
        assert session.status == AgentStatus.IDLE
        assert session.session_id == "sdk-001"
        assert session.cost_usd == pytest.approx(0.05)


class TestSend:
    @pytest.mark.asyncio
    async def test_send_triggers_turn(self, session, mock_sdk):
        session.debounce_sec = 0.1
        with patch("app.session.AgentSession._make_client", return_value=mock_sdk):
            await session.start()
            await session.send("task")
            await asyncio.sleep(0.3)
            if session._turn_task:
                await session._turn_task
        mock_sdk.query.assert_awaited()


class TestTurn:
    @pytest.mark.asyncio
    async def test_error_returns_to_idle(self, session, mock_sdk):
        from app.session import AgentStatus
        mock_sdk.connect = AsyncMock(side_effect=ConnectionError("fail"))
        with patch("app.session.AgentSession._make_client", return_value=mock_sdk):
            await session.start("task")
            if session._turn_task:
                try:
                    await session._turn_task
                except:
                    pass
        assert session.status == AgentStatus.IDLE

    @pytest.mark.asyncio
    async def test_disconnect_called(self, session, mock_sdk):
        with patch("app.session.AgentSession._make_client", return_value=mock_sdk):
            await session.start("task")
            if session._turn_task:
                await session._turn_task
        mock_sdk.disconnect.assert_awaited()


class TestStop:
    @pytest.mark.asyncio
    async def test_stop_sets_idle(self, session, mock_sdk):
        from app.session import AgentStatus
        with patch("app.session.AgentSession._make_client", return_value=mock_sdk):
            await session.start()
            await session.stop()
        assert session.status == AgentStatus.IDLE
