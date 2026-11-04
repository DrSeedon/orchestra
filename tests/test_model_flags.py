"""#366 T1 — kv writers + per-model availability flags (two levels, all runtimes)."""


import json
from unittest.mock import AsyncMock, Mock

import pytest


@pytest.fixture(autouse=True)
def _init_db():
    from app.db import init_db

    init_db()

import app.db as db
import app.models as registry


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



def test_t1_kv_set_and_delete_roundtrip():
    db.kv_set("t1-key", "v1")
    assert db.kv_get("t1-key") == "v1"
    db.kv_set("t1-key", "v2")
    assert db.kv_get("t1-key") == "v2"
    db.kv_delete("t1-key")
    assert db.kv_get("t1-key", "gone") == "gone"


def test_t1_manifest_models_default_to_visible_and_allowed():
    assert registry.get_model_flags("claude-haiku-5-5") == {
        "dashboard": True,
        "agents": True,
    }


def test_t1_registered_catalog_model_defaults_to_hidden_and_forbidden():
    from app.models import ModelSpec

    spec = ModelSpec(
        id="test/vendor-x:free", name="Vendor X", runtime="harness",
        provider="openrouter", context_length=128000,
        price_input=0.0, price_output=0.0, supported_parameters=("tools",),
    )
    registry.register_model(spec)
    try:
        assert registry.get_model_flags("test/vendor-x:free") == {
            "dashboard": False,
            "agents": False,
        }
    finally:
        registry.unregister_model("test/vendor-x:free")


def test_t1_set_flags_roundtrip_and_unknown_rejected():
    with pytest.raises(ValueError):
        registry.set_model_flags("no/such-model", agents=False)
    out = registry.set_model_flags("claude-haiku-5-5", agents=False)
    assert out == {"dashboard": True, "agents": False}
    assert registry.get_model_flags("claude-haiku-5-5") == {
        "dashboard": True,
        "agents": False,
    }
    out = registry.set_model_flags("claude-haiku-5-5", agents=True, dashboard=False)
    assert out == {"dashboard": False, "agents": True}


@pytest.fixture
def models_client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routes.system import router

    # Exercise the real routes without starting live background collectors or CLIs.
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize("alias,canonical", [
    ("claude", "claude"), ("anthropic", "claude"), ("anthropic_fable", "claude"),
    ("codex", "codex"), ("openai", "codex"), ("codex_spark", "codex"),
    ("grok", "grok"), ("xai", "grok"),
    ("harness", "harness"), ("openrouter", "harness"), ("hub", "hub"),
])
def test_provider_aliases(alias, canonical):
    assert registry.normalize_provider_key(alias) == canonical
    registry.set_provider_disabled(alias, True)
    assert registry.is_provider_disabled(canonical)
    assert registry.is_provider_disabled(alias)
    assert registry.set_provider_disabled(alias, False) == []


def test_disabled_providers_local_storage_and_precedence(monkeypatch, tmp_path):
    path = registry._disabled_providers_file()
    assert path == db.DB_PATH.parent / "disabled_providers.json"
    db.kv_set(registry.DISABLED_PROVIDERS_KV_KEY, '["anthropic", "xai"]')
    assert registry.list_disabled_providers() == ["claude", "grok"]

    # An explicit empty local file wins over a historical database setting.
    path.write_text('{"disabled_providers": []}')
    assert registry.list_disabled_providers() == []
    path.write_text('["openai", "codex_spark", "unknown"]')
    monkeypatch.setenv("ORCHESTRA_DISABLED_PROVIDERS", "anthropic,claude,xai,unknown")
    assert registry.list_disabled_providers() == ["claude", "codex", "grok"]

    override = tmp_path / "local" / "providers.json"
    monkeypatch.setenv("ORCHESTRA_DISABLED_PROVIDERS_FILE", str(override))
    assert registry._disabled_providers_file() == override
    assert registry.set_provider_disabled("openrouter", True) == ["claude", "grok", "harness"]
    assert json.loads(override.read_text()) == {
        "disabled_providers": ["claude", "grok", "harness"],
    }
    assert json.loads(db.kv_get(registry.DISABLED_PROVIDERS_KV_KEY)) == ["claude", "grok", "harness"]
    assert registry.normalize_provider_key(None) is None
    with pytest.raises(ValueError, match="unknown provider"):
        registry.set_provider_disabled("unknown", True)


