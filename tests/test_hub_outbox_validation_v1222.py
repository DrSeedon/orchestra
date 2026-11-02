"""V-1222: rejected bookkeeping cannot poison the durable report/recovery FIFO."""
import copy
import json
from unittest.mock import AsyncMock

import httpx
import pytest

from app import backend_hub as hub, checklists, hub_outbox as ob, hub_workspace as hw
from tests.test_hub_workspace import repo, _offline_hub_pool, _outbox_backend, _turn


INVALID = {'tool': 'update_checklist', 'args': {
    'items': ['Inspect', 'Verify'], 'completed': [0], 'current': 0,
    'estimates_minutes': [2, 3],
}}
VALID = {'tool': 'update_checklist', 'args': {**INVALID['args'], 'current': 1}}
REPORT = {'tool': 'send_message', 'args': {'message': 'DONE: synthetic result'}}
ERROR = 'current step cannot also be completed'


class LocalApi:
    """Real local HTTP adapter with an offline transport and canonical validator."""
    def __init__(self, monkeypatch):
        self.calls = []
        self.receipts = {}
        self.previous = None
        self.failure = None
        self.lose_ack = False
        self.reported = []
        client = httpx.AsyncClient
        transport = httpx.MockTransport(self.handle)
        monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: client(transport=transport, **kw))
        monkeypatch.setenv('ORCHESTRA_URL', 'http://synthetic.invalid')

    async def handle(self, request):
        body = json.loads(request.content)
        self.calls.append((request.url.path, copy.deepcopy(body)))
        if self.failure is not None:
            if isinstance(self.failure, Exception):
                raise self.failure
            status, payload = self.failure
            return httpx.Response(status, json=payload)
        if request.url.path.endswith('/checklist'):
            try:
                steps = checklists.validate_items(**body, previous_items=self.previous)
            except ValueError as exc:
                return httpx.Response(422, json={'error': str(exc)})
            self.previous = steps
        elif request.url.path.endswith('/send'):
            key = body['delivery_id']
            if key in self.receipts:
                assert self.receipts[key] == body, 'replay changed delivery body'
            self.receipts[key] = body
            if self.lose_ack:
                self.lose_ack = False
                raise httpx.ReadError('synthetic lost ack after acceptance')
            return httpx.Response(200, json={'ok': True, 'delivery_state': 'QUEUED'})
        return httpx.Response(200, json={'ok': True})

    def bridge(self, identity):
        return ob.HubBridge(identity, on_parent_report=self.reported.append)


@pytest.mark.asyncio
async def test_saved_invalid_checklist_recovers_then_allows_valid_action_and_resume(
    repo, tmp_path, monkeypatch, caplog,
):
    api = LocalApi(monkeypatch)
    backend, ssh, mc = _outbox_backend(repo, tmp_path, monkeypatch, [INVALID, VALID, REPORT], None)
    backend._bridge = api.bridge(backend._bridge.identity)
    # Save precisely the old pending journal shape, before any local API attempt.
    delete = ssh.delete_files
    ssh.delete_files = AsyncMock(side_effect=hw.HubWorkspaceError('synthetic ack outage'))
    events = await _turn(backend, 'first')
    assert events[-1].metadata['ok'] is False
    saved = hw.WorkspaceState.load(backend.session_id)
    original = copy.deepcopy(saved.pending_sync['entries'])
    assert [e['tool'] for e in original] == ['update_checklist', 'update_checklist', 'send_message']
    ssh.delete_files = delete
    # Reconstruct the broker: automatic pre-generation recovery, no journal edits.
    recovered = hub.HubBackend(backend.model, str(repo), bridge=backend._bridge, paths=backend._paths)
    recovered._state = saved
    recovered._client = backend._client
    recovered._ssh = ssh
    events = await _turn(recovered, 'resume')
    text = '\n'.join(e.content for e in events)
    assert events[-1].metadata['ok'], text
    assert ERROR in text and 'terminal validation rejection' in text
    assert '"current": 0' in text and '"completed": [0]' in text
    assert original[0]['_delivery_id'] in text
    assert ERROR in caplog.text and '"current": 0' in caplog.text
    assert not hw.WorkspaceState.load(saved.ws_id).pending_sync
    assert api.calls[0][1] == INVALID['args'], 'never silently repair model arguments'
    assert api.calls[1][1] == VALID['args']
    assert len(api.receipts) == 1
    # Recovery delivers the old turn's report without marking the new turn
    # reported; its own eventual auto-report must still be possible.
    assert not api.reported
    assert 'DONE: synthetic result' in next(iter(api.receipts.values()))['message']
    assert any(name == 't3_thread_send' for name, _ in mc.calls), 'resume never reached generation'
    calls = len(api.calls)
    await _turn(recovered, 'another follow-up')
    assert len(api.calls) == calls, 'terminal rejection retried on later follow-up'


