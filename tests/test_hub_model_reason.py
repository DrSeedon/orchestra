"""V-1024: hub Claude is a reasoned exception; a reason never bypasses pool admission."""
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.models import HUB_CLAUDE_REASON_RULE, validate_model_reason

CLAUDE = ['hubsonnet', 'hubopus', 'hubhaiku', 'hub-claude-sonnet-5-5']
REASON = 'Creative scene direction and visual judgment'


@pytest.mark.parametrize('model', CLAUDE)
@pytest.mark.parametrize('reason', ['', '  \n ', None])
def test_claude_exception_requires_a_nonempty_reason(model, reason):
    with pytest.raises(ValueError, match=HUB_CLAUDE_REASON_RULE):
        validate_model_reason(model, reason)


@pytest.mark.parametrize('model', CLAUDE)
def test_claude_exception_accepts_a_named_reason(model):
    assert validate_model_reason(model, '  ' + REASON + '  ') == REASON


@pytest.mark.parametrize('model', ['hubsol', 'hub-gpt-6.1-sol', 'sonnet', 'opus', 'sol'])
def test_default_hub_and_own_models_need_no_reason(model):
    assert validate_model_reason(model) == ''


@pytest.mark.asyncio
@pytest.mark.parametrize('tool', ['spawn', 'change'])
@pytest.mark.parametrize('model', CLAUDE[:3])
async def test_tools_refuse_missing_reason_before_any_api_call(monkeypatch, tool, model):
    from app import mcp_stdio as mcp

    api = AsyncMock()
    monkeypatch.setattr(mcp, '_api', api)
    with pytest.raises(mcp.ApiToolError) as caught:
        if tool == 'spawn':
            await mcp.spawn_worker('worker', 'task', '/repo', model)
        else:
            await mcp.change_worker_model('worker', model)
    assert caught.value.code == HUB_CLAUDE_REASON_RULE
    assert HUB_CLAUDE_REASON_RULE in str(caught.value)
    api.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('tool', ['spawn', 'change'])
@pytest.mark.parametrize('model,reason', [('hubsonnet', REASON), ('hubopus', REASON),
                                         ('hubhaiku', REASON), ('hubsol', ''), ('sonnet', '')])
async def test_tools_forward_named_reason_and_allow_other_models_without_one(monkeypatch, tool, model, reason):
    from app import mcp_stdio as mcp

    api = AsyncMock(return_value={'ok': True, 'model': model, 'branch': 'task-V-1/worker',
                                 'worktree_path': '/repo/wt', 'repo_path': '/repo',
                                 'git_common_dir': '/repo/.git'})
    monkeypatch.setattr(mcp, '_api', api)
    monkeypatch.setattr(mcp, '_post_initial_delivery', AsyncMock(return_value={'state': 'SENT'}))
    monkeypatch.setattr(mcp, '_cross_repo_note', lambda *args: '')
    if tool == 'spawn':
        await mcp.spawn_worker('worker', 'task', '/repo', model, model_reason=reason)
    else:
        await mcp.change_worker_model('worker', model, model_reason=reason)
    assert api.await_count == 1
    assert api.call_args.kwargs['json'].get('model_reason', '') == reason


@pytest.fixture
def manager(tmp_path, monkeypatch):
    from app import db, hub_pool, pipeline
    from app.manager import SessionManager

    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'test.db')
    db.init_db()
    monkeypatch.setattr(pipeline, 'PIPELINES_DIR', Path(__file__).resolve().parents[1] / '.orchestra/pipelines')
    pipeline.load_pipeline.cache_clear()

    async def pool(**kwargs):
        return {'available': True, 'providers': {
            p: {'usable': 1, 'accounts': 2, 'threshold_pct': 100} for p in ('claude', 'codex')}}
    monkeypatch.setattr(hub_pool, 'get_hub_pool', pool)
    yield SessionManager()
    pipeline.load_pipeline.cache_clear()


@pytest.mark.asyncio
@pytest.mark.parametrize('model', CLAUDE[:3])
async def test_direct_spawn_cannot_bypass_the_reason_rule(manager, tmp_path, model):
    with pytest.raises(ValueError, match=HUB_CLAUDE_REASON_RULE):
        await manager.create_session('worker', str(tmp_path), str(tmp_path), model)
    assert not manager.sessions


@pytest.mark.asyncio
@pytest.mark.parametrize('model,reason', [('hubsonnet', REASON), ('hubsol', ''), ('sonnet', '')])
async def test_spawn_reason_survives_database_reload_and_both_dashboard_lists(
    manager, tmp_path, model, reason,
):
    from app import db
    from app.manager import SessionManager

    worker = await manager.create_session('worker', str(tmp_path), str(tmp_path), model, model_reason=reason)
    await worker._drain_persist()
    row = db.get_session(worker.id)
    assert row['model_reason'] == reason
    assert db.get_session_by_name('worker', str(tmp_path))['model_reason'] == reason
    assert worker.to_dict()['model_reason'] == reason
    assert manager.list_sessions(str(tmp_path))[0]['model_reason'] == reason
    # A detached dashboard row and a genuinely reconstructed session use the same persisted value.
    reloaded_manager = SessionManager()
    assert reloaded_manager.list_sessions(str(tmp_path))[0]['model_reason'] == reason
    loaded = await reloaded_manager._load_from_db(row)
    assert loaded.model_reason == reason and loaded.to_dict()['model_reason'] == reason
    await loaded._drain_persist()