def test_provider_block_overrides_model_flags_and_gates(models_client, monkeypatch):
    unaffected = {
        mid: registry.get_model_flags(mid)
        for mid, spec in registry.MODEL_SPECS.items() if spec.runtime in {"codex", "hub"}
    }
    assert registry.set_provider_disabled("claude", True) == ["claude"]
    assert json.loads(registry._disabled_providers_file().read_text()) == {
        "disabled_providers": ["claude"],
    }
    assert json.loads(db.kv_get(registry.DISABLED_PROVIDERS_KV_KEY)) == ["claude"]
    claude_ids = {
        mid for mid, spec in registry.MODEL_SPECS.items() if spec.runtime == "claude"
    }
    assert "claude-haiku-5-5" in claude_ids
    for mid in claude_ids:
        assert registry.get_model_flags(mid) == {"dashboard": False, "agents": False}
        with pytest.raises(ValueError, match="locally disabled.*dashboard / agents"):
            registry.ensure_dashboard_visible(mid)
        # API credit cannot bypass a local block either.
        with pytest.raises(ValueError, match="locally disabled.*dashboard / agents"):
            registry.ensure_spawn_allowed(mid, billing="api_credit")
    registry.set_model_flags("claude-haiku-5-5", dashboard=True, agents=True)
    assert registry.get_model_flags("claude-haiku-5-5") == {"dashboard": False, "agents": False}
    response = models_client.get("/api/models").json()
    assert response["disabled_providers"] == ["claude"]
    ids = {model["id"] for model in response["models"]}
    assert not ids & claude_ids
    for mid, flags in unaffected.items():
        assert registry.get_model_flags(mid) == flags
        if flags["dashboard"]:
            assert mid in ids
    monkeypatch.setattr("app.backend_hub.hub_configured", lambda: None)
    registry.ensure_spawn_allowed(registry.resolve_model("hubsol"))
    registry.ensure_dashboard_visible("gpt-6.1-sol")
    registry.set_provider_disabled("claude", False)
    registry.ensure_dashboard_visible("claude-haiku-5-5")
    registry.ensure_spawn_allowed("claude-haiku-5-5", billing="api_credit")


def test_provider_toggle_endpoint_and_catalog(models_client):
    for disabled in (True, False):
        expected = ["claude"] if disabled else []
        response = models_client.patch("/api/models/catalog/flags", json={
            "provider": "anthropic", "disabled": disabled,
        })
        assert response.status_code == 200
        assert response.json() == {
            "ok": True, "provider": "claude", "disabled": disabled,
            "disabled_providers": expected,
        }
        catalog = models_client.get("/api/models/catalog").json()
        assert catalog["disabled_providers"] == expected
        for model in catalog["catalog"]:
            assert model["provider_disabled"] == (disabled and model["runtime"] == "claude")
    # The existing per-model request shape still works.
    response = models_client.patch("/api/models/catalog/flags", json={
        "id": "claude-haiku-5-5", "dashboard": False,
    })
    assert response.status_code == 200
    assert response.json()["flags"] == {"dashboard": False, "agents": True}


@pytest.mark.parametrize("body", [
    {"provider": "claude", "disabled": "false"},
    {"provider": "claude", "disabled": 1},
    {"provider": "claude"},
    {"provider": "unknown", "disabled": True},
    {"provider": None, "disabled": True},
    {"provider": [], "disabled": True},
])
def test_provider_toggle_rejects_invalid_requests(models_client, body):
    assert models_client.patch("/api/models/catalog/flags", json=body).status_code == 400
    assert registry.list_disabled_providers() == []


@pytest.fixture
def mocked_usage(monkeypatch):
    from app.routes import system

    monkeypatch.setattr(system, "is_owner_mode", lambda: True)
    monkeypatch.setattr(system, "_maybe_refresh_openrouter_reconciliation", AsyncMock())
    monkeypatch.setattr(system, "_get_openrouter_usage", lambda: None)
    monkeypatch.setattr(system, "_get_agents_cost", lambda: {})
    monkeypatch.setattr(system, "_get_voice_cost_usd", lambda: 0)
    monkeypatch.setattr(system, "_save_usage_cache", Mock())
    monkeypatch.setattr(system, "_read_oauth_credentials", Mock(return_value=("test-token", None)))
    monkeypatch.setattr(system, "_read_grok_token", Mock(return_value="test-token"))
    for cache in ("_usage_cache", "_codex_usage_cache", "_grok_usage_cache"):
        monkeypatch.setattr(system, cache, {"data": {"stale": True}, "ts": 0, "error": "stale"})
    for fetch in ("_fetch_anthropic_usage", "_fetch_codex_usage", "_fetch_grok_usage"):
        monkeypatch.setattr(system, fetch, AsyncMock(return_value={"fresh": True}))
    monkeypatch.setattr(system, "_latest_claude_data", Mock(side_effect=lambda data: data))
    return system