@pytest.mark.asyncio
async def test_terminal_diagnostic_is_saved_before_lost_parent_ack_and_replayed_once(
    repo, tmp_path, monkeypatch,
):
    api = LocalApi(monkeypatch)
    backend, ssh, mc = _outbox_backend(repo, tmp_path, monkeypatch, [INVALID, REPORT], None)
    backend._bridge = api.bridge(backend._bridge.identity)
    api.lose_ack = True
    events = await _turn(backend, 'go')
    assert events[-1].metadata['ok'] is False
    saved = hw.WorkspaceState.load(backend.session_id)
    assert [e['tool'] for e in saved.pending_sync['entries']] == ['send_message']
    diagnostic, = saved.pending_sync['dropped']
    assert ERROR in diagnostic and '"current": 0' in diagnostic
    send = copy.deepcopy(saved.pending_sync['entries'][0])
    assert not api.reported
    recovered = hub.HubBackend(backend.model, str(repo), bridge=backend._bridge)
    summary = await recovered._sync_back(ssh, saved, repo, tmp_path)
    assert diagnostic in summary
    assert len(api.receipts) == len(api.reported) == 1
    assert [body for path, body in api.calls if path.endswith('/send')][0] == api.calls[-1][1]
    assert api.calls[-1][1]['delivery_id'] == send['_delivery_id']
    assert len([path for path, _ in api.calls if path.endswith('/checklist')]) == 1
    assert not hw.WorkspaceState.load(saved.ws_id).pending_sync


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', [
    httpx.ReadTimeout('synthetic temporary outage'),
    (503, {'error': ERROR}), (401, {'error': ERROR}), (403, {'error': ERROR}),
    (409, {'error': ERROR}), (422, {'detail': 'unknown outcome'}),
    (422, {'error': {'code': 'UNKNOWN'}}), (200, {'error': ERROR}),
    (200, {}), (200, {'ok': False}), (200, None),
])
async def test_uncertain_or_authority_failure_retains_pending_and_stable_ids(
    repo, tmp_path, monkeypatch, failure,
):
    api = LocalApi(monkeypatch)
    backend, ssh, mc = _outbox_backend(repo, tmp_path, monkeypatch, [VALID, REPORT], None)
    backend._bridge = api.bridge(backend._bridge.identity)
    api.failure = failure
    events = await _turn(backend, 'go')
    assert events[-1].metadata['ok'] is False
    saved = hw.WorkspaceState.load(backend.session_id)
    entries = copy.deepcopy(saved.pending_sync['entries'])
    assert [e['tool'] for e in entries] == ['update_checklist', 'send_message']
    events = await _turn(backend, 'retry once')
    assert events[-1].metadata['ok'] is False
    assert hw.WorkspaceState.load(saved.ws_id).pending_sync['entries'] == entries
    assert not api.receipts and not api.reported
    api.failure = None
    await backend._sync_back(ssh, saved, repo, tmp_path)
    assert not hw.WorkspaceState.load(saved.ws_id).pending_sync
    assert api.calls[-1][1]['delivery_id'] == entries[-1]['_delivery_id']
    assert len(api.receipts) == len(api.reported) == 1


@pytest.mark.asyncio
async def test_valid_checklist_can_reuse_previous_estimates(monkeypatch):
    api = LocalApi(monkeypatch)
    who = ob.Identity('s', 'worker', '/synthetic', parent_name='boss')
    bridge = api.bridge(lambda: who)
    first = await bridge.run([VALID])
    reuse = {**VALID, 'args': {k: v for k, v in VALID['args'].items() if k != 'estimates_minutes'}}
    second = await bridge.run([reuse])
    assert first.done == second.done == ['update_checklist']
    assert not first.dropped and not second.dropped
    assert [step['estimate_minutes'] for step in api.previous] == [2, 3]


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', [
    (422, {'error': ERROR}), (403, {'error': 'ownership denied'}),
    (200, {'ok': True, 'delivery_state': 'DELIVERY_UNKNOWN'}),
])
async def test_send_message_rejection_is_never_terminal_bookkeeping(
    repo, tmp_path, monkeypatch, failure,
):
    api = LocalApi(monkeypatch)
    backend, ssh, mc = _outbox_backend(repo, tmp_path, monkeypatch, [REPORT], None)
    backend._bridge = api.bridge(backend._bridge.identity)
    api.failure = failure
    events = await _turn(backend, 'go')
    assert events[-1].metadata['ok'] is False
    saved = hw.WorkspaceState.load(backend.session_id)
    entry, = copy.deepcopy(saved.pending_sync['entries'])
    assert entry['tool'] == 'send_message' and entry['_delivery_id']
    assert not saved.pending_sync['dropped']
    api.failure = None
    await backend._sync_back(ssh, saved, repo, tmp_path)
    assert api.calls[0][1] == api.calls[-1][1]
    assert len(api.receipts) == len(api.reported) == 1


