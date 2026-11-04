"""Approved V-1244 archival keeps actual history objects through lifecycle paths."""
import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app import backend_hub as hub, hub_workspace as hw
from app.events import MessageProvenance
from app.multicode_client import MultiCodeError
from tests.test_hub_workspace import FakeSsh, repo, _offline_hub_pool, _backend, _turn
from tests.test_merge_operations import merge_db


class HistoryMc:
    def __init__(self):
        self.calls = []
        self.project = {'id': 'project-owned', 'history': ['thread-owned'], 'usage': {'tokens': 321}}
        self.thread = {'id': 'thread-owned', 'messages': ['accepted result'], 'turns': ['turn-1'],
                       'attachments': ['attachment-1'], 'archived': False}
        self.lost_archive_reply = False
        self.missing_thread = False
        self.pending_request_count = 0
        self.read_error = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        pass

    async def tool_call(self, name, args):
        self.calls.append((name, dict(args)))
        if name == 't3_thread_read':
            if self.read_error:
                raise self.read_error
            if self.missing_thread:
                raise MultiCodeError(
                    f'MultiCode tool t3_thread_read failed: Thread {args["threadId"]} is no longer available.',
                    remote_code='thread_not_found', remote_resource_id=args['threadId'])
            return {'thread': {'threadId': self.thread['id'], 'projectId': self.project['id'],
                               'pendingRequestCount': self.pending_request_count}, 'items': []}
        elif name == 't3_thread_interrupt':
            assert args['threadId'] == self.thread['id']
        elif name == 't3_thread_wait':
            assert args['threadId'] == self.thread['id']
            return {'status': 'interrupted', 'timedOut': False}
        elif name == 't3_thread_organize':
            assert args == {'threadId': self.thread['id'], 'action': 'archive'}
            self.thread['archived'] = True
            if self.lost_archive_reply:
                self.lost_archive_reply = False
                raise OSError('lost archive response after remote acceptance')
        elif name == 't3_project_delete':
            # Intentionally destructive fake: a regression is detected by object
            # survival assertions as well as the actual routed action names.
            self.project.clear()
            self.thread.clear()
        else:
            raise AssertionError(f'unexpected remote action: {name}')
        return {'ok': True}


@pytest.fixture
def history(tmp_path, monkeypatch):
    monkeypatch.setattr(hw, 'STATE_DIR', tmp_path / 'records')
    wt = tmp_path / 'worktree'
    wt.mkdir()
    ssh = FakeSsh(tmp_path / 'remote')
    ws = hw.WorkspaceState('hub-aaaaaaaaaaaaaaaa', str(wt), str(ssh.base / 'hub-aaaaaaaaaaaaaaaa'),
                           project_id='project-owned', thread_id='thread-owned',
                           manifest={'result.py': 'synthetic-hash'}, input_manifest={'input.txt': 'input-hash'})
    remote = Path(ws.remote_dir)
    remote.mkdir(parents=True)
    (remote / 'provider.jsonl').write_text('provider history and accounting\n')
    (remote / 'result.py').write_text('accepted work\n')
    ws.save()
    ws.path().with_suffix('.sync.tar').write_bytes(b'recovery provenance')
    mc = HistoryMc()
    monkeypatch.setattr(hw.HubSsh, 'from_env', classmethod(lambda _: ssh))
    monkeypatch.setattr(hub.MultiCodeClient, 'from_env', classmethod(lambda _: mc))
    monkeypatch.setattr(hub, 'hub_configured', lambda: None)
    return SimpleNamespace(ws=ws, ssh=ssh, mc=mc, wt=wt,
                           project=copy.deepcopy(mc.project), thread=copy.deepcopy(mc.thread))


