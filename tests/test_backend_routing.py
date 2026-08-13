"""Exhaustive model/runtime/provider routing."""

import pytest

from app.models import (
    ALIASES,
    BACKENDS,
    CONTEXT_LIMITS,
    MODELS,
    PROVIDER_METADATA,
    TOKEN_PRICES,
    ModelSpec,
    available_models_block,
    backend_for_model,
    cache_policy_for_runtime,
    fetch_models_from_proxy,
    get_model_spec,
    register_model,
    resolve_model,
    unregister_model,
    validate_model_registry,
)
from app.backend_opencode import OpenCodeBackend


@pytest.fixture
def isolated_model_registry(monkeypatch):
    import app.models as registry

    for name in (
        "MODELS",
        "CONTEXT_LIMITS",
        "ALIASES",
        "BACKENDS",
        "MODEL_PROVIDERS",
        "TOKEN_PRICES",
        "MODEL_SPECS",
    ):
        monkeypatch.setattr(registry, name, dict(getattr(registry, name)))
    monkeypatch.setattr(registry, "_proxy_connected", False)
    return registry


def test_spark_is_registered_for_codex_workers():
    model_id = "gpt-5.3-codex-spark"
    assert MODELS[model_id] == "GPT-5.3 Codex Spark"
    assert CONTEXT_LIMITS[model_id] == 128000
    assert BACKENDS[model_id] == "codex"
    assert ALIASES["spark"] == model_id
    assert backend_for_model(model_id) == "codex"
    assert "`gpt-5.3-codex-spark` — GPT-5.3 Codex Spark, 128k context" in available_models_block()


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
    # Retired ids upgrade to Opus 5; 4.6 is selectable again and resolves to itself.
    assert resolve_model("claude-opus-4-8[1m]") == model_id
    assert resolve_model("claude-opus-4-6") == "claude-opus-4-6"
    assert "claude-opus-4-8[1m]" not in MODELS
    assert get_model_spec("claude-opus-4-8[1m]").runtime == "claude"


def test_backend_for_model_registered_wins():
    assert "claude-sonnet-5[1m]" in BACKENDS
    assert backend_for_model("claude-sonnet-5[1m]") == "claude"


@pytest.mark.parametrize("model_id", [
    "deepseek/deepseek-v5-future",
    "gpt-9-future",
    "grok-9.9-future",
    "x-ai/grok-4",
])
def test_unknown_model_fails_loud_instead_of_inferring(model_id):
    with pytest.raises(ValueError, match="unknown model") as exc:
        backend_for_model(model_id)
    assert "registered models:" in str(exc.value)
    with pytest.raises(ValueError, match="unknown model"):
        resolve_model(model_id)


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


def test_model_registration_rejects_unknown_runtime_and_provider():
    with pytest.raises(ValueError, match="unknown agent runtime"):
        register_model(ModelSpec(
            id="vendor/model",
            name="Missing runtime",
            runtime="not-registered",
            provider="vendor",
        ))
    with pytest.raises(ValueError, match="provider 'vendor'.*not registered"):
        register_model(ModelSpec(
            id="vendor/model",
            name="Missing provider metadata",
            runtime="opencode",
            provider="vendor",
        ))


def test_persisted_legacy_sonnet_has_exact_compatibility_route():
    spec = get_model_spec("claude-sonnet-4-6")
    assert spec.runtime == "claude"
    assert spec.provider == "anthropic"
    assert spec.context_length == 200000
    assert "claude-sonnet-4-6" not in MODELS


def test_registry_validator_covers_every_selectable_model():
    validate_model_registry()
    assert set(MODELS) == set(BACKENDS)
    for model_id in MODELS:
        spec = get_model_spec(model_id)
        assert spec.runtime in PROVIDER_METADATA
        assert spec.provider != "unknown"


def test_declaring_one_spec_populates_every_derived_view(isolated_model_registry):
    """Adding a model must mean editing SELECTABLE_MODEL_SPECS and nothing else.

    The five dicts below used to be hand-maintained in parallel, so forgetting one
    made a model either invisible in the picker or fatal at spawn.
    """
    registry = isolated_model_registry
    spec = ModelSpec(
        id="claude-hypothetical-9",
        name="Hypothetical 9",
        runtime="claude",
        provider="anthropic",
        context_length=333000,
        price_input=1.25,
        price_output=6.5,
    )

    assert spec.id not in registry.MODELS

    registry.register_model(spec)

    assert registry.MODELS[spec.id] == "Hypothetical 9"
    assert registry.CONTEXT_LIMITS[spec.id] == 333000
    assert registry.BACKENDS[spec.id] == "claude"
    assert registry.MODEL_PROVIDERS[spec.id] == "anthropic"
    assert registry.TOKEN_PRICES[spec.id] == {"input": 1.25, "output": 6.5}
    assert registry.get_model_spec(spec.id) is spec
    registry.validate_model_registry()


def test_derived_views_carry_exactly_the_declared_specs():
    """No view may gain or lose an id relative to the single declaration list."""
    import app.models as registry

    declared = {spec.id for spec in registry.SELECTABLE_MODEL_SPECS}
    assert declared == set(MODELS)
    assert declared == set(BACKENDS)
    assert declared == set(CONTEXT_LIMITS)
    assert declared == set(registry.MODEL_PROVIDERS)
    # Only priced specs reach TOKEN_PRICES; Codex/Grok price in their backends.
    assert set(TOKEN_PRICES) == {
        spec.id for spec in registry.SELECTABLE_MODEL_SPECS
        if spec.price_input is not None or spec.price_output is not None
    }
    for spec in registry.SELECTABLE_MODEL_SPECS:
        assert MODELS[spec.id] == spec.name
        assert CONTEXT_LIMITS[spec.id] == spec.context_length
        assert BACKENDS[spec.id] == spec.runtime
        assert registry.MODEL_PROVIDERS[spec.id] == spec.provider


