"""A surviving CLI must remain reachable across supervisor generations."""
import asyncio
import json
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.backend_codex import CodexBackend

from app import db as database, manager
from app.backend_jsonrpc import process_start_time
from tests.test_fd_adopt import db, _save_running_session, _read_bounded
from tests.test_session import mock_db, session


def test_spawn_publication_preserves_identity_and_graceful_buffer(db, monkeypatch):
    _save_running_session('identity-537')
    database.save_handover_state('identity-537', 'turn-537', 'buffer')
    stored = {}
    monkeypatch.setattr('app.fdstore.store_fds', lambda name, fds: stored.update({name: fds}))
    backend = SimpleNamespace(fd_in=11, fd_out=12, pid=os.getpid(),
                              cli_started_at=process_start_time(os.getpid()))
    assert backend.cli_started_at > 0
    session = SimpleNamespace(id='identity-537', name='identity-537', _backend=backend)
    assert manager.publish_backend_fds(session)
    with database._conn() as conn:
        row = conn.execute('SELECT * FROM sessions WHERE id=?', (session.id,)).fetchone()
    assert (row['cli_pid'], row['cli_started_at']) == (backend.pid, backend.cli_started_at)
    assert (row['active_turn_id'], row['leftover']) == ('turn-537', 'buffer')
    assert stored == {'agent.identity-537.stdin': [11], 'agent.identity-537.stdout': [12]}


def test_failed_identity_write_prevents_fd_publication(db, monkeypatch):
    removed = []
    stored = []
    monkeypatch.setattr('app.fdstore.store_fds', lambda *args: stored.append(args))
    monkeypatch.setattr('app.fdstore.remove_fds', removed.append)
    def fail(*args):
        raise OSError('identity storage unavailable')
    monkeypatch.setattr(database, 'save_backend_identity', fail)
    session = SimpleNamespace(id='failed-537', name='failed-537',
                              _backend=SimpleNamespace(fd_in=11, fd_out=12, pid=1, cli_started_at=2))
    assert not manager.publish_backend_fds(session)
    assert stored == []
    assert removed == []


def test_missing_identity_cannot_inherit_previous_process(db, monkeypatch):
    _save_running_session('missing-537')
    database.save_backend_identity('missing-537', 123, 456)
    monkeypatch.setattr('app.fdstore.store_fds', lambda *args: None)
    session = SimpleNamespace(id='missing-537', name='missing-537',
                              _backend=SimpleNamespace(fd_in=11, fd_out=12, pid=0, cli_started_at=0))
    assert manager.publish_backend_fds(session)
    with database._conn() as conn:
        row = conn.execute('SELECT cli_pid, cli_started_at FROM sessions WHERE id=?',
                           (session.id,)).fetchone()
    assert tuple(row) == (0, 0)


@pytest.mark.asyncio
@pytest.mark.parametrize('identity', ['missing', 'reused', 'valid'])
async def test_adopted_identity_controls_refresh_and_real_delivery(session, monkeypatch, identity):
    cli_in_r, cli_in_w = os.pipe()
    cli_out_r, cli_out_w = os.pipe()
    backend = CodexBackend(model='gpt-5.6-luna', cwd='/tmp')
    started = process_start_time(os.getpid())
    pid = os.getpid() if identity != 'missing' else 0
    recorded_start = started if identity == 'valid' else (started + 1 if pid else 0)
    await backend.adopt(cli_in_w, cli_out_r, 'thread-537',
                        cli_pid=pid, cli_started_at=recorded_start)
    session.backend_type = 'codex'
    session.session_id = 'thread-537'
    session._backend = backend
    session.tools_are_stale = True
    disconnect = AsyncMock()
    monkeypatch.setattr(backend, 'disconnect', disconnect)
    try:
        await session._refresh_stale_backend()
        if identity == 'valid':
            disconnect.assert_awaited_once()
            assert session._backend is None
        else:
            disconnect.assert_not_called()
            assert session._backend is backend
            assert session.tools_are_stale
            # The second refresh path inside CodexBackend.send must also keep the writer.
            monkeypatch.setattr(backend, '_managed_codex_home_path',
                                lambda: (_ for _ in ()).throw(AssertionError('unsafe config refresh')))
            sending = asyncio.create_task(backend.send('delivery after restart'))
            request = json.loads(await _read_bounded(cli_in_r, until=b'\n'))
            assert request['method'] == 'turn/start'
            assert request['params']['threadId'] == 'thread-537'
            assert request['params']['input'][0]['text'] == 'delivery after restart'
            os.write(cli_out_w, (json.dumps({'id': request['id'],
                'result': {'turn': {'id': 'turn-537'}}}) + '\n').encode())
            await asyncio.wait_for(sending, 5)
            assert backend.active_turn_id == 'turn-537'
            disconnect.assert_not_called()
    finally:
        # The stand-in CLI is this test process, never a signal target.
        backend._adopted_pid = None
        await backend.teardown_adopted()
        os.close(cli_in_r)
        os.close(cli_out_w)


