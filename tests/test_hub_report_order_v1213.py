"""V-1213: synthetic real import/commit/report path, including durable recovery."""
import asyncio
import json
import threading
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app import backend_hub as hub, hub_workspace as hw, hub_outbox as ob
from tests.test_hub_workspace import (
    repo, _offline_hub_pool, _outbox_backend, _turn, _git,
)
from tests.test_turn_signals import world


class Parent:
    def __init__(self, root):
        self.root = root
        self.calls = []
        self.receipts = {}
        self.lose_response = False

    async def __call__(self, method, path, body):
        head = _git(self.root, 'rev-parse', '--short', 'HEAD').strip()
        committed = _git(self.root, 'show', 'HEAD:calc.py')
        self.calls.append((path, dict(body), head, committed))
        if path.endswith('/send'):
            key = body['delivery_id']
            if key in self.receipts:
                assert self.receipts[key] == body
            self.receipts[key] = dict(body)
            if self.lose_response:
                self.lose_response = False
                raise OSError('synthetic response lost after durable receipt')
            return {'ok': True, 'delivery_state': 'QUEUED'}
        return {'ok': True}


def worker(repo, tmp_path, monkeypatch, entries=None):
    parent = Parent(repo)
    backend, ssh, mc = _outbox_backend(repo, tmp_path, monkeypatch, entries or [
        {'tool': 'send_message', 'args': {'message': 'DONE: tests and result ready'}},
    ], parent)
    return backend, ssh, mc, parent


@pytest.mark.asyncio
async def test_parent_observes_committed_result_and_final_head(repo, tmp_path, monkeypatch):
    backend, ssh, mc, parent = worker(repo, tmp_path, monkeypatch)
    before = _git(repo, 'rev-parse', '--short', 'HEAD').strip()
    events = await _turn(backend, 'go')
    assert events[-1].metadata['ok']
    _, body, observed_head, committed = parent.calls[0]
    assert 'return a + b' in committed, 'report arrived before local commit'
    assert len(parent.calls) == 1
    assert observed_head != before
    assert f'local HEAD {observed_head}' in body['message']
    assert body['message'].startswith('[hub result] status=ok; provider=completed')
    assert 'DONE: tests and result ready' in body['message']
    assert not hw.WorkspaceState.load(backend.session_id).pending_sync
    assert not backend._state.path().with_suffix('.sync.tar').exists()
    await _turn(backend, 'follow-up')
    assert len(parent.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['conflict', 'rejected', 'commit', 'unstaged', 'ignored', 'oserror'])
async def test_incomplete_sync_reports_partial_and_ends_failed(repo, tmp_path, monkeypatch, failure):
    backend, ssh, mc, parent = worker(repo, tmp_path, monkeypatch)
    original = mc.hub_edit

    def edit(root):
        original(root)
        if failure == 'conflict':
            (repo / 'calc.py').write_text('local competing edit\n')
        elif failure == 'rejected':
            (root / 'unsafe.pem').write_text('synthetic excluded file\n')
        elif failure == 'ignored':
            (repo / '.git/info/exclude').write_text('ignored.txt\n')
            (root / 'ignored.txt').write_text('new ignored output\n')
    mc.hub_edit = edit
    if failure in {'commit', 'oserror'}:
        def fail(*args):
            raise (OSError if failure == 'oserror' else hw.HubWorkspaceError)('synthetic commit refusal')
        monkeypatch.setattr(hw, 'commit_sync', fail)
    elif failure == 'unstaged':
        real = hw.commit_sync
        def partial(root, changed, deleted, message):
            sha, _ = real(root, changed, deleted, message)
            return sha, [('synthetic.txt', 'git refused')]
        monkeypatch.setattr(hw, 'commit_sync', partial)
    events = await _turn(backend, 'go')
    assert events[-1].metadata['ok'] is False
    assert len(parent.receipts) == 1
    text = parent.calls[0][1]['message']
    assert text.startswith('[hub result] status=partial/failed;')
    expected = {'conflict': 'conflicts', 'rejected': 'rejected:', 'commit': 'NOT COMMITTED',
                'oserror': 'NOT COMMITTED', 'unstaged': 'left uncommitted', 'ignored': 'left uncommitted'}
    assert expected[failure] in text
    if failure == 'conflict':
        assert (repo / 'calc.py').read_text() == 'local competing edit\n'


