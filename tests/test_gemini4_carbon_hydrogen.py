import pytest
from unittest.mock import AsyncMock

from app import backend_hub, models, quota_gate
from app.pipeline import get_role, load_pipeline, resolve_effort


def test_carbon_and_hydrogen_aliases_and_context_limits():
    assert models.resolve_model("hubcarbon") == "hub-gemini-4-carbon"
    assert models.resolve_model("hubhydrogen") == "hub-gemini-4-hydrogen"
    assert models.resolve_model("agy-carbon") == "antigravity/gemini-4-carbon-medium"
    assert models.resolve_model("agy-hydrogen") == "antigravity/gemini-4-hydrogen-high"

    for raw in (
        "gemini-4-carbon-low", "gemini-4-carbon-medium", "gemini-4-carbon-high",
        "gemini-4-hydrogen-low", "gemini-4-hydrogen-medium", "gemini-4-hydrogen-high", "gemini-4-hydrogen-xhigh",
    ):
        full = f"antigravity/{raw}"
        assert full in models.MODELS
        assert models.CONTEXT_LIMITS[full] == 1_000_000
        decision = quota_gate.evaluate_worker_admission(full, {}, {}, now=1000.0)
        assert decision.provider == "antigravity_gemini"


@pytest.mark.parametrize("scope", ["/home/kesha/orchestra", "/home/kesha/seedon", "/mnt/multicast/game"])
@pytest.mark.parametrize("alias", ["hubcarbon", "hubhydrogen", "hub-gemini-4-carbon", "hub-gemini-4-hydrogen"])
def test_carbon_and_hydrogen_admitted_across_all_project_scopes(scope, alias, monkeypatch):
    monkeypatch.delenv("ORCHESTRA_ALLOW_CLAUDE_ALL", raising=False)
    models.ensure_hub_worker_allowed(alias, role="worker", pipeline="default", scope=scope, task_id="t1")


def test_default_pipeline_effort_for_carbon_and_hydrogen():
    load_pipeline.cache_clear()
    for role_name in ("orchestrator", "sub-orchestrator", "worker", "full-cycle", "reducer", "specialist"):
        role = get_role("default", role_name)
        assert resolve_effort(role.effort, "hub-gemini-4-carbon", "hub") == "medium"
        assert resolve_effort(role.effort, "hub-gemini-4-hydrogen", "hub") == "high"


@pytest.mark.asyncio
async def test_hub_backend_model_selection_supports_carbon_and_unlisted_hydrogen():
    hb = backend_hub.HubBackend(model="hub-gemini-4-hydrogen", cwd="/tmp")
    mc = AsyncMock()
    # Simulate current T3 capabilities where Carbon is listed and Hydrogen is omitted by onlyListed=true.
    mc.tool_call = AsyncMock(return_value={
        "providers": [{
            "providerInstanceId": "antigravity",
            "models": [{
                "id": "gemini-4-carbon",
                "options": [{
                    "id": "reasoningEffort",
                    "type": "select",
                    "options": [{"id": "low"}, {"id": "medium"}, {"id": "high"}],
                }],
            }],
        }],
    })

    for eff in ("low", "medium", "high"):
        sel = await hb._model_selection(mc, "hub-gemini-4-carbon", eff)
        assert sel == {
            "instanceId": "antigravity",
            "model": "gemini-4-carbon",
            "options": {"reasoningEffort": eff},
        }
    with pytest.raises(ValueError, match="does not support effort 'xhigh'"):
        await hb._model_selection(mc, "hub-gemini-4-carbon", "xhigh")

    for eff in ("low", "medium", "high", "xhigh"):
        sel = await hb._model_selection(mc, "hub-gemini-4-hydrogen", eff)
        assert sel == {
            "instanceId": "antigravity",
            "model": "gemini-4-hydrogen",
            "options": {"reasoningEffort": eff},
        }
    with pytest.raises(ValueError, match="does not support effort 'max'"):
        await hb._model_selection(mc, "hub-gemini-4-hydrogen", "max")


def test_antigravity_gemini4_dashboard_visibility_and_frontend_tokens():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    assert models.resolve_model("agy-hydrogen-xhigh") == "antigravity/gemini-4-hydrogen-xhigh"
    for raw in (
        "gemini-4-carbon-medium", "gemini-4-carbon-high", "gemini-4-carbon-low",
        "gemini-4-hydrogen-xhigh", "gemini-4-hydrogen-high", "gemini-4-hydrogen-medium", "gemini-4-hydrogen-low",
        "gemini-4-argon-medium", "gemini-pro-orchestrator",
        "claude-opus-5-5-high", "claude-sonnet-5-5-high",
    ):
        spec = models.get_model_spec(f"antigravity/{raw}")
        assert spec.default_dashboard is True
        assert spec.default_agents is False
        assert spec.context_length == 1_000_000

    css = (root / "app/static/css/design-system.css").read_text()
    for token in ("--model-carbon:", "--model-hydrogen:", "--model-argon:"):
        assert token in css

    theme_js = (root / "app/static/js/theme.js").read_text()
    for fam in ("carbon", "hydrogen", "argon"):
        assert f"['{fam}'," in theme_js

    app_js = (root / "app/static/js/app.js").read_text()
    assert "['antigravity', 'Antigravity']" in app_js