@pytest.mark.asyncio
@pytest.mark.parametrize('turn_status', ['inProgress', 'completed'])
async def test_crash_adoption_restores_live_turn_and_delivery(db, session, monkeypatch, turn_status):
    _save_running_session(session.id, thread='thread-537')
    cli_in_r, cli_in_w = os.pipe()
    cli_out_r, cli_out_w = os.pipe()
    stored = {}
    monkeypatch.setattr('app.fdstore.store_fds',
                        lambda name, fds: stored.update({name: os.dup(fds[0])}))
    monkeypatch.setattr('app.fdstore.remove_fds', lambda *args: None)
    survivor = SimpleNamespace(fd_in=cli_in_w, fd_out=cli_out_r, pid=os.getpid(),
                               cli_started_at=process_start_time(os.getpid()))
    session._backend = survivor
    session.backend_type = 'codex'
    session.session_id = 'thread-537'
    assert manager.publish_backend_fds(session)
    os.close(cli_in_w)
    os.close(cli_out_r)
    # The old generation is gone; only the published duplicate ends and DB survive.
    session._backend = None
    backend = CodexBackend(model='gpt-5.6-luna', cwd='/tmp')
    monkeypatch.setattr(session, '_make_backend', lambda: backend)
    monkeypatch.setattr(session, '_activate_backend_tasks', lambda: None)
    monkeypatch.setattr('app.fdstore.acquire_fds', lambda: dict(stored))
    # Re-publication belongs to the new generation; avoid leaking duplicate stand-ins.
    monkeypatch.setattr('app.fdstore.store_fds', lambda *args: None)
    mgr = manager.SessionManager()
    async def load(row, **kwargs):
        mgr.sessions[session.id] = session
        return session
    monkeypatch.setattr(mgr, '_load_from_db', load)
    async def cli():
        request = json.loads(await _read_bounded(cli_in_r, until=b'\n'))
        assert request['method'] == 'thread/turns/list'
        os.write(cli_out_w, (json.dumps({'id': request['id'], 'result': {
            'data': [{'id': 'surviving-turn', 'status': turn_status}]}}) + '\n').encode())
    server = asyncio.create_task(cli())
    try:
        await asyncio.wait_for(mgr.auto_resume_all(), 5)
        await server
        assert backend.pid == survivor.pid
        assert backend.cli_started_at == survivor.cli_started_at
        assert not session._adopted_recovery_pending
        assert session.status.value == ('running' if turn_status == 'inProgress' else 'idle')
        await session.preflight_delivery_admission()
        # Drive the real provider transport after admission; no real model invocation.
        monkeypatch.setattr(backend, '_reload_stale_managed_config_before_turn', AsyncMock())
        sending = asyncio.create_task(backend.send('new delivery'))
        request = json.loads(await _read_bounded(cli_in_r, until=b'\n'))
        assert request['method'] == ('turn/steer' if turn_status == 'inProgress' else 'turn/start')
        assert request['params']['threadId'] == 'thread-537'
        os.write(cli_out_w, (json.dumps({'id': request['id'],
            'result': {'turn': {'id': 'next-turn'}}}) + '\n').encode())
        await asyncio.wait_for(sending, 5)
    finally:
        if session._listen_task:
            session._listen_task.cancel()
            await asyncio.gather(session._listen_task, return_exceptions=True)
        backend._adopted_pid = None
        await backend.teardown_adopted()
        os.close(cli_in_r)
        os.close(cli_out_w)


