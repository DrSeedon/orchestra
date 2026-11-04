"""General and specialist Hub admission with synthetic identity and no provider execution."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app import models, hub_pool, hub_workspace as hw
from app.backend_hub import HUB_MODELS, HubBackend
from app.events import MessageProvenance
from app.session import AgentSession

ARGON = models.HUB_ARGON_MODEL
SOL = models.HUB_SOL_MODEL
PROVENANCE = MessageProvenance(origin="user", senders=("user",), subtype="dashboard")


@pytest.fixture(autouse=True)
def _stable_worker_quota():
    # Exercise real admission with the offline Hub-pool fixture, not conftest's
    # generic not-applicable quota stub. No telemetry/provider calls are made.
    pass


def identity(scope="/synthetic/design"):
    return dict(role="specialist", pipeline="default", scope=scope, task_id="V-1257")


@pytest.fixture
def admission(monkeypatch):
    monkeypatch.setattr(models, "_load_model_flags", lambda: {
        m: {"agents": True, "dashboard": True} for m in models.MODELS})
    monkeypatch.setattr("app.backend_hub.hub_configured", lambda: None)
    monkeypatch.setattr(hw, "known_secret_values", lambda *args: [])


@pytest.mark.parametrize("field,value", [
    ("role", ""), ("role", "worker"), ("role", "full-cycle"),
    ("role", "reducer"), ("role", "old-specialist"), ("role", "Specialist"), ("role", "designer"),
    ("pipeline", ""), ("pipeline", "other"),
    ("scope", ""), ("scope", "relative"), ("scope", "/"),
    ("task_id", ""), ("task_id", "design"), ("task_id", "0"), ("task_id", None),
])
def test_argon_admitted_independently_of_role_pipeline_task_and_scope(admission, field, value):
    context = identity()
    models.ensure_spawn_allowed(ARGON, **context)
    context[field] = value
    models.ensure_spawn_allowed(ARGON, model_reason="owner design request", **context)
    models.ensure_spawn_allowed(SOL, **context)


def test_registry_mapping_and_unknown_metadata_are_honest():
    assert HUB_MODELS[ARGON] == ("antigravity", "gemini-4-argon")
    spec = models.get_model_spec(ARGON)
    assert (spec.runtime, spec.provider) == ("hub", "multicode")
    assert spec.context_length == 0 and spec.input_modalities == ()
    assert spec.price_input is None and spec.price_output is None
    assert models.resolve_model("hubargon") == ARGON
    assert spec.name == "Hub: Gemini 4 Argon"
    models.validate_model_registry()


def test_specialist_does_not_restore_other_models_or_credit_routes(admission):
    for spec in models.SELECTABLE_MODEL_SPECS:
        if spec.runtime == "hub" and spec.id not in models.ALLOWED_HUB_WORKER_MODELS:
            with pytest.raises(ValueError, match=models.HUB_SOL_ONLY_RULE):
                models.ensure_spawn_allowed(spec.id, **identity())
    with pytest.raises(ValueError, match="billing"):
        models.ensure_spawn_allowed(ARGON, billing="api_credit", **identity())
    assert models.validate_model_reason(ARGON, "optional metadata") == ""
    assert models.validate_model_reason(ARGON, "not a permission", **identity()) == ""


def test_catalog_and_configuration_remain_required(admission, monkeypatch):
    monkeypatch.setattr("app.backend_hub.hub_configured", lambda: "synthetic unconfigured hub")
    with pytest.raises(ValueError, match="unconfigured"):
        models.ensure_spawn_allowed(ARGON, **identity())
    monkeypatch.setattr("app.backend_hub.hub_configured", lambda: None)
    monkeypatch.setattr(models, "_load_model_flags", lambda: {ARGON: {"agents": False}})
    with pytest.raises(ValueError, match="disabled for agents"):
        models.ensure_spawn_allowed(ARGON, **identity())


def test_real_pipeline_assembles_terminal_argon_specialist():
    from app import pipeline
    from app.manager import ROLE_SYSTEM_PROMPT

    pipeline.load_pipeline.cache_clear()
    cfg = pipeline.load_pipeline("default")
    role = pipeline.get_role("default", "specialist")
    assert cfg.roles["specialist"].model == ARGON
    assert role.model == cfg.roles["specialist"].model
    assert role.can_spawn == []
    assert set(role.skills) == set(cfg.defaults.skills)
    assert "hub_generate_image" in role.disabled_tools
    assert pipeline.resolve_effort(role.effort, ARGON, "hub") == "high"
    assembled = ROLE_SYSTEM_PROMPT("default", "specialist")
    for rel in ("base.md", "roles/specialist.md", "modules/model-routing.md"):
        assert pipeline.prompt_path("default", rel).read_text().strip() in assembled
    for parent in ("orchestrator", "sub-orchestrator", "full-cycle"):
        pipeline.validate_spawn("default", parent, "specialist")
    with pytest.raises(ValueError):
        pipeline.validate_spawn("default", "specialist", "worker")
    for name in ("worker", "full-cycle", "reducer"):
        assert cfg.roles[name].model == SOL


class CatalogHub:
    def __init__(self):
        self.calls = []

    async def tool_call(self, name, args):
        self.calls.append((name, args))
        if name == "orchestrator_capabilities":
            return {"providers": [{"providerInstanceId": "antigravity", "models": [{
                "id": "gemini-4-argon", "options": [{
                    "id": "reasoningEffort", "type": "select",
                    "options": [{"id": v} for v in ("low", "medium", "high")],
                }],
            }]}]}
        return {"threadId": "synthetic-thread", "runId": "synthetic-run"}


def backend_fixture(context=None, effort="high"):
    context = identity() if context is None else context
    backend = HubBackend(ARGON, ".", scope=context["scope"], effort=effort,
                         context_source=lambda: context)
    hub = CatalogHub()
    backend._mc = hub
    backend._ssh = SimpleNamespace(assert_file_policy=AsyncMock())
    state = hw.WorkspaceState("synthetic-workspace", ".", "/synthetic/copy",
                              project_id="synthetic-project")
    state.save = lambda: None
    backend._state = state
    return backend, hub, state, context


def test_specialist_role_reaches_trimmed_hub_prompt_and_resumed_turn(monkeypatch):
    from app import backend_hub, pipeline

    monkeypatch.setattr(backend_hub, "_branch_task_ref", lambda *args: "#V-1257")
    backend, _, _, _ = backend_fixture()
    source = pipeline.prompt_path("default", "roles/specialist.md").read_text().strip()
    assert backend._prompt("safe design task", first=True).count(source) == 1
    assert backend._prompt("continue design", first=False).count(source) == 1
    ordinary = HubBackend(SOL, ".", role="worker", pipeline="default")
    assert source not in ordinary._prompt("ordinary task", first=True)
    assert source not in ordinary._prompt("ordinary continuation", first=False)


@pytest.mark.asyncio
@pytest.mark.parametrize("effort", ["low", "medium", "high"])
async def test_argon_selection_and_resume_use_exact_catalog_effort(admission, effort):
    backend, hub, state, _ = backend_fixture(effort=effort)
    assert await backend._start(hub, state, "safe design source") == "synthetic-run"
    launch = hub.calls[-1][1]
    assert launch["modelSelection"] == {
        "instanceId": "antigravity", "model": "gemini-4-argon",
        "options": {"reasoningEffort": effort},
    }
    assert "runtimeMode" not in launch
    await backend._start(hub, state, "continue the same design")
    assert [name for name, _ in hub.calls][-2:] == ["t3_thread_configure", "t3_thread_send"]
    assert sum(name == "orchestrator_capabilities" for name, _ in hub.calls) == 1
    event = backend._turn_end(True, "end_turn", "")
    assert event.metadata["max_tokens"] == 0


@pytest.mark.asyncio
async def test_unsupported_effort_never_launches(admission):
    backend, hub, state, _ = backend_fixture(effort="xhigh")
    with pytest.raises(ValueError, match="allowed values"):
        await backend._start(hub, state, "safe design")
    assert [name for name, _ in hub.calls] == ["orchestrator_capabilities"]
    assert not state.thread_id


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["connect", "send", "retarget", "reconnect", "events", "turn", "start"])
@pytest.mark.parametrize("field,value", [("role", "worker"), ("task_id", ""), ("scope", "/other/project")])
async def test_backend_refuses_forbidden_route_in_every_live_context(admission, operation, field, value):
    backend, hub, state, context = backend_fixture()
    backend._pending = "retained design input"
    backend._turn_active = True
    context[field] = value
    backend.model = "hub-claude-opus-5-5"
    before = (backend.model, backend._pending, backend._turn_active, dict(state.__dict__))
    with pytest.raises(ValueError, match=models.HUB_SOL_ONLY_RULE):
        if operation == "connect":
            await backend.connect()
        elif operation == "send":
            await backend.send("new input")
        elif operation == "retarget":
            await backend.retarget_model("hub-claude-opus-5-5")
        elif operation == "reconnect":
            await backend.reconnect()
        elif operation == "events":
            _ = [event async for event in backend.events()]
        elif operation == "turn":
            _ = [event async for event in backend._run_turn("new input")]
        else:
            await backend._start(hub, state, "new input")
    assert before == (backend.model, backend._pending, backend._turn_active, state.__dict__)
    assert hub.calls == []


def test_factory_admits_argon_after_task_role_and_scope_change(admission):
    worker = AgentSession(id="specialist", name="specialist", cwd="/synthetic/design", model=ARGON,
                          backend_type="hub", **identity())
    backend = worker._make_backend()
    backend._ensure_model_allowed()
    worker.task_id = ""
    backend._ensure_model_allowed()
    worker.role = "worker"
    worker.scope = "/other/project"
    backend._ensure_model_allowed()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["preflight", "send", "flush", "backend", "reconnect", "handoff"])
async def test_forbidden_session_preserves_recovery(admission, operation):
    context = identity()
    context["role"] = "worker"
    worker = AgentSession(id="old", name="specialist-by-name", cwd=context["scope"],
                          model="hub-claude-opus-5-5", backend_type="hub", model_reason="specialist", **context)
    worker.session_id = "retained-workspace"
    worker._session_limit_hit = worker._manually_interrupted = True
    worker._handoff_recovery_required = True
    worker._pending_messages = ["retained design"]
    worker._pending_owner_texts = ["retained design"]
    worker.session_id_history = [{"session_id": "retained-history"}]
    provider = AsyncMock()
    worker._backend = provider
    before = (worker.model, worker.session_id, list(worker.session_id_history),
              worker._session_limit_hit, worker._manually_interrupted, worker._handoff_recovery_required)
    with pytest.raises(ValueError, match=models.HUB_SOL_ONLY_RULE):
        if operation == "preflight":
            await worker.preflight_delivery_admission()
        elif operation == "send":
            await worker.send("new design", provenance=PROVENANCE)
        elif operation == "flush":
            await worker._flush_pending()
        elif operation == "backend":
            await worker._ensure_backend(force_fresh=True)
        elif operation == "reconnect":
            await worker._reconnect_backend()
        else:
            await worker.recover_runtime_handoff({"status": "source_released"}, [])
    assert before == (worker.model, worker.session_id, worker.session_id_history,
                      worker._session_limit_hit, worker._manually_interrupted, worker._handoff_recovery_required)
    assert worker._pending_messages == worker._pending_owner_texts == ["retained design"]
    assert not worker._lifecycle_lock.locked()
    assert provider.mock_calls == []


@pytest.mark.asyncio
async def test_persisted_specialist_reloads_and_passes_normal_preflight(admission, tmp_path):
    from app import db
    from app.manager import SessionManager

    db.init_db()
    worker = AgentSession(id="persisted", name="specialist", cwd=str(tmp_path), model=ARGON,
                          backend_type="hub", **identity(str(tmp_path)))
    worker.session_id = "retained-workspace"
    worker.session_id_history = [{"session_id": "prior-history"}]
    db.save_session(worker._to_db_dict())
    manager = SessionManager()
    restored = await manager._load_from_db(db.get_session(worker.id))
    assert models.hub_worker_context(restored) == identity(str(tmp_path))
    assert restored.session_id == worker.session_id
    assert restored.session_id_history == worker.session_id_history
    await restored.preflight_delivery_admission()
    assert not restored._lifecycle_lock.locked()


@pytest.mark.asyncio
async def test_forbidden_queued_delivery_refuses_before_submit_and_keeps_payload(admission, tmp_path, monkeypatch):
    from app import db, message_deliveries as deliveries
    from app.manager import SessionManager

    db.init_db()
    context = identity(str(tmp_path))
    context["role"] = "worker"
    worker = AgentSession(id="old-argon", name="specialist-by-name", cwd=str(tmp_path),
                          model="hub-claude-opus-5-5", backend_type="hub", session_id="retained-workspace", **context)
    worker.session_id_history = [{"session_id": "retained-history"}]
    db.save_session(worker._to_db_dict())
    manager = SessionManager()
    restored = await manager._load_from_db(db.get_session(worker.id))
    await restored._drain_persist()
    provider = AsyncMock()
    restored._backend = provider
    manager.sessions[restored.id] = restored
    delivery_id = "7b34bf37-c388-48c7-8071-13a2cf1ef70b"
    monkeypatch.setattr(deliveries, "ensure_target_runner", Mock())
    monkeypatch.setattr(deliveries, "notify_message_delivery_failure", AsyncMock())
    _, status = await deliveries.accept_message_delivery(
        delivery_id=delivery_id, source_principal="synthetic:owner", source_scope=str(tmp_path),
        target_session_id=restored.id, target_name=restored.name, target_scope=restored.scope,
        target_generation=(f"session={restored.id}|task={restored.task_id}|"
                           f"branch={restored.branch}|needs_switch=0"),
        message="retained queued design", rendered_message="retained queued design", provenance=PROVENANCE,
    )
    assert status == 202
    await deliveries.recover_message_deliveries(target_session_id=restored.id)
    with pytest.raises(ValueError, match=models.HUB_SOL_ONLY_RULE):
        await deliveries.run_message_delivery(delivery_id, manager)
    row = dict(deliveries._row(delivery_id))
    assert row["state"] == "FAILED_BEFORE_SUBMIT"
    assert row["message"] == row["rendered_message"] == "retained queued design"
    assert db.get_session(worker.id)["session_id"] == "retained-workspace"
    assert restored.session_id_history == worker.session_id_history
    assert provider.mock_calls == []


@pytest.mark.asyncio
async def test_spawn_resolves_task_and_publishes_dedicated_role(admission, monkeypatch, tmp_path):
    from app import db, manager as module, tm

    db.init_db()
    task = {"id": "synthetic-task", "ref_prefix": "V", "par_number": 1257}
    resolve = Mock(return_value=task)
    publish = Mock()
    start = AsyncMock()
    monkeypatch.setattr(tm, "resolve_scoped_task_identity", resolve)
    monkeypatch.setattr(module, "publish_ready_session", publish)
    monkeypatch.setattr(module.AgentSession, "start", start)
    monkeypatch.setattr(module.private_folder, "ensure_main_private", Mock())
    monkeypatch.setattr(module, "_scaffold_role_docs", Mock())
    manager = module.SessionManager()
    worker = await manager.create_session(
        "specialist", str(tmp_path), str(tmp_path), ARGON, parent_name="root",
        role="specialist", pipeline="default", task_id="V-1257", owned_dirs=["design"],
    )
    assert models.hub_worker_context(worker) == identity(str(tmp_path))
    assert worker.model == ARGON and worker.effort == "high"
    resolve.assert_called_once_with(str(tmp_path), "V-1257")
    assert publish.call_args.args[1] == task
    start.assert_awaited_once_with(persist=False)


@pytest.mark.asyncio
async def test_spawn_keeps_task_ownership_refusal_before_backend(admission, monkeypatch, tmp_path):
    from app import db, manager as module, tm

    db.init_db()
    start = AsyncMock()
    publish = Mock()
    monkeypatch.setattr(module.AgentSession, "start", start)
    monkeypatch.setattr(module, "publish_ready_session", publish)
    monkeypatch.setattr(tm, "resolve_scoped_task_identity", Mock(side_effect=ValueError("task belongs to another scope")))
    manager = module.SessionManager()
    with pytest.raises(ValueError, match="another scope"):
        await manager.create_session("specialist", str(tmp_path), str(tmp_path), ARGON,
                                     parent_name="root", role="specialist", task_id="V-1257")
    assert not manager.sessions
    start.assert_not_awaited()
    publish.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["specialist", "worker"])
async def test_direct_model_change_checks_current_session(admission, monkeypatch, role):
    context = identity()
    context["role"] = role
    worker = AgentSession(id="target", name="target", cwd=context["scope"], model=SOL,
                          backend_type="hub", **context)
    change = AsyncMock(return_value={"ok": True, "changed": False})
    monkeypatch.setattr(worker, "_change_model_locked", change)
    monkeypatch.setattr(worker, "_persist", Mock())
    result = await worker.change_model(ARGON, "design name and tag")
    assert result["ok"]
    change.assert_awaited_once_with(ARGON)


@pytest.mark.asyncio
@pytest.mark.parametrize("via", ["mcp", "dashboard"])
@pytest.mark.parametrize("role", ["specialist", "worker"])
async def test_change_route_accepts_argon_for_worker_and_specialist(admission, monkeypatch, via, role):
    from app.routes import sessions

    context = identity()
    context["role"] = role
    target = SimpleNamespace(**context, change_model=AsyncMock(return_value={"ok": True, "changed": False}))
    loaded = AsyncMock(return_value=target)
    monkeypatch.setattr(sessions.manager, "ensure_loaded", loaded)
    result = await sessions.change_model("target", {
        "model": ARGON, "scope": context["scope"], "via": via,
        "role": "specialist", "pipeline": "default", "task_id": "V-1257",
        "model_reason": "owner says design", "tags": ["design"],
    })
    assert result["ok"]
    target.change_model.assert_awaited_once_with(ARGON, model_reason="owner says design")
    loaded.assert_awaited_once_with("target", context["scope"])


@pytest.mark.asyncio
async def test_change_route_keeps_scoped_session_lookup(admission, monkeypatch):
    from app import db
    from app.routes import sessions

    db.init_db()
    loaded = AsyncMock(return_value=None)
    monkeypatch.setattr(sessions.manager, "ensure_loaded", loaded)
    result = await sessions.change_model("target", {"model": "hubargon", "scope": "/synthetic/design"})
    assert result.status_code == 404
    loaded.assert_awaited_once_with("target", "/synthetic/design")


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["available", "blocked", "unknown"])
async def test_antigravity_capacity_is_checked_not_skipped(monkeypatch, state):
    from app.quota_gate import get_worker_admission, require_worker_admission, QuotaGateError

    assert hub_pool.provider_for_model(ARGON) == "antigravity"
    summary = {"available": state != "unknown", "cached_age_s": 0, "providers": {}}
    if state != "unknown":
        summary["providers"]["antigravity"] = {
            "usable": int(state == "available"), "accounts": 1, "unknown": 0, "threshold_pct": 100,
        }
    fetch = AsyncMock(return_value=summary)
    monkeypatch.setattr(hub_pool, "get_hub_pool", fetch)
    decision = await get_worker_admission(ARGON)
    assert decision.state == state
    if state == "blocked":
        with pytest.raises(QuotaGateError):
            require_worker_admission(decision)
    else:
        require_worker_admission(decision)
    if state == "unknown":
        assert "capacity was not checked" in decision.reason
    fetch.assert_awaited_once()


def test_antigravity_pool_sanitizes_accounts_and_missing_windows():
    result = hub_pool.summarize_relay_limits({"providers": {"antigravity": {
        "active_id": "private-account", "ids": [{
            "id": "private-account", "email": "private@example.invalid", "windows": [],
        }],
    }}})
    public = json.dumps(result)
    assert "private-account" not in public and "private@example.invalid" not in public
    block = result["providers"]["antigravity"]
    assert (block["usable"], block["unknown"], block["windows"]) == (0, 1, [])
