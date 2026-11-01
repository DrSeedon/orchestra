"""V-1152: real manager + database + ordinary-worker quota path for the local Luna route.

Only the provider backend is fake. The hub, its pool and its upload path are made to fail
loudly, so a native route that touched them would be caught.
"""
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app import db, models, quota_gate as gate
from app.events import MessageProvenance
from app.manager import SessionManager
from app.session import AgentStatus

REASON = 'protected data must stay on this machine'
START = datetime(2026, 10, 20, 7, tzinfo=timezone.utc).timestamp()
WEEK = 10080 * 60
NOW = START + 0.1 * WEEK


def decision(used):
    return gate.evaluate_worker_admission(
        models.LOCAL_LUNA_MODEL,
        {'codex': {'windows': [dict(id='primary', window_minutes=10080, utilization=used,
                                    resets_at=START + WEEK)]}},
        {'codex': NOW}, now=NOW,
    )


@pytest.fixture
def env(tmp_path, monkeypatch):
    from app import backend_hub, hub_pool, pipeline

    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'test.db')
    db.init_db()
    from app import tm

    with tm._conn() as conn:
        tm.ensure_project(conn, 'test', scope=str(tmp_path))
    monkeypatch.setattr(gate.time, 'time', lambda: NOW)
    monkeypatch.setattr(pipeline, 'PIPELINES_DIR',
                        Path(__file__).resolve().parents[1] / '.orchestra/pipelines')
    pipeline.load_pipeline.cache_clear()
    stored = {model: {'agents': True, 'dashboard': True} for model in models.MODELS}
    monkeypatch.setattr(models, '_load_model_flags', lambda: stored)
    hub = Mock(side_effect=AssertionError('native Luna touched the hub'))
    # Only a refusal hint may consult configuration; the backend and pool must stay unused.
    monkeypatch.setattr(backend_hub, 'hub_configured', lambda: None)
    monkeypatch.setattr(backend_hub, 'HubBackend', hub)
    monkeypatch.setattr(hub_pool, 'get_hub_pool', AsyncMock(side_effect=AssertionError('hub pool read')))
    yield SimpleNamespace(tmp=tmp_path, hub=hub)
    pipeline.load_pipeline.cache_clear()


def fake_backend(session, monkeypatch):
    backend = SimpleNamespace(send=AsyncMock(), active_turn_id='fake-turn')
    ensure = AsyncMock(return_value=backend)
    monkeypatch.setattr(session, '_ensure_backend', ensure)
    monkeypatch.setattr(session, '_persist', Mock())
    monkeypatch.setattr(session, '_log', Mock())
    monkeypatch.setattr(session, '_turn_event_loop', AsyncMock())
    return backend, ensure


@pytest.mark.asyncio
async def test_luna_worker_persists_reason_reloads_and_follows_the_ordinary_quota_path(env, monkeypatch):
    tmp = str(env.tmp)
    admission = AsyncMock(return_value=decision(0))
    monkeypatch.setattr(gate, 'get_worker_admission', admission)
    manager = SessionManager()
    worker = await manager.create_session(
        'worker', tmp, tmp, 'luna', parent_name='orchestrator', use_worktree=False,
        planned_initial_turn=True, model_reason=REASON,
    )
    admission.assert_awaited_once_with(models.LOCAL_LUNA_MODEL)
    assert worker.model == models.LOCAL_LUNA_MODEL and worker.backend_type == 'codex'
    assert not worker.is_orchestrator
    await worker._drain_persist()
    row = db.get_session(worker.id)
    assert row['model_reason'] == REASON and row['model'] == models.LOCAL_LUNA_MODEL

    reloaded = await SessionManager()._load_from_db(row)
    assert reloaded.model_reason == REASON and reloaded.backend_type == 'codex'
    assert not reloaded.is_orchestrator
    await reloaded._drain_persist()

    backend, ensure = fake_backend(reloaded, monkeypatch)
    reloaded._admission_service = AsyncMock(return_value=decision(90))
    provenance = MessageProvenance(origin='agent', senders=('orchestrator',))
    with pytest.raises(gate.QuotaGateError):
        await reloaded.preflight_delivery_admission()
    with pytest.raises(gate.QuotaGateError):
        await reloaded.send('held', provenance=provenance)
    ensure.assert_not_awaited()
    backend.send.assert_not_awaited()
    assert reloaded.status == AgentStatus.IDLE

    reloaded._admission_service.return_value = decision(0)
    await reloaded.send('released', provenance=provenance)
    backend.send.assert_awaited_once()
    if reloaded._listen_task:
        await reloaded._listen_task
    env.hub.assert_not_called()


@pytest.mark.asyncio
async def test_closed_quota_refuses_luna_before_any_session_exists(env, monkeypatch):
    tmp = str(env.tmp)
    monkeypatch.setattr(gate, 'get_worker_admission', AsyncMock(return_value=decision(90)))
    manager = SessionManager()
    with pytest.raises(gate.QuotaGateError):
        await manager.create_session(
            'worker', tmp, tmp, 'luna', parent_name='orchestrator', use_worktree=False,
            planned_initial_turn=True, model_reason=REASON,
        )
    assert not manager.sessions and db.get_session_by_name('worker', tmp) is None
    env.hub.assert_not_called()
