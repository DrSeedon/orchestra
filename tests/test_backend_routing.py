"""Task #96 Phase 2 — backend routing: non-Claude/non-GPT models → opencode."""

import pytest

from app.models import (
    ALIASES,
    BACKENDS,
    CONTEXT_LIMITS,
    MODELS,
    TOKEN_PRICES,
    ModelSpec,
    _infer_backend,
    available_models_block,
    backend_for_model,
    cache_policy_for_runtime,
    fetch_models_from_proxy,
    get_model_spec,
    register_model,
    resolve_model,
    unregister_model,
)
from app.backend_opencode import OpenCodeBackend


# ── _infer_backend prefix routing ──

def test_infer_gpt_to_codex():
    assert _infer_backend("gpt-5.5") == "codex"
    assert _infer_backend("gpt-5.4-mini") == "codex"


def test_spark_is_registered_for_codex_workers():
    model_id = "gpt-5.3-codex-spark"
    assert MODELS[model_id] == "GPT-5.3 Codex Spark"
    assert CONTEXT_LIMITS[model_id] == 128000
    assert BACKENDS[model_id] == "codex"
    assert ALIASES["spark"] == model_id
    assert backend_for_model(model_id) == "codex"
    assert "`gpt-5.3-codex-spark` — GPT-5.3 Codex Spark, 128k context" in available_models_block()


def test_infer_claude_to_claude():
    assert _infer_backend("claude-sonnet-5[1m]") == "claude"
    assert _infer_backend("claude-opus-5[1m]") == "claude"
    assert _infer_backend("claude-opus-4-8[1m]") == "claude"


def test_opus5_registry_and_aliases():
    model_id = "claude-opus-5[1m]"
    spec = get_model_spec(model_id)

    assert MODELS[model_id] == "Opus 5 (1M)"
    assert spec.runtime == "claude"
    assert spec.provider == "anthropic"
    assert spec.context_length == 1_000_000
    assert TOKEN_PRICES[model_id] == {"input": 5.0, "output": 25.0}
    assert resolve_model("opus") == model_id
    assert resolve_model("opus5") == model_id
    assert resolve_model("claude-opus-5") == model_id
    # retired Opus 4.6/4.8 ids remap to Opus 5 — old sessions keep resolving
    assert resolve_model("claude-opus-4-8[1m]") == model_id
    assert resolve_model("claude-opus-4-6") == model_id
    assert "claude-opus-4-8[1m]" not in MODELS


def test_infer_others_to_opencode():
    assert _infer_backend("deepseek/deepseek-v4-flash") == "opencode"
    assert _infer_backend("gemini-2.5-flash") == "opencode"
    assert _infer_backend("meta-llama/llama-4") == "opencode"
    assert _infer_backend("mistral-large") == "opencode"
    assert _infer_backend("qwen/qwen-3") == "opencode"


# ── backend_for_model: registered wins, unregistered infers ──

def test_backend_for_model_registered_wins():
    # claude-sonnet-5[1m] is in the hardcoded BACKENDS dict
    assert "claude-sonnet-5[1m]" in BACKENDS
    assert backend_for_model("claude-sonnet-5[1m]") == "claude"


def test_backend_for_model_unregistered_infers_opencode():
    assert "deepseek/deepseek-v4-flash" not in BACKENDS
    assert backend_for_model("deepseek/deepseek-v4-flash") == "opencode"


def test_backend_for_model_unregistered_gpt_infers_codex():
    assert backend_for_model("gpt-9-future") == "codex"


def test_registered_model_spec_wins_over_name_prefix():
    model_id = "gpt-served-by-openrouter"
    register_model(ModelSpec(
        id=model_id,
        name="GPT via OpenRouter",
        runtime="opencode",
        provider="openrouter",
        context_length=123456,
    ))
    try:
        assert backend_for_model(model_id) == "opencode"
        assert get_model_spec(model_id).provider == "openrouter"
        assert get_model_spec(model_id).context_length == 123456
    finally:
        unregister_model(model_id)


def test_unknown_grok_gets_explicit_opencode_spec():
    spec = get_model_spec("x-ai/grok-4")
    assert spec.runtime == "opencode"
    assert spec.provider == "x-ai"


def test_cache_policy_is_exact_for_claude_and_approximate_for_codex():
    assert cache_policy_for_runtime("claude") == {
        "cache_ttl_seconds": 3600,
        "cache_ttl_approximate": False,
    }
    assert cache_policy_for_runtime("codex") == {
        "cache_ttl_seconds": 1800,
        "cache_ttl_approximate": True,
    }
    assert cache_policy_for_runtime("opencode") == {
        "cache_ttl_seconds": 3600,
        "cache_ttl_approximate": False,
    }


@pytest.mark.asyncio
async def test_models_api_exposes_runtime_provider_and_capabilities():
    from app.routes.system import list_models

    response = await list_models()
    sol = next(model for model in response["models"] if model["id"] == "gpt-5.6-sol")
    assert sol["runtime"] == "codex"
    assert sol["provider"] == "openai"
    assert sol["capabilities"]["event_stream"] == "per_turn"
    spark = next(model for model in response["models"] if model["id"] == "gpt-5.3-codex-spark")
    assert spark["runtime"] == "codex"
    assert spark["provider"] == "openai"
    assert spark["context_length"] == 128000


@pytest.mark.asyncio
async def test_proxy_model_fetch_omits_empty_authorization_header(monkeypatch):
    captured = {}

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"id": "gpt-5.5", "context_length": 258400}]}

    class _Client:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, _url, headers):
            captured["headers"] = headers
            return _Response()

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("app.models.httpx.AsyncClient", _Client)
    monkeypatch.setattr("app.models._proxy_connected", False)

    assert await fetch_models_from_proxy() is True
    assert captured["headers"] == {}


# ── provider/model split for proxy IDs ──

def test_opencode_split_deepseek():
    b = OpenCodeBackend(model="deepseek/deepseek-v4-flash", cwd="/tmp")
    assert b.provider_id == "deepseek"
    assert b.model == "deepseek-v4-flash"


def test_opencode_split_nested_provider_path():
    # only the FIRST slash splits provider from model id
    b = OpenCodeBackend(model="meta-llama/llama-4-maverick", cwd="/tmp")
    assert b.provider_id == "meta-llama"
    assert b.model == "llama-4-maverick"


def test_opencode_bare_model_keeps_ctor_provider():
    # Proxy IDs are always "provider/model"; a bare ID is degenerate and keeps the
    # ctor provider_id verbatim (no split). Documents the contract, not an endorsement
    # of bare IDs for opencode (the daemon needs a real providerID).
    b = OpenCodeBackend(model="mistral-large", cwd="/tmp", provider_id="mistral")
    assert b.provider_id == "mistral"
    assert b.model == "mistral-large"
