"""Writer contention must never accept another silent delivery or steal a live lock."""
import asyncio
import fcntl
import json
import subprocess
import sys
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app import backend_codex, message_deliveries
from app.backend_codex import CodexProtocolError, CodexWriterConflictError
from app.events import MessageProvenance
from app.session import AgentStatus
from tests.test_session import mock_db, session
from tests.test_message_delivery_receipts_380 import (
    message_db, _accept, _delivery_row, _request_with_proof,
    SOURCE_ID, SOURCE_NAME, TARGET_ID, TARGET_NAME, SCOPE,
)

THREAD_ID = '01a0776b-d1b7-7b83-b4e9-e236d37340eb'


@pytest.fixture
def writer_path(tmp_path, monkeypatch):
    monkeypatch.setattr(backend_codex, '_CODEX_HOME_ROOT', tmp_path)
    def path(session_id):
        result = tmp_path / session_id / 'thread-writer-locks' / f'{THREAD_ID}.lock'
        result.parent.mkdir(parents=True, exist_ok=True)
        return result
    return path


def test_dead_writer_releases_native_lock_without_unlink(writer_path):
    path = writer_path('dead-worker')
    proc = subprocess.Popen([sys.executable, '-c',
        'import fcntl,sys; f=open(sys.argv[1],"w"); '
        'fcntl.flock(f,fcntl.LOCK_EX); print("ready",flush=True); sys.stdin.read()',
        str(path)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert proc.stdout.readline().strip() == 'ready'
        inode = path.stat().st_ino
        assert backend_codex.codex_writer_conflict('dead-worker', THREAD_ID)
        proc.stdin.close()
        proc.wait(timeout=5)
        assert path.exists()
        assert backend_codex.codex_writer_conflict('dead-worker', THREAD_ID) is None
        assert path.stat().st_ino == inode
        with path.open('r+') as candidate:
            fcntl.flock(candidate, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


@pytest.mark.asyncio
async def test_detached_conflict_visible_and_every_send_refused(session, writer_path):
    session.backend_type = 'codex'
    session.session_id = THREAD_ID
    session._worker_admission = AsyncMock(side_effect=AssertionError('must refuse before quota'))
    path = writer_path(session.id)
    with path.open('w') as owner:
        fcntl.flock(owner, fcntl.LOCK_EX)
        inode = path.stat().st_ino
        for _ in range(3):
            view = session.to_dict()
            assert view['status'] == 'broken'
            assert view['runtime_connection'] == 'writer_conflict'
            assert view['runtime_error']['code'] == 'CODEX_WRITER_CONFLICT'
            with pytest.raises(CodexWriterConflictError):
                await session.preflight_delivery_admission()
            assert not session._lifecycle_lock.locked()
        assert path.stat().st_ino == inode
        with path.open('r+') as rival:
            with pytest.raises(BlockingIOError):
                fcntl.flock(rival, fcntl.LOCK_EX | fcntl.LOCK_NB)
    assert session.to_dict()['status'] == 'idle'
    session.is_orchestrator = True
    await session.preflight_delivery_admission()
    assert session.session_id == THREAD_ID
    assert path.stat().st_ino == inode


@pytest.mark.asyncio
async def test_attached_running_writer_keeps_steering(session, writer_path, tmp_path):
    session.backend_type = 'codex'
    session.session_id = THREAD_ID
    session.status = AgentStatus.RUNNING
    path = writer_path(session.id)
    output = tmp_path / 'turn-output.txt'
    script = """import fcntl,sys
f=open(sys.argv[1],'w'); fcntl.flock(f,fcntl.LOCK_EX)
print('ready',flush=True)
for line in sys.stdin:
    with open(sys.argv[2],'a') as out: out.write(line)
    print('written',flush=True)
"""
    proc = subprocess.Popen([sys.executable, '-c', script, str(path), str(output)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert proc.stdout.readline().strip() == 'ready'
        async def steer(message):
            proc.stdin.write(message + '\n')
            proc.stdin.flush()
            assert await asyncio.wait_for(asyncio.to_thread(proc.stdout.readline), 5) == 'written\n'
        session._backend = SimpleNamespace(is_alive=True, send=AsyncMock(side_effect=steer),
            deferred_interrupt_pending=False, session_id=THREAD_ID)
        delivery = SimpleNamespace(allow_running=True, before_submit=AsyncMock(),
            mark_submitted=AsyncMock(), mark_unknown=AsyncMock())
        await session.preflight_delivery_admission()
        assert session.to_dict()['status'] == 'running'
        await session.send('continue', provenance=MessageProvenance(
            origin='system', senders=('system',), subtype='restart'), delivery=delivery)
        assert output.read_text() == 'continue\n'
        assert proc.poll() is None
        assert backend_codex.codex_writer_conflict(session.id, THREAD_ID)
        delivery.mark_submitted.assert_awaited_once()
        assert session.status == AgentStatus.RUNNING
    finally:
        proc.stdin.close()
        try:
            proc.wait(timeout=5)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)


@pytest.mark.asyncio
async def test_resume_conflict_is_typed_and_visible_until_success(session, monkeypatch):
    session.backend_type = 'codex'
    session.session_id = THREAD_ID
    session.status = AgentStatus.RUNNING
    session._refresh_skills = AsyncMock()
    session._refresh_codex_project_doc = AsyncMock()
    session._activate_backend_tasks = MagicMock()
    session._persist = MagicMock()
    session._hibernate.schedule = MagicMock()
    monkeypatch.setattr('app.workspace.sync_agents_md', lambda *args: None)
    monkeypatch.setattr('app.manager.publish_backend_fds', lambda *args: None)
    candidate = SimpleNamespace(has_owned_processes=False, connect=AsyncMock(
        side_effect=CodexProtocolError('thread/resume', {'message':
            f'thread {THREAD_ID} already has an active writer'})))
    session._make_backend = MagicMock(return_value=candidate)
    with pytest.raises(CodexWriterConflictError) as exc:
        await session._ensure_backend()
    assert message_deliveries._failure(exc.value)['code'] == 'CODEX_WRITER_CONFLICT'
    assert session.to_dict()['status'] == 'broken'
    candidate.connect.side_effect = None
    await session._ensure_backend()
    assert session.to_dict()['runtime_error'] is None


@pytest.mark.asyncio
async def test_queued_race_fails_every_receipt_in_existing_runner(
    message_db, monkeypatch, session, writer_path,
):
    monkeypatch.setattr(message_deliveries, 'ensure_target_runner', lambda *args: None)
    ids = [str(uuid.uuid4()) for _ in range(3)]
    for delivery_id in ids:
        await _accept(message_deliveries, delivery_id=delivery_id)
    session.backend_type = 'codex'
    session.session_id = THREAD_ID
    session.is_orchestrator = True
    class FailedConnect:
        async def send_message_delivery(self, _id, message, *, delivery, provenance, **kwargs):
            await session.send(message, delivery=delivery, provenance=provenance)
    with writer_path(session.id).open('w') as owner:
        fcntl.flock(owner, fcntl.LOCK_EX)
        await message_deliveries.run_target_message_deliveries(TARGET_ID, FailedConnect())
    for delivery_id in ids:
        row = _delivery_row(message_db, delivery_id)
        assert row['state'] == 'FAILED_BEFORE_SUBMIT'
        assert json.loads(row['error_json'])['code'] == 'CODEX_WRITER_CONFLICT'


@pytest.mark.asyncio
async def test_http_repeated_conflict_never_returns_queued(message_db, writer_path, monkeypatch):
    from app.routes import sessions as routes
    from app.mcp_proof import issue_mcp_proof
    target = routes.manager.get_by_name(TARGET_NAME, SCOPE)
    target.backend_type = 'codex'
    target.session_id = THREAD_ID
    # Keep the real session gate while adapting the manager's session-id argument.
    async def preflight(_id):
        await target.preflight_delivery_admission()
    monkeypatch.setattr(routes.manager, 'preflight_message_delivery', preflight)
    monkeypatch.setattr(message_deliveries, 'ensure_target_runner', lambda *args: None)
    request = _request_with_proof(SOURCE_ID, issue_mcp_proof(SOURCE_ID))
    with writer_path(target.id).open('w') as owner:
        fcntl.flock(owner, fcntl.LOCK_EX)
        for _ in range(3):
            response = await routes.send_message(TARGET_NAME, routes.SendRequest(
                delivery_id=str(uuid.uuid4()), message='continue', sender=SOURCE_NAME,
                scope=SCOPE), request=request)
            assert response.status_code == 409
            payload = json.loads(response.body)
            assert payload['error']['code'] == 'CODEX_WRITER_CONFLICT'
            assert payload['error']['outcome_unknown'] is False


def test_unloaded_list_exposes_conflict(message_db, writer_path):
    from app.manager import SessionManager
    from app import db
    with db._conn() as connection:
        connection.execute("UPDATE sessions SET session_id=?, backend_type='codex' WHERE id=?",
                           (THREAD_ID, TARGET_ID))
    manager = SessionManager()
    with writer_path(TARGET_ID).open('w') as owner:
        fcntl.flock(owner, fcntl.LOCK_EX)
        target = next(row for row in manager.list_sessions(SCOPE) if row['id'] == TARGET_ID)
        assert target['status'] == 'broken'
        assert target['runtime_error']['code'] == 'CODEX_WRITER_CONFLICT'
