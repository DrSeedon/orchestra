"""Task #39 Fix 6 — ClaudeBackend cleans up client on connect/reconnect failure (no zombie CLI)."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

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
async def test_reconnect_timeout_disconnects_client():
    client = AsyncMock()
    client.connect = AsyncMock(side_effect=TimeoutError("reconnect timed out"))
    client.disconnect = AsyncMock()
    b = _backend()
    with patch.object(b, "_make_client", return_value=client):
        with pytest.raises(TimeoutError):
            await b.reconnect()
    assert b._client is None
