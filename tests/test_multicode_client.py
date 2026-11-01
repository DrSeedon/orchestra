import json

import httpx
import pytest

from app.multicode_client import MultiCodeClient, MultiCodeError, PROTOCOL_VERSION


def test_multicode_run_is_registered_in_orchestra_mcp():
    import app.mcp_stdio as mcp_stdio

    assert any(tool.name == "multicode_run" for tool in mcp_stdio.mcp._tool_manager.list_tools())


def _rpc_response(request_id, result):
    return httpx.Response(200, json={"jsonrpc": "2.0", "id": request_id, "result": result},
                          headers={"content-type": "application/json",
                                   "Mcp-Session-Id": "mock-session"})


@pytest.mark.asyncio
async def test_handshake_run_wait_retry_reads_last_assistant_and_archives(monkeypatch):
    token = "test-bearer-never-display"
    monkeypatch.setenv("MULTICODE_MCP_BASE", "http://hub.local")
    monkeypatch.setenv("MULTICODE_MCP_TOKEN", token)
    client = MultiCodeClient.from_env()
    calls = []
    waits = 0

    async def handler(request):
        nonlocal waits
        body = json.loads(request.content)
        calls.append((body, request.headers))
        assert request.headers["authorization"] == f"Bearer {token}"
        assert request.headers["accept"] == "application/json, text/event-stream"
        if body["method"] == "initialize":
            assert body["params"]["protocolVersion"] == PROTOCOL_VERSION
            return _rpc_response(body["id"], {"protocolVersion": PROTOCOL_VERSION})
        if body["method"] == "notifications/initialized":
            return httpx.Response(202)
        params = body["params"]
        name = params["name"]
        args = params["arguments"]
        if name == "t3_thread_launch":
            assert args["scratch"] is True
            return _rpc_response(body["id"], {"content": [], "structuredContent": {"threadId": "thread-1"}})
        if name == "t3_thread_wait":
            waits += 1
            return _rpc_response(body["id"], {"structuredContent": {"timedOut": waits == 1}})
        if name == "t3_thread_read":
            assert args["view"] == "messages"
            return _rpc_response(body["id"], {"structuredContent": {
                "thread": {}, "recentRuns": [], "items": [
                    {"createdBy": "user", "text": "prompt"},
                    {"createdBy": "agent", "text": "older"},
                    {"createdBy": "agent", "text": f"answer with {token}"},
                ], "nextPosition": None, "hasMore": False,
            }})
        if name == "t3_thread_organize":
            assert args == {"threadId": "thread-1", "action": "archive"}
            return _rpc_response(body["id"], {"structuredContent": {"ok": True}})
        raise AssertionError(name)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
        client._client = transport
        client._owns_client = False
        answer = await client.run("do the task", wait_slice_ms=100, timeout_ms=500)
    assert answer == "answer with [redacted]"
    assert waits == 2
    assert [call[0].get("params", {}).get("name", call[0].get("method")) for call in calls] == [
        "initialize", "notifications/initialized", "t3_thread_launch", "t3_thread_wait",
        "t3_thread_wait", "t3_thread_read", "t3_thread_organize",
    ]
    assert all(token not in repr(call[0]) for call in calls)


