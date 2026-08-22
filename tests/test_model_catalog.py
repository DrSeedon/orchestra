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
    "id": "vendor/model-x",
    "name": "Vendor: Model X",
    "context_length": 128000,
    "pricing": {"prompt": "0.0000005", "completion": "0.0000015"},
    "architecture": {"input_modalities": ["text", "image"]},
    "supported_parameters": ["tools", "temperature"],
}

NORMALIZED = {
    "id": "vendor/model-x",
    "name": "Vendor: Model X",
    "context_length": 128000,
    "price_prompt": 0.5,
    "price_completion": 1.5,
    "input_modalities": ["text", "image"],
    "supports_tools": True,
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
    assert "vendor/model-x" in registry.MODELS
    assert registry.BACKENDS["vendor/model-x"] == "harness"
    assert registry.CONTEXT_LIMITS["vendor/model-x"] == 128000
    assert registry.TOKEN_PRICES["vendor/model-x"] == {"input": 0.5, "output": 1.5}
    assert "claude-proxy-9" in registry.MODELS
