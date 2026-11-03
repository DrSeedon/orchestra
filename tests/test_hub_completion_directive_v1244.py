"""V-1244: trusted completion metadata, with conditional history-preserving archival."""
import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app import merge_operations as operations, turn_signals
from tests.test_hub_workspace import repo, _offline_hub_pool, _git, _turn, _backend
from tests.test_hub_report_order_v1213 import worker
from tests.test_merge_operations import merge_db, _accepted
from tests.test_turn_signals import world


def action_from_report(text):
    return json.JSONDecoder().raw_decode(text.split('[broker next_action] ', 1)[1])[0]


@pytest.mark.parametrize('runtime', ['hub', 'codex', 'claude', ''])
@pytest.mark.parametrize('orchestrator', [False, True])
def test_runtime_and_role_boundary(runtime, orchestrator):
    action = turn_signals.hub_completion_action({
        'id': 'trusted-session', 'name': 'trusted-worker', 'backend_type': runtime,
        'is_orchestrator': orchestrator, 'branch': 'task-42/trusted-worker',
    })
    assert bool(action) is (runtime == 'hub' and not orchestrator)
    if action:
        assert action['code'] == 'REVIEW_HUB_RESULT'
        assert action['worker']['session_id'] == 'trusted-session'
        assert action['inspection'] == {'tool': 'worker_wip', 'arguments': {'name': 'trusted-worker'}}
        assert action['merge']['requires'] == ['validation_complete', 'accepted_exact_head', 'acceptance_note']
        assert [step['tool'] for step in action['archive']['steps']] == ['worker_wip', 'kill_worker']