@pytest.mark.asyncio
async def test_wait_timeout_is_reported_and_does_not_read_or_archive():
    calls = []

    async def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        if body["method"] == "initialize":
            return _rpc_response(body["id"], {})
        if body["method"] == "notifications/initialized":
            return httpx.Response(202)
        if body["params"]["name"] == "t3_thread_launch":
            return _rpc_response(body["id"], {"structuredContent": {"threadId": "t-2"}})
        return _rpc_response(body["id"], {"structuredContent": {"timedOut": True}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
        client = MultiCodeClient("http://mock", "secret", client=transport)
        with pytest.raises(MultiCodeError, match="timed out"):
            await client.run("prompt", timeout_ms=50, wait_slice_ms=50)
    assert [call.get("params", {}).get("name") for call in calls if call["method"] == "tools/call"] == [
        "t3_thread_launch", "t3_thread_wait",
    ]


@pytest.mark.asyncio
async def test_json_rpc_error_does_not_emit_token():
    token = "private-token-value"

    async def handler(request):
        body = json.loads(request.content)
        if body["method"] == "initialize":
            return _rpc_response(body["id"], {})
        if body["method"] == "notifications/initialized":
            return httpx.Response(202)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"],
                                         "error": {"code": -32000, "message": token}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
        client = MultiCodeClient("http://mock", token, client=transport)
        with pytest.raises(MultiCodeError) as error:
            await client.tool_call("t3_thread_launch", {"title": "x", "message": "y", "scratch": True})
    assert token not in str(error.value)


async def _launch_args(monkeypatch, **kwargs):
    monkeypatch.setenv("MULTICODE_MCP_BASE", "http://hub.local")
    monkeypatch.setenv("MULTICODE_MCP_TOKEN", "secret-token-xyz")
    seen = {}

    async def handler(request):
        body = json.loads(request.content)
        if body["method"] == "initialize":
            return _rpc_response(body["id"], {})
        if body["method"] == "notifications/initialized":
            return httpx.Response(202)
        name = body["params"]["name"]
        if name == "t3_thread_launch":
            seen.update(body["params"]["arguments"])
            return _rpc_response(body["id"], {"structuredContent": {"threadId": "x"}})
        if name == "t3_thread_wait":
            return _rpc_response(body["id"], {"structuredContent": {}})
        if name == "t3_thread_read":
            return _rpc_response(body["id"], {"structuredContent": {"items": [
                {"createdBy": "user", "text": "Reply ... PONG ..."},
                {"createdBy": "agent", "text": "PONG"},
            ]}})
        return _rpc_response(body["id"], {"structuredContent": {}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
        client = MultiCodeClient.from_env()
        client._client = transport
        client._owns_client = False
        await client.run("ping", **kwargs)
    return seen


@pytest.mark.asyncio
async def test_launch_model_selection_defaults(monkeypatch):
    monkeypatch.delenv("MULTICODE_MCP_INSTANCE", raising=False)
    monkeypatch.delenv("MULTICODE_MCP_MODEL", raising=False)
    args = await _launch_args(monkeypatch)
    assert args["modelSelection"] == {"instanceId": "claudeAgent", "model": "claude-sonnet-5-5"}


@pytest.mark.asyncio
async def test_launch_model_selection_env_and_args(monkeypatch):
    monkeypatch.setenv("MULTICODE_MCP_INSTANCE", "grok")
    monkeypatch.setenv("MULTICODE_MCP_MODEL", "grok-4.7")
    assert (await _launch_args(monkeypatch))["modelSelection"] == {
        "instanceId": "grok", "model": "grok-4.7"}
    args = await _launch_args(monkeypatch, instance="codex", model="gpt-6.1-sol", effort="high")
    assert args["modelSelection"] == {
        "instanceId": "codex", "model": "gpt-6.1-sol", "options": {"effort": "high"}}


def test_last_assistant_text_reads_items_created_by_and_content():
    from app.multicode_client import _last_assistant_text

    assert _last_assistant_text({"items": [
        {"createdBy": "agent", "text": "older"},
        {"createdBy": "user", "text": "user reply"},
        {"createdBy": "agent", "content": [
            {"type": "text", "text": "latest "}, {"type": "text", "text": "answer"},
        ]},
    ]}) == "latest answer"


@pytest.mark.asyncio
@pytest.mark.parametrize("status,detail", [
    (400, "Unknown Mcp-Session-Id"),
    (400, "SESSION expired"),
    (400, "Not initialized"),
    (404, "gone"),
])
async def test_long_lived_client_recovers_expired_session_once(status, detail):
    calls = []
    handshakes = 0
    tools = 0

    async def handler(request):
        nonlocal handshakes, tools
        body = json.loads(request.content)
        session = request.headers.get("Mcp-Session-Id")
        calls.append((body, session))
        if body["method"] == "initialize":
            assert session is None
            handshakes += 1
            return httpx.Response(200, json={"id": body["id"], "result": {}},
                                  headers={"Mcp-Session-Id": f"session-{handshakes}"})
        if body["method"] == "notifications/initialized":
            assert session == f"session-{handshakes}"
            return httpx.Response(202)
        tools += 1
        if tools == 2:  # The server forgot the session between two turns of this client.
            assert session == "session-1"
            return httpx.Response(status, text=detail)
        return httpx.Response(200, json={"id": body["id"], "result": {
            "structuredContent": {"ok": True}}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
        client = MultiCodeClient("http://mock", "test-token", client=transport)
        assert await client.tool_call("t3_thread_read", {"threadId": "first"}) == {"ok": True}
        assert await client.tool_call("t3_thread_read", {"threadId": "next"}) == {"ok": True}
        assert client._session_id == "session-2"
        assert client._initialized
    assert [body["method"] for body, _ in calls] == [
        "initialize", "notifications/initialized", "tools/call", "tools/call",
        "initialize", "notifications/initialized", "tools/call"]
    assert calls[3][0] == calls[6][0]  # Same request, including its JSON-RPC id.
    assert calls[6][1] == "session-2"


@pytest.mark.asyncio
@pytest.mark.parametrize("has_session", [False, True])
async def test_plain_http_400_has_redacted_bounded_body_without_retry(has_session):
    token = "bearer-value-for-http-error-test"
    # Include a token crossing the truncation boundary as well as one at the start.
    body = f"invalid arguments: Bearer {token}; " + "x" * 240 + token + "tail" * 100
    calls = []

    async def handler(request):
        calls.append(request)
        return httpx.Response(400, text=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
        client = MultiCodeClient("http://mock", token, client=transport)
        client._initialized = True
        client._session_id = "old" if has_session else None
        with pytest.raises(MultiCodeError) as error:
            await client.tool_call("t3_thread_send", {"message": "once"})
    assert len(calls) == 1
    assert str(error.value) == "MultiCode MCP returned HTTP 400: " + body.replace(token, "[redacted]")[:300]
    assert token not in str(error.value)
    assert "bearer-value" not in str(error.value)
    assert not error.value.retryable


@pytest.mark.asyncio
@pytest.mark.parametrize("second_status,second_body", [
    (400, "session still unknown"), (404, "still gone"),
    (400, "invalid arguments after recovery"), (503, "upstream unavailable"),
])
async def test_second_session_failure_surfaces_without_another_initialize(second_status, second_body):
    calls = []
    token = "test-private-second-failure"

    async def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        if body["method"] == "initialize":
            assert "Mcp-Session-Id" not in request.headers
            return _rpc_response(body["id"], {})
        if body["method"] == "notifications/initialized":
            return httpx.Response(202)
        if len(calls) == 1:
            return httpx.Response(400, text="session expired")
        return httpx.Response(second_status, text=second_body + " " + token)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
        client = MultiCodeClient("http://mock", token, client=transport)
        client._initialized = True
        client._session_id = "stale"
        with pytest.raises(MultiCodeError) as error:
            await client.tool_call("t3_thread_wait", {"threadId": "running"})
        if second_status == 404 or "session" in second_body:
            assert client._session_id is None
            assert not client._initialized
    assert [body["method"] for body in calls] == [
        "tools/call", "initialize", "notifications/initialized", "tools/call"]
    assert calls[0] == calls[3]
    assert str(second_status) in str(error.value)
    assert second_body in str(error.value)
    assert token not in str(error.value)
    assert "[redacted]" in str(error.value)


@pytest.mark.asyncio
async def test_session_400_without_session_header_is_not_retried():
    calls = []

    async def handler(request):
        calls.append(request)
        return httpx.Response(400, text="session not initialized")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
        client = MultiCodeClient("http://mock", "test-token", client=transport)
        with pytest.raises(MultiCodeError, match="session not initialized") as error:
            await client.tool_call("t3_thread_read", {})
    assert len(calls) == 1
    assert not error.value.retryable


@pytest.mark.asyncio
async def test_failed_reinitialize_does_not_recurse():
    calls = []

    async def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        return httpx.Response(400, text="session not initialized")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
        client = MultiCodeClient("http://mock", "test-token", client=transport)
        client._initialized = True
        client._session_id = "stale"
        with pytest.raises(MultiCodeError, match="session not initialized"):
            await client.tool_call("t3_thread_read", {})
    assert [body["method"] for body in calls] == ["tools/call", "initialize"]