def assert_history_survives(h, *, archived=True):
    assert h.mc.project == h.project
    assert {k: v for k, v in h.mc.thread.items() if k != 'archived'} == {
        k: v for k, v in h.thread.items() if k != 'archived'}
    assert h.mc.thread['archived'] is archived
    assert (Path(h.ws.remote_dir) / 'provider.jsonl').read_text() == 'provider history and accounting\n'
    assert (Path(h.ws.remote_dir) / 'result.py').read_text() == 'accepted work\n'
    record = hw.WorkspaceState.load(h.ws.ws_id)
    assert record is not None
    assert record.archived is archived
    assert record.manifest == h.ws.manifest
    assert record.input_manifest == h.ws.input_manifest
    assert record.project_id == h.ws.project_id and record.thread_id == h.ws.thread_id
    assert h.ws.path().with_suffix('.sync.tar').read_bytes() == b'recovery provenance'
    assert not h.ssh.removed and not getattr(h.ssh, 'scrubbed', [])
    assert not any(name == 't3_project_delete' for name, _ in h.mc.calls)


@pytest.mark.asyncio
async def test_archive_preserves_objects_and_idempotent_restart(history):
    h = history
    await hub.archive_for_worktree(str(h.wt))
    assert_history_survives(h)
    calls = copy.deepcopy(h.mc.calls)
    # Replay from only the persisted record, with no available transport.
    assert await hub.archive_for_worktree(str(h.wt), mc=object()) == []
    assert h.mc.calls == calls
    assert_history_survives(h)


@pytest.mark.asyncio
async def test_archive_lost_reply_retries_same_identity_without_purge(history):
    h = history
    h.mc.lost_archive_reply = True
    with pytest.raises(OSError, match='lost archive response'):
        await hub.archive_for_worktree(str(h.wt))
    assert not hw.WorkspaceState.load(h.ws.ws_id).archived
    await hub.archive_for_worktree(str(h.wt))
    assert_history_survives(h)
    assert [a['threadId'] for n, a in h.mc.calls if n == 't3_thread_organize'] == [h.ws.thread_id] * 2


@pytest.mark.asyncio
@pytest.mark.parametrize('blocker', ['pending', 'unsafe-input', 'path', 'transport'])
async def test_blocked_close_leaves_lifecycle_jobs_and_history_intact(history, merge_db, monkeypatch, blocker):
    from app import db, manager as module
    from app.bg_jobs import bg_manager
    h = history
    row = db.get_session('merge-session')
    row.update(worktree_path=str(h.wt), backend_type='hub', model='hub-gpt-6.1-sol')
    db.save_session(row)
    before = db.get_session('merge-session')
    if blocker == 'pending':
        h.ws.pending_sync = {'phase': 'report', 'entries': [{'tool': 'send_message'}]}
        h.ws.save()
    elif blocker == 'unsafe-input':
        h.ws.input_manifest = {'../escape.md': 'synthetic-hash'}
        h.ws.save()
    elif blocker == 'path':
        h.ws.manifest['../escape.md'] = 'synthetic-hash'
        h.ws.save()
    else:
        h.mc.tool_call = AsyncMock(side_effect=OSError('transport unavailable'))
    manager = module.SessionManager()
    cancel = AsyncMock()
    remove = Mock()
    cleanup = Mock()
    monkeypatch.setattr(bg_manager, 'cancel_by_session', cancel)
    monkeypatch.setattr(module, 'remove_worktree', remove)
    monkeypatch.setattr(manager, '_cleanup_cli_home', cleanup)
    with pytest.raises((hw.HubWorkspaceError, OSError)):
        await manager.remove('merge-session')
    assert db.get_session('merge-session') == before
    cancel.assert_not_awaited()
    remove.assert_not_called()
    cleanup.assert_not_called()
    assert h.wt.exists() and h.ws.path().exists()
    assert h.ws.path().with_suffix('.sync.tar').read_bytes() == b'recovery provenance'
    assert h.mc.project == h.project and h.mc.thread == h.thread


