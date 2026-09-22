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
