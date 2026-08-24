"""#366 T6 — a model switched off while an agent is running on it.


Two shoulders (user requirement):
A) the running agent finishes its lifecycle — the whole resume surface keeps resolving;
B) NEW usage is refused — worker spawn fails closed with an actionable message.
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


def test_t6_running_agent_resume_surface_intact(vendor_model):
    registry.set_model_flags("test/vendor-x:free", dashboard=False, agents=False)
    # Everything the resume/restart path touches must keep working.
    assert registry.get_model_spec("test/vendor-x:free").runtime == "harness"
    assert registry.resolve_model("test/vendor-x:free") == "test/vendor-x:free"
    assert registry.CONTEXT_LIMITS["test/vendor-x:free"] == 128000
    assert registry.TOKEN_PRICES["test/vendor-x:free"] == {"input": 0.0, "output": 0.0}
    assert registry.backend_for_model("test/vendor-x:free") == "harness"


def test_t6_new_worker_spawn_rejected_with_actionable_error(vendor_model):
    registry.set_model_flags("test/vendor-x:free", agents=False)
    with pytest.raises(ValueError, match="[Cc]atalog"):
        registry.ensure_spawn_allowed("test/vendor-x:free")


def test_t6_switching_away_from_disabled_model_is_allowed(vendor_model):
    """The escape hatch: a session ON the disabled model may change to any
    dashboard-visible model — only the TARGET model's level is checked."""
    registry.set_model_flags("test/vendor-x:free", dashboard=False, agents=False)
    registry.ensure_dashboard_visible("claude-haiku-4-5")  # target is fine → change proceeds