@pytest.mark.asyncio
@pytest.mark.parametrize(('thread_id', 'blocked'), [
    ('synthetic-thread-a', True),
    ('synthetic-thread-b', True),
    ('synthetic-thread-c', False),
])
async def test_missing_thread_archives_only_local_card_and_preserves_retained_data(
        history, merge_db, monkeypatch, thread_id, blocked):
    from app import db, manager as module, message_deliveries
    from app.bg_jobs import bg_manager
    h = history
    h.ws.thread_id = thread_id
    h.ws.file_policy_blocked = blocked
    h.ws.save()
    h.mc.thread['id'] = thread_id
    h.thread = copy.deepcopy(h.mc.thread)
    h.mc.missing_thread = True
    row = db.get_session('merge-session')
    row.update(worktree_path=str(h.wt), backend_type='hub', model='hub-gpt-6.1-sol',
               cost_usd=1.25, total_input_tokens=321, total_turns=2, total_tool_calls=3)
    db.save_session(row)
    db.add_log('merge-session', datetime.now(timezone.utc), 'text', 'retained local history')
    before_row = db.get_session('merge-session')
    delivery_id = f'00000000-0000-4000-8000-0000000126{int(thread_id[-1], 36):02d}'
    await message_deliveries.accept_message_delivery(
        delivery_id=delivery_id, source_principal='synthetic:parent', source_scope=str(h.wt),
        target_session_id='merge-session', target_name='worker', target_scope=str(h.wt),
        target_generation='session=merge-session|task=|branch=|needs_switch=0',
        message='retained pending item', rendered_message='retained pending item', wake=False,
        provenance=MessageProvenance(origin='user', senders=('user',), subtype='dashboard'))
    message_deliveries.prepare_message_delivery(delivery_id)
    message_deliveries.mark_message_delivery_dispatching(delivery_id)
    message_deliveries.mark_message_delivery_unknown(delivery_id, RuntimeError('synthetic uncertain delivery'))
    before_delivery = dict(message_deliveries._row(delivery_id))
    with db._conn() as connection:
        before_logs = [tuple(item) for item in connection.execute(
            "SELECT * FROM logs WHERE session_id=? ORDER BY id", ('merge-session',))]
    state_hash = hashlib.sha256(h.ws.path().read_bytes()).hexdigest()
    sync_hash = hashlib.sha256(h.ws.path().with_suffix('.sync.tar').read_bytes()).hexdigest()
    history_hash = hashlib.sha256((Path(h.ws.remote_dir) / 'provider.jsonl').read_bytes()).hexdigest()

    manager = module.SessionManager()
    remove_worktree = Mock()
    cleanup_cli = Mock()
    cancel_jobs = AsyncMock()
    monkeypatch.setattr(bg_manager, 'cancel_by_session', cancel_jobs)
    monkeypatch.setattr(module, 'remove_worktree', remove_worktree)
    monkeypatch.setattr(manager, '_cleanup_cli_home', cleanup_cli)
    session = manager._hydrate_row(db.get_session('merge-session'))

    await manager.remove(session.id)

    after_row = db.get_session('merge-session')
    assert after_row['status'] == 'archived'
    for key in ('cost_usd', 'total_input_tokens', 'total_turns', 'total_tool_calls'):
        assert after_row[key] == before_row[key]
    with db._conn() as connection:
        after_logs = [tuple(item) for item in connection.execute(
            "SELECT * FROM logs WHERE session_id=? ORDER BY id", ('merge-session',))]
    assert after_logs == before_logs
    assert dict(message_deliveries._row(delivery_id)) == before_delivery
    assert hashlib.sha256(h.ws.path().read_bytes()).hexdigest() == state_hash
    assert hw.WorkspaceState.load(h.ws.ws_id).file_policy_blocked is blocked
    assert hashlib.sha256(h.ws.path().with_suffix('.sync.tar').read_bytes()).hexdigest() == sync_hash
    assert hashlib.sha256((Path(h.ws.remote_dir) / 'provider.jsonl').read_bytes()).hexdigest() == history_hash
    assert h.wt.is_dir() and Path(h.ws.remote_dir).is_dir()
    assert h.mc.project == h.project and h.mc.thread == h.thread
    assert [name for name, _ in h.mc.calls] == ['t3_thread_read']
    assert remove_worktree.call_count == cleanup_cli.call_count == 0
    cancel_jobs.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_thread_close_refuses_pending_sync_and_ambiguous_generation(
        history, merge_db, monkeypatch):
    from app import db, manager as module
    from app.hub_workspace import WorkspaceState
    h = history
    h.mc.missing_thread = True
    row = db.get_session('merge-session')
    row.update(worktree_path=str(h.wt), backend_type='hub', model='hub-gpt-6.1-sol')
    db.save_session(row)
    manager = module.SessionManager()
    session = manager._hydrate_row(db.get_session('merge-session'))

    with monkeypatch.context() as patcher:
        patcher.setattr(db, 'bg_get_jobs', lambda **_: [{'id': 'synthetic-active-job'}])
        with pytest.raises(hw.HubWorkspaceError, match='active background job'):
            await manager.remove(session.id)
    assert db.get_session('merge-session')['status'] == 'idle'
    assert h.mc.calls == []

    h.ws.pending_sync = {'phase': 'report', 'entries': [{'tool': 'send_message'}]}
    h.ws.save()
    with pytest.raises(hw.HubWorkspaceError, match='pending sync'):
        await manager.remove(session.id)
    assert db.get_session('merge-session')['status'] == 'idle'
    assert h.mc.calls == []

    h.ws.pending_sync = {}
    h.ws.save()
    extra = WorkspaceState(
        'hub-bbbbbbbbbbbbbbbb', str(h.wt), str(h.ws.remote_dir) + '-other',
        project_id='other-project', thread_id='other-thread')
    extra.save()
    with pytest.raises(hw.HubWorkspaceError, match='ambiguous'):
        await manager.remove(session.id)
    assert db.get_session('merge-session')['status'] == 'idle'
    assert h.mc.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize('state', [
    'QUEUED', 'PREPARING', 'DISPATCHING', 'WAITING_NEXT_TURN', 'WAITING_QUOTA',
])
async def test_missing_thread_close_refuses_dispatchable_delivery_states_without_mutating_them(
        history, merge_db, state):
    from app import db, manager as module, message_deliveries
    h = history
    h.mc.missing_thread = True
    row = db.get_session('merge-session')
    row.update(worktree_path=str(h.wt), backend_type='hub', model='hub-gpt-6.1-sol')
    db.save_session(row)
    delivery_id = '00000000-0000-4000-8000-000000012699'
    await message_deliveries.accept_message_delivery(
        delivery_id=delivery_id, source_principal='synthetic:parent', source_scope=str(h.wt),
        target_session_id='merge-session', target_name='worker', target_scope=str(h.wt),
        target_generation='session=merge-session|task=|branch=|needs_switch=0',
        message='queued recovery', rendered_message='queued recovery', wake=False,
        provenance=MessageProvenance(origin='user', senders=('user',), subtype='dashboard'))
    if state != 'QUEUED':
        message_deliveries.prepare_message_delivery(delivery_id)
    if state == 'DISPATCHING':
        message_deliveries.mark_message_delivery_dispatching(delivery_id)
    elif state == 'WAITING_NEXT_TURN':
        assert message_deliveries.hold_message_delivery_for_turn_end(delivery_id)
    elif state == 'WAITING_QUOTA':
        with db._conn() as connection:
            connection.execute(
                "UPDATE message_deliveries SET state='WAITING_QUOTA' WHERE delivery_id=?",
                (delivery_id,),
            )
    before_delivery = dict(message_deliveries._row(delivery_id))
    manager = module.SessionManager()
    session = manager._hydrate_row(db.get_session('merge-session'))

    with pytest.raises(hw.HubWorkspaceError, match='delivery prevents retained archive'):
        await manager.remove(session.id)

    assert db.get_session('merge-session')['status'] == 'idle'
    assert dict(message_deliveries._row(delivery_id)) == before_delivery
    assert h.wt.is_dir() and not h.ws.archived
    assert [name for name, _ in h.mc.calls] == ['t3_thread_read']


