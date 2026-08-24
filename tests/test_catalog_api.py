"""#366 T4 — catalog HTTP API: list, refresh, flags."""


import json
from types import SimpleNamespace

import pytest


@pytest.fixture(autouse=True)
def _init_db():
    from app.db import init_db

    init_db()

import app.db as db
import app.models as registry
from app.models import ModelSpec


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

NORMALIZED = {
    "id": "vendor/model-x:free",
    "name": "Vendor: Model X",
    "context_length": 128000,
    "price_prompt": 0.0,
    "price_completion": 0.0,
    "input_modalities": ["text", "image"],
    "output_modalities": ["text"],
    "supports_tools": True,
    "supported_parameters": ["tool_choice", "tools"],
    "is_free": True,
    "harness_eligible": True,
    "available": True,
}


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from app.main import app, manager

    manager.sessions.clear()
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def vendor_model():
    spec = ModelSpec(
        id="test/vendor-x:free", name="Vendor X", runtime="harness",
        provider="openrouter", context_length=128000,
        price_input=0.0, price_output=0.0, supported_parameters=("tools",),
    )
    registry.register_model(spec)
    yield spec
    registry.unregister_model("test/vendor-x:free")


def test_t4_catalog_list_carries_flags(vendor_model, client):
    registry.set_model_flags("test/vendor-x:free", agents=True)
    body = client.get("/api/models/catalog").json()
    entry = next(m for m in body["catalog"] if m["id"] == "test/vendor-x:free")
    # Catalog default is false/false; the user enabled agents only.
    assert entry["flags"] == {"dashboard": False, "agents": True}
    assert entry["price_prompt"] == 0.0
    assert entry["context_length"] == 128000
    manifest_entry = next(m for m in body["catalog"] if m["id"] == "claude-haiku-4-5")
    assert manifest_entry["flags"] == {"dashboard": True, "agents": True}


def test_t4_patch_flags_persists(vendor_model, client):
    resp = client.patch(
        "/api/models/catalog/flags",
        json={"id": "test/vendor-x:free", "dashboard": True, "agents": False},
    )
    assert resp.status_code == 200
    assert resp.json()["flags"] == {"dashboard": True, "agents": False}
    assert registry.get_model_flags("test/vendor-x:free") == {
        "dashboard": True,
        "agents": False,
    }
    unknown = client.patch(
        "/api/models/catalog/flags", json={"id": "no/such-model", "agents": True},
    )
    assert unknown.status_code == 400


def test_t4_cannot_enable_unsuffixed_harness_route(client):
    spec = ModelSpec(
        id="test/paid-preview", name="Paid preview", runtime="harness",
        provider="openrouter", context_length=128000,
        supported_parameters=("tools",),
    )
    registry.register_model(spec)
    try:
        resp = client.patch(
            "/api/models/catalog/flags",
            json={"id": spec.id, "agents": True},
        )
        assert resp.status_code == 400
        assert ":free" in resp.json()["error"]
    finally:
        registry.unregister_model(spec.id)


def test_t4_refresh_refetches_and_reregisters(vendor_model, client, monkeypatch):
    class _FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": [NORMALIZED_RAW]}

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, headers=None):
            return _FakeResponse()

    NORMALIZED_RAW = {
        "id": "vendor/model-y:free",
        "name": "Vendor: Model Y",
        "context_length": 64000,
        "pricing": {"prompt": "0", "completion": "0"},
        "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
        "supported_parameters": ["tools", "tool_choice"],
    }
    monkeypatch.setattr(
        "app.model_catalog.httpx", SimpleNamespace(AsyncClient=_FakeAsyncClient)
    )
    try:
        resp = client.post("/api/models/catalog/refresh")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["fetched"] == 1
        assert "vendor/model-y:free" in registry.MODELS
    finally:
        registry.unregister_model("vendor/model-y:free")
