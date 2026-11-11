"""Hub allowlist routing: real admission/lifecycle code, synthetic data and no providers."""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app import models
from app.events import MessageProvenance
from app.session import AgentSession, AgentStatus

SOL = 'hub-gpt-6.1-sol'
FORBIDDEN = [m.id for m in models.SELECTABLE_MODEL_SPECS
             if m.runtime == 'hub' and m.id not in models.ALLOWED_HUB_WORKER_MODELS]
REQUESTS = FORBIDDEN + [a for a, m in models.ALIASES.items() if m in FORBIDDEN]
PROVENANCE = MessageProvenance(origin='user', senders=('user',), subtype='dashboard')


@pytest.fixture
def admission(monkeypatch):
    # Old catalog data must never reopen a forbidden route.
    monkeypatch.setattr(models, '_load_model_flags', lambda: {
        m: {'agents': True, 'dashboard': True} for m in models.MODELS})
    monkeypatch.setattr('app.backend_hub.hub_configured', lambda: None)


@pytest.mark.parametrize('model_request', REQUESTS)
@pytest.mark.parametrize('reason', ['', 'Creative research requested by owner'])
def test_forbidden_hub_requests_refuse_even_with_old_enabled_flags(admission, model_request, reason):
    with pytest.raises(ValueError, match=models.HUB_SOL_ONLY_RULE):
        models.ensure_spawn_allowed(models.resolve_model(model_request), model_reason=reason)


def test_future_hub_route_fails_closed(admission, monkeypatch):
    spec = replace(models.get_model_spec(SOL), id='hub-future-model')
    monkeypatch.setitem(models.MODEL_SPECS, spec.id, spec)
    with pytest.raises(ValueError, match=models.HUB_SOL_ONLY_RULE):
        models.ensure_spawn_allowed(spec.id)


@pytest.mark.parametrize('model', [
    'gpt5.6luna', 'retired-codex-model', 'retired-claude-model',
    'grok-4', 'openrouter:synthetic',
])
def test_native_runtime_identity_validation_stays_with_its_owner(admission, model):
    models.ensure_hub_worker_allowed(model)
    assert models.validate_model_reason(model, 'task metadata') == ''
    # Deferring a Hub-only check does not admit an unknown native worker.
    with pytest.raises(ValueError):
        models.ensure_spawn_allowed(model)


@pytest.mark.parametrize('model', ['hub-unregistered-model', ' HUB-CLAUDE-FUTURE '])
def test_unknown_hub_identity_cannot_escape_through_native_deferral(admission, model):
    with pytest.raises(ValueError, match=models.HUB_SOL_ONLY_RULE):
        models.ensure_hub_worker_allowed(model)


@pytest.mark.parametrize('model', FORBIDDEN)
def test_api_credit_is_not_an_escape_for_forbidden_hub_models(admission, model):
    with pytest.raises(ValueError, match=models.HUB_SOL_ONLY_RULE):
        models.ensure_spawn_allowed(model, billing='api_credit', model_reason='creative')


@pytest.mark.parametrize('model_request', [
    'hubopus', 'hubsol', 'hubargon', 'hubsonnet', 'hubluna', *sorted(models.ALLOWED_HUB_WORKER_MODELS),
])
@pytest.mark.parametrize('context', [
    {},
    dict(role='worker', pipeline='custom', scope='relative', task_id=''),
    dict(role='specialist', pipeline='default', scope='/synthetic/design', task_id='V-1257'),
])
def test_allowed_hub_models_pass_existing_config_and_catalog_gates(admission, model_request, context):
    models.ensure_spawn_allowed(models.resolve_model(model_request), **context)


@pytest.mark.parametrize('model', [' HUB-GPT-6.1-SOL ', 'HUBSOL'])
def test_sol_metadata_follows_case_insensitive_canonical_resolution(admission, model):
    assert models.resolve_model(model) == SOL
    models.ensure_hub_worker_allowed(model)
    assert models.validate_model_reason(model, 'creative task metadata') == ''


@pytest.mark.asyncio
async def test_auth_startup_refresh_without_endpoint_preserves_registry(monkeypatch):
    from app import db, model_catalog
    from app.auth import is_auth_enabled

    db.init_db()
    for key in ('ANTHROPIC_BASE_URL', 'UPSTREAM_API'):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv('DASHBOARD_USER', 'fixture-operator')
    monkeypatch.setenv('DASHBOARD_PASSWORD', 'fixture-password')
    assert is_auth_enabled()
    model_catalog.apply_model_catalog()
    views = ['MODEL_SPECS', 'MODELS', 'BACKENDS', 'ALIASES', 'TOKEN_PRICES', 'CONTEXT_LIMITS', 'MODEL_PROVIDERS']
    before = {key: dict(getattr(models, key)) for key in views}
    fetch = AsyncMock(side_effect=AssertionError('external catalog request forbidden'))
    monkeypatch.setattr(models, 'fetch_models_from_proxy', fetch)

    await models.refresh_models()

    fetch.assert_not_awaited()
    assert {key: dict(getattr(models, key)) for key in views} == before