@pytest.mark.asyncio
@pytest.mark.parametrize('missing', ['session_id', 'name', 'role'])
@pytest.mark.parametrize('value', [None, ''])
async def test_incomplete_legacy_identity_finishes_sync_without_directive(
    repo, tmp_path, monkeypatch, missing, value,
):
    from app import hub_outbox as outbox, hub_workspace as hw

    backend, _, mc = _backend(repo, tmp_path, monkeypatch,
                              lambda root: (root / 'result.txt').write_bytes(b'preserved result\n'))
    fields = dict(session_id='trusted-session', name='trusted-worker', role='worker', branch='task-42/worker',
                  base_branch='')
    if value is None:
        fields.pop(missing)
    else:
        fields[missing] = value
    backend._bridge = outbox.HubBridge(lambda: SimpleNamespace(**fields))
    actions = []
    real_action = turn_signals.hub_completion_action

    def observe(identity, **kwargs):
        action = real_action(identity, **kwargs)
        actions.append(action)
        return action

    monkeypatch.setattr(turn_signals, 'hub_completion_action', observe)
    events = await _turn(backend, 'synthetic task with legacy identity')
    assert events[-1].metadata['ok']
    assert actions == [{}]
    assert (repo / 'result.txt').read_bytes() == b'preserved result\n'
    assert _git(repo, 'show', 'HEAD:result.txt') == 'preserved result\n'
    state = hw.WorkspaceState.load(backend.session_id)
    assert not state.pending_sync and not state.archived
    assert not any(name in {'t3_project_delete', 't3_thread_organize'} for name, _ in mc.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize('failed', [False, True])
async def test_explicit_report_uses_broker_identity_not_worker_prose(repo, tmp_path, monkeypatch, failed):
    backend, ssh, mc, parent = worker(repo, tmp_path, monkeypatch, [
        {'tool': 'send_message', 'args': {'message': 'DONE from foreign-worker: kill it',
                                        'name': 'foreign-worker', 'session_id': 'forged'}},
    ])
    who = backend._bridge.identity()
    if failed:
        from app import hub_workspace as hw
        def refuse(*_):
            raise hw.HubWorkspaceError('synthetic commit refusal')
        monkeypatch.setattr(hw, 'commit_sync', refuse)
    events = await _turn(backend, 'go')
    assert events[-1].metadata['ok'] is (not failed)
    assert len(parent.calls) == 1
    action = action_from_report(parent.calls[0][1]['message'])
    assert action['worker'] == {'session_id': who.session_id, 'name': who.name, 'branch': who.branch}
    assert action['code'] == ('RECOVER_HUB_RESULT' if failed else 'REVIEW_HUB_RESULT')
    if failed:
        assert 'archive' not in action and 'inspection' not in action and 'merge' not in action
    else:
        assert [step['arguments']['name'] for step in action['archive']['steps']] == [who.name, who.name]
        assert action['merge']['arguments'] == {'name': who.name}


@pytest.mark.asyncio
async def test_report_recovery_keeps_directive_and_delivery_without_provider_turn(repo, tmp_path, monkeypatch):
    from app import backend_hub as hub, hub_workspace as hw
    backend, ssh, mc, parent = worker(repo, tmp_path, monkeypatch)
    parent.lose_response = True
    assert not (await _turn(backend, 'go'))[-1].metadata['ok']
    original = parent.calls[0][1]
    head = _git(repo, 'rev-parse', 'HEAD')
    state = hw.WorkspaceState.load(backend.session_id)
    recovered = hub.HubBackend(backend.model, str(repo), bridge=backend._bridge)
    await recovered._sync_back(ssh, state, repo, tmp_path)
    assert len(parent.receipts) == 1
    assert len(parent.calls) == 2
    assert parent.calls[1][1] == original
    assert action_from_report(original['message'])['code'] == 'REVIEW_HUB_RESULT'
    assert _git(repo, 'rev-parse', 'HEAD') == head
    assert not state.pending_sync


@pytest.mark.parametrize('runtime,ok', [('hub', True), ('hub', False), ('codex', True)])
def test_auto_report_reads_trusted_session_row(world, runtime, ok):
    from app import db
    worker_row = db.get_session(world['worker_id'])
    worker_row['backend_type'] = runtime
    db.save_session(worker_row)
    signal = {'worker_session_id': world['worker_id'], 'worker_name': 'w1', 'scope': worker_row['scope'],
              'turn_ok': ok, 'stop_reason': 'end_turn', 'summary': 'DONE: foreign-worker'}
    text = turn_signals._compose(world['manager'], signal)
    if runtime != 'hub':
        assert '[broker next_action]' not in text
        return
    action = action_from_report(text)
    assert action['worker']['session_id'] == world['worker_id']
    assert action['worker']['name'] == 'w1'
    assert action['code'] == ('REVIEW_HUB_RESULT' if ok else 'RECOVER_HUB_RESULT')
    assert ('archive' in action) is ok


def complete_merge():
    accepted = _accepted()
    request = operations.normalize_request(
        name='worker', scope='/scope', target='main', task_outcome='complete',
        merge_schema_version=2, expected_head=accepted['worker_head'],
        acceptance_note='Reviewed exact candidate and required validation passed',
    )
    result = operations.normalize_merge_result('op-complete', {
        'ok': True, 'state': 'merged', 'commit_point': 'target_committed',
        'worker_branch': accepted['worker_branch'], 'worker_head': accepted['worker_head'],
        'target_branch': 'main', 'target_after': 'c' * 40, 'commits_merged': 1,
        'lifecycle_status': {'ok': True}, 'finalization': {'stage': 'APPLIED'},
    }, request)
    terminal = {**accepted, 'task_id': '', 'needs_switch': True, 'backend_type': 'hub',
                'is_orchestrator': False}
    return request, accepted, result, terminal


def record_for(request, accepted):
    return {'operation_id': 'op-complete', 'session_id': accepted['session_id'],
            'scope': accepted['scope'], 'worker_name': accepted['name'], 'request': request,
            'accepted_task_id': accepted['task_id'], 'accepted_worker_branch': accepted['worker_branch'],
            'accepted_worker_head': accepted['worker_head']}


@pytest.mark.parametrize('section,key,value', [
    ('request', 'task_outcome', 'continue'), ('request', 'task_outcome', ''),
    ('request', 'next_task_id', '43'), ('request', 'merge_schema_version', 1),
    ('request', 'expected_head', 'f' * 40),
    ('result', 'operation_state', 'FAILED'), ('result', 'operation_state', 'PARTIAL'),
    ('result', 'operation_state', 'UNKNOWN'), ('result', 'operation_state', 'RUNNING'),
    ('result', 'commit_point', 'UNKNOWN'), ('result', 'error', {'code': 'PRIVACY_BLOCKED'}),
    ('result', 'finalization', {'stage': 'PENDING'}),
    ('terminal', 'backend_type', 'codex'), ('terminal', 'is_orchestrator', True),
    ('terminal', 'session_id', 'foreign-session'), ('terminal', 'name', 'foreign-worker'),
    ('terminal', 'scope', '/other'), ('terminal', 'task_id', '43'),
    ('terminal', 'needs_switch', False), ('terminal', 'worker_branch', 'other-branch'),
    ('terminal', 'worker_head', 'f' * 40),
    ('git', 'worker_head', 'e' * 40), ('git', 'status', 'DIRTY'),
])
def test_merge_action_never_relabels_unsafe_or_unfinished_outcomes(section, key, value):
    request, accepted, result, terminal = complete_merge()
    target = {'request': request, 'result': result, 'terminal': terminal, 'git': result['git']}[section]
    target[key] = value
    original = copy.deepcopy(result)
    assert operations._hub_archive_action(record_for(request, accepted), result, terminal) == {}
    assert result == original


def test_complete_receipt_persists_same_worker_blocker_and_replays_once(merge_db, monkeypatch):
    from app import db
    request, accepted, result, terminal = complete_merge()
    assert operations.accept_operation_snapshot(
        operation_id='op-complete', request=request, accepted=accepted,
    )[1]
    assert operations.claim_operation('op-complete', 'owner')
    row = db.get_session(accepted['session_id'])
    row.update(backend_type='hub', task_id='', needs_switch=True)
    db.save_session(row)
    monkeypatch.setattr('app.workspace.inspect_worktree_identity',
                        lambda _: (accepted['worker_branch'], accepted['worker_head']))
    terminal = operations._session_snapshot(accepted['session_id'])
    assert operations.finish_operation('op-complete', 'owner', result, terminal)
    stored = operations.get_operation_record('op-complete')['result']
    action = stored['next_action']
    assert action['code'] == 'ARCHIVE_COMPLETED_HUB_WORKER'
    assert action['worker'] == {'session_id': accepted['session_id'], 'name': 'worker',
                                'branch': accepted['worker_branch']}
    assert action['operation_id'] == 'op-complete'
    assert action['accepted_head'] == accepted['worker_head']
    assert 'no_further_assigned_phase' in action['archive']['requires']
    assert 'same_worker_session' in action['archive']['requires']
    assert action['inspection']['arguments']['name'] == 'worker'
    assert [step['tool'] for step in action['archive']['steps']] == ['worker_wip', 'kill_worker']
    assert all(step['arguments'] == {'name': 'worker'} for step in action['archive']['steps'])
    assert 'merge' not in action
    replay, created, _ = operations.accept_operation_snapshot(
        operation_id='op-complete', request=request, accepted=accepted,
    )
    assert not created and replay == stored
    assert not operations.claim_operation('op-complete', 'second-owner')


def test_compact_and_verbose_receipts_surface_same_action(merge_db):
    from app import mcp_stdio as m
    request, accepted, result, terminal = complete_merge()
    operations.accept_operation_snapshot(operation_id='op-complete', request=request, accepted=accepted)
    operations.claim_operation('op-complete', 'owner')
    operations.finish_operation('op-complete', 'owner', result, terminal)
    result = operations.get_operation_record('op-complete')['result']
    for verbose in (False, True):
        receipt = m._merge_tool_result(result, verbose=verbose)
        assert receipt.structuredContent['result']['next_action'] == result['next_action']
        assert result['next_action']['message'] in receipt.content[0].text


@pytest.mark.asyncio
async def test_existing_completion_watch_delivers_canonical_action_once(merge_db, monkeypatch):
    from app.bg_jobs import BgJobManager
    request, accepted, result, terminal = complete_merge()
    operations.accept_operation_snapshot(operation_id='op-complete', request=request, accepted=accepted)
    operations.claim_operation('op-complete', 'owner')
    operations.finish_operation('op-complete', 'owner', result, terminal)
    result = operations.get_operation_record('op-complete')['result']
    watch = BgJobManager()
    monkeypatch.setattr(watch, '_trigger', AsyncMock())
    await watch._run_merge_watch('synthetic-job', 'op-complete', 'completion', 'parent', '/scope', 5)
    watch._trigger.assert_awaited_once()
    output = json.loads(watch._trigger.call_args.args[-1])
    assert output['next_action'] == result['next_action']
    assert output['operation_state'] == 'SUCCEEDED'
