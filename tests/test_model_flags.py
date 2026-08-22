"""#366 T1 — kv writers + per-model availability flags (two levels, all runtimes)."""


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
    assert registry.get_model_flags("claude-haiku-4-5") == {
        "dashboard": True,
        "agents": True,
    }


def test_t1_registered_catalog_model_defaults_to_hidden_and_forbidden():
    from app.models import ModelSpec

    spec = ModelSpec(
        id="test/vendor-x", name="Vendor X", runtime="harness",
        provider="openrouter", context_length=128000,
        price_input=0.5, price_output=1.5,
    )
    registry.register_model(spec)
    try:
        assert registry.get_model_flags("test/vendor-x") == {
            "dashboard": False,
            "agents": False,
        }
    finally:
        registry.unregister_model("test/vendor-x")


def test_t1_set_flags_roundtrip_and_unknown_rejected():
    with pytest.raises(ValueError):
        registry.set_model_flags("no/such-model", agents=False)
    out = registry.set_model_flags("claude-haiku-4-5", agents=False)
    assert out == {"dashboard": True, "agents": False}
    assert registry.get_model_flags("claude-haiku-4-5") == {
        "dashboard": True,
        "agents": False,
    }
    out = registry.set_model_flags("claude-haiku-4-5", agents=True, dashboard=False)
    assert out == {"dashboard": False, "agents": True}