@pytest.mark.asyncio
@pytest.mark.parametrize('receipt', ['lost', 'unknown', 'quota'])
async def test_report_recovery_uses_same_durable_identity_and_body(repo, tmp_path, monkeypatch, receipt):
    backend, ssh, mc, parent = worker(repo, tmp_path, monkeypatch)
    parent.lose_response = receipt == 'lost'
    real_call = parent.__call__
    first = True

    async def call(method, path, body):
        nonlocal first
        if first and receipt == 'unknown':
            first = False
            return {'ok': True, 'delivery_state': 'DELIVERY_UNKNOWN'}
        if receipt == 'quota':
            await real_call(method, path, body)
            return {'ok': True, 'delivery_state': 'WAITING_QUOTA', 'error': {'code': 'WAITING_QUOTA'}}
        return await real_call(method, path, body)
    backend._bridge = ob.HubBridge(backend._bridge.identity, call)
    events = await _turn(backend, 'go')
    if receipt == 'quota':
        assert events[-1].metadata['ok']
        assert not backend._state.pending_sync
        return
    assert events[-1].metadata['ok'] is False
    state = hw.WorkspaceState.load(backend.session_id)
    assert state.pending_sync['phase'] == 'report'
    if receipt == 'lost':
        # Once the outcome is saved, report recovery no longer needs archive bytes.
        state.path().with_suffix('.sync.tar').unlink()
    head = _git(repo, 'rev-parse', 'HEAD')
    # Simulate a reconstructed backend and recover without a provider turn.
    recovered = hub.HubBackend(backend.model, str(repo), bridge=backend._bridge)
    await recovered._sync_back(ssh, state, repo, tmp_path)
    assert _git(repo, 'rev-parse', 'HEAD') == head
    assert len(parent.receipts) == 1
    assert not hw.WorkspaceState.load(state.ws_id).pending_sync
    if receipt == 'lost':
        assert parent.calls[0][1] == parent.calls[1][1]


@pytest.mark.asyncio
async def test_remote_ack_failure_keeps_report_until_recovery(repo, tmp_path, monkeypatch):
    backend, ssh, mc, parent = worker(repo, tmp_path, monkeypatch)
    real = ssh.delete_files
    ssh.delete_files = AsyncMock(side_effect=hw.HubWorkspaceError('synthetic ack unavailable'))
    events = await _turn(backend, 'go')
    assert events[-1].metadata['ok'] is False
    assert parent.calls == []
    state = hw.WorkspaceState.load(backend.session_id)
    assert state.pending_sync['entries']
    ssh.delete_files = real
    await backend._sync_back(ssh, state, repo, tmp_path)
    assert len(parent.receipts) == 1


@pytest.mark.asyncio
async def test_recovery_after_import_and_after_commit_does_not_lose_results(repo, tmp_path, monkeypatch):
    backend, ssh, mc, parent = worker(repo, tmp_path, monkeypatch)
    real_record = backend._record_sync
    def crash_after_import(*args):
        raise OSError('synthetic broker crash after file replacement')
    backend._record_sync = crash_after_import
    events = await _turn(backend, 'go')
    assert events[-1].metadata['ok'] is False and not parent.calls
    state = hw.WorkspaceState.load(backend.session_id)
    assert state.pending_sync['phase'] == 'import'
    assert 'return a + b' in (repo / 'calc.py').read_text()
    backend._record_sync = real_record
    real_commit = hw.commit_sync
    # Raise a non-cancellation BaseException without involving the event loop's
    # special KeyboardInterrupt handling.
    class Crash(BaseException):
        pass
    def crash(*args):
        real_commit(*args)
        raise Crash()
    monkeypatch.setattr(hw, 'commit_sync', crash)
    with pytest.raises(Crash):
        await backend._sync_back(ssh, state, repo, tmp_path)
    head = _git(repo, 'rev-parse', 'HEAD')
    state = hw.WorkspaceState.load(state.ws_id)
    monkeypatch.setattr(hw, 'commit_sync', real_commit)
    await backend._sync_back(ssh, state, repo, tmp_path)
    assert _git(repo, 'rev-parse', 'HEAD') == head
    assert len(parent.receipts) == 1
    assert 'return a + b' in parent.calls[0][3]


@pytest.mark.asyncio
async def test_cancellation_drains_commit_and_reports_interrupted(repo, tmp_path, monkeypatch):
    backend, ssh, mc, parent = worker(repo, tmp_path, monkeypatch)
    entered, release = threading.Event(), threading.Event()
    real = hw.commit_sync
    def blocked(*args):
        entered.set()
        assert release.wait(5), 'test commit latch timed out'
        return real(*args)
    monkeypatch.setattr(hw, 'commit_sync', blocked)
    task = asyncio.create_task(_turn(backend, 'go'))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        task.cancel()
        await asyncio.sleep(0)  # yield once; no timer/poll loop
        task.cancel()  # a second Stop must not cancel the shielded commit task
        await asyncio.sleep(0)
        assert not task.done()
        assert not parent.calls
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(parent.receipts) == 1
    assert 'status=failed/interrupted' in parent.calls[0][1]['message']
    assert 'return a + b' in parent.calls[0][3]


