"""Tests for the two-contour $0 Free Worker Pool (Local Contabo llama-server + Cloud Free Cascade)."""

from __future__ import annotations

import json
import os
import pytest
import httpx

from app.harness.free_pool import (
    CLOUD_FREE_PROVIDERS,
    FREE_ROUTER_MODEL_ID,
    LOCAL_HERETIC_MODEL_ID,
    CloudOpenAIClient,
    FreeWorkerRouter,
    LocalLlamaClient,
    clear_route_cooldowns,
    create_free_pool_llm_client,
    is_private_conversation,
    is_route_cooled_down,
    mark_route_cooldown,
    upstream_model_name,
)
from app.models import (
    FREE_POOL_MODEL_IDS,
    ensure_spawn_allowed,
    get_model_flags,
    get_model_spec,
    resolve_model,
    validate_harness_model_spec,
)


@pytest.fixture(autouse=True)
def _clean_cooldowns():
    clear_route_cooldowns()
    yield
    clear_route_cooldowns()


def test_free_pool_aliases_and_resolution():
    assert resolve_model("local") == LOCAL_HERETIC_MODEL_ID
    assert resolve_model("local-heretic") == LOCAL_HERETIC_MODEL_ID
    assert resolve_model("heretic") == LOCAL_HERETIC_MODEL_ID
    assert resolve_model("free-local") == LOCAL_HERETIC_MODEL_ID
    assert resolve_model("local-35b") == LOCAL_HERETIC_MODEL_ID

    assert resolve_model("free") == FREE_ROUTER_MODEL_ID
    assert resolve_model("free-auto") == FREE_ROUTER_MODEL_ID
    assert resolve_model("free-router") == FREE_ROUTER_MODEL_ID
    assert resolve_model("free-pool") == FREE_ROUTER_MODEL_ID

    assert resolve_model("cerebras") == "cerebras/qwen-3-32b:free"
    assert resolve_model("cerebras-llama") == "cerebras/llama-3.3-70b:free"
    assert resolve_model("groq") == "groq/llama-3.3-70b-versatile:free"
    assert resolve_model("groq-qwen") == "groq/qwen-qwq-32b:free"
    assert resolve_model("aistudio") == "aistudio/gemini-2.5-flash:free"
    assert resolve_model("codestral") == "mistral/codestral-latest:free"


def test_free_pool_model_flags_and_spawn_admission(monkeypatch):
    # Local Heretic is explicitly blocked by owner decision (09.11.2026)
    heretic_spec = get_model_spec(LOCAL_HERETIC_MODEL_ID)
    assert get_model_flags(LOCAL_HERETIC_MODEL_ID) == {"dashboard": False, "agents": False}
    for alias in (LOCAL_HERETIC_MODEL_ID, "local", "heretic", "local-heretic", "free-local", "local-35b"):
        with pytest.raises(ValueError, match="отключено решением владельца"):
            ensure_spawn_allowed(resolve_model(alias))
    with pytest.raises(ValueError, match="отключено решением владельца"):
        validate_harness_model_spec(heretic_spec)
    with pytest.raises(ValueError, match="отключено решением владельца"):
        create_free_pool_llm_client(LOCAL_HERETIC_MODEL_ID)

    # Free Router remains admitted
    for mid in (FREE_ROUTER_MODEL_ID,):
        assert mid in FREE_POOL_MODEL_IDS
        spec = get_model_spec(mid)
        validate_harness_model_spec(spec)
        flags = get_model_flags(mid)
        assert spec.runtime == "harness"
        assert spec.context_length == 131072
        assert spec.price_input == spec.price_output == 0.0
        assert flags["agents"] is True
        ensure_spawn_allowed(mid)

    # Direct cloud free routes require their respective env key for availability
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(ValueError, match="GROQ_API_KEY"):
        validate_harness_model_spec(get_model_spec("groq/llama-3.3-70b-versatile:free"))
    with pytest.raises(ValueError, match="GROQ_API_KEY"):
        ensure_spawn_allowed("groq/llama-3.3-70b-versatile:free")

    monkeypatch.setenv("GROQ_API_KEY", "gsk_test_free_key")
    validate_harness_model_spec(get_model_spec("groq/llama-3.3-70b-versatile:free"))
    ensure_spawn_allowed("groq/llama-3.3-70b-versatile:free")


def test_upstream_model_name_parsing():
    assert upstream_model_name(LOCAL_HERETIC_MODEL_ID) == ("local", "qwen3.5-35b-a3b-heretic")
    assert upstream_model_name(FREE_ROUTER_MODEL_ID) == ("free", "auto")
    assert upstream_model_name("cerebras/qwen-3-32b:free") == ("cerebras", "qwen-3-32b")
    assert upstream_model_name("groq/llama-3.3-70b-versatile:free") == ("groq", "llama-3.3-70b-versatile")
    assert upstream_model_name("mistral/codestral-latest:free") == ("mistral", "codestral-latest")
    assert upstream_model_name("aistudio/gemini-2.5-flash:free") == ("aistudio", "gemini-2.5-flash")
    assert upstream_model_name("nvidia/nemotron-3-ultra-550b-a55b:free") == (
        "openrouter",
        "nvidia/nemotron-3-ultra-550b-a55b:free",
    )


