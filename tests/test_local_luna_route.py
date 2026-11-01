"""V-1152: protected-work local Luna admission; every other native route stays refused."""
from unittest.mock import AsyncMock

import pytest

from app import models

NATIVE = [spec.id for spec in models.SELECTABLE_MODEL_SPECS if spec.runtime != 'hub']


@pytest.fixture
def admission(monkeypatch):
    from app import backend_hub

    stored = {model: {'agents': True, 'dashboard': True} for model in models.MODELS}
    monkeypatch.setattr(models, '_load_model_flags', lambda: stored)
    monkeypatch.setattr(backend_hub, 'hub_configured', lambda: None)
    return stored


# ── V-1152: protected-work local Luna route ──────────────────────────────────────────
LUNA = models.LOCAL_LUNA_MODEL
REASON = 'protected data must stay on this machine'


def test_luna_is_the_only_native_route_admitted_and_only_with_a_reason(admission):
    models.ensure_spawn_allowed(LUNA, model_reason=REASON)
    models.ensure_spawn_allowed(models.resolve_model('luna'), model_reason=f'  {REASON}  ')
    for reason in ('', '   ', None, 7):
        with pytest.raises(ValueError, match=models.AGENT_HUB_ROUTE_RULE):
            models.ensure_spawn_allowed(LUNA, model_reason=reason)
    for model in NATIVE + ['claude-opus-4-6', 'gpt-5.6-luna']:
        if model == LUNA:
            continue
        with pytest.raises(ValueError, match=models.AGENT_HUB_ROUTE_RULE):
            models.ensure_spawn_allowed(model, model_reason=REASON)


@pytest.mark.parametrize('billing', ['api_credit', 'invalid'])
def test_reason_does_not_turn_luna_into_a_billing_route(admission, billing):
    with pytest.raises(ValueError):
        models.ensure_spawn_allowed(LUNA, billing=billing, model_reason=REASON)


def test_catalog_flag_still_gates_luna_and_hub_outage_never_opens_it(admission, monkeypatch):
    from app import backend_hub

    admission[LUNA]['agents'] = False
    with pytest.raises(ValueError) as flag:
        models.ensure_spawn_allowed(LUNA, model_reason=REASON)
    assert models.AGENT_HUB_ROUTE_RULE not in str(flag.value)
    admission[LUNA]['agents'] = True
    # The hub being down blocks hub routes; it is not a reason to admit native Luna.
    monkeypatch.setattr(backend_hub, 'hub_configured', lambda: 'test hub unavailable')
    with pytest.raises(ValueError, match='test hub unavailable'):
        models.ensure_spawn_allowed(models.resolve_model('hubsol'), model_reason=REASON)
    with pytest.raises(ValueError, match=models.AGENT_HUB_ROUTE_RULE):
        models.ensure_spawn_allowed('gpt-6.1-sol', model_reason=REASON)
    with pytest.raises(ValueError, match=models.AGENT_HUB_ROUTE_RULE):
        models.ensure_spawn_allowed(LUNA)


def test_reason_metadata_is_kept_for_luna_and_optional_for_manual_selection(admission):
    assert models.validate_model_reason('luna', f' {REASON} ') == REASON
    assert models.validate_model_reason('luna') == ''
    assert models.validate_model_reason('sol', REASON) == ''
    with pytest.raises(ValueError, match=models.HUB_CLAUDE_REASON_RULE):
        models.validate_model_reason('hubsonnet')


class _Sentinel(Exception):
    pass


@pytest.mark.asyncio
async def test_spawn_passes_admission_for_luna_with_reason_and_reaches_quota_gate(
    admission, monkeypatch, tmp_path,
):
    from app import manager as module, quota_gate

    seen = []

    def blocked(decision):
        seen.append(decision)
        raise _Sentinel

    async def admission_for(model):
        seen.append(model)
        return 'decision'

    monkeypatch.setattr(module, 'get_session_by_name', lambda *a, **k: None)
    monkeypatch.setattr(quota_gate, 'get_worker_admission', admission_for)
    monkeypatch.setattr(quota_gate, 'require_worker_admission', blocked)
    manager = module.SessionManager()
    with pytest.raises(_Sentinel):
        await manager.create_session(
            'worker', str(tmp_path), str(tmp_path), 'luna', parent_name='orchestrator',
            use_worktree=False, planned_initial_turn=True, model_reason=REASON,
        )
    assert seen == [LUNA, 'decision']
    assert not manager.sessions
    with pytest.raises(ValueError, match=models.AGENT_HUB_ROUTE_RULE):
        await manager.create_session(
            'worker', str(tmp_path), str(tmp_path), 'luna', parent_name='orchestrator',
            use_worktree=False, planned_initial_turn=True,
        )


@pytest.mark.asyncio
async def test_change_to_luna_needs_a_reason_and_forwards_it(admission, monkeypatch):
    from app.routes import sessions

    worker = AsyncMock()
    worker.change_model.return_value = {'ok': True, 'changed': False}
    monkeypatch.setattr(sessions.manager, 'ensure_loaded', AsyncMock(return_value=worker))
    refused = await sessions.change_model('worker', {'model': 'luna', 'via': 'mcp'})
    assert refused.status_code == 409
    assert models.AGENT_HUB_ROUTE_RULE in refused.body.decode()
    worker.change_model.assert_not_awaited()
    result = await sessions.change_model(
        'worker', {'model': 'luna', 'via': 'mcp', 'model_reason': REASON})
    assert result['ok']
    worker.change_model.assert_awaited_once_with(LUNA, model_reason=REASON)
    other = await sessions.change_model(
        'worker', {'model': 'sol', 'via': 'mcp', 'model_reason': REASON})
    assert other.status_code == 409


def test_dynamic_workflow_stays_closed_to_luna_even_with_a_reason(admission):
    from app import mcp_stdio

    task, error = mcp_stdio._normalize_dynamic_task(
        {'prompt': 'task', 'model': 'luna', 'model_reason': REASON}, label='task')
    assert task == {}
    assert models.AGENT_HUB_ROUTE_RULE in error
