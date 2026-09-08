from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


def test_process_identity_is_persisted_before_fd_publication(tmp_path, monkeypatch):
    from app import db, manager
    from app.session import AgentSession
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'db.sqlite')
    db.init_db()
    session = AgentSession(id='owner', name='owner', scope='/test', cwd='/test')
    db.save_session(session._to_db_dict())
    session._backend = SimpleNamespace(pid=12345, cli_started_at=67890, fd_in=11, fd_out=12)
    published = []
    def store(name, fds):
        row = db.get_session('owner')
        assert (row['cli_pid'], row['cli_started_at']) == (12345, 67890)
        published.append(name)
    monkeypatch.setattr('app.fdstore.store_fds', store)
    assert manager.publish_backend_fds(session)
    assert len(published) == 2


@pytest.mark.asyncio
async def test_stale_refresh_releases_store_before_disconnect_and_preserves_failure(monkeypatch):
    from app.session import AgentSession
    session = AgentSession(id='s', name='s', scope='/test', cwd='/test')
    session.tools_are_stale = True
    steps = []
    monkeypatch.setattr('app.manager.retire_backend_fds', lambda s: steps.append('retired'))
    async def disconnect():
        assert steps == ['retired']
        raise RuntimeError('old writer is not released')
    old = SimpleNamespace(disconnect=disconnect)
    session._backend = old
    with pytest.raises(RuntimeError, match='not released'):
        await session._refresh_stale_backend()
    assert session._backend is old
    assert session.tools_are_stale
    assert 'not released' in session._runtime_error


@pytest.mark.asyncio
async def test_adopted_codex_waits_for_writer_release(monkeypatch, tmp_path):
    from app.backend_codex import CodexBackend, CodexWriterConflictError
    backend = CodexBackend(model='gpt-6-astra', cwd=str(tmp_path))
    backend._adopted_fds = (11, 12)
    backend._thread_id = 'thread'
    backend.teardown_adopted = AsyncMock()
    monkeypatch.setattr(backend, '_managed_codex_home_path', lambda: tmp_path / 'owner')
    outcomes = iter([CodexWriterConflictError('thread'), None])
    observe = MagicMock(side_effect=lambda *args: next(outcomes))
    monkeypatch.setattr('app.backend_codex.codex_writer_conflict', observe)
    await backend.disconnect()
    assert observe.call_count == 2
    backend.teardown_adopted.assert_awaited_once()


@pytest.mark.asyncio
async def test_adopted_disconnect_waits_for_actual_kernel_flock(tmp_path, monkeypatch):
    import asyncio
    import fcntl
    from app.backend_codex import CodexBackend
    root = tmp_path / 'homes'
    home = root / 'owner'
    locks = home / 'thread-writer-locks'
    locks.mkdir(parents=True)
    with (locks / 'thread.lock').open('w') as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        backend = CodexBackend(model='gpt-6-astra', cwd=str(tmp_path))
        backend._adopted_fds = (11, 12)
        backend._thread_id = 'thread'
        backend.teardown_adopted = AsyncMock()
        monkeypatch.setattr('app.backend_codex._CODEX_HOME_ROOT', root)
        monkeypatch.setattr(backend, '_managed_codex_home_path', lambda: home)
        async def release():
            await asyncio.sleep(0.1)
            fcntl.flock(held, fcntl.LOCK_UN)
        task = asyncio.create_task(release())
        try:
            await asyncio.wait_for(backend.disconnect(), timeout=2)
            assert task.done(), 'replacement was allowed while the native writer still held its lock'
        finally:
            await task


@pytest.mark.asyncio
async def test_timed_out_writer_release_can_be_retried_without_spawning(monkeypatch, tmp_path):
    from app.backend_codex import CodexBackend, CodexWriterConflictError
    backend = CodexBackend(model='gpt-6-astra', cwd=str(tmp_path))
    backend._adopted_fds = (11, 12)
    backend._thread_id = 'thread'
    async def teardown():
        backend._adopted_fds = None
    backend.teardown_adopted = teardown
    monkeypatch.setattr(backend, '_managed_codex_home_path', lambda: tmp_path / 'owner')
    monkeypatch.setattr('app.backend_codex.CODEX_PROCESS_TIMEOUT_SECONDS', 0.01)
    monkeypatch.setattr('app.backend_codex.codex_writer_conflict', lambda *a: CodexWriterConflictError('thread'))
    with pytest.raises(TimeoutError):
        await backend.disconnect()
    assert backend._teardown_error
    monkeypatch.setattr('app.backend_codex.codex_writer_conflict', lambda *a: None)
    await backend.disconnect()
    assert backend._teardown_error is None