@pytest.mark.parametrize('model', FORBIDDEN)
@pytest.mark.parametrize('operation', ['spawn', 'agent_change', 'dashboard_change'])
@pytest.mark.asyncio
async def test_forbidden_requests_do_not_allocate_or_load(admission, monkeypatch, tmp_path, model, operation):
    from app import manager as module
    from app.routes import sessions
    lookup = Mock()
    loaded = AsyncMock()
    monkeypatch.setattr(module, 'get_session_by_name', lookup)
    monkeypatch.setattr(sessions.manager, 'ensure_loaded', loaded)
    if operation == 'spawn':
        manager = module.SessionManager()
        with pytest.raises(ValueError, match=models.HUB_SOL_ONLY_RULE):
            await manager.create_session('worker', str(tmp_path), str(tmp_path), model,
                                         parent_name='orchestrator', model_reason='creative')
        assert not manager.sessions
        lookup.assert_not_called()
    else:
        result = await sessions.change_model('worker', {
            'model': model, 'model_reason': 'creative',
            'via': 'mcp' if operation == 'agent_change' else 'dashboard'})
        assert result.status_code == 409
        assert models.HUB_SOL_ONLY_RULE in result.body.decode()
    loaded.assert_not_awaited()


@pytest.mark.parametrize('operation', ['send', 'preflight', 'flush', 'backend', 'reconnect', 'handoff'])
@pytest.mark.parametrize('running', [False, True])
@pytest.mark.asyncio
async def test_persisted_worker_refuses_without_clearing_inputs_history_or_latches(
    admission, monkeypatch, operation, running,
):
    worker = AgentSession(id='worker', name='worker', scope='/synthetic', cwd='/synthetic',
                          model=FORBIDDEN[0], model_reason='Old creative permission', backend_type='hub')
    worker.status = AgentStatus.RUNNING if running else AgentStatus.IDLE
    worker.session_id = 'retained-workspace'
    worker.session_id_history = [{'session_id': 'old-thread'}]
    worker._session_limit_hit = worker._manually_interrupted = True
    worker._handoff_recovery_required = True
    worker.runtime_handoff = 'Retained handoff'
    worker._pending_messages = ['queued work']
    worker._pending_owner_texts = ['queued work']
    worker._pending_owner_initiated_turn = True
    provider = AsyncMock()
    worker._backend = provider
    monkeypatch.setattr('app.session.asyncio.sleep', AsyncMock())
    snapshot = (worker.model, worker.session_id, list(worker.session_id_history), worker.runtime_handoff,
                worker._session_limit_hit, worker._manually_interrupted, worker._handoff_recovery_required)
    # Busy flush intentionally retains its queue without admission or dispatch.
    if running and operation == 'flush':
        await worker._flush_pending()
    else:
        with pytest.raises(ValueError, match=models.HUB_SOL_ONLY_RULE):
            if operation == 'send':
                await worker.send('new work', provenance=PROVENANCE)
            elif operation == 'preflight':
                await worker.preflight_delivery_admission()
            elif operation == 'flush':
                await worker._flush_pending()
            elif operation == 'backend':
                await worker._ensure_backend(force_fresh=True)
            elif operation == 'reconnect':
                await worker._reconnect_backend()
            else:
                await worker.recover_runtime_handoff({'status': 'source_released'}, [])
    assert snapshot == (worker.model, worker.session_id, worker.session_id_history, worker.runtime_handoff,
                        worker._session_limit_hit, worker._manually_interrupted, worker._handoff_recovery_required)
    assert worker._pending_messages == worker._pending_owner_texts == ['queued work']
    assert worker._pending_owner_initiated_turn
    assert not worker._lifecycle_lock.locked()
    assert provider.mock_calls == []


@pytest.mark.asyncio
async def test_manager_refuses_before_auto_switch_or_task_reset(admission, monkeypatch):
    from app.manager import SessionManager
    worker = AgentSession(id='worker', name='worker', scope='/synthetic', cwd='/synthetic',
                          model=FORBIDDEN[0], backend_type='hub', needs_switch=True)
    manager = SessionManager()
    manager.sessions[worker.id] = worker
    switch = AsyncMock()
    monkeypatch.setattr(manager, '_auto_switch_before_delivery', switch)
    with pytest.raises(ValueError, match=models.HUB_SOL_ONLY_RULE):
        await manager.send(worker.id, 'new task', provenance=PROVENANCE)
    switch.assert_not_awaited()
    assert worker.needs_switch


