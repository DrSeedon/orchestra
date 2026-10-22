"""Offline transport regressions for watching a running hub thread (V-1040)."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from app import backend_hub as hub
from app.multicode_client import MultiCodeClient, MultiCodeError


def _backend():
    return hub.HubBackend("hub-gpt-6.1-sol", ".")


def _stream():
    return SimpleNamespace(cursor=None, feed=Mock(return_value=[]))


def _ready_client(transport):
    client = MultiCodeClient("http://mock", "test-watch-token", client=transport)
    client._initialized = True
    client._session_id = "live-session"
    return client


def _result(body, value):
    return httpx.Response(200, json={"id": body["id"], "result": {"structuredContent": value}})


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [
    httpx.RemoteProtocolError, httpx.ReadError, httpx.ConnectError, httpx.ReadTimeout,
    500, 502, 503, 599, 400, 404,
])
async def test_watch_survives_transient_transport_or_session_error(monkeypatch, failure):
    calls = []
    waits = 0
    sleep = AsyncMock()
    monkeypatch.setattr(hub.asyncio, "sleep", sleep)

    async def handler(request):
        nonlocal waits
        body = json.loads(request.content)
        calls.append(body)
        if body["method"] == "initialize":
            return httpx.Response(200, json={"id": body["id"], "result": {}},
                                  headers={"Mcp-Session-Id": "new-session"})
        if body["method"] == "notifications/initialized":
            return httpx.Response(202)
        name = body["params"]["name"]
        if name == "t3_thread_wait":
            waits += 1
            if waits == 1:
                if isinstance(failure, int):
                    return httpx.Response(failure, text="session forgotten" if failure < 500 else "upstream broken")
                raise failure("test-watch-token", request=request)
            return _result(body, {"status": "completed", "timedOut": False})
        assert name == "t3_thread_read"
        return _result(body, {"items": [], "hasMore": False})

    backend = _backend()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
        assert [event async for event in backend._watch(
            _ready_client(transport), "thread", "run", _stream())] == []
    assert backend._watch_status == "completed"
    assert waits == 2
    if failure in (400, 404):
        sleep.assert_not_awaited()  # MCP session recovery itself is immediate and single-shot.
        assert sum(body["method"] == "initialize" for body in calls) == 1
    else:
        sleep.assert_awaited_once_with(1)
    assert all(body.get("params", {}).get("name") in (None, "t3_thread_wait", "t3_thread_read")
               for body in calls)


@pytest.mark.asyncio
async def test_watch_bounds_retries_and_surfaces_last_redacted_error(monkeypatch):
    calls = []
    sleep = AsyncMock()
    monkeypatch.setattr(hub.asyncio, "sleep", sleep)

    async def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(503, text=f"failure-{len(calls)} test-watch-token")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
        with pytest.raises(MultiCodeError) as error:
            _ = [event async for event in _backend()._watch(
                _ready_client(transport), "thread", "run", _stream())]
    assert len(calls) == 5
    assert [call.args[0] for call in sleep.await_args_list] == [1, 2, 4, 8]
    assert "failure-5" in str(error.value)
    assert "test-watch-token" not in str(error.value)
    assert "[redacted]" in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 403])
async def test_watch_does_not_retry_non_transient_http_error(monkeypatch, status):
    calls = []
    sleep = AsyncMock()
    monkeypatch.setattr(hub.asyncio, "sleep", sleep)

    async def handler(request):
        calls.append(request)
        return httpx.Response(status, text="invalid arguments")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
        with pytest.raises(MultiCodeError, match="invalid arguments"):
            _ = [event async for event in _backend()._watch(
                _ready_client(transport), "thread", "run", _stream())]
    assert len(calls) == 1
    sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_watch_retries_exhausted_session_recovery(monkeypatch):
    calls = []
    waits = 0
    sleep = AsyncMock()
    monkeypatch.setattr(hub.asyncio, "sleep", sleep)

    async def handler(request):
        nonlocal waits
        body = json.loads(request.content)
        calls.append(body)
        if body["method"] == "initialize":
            assert "Mcp-Session-Id" not in request.headers
            return httpx.Response(200, json={"id": body["id"], "result": {}},
                                  headers={"Mcp-Session-Id": "new-session"})
        if body["method"] == "notifications/initialized":
            return httpx.Response(202)
        if body["params"]["name"] == "t3_thread_wait":
            waits += 1
            if waits <= 2:
                return httpx.Response(400, text="session not found")
            return _result(body, {"status": "completed"})
        return _result(body, {"items": []})

    backend = _backend()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
        _ = [event async for event in backend._watch(_ready_client(transport), "thread", "run", _stream())]
    assert backend._watch_status == "completed"
    assert waits == 3
    sleep.assert_awaited_once_with(1)
    assert sum(body["method"] == "initialize" for body in calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["_poll", "_read_reply"])
async def test_watch_reads_survive_transient_error(monkeypatch, operation):
    reads = 0
    sleep = AsyncMock()
    monkeypatch.setattr(hub.asyncio, "sleep", sleep)

    async def handler(request):
        nonlocal reads
        body = json.loads(request.content)
        assert body["params"]["name"] == "t3_thread_read"
        reads += 1
        if reads == 1:
            return httpx.Response(502, text="upstream temporarily unavailable")
        return _result(body, {"items": [
            {"type": "assistant_message", "runId": "run", "text": "reply"}]})

    backend = _backend()
    stream = _stream()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
        client = _ready_client(transport)
        if operation == "_poll":
            assert await backend._poll(client, "thread", stream) == []
            stream.feed.assert_called_once()
        else:
            assert await backend._read_reply(client, "thread", "run") == "reply"
    assert reads == 2
    sleep.assert_awaited_once_with(1)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [
    httpx.ReadError, httpx.RemoteProtocolError, httpx.ConnectError, httpx.ReadTimeout,
    500, 503, "missing_run_id",
])
async def test_start_never_relaunches_after_uncertain_send(monkeypatch, failure):
    calls = []

    async def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        assert body["params"]["name"] == "t3_thread_send"
        if failure == "missing_run_id":
            return _result(body, {})
        if isinstance(failure, int):
            return httpx.Response(failure, text="upstream unavailable")
        raise failure("connection lost after delivery", request=request)

    backend = _backend()
    monkeypatch.setattr(backend, "_preamble", lambda: "preamble: ")
    state = SimpleNamespace(thread_id="existing-thread", ws_id="ws", project_id="project", save=Mock())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
        with pytest.raises(MultiCodeError):
            await backend._start(_ready_client(transport), state, "do once")
    assert len(calls) == 1
    assert state.thread_id == "existing-thread"
    state.save.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("refused_tool,status,detail", [
    ("t3_thread_send", 400, "thread is in error state"),
    ("t3_thread_send", 403, "thread is archived"),
    ("t3_thread_send", 409, "thread cannot accept messages"),
    ("t3_thread_send", 422, "thread rejected this turn"),
    ("t3_thread_configure", 400, "configuration rejected"),
    ("t3_thread_configure", 409, "thread is archived"),
])
async def test_explicit_thread_refusal_launches_replacement(monkeypatch, refused_tool, status, detail):
    calls = []
    backend = _backend()
    monkeypatch.setattr(backend, "_preamble", lambda: "preamble: ")
    monkeypatch.setattr(backend, "_model_selection", AsyncMock(return_value={"model": "test-model"}))
    if refused_tool == "t3_thread_configure":
        backend._effort = "high"

    async def handler(request):
        body = json.loads(request.content)
        params = body["params"]
        calls.append(params)
        if params["name"] == refused_tool:
            return httpx.Response(status, text=detail)
        assert params["name"] == "t3_thread_launch"
        return _result(body, {"threadId": "replacement", "runId": "new-run"})

    state = SimpleNamespace(thread_id="old-thread", ws_id="ws", project_id="project", save=Mock())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
        assert await backend._start(_ready_client(transport), state, "prompt") == "new-run"
    assert [call["name"] for call in calls] == [refused_tool, "t3_thread_launch"]
    assert calls[1]["arguments"]["message"] == "preamble: prompt"
    assert state.thread_id == "replacement"
    state.save.assert_called_once()


@pytest.mark.parametrize("status", [400, 404, 503])
def test_session_or_transport_error_is_not_workspace_loss(status):
    assert not hub._workspace_lost(MultiCodeError(
        f"MultiCode MCP returned HTTP {status}: session not found", retryable=True))
    assert hub._workspace_lost(MultiCodeError("orchestration_error: project not found"))


@pytest.mark.asyncio
async def test_watch_retry_budget_includes_request_time(monkeypatch):
    original_timeout = asyncio.timeout
    budgets = []

    def short_timeout(seconds):
        budgets.append(seconds)
        return original_timeout(0)  # Expire at the next suspension, without a real 60s wait.

    monkeypatch.setattr(hub.asyncio, "timeout", short_timeout)
    calls = []

    async def handler(request):
        calls.append(request)
        await asyncio.Future()

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
        with pytest.raises(MultiCodeError, match="60 seconds"):
            _ = [event async for event in _backend()._watch(
                _ready_client(transport), "thread", "run", _stream())]
    assert budgets == [60]
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_watch_budget_preserves_last_safe_error(monkeypatch):
    original_timeout = asyncio.timeout
    monkeypatch.setattr(hub.asyncio, "timeout", lambda _: original_timeout(0))
    calls = []

    async def handler(request):
        calls.append(request)
        return httpx.Response(503, text="last failure test-watch-token")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
        with pytest.raises(MultiCodeError, match="503: last failure") as error:
            _ = [event async for event in _backend()._watch(
                _ready_client(transport), "thread", "run", _stream())]
    assert len(calls) == 1
    assert "test-watch-token" not in str(error.value)


@pytest.mark.asyncio
async def test_watch_cancellation_is_not_retried(monkeypatch):
    sleep = AsyncMock()
    monkeypatch.setattr(hub.asyncio, "sleep", sleep)

    async def handler(request):
        raise asyncio.CancelledError

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
        with pytest.raises(asyncio.CancelledError):
            _ = [event async for event in _backend()._watch(
                _ready_client(transport), "thread", "run", _stream())]
    sleep.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [httpx.RemoteProtocolError, 503])
async def test_initial_launch_is_not_retried(failure):
    calls = []

    async def handler(request):
        calls.append(json.loads(request.content))
        if isinstance(failure, int):
            return httpx.Response(failure, text="upstream unavailable")
        raise failure("delivery unknown", request=request)

    state = SimpleNamespace(thread_id="", ws_id="ws", project_id="project", save=Mock())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
        with pytest.raises(MultiCodeError):
            await _backend()._start(_ready_client(transport), state, "do once")
    assert [body["params"]["name"] for body in calls] == ["t3_thread_launch"]
    state.save.assert_not_called()


@pytest.mark.asyncio
async def test_confirmed_missing_thread_can_still_start_replacement(monkeypatch):
    calls = []
    backend = _backend()
    monkeypatch.setattr(backend, "_preamble", lambda: "preamble: ")

    async def handler(request):
        body = json.loads(request.content)
        calls.append(body["params"])
        if body["params"]["name"] == "t3_thread_send":
            return httpx.Response(200, json={"id": body["id"], "error": {
                "code": -32000, "message": "thread not found"}})
        return _result(body, {"threadId": "replacement", "runId": "new-run"})

    state = SimpleNamespace(thread_id="gone", ws_id="ws", project_id="project", save=Mock())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
        assert await backend._start(_ready_client(transport), state, "prompt") == "new-run"
    assert [call["name"] for call in calls] == ["t3_thread_send", "t3_thread_launch"]
    assert calls[1]["arguments"]["message"] == "preamble: prompt"
    assert state.thread_id == "replacement"
    state.save.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [httpx.ReadError, 503])
async def test_uncertain_steer_is_not_queued_for_redelivery(failure):
    calls = []

    async def handler(request):
        calls.append(json.loads(request.content))
        if isinstance(failure, int):
            return httpx.Response(failure, text="upstream unavailable")
        raise failure("delivery unknown", request=request)

    backend = _backend()
    backend._ssh = object()
    backend._state = SimpleNamespace(thread_id="existing")
    backend._run_id = "running"
    backend._turn_active = True
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
        backend._mc = _ready_client(transport)
        with pytest.raises(MultiCodeError):
            await backend.send("steer once")
    assert len(calls) == 1
    assert backend._early_steer == []
