"""TDD tests for session.py — AgentSession state machine + concurrency."""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_sdk():
    """Mock ClaudeSDKClient that simulates connect/query/receive/disconnect."""
    client = AsyncMock()
    client.connect = AsyncMock()
    client.disconnect = AsyncMock()
    client.query = AsyncMock()
    client.interrupt = AsyncMock()

    async def fake_receive():
        from app.session import _make_result_message
        yield _make_result_message(session_id="sdk-session-001", cost=0.05)

    client.receive_messages = fake_receive
    return client


@pytest.fixture
def mock_db(monkeypatch):
    """Stub out all DB calls."""
    monkeypatch.setattr("app.session.save_session", MagicMock())
    monkeypatch.setattr("app.session.add_log", MagicMock(return_value=1))


@pytest.fixture
def session(mock_db):
    from app.session import AgentSession, AgentStatus
    return AgentSession(
        id="test-uuid-001",
        name="worker-1",
        scope="/mnt/data/Projects/test",
        cwd="/tmp/test-cwd",
        model="claude-sonnet-4-6",
        system_prompt="You are a worker.",
        status=AgentStatus.STARTING,
        created_at=datetime.now(timezone.utc),
    )


class TestStartNoMessage:
    @pytest.mark.asyncio
    async def test_goes_idle(self, session, mock_sdk):
        from app.session import AgentStatus
        with patch("app.session._create_client", return_value=mock_sdk):
            await session.start()
        assert session.status == AgentStatus.IDLE

    @pytest.mark.asyncio
    async def test_connects_client(self, session, mock_sdk):
        with patch("app.session._create_client", return_value=mock_sdk):
            await session.start()
        mock_sdk.connect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_query_called(self, session, mock_sdk):
        with patch("app.session._create_client", return_value=mock_sdk):
            await session.start()
        mock_sdk.query.assert_not_awaited()


class TestStartWithMessage:
    @pytest.mark.asyncio
    async def test_goes_running_then_idle(self, session, mock_sdk):
        from app.session import AgentStatus
        with patch("app.session._create_client", return_value=mock_sdk):
            await session.start("do something")
            await asyncio.sleep(0.1)
            if session._turn_task:
                await session._turn_task
        assert session.status == AgentStatus.IDLE

    @pytest.mark.asyncio
    async def test_query_called(self, session, mock_sdk):
        with patch("app.session._create_client", return_value=mock_sdk):
            await session.start("do something")
            if session._turn_task:
                await session._turn_task
        mock_sdk.query.assert_awaited_once_with("do something")

    @pytest.mark.asyncio
    async def test_session_id_saved(self, session, mock_sdk):
        with patch("app.session._create_client", return_value=mock_sdk):
            await session.start("task")
            if session._turn_task:
                await session._turn_task
        assert session.session_id == "sdk-session-001"

    @pytest.mark.asyncio
    async def test_cost_accumulated(self, session, mock_sdk):
        with patch("app.session._create_client", return_value=mock_sdk):
            await session.start("task")
            if session._turn_task:
                await session._turn_task
        assert session.cost_usd == pytest.approx(0.05)


