"""#366 T3 — enforcement of the two availability levels.


dashboard flag → what the dashboard shows (/api/models) and what user actions accept;
agents flag → what agents may use (spawn, MCP change-model, dynamic workflows, review).
Persisted-session recovery uses compatibility routes; owner-only models remain gated on every
agent entry point, including the internal review-model resolver.
"""

import pytest


@pytest.fixture(autouse=True)
def _init_db():
    from app.db import init_db

    init_db()

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



@pytest.fixture()
def vendor_model(live_harness_route):
    live_harness_route("test/vendor-x:free")
    yield registry.get_model_spec("test/vendor-x:free")
    registry.unregister_model("test/vendor-x:free")


def test_t3_api_models_hides_dashboard_off(vendor_model, monkeypatch):
    from fastapi.testclient import TestClient

    registry.set_model_flags("test/vendor-x:free", dashboard=False)
    from app.main import app, manager

    manager.sessions.clear()
    with TestClient(app) as client:
        ids = {m["id"] for m in client.get("/api/models").json()["models"]}
    assert "test/vendor-x:free" not in ids
    assert "claude-haiku-5-5" in ids

    registry.set_model_flags("test/vendor-x:free", dashboard=True)
    with TestClient(app) as client:
        ids = {m["id"] for m in client.get("/api/models").json()["models"]}
    assert "test/vendor-x:free" in ids


def test_t3_worker_spawn_rejected_on_agents_off(vendor_model, monkeypatch):
    registry.set_model_flags("test/vendor-x:free", agents=False)
    with pytest.raises(ValueError, match="agents"):
        registry.ensure_spawn_allowed("test/vendor-x:free")
    monkeypatch.setattr("app.backend_hub.hub_configured", lambda: None)
    registry.ensure_spawn_allowed(registry.resolve_model("hubsol"))


@pytest.mark.asyncio
@pytest.mark.parametrize("model", ["astra", "sol"])
async def test_manual_only_model_cannot_be_spawned_by_an_agent(model):
    from app.manager import SessionManager

    with pytest.raises(ValueError, match="disabled for agents"):
        await SessionManager().create_session(
            name="manual-only-child", scope="/tmp", cwd="/tmp", model=model,
            parent_name="agent-orchestrator",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("model", ["astra", "sol"])
async def test_mcp_change_model_rejects_manual_only_models_before_loading(model, monkeypatch):
    from app.routes import sessions as routes
    from fastapi.responses import JSONResponse
    from unittest.mock import AsyncMock

    ensure_loaded = AsyncMock(side_effect=AssertionError("gate must run before loading"))
    monkeypatch.setattr(routes.manager, "ensure_loaded", ensure_loaded)
    response = await routes.change_model(
        "worker", {"scope": "/tmp", "model": model, "via": "mcp"},
    )
    assert isinstance(response, JSONResponse)
    assert response.status_code == 409
    assert "disabled for agents" in response.body.decode()
    ensure_loaded.assert_not_awaited()


def test_t3_dashboard_gate_blocks_user_actions_only(monkeypatch):
    model = registry.resolve_model("hubsol")
    monkeypatch.setattr("app.backend_hub.hub_configured", lambda: None)
    registry.set_model_flags(model, dashboard=False)
    with pytest.raises(ValueError, match="dashboard"):
        registry.ensure_dashboard_visible(model)
    # Visibility remains independent on the permitted ordinary-worker route.
    registry.set_model_flags(model, agents=True)
    registry.ensure_spawn_allowed(model)


def test_t3_resolve_model_unaffected_by_flags(vendor_model):
    """Overlay must never unregister: codex_review and session resume rely on this."""
    registry.set_model_flags("test/vendor-x:free", agents=False, dashboard=False)
    assert registry.resolve_model("test/vendor-x:free") == "test/vendor-x:free"
    assert registry.get_model_spec("test/vendor-x:free").context_length == 128000


def test_t3_gates_are_wired_into_spawn_and_change_model():
    """Delivery check: the gates must sit on the real paths, not only exist.
    Asserts the CALL inside create_session / change_model, not a module-level
    import (a dangling import would make this pass on broken wiring)."""
    import inspect

    import app.manager as manager_mod
    import app.mcp_stdio as mcp_mod
    from app.routes import sessions as sessmod

    create_src = inspect.getsource(
        manager_mod.SessionManager._create_session_locked
    )
    assert "ensure_spawn_allowed" in create_src
    assert "ensure_dashboard_visible" in create_src
    change_src = inspect.getsource(sessmod.change_model)
    assert "ensure_spawn_allowed" in change_src
    assert "ensure_dashboard_visible" in change_src
    # The MCP tool acts as an agent: its request must carry the agent level.
    mcp_src = inspect.getsource(mcp_mod)
    assert '"mcp"' in mcp_src or "'mcp'" in mcp_src


def test_sol_is_dashboard_selectable_but_closed_to_agents():
    from app.models import ensure_dashboard_visible, ensure_spawn_allowed, get_model_flags

    assert get_model_flags("gpt-6.1-sol") == {"dashboard": True, "agents": False}
    ensure_dashboard_visible("gpt-6.1-sol")
    with pytest.raises(ValueError, match="disabled for agents"):
        ensure_spawn_allowed("gpt-6.1-sol")


@pytest.mark.asyncio
async def test_owner_dashboard_change_model_allows_sol(monkeypatch):
    from app.routes import sessions as routes
    from unittest.mock import AsyncMock

    changed_to = []

    class Worker:
        async def change_model(self, model):
            changed_to.append(model)
            return {"ok": True, "changed": True, "old_model": "gpt-6-luna", "model": model}

    monkeypatch.setattr(routes.manager, "ensure_loaded", AsyncMock(return_value=Worker()))
    result = await routes.change_model("worker", {"scope": "/tmp", "model": "sol"})

    assert result["ok"] is True
    assert changed_to == ["gpt-6.1-sol"]
