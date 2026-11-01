"""V-1119: exercise agent refusal, manual/recovery boundaries and opt-in billing."""
from unittest.mock import AsyncMock

import pytest

from app import models
from scripts import wf_adapters

NATIVE = [spec.id for spec in models.SELECTABLE_MODEL_SPECS if spec.runtime != 'hub']
HUB = ['hubsol', 'hubsonnet', 'hubopus', 'hubhaiku', 'hubluna', 'hubgrok']


@pytest.fixture
def admission(monkeypatch):
    from app import backend_hub

    # Deliberately enable every stored flag: policy must survive old catalog data.
    stored = {model: {'agents': True, 'dashboard': True} for model in models.MODELS}
    monkeypatch.setattr(models, '_load_model_flags', lambda: stored)
    monkeypatch.setattr(backend_hub, 'hub_configured', lambda: None)
    return stored


@pytest.mark.parametrize('model', NATIVE)
def test_native_agent_admission_refuses_even_with_enabled_catalog_flags(admission, model):
    with pytest.raises(ValueError, match=models.AGENT_HUB_ROUTE_RULE):
        models.ensure_spawn_allowed(model)


@pytest.mark.parametrize('alias', HUB)
def test_hub_agent_routes_are_permitted(admission, alias):
    models.ensure_spawn_allowed(models.resolve_model(alias))


@pytest.mark.parametrize('model', NATIVE)
def test_manual_selection_and_old_route_lookup_survive(admission, model):
    spec = models.get_model_spec(model)
    if spec.runtime != 'harness':
        models.ensure_dashboard_visible(model)
    assert models.backend_for_model(model) == spec.runtime


def test_legacy_route_lookup_survives_but_new_agent_use_refuses(admission):
    model = 'claude-opus-4-6'
    assert models.backend_for_model(model) == 'claude'
    with pytest.raises(ValueError, match=models.AGENT_HUB_ROUTE_RULE):
        models.ensure_spawn_allowed(model)


@pytest.mark.parametrize('alias', ['sonnet', 'opus', 'haiku'])
def test_opt_in_credit_admission_remains_available(admission, alias):
    model = models.resolve_model(alias)
    models.ensure_spawn_allowed(model, billing='api_credit')
    admission[model]['agents'] = False
    with pytest.raises(ValueError, match='disabled for agents'):
        models.ensure_spawn_allowed(model, billing='api_credit')


@pytest.mark.parametrize('billing', ['api_credit', 'invalid'])
def test_billing_does_not_open_native_codex_or_hub_routes(admission, billing):
    for alias in ['luna', 'hubsol']:
        with pytest.raises(ValueError, match='billing'):
            models.ensure_spawn_allowed(models.resolve_model(alias), billing=billing)


def test_hub_configuration_and_catalog_gates_remain_effective(admission, monkeypatch):
    from app import backend_hub

    model = models.resolve_model('hubsol')
    monkeypatch.setattr(backend_hub, 'hub_configured', lambda: 'test hub unavailable')
    with pytest.raises(ValueError, match='test hub unavailable'):
        models.ensure_spawn_allowed(model)
    monkeypatch.setattr(backend_hub, 'hub_configured', lambda: None)
    admission[model]['agents'] = False
    with pytest.raises(ValueError, match='disabled for agents'):
        models.ensure_spawn_allowed(model)


@pytest.mark.asyncio
@pytest.mark.parametrize('alias', ['sonnet', 'opus', 'luna', 'spark', 'grok', 'gigachat'])
async def test_agent_spawn_refuses_before_allocating_any_session(admission, monkeypatch, tmp_path, alias):
    from app import manager as module

    lookup = AsyncMock()
    monkeypatch.setattr(module, 'get_session_by_name', lookup)
    manager = module.SessionManager()
    with pytest.raises(ValueError, match=models.AGENT_HUB_ROUTE_RULE):
        await manager.create_session(
            'worker', str(tmp_path), str(tmp_path), alias, parent_name='orchestrator',
        )
    assert not manager.sessions
    lookup.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize('alias', ['sonnet', 'opus', 'luna', 'spark', 'grok', 'gigachat'])
async def test_agent_change_refuses_before_loading_or_mutating_worker(admission, monkeypatch, alias):
    from app.routes import sessions

    loaded = AsyncMock()
    monkeypatch.setattr(sessions.manager, 'ensure_loaded', loaded)
    result = await sessions.change_model('worker', {'model': alias, 'via': 'mcp'})
    assert result.status_code == 409
    assert models.AGENT_HUB_ROUTE_RULE in result.body.decode()
    loaded.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('alias', HUB)
