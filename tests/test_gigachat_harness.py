"""Core GigaChat transport contracts; all HTTP is mocked."""

import json

import httpx
import pytest

from app.harness.llm import (
    GigaChatClient,
    functions_to_openai_tools,
    openai_messages_to_gigachat,
    tools_to_gigachat_functions,
)
from app.models import backend_for_model, get_model_spec, resolve_model


TOOLS = [{
    "type": "function",
    "function": {
        "name": "read",
        "description": "Read a file",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
    },
}]


def test_function_schema_translation_is_bidirectional():
    functions = tools_to_gigachat_functions(TOOLS)
    assert functions == [TOOLS[0]["function"]]
    assert functions_to_openai_tools(functions) == TOOLS


def test_gigachat_models_are_registered_as_harness_routes():
    assert backend_for_model("GigaChat-2") == "harness"
    assert get_model_spec(resolve_model("gigachat")).provider == "gigachat"


def test_history_translation_keeps_function_arguments_and_result():
    messages = [
        {"role": "system", "content": "You are an agent"},
        {"role": "user", "content": "read this"},
        {"role": "assistant", "content": None, "tool_calls": [{
            "id": "call-1", "type": "function",
            "function": {"name": "read", "arguments": '{"path":"a.txt"}'},
        }]},
        {"role": "tool", "tool_call_id": "call-1", "content": "contents"},
    ]
    assert openai_messages_to_gigachat(messages)[-2:] == [
        {"role": "assistant", "content": "", "function_call": {
            "name": "read", "arguments": {"path": "a.txt"},
        }},
        {"role": "function", "name": "read", "content": '"contents"'},
    ]


@pytest.mark.asyncio
async def test_token_is_refreshed_after_expiry_and_401(monkeypatch):
    monkeypatch.setenv("GIGACHAT_SCOPE", "GIGACHAT_API_PERS")
    monkeypatch.setenv("GIGACHAT_AUTH_KEY", "encoded-test-key")
    calls: list[tuple[str, str]] = []
    oauth_count = 0
    chat_count = 0

    def handler(request):
        nonlocal oauth_count, chat_count
        calls.append((request.url.host, request.url.path))
        if request.url.path.endswith("/oauth"):
            oauth_count += 1
            return httpx.Response(200, json={"access_token": f"token-{oauth_count}", "expires_in": 1800})
        chat_count += 1
        if chat_count == 1:
            return httpx.Response(401, json={"error": "expired"})
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 1},
        })

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = GigaChatClient(
        "GigaChat-2", http=http,
        auth_url="https://testserver/api/v2/oauth",
        chat_url="https://testserver/v1/chat/completions",
    )
    events = [event async for event in client.stream(
        [{"role": "user", "content": "hello"}], TOOLS)]
    assert [event.kind for event in events] == ["text_delta", "final"]
    assert oauth_count == 2 and chat_count == 2
    assert calls == [
        ("testserver", "/api/v2/oauth"),
        ("testserver", "/v1/chat/completions"),
        ("testserver", "/api/v2/oauth"),
        ("testserver", "/v1/chat/completions"),
    ]
    client._token_expires_at = 0
    [event async for event in client.stream([{"role": "user", "content": "again"}], [])]
    assert oauth_count == 3
    await http.aclose()


@pytest.mark.asyncio
async def test_provider_error_is_loud(monkeypatch):
    import app.harness.llm as llm_module

    monkeypatch.setattr(llm_module, "BACKOFF_BASE", 0.0)
    monkeypatch.setattr(llm_module.random, "uniform", lambda a, b: 0.0)
    monkeypatch.setenv("GIGACHAT_SCOPE", "scope")
    monkeypatch.setenv("GIGACHAT_AUTH_KEY", "key")

    def handler(request):
        if request.url.path.endswith("/oauth"):
            return httpx.Response(200, json={"access_token": "token", "expires_in": 1800})
        return httpx.Response(500, json={"error": {"message": "provider down"}})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = GigaChatClient(
        "GigaChat-2", http=http,
        auth_url="https://testserver/api/v2/oauth",
        chat_url="https://testserver/v1/chat/completions",
    )
    with pytest.raises(RuntimeError, match="provider down"):
        async for _ in client.stream([{"role": "user", "content": "hello"}], []):
            pass
    await http.aclose()


