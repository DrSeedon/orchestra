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
            return _rpc_response(body["id"], {"structuredContent": {"messages": [
                {"role": "user", "text": "prompt"},
                {"role": "assistant", "text": "older"},
                {"role": "assistant", "text": f"answer with {token}"},
            ]}})
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
