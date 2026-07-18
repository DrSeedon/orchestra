"""Task #39 Fix 6 — ClaudeBackend cleans up client on connect/reconnect failure (no zombie CLI)."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock

import app.backend_claude as backend_claude
from app.backend_claude import ClaudeBackend


def _backend():
    return ClaudeBackend(model="claude-sonnet-5[1m]", cwd="/tmp")


@pytest.mark.asyncio
async def test_connect_timeout_disconnects_client():
    client = AsyncMock()
    client.connect = AsyncMock(side_effect=TimeoutError("connect timed out"))
    client.disconnect = AsyncMock()
    b = _backend()
    with patch.object(b, "_make_client", return_value=client):
        with pytest.raises(TimeoutError):
            await b.connect()
    client.disconnect.assert_awaited_once()
    assert b._client is None


@pytest.mark.asyncio
async def test_connect_cancelled_disconnects_client():
    client = AsyncMock()
    client.connect = AsyncMock(side_effect=asyncio.CancelledError())
    client.disconnect = AsyncMock()
    b = _backend()
    with patch.object(b, "_make_client", return_value=client):
        with pytest.raises(asyncio.CancelledError):
            await b.connect()
    client.disconnect.assert_awaited_once()
    assert b._client is None


@pytest.mark.asyncio
async def test_missing_resume_transcript_falls_back_to_fresh_client():
    failed = AsyncMock()
    failed.connect = AsyncMock(side_effect=RuntimeError("Check stderr output for details"))
    failed.disconnect = AsyncMock()
    fresh = AsyncMock()
    fresh.connect = AsyncMock()
    fresh.disconnect = AsyncMock()
    b = ClaudeBackend(
        model="claude-opus-4-6[1m]",
        cwd="/tmp",
        resume_session_id="missing-session",
    )

    with (
        patch.object(b, "_make_client", side_effect=[failed, fresh]),
        patch.object(b, "_resume_transcript_exists", return_value=False),
    ):
        await b.connect()

    failed.disconnect.assert_awaited_once()
    fresh.connect.assert_awaited_once()
    assert b.resume_failed is True
    assert b.session_id is None
    assert b._client is fresh


@pytest.mark.asyncio
async def test_existing_resume_transcript_does_not_hide_connect_failure():
    failed = AsyncMock()
    failed.connect = AsyncMock(side_effect=RuntimeError("upstream unavailable"))
    failed.disconnect = AsyncMock()
    b = ClaudeBackend(
        model="claude-opus-4-6[1m]",
        cwd="/tmp",
        resume_session_id="existing-session",
    )

    with (
        patch.object(b, "_make_client", return_value=failed),
        patch.object(b, "_resume_transcript_exists", return_value=True),
        pytest.raises(RuntimeError, match="upstream unavailable"),
    ):
        await b.connect()

    assert b.resume_failed is False


@pytest.mark.asyncio
async def test_reconnect_timeout_disconnects_client():
    client = AsyncMock()
    client.connect = AsyncMock(side_effect=TimeoutError("reconnect timed out"))
    client.disconnect = AsyncMock()
    b = _backend()
    with patch.object(b, "_make_client", return_value=client):
        with pytest.raises(TimeoutError):
            await b.reconnect()
    assert b._client is None


@pytest.mark.asyncio
async def test_interrupt_returns_true_on_control_ack():
    client = AsyncMock()
    client.interrupt = AsyncMock()
    b = _backend()
    b._client = client

    assert await b.interrupt() is True
    client.interrupt.assert_awaited_once()


@pytest.mark.asyncio
async def test_interrupt_is_bounded_when_control_ack_never_arrives(monkeypatch):
    async def never_returns():
        await asyncio.Event().wait()

    client = AsyncMock()
    client.interrupt = never_returns
    b = _backend()
    b._client = client
    monkeypatch.setattr(backend_claude, "CLAUDE_INTERRUPT_TIMEOUT", 0.02, raising=False)

    result = await asyncio.wait_for(b.interrupt(), timeout=0.2)

    assert result is False


def test_server_error_is_carried_into_terminal_turn_result():
    b = _backend()

    error_events = b._convert(AssistantMessage(
        content=[TextBlock("API Error: Response stalled mid-stream.")],
        model="claude-opus-4-8",
        error="server_error",
    ))
    result_events = b._convert(ResultMessage(
        subtype="result",
        duration_ms=301_000,
        duration_api_ms=301_000,
        is_error=True,
        num_turns=1,
        session_id="sdk-server-error",
        stop_reason="stop_sequence",
        errors=[],
    ))

    assert error_events[-1].type == "error"
    assert error_events[-1].metadata["model_error"] == "server_error"
    turn_end = result_events[-1]
    assert turn_end.type == "turn_end"
    assert turn_end.metadata["ok"] is False
    assert turn_end.metadata["model_error"] == "server_error"
    assert turn_end.metadata["errors"] == ["server_error"]

    next_result = b._convert(ResultMessage(
        subtype="result",
        duration_ms=10,
        duration_api_ms=10,
        is_error=False,
        num_turns=1,
        session_id="sdk-server-error",
        stop_reason="stop_sequence",
    ))[-1]
    assert next_result.metadata["model_error"] == ""
    assert next_result.metadata["errors"] == []