@pytest.mark.asyncio
async def test_chat_request_uses_functions_schema_not_openai_tools(monkeypatch):
    # GigaChat answers OpenAI `tools`/`tool_choice` with HTTP 200 plain text and never calls
    # the tool (probe 17.09.2026) — only the actual wire body can catch that regression.
    monkeypatch.setenv("GIGACHAT_SCOPE", "scope")
    monkeypatch.setenv("GIGACHAT_AUTH_KEY", "key")
    bodies: list[dict] = []

    def handler(request):
        if request.url.path.endswith("/oauth"):
            return httpx.Response(200, json={"access_token": "token", "expires_in": 1800})
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{
            "message": {"role": "assistant", "content": "",
                        "function_call": {"name": "read", "arguments": {"path": "a.txt"}}},
            "finish_reason": "function_call",
        }]})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = GigaChatClient(
        "GigaChat-2", http=http,
        auth_url="https://testserver/api/v2/oauth",
        chat_url="https://testserver/v1/chat/completions",
    )
    events = [event async for event in client.stream(
        [{"role": "user", "content": "read a.txt"}], TOOLS)]
    await http.aclose()

    [body] = bodies
    assert body["functions"] == [TOOLS[0]["function"]]
    assert body["function_call"] == "auto"
    assert "tools" not in body and "tool_choice" not in body
    assert [event.kind for event in events] == ["tool_call_done", "final"]
    assert events[0].tool_name == "read"
    assert json.loads(events[0].arguments) == {"path": "a.txt"}
    assert events[1].finish_reason == "tool_calls"


def _gigachat_rejections(schema, path="parameters") -> list[str]:
    """Shapes GigaChat answered 422 to on 24.09.2026 (V-636); one rejects the whole request."""
    problems = []
    if isinstance(schema, list):
        for item in schema:
            problems += _gigachat_rejections(item, path)
        return problems
    if not isinstance(schema, dict):
        return problems
    if isinstance(schema.get("type"), list):
        problems.append(f"{path}: type list {schema['type']}")
    for key in ("anyOf", "oneOf"):
        if any(isinstance(v, dict) and v.get("type") == "null" for v in schema.get(key) or []):
            problems.append(f"{path}: nullable {key}")
    if schema.get("type") == "object" and not isinstance(schema.get("properties"), dict):
        problems.append(f"{path}: object without properties")
    for key, value in schema.items():
        problems += _gigachat_rejections(value, f"{path}.{key}")
    return problems


def test_nullable_and_free_form_arguments_become_gigachat_valid():
    functions = tools_to_gigachat_functions([{"type": "function", "function": {
        "name": "spawn_worker",
        "parameters": {"type": "object", "properties": {
            "disabled_tools": {"anyOf": [{"type": "array", "items": {"type": "string"}},
                                         {"type": "null"}], "default": None},
            "ttl_seconds": {"type": ["integer", "null"]},
            "data": {"type": "object", "additionalProperties": True},
        }, "required": ["data"]},
    }}])
    params = functions[0]["parameters"]
    assert _gigachat_rejections(params) == []
    assert params["properties"]["disabled_tools"] == {"type": "array", "items": {"type": "string"}}
    assert params["properties"]["ttl_seconds"] == {"type": "integer"}
    assert params["required"] == ["data"]


def test_every_orchestra_mcp_tool_is_accepted_by_gigachat():
    """One nullable argument in any Orchestra tool made EVERY GigaChat turn fail with 422."""
    import app.mcp_stdio as mcp_stdio

    tools = [{"type": "function", "function": {
        "name": tool.name, "description": tool.description or "", "parameters": tool.parameters,
    }} for tool in mcp_stdio.mcp._tool_manager.list_tools()]
    assert len(tools) > 20
    problems = [f"{fn['name']}: {problem}"
                for fn in tools_to_gigachat_functions(tools)
                for problem in _gigachat_rejections(fn["parameters"])]
    assert problems == []


