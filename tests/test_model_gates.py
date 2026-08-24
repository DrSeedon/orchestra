"""#366 T3 — enforcement of the two availability levels.


dashboard flag → what the dashboard shows (/api/models) and what user actions accept;
agents flag  → what agents may use (spawn prompt block, worker spawn, MCP change-model).
Internal routes (codex_review model resolution) are deliberately NOT gated.
"""

import pytest


@pytest.fixture(autouse=True)
def _init_db():
    from app.db import init_db

    init_db()

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


def test_t3_api_models_hides_dashboard_off(vendor_model, monkeypatch):
    from fastapi.testclient import TestClient

    registry.set_model_flags("test/vendor-x:free", dashboard=False)
    from app.main import app, manager

    manager.sessions.clear()
    with TestClient(app) as client:
        ids = {m["id"] for m in client.get("/api/models").json()["models"]}
    assert "test/vendor-x:free" not in ids
    assert "claude-haiku-4-5" in ids

    registry.set_model_flags("test/vendor-x:free", dashboard=True)
    with TestClient(app) as client:
        ids = {m["id"] for m in client.get("/api/models").json()["models"]}
    assert "test/vendor-x:free" in ids


def test_t3_available_models_block_respects_agents_flag(vendor_model):
    registry.set_model_flags("test/vendor-x:free", agents=False)
    assert "test/vendor-x:free" not in registry.available_models_block()
    registry.set_model_flags("test/vendor-x:free", agents=True)
    assert "test/vendor-x:free" in registry.available_models_block()


def test_t3_worker_spawn_rejected_on_agents_off(vendor_model):
    registry.set_model_flags("test/vendor-x:free", agents=False)
    with pytest.raises(ValueError, match="agents"):
        registry.ensure_spawn_allowed("test/vendor-x:free")
    registry.ensure_spawn_allowed("claude-haiku-4-5")


def test_t3_dashboard_gate_blocks_user_actions_only(vendor_model):
    registry.set_model_flags("test/vendor-x:free", dashboard=False)
    with pytest.raises(ValueError, match="dashboard"):
        registry.ensure_dashboard_visible("test/vendor-x:free")
    # Levels are independent: hidden from the dashboard, still allowed to agents.
    registry.set_model_flags("test/vendor-x:free", agents=True)
    registry.ensure_spawn_allowed("test/vendor-x:free")


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