async def test_hub_change_dispatches_and_preserves_reason_metadata(admission, monkeypatch, alias):
    from app.routes import sessions

    worker = AsyncMock()
    worker.change_model.return_value = {'ok': True, 'changed': False}
    monkeypatch.setattr(sessions.manager, 'ensure_loaded', AsyncMock(return_value=worker))
    reason = 'A small creative scene'
    result = await sessions.change_model('worker', {
        'model': alias, 'via': 'mcp', 'model_reason': reason,
    })
    assert result['ok']
    worker.change_model.assert_awaited_once_with(models.resolve_model(alias), model_reason=reason)


@pytest.mark.asyncio
async def test_manual_native_model_change_still_dispatches(admission, monkeypatch):
    from app.routes import sessions

    worker = AsyncMock()
    worker.change_model.return_value = {'ok': True, 'changed': False}
    monkeypatch.setattr(sessions.manager, 'ensure_loaded', AsyncMock(return_value=worker))
    result = await sessions.change_model('worker', {'model': 'sol', 'via': 'dashboard'})
    assert result['ok']
    worker.change_model.assert_awaited_once_with(models.resolve_model('sol'))


@pytest.mark.parametrize('alias', ['sonnet', 'opus', 'luna', 'spark', 'grok', 'gigachat'])
def test_dynamic_normalization_refuses_ordinary_native_tasks(admission, alias):
    from app import mcp_stdio

    task, error = mcp_stdio._normalize_dynamic_task({'prompt': 'task', 'model': alias}, label='task')
    assert task == {}
    assert models.AGENT_HUB_ROUTE_RULE in error


@pytest.mark.parametrize('alias', ['sonnet', 'opus', 'haiku'])
def test_dynamic_normalization_preserves_explicit_credit_opt_in(admission, alias):
    from app import mcp_stdio

    task, error = mcp_stdio._normalize_dynamic_task(
        {'prompt': 'task', 'model': alias, 'billing': 'api_credit'}, label='task',
    )
    assert error is None
    assert task['billing'] == 'api_credit'
    assert task['model'] == models.resolve_model(alias)


@pytest.mark.asyncio
@pytest.mark.parametrize('alias', ['sonnet', 'opus', 'luna', 'spark', 'gigachat', 'hubsol'])
async def test_one_shot_dispatch_refuses_without_any_provider_call(admission, monkeypatch, tmp_path, alias):
    calls = [AsyncMock() for _ in range(3)]
    for name, call in zip(['run_claude', 'run_codex', 'run_harness'], calls):
        monkeypatch.setattr(wf_adapters, name, call)
    result = await wf_adapters.run_adapter(
        'task', model=models.resolve_model(alias), cwd=tmp_path, timeout=1,
    )
    assert not result.ok
    assert result.cost_usd == 0
    assert not result.cost_unaccounted
    assert result.stop_reason == ('unsupported' if alias == 'hubsol' else 'model_policy_refused')
    for call in calls:
        call.assert_not_awaited()


@pytest.mark.asyncio
async def test_one_shot_explicit_credit_dispatch_preserves_billing_and_does_not_fallback(
    admission, monkeypatch, tmp_path,
):
    refusal = wf_adapters.AdapterResult('', 'claude', models.resolve_model('sonnet'), False,
                                       'credit_unavailable', 0.0, billing_mode='api_credit')
    claude = AsyncMock(return_value=refusal)
    codex, harness = AsyncMock(), AsyncMock()
    monkeypatch.setattr(wf_adapters, 'run_claude', claude)
    monkeypatch.setattr(wf_adapters, 'run_codex', codex)
    monkeypatch.setattr(wf_adapters, 'run_harness', harness)
    result = await wf_adapters.run_adapter(
        'task', model=models.resolve_model('sonnet'), cwd=tmp_path, timeout=1,
        billing_mode='api_credit',
    )
    assert result is refusal
    claude.assert_awaited_once()
    assert claude.call_args.kwargs['billing_mode'] == 'api_credit'
    codex.assert_not_awaited()
    harness.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('alias', HUB)
async def test_dynamic_hub_requests_refuse_before_queuing_a_job(admission, monkeypatch, alias):
    from app import mcp_stdio

    api = AsyncMock()
    monkeypatch.setattr(mcp_stdio, '_api', api)
    result = await mcp_stdio.dynamic_workflow(
        tasks=[{'prompt': 'task', 'model': alias}], task_id='task',
        budget_usd=1, max_calls=1, max_concurrency=1, repo='/repo',
    )
    assert result.startswith('Error:')
    assert 'spawn_worker' in result
    api.assert_not_awaited()