@pytest.mark.asyncio
async def test_functions_state_id_survives_the_round_trip(monkeypatch):
    """Without functions_state_id on the replayed call GigaChat-2-Max repeated the same call
    for a whole turn (V-636). The text beside the call imitates a different call and is dropped."""
    monkeypatch.setenv("GIGACHAT_SCOPE", "scope")
    monkeypatch.setenv("GIGACHAT_AUTH_KEY", "key")

    def handler(request):
        if request.url.path.endswith("/oauth"):
            return httpx.Response(200, json={"access_token": "token", "expires_in": 1800})
        return httpx.Response(200, json={"choices": [{
            "message": {"role": "assistant", "content": "write path=a.txt",
                        "functions_state_id": "01a0d454-6cf2-7a0e-ac52-bb9e4f3e5e27",
                        "function_call": {"name": "read", "arguments": {"path": "a.txt"}}},
            "finish_reason": "function_call",
        }]})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = GigaChatClient("GigaChat-2-Max", http=http, auth_url="https://testserver/api/v2/oauth",
                            chat_url="https://testserver/v1/chat/completions")
    events = [event async for event in client.stream([{"role": "user", "content": "x"}], TOOLS)]
    await http.aclose()
    assert [event.kind for event in events] == ["tool_call_done", "final"]
    call = events[0]
    history = [
        {"role": "assistant", "content": None, "tool_calls": [{
            "id": call.tool_id, "type": "function",
            "function": {"name": call.tool_name, "arguments": call.arguments}}]},
        {"role": "tool", "tool_call_id": call.tool_id, "content": "hello"},
    ]
    assistant, result = openai_messages_to_gigachat(history)
    assert assistant["functions_state_id"] == "01a0d454-6cf2-7a0e-ac52-bb9e4f3e5e27"
    assert result["name"] == "read"


def test_double_escaped_and_fenced_file_content_is_repaired():
    from app.harness.llm import _repair_file_arguments

    code = "def f():\n    return 1\n\nprint(f())"
    fixed = _repair_file_arguments("write", {"path": "a.py", "content": "```python\n" + code + "\n```"})
    assert fixed["content"] == "def f():\n    return 1\n\nprint(f())\n"
    one_liner = 'print("a\\nb")'
    assert _repair_file_arguments("write", {"path": "a.py", "content": one_liner})["content"] == one_liner
    readme = "```\nexample\n```\n"
    assert _repair_file_arguments("write", {"path": "README.md", "content": readme})["content"] == readme
    edit = _repair_file_arguments("edit", {"path": "a.py", "old": "a\\nb\\nc", "new": "x"})
    assert edit["old"] == "a\nb\nc"
    escaped = 'names = [\\"MIT\\", \\"BSD\\"]\nprint(f\\"{names}\\")\n'
    assert _repair_file_arguments("write", {"path": "a.py", "content": escaped})["content"] == (
        'names = ["MIT", "BSD"]\nprint(f"{names}")\n')
    valid = 'print("say \\"hi\\"")\n'
    assert _repair_file_arguments("write", {"path": "a.py", "content": valid})["content"] == valid
    # Stand, V-636: one line of literal \n in a fence, then stray JSON with a real line break.
    stray = "```python\\nx = {\\\\n    'MIT'\\n}\\nprint(x)\\n```\",\n    "
    assert _repair_file_arguments("write", {"path": "a.py", "content": stray})["content"] == (
        "x = {\\\n    'MIT'\n}\nprint(x)\n")