@pytest.mark.parametrize('model', FORBIDDEN)
@pytest.mark.parametrize('operation', ['connect', 'send', 'steer', 'retarget', 'start', 'events', 'run', 'reconnect'])
@pytest.mark.asyncio
async def test_backend_boundary_refuses_before_remote_calls_or_state_changes(monkeypatch, tmp_path, model, operation):
    from app.backend_hub import HubBackend
    from app.hub_workspace import WorkspaceState
    backend = HubBackend(model, str(tmp_path))
    state = WorkspaceState('old-workspace', str(tmp_path), '/synthetic/remote',
                           thread_id='old-thread', project_id='old-project',
                           pending_sync={'retained': True}, file_policy_blocked=True)
    backend._state = state
    backend._ssh = SimpleNamespace()
    backend._run_id = 'old-run'
    backend._pending = 'retained input'
    backend._early_steer = ['retained steer']
    backend._turn_active = operation in {'steer', 'events'}
    remote = AsyncMock()
    backend._mc = remote
    before = (backend.model, backend._pending, backend._turn_active, state.__dict__.copy())
    with pytest.raises(ValueError, match=models.HUB_SOL_ONLY_RULE):
        if operation in {'run', 'events'}:
            iterator = backend._run_turn('task') if operation == 'run' else backend.events()
            await anext(iterator)
        elif operation == 'start':
            await backend._start(remote, state, 'task')
        elif operation == 'retarget':
            backend.model = SOL
            before = (SOL, backend._pending, backend._turn_active, state.__dict__.copy())
            await backend.retarget_model(model)
        elif operation in {'send', 'steer'}:
            await backend.send('task')
        else:
            await getattr(backend, operation)()
    assert before == (backend.model, backend._pending, backend._turn_active, state.__dict__)
    assert backend._early_steer == ['retained steer']
    assert remote.mock_calls == []


@pytest.mark.asyncio
async def test_persisted_queued_delivery_recovery_fails_before_submit_and_keeps_payload(
    admission, tmp_path, monkeypatch,
):
    from app import db, message_deliveries as deliveries, pipeline
    from app.manager import SessionManager
    db.init_db()
    monkeypatch.setattr(pipeline, 'PIPELINES_DIR', Path(__file__).resolve().parents[1] / '.orchestra/pipelines')
    pipeline.load_pipeline.cache_clear()
    manager = SessionManager()
    worker = AgentSession(id='worker', name='worker', scope=str(tmp_path), cwd=str(tmp_path),
                          model=FORBIDDEN[0], model_reason='old permission', backend_type='hub',
                          session_id='retained-workspace', runtime_handoff='old handoff')
    db.save_session(worker._to_db_dict())
    worker = await manager._load_from_db(db.get_session(worker.id))
    await worker._drain_persist()
    provider = AsyncMock()
    worker._backend = provider
    delivery_id = '00000000-0000-4000-8000-000000001240'
    monkeypatch.setattr(deliveries, 'ensure_target_runner', Mock())
    monkeypatch.setattr(deliveries, 'notify_message_delivery_failure', AsyncMock())
    receipt, status = await deliveries.accept_message_delivery(
        delivery_id=delivery_id, source_principal='synthetic:owner', source_scope=str(tmp_path),
        target_session_id=worker.id, target_name=worker.name, target_scope=worker.scope,
        target_generation=(f'session={worker.id}|task={worker.task_id}|'
                           f'branch={worker.branch}|needs_switch=0'),
        message='queued source task', rendered_message='queued source task', provenance=PROVENANCE)
    assert status == 202
    await deliveries.recover_message_deliveries(target_session_id=worker.id)
    with pytest.raises(ValueError, match=models.HUB_SOL_ONLY_RULE):
        await deliveries.run_message_delivery(delivery_id, manager)
    row = dict(deliveries._row(delivery_id))
    assert row['state'] == 'FAILED_BEFORE_SUBMIT'
    assert row['message'] == row['rendered_message'] == 'queued source task'
    assert models.HUB_SOL_ONLY_RULE in row['error_json']
    persisted = db.get_session(worker.id)
    assert persisted['model'] == FORBIDDEN[0]
    assert persisted['model_reason'] == 'old permission'
    assert persisted['session_id'] == 'retained-workspace'
    assert persisted['runtime_handoff'] == 'old handoff'
    assert provider.mock_calls == []
    pipeline.load_pipeline.cache_clear()


def test_only_the_owner_hub_stack_is_enabled_for_agents_by_default(monkeypatch):
    # 04.11.2026: Sol, Argon, Sonnet, Luna; 09.11.2026 adds Opus 5.5 (xhigh) to that stack.
    monkeypatch.setattr(models, '_load_model_flags', lambda: {})
    enabled = {
        spec.id for spec in models.SELECTABLE_MODEL_SPECS
        if spec.runtime == 'hub' and models.get_model_flags(spec.id)['agents']
    }
    assert enabled == models.ALLOWED_HUB_WORKER_MODELS == {
        'hub-claude-opus-5-5', 'hub-claude-sonnet-5-5', 'hub-gemini-4-argon',
        'hub-gpt-6.1-sol', 'hub-gpt-6-luna', 'hub-gpt-6-astra',
    }