@pytest.mark.asyncio
async def test_missing_thread_close_refuses_queued_initial_delivery_without_mutating_it(
        history, merge_db, monkeypatch):
    from app import db, initial_deliveries, manager as module
    h = history
    h.mc.missing_thread = True
    row = db.get_session('merge-session')
    row.update(worktree_path=str(h.wt), backend_type='hub', model='hub-gpt-6.1-sol')
    db.save_session(row)
    delivery_id = '00000000-0000-4000-8000-000000012698'
    provenance = MessageProvenance(
        origin='agent', senders=('synthetic-parent',), subtype='initial_delivery', ref=delivery_id)
    monkeypatch.setattr(initial_deliveries, 'ensure_delivery_runner', Mock())
    await initial_deliveries.accept_initial_delivery(
        delivery_id=delivery_id, session_id='merge-session', worker_name='worker',
        scope=str(h.wt), sender='synthetic-parent', message='queued initial task',
        provenance=provenance)
    with db._conn() as connection:
        before = dict(connection.execute(
            "SELECT * FROM initial_deliveries WHERE delivery_id=?", (delivery_id,)).fetchone())
    manager = module.SessionManager()
    session = manager._hydrate_row(db.get_session('merge-session'))

    with pytest.raises(hw.HubWorkspaceError, match='initial delivery prevents retained archive'):
        await manager.remove(session.id)

    assert db.get_session('merge-session')['status'] == 'idle'
    with db._conn() as connection:
        after = dict(connection.execute(
            "SELECT * FROM initial_deliveries WHERE delivery_id=?", (delivery_id,)).fetchone())
    assert after == before
    assert h.wt.is_dir() and not h.ws.archived
    assert [name for name, _ in h.mc.calls] == ['t3_thread_read']


