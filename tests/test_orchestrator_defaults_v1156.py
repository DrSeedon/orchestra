"""Safe default-selection mechanics before the separately gated Terra manifest."""

from pathlib import Path
import json
import shutil
import subprocess

from fastapi import Response
import pytest

from app import models, pipeline
from app.routes.sessions import CreateSessionRequest
from app.routes.system import list_models
from app.runtime_registry import BackendBuildContext, build_backend

OPUS = "claude-opus-5-5[1m]"
TERRA = "gpt-6.1-terra"
LEGACY = """name: default
defaults:
  model: sonnet
  skills: []
roles:
  orchestrator:
    kind: orchestrator
    label: Orchestrator
    model: claude-opus-5-5[1m]
    effort: {"claude-opus-5-5[1m]": high, default: low}
  sub-orchestrator:
    kind: orchestrator
    label: Sub-Orchestrator
    model: claude-opus-5-5[1m]
    effort: {"claude-opus-5-5[1m]": high, default: low}
  worker:
    kind: worker
    label: Worker
    model: sonnet
    effort: medium
"""


@pytest.fixture
def manifest(tmp_path, monkeypatch):
    from app.db import init_db

    init_db()
    root = tmp_path / "pipelines"
    folder = root / "default"
    folder.mkdir(parents=True)
    path = folder / "pipeline.yaml"
    path.write_text(LEGACY)
    monkeypatch.setattr(pipeline, "PIPELINES_DIR", root)
    pipeline.load_pipeline.cache_clear()
    yield path
    pipeline.load_pipeline.cache_clear()


@pytest.fixture
def old_registry(monkeypatch):
    monkeypatch.delitem(models.MODELS, TERRA)
    for alias, model in list(models.ALIASES.items()):
        if model == TERRA:
            monkeypatch.delitem(models.ALIASES, alias)


@pytest.mark.asyncio
async def test_existing_manifest_and_registry_without_terra_keep_catalog_and_request_working(
    manifest, old_registry, tmp_path,
):
    result = await list_models(Response())
    assert result["default_orchestrator_model"] == OPUS
    assert OPUS in {entry["id"] for entry in result["models"]}
    assert TERRA not in {entry["id"] for entry in result["models"]}
    request = CreateSessionRequest(name="new-orchestrator", cwd=str(tmp_path), is_orchestrator=True)
    assert request.model == OPUS


@pytest.mark.parametrize("role_name", ["orchestrator", "sub-orchestrator"])
@pytest.mark.parametrize("explicit", [None, "sol", "sonnet"])
def test_request_role_default_is_used_only_when_model_omitted(manifest, tmp_path, role_name, explicit):
    values = dict(name="new-orchestrator", cwd=str(tmp_path), is_orchestrator=True,
                  pipeline="default", role=role_name)
    if explicit is not None:
        values["model"] = explicit
    request = CreateSessionRequest(**values)
    assert request.model == (models.resolve_model(explicit) if explicit else OPUS)


def test_worker_and_explicit_ad_hoc_request_keep_existing_defaults(manifest, tmp_path, monkeypatch):
    def no_manifest_lookup(*args):
        raise AssertionError("explicit and worker requests do not resolve an orchestrator default")

    monkeypatch.setattr(pipeline, "get_role", no_manifest_lookup)
    worker = CreateSessionRequest(name="worker", cwd=str(tmp_path), pipeline="default", role="worker")
    assert worker.model == "claude-sonnet-5-5[1m]"
    explicit = CreateSessionRequest(name="explicit", cwd=str(tmp_path), is_orchestrator=True, model="sol")
    assert explicit.model == "gpt-6.1-sol"
    with pytest.raises(ValueError, match="repo_path required"):
        CreateSessionRequest(name="invalid-worktree", cwd=str(tmp_path), is_orchestrator=True, use_worktree=True)


@pytest.mark.asyncio
async def test_catalog_default_is_visibility_filtered(manifest):
    models.set_model_flags(OPUS, dashboard=False)
    result = await list_models(Response())
    assert result["default_orchestrator_model"] is None
    assert OPUS not in {entry["id"] for entry in result["models"]}
    models.set_model_flags(OPUS, dashboard=True)
    assert (await list_models(Response()))["default_orchestrator_model"] == OPUS


@pytest.mark.asyncio
@pytest.mark.parametrize("content", [None, "not: [valid", LEGACY.replace(OPUS, "unknown-model")])
async def test_unavailable_pipeline_does_not_break_catalog_or_enable_an_unknown_default(manifest, content, tmp_path):
    before = {entry["id"] for entry in (await list_models(Response()))["models"]}
    if content is None:
        manifest.unlink()
    else:
        manifest.write_text(content)
    pipeline.load_pipeline.cache_clear()
    result = await list_models(Response())
    assert result["default_orchestrator_model"] is None
    assert {entry["id"] for entry in result["models"]} == before
    with pytest.raises(ValueError):
        CreateSessionRequest(name="invalid-default", cwd=str(tmp_path), is_orchestrator=True)