@pytest.mark.parametrize("provider,field,fetch", [
    ("claude", "anthropic", "_fetch_anthropic_usage"),
    ("codex", "codex", "_fetch_codex_usage"),
    ("grok", "grok", "_fetch_grok_usage"),
])
def test_usage_skips_disabled_provider(models_client, mocked_usage, provider, field, fetch):
    registry.set_provider_disabled(provider, True)
    response = models_client.get("/api/usage")
    assert response.status_code == 200
    usage = response.json()
    assert usage["disabled_providers"] == [provider]
    assert usage[field] is None
    getattr(mocked_usage, fetch).assert_not_awaited()
    if provider == "claude":
        mocked_usage._read_oauth_credentials.assert_not_called()
        mocked_usage._latest_claude_data.assert_not_called()
        assert usage["anthropic_error"] is None
        assert usage["quota_headroom"] is None
    if provider == "grok":
        mocked_usage._read_grok_token.assert_not_called()
    registry.set_provider_disabled(provider, False)
    assert models_client.get("/api/usage").json()[field] == {"fresh": True}
    getattr(mocked_usage, fetch).assert_awaited_once()


@pytest.mark.asyncio
async def test_background_collector_skips_disabled_providers(mocked_usage, monkeypatch):
    save = Mock()
    monkeypatch.setattr(db, "usage_save_snapshot", save)
    for provider in ("claude", "codex", "grok"):
        registry.set_provider_disabled(provider, True)
    await mocked_usage._collect_usage_snapshot()
    mocked_usage._read_oauth_credentials.assert_not_called()
    mocked_usage._read_grok_token.assert_not_called()
    mocked_usage._latest_claude_data.assert_not_called()
    for fetch in ("_fetch_anthropic_usage", "_fetch_codex_usage", "_fetch_grok_usage"):
        getattr(mocked_usage, fetch).assert_not_awaited()
    save.assert_not_called()
    for provider in ("claude", "codex", "grok"):
        registry.set_provider_disabled(provider, False)
    await mocked_usage._collect_usage_snapshot()
    mocked_usage._read_oauth_credentials.assert_called_once()
    mocked_usage._read_grok_token.assert_called_once()
    for fetch in ("_fetch_anthropic_usage", "_fetch_codex_usage", "_fetch_grok_usage"):
        getattr(mocked_usage, fetch).assert_awaited_once()


@pytest.mark.asyncio
async def test_quota_map_excludes_disabled_provider(mocked_usage):
    baseline = await mocked_usage.build_quota_map()
    assert any(item["bucket"] == "anthropic" for item in baseline["buckets"])
    registry.set_provider_disabled("claude", True)
    quota = await mocked_usage.build_quota_map()
    assert not any(item["bucket"] in {"anthropic", "anthropic_fable"} for item in quota["buckets"])
    assert any(item["bucket"] == "codex" for item in quota["buckets"])


@pytest.mark.parametrize("provider", ["claude", "anthropic"])
def test_limits_card_omits_blocked_claude_and_keeps_history_alignment(provider, monkeypatch):
    from app import limits_card

    histories = {key: {"source": key} for key in limits_card.POOL_HISTORY_KEYS}
    monkeypatch.setattr(limits_card, "collect_history", lambda history, now: histories)
    usage = {"quota_headroom": {"rate": 1, "windows_left": 1}}
    assert len(limits_card.collect(usage)["pools"]) == 6
    usage["disabled_providers"] = [provider]
    card = limits_card.collect(usage)
    assert card["week"] is None
    assert len(card["pools"]) == 4
    assert all("Claude" not in p["label"] for p in card["pools"])
    assert card["pools"][0]["history"] == {"source": ("codex", "primary")}