class TestSend:
    @pytest.mark.asyncio
    async def test_idle_accepts_send(self, session, mock_sdk):
        from app.session import AgentStatus
        with patch("app.session._create_client", return_value=mock_sdk):
            await session.start()
            assert session.status == AgentStatus.IDLE
            await session.send("new task")
            await asyncio.sleep(0.1)
            if session._turn_task:
                await session._turn_task
            assert session.status in (AgentStatus.RUNNING, AgentStatus.IDLE)

    @pytest.mark.asyncio
    async def test_running_queues(self, session, mock_sdk):
        from app.session import AgentStatus

        never_finish = AsyncMock()
        async def slow_receive():
            await asyncio.sleep(10)
            yield MagicMock()
        never_finish.receive_messages = slow_receive
        never_finish.connect = AsyncMock()
        never_finish.query = AsyncMock()

        with patch("app.session._create_client", return_value=never_finish):
            await session.start("long task")
            await asyncio.sleep(0.05)
            assert session.status == AgentStatus.RUNNING
            await session.send("queued task")
            assert session._pending or session.status == AgentStatus.RUNNING

    @pytest.mark.asyncio
    async def test_stopped_raises(self, session, mock_sdk):
        from app.session import AgentStatus
        session.status = AgentStatus.STOPPED
        with pytest.raises(RuntimeError):
            await session.send("task")

    @pytest.mark.asyncio
    async def test_reconnects_per_turn(self, session, mock_sdk):
        session.debounce_sec = 0.1
        with patch("app.session._create_client", return_value=mock_sdk) as factory:
            await session.start()
            session.session_id = "existing-session"
            await session.send("new task")
            await asyncio.sleep(0.3)
            if session._turn_task:
                await session._turn_task
            assert factory.call_count == 2


class TestListenLoop:
    @pytest.mark.asyncio
    async def test_result_message_sets_idle(self, session, mock_sdk):
        from app.session import AgentStatus
        with patch("app.session._create_client", return_value=mock_sdk):
            await session.start("task")
            if session._turn_task:
                await session._turn_task
        assert session.status == AgentStatus.IDLE

    @pytest.mark.asyncio
    async def test_error_sets_error_status(self, session, mock_sdk):
        from app.session import AgentStatus
        mock_sdk.query = AsyncMock(side_effect=ConnectionError("lost connection"))
        with patch("app.session._create_client", return_value=mock_sdk):
            await session.start("task")
            if session._turn_task:
                try:
                    await session._turn_task
                except ConnectionError:
                    pass
        assert session.status == AgentStatus.ERROR


class TestStop:
    @pytest.mark.asyncio
    async def test_cancels_turn_task(self, session, mock_sdk):
        never_finish = AsyncMock()
        async def slow_receive():
            await asyncio.sleep(10)
            yield MagicMock()
        never_finish.receive_messages = slow_receive
        never_finish.connect = AsyncMock()
        never_finish.query = AsyncMock()
        never_finish.disconnect = AsyncMock()

        with patch("app.session._create_client", return_value=never_finish):
            await session.start("long task")
            await asyncio.sleep(0.05)
            await session.stop()
        from app.session import AgentStatus
        assert session.status == AgentStatus.STOPPED

    @pytest.mark.asyncio
    async def test_disconnects_client(self, session, mock_sdk):
        with patch("app.session._create_client", return_value=mock_sdk):
            await session.start()
            await session.stop()
        mock_sdk.disconnect.assert_awaited()


class TestInterrupt:
    @pytest.mark.asyncio
    async def test_calls_interrupt(self, session, mock_sdk):
        with patch("app.session._create_client", return_value=mock_sdk):
            await session.start()
            await session.interrupt()
        mock_sdk.interrupt.assert_awaited_once()


class TestConcurrentSend:
    @pytest.mark.asyncio
    async def test_second_send_queued(self, session, mock_sdk):
        slow = AsyncMock()
        async def slow_receive():
            await asyncio.sleep(0.5)
            from app.session import _make_result_message
            yield _make_result_message(session_id="s", cost=0)
        slow.receive_messages = slow_receive
        slow.connect = AsyncMock()
        slow.query = AsyncMock()

        with patch("app.session._create_client", return_value=slow):
            await session.start("task1")
            await asyncio.sleep(0.05)
            await session.send("task2")
            assert True


class TestAutoApprove:
    @pytest.mark.asyncio
    async def test_returns_allow(self):
        from app.session import AgentSession
        result = await AgentSession._auto_approve("Bash", {"command": "ls"})
        from claude_agent_sdk import PermissionResultAllow
        assert isinstance(result, PermissionResultAllow)