def test_local_llama_client_builds_expected_body():
    client = LocalLlamaClient(LOCAL_HERETIC_MODEL_ID)
    tools = [{"type": "function", "function": {"name": "read_file", "parameters": {"type": "object"}}}]
    body_default = client._build_body([{"role": "user", "content": "hi"}], tools, effort="medium")
    assert body_default["model"] == "qwen3.5-35b-a3b-heretic"
    assert body_default["stream"] is True
    assert body_default["stream_options"] == {"include_usage": True}
    assert body_default["tools"] == tools
    assert body_default["tool_choice"] == "auto"
    assert body_default["chat_template_kwargs"] == {"enable_thinking": False}

    body_high = client._build_body([{"role": "user", "content": "hi"}], [], effort="high")
    assert body_high["chat_template_kwargs"] == {"enable_thinking": False}


def test_private_conversation_detection_routes_strictly_to_local(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    monkeypatch.setenv("CEREBRAS_API_KEY", "csk_test")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")

    private_msgs = [
        {"role": "system", "content": "You are a worker."},
        {"role": "user", "content": "Проверь статус акта в Диадок и 1С по СберБизнесу."},
    ]
    assert is_private_conversation(private_msgs) is True

    dnd_msgs = [{"role": "user", "content": "Сгенерируй сцену D&D для бота Кеша (heretic uncensored)."}]
    assert is_private_conversation(dnd_msgs) is True

    general_msgs = [{"role": "user", "content": "Write a Python unit test for string sorting."}]
    assert is_private_conversation(general_msgs) is False

    router = FreeWorkerRouter()
    priv_candidates = router.build_candidates(private_msgs, [])
    assert LOCAL_HERETIC_MODEL_ID not in [cid for cid, _ in priv_candidates]

    gen_candidates = router.build_candidates(general_msgs, [])
    gen_ids = [cid for cid, _ in gen_candidates]
    assert "cerebras/qwen-3-32b:free" in gen_ids
    assert "groq/llama-3.3-70b-versatile:free" in gen_ids
    assert LOCAL_HERETIC_MODEL_ID not in gen_ids


@pytest.mark.asyncio
async def test_free_worker_router_cascades_on_429_to_next_cloud_provider(monkeypatch):
    from app import openrouter_counter

    def no_openrouter_attempt():
        pytest.fail("Direct Cerebras/Groq inference must not consume OpenRouter quota")

    monkeypatch.setattr(openrouter_counter, "record_attempt_start", no_openrouter_attempt)
    monkeypatch.setenv("CEREBRAS_API_KEY", "csk_test")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    monkeypatch.delenv("CODESTRAL_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_KEY", raising=False)

    called_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        called_urls.append(url)
        if "api.cerebras.ai" in url:
            return httpx.Response(429, json={"error": {"message": "Rate limit reached"}})
        sse_payload = (
            'data: {"choices":[{"delta":{"content":"Fallback OK"},"finish_reason":null}]}\n\n'
            'data: {"choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":10,"completion_tokens":3}}\n\n'
            "data: [DONE]\n\n"
        )
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=sse_payload.encode("utf-8"),
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        router = FreeWorkerRouter(http=http_client)
        events = []
        async for ev in router.stream(
            [{"role": "user", "content": "Run a general check"}],
            tools=[],
        ):
            events.append(ev)

    assert any("api.cerebras.ai" in u for u in called_urls)
    assert any("api.groq.com" in u for u in called_urls)
    assert not any("127.0.0.1:8091" in u for u in called_urls)
    assert is_route_cooled_down("cerebras/qwen-3-32b:free") is True
    assert router.last_routed_model == "groq/llama-3.3-70b-versatile:free"
    text_events = [e.text for e in events if e.kind == "text_delta"]
    assert "".join(text_events) == "Fallback OK"
    final_events = [e for e in events if e.kind == "final"]
    assert len(final_events) == 1
    assert final_events[0].usage.get("routed_model") == "groq/llama-3.3-70b-versatile:free"



@pytest.mark.asyncio
async def test_heretic_blocked_across_all_aliases_and_backend():
    from app.models import ensure_dashboard_visible, ensure_spawn_allowed, resolve_model
    from app.backend_harness import HarnessBackend

    for alias in (
        "local",
        "local-heretic",
        "heretic",
        "free-local",
        "local-35b",
        "qwen3.5-35b-a3b-heretic",
        "qwen3.5-35b-a3b",
        "local/qwen3.5-35b-a3b-heretic:free",
    ):
        resolved = resolve_model(alias)
        assert resolved == "local/qwen3.5-35b-a3b-heretic:free"
        with pytest.raises(ValueError, match="отключено решением владельца"):
            ensure_spawn_allowed(resolved)
        with pytest.raises(ValueError, match="отключено решением владельца"):
            ensure_dashboard_visible(resolved)

    backend = HarnessBackend(model="local/qwen3.5-35b-a3b-heretic:free", cwd="/tmp")
    with pytest.raises(ValueError, match="отключено решением владельца"):
        await backend.connect()
    backend._llm = object()
    with pytest.raises(ValueError, match="отключено решением владельца"):
        await backend.send("hello")