@pytest.mark.asyncio
async def test_missing_thread_close_refuses_transient_identity_race_and_pending_requests(
        history, merge_db):
    from app import db, manager as module
    h = history
    row = db.get_session('merge-session')
    row.update(worktree_path=str(h.wt), backend_type='hub', model='hub-gpt-6.1-sol')
    db.save_session(row)
    manager = module.SessionManager()
    session = manager._hydrate_row(db.get_session('merge-session'))

    h.mc.read_error = MultiCodeError('read timeout', retryable=True)
    with pytest.raises(hw.HubWorkspaceError, match='status unavailable'):
        await manager.remove(session.id)
    assert db.get_session('merge-session')['status'] == 'idle'
    assert [name for name, _ in h.mc.calls] == ['t3_thread_read']

    h.mc.calls.clear()
    h.mc.read_error = None
    h.mc.missing_thread = True
    original_call = h.mc.tool_call
    async def change_generation(name, args):
        if name == 't3_thread_read':
            current = hw.WorkspaceState.load(h.ws.ws_id)
            current.thread_id = 'synthetic-new-generation'
            current.save()
        return await original_call(name, args)
    h.mc.tool_call = change_generation
    with pytest.raises(hw.HubWorkspaceError, match='generation changed'):
        await manager.remove(session.id)
    assert db.get_session('merge-session')['status'] == 'idle'
    h.mc.tool_call = original_call

    h.ws.thread_id = 'thread-owned'
    h.ws.save()
    h.mc.thread['id'] = 'thread-owned'
    h.mc.missing_thread = False
    h.mc.pending_request_count = 2
    h.mc.calls.clear()
    with pytest.raises(hw.HubWorkspaceError, match='pending requests'):
        await manager.remove(session.id)
    assert db.get_session('merge-session')['status'] == 'idle'
    assert [name for name, _ in h.mc.calls] == ['t3_thread_read']


@pytest.mark.asyncio
@pytest.mark.parametrize('loaded', [False, True])
async def test_stored_and_loaded_close_preserve_history_and_accounting(history, merge_db, monkeypatch, loaded):
    from app import db, manager as module
    from app.bg_jobs import bg_manager
    from app.session import AgentStatus
    h = history
    row = db.get_session('merge-session')
    row.update(worktree_path=str(h.wt), backend_type='hub', model='hub-gpt-6.1-sol', cost_usd=1.25,
               total_input_tokens=321, total_turns=2, total_tool_calls=3)
    db.save_session(row)
    stats_before = db.get_stats(row['scope'])
    db.add_log('merge-session', datetime.now(timezone.utc), 'text', 'saved accepted result')
    manager = module.SessionManager()
    if loaded:
        # Only the provider connection is fake; real remove/archive_session runs.
        session = manager._hydrate_row(db.get_session('merge-session'))
        session.status = AgentStatus.IDLE
        session.loaded = True
        disconnect = AsyncMock()
        monkeypatch.setattr(session, '_disconnect_backend', disconnect)
        manager.sessions[session.id] = session
    monkeypatch.setattr(bg_manager, 'cancel_by_session', AsyncMock())
    monkeypatch.setattr(module, 'remove_worktree', Mock())
    monkeypatch.setattr(manager, '_cleanup_cli_home', Mock())
    await manager.remove('merge-session')
    archived = db.get_session('merge-session')
    assert archived['status'] == 'archived'
    assert archived['cost_usd'] == 1.25
    stats_after = db.get_stats(row['scope'])
    for key in ('total_cost_usd', 'total_input_tokens', 'total_turns', 'total_tool_calls', 'total_sessions'):
        assert stats_after[key] == stats_before[key]
    assert stats_after['archived'] == stats_before['archived'] + 1
    with db._conn() as c:
        assert c.execute("SELECT content FROM logs WHERE session_id=? AND type='text'", ('merge-session',)).fetchone()[0] == 'saved accepted result'
    assert 'merge-session' not in manager.sessions
    if loaded:
        disconnect.assert_awaited_once()
    assert_history_survives(h)