def test_opus46_is_selectable_and_priced():
    """Opus 4.6 is live on the subscription — picking it must not divert to Opus 5."""
    spec = get_model_spec("claude-opus-4-6")
    assert MODELS["claude-opus-4-6"] == "Opus 4.6"
    assert spec.runtime == "claude"
    assert spec.provider == "anthropic"
    assert spec.context_length == 200000
    assert get_model_spec("claude-opus-4-6[1m]").context_length == 1_000_000
    assert TOKEN_PRICES["claude-opus-4-6"] == {"input": 5.0, "output": 25.0}
    assert resolve_model("claude-opus-4-6") == "claude-opus-4-6"
    assert resolve_model("claude-opus-4-6[1m]") == "claude-opus-4-6[1m]"
    assert backend_for_model("claude-opus-4-6") == "claude"
    # A live model must not also linger as a retired compatibility route.
    import app.models as registry
    assert "claude-opus-4-6" not in registry.COMPAT_MODEL_SPECS


def test_cache_policy_is_explicit_and_unknown_is_conservative():
    assert cache_policy_for_runtime("claude") == {
        "cache_ttl_seconds": 3600,
        "cache_ttl_approximate": False,
    }
    assert cache_policy_for_runtime("codex") == {
        "cache_ttl_seconds": 1800,
        "cache_ttl_approximate": True,
    }
    assert cache_policy_for_runtime("opencode") == {
        "cache_ttl_seconds": 0,
        "cache_ttl_approximate": True,
    }
    assert cache_policy_for_runtime("not-registered") == {
        "cache_ttl_seconds": 0,
        "cache_ttl_approximate": True,
    }


@pytest.mark.asyncio
async def test_models_api_exposes_runtime_provider_and_capabilities():
    from fastapi import Response

    from app.routes.system import list_models

    # #15 добавил маршруту параметр response — версия фронта уезжает заголовком
    response = await list_models(Response())
    sol = next(model for model in response["models"] if model["id"] == "gpt-5.6-sol")
    assert sol["runtime"] == "codex"
    assert sol["provider"] == "openai"
    assert sol["capabilities"]["event_stream"] == "per_turn"
    spark = next(model for model in response["models"] if model["id"] == "gpt-5.3-codex-spark")
    assert spark["runtime"] == "codex"
    assert spark["provider"] == "openai"
    assert spark["context_length"] == 128000
    assert set(response["provider_metadata"]) == set(PROVIDER_METADATA)
    assert response["provider_metadata"]["unknown"]["cache_ttl_seconds"] == 0


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


@pytest.mark.asyncio
async def test_observed_proxy_models_use_reviewed_exact_opencode_routes(
    monkeypatch,
    isolated_model_registry,
):
    payload = {"data": [
        {
            "id": "deepseek/deepseek-v4-flash",
            "context_length": 1048576,
            "pricing": {"prompt": "0.000000098", "completion": "0.000000196"},
        },
        {
            "id": "deepseek/deepseek-v4-pro",
            "context_length": 1048576,
            "pricing": {"prompt": "0.000000435", "completion": "0.000000870"},
        },
    ]}

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return payload

    class _Client:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, _url, headers):
            return _Response()

    monkeypatch.setattr("app.models.httpx.AsyncClient", _Client)

    assert await isolated_model_registry.fetch_models_from_proxy(
        enterprise_mode=True
    ) is True
    assert set(isolated_model_registry.MODELS) == {
        "deepseek/deepseek-v4-flash",
        "deepseek/deepseek-v4-pro",
    }
    for model_id in isolated_model_registry.MODELS:
        spec = isolated_model_registry.get_model_spec(model_id)
        assert spec.runtime == "opencode"
        assert spec.provider == "deepseek"
        assert spec.context_length == 1048576


@pytest.mark.asyncio
async def test_unreviewed_proxy_model_without_route_fails_before_mutation(
    monkeypatch,
    isolated_model_registry,
):
    before = dict(isolated_model_registry.MODEL_SPECS)

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"id": "meta/new-model", "context_length": 1000}]}

    class _Client:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, _url, headers):
            return _Response()

    monkeypatch.setattr("app.models.httpx.AsyncClient", _Client)

    with pytest.raises(ValueError, match="meta/new-model.*runtime/backend"):
        await isolated_model_registry.fetch_models_from_proxy(enterprise_mode=True)
    assert isolated_model_registry.MODEL_SPECS == before


@pytest.mark.asyncio
async def test_proxy_model_with_explicit_runtime_and_provider_is_accepted(
    monkeypatch,
    isolated_model_registry,
):
    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{
                "id": "x-ai/grok-4",
                "runtime": "opencode",
                "provider": "x-ai",
                "context_length": 256000,
            }]}

    class _Client:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, _url, headers):
            return _Response()

    monkeypatch.setattr("app.models.httpx.AsyncClient", _Client)

    assert await isolated_model_registry.fetch_models_from_proxy(
        enterprise_mode=True
    ) is True
    assert isolated_model_registry.backend_for_model("x-ai/grok-4") == "opencode"


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