@pytest.mark.asyncio
async def test_direct_model_change_refuses_missing_reason_and_preserves_previous_reason(manager, monkeypatch):
    from app.session import AgentSession

    worker = AgentSession(id='worker', name='worker', cwd='/repo', scope='/repo',
                          model='hub-gpt-6.1-sol', backend_type='hub')
    change = AsyncMock()
    monkeypatch.setattr(worker, '_change_model_locked', change)
    result = await worker.change_model('hub-claude-sonnet-5-5')
    assert result['error_code'] == HUB_CLAUDE_REASON_RULE
    change.assert_not_awaited()
    assert worker.model == 'hub-gpt-6.1-sol' and worker.model_reason == ''


@pytest.mark.asyncio
async def test_model_change_persists_reason_atomically_and_clears_it_on_sol(manager, monkeypatch):
    from app import db
    from app.session import AgentSession

    worker = AgentSession(id='worker', name='worker', cwd='/repo', scope='/repo',
                          model='hub-gpt-6.1-sol', backend_type='hub')
    db.save_session(worker._to_db_dict())

    async def change(model):
        worker.model = model
        # Existing model transition code persists before its wrapper returns.
        db.save_session(worker._to_db_dict())
        assert db.get_session(worker.id)['model_reason'] == (REASON if 'claude' in model else '')
        return {'ok': True, 'changed': True}
    monkeypatch.setattr(worker, '_change_model_locked', change)
    assert (await worker.change_model('hub-claude-sonnet-5-5', REASON))['ok']
    await worker._drain_persist()
    assert db.get_session(worker.id)['model_reason'] == REASON
    assert worker.to_dict()['model_reason'] == REASON
    assert (await worker.change_model('hub-gpt-6.1-sol'))['ok']
    await worker._drain_persist()
    assert db.get_session(worker.id)['model_reason'] == ''


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', ['spawn', 'change'])
async def test_named_reason_does_not_bypass_an_exhausted_claude_pool(manager, tmp_path, monkeypatch, operation):
    from app import hub_pool
    from app.quota_gate import QuotaGateError
    from app.session import AgentSession

    async def pool(**kwargs):
        return {'available': True, 'providers': {'claude': {
            'usable': 0, 'accounts': 10, 'threshold_pct': 100}}}
    monkeypatch.setattr(hub_pool, 'get_hub_pool', pool)
    if operation == 'spawn':
        with pytest.raises(QuotaGateError, match="model='hubsol'"):
            await manager.create_session('worker', str(tmp_path), str(tmp_path), 'hubsonnet', model_reason=REASON)
        assert not manager.sessions
    else:
        worker = AgentSession(id='worker', name='worker', cwd='/repo', scope='/repo',
                              model='hub-gpt-6.1-sol', backend_type='hub')
        result = await worker.change_model('hub-claude-sonnet-5-5', REASON)
        assert result['ok'] is False and "model='hubsol'" in result['error']
        assert worker.model_reason == ''


def test_existing_v3_database_gets_additive_reason_storage_without_losing_sessions(manager):
    from app import db
    from app.session import AgentSession

    worker = AgentSession(id='worker', name='worker', cwd='/repo', scope='/repo')
    db.save_session(worker._to_db_dict())
    with db._conn() as conn:
        conn.execute('DROP TABLE session_model_reasons')
    db.init_db()
    db.init_db()
    assert db.get_session('worker')['name'] == 'worker'
    assert db.get_session('worker')['model_reason'] == ''


@pytest.mark.asyncio
async def test_failed_claude_switch_keeps_previous_reason(manager, monkeypatch):
    from app.session import AgentSession

    worker = AgentSession(id='worker', name='worker', scope='/repo', cwd='/repo',
                          model='hub-claude-sonnet-5-5', model_reason=REASON, backend_type='hub')
    result = await worker.change_model('hub-claude-opus-5-5', ' ')
    assert result['error_code'] == HUB_CLAUDE_REASON_RULE
    assert worker.model_reason == REASON
    monkeypatch.setattr(worker, '_change_model_locked', AsyncMock(return_value={'ok': False, 'error': 'refused'}))
    result = await worker.change_model('hub-claude-opus-5-5', 'A different named reason')
    assert result['ok'] is False and worker.model_reason == REASON


@pytest.mark.asyncio
@pytest.mark.parametrize('reason', ['', REASON])
async def test_change_model_api_enforces_reason_and_forwards_it(manager, monkeypatch, reason):
    from app.routes import sessions as routes
    from app.session import AgentSession

    worker = AgentSession(id='worker', name='worker', scope='/repo', cwd='/repo',
                          model='hub-gpt-6.1-sol', backend_type='hub')
    monkeypatch.setattr(routes.manager, 'ensure_loaded', AsyncMock(return_value=worker))
    async def change(model):
        worker.model = model
        return {'ok': True, 'changed': True}
    change_mock = AsyncMock(side_effect=change)
    monkeypatch.setattr(worker, '_change_model_locked', change_mock)
    response = await routes.change_model('worker', {'model': 'hubsonnet', 'model_reason': reason})
    if reason:
        assert response['ok'] is True and worker.model_reason == REASON
        change_mock.assert_awaited_once()
        await worker._drain_persist()
    else:
        assert response.status_code == 409
        assert HUB_CLAUDE_REASON_RULE in response.body.decode()
        change_mock.assert_not_awaited()