@pytest.mark.asyncio
async def test_dropped_connection_is_retried_not_a_failed_turn(monkeypatch):
    """V-636: a single empty httpx transport error ended the user's turn with a bare
    "llm round failed:"; the request must be retried instead."""
    import app.harness.llm as llm_module

    monkeypatch.setenv("GIGACHAT_SCOPE", "scope")
    monkeypatch.setenv("GIGACHAT_AUTH_KEY", "key")
    monkeypatch.setattr(llm_module, "BACKOFF_BASE", 0.0)
    monkeypatch.setattr(llm_module.random, "uniform", lambda a, b: 0.0)
    calls = {"chat": 0}

    def handler(request):
        if request.url.path.endswith("/oauth"):
            return httpx.Response(200, json={"access_token": "token", "expires_in": 1800})
        calls["chat"] += 1
        if calls["chat"] == 1:
            raise httpx.RemoteProtocolError("")
        if calls["chat"] == 2:
            return httpx.Response(503, json={"message": "busy"})
        return httpx.Response(200, json={"choices": [{
            "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}]})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = GigaChatClient("GigaChat-2-Max", http=http, auth_url="https://testserver/api/v2/oauth",
                            chat_url="https://testserver/v1/chat/completions")
    events = [event async for event in client.stream([{"role": "user", "content": "x"}], TOOLS)]
    await http.aclose()
    assert calls["chat"] == 3
    assert [event.kind for event in events] == ["text_delta", "final"]


def test_harness_does_not_offer_tools_its_policy_refuses():
    """V-636: disabled Orchestra tools stayed in the function list; GigaChat kept calling
    them (tool_disabled) and never reached bash/glob."""
    from app.backend_harness import HarnessBackend

    def schema(name):
        return {"type": "function", "function": {"name": name, "parameters": {"type": "object", "properties": {}}}}

    backend = HarnessBackend("GigaChat-2-Max", "/tmp", mcp_servers={"orchestra": {
        "command": "x", "env": {"ORCHESTRA_DISABLED_TOOLS": '["merge_worker", "send_chart"]'}}})

    class FakeMCP:
        def tool_schemas(self):
            return [schema("spawn_worker"), schema("merge_worker"), schema("send_chart")]

    backend._mcp = FakeMCP()
    assert [s["function"]["name"] for s in backend._offered_mcp_schemas()] == ["spawn_worker"]


def test_policy_naming_review_switches_off_the_reviewer_tool():
    from app.backend_harness import HarnessBackend

    def offered(disabled):
        backend = HarnessBackend("GigaChat-2-Max", "/tmp", mcp_servers={"orchestra": {
            "command": "x", "env": {"ORCHESTRA_DISABLED_TOOLS": disabled}}})
        backend._tool_schemas = []
        return [s["function"]["name"] for s in backend._turn_tool_schemas("medium")]

    assert offered("[]") == ["review"]
    assert offered('["review"]') == []


def test_spawn_worker_schema_marks_model_required():
    """The server refuses spawn_worker without model; a schema calling it optional made
    GigaChat omit it and retry the refused call for the whole turn (V-636)."""
    import app.mcp_stdio as mcp_stdio

    [tool] = [t for t in mcp_stdio.mcp._tool_manager.list_tools() if t.name == "spawn_worker"]
    assert "model" in tool.parameters["required"]


@pytest.mark.asyncio
async def test_concurrent_agents_send_one_gigachat_request_at_a_time(monkeypatch):
    """V-636: orchestrator and worker asked GigaChat together, got 429 until retries ran out."""
    import asyncio

    monkeypatch.setenv("GIGACHAT_SCOPE", "scope")
    monkeypatch.setenv("GIGACHAT_AUTH_KEY", "key")
    state = {"now": 0, "peak": 0}

    async def handler(request):
        if request.url.path.endswith("/oauth"):
            return httpx.Response(200, json={"access_token": "token", "expires_in": 1800})
        state["now"] += 1
        state["peak"] = max(state["peak"], state["now"])
        await asyncio.sleep(0.05)
        state["now"] -= 1
        return httpx.Response(200, json={"choices": [{
            "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}]})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def one_turn():
        client = GigaChatClient("GigaChat-2-Max", http=http,
                                auth_url="https://testserver/api/v2/oauth",
                                chat_url="https://testserver/v1/chat/completions")
        return [event.kind async for event in client.stream([{"role": "user", "content": "x"}], TOOLS)]

    results = await asyncio.gather(one_turn(), one_turn(), one_turn())
    await http.aclose()
    assert results == [["text_delta", "final"]] * 3
    assert state["peak"] == 1


def test_gigachat_3_ultra_is_a_selectable_harness_model():
    """The stand needs the strongest GigaChat; an unknown GigaChat id must still be refused."""
    import dataclasses
    from app.models import MODEL_SPECS, resolve_model, validate_harness_model_spec

    assert resolve_model("gigachat-3-ultra") == "GigaChat-3-Ultra"
    spec = MODEL_SPECS["GigaChat-3-Ultra"]
    validate_harness_model_spec(spec)
    with pytest.raises(ValueError):
        validate_harness_model_spec(dataclasses.replace(spec, id="GigaChat-9-Imaginary"))


@pytest.mark.parametrize("model_id", [
    "GigaChat-2", "GigaChat-2-Pro", "GigaChat-2-Max",
    "GigaChat-3-Lightning", "GigaChat-3-Pro", "GigaChat-3-Ultra",
])
def test_every_gigachat_api_chat_model_is_selectable(model_id):
    """The expert's stand offers every GigaChat chat model the API serves (owner, 25.09)."""
    from app.models import MODEL_SPECS, validate_harness_model_spec

    validate_harness_model_spec(MODEL_SPECS[model_id])