@pytest.mark.asyncio
async def test_failed_adoption_query_is_retried_before_admission(session):
    backend = SimpleNamespace(recover_adopted_turn=AsyncMock(
        side_effect=[TimeoutError('no response'), None]), is_alive=True)
    session._backend = backend
    session.backend_type = 'codex'
    session._adopted_recovery_pending = True
    session._activate_backend_tasks = lambda: None
    with pytest.raises(TimeoutError):
        await session.preflight_delivery_admission()
    assert session._adopted_recovery_pending
    assert not session._lifecycle_lock.locked()
    assert session.to_dict()['runtime_connection'] == 'recovering'
    await session.preflight_delivery_admission()
    assert not session._adopted_recovery_pending
    assert backend.recover_adopted_turn.await_count == 2


def test_consumed_handover_cannot_replay_on_later_crash(db):
    _save_running_session('consumed-537')
    database.save_handover_state('consumed-537', 'old-turn', 'old-buffer', 123, 456)
    database.clear_consumed_handover('consumed-537')
    with database._conn() as conn:
        row = conn.execute('SELECT active_turn_id, leftover, cli_pid, cli_started_at '
                           'FROM sessions WHERE id=?', ('consumed-537',)).fetchone()
    assert tuple(row) == ('', '', 123, 456)


def test_identity_write_requires_existing_session(db):
    with pytest.raises(RuntimeError):
        database.save_backend_identity('absent-537', 123, 456)


@pytest.mark.asyncio
async def test_retired_transport_does_not_poison_later_admission(session):
    session._backend = SimpleNamespace(disconnect=AsyncMock())
    session._adopted_recovery_pending = True
    await session._disconnect_backend()
    assert session._backend is None
    assert not session._adopted_recovery_pending
    await session.preflight_delivery_admission()


@pytest.mark.asyncio
async def test_failed_recovery_is_requeried_after_second_restart(db, monkeypatch):
    from datetime import datetime, timezone
    from app.session import AgentSession

    _save_running_session('twice-537', thread='thread-537')
    monkeypatch.setattr('app.fdstore.acquire_fds', lambda: {
        'agent.twice-537.stdin': 101, 'agent.twice-537.stdout': 102,
    })
    monkeypatch.setattr(manager, 'publish_backend_fds', lambda *args: True)
    backends = [
        SimpleNamespace(adopt=AsyncMock(), recover_adopted_turn=AsyncMock(
            side_effect=TimeoutError('server did not answer')), active_turn_id=None),
        SimpleNamespace(adopt=AsyncMock(), recover_adopted_turn=AsyncMock(
            return_value=None), active_turn_id=None),
    ]
    for generation, backend in enumerate(backends):
        mgr = manager.SessionManager()
        async def load(row, **kwargs):
            restored = AgentSession(
                id=row['id'], name=row['name'], scope=row['scope'], cwd=row['cwd'],
                model=row['model'], system_prompt='', backend_type='codex',
                created_at=datetime.now(timezone.utc), session_id=row['session_id'],
            )
            restored._make_backend = lambda: backend
            restored._activate_backend_tasks = lambda: None
            mgr.sessions[restored.id] = restored
            return restored
        monkeypatch.setattr(mgr, '_load_from_db', load)
        await mgr.auto_resume_all()
        restored = mgr.sessions['twice-537']
        await restored._drain_persist()
        with database._conn() as conn:
            row = conn.execute('SELECT status, active_turn_id FROM sessions WHERE id=?',
                               ('twice-537',)).fetchone()
        backend.recover_adopted_turn.assert_awaited_once()
        if generation == 0:
            assert row['status'] == 'running'
            assert not row['active_turn_id']
            assert restored._adopted_recovery_pending
        else:
            assert row['status'] == 'idle'
            assert not restored._adopted_recovery_pending
