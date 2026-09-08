import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from app import db
from app.bg_jobs import BgJobManager
from app.events import MessageProvenance
from app.idle_watch import check
from app.session import AgentSession


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'idle.db')
    db.init_db()
    for name, parent, role in [('root', '', 'orchestrator'), ('child', 'root', 'worker'),
                               ('grandchild', 'child', 'worker'), ('other', '', 'orchestrator'),
                               ('foreign', 'other', 'worker')]:
        session = AgentSession(id=name, name=name, scope='/repo', cwd='/repo',
                               role=role, parent_id=parent, parent_name=parent)
        db.save_session(session._to_db_dict())
    manager = SimpleNamespace(sessions={})
    jobs = BgJobManager()
    jobs.set_session_manager(manager)
    monkeypatch.setattr(jobs, '_start_task', lambda *args: None)
    monkeypatch.setattr('app.message_deliveries.ensure_target_runner', lambda *args: None)
    return jobs, manager


async def create(env, target='root'):
    return await env[0].create('idle', {}, 'Check results', target, target, '/repo', target,
                               timeout_seconds=0)


def activity(session, kind, origin='user', subtype=''):
    db.add_log(session, datetime.now(timezone.utc), kind, 'activity',
               provenance=MessageProvenance(origin=origin, senders=('source',), subtype=subtype))


@pytest.mark.asyncio
async def test_rearms_on_worker_activity_but_not_own_wake(env):
    jobs, manager = env
    job = await create(env)
    assert not jobs.has_active_jobs('root')
    assert await check(job['id'], manager)
    assert not await check(job['id'], manager)
    activity('root', 'user_message', 'background_task', 'idle_watch')
    activity('root', 'text')
    assert not await check(job['id'], manager)
    activity('grandchild', 'tool')
    assert await check(job['id'], manager)
    with db._conn() as conn:
        assert conn.execute('SELECT COUNT(*) FROM message_deliveries').fetchone()[0] == 2
    assert db.bg_get_job(job['id'])['status'] == 'active'


@pytest.mark.asyncio
async def test_only_own_tree_and_other_background_work_block(env):
    jobs, manager = env
    job = await create(env)
    with db._conn() as conn:
        conn.execute("UPDATE sessions SET status='running' WHERE id IN ('grandchild','foreign')")
    assert not await check(job['id'], manager)
    with db._conn() as conn:
        conn.execute("UPDATE sessions SET status='idle' WHERE id='grandchild'")
    timer = await jobs.create('timer', {'delay_seconds': 10}, 'done', 'child', 'child', '/repo', 'root')
    assert not await check(job['id'], manager)
    await jobs.cancel(timer['id'])
    assert await check(job['id'], manager)


@pytest.mark.asyncio
async def test_live_state_and_pending_report_block(env):
    _, manager = env
    job = await create(env)
    manager.sessions['child'] = SimpleNamespace(status='running')
    assert not await check(job['id'], manager)
    manager.sessions['child'] = SimpleNamespace(status='idle', _auto_report_task=SimpleNamespace(done=lambda: False))
    assert not await check(job['id'], manager)
    manager.sessions.clear()
    assert await check(job['id'], manager)


@pytest.mark.asyncio
async def test_crash_between_delivery_and_ack_does_not_duplicate(env):
    job = await create(env)
    assert await check(job['id'], env[1])
    with db._conn() as conn:
        conn.execute("UPDATE bg_jobs SET config=json_remove(config,'$.last_idle_signature')")
    assert await check(job['id'], env[1])
    with db._conn() as conn:
        assert conn.execute('SELECT COUNT(*) FROM message_deliveries').fetchone()[0] == 1
    assert not await check(job['id'], env[1])


@pytest.mark.asyncio
async def test_replacement_cancel_and_worker_rejection(env):
    first = await create(env)
    other = await create(env, 'other')
    replacement = await create(env)
    assert db.bg_get_job(first['id'])['status'] == 'cancelled'
    assert db.bg_get_job(other['id'])['status'] == 'active'
    await env[0].cancel(replacement['id'])
    assert not await check(replacement['id'], env[1])
    assert 'error' in await create(env, 'child')


@pytest.mark.asyncio
async def test_restore_keeps_ack_and_no_expiry(env, monkeypatch):
    job = await create(env)
    assert await check(job['id'], env[1])
    restored = BgJobManager()
    restored.set_session_manager(env[1])
    started = []
    monkeypatch.setattr(restored, '_start_task', lambda *args, **kwargs: started.append(args))
    await restored.restore_from_db()
    assert started
    assert json.loads(db.bg_get_job(job['id'])['config'])['no_expiry']
    assert not await check(job['id'], env[1])


@pytest.mark.asyncio
async def test_parallel_checks_accept_only_one_delivery(env):
    import asyncio
    job = await create(env)
    await asyncio.gather(check(job['id'], env[1]), check(job['id'], env[1]))
    with db._conn() as conn:
        assert conn.execute('SELECT COUNT(*) FROM message_deliveries').fetchone()[0] == 1


@pytest.mark.asyncio
async def test_idle_runner_expires_and_leaves_no_active_watch(env, monkeypatch):
    import app.bg_jobs as module
    job = await create(env)
    ticks = iter([0, 0, 2])
    monkeypatch.setattr(module, 'time', SimpleNamespace(monotonic=lambda: next(ticks)))
    async def no_sleep(_):
        pass
    monkeypatch.setattr(module.asyncio, 'sleep', no_sleep)
    await env[0]._run_idle(job['id'], 1)
    assert db.bg_get_job(job['id'])['status'] == 'expired'
