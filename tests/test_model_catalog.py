"""#366 T2 — OpenRouter catalog fetch/normalize/cache + registration-order guarantee.


The order test encodes the invariant from research F4/risk #1: the catalog is applied
BEFORE an enterprise-mode proxy refresh wipes the registry, and must still be present
AFTERWARDS — i.e. the refresh path itself re-applies the catalog.
"""

import json
from types import SimpleNamespace

import pytest


@pytest.fixture(autouse=True)
def _init_db():
    from app.db import init_db

    init_db()

import app.db as db


@pytest.fixture(autouse=True)
def _registry_snapshot():
    """Registry dicts are module-global and mutated in place: hand them back to
    the next test exactly as received (kv state is per-test via conftest DB)."""
    import copy

    import app.models as registry

    names = ("MODELS", "BACKENDS", "CONTEXT_LIMITS", "MODEL_PROVIDERS",
             "TOKEN_PRICES", "MODEL_SPECS", "ALIASES")
    snap = {n: copy.deepcopy(getattr(registry, n)) for n in names}
    yield
    for n in names:
        d = getattr(registry, n)
        d.clear()
        d.update(snap[n])


CATALOG_KV_KEY = "model_catalog_cache"

RAW_MODEL = {
    "id": "vendor/model-x:free",
    "name": "Vendor: Model X",
    "context_length": 128000,
    "pricing": {"prompt": "0", "completion": "0"},
    "architecture": {
        "input_modalities": ["text", "image"],
        "output_modalities": ["text"],
    },
    "supported_parameters": ["tools", "temperature", "tool_choice"],
}

NORMALIZED = {
    "id": "vendor/model-x:free",
    "name": "Vendor: Model X",
    "context_length": 128000,
    "price_prompt": 0.0,
    "price_completion": 0.0,
    "input_modalities": ["text", "image"],
    "output_modalities": ["text"],
    "supports_tools": True,
    "supported_parameters": ["temperature", "tool_choice", "tools"],
    "is_free": True,
    "harness_eligible": True,
    "available": True,
}


def _seed_cache():
    db.kv_set(
        CATALOG_KV_KEY,
        json.dumps({"fetched_at": 1724300000.0, "models": [NORMALIZED]}),
    )


def _catalog_module():
    """Import the catalog module; absence fails as an explicit assertion
    (missing behaviour), not as a collection-time ImportError."""
    import importlib

    try:
        return importlib.import_module("app.model_catalog")
    except ImportError as exc:
        pytest.fail(f"app.model_catalog module missing: {exc}")


def test_t2_normalize_maps_openrouter_fields():
    assert _catalog_module().normalize_catalog_model(RAW_MODEL) == NORMALIZED


def test_t2_normalize_free_and_no_tools():
    raw = {
        **RAW_MODEL,
        "pricing": {"prompt": "0", "completion": "0"},
        "supported_parameters": ["temperature"],
        "architecture": {"input_modalities": ["text"]},
    }
    norm = _catalog_module().normalize_catalog_model(raw)
    assert norm["price_prompt"] == 0.0
    assert norm["price_completion"] == 0.0
    assert norm["supports_tools"] is False
    assert norm["input_modalities"] == ["text"]
    assert norm["harness_eligible"] is False


def test_t2_zero_token_price_without_free_suffix_is_not_harness_eligible():
    raw = {
        **RAW_MODEL,
        "id": "google/lyria-3-pro-preview",
        "pricing": {"prompt": "0", "completion": "0"},
    }

    norm = _catalog_module().normalize_catalog_model(raw)

    assert norm["price_prompt"] == 0.0
    assert norm["price_completion"] == 0.0
    assert norm["is_free"] is False
    assert norm["harness_eligible"] is False


def test_t2_normalize_rejects_empty_id():
    assert _catalog_module().normalize_catalog_model({**RAW_MODEL, "id": ""}) is None