def test_worker_routing_and_protected_luna_exception_are_unchanged(manifest, monkeypatch):
    monkeypatch.setattr(models, "_load_model_flags", lambda: {
        model: {"dashboard": True, "agents": True} for model in models.MODELS
    })
    monkeypatch.setattr("app.backend_hub.hub_configured", lambda: None)
    models.ensure_spawn_allowed(models.resolve_model("hubsol"))
    models.ensure_spawn_allowed(models.resolve_model("luna"), model_reason="protected work")
    for model in (TERRA, "gpt-6.1-sol", OPUS, "gpt-6-luna"):
        with pytest.raises(ValueError, match="disabled for agents"):
            models.ensure_spawn_allowed(model)
    assert models.get_model_flags(TERRA)["agents"] is False


@pytest.mark.asyncio
async def test_future_manifest_is_rejected_without_terra_then_resolves_high_after_registration(
    manifest, tmp_path, monkeypatch,
):
    manifest.write_text(LEGACY.replace(OPUS, TERRA))
    with monkeypatch.context() as old:
        old.delitem(models.MODELS, TERRA)
        for alias, model in list(models.ALIASES.items()):
            if model == TERRA:
                old.delitem(models.ALIASES, alias)
        pipeline.load_pipeline.cache_clear()
        assert (await list_models(Response()))["default_orchestrator_model"] is None
        with pytest.raises(ValueError, match="unknown model"):
            CreateSessionRequest(name="too-early", cwd=str(tmp_path), is_orchestrator=True)
    pipeline.load_pipeline.cache_clear()
    assert (await list_models(Response()))["default_orchestrator_model"] == TERRA
    request = CreateSessionRequest(name="future", cwd=str(tmp_path), is_orchestrator=True)
    role = pipeline.get_role("default", "orchestrator")
    assert request.model == TERRA
    assert pipeline.resolve_effort(role.effort, request.model, "codex") == "high"
    backend = build_backend("codex", BackendBuildContext(
        model=request.model, provider="openai", cwd=str(tmp_path), system_prompt="",
        resume_session_id=None, mcp_servers={}, is_orchestrator=True, scope=str(tmp_path),
        pipeline="default", role="orchestrator", profile="personal",
        effort=pipeline.resolve_effort(role.effort, request.model, "codex"),
        context_limit=258400, validation_profile=True,
    ))
    assert backend.model == TERRA and backend.reasoning_effort == "high"
    assert not backend.is_alive


def test_picker_tracks_automatic_default_but_keeps_explicit_user_selection():
    node = shutil.which("node")
    if not node:
        pytest.skip("node required for offline selector behavior")
    source = (Path(__file__).resolve().parents[1] / "app/static/js/app.js").read_text()
    function = source[source.index("function _renderModels(data) {"):source.index("\nasync function _loadModelsNow()")]
    script = r'''
let _MODELS = [], _modelsLoaded = false;
const handlers = [];
const select = {value: '', dataset: {}, options: [],
 set innerHTML(value) { this.options = []; this.value = ''; },
 addEventListener(type, fn) { if (type === 'change') handlers.push(fn); },
 appendChild(opt) { this.options.push(opt); if (this.options.length === 1) this.value = opt.value; }};
const $ = () => select, document = {createElement: () => ({})};
const _updateProxyStatus = () => {};
''' + function + r'''
const models = ['fable', 'opus', 'terra', 'sol'].map(id => ({id, name:id}));
function render(preferred, items=models) { _renderModels({models:items,default_orchestrator_model:preferred}); return select.value; }
const initial = render('opus');
const automaticChanged = render('terra');
select.value = 'sol'; handlers.forEach(fn => fn());
const explicitPreserved = render('terra');
const removed = render('terra', models.filter(model => model.id !== 'sol'));
const returned = render('terra');
const hidden = render(null, models.filter(model => model.id !== 'terra'));
_renderModels({models}); const legacy = select.value;
console.log(JSON.stringify({initial,automaticChanged,explicitPreserved,removed,returned,hidden,legacy,listeners:handlers.length}));
'''
    result = subprocess.run([node, "-e", script], check=True, capture_output=True, text=True, timeout=10)
    assert json.loads(result.stdout) == {
        "initial": "opus", "automaticChanged": "terra", "explicitPreserved": "sol",
        "removed": "terra", "returned": "terra", "hidden": "fable", "legacy": "fable", "listeners": 1,
    }


def test_opening_new_orchestrator_refreshes_default_from_server():
    node = shutil.which("node")
    if not node:
        pytest.skip("node required for offline selector behavior")
    source = (Path(__file__).resolve().parents[1] / "app/static/js/app.js").read_text()
    start = source.index("$('#new-orch-btn').addEventListener('click',")
    binding = source[start:source.index("\n    });", start) + len("\n    });")]
    script = r'''
let callback, models=0, profiles=0, pipelines=0;
const element = {classList:{add(){},remove(){}},focus(){}};
const $ = selector => selector === '#new-orch-btn'
 ? {addEventListener(type, fn) { callback=fn; }} : element;
const loadModels = () => { models++; };
const loadProfilesDropdown = () => { profiles++; };
const loadPipelinesDropdown = () => { pipelines++; };
''' + binding + r'''
callback();
console.log(JSON.stringify({models,profiles,pipelines}));
'''
    result = subprocess.run([node, "-e", script], check=True, capture_output=True, text=True, timeout=10)
    assert json.loads(result.stdout) == {"models": 1, "profiles": 1, "pipelines": 1}