@pytest.mark.asyncio
@pytest.mark.parametrize('outcome,next_task,expected_archive', [('complete', '', False), ('continue', '', False), ('complete', '43', False)])
async def test_merge_cleanup_preserves_history_for_complete_continue_and_handoff(history, monkeypatch, outcome, next_task, expected_archive):
    from app import merge_operations as operations, workspace, worktree_cleanup
    h = history
    monkeypatch.setattr(operations, 'get_session', lambda _: {'worktree_path': str(h.wt), 'backend_type': 'hub'})
    monkeypatch.setattr(workspace, '_resolve_repo', lambda *_: h.wt)
    clean = Mock(return_value={'state': 'skipped'})
    monkeypatch.setattr(worktree_cleanup, 'clean_worktree', clean)
    await operations._clean_worktree_after_merge(
        {'session_id': 'worker', 'request': {'merge_schema_version': 2, 'task_outcome': outcome, 'next_task_id': next_task}},
        {'git': {'target_branch': 'main'}})
    assert_history_survives(h, archived=expected_archive)
    assert clean.call_count == int(expected_archive)


@pytest.mark.asyncio
async def test_sweep_never_interprets_old_incomplete_or_missing_records_as_disposable(history, monkeypatch):
    h = history
    payload = json.loads(h.ws.path().read_text())
    payload.pop('archived')  # legacy record; no migration/inference grants deletion
    payload.update(created_at=0, thread_id='', project_id='')
    h.ws.path().write_text(json.dumps(payload))
    orphan = Path(h.ws.remote_dir).parent / 'hub-bbbbbbbbbbbbbbbb'
    orphan.mkdir()
    (orphan / 'history.jsonl').write_text('unrecorded retained history')
    bad = hw.STATE_DIR / 'hub-cccccccccccccccc.json'
    bad.write_text('{invalid retained record')
    monkeypatch.setattr(hub.MultiCodeClient, 'from_env', Mock(side_effect=AssertionError('sweep must not contact remote')))
    before = h.ws.path().read_bytes()
    for live in (set(), {str(h.wt): 'different-generation'}):
        report = await hub.sweep_orphans(live, min_age=0)
        assert report['released'] == report['remote_dirs'] == report['projects'] == []
    assert h.ws.path().read_bytes() == before
    assert not hw.WorkspaceState.load(h.ws.ws_id).archived
    assert bad.read_text() == '{invalid retained record'
    assert (orphan / 'history.jsonl').read_text() == 'unrecorded retained history'
    assert h.mc.project == h.project and h.mc.thread == h.thread


@pytest.mark.asyncio
async def test_pending_transition_keeps_old_binding_and_recovery(history, merge_db):
    from app import db, manager as module
    h = history
    h.ws.pending_sync = {'phase': 'import', 'entries': []}
    h.ws.save()
    row = db.get_session('merge-session')
    row.update(worktree_path=str(h.wt), backend_type='hub', model='hub-gpt-6.1-sol')
    db.save_session(row)
    manager = module.SessionManager()
    session = manager._hydrate_row(db.get_session('merge-session'))
    with pytest.raises(hw.HubWorkspaceError, match='pending sync'):
        await manager.transition_lifecycle(session, branch='task-43/worker', base_branch='main', task_id='43', needs_switch=False)
    assert session.task_id == '42' and db.get_session(session.id)['task_id'] == '42'
    assert hw.WorkspaceState.load(h.ws.ws_id).pending_sync == h.ws.pending_sync
    assert h.mc.calls == []