@pytest.mark.asyncio
async def test_invalid_entry_cannot_trap_recovery_or_hide_valid_report(repo, tmp_path, monkeypatch):
    backend, ssh, mc, parent = worker(repo, tmp_path, monkeypatch, [
        {'tool': 'update_progress', 'args': {'percent': 'invalid'}},
        {'tool': 'send_message', 'args': {'message': 'DONE'}},
    ])
    events = await _turn(backend, 'go')
    assert events[-1].metadata['ok']
    assert len(parent.receipts) == 1
    assert '1 dropped' in events[-2].content
    assert not backend._state.pending_sync


def test_legacy_state_and_untrusted_delivery_id(repo):
    state = hw.WorkspaceState(hw.WorkspaceState.new_id(), str(repo), 'synthetic')
    state.save()
    payload = json.loads(state.path().read_text())
    payload.pop('pending_sync')
    state.path().write_text(json.dumps(payload))
    assert hw.WorkspaceState.load(state.ws_id).pending_sync == {}
    entries, _ = ob.parse_outbox(json.dumps({'tool': 'send_message', '_delivery_id': 'attacker',
                                           'args': {'message': 'DONE', 'delivery_id': 'attacker'}}).encode())
    assert '_delivery_id' not in entries[0]
    request = ob._request_for('send_message', entries[0]['args'], ob.Identity('s', 'w', '', parent_name='p'))
    assert request[2]['delivery_id'] != 'attacker'


@pytest.mark.asyncio
@pytest.mark.parametrize('explicit', [True, False])
@pytest.mark.parametrize('failed', [True, False])
async def test_session_reports_final_sync_once_without_ack_loop(
    repo, tmp_path, monkeypatch, world, explicit, failed,
):
    from unittest.mock import Mock
    from app.events import MessageProvenance
    from tests.test_turn_signals import _session, _settle

    entries = ([{'tool': 'send_message', 'args': {'message': 'DONE'}}] if explicit else
               [{'tool': 'update_progress', 'args': {'percent': 100}}])
    backend, ssh, mc, parent = worker(repo, tmp_path, monkeypatch, entries)
    session = _session(world)
    session.backend_type = 'hub'
    session._submit_db_write = Mock()
    session._spawn_bg = lambda coroutine: coroutine.close()
    session._turns.schedule_context_compaction = Mock()

    async def api(who, method, path, body):
        if path.endswith('/send'):
            await world['manager'].send(world['parent_id'], body['message'], provenance=MessageProvenance(
                'agent', (who.name,), subtype='direct_message', ref=body['delivery_id']))
        return {'ok': True, 'delivery_state': 'QUEUED'}
    monkeypatch.setattr(ob, 'local_api_call', api)
    backend._bridge = session._hub_bridge()
    if failed:
        def fail(*args):
            raise hw.HubWorkspaceError('synthetic commit failure')
        monkeypatch.setattr(hw, 'commit_sync', fail)
    events = await _turn(backend, 'go')
    assert events[-1].metadata['ok'] is (not failed)
    for event in events:
        session._handle_event(event)
    await _settle(session)
    session._turns.fire_auto_report()
    await _settle(session)
    assert len(world['manager'].sent) == 1
    _, message, provenance = world['manager'].sent[0]
    assert ('NOT COMMITTED' if failed else 'local HEAD') in message
    assert provenance.subtype == ('direct_message' if explicit else 'auto_report')
    assert session._did_report is explicit


@pytest.mark.asyncio
@pytest.mark.parametrize('stage', ['download', 'import'])
async def test_sync_failure_retains_explicit_report_for_retry(repo, tmp_path, monkeypatch, stage):
    backend, ssh, mc, parent = worker(repo, tmp_path, monkeypatch)
    if stage == 'download':
        real = ssh.get
        ssh.get = AsyncMock(side_effect=hw.HubWorkspaceError('synthetic download failure'))
    else:
        real = hw.apply_changes
        def fail(*args, **kwargs):
            raise OSError('synthetic import failure')
        monkeypatch.setattr(hw, 'apply_changes', fail)
    events = await _turn(backend, 'go')
    assert events[-1].metadata['ok'] is False
    assert parent.calls == []
    state = hw.WorkspaceState.load(backend.session_id)
    assert (Path(state.remote_dir) / ob.OUTBOX_NAME).exists()
    if stage == 'download':
        ssh.get = real
    else:
        monkeypatch.setattr(hw, 'apply_changes', real)
    await backend._sync_back(ssh, state, repo, tmp_path)
    assert len(parent.receipts) == 1
    assert 'local HEAD' in parent.calls[0][1]['message']


