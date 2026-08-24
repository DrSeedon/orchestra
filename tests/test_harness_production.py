"""Production contracts for the in-process OpenRouter Harness."""

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from app.harness.llm import OpenRouterClient
from app.harness.loop import AgentLoop
from app.harness.sessions import SessionStore
from app.backend_harness import HarnessBackend


TOOLS = [{"type": "function", "function": {"name": "read", "parameters": {"type": "object"}}}]


def _client(model="poolside/laguna-s-2.1:free", parameters=("tools", "tool_choice", "reasoning")):
    return OpenRouterClient("test", model, supported_parameters=parameters)


def test_unsuffixed_zero_price_preview_is_rejected_before_a_request_is_built():
    client = _client(model="stealth/ox-alpha")

    with pytest.raises(ValueError, match=":free"):
        client._build_body([{"role": "user", "content": "hi"}], TOOLS)


@pytest.mark.asyncio
async def test_backend_never_uses_anthropic_credentials_for_openrouter(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-cross-provider-boundary")
    backend = HarnessBackend("z-ai/glm-5.2:free", str(tmp_path))

    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        await backend.connect()


def test_request_parameters_follow_exact_model_capabilities():
    inkling = _client(
        model="thinkingmachines/inkling-small:free",
        parameters=("tools", "reasoning", "reasoning_effort"),
    )
    body = inkling._build_body([{"role": "user", "content": "fix"}], TOOLS, effort="high")
    assert body["tools"] == TOOLS
    assert body["reasoning"] == {"effort": "high"}
    assert "tool_choice" not in body
    assert "parallel_tool_calls" not in body

    laguna = _client()
    body = laguna._build_body([{"role": "user", "content": "fix"}], TOOLS, effort="high")
    assert body["tool_choice"] == "auto"
    assert "parallel_tool_calls" not in body


def test_tools_are_rejected_locally_when_model_does_not_advertise_them():
    client = _client(parameters=("reasoning",))

    with pytest.raises(ValueError, match="does not support tools"):
        client._build_body([{"role": "user", "content": "hi"}], TOOLS)


@pytest.mark.asyncio
async def test_stream_error_event_is_not_reported_as_a_success():
    payload = b'data: {"error":{"code":429,"message":"provider overloaded"}}\n\ndata: [DONE]\n\n'

    def handler(request):
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=payload)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = OpenRouterClient(
        "test", "poolside/laguna-s-2.1:free",
        supported_parameters=("tools", "tool_choice"), http=http,
    )
    with pytest.raises(RuntimeError, match="provider overloaded"):
        async for _ in client.stream([{"role": "user", "content": "hi"}], []):
            pass
    await http.aclose()


@pytest.mark.asyncio
async def test_empty_completion_is_a_loud_failure():
    payload = b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'

    def handler(request):
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=payload)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = OpenRouterClient(
        "test", "poolside/laguna-s-2.1:free",
        supported_parameters=("tools", "tool_choice"), http=http,
    )
    with pytest.raises(RuntimeError, match="empty completion"):
        async for _ in client.stream([{"role": "user", "content": "hi"}], []):
            pass
    await http.aclose()


@pytest.mark.asyncio
async def test_nonzero_provider_cost_blocks_the_round_before_tools_can_run():
    payload = (
        b'data: {"choices":[{"delta":{"content":"answer"}}]}\n\n'
        b'data: {"choices":[],"usage":{"prompt_tokens":1,"completion_tokens":1,"cost":0.01}}\n\n'
        b'data: [DONE]\n\n'
    )

    def handler(request):
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=payload)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = OpenRouterClient(
        "test", "poolside/laguna-s-2.1:free",
        supported_parameters=("tools", "tool_choice"), http=http,
    )
    with pytest.raises(RuntimeError, match="zero-spend contract"):
        async for _ in client.stream([{"role": "user", "content": "hi"}], []):
            pass
    await http.aclose()


def test_invalid_sse_json_is_a_loud_protocol_failure():
    from app.harness.llm import _parse_sse

    with pytest.raises(RuntimeError, match="invalid OpenRouter SSE JSON"):
        _parse_sse("data: {broken")


class _NoMCP:
    def has_tool(self, name):
        return False

    async def call(self, name, args):
        return "[noop]"


def test_context_fit_keeps_user_instructions_and_complete_tool_rounds():
    history = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "original task"},
    ]
    for i in range(12):
        history.extend([
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": f"call-{i}", "type": "function",
                    "function": {"name": "read", "arguments": "{}"},
                }],
            },
            {"role": "tool", "tool_call_id": f"call-{i}", "content": "x" * 4000},
        ])
    history.append({"role": "user", "content": "steering correction"})
    loop = AgentLoop(None, _NoMCP(), "/tmp", history, [], max_context=8000)

    assert loop._fit_context() is True
    assert [m["content"] for m in history if m["role"] == "user"] == [
        "original task", "steering correction",
    ]
    assistant_ids = {
        tc["id"]
        for m in history if m["role"] == "assistant"
        for tc in m.get("tool_calls", [])
    }
    assert assistant_ids
    assert {m["tool_call_id"] for m in history if m["role"] == "tool"} == assistant_ids


def test_session_store_replace_is_atomic_snapshot_and_append_stays_valid(tmp_path):
    async def scenario():
        store = SessionStore(str(tmp_path), session_id="s")
        await store.append_messages([
            {"role": "user", "content": "old"},
            {"role": "assistant", "content": "old answer"},
        ])
        await store.replace_messages([{"role": "user", "content": "compacted"}])
        await store.append({"role": "assistant", "content": "new answer"})
        await store.close()
        return store.load()

    assert asyncio.run(scenario()) == [
        {"role": "user", "content": "compacted"},
        {"role": "assistant", "content": "new answer"},
    ]
    for line in (tmp_path / "s.jsonl").read_text().splitlines():
        assert isinstance(json.loads(line), dict)


def test_session_store_rejects_corruption_before_the_trailing_line(tmp_path):
    path = tmp_path / "broken.jsonl"
    path.write_text(
        '{"role":"user","content":"ok"}\n'
        '{broken}\n'
        '{"role":"assistant","content":"must not be silently accepted"}\n'
    )
    store = SessionStore(str(tmp_path), session_id="broken")

    with pytest.raises(RuntimeError, match="line 2"):
        store.load()


@pytest.mark.asyncio
async def test_backend_persists_compacted_history_as_snapshot_not_append():
    calls = []

    class Store:
        async def append_messages(self, messages):
            calls.append(("append", list(messages)))

        async def replace_messages(self, messages):
            calls.append(("replace", list(messages)))

    backend = HarnessBackend("z-ai/glm-5.2:free", "/tmp")
    backend._store = Store()
    backend._history = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "kept"},
    ]
    loop = SimpleNamespace(truncated_dropped=4, new_messages=[{"role": "user", "content": "kept"}])

    await backend._persist_loop(loop)

    assert calls == [("replace", backend._history)]


@pytest.mark.asyncio
async def test_mcp_invalid_json_fails_pending_request_with_the_real_reason():
    from app.harness.mcp import _Server

    class Stdout:
        async def readline(self):
            return b"{broken json}\n"

    server = _Server("broken", {"command": "unused"})
    server.proc = SimpleNamespace(stdout=Stdout())
    server._alive = True
    pending = asyncio.get_running_loop().create_future()
    server._pending[1] = pending

    await server._read_loop()

    with pytest.raises(ConnectionError, match="invalid JSON"):
        await pending