class _FakeResponse:
    def raise_for_status(self):
        pass

    def json(self):
        return {"data": [{"id": "claude-proxy-9", "name": "Proxy 9",
                          "runtime": "claude", "provider": "anthropic"}]}


class _FakeAsyncClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url, headers=None):
        return _FakeResponse()


@pytest.mark.asyncio
async def test_t2_catalog_survives_enterprise_proxy_refresh(monkeypatch):
    """Catalog was applied BEFORE the wipe (seeded cache) — it must still be in the
    registry AFTERWARDS: the refresh path itself re-applies the catalog."""
    import app.models as registry

    apply = _catalog_module().apply_model_catalog

    monkeypatch.setattr("app.models.httpx", SimpleNamespace(AsyncClient=_FakeAsyncClient))
    _seed_cache()
    assert apply() >= 1
    ok = await registry.fetch_models_from_proxy(enterprise_mode=True)
    assert ok is True
    assert "vendor/model-x:free" in registry.MODELS
    assert registry.BACKENDS["vendor/model-x:free"] == "harness"
    assert registry.CONTEXT_LIMITS["vendor/model-x:free"] == 128000
    assert registry.TOKEN_PRICES["vendor/model-x:free"] == {"input": 0.0, "output": 0.0}
    assert registry.MODEL_SPECS["vendor/model-x:free"].supported_parameters == (
        "temperature", "tool_choice", "tools",
    )
    assert "claude-proxy-9" in registry.MODELS


def test_t2_apply_retains_disappeared_model_as_unavailable_compatibility_route():
    catalog = _catalog_module()
    _seed_cache()
    assert catalog.apply_model_catalog() == 1
    assert "vendor/model-x:free" in __import__("app.models", fromlist=["MODEL_SPECS"]).MODEL_SPECS

    stale = {**NORMALIZED, "available": False}
    db.kv_set(CATALOG_KV_KEY, json.dumps({"fetched_at": 1724300001.0, "models": [stale]}))
    catalog.apply_model_catalog()

    import app.models as registry
    spec = registry.MODEL_SPECS["vendor/model-x:free"]
    assert spec.available is False
    with pytest.raises(ValueError, match="no longer available"):
        registry.validate_harness_model_spec(spec)


def test_t2_legacy_cache_row_stays_usable_with_conservative_tools_only_capability():
    legacy = {
        key: value for key, value in NORMALIZED.items()
        if key not in {"output_modalities", "supported_parameters", "is_free", "harness_eligible"}
    }
    db.kv_set(CATALOG_KV_KEY, json.dumps({"fetched_at": 1724300000.0, "models": [legacy]}))

    assert _catalog_module().apply_model_catalog() == 1

    import app.models as registry
    assert registry.MODEL_SPECS["vendor/model-x:free"].supported_parameters == ("tools",)


def test_t2_apply_never_registers_zero_token_unsuffixed_route():
    lyria = _catalog_module().normalize_catalog_model({
        **RAW_MODEL,
        "id": "google/lyria-3-pro-preview",
        "pricing": {"prompt": "0", "completion": "0"},
    })
    db.kv_set(
        CATALOG_KV_KEY,
        json.dumps({"fetched_at": 1724300000.0, "models": [NORMALIZED, lyria]}),
    )

    assert _catalog_module().apply_model_catalog() == 1

    import app.models as registry
    assert "vendor/model-x:free" in registry.MODEL_SPECS
    assert "google/lyria-3-pro-preview" not in registry.MODEL_SPECS


@pytest.mark.asyncio
async def test_t2_refresh_retains_vanished_route_for_resume_but_marks_it_unavailable(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": []}

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, headers=None):
            return Response()

    catalog = _catalog_module()
    _seed_cache()
    monkeypatch.setattr(catalog.httpx, "AsyncClient", Client)

    result = await catalog.refresh_catalog()

    cached = catalog.cached_catalog()
    assert result["retained_stale"] == 1
    assert cached == [{**NORMALIZED, "available": False}]