@pytest.mark.asyncio
@pytest.mark.parametrize('status', ['failed', 'cancelled', 'interrupted', 'rolled_back'])
async def test_failed_provider_never_reports_success_after_good_import(repo, tmp_path, monkeypatch, status):
    backend, ssh, mc, parent = worker(repo, tmp_path, monkeypatch)
    real = mc.tool_call
    async def call(name, args):
        if name == 't3_thread_wait':
            return {'status': status, 'timedOut': False}
        return await real(name, args)
    mc.tool_call = call
    events = await _turn(backend, 'go')
    assert events[-1].metadata['ok'] is False
    assert parent.calls[0][1]['message'].startswith('[hub result] status=failed/interrupted;')
    assert 'return a + b' in parent.calls[0][3]


@pytest.mark.asyncio
async def test_pending_ack_blocks_next_upload_and_provider_run(repo, tmp_path, monkeypatch):
    backend, ssh, mc, parent = worker(repo, tmp_path, monkeypatch)
    ssh.delete_files = AsyncMock(side_effect=hw.HubWorkspaceError('synthetic ack unavailable'))
    await _turn(backend, 'go')
    before = len(mc.calls)
    ssh.put = AsyncMock(side_effect=AssertionError('upload before recovery'))
    events = await _turn(backend, 'follow-up')
    assert events[-1].metadata['ok'] is False
    assert len(mc.calls) == before
    assert parent.calls == []
    assert hw.WorkspaceState.load(backend.session_id).pending_sync['entries']


@pytest.mark.asyncio
async def test_recovery_refuses_to_commit_intervening_local_edit(repo, tmp_path, monkeypatch):
    backend, ssh, mc, parent = worker(repo, tmp_path, monkeypatch)
    real_commit = hw.commit_sync
    class Crash(BaseException):
        pass
    def crash(*args):
        raise Crash()
    monkeypatch.setattr(hw, 'commit_sync', crash)
    with pytest.raises(Crash):
        await _turn(backend, 'go')
    state = hw.WorkspaceState.load(backend.session_id)
    (repo / 'calc.py').write_text('subsequent local edit\n')
    monkeypatch.setattr(hw, 'commit_sync', real_commit)
    await backend._sync_back(ssh, state, repo, tmp_path)
    assert 'subsequent local edit' not in _git(repo, 'show', 'HEAD:calc.py')
    assert (repo / 'calc.py').read_text() == 'subsequent local edit\n'
    assert parent.calls[0][1]['message'].startswith('[hub result] status=partial/failed;')
    assert 'imported path changed before commit' in parent.calls[0][1]['message']


@pytest.mark.asyncio
async def test_recovered_old_report_does_not_suppress_new_turn_auto_report(
    repo, tmp_path, monkeypatch, world,
):
    from unittest.mock import Mock
    from tests.test_turn_signals import _session, _settle

    backend, ssh, mc, parent = worker(repo, tmp_path, monkeypatch)
    session = _session(world)
    session.backend_type = 'hub'
    session._submit_db_write = Mock()
    session._spawn_bg = lambda coroutine: coroutine.close()
    session._turns.schedule_context_compaction = Mock()
    backend._bridge = session._hub_bridge()
    backend._bridge._call = parent
    parent.lose_response = True
    first = await _turn(backend, 'go')
    assert first[-1].metadata['ok'] is False
    assert session._did_report is False
    session._turns.bump_turn_gen()
    events = await _turn(backend, 'new task')
    assert events[-1].metadata['ok'] is True
    assert session._did_report is False, 'previous report must not mark the new provider turn reported'
    for event in events:
        session._handle_event(event)
    await _settle(session)
    assert len(parent.receipts) == 1
    assert len(world['manager'].sent) == 1
    assert world['manager'].sent[0][2].subtype == 'auto_report'


@pytest.mark.asyncio
async def test_deleted_output_is_committed_when_import_replays_after_crash(repo, tmp_path, monkeypatch):
    backend, ssh, mc, parent = worker(repo, tmp_path, monkeypatch)
    real_edit = mc.hub_edit
    def edit(root):
        real_edit(root)
        (root / 'src/keep.txt').unlink()
    mc.hub_edit = edit
    real_record = backend._record_sync
    def crash(*args):
        raise OSError('synthetic crash after unlink')
    backend._record_sync = crash
    events = await _turn(backend, 'go')
    assert events[-1].metadata['ok'] is False and not parent.calls
    state = hw.WorkspaceState.load(backend.session_id)
    assert not (repo / 'src/keep.txt').exists()
    backend._record_sync = real_record
    await backend._sync_back(ssh, state, repo, tmp_path)
    assert 'src/keep.txt' not in _git(repo, 'ls-tree', '-r', '--name-only', 'HEAD').splitlines()
    assert 'deleted 1' in parent.calls[0][1]['message']
    assert parent.calls[0][1]['message'].startswith('[hub result] status=ok;')