@pytest.mark.asyncio
async def test_invalid_send_message_stays_pending_instead_of_being_discarded(repo, tmp_path, monkeypatch):
    api = LocalApi(monkeypatch)
    invalid = {'tool': 'send_message', 'args': {'message': ''}}
    backend, ssh, mc = _outbox_backend(repo, tmp_path, monkeypatch, [invalid, REPORT], None)
    backend._bridge = api.bridge(backend._bridge.identity)
    events = await _turn(backend, 'go')
    assert events[-1].metadata['ok'] is False
    saved = hw.WorkspaceState.load(backend.session_id)
    assert [e['args'] for e in saved.pending_sync['entries']] == [invalid['args'], REPORT['args']]
    assert not api.calls


@pytest.mark.asyncio
async def test_real_checklist_route_keeps_validation_strict_and_preserves_previous_state(
    tmp_path, monkeypatch,
):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import Mock
    from fastapi import FastAPI
    from app import db
    from app.routes import sessions as routes
    from app.session import AgentStatus
    from tests.test_checklists_v858 import _insert_session

    db.init_db()
    checklists.ensure_schema()
    _insert_session(db, 'worker', 'task-1')
    session = SimpleNamespace(
        id='worker', name='worker', scope='/v858', loaded=True,
        status=AgentStatus.RUNNING, task_id='task-1', _turn_gen=1,
        _checklist_turn_key='synthetic-turn', _checklist_activity_event=asyncio.Event(), _log=Mock(),
    )
    monkeypatch.setattr(routes.manager, 'sessions', {'worker': session})
    application = FastAPI()
    application.include_router(routes.router)
    client = httpx.AsyncClient
    transport = httpx.ASGITransport(app=application)
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: client(transport=transport, **kw))
    monkeypatch.setenv('ORCHESTRA_URL', 'http://synthetic.invalid')
    bridge = ob.HubBridge(lambda: ob.Identity('worker', 'worker', '/v858', parent_name='boss'))
    first = await bridge.run([VALID])
    assert first.done == ['update_checklist']
    previous = checklists.get_checklist('worker', 'task-1')
    rejected = await bridge.run([INVALID])
    assert not rejected.done and rejected.rejected == rejected.dropped
    assert ERROR in rejected.dropped[0] and '"current": 0' in rejected.dropped[0]
    assert checklists.get_checklist('worker', 'task-1') == previous
    malformed = {'tool': 'update_checklist', 'args': {**VALID['args'], 'current': 'invalid-index'}}
    rejected = await bridge.run([malformed])
    assert rejected.rejected == rejected.dropped and rejected.rejected
    assert checklists.get_checklist('worker', 'task-1') == previous
    session.status = AgentStatus.IDLE  # lifecycle/ownership refusal stays pending
    denied = await bridge.run([VALID])
    assert denied.dropped and not denied.rejected
    session.status = AgentStatus.RUNNING
    reuse = {'tool': 'update_checklist', 'args': {**VALID['args'], 'estimates_minutes': [None, None]}}
    accepted = await bridge.run([reuse])
    assert accepted.done == ['update_checklist'] and not accepted.dropped


@pytest.mark.asyncio
@pytest.mark.parametrize('args', [
    {**VALID['args'], 'items': []},
    {**VALID['args'], 'completed': [0, 0]},
    {**VALID['args'], 'current': 2},
    {**VALID['args'], 'estimates_minutes': [None, None]},
    {**VALID['args'], 'estimates_minutes': [-1, 3]},
    {**VALID['args'], 'completed': 'invalid'},
    {**VALID['args'], 'items': 'invalid'},
])
async def test_optional_validation_rejection_is_terminal_and_keeps_original_action(monkeypatch, args):
    api = LocalApi(monkeypatch)
    entry = {'tool': 'update_checklist', 'args': args, '_delivery_id': 'broker-owned-id'}
    report = await api.bridge(lambda: ob.Identity('s', 'worker', '/synthetic')).run([entry])
    assert not report.done
    assert report.rejected == report.dropped and len(report.rejected) == 1
    reason, serialized = report.rejected[0].split('; action=', 1)
    assert 'terminal validation rejection' in reason
    assert json.loads(serialized) == entry
    assert api.previous is None, 'rejected request changed checklist state'