@pytest.mark.asyncio
async def test_archived_generation_is_not_resumed_by_stale_or_reconstructed_backend(repo, tmp_path, monkeypatch):
    monkeypatch.setattr(hw, 'known_secret_values', lambda extra=None: [])
    backend, ssh, mc = _backend(repo, tmp_path, monkeypatch, lambda _: None)
    await _turn(backend, 'first assignment')
    old = backend._state
    await hub.archive_for_worktree(str(repo), ssh=ssh, mc=mc)
    assert hw.WorkspaceState.load(old.ws_id).archived
    before = list(mc.calls)
    await _turn(backend, 'new assigned task')
    assert backend.session_id != old.ws_id
    assert old.path().exists() and Path(old.remote_dir).exists()
    assert not any(n == 't3_project_delete' for n, _ in mc.calls[len(before):])


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [{'status': 'running'}, {'status': 'interrupted', 'timedOut': True}, {}])
async def test_unconfirmed_thread_termination_blocks_archive_and_retains_history(history, status):
    h = history
    real = h.mc.tool_call
    async def call(name, args):
        if name == 't3_thread_wait':
            return status
        return await real(name, args)
    h.mc.tool_call = call
    with pytest.raises(hw.HubWorkspaceError, match='termination is not confirmed'):
        await hub.archive_for_worktree(str(h.wt))
    assert_history_survives(h, archived=False)
    assert not any(n == 't3_thread_organize' for n, _ in h.mc.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize('reconstruct', [False, True])
async def test_corrupted_known_record_refuses_resume_without_provider_turn(repo, tmp_path, monkeypatch, reconstruct):
    monkeypatch.setattr(hw, 'known_secret_values', lambda extra=None: [])
    backend, ssh, mc = _backend(repo, tmp_path, monkeypatch, lambda _: None)
    await _turn(backend, 'assignment')
    state = backend._state
    state.path().write_text('{invalid retained record')
    before = list(mc.calls)
    if reconstruct:
        recovered = hub.HubBackend(backend.model, str(repo), resume_session_id=state.ws_id)
        with pytest.raises(hw.HubWorkspaceError, match='record is unreadable'):
            await recovered.connect()
    else:
        events = await _turn(backend, 'retry')
        assert events[-1].metadata['ok'] is False
        assert any('record is unreadable' in e.content for e in events)
    assert state.path().read_text() == '{invalid retained record'
    assert Path(state.remote_dir).exists()
    assert mc.calls == before


@pytest.mark.asyncio
async def test_successful_task_transition_archives_old_generation_and_keeps_history(history, merge_db):
    from app import db, manager as module
    h = history
    row = db.get_session('merge-session')
    row.update(worktree_path=str(h.wt), backend_type='hub', model='hub-gpt-6.1-sol')
    db.save_session(row)
    manager = module.SessionManager()
    session = manager._hydrate_row(db.get_session('merge-session'))
    await manager.transition_lifecycle(session, branch='task-43/worker', base_branch='main', task_id='43', needs_switch=False)
    assert session.task_id == '43' and db.get_session(session.id)['task_id'] == '43'
    assert_history_survives(h)


@pytest.mark.asyncio
async def test_pending_return_arriving_during_archive_is_not_overwritten(history):
    h = history
    real = h.mc.tool_call
    journal = {'phase': 'report', 'entries': [{'tool': 'send_message', '_delivery_id': 'retained-delivery'}]}
    async def concurrent_return(name, args):
        result = await real(name, args)
        if name == 't3_thread_organize':
            latest = hw.WorkspaceState.load(h.ws.ws_id)
            latest.pending_sync = copy.deepcopy(journal)
            latest.save()
        return result
    h.mc.tool_call = concurrent_return
    with pytest.raises(hw.HubWorkspaceError, match='pending sync'):
        await hub.archive_for_worktree(str(h.wt))
    latest = hw.WorkspaceState.load(h.ws.ws_id)
    assert latest.pending_sync == journal and not latest.archived
    assert h.mc.project == h.project
    assert h.mc.thread['messages'] == h.thread['messages']
    assert Path(h.ws.remote_dir).exists() and h.ws.path().with_suffix('.sync.tar').exists()


@pytest.mark.asyncio
async def test_new_identity_arriving_during_archive_is_not_relabelled_closed(history):
    h = history
    real = h.mc.tool_call
    async def concurrent_identity(name, args):
        result = await real(name, args)
        if name == 't3_thread_organize':
            latest = hw.WorkspaceState.load(h.ws.ws_id)
            latest.thread_id = 'new-assigned-thread'
            latest.save()
        return result
    h.mc.tool_call = concurrent_identity
    with pytest.raises(hw.HubWorkspaceError, match='identity changed'):
        await hub.archive_for_worktree(str(h.wt))
    latest = hw.WorkspaceState.load(h.ws.ws_id)
    assert latest.thread_id == 'new-assigned-thread' and not latest.archived
    assert h.mc.project == h.project
    assert h.mc.thread['messages'] == h.thread['messages']


@pytest.mark.asyncio
async def test_privacy_refusal_retains_return_arriving_during_policy_probe(history):
    h = history
    journal = {'phase': 'report', 'entries': [{'tool': 'send_message', '_delivery_id': 'privacy-retained-return'}]}
    async def refused_probe(remote_dir):
        latest = hw.WorkspaceState.load(h.ws.ws_id)
        latest.pending_sync = copy.deepcopy(journal)
        latest.save()
        raise hw.HubFilePolicyError('synthetic retained privacy refusal')
    h.ssh.assert_file_policy = refused_probe
    with pytest.raises(hw.HubFilePolicyError):
        await hub.archive_for_worktree(str(h.wt))
    latest = hw.WorkspaceState.load(h.ws.ws_id)
    assert latest.pending_sync == journal and latest.file_policy_blocked
    assert not latest.archived and h.mc.calls == []
    assert h.mc.project == h.project and h.mc.thread == h.thread


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', ['transition', 'close'])
async def test_native_lifecycle_archives_legacy_company_history_without_blocking(history, merge_db, monkeypatch, operation):
    from app import db, manager as module
    from app.bg_jobs import bg_manager
    h = history
    h.ws.file_policy_blocked = True
    h.ws.save()
    retained = h.ws.path().read_bytes()
    row = db.get_session('merge-session')
    row.update(worktree_path=str(h.wt), backend_type='codex', model='gpt-6-luna')
    db.save_session(row)
    manager = module.SessionManager()
    session = manager._hydrate_row(db.get_session('merge-session'))
    if operation == 'transition':
        await manager.transition_lifecycle(session, branch='task-43/worker', base_branch='main', task_id='43', needs_switch=False)
        assert db.get_session(session.id)['task_id'] == '43'
    else:
        monkeypatch.setattr(bg_manager, 'cancel_by_session', AsyncMock())
        monkeypatch.setattr(module, 'remove_worktree', Mock())
        monkeypatch.setattr(manager, '_cleanup_cli_home', Mock())
        await manager.remove(session.id)
        assert db.get_session(session.id)['status'] == 'archived'
    assert json.loads(h.ws.path().read_bytes()) == {**json.loads(retained), 'archived': True}
    assert_history_survives(h)
    assert any(name == 't3_thread_organize' for name, _ in h.mc.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize('explicit_next', [False, True])
async def test_post_merge_cleanup_does_not_close_a_new_assignment(history, monkeypatch, explicit_next):
    from app import merge_operations as operations, workspace, worktree_cleanup
    h = history
    monkeypatch.setattr(operations, 'get_session', lambda _: {'worktree_path': str(h.wt), 'task_id': '43'})
    monkeypatch.setattr(workspace, '_resolve_repo', lambda *_: h.wt)
    clean = Mock(return_value={'state': 'skipped'})
    monkeypatch.setattr(worktree_cleanup, 'clean_worktree', clean)
    await operations._clean_worktree_after_merge(
        {'session_id': 'worker', 'accepted_task_id': '42',
         'request': {'merge_schema_version': 2, 'task_outcome': 'complete',
                     'next_task_id': '43' if explicit_next else ''}},
        {'git': {'target_branch': 'main'}})
    assert_history_survives(h, archived=False)
    assert h.mc.calls == []
    clean.assert_not_called()
