"""The real manifest must deliver the owner's Terra High orchestrator choice."""

from fastapi import Response
import pytest

from app import models, pipeline
from app.routes.sessions import CreateSessionRequest
from app.routes.system import list_models
from app.runtime_registry import BackendBuildContext, build_backend

TERRA = "gpt-6.1-terra"


@pytest.fixture(autouse=True)
def isolated_state():
    from app.db import init_db

    init_db()
    pipeline.load_pipeline.cache_clear()
    yield
    pipeline.load_pipeline.cache_clear()


@pytest.mark.parametrize("role_name", ["orchestrator", "sub-orchestrator"])
def test_real_role_default_reaches_native_backend_with_explicit_high(role_name, tmp_path):
    role = pipeline.get_role("default", role_name)
    assert role.is_orchestrator
    assert models.resolve_model(role.model) == TERRA
    assert role.effort[TERRA] == "high"
    request = CreateSessionRequest(
        name="new-orchestrator", cwd=str(tmp_path), is_orchestrator=True,
        pipeline="default", role=role_name,
    )
    assert request.model == TERRA
    backend = build_backend("codex", BackendBuildContext(
        model=request.model, provider=models.get_model_spec(request.model).provider,
        cwd=str(tmp_path), system_prompt="", resume_session_id=None, mcp_servers={},
        is_orchestrator=True, scope=str(tmp_path), pipeline="default", role=role_name,
        profile="personal", effort=pipeline.resolve_effort(role.effort, request.model, "codex"),
        context_limit=models.get_model_spec(request.model).context_length,
        validation_profile=True,
    ))
    assert backend.model == TERRA
    assert backend.reasoning_effort == "high"
    assert not backend.is_alive


@pytest.mark.asyncio
async def test_real_default_reaches_picker_api_without_becoming_available_to_agents():
    result = await list_models(Response())
    assert result["default_orchestrator_model"] == TERRA
    terra = next(entry for entry in result["models"] if entry["id"] == TERRA)
    assert terra["provider"] == "openai" and terra["runtime"] == "codex"
    assert models.get_model_flags(TERRA) == {"dashboard": True, "agents": False}
    models.ensure_dashboard_visible(TERRA)
    models.set_model_flags(TERRA, dashboard=False)
    assert (await list_models(Response()))["default_orchestrator_model"] is None


@pytest.mark.parametrize("role_name", ["orchestrator", "sub-orchestrator"])
@pytest.mark.parametrize("selected", ["sol", "sonnet", "luna"])
def test_manual_explicit_model_overrides_real_terra_default(role_name, selected, tmp_path):
    request = CreateSessionRequest(
        name="manual-choice", cwd=str(tmp_path), is_orchestrator=True,
        pipeline="default", role=role_name, model=selected,
    )
    assert request.model == models.resolve_model(selected)


def test_worker_defaults_and_native_admission_do_not_follow_orchestrator_default(monkeypatch, tmp_path):
    config = pipeline.load_pipeline("default")
    assert models.resolve_model(config.defaults.model) == "claude-opus-5-5[1m]"
    for name, expected in [
        ("worker", "claude-sonnet-5-5[1m]"), ("full-cycle", "claude-sonnet-5-5[1m]"),
        ("reducer", "gpt-6-luna"),
    ]:
        role = pipeline.get_role("default", name)
        assert not role.is_orchestrator
        assert models.resolve_model(role.model) == expected
    worker = CreateSessionRequest(name="worker", cwd=str(tmp_path), pipeline="default", role="worker")
    assert worker.model == "claude-sonnet-5-5[1m]"
    assert models.resolve_model("sol") == models.resolve_model("codex") == "gpt-6.1-sol"
    monkeypatch.setattr(models, "_load_model_flags", lambda: {
        model: {"dashboard": True, "agents": True} for model in models.MODELS
    })
    monkeypatch.setattr("app.backend_hub.hub_configured", lambda: None)
    models.ensure_spawn_allowed(models.resolve_model("hubsol"))
    models.ensure_spawn_allowed(models.resolve_model("luna"), model_reason="protected work")
    for model in (TERRA, "gpt-6.1-sol", "claude-opus-5-5[1m]"):
        for reason in ("", "protected work"):
            with pytest.raises(ValueError, match="disabled for agents"):
                models.ensure_spawn_allowed(model, model_reason=reason)
    with pytest.raises(ValueError, match="disabled for agents"):
        models.ensure_spawn_allowed(models.resolve_model("luna"))
    assert models.get_model_flags(TERRA)["agents"] is False


def test_terra_high_default_retains_manual_only_billing_boundary():
    with pytest.raises(ValueError, match="requires a Claude model"):
        models.ensure_spawn_allowed(TERRA, billing="api_credit", model_reason="protected work")
