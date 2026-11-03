"""Cancellation must drain the real cleanup thread before lifecycle publication."""
import asyncio
import fcntl
import os
import threading
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from tests.test_merge_operations import merge_db
from tests.test_worktree_cleanup_v984 import setup, git


async def scheduler_fence():
    event = asyncio.Event()
    asyncio.get_running_loop().call_soon(event.set)
    await event.wait()


@pytest.mark.asyncio
@pytest.mark.parametrize('repeated', [False, True])
@pytest.mark.parametrize('cleanup_fails', [False, True])
async def test_cancel_drains_thread_before_actual_lifecycle_publication(
    setup, merge_db, tmp_path, monkeypatch, repeated, cleanup_fails,
):
    from app import db, deps, hub_workspace as hw, merge_operations as operations, workspace, worktree_cleanup
    from app.manager import SessionManager

    main, worktree = setup
    sid = 'merge-session'
    branch = git(worktree, 'branch', '--show-current').stdout.strip()
    head = git(worktree, 'rev-parse', 'HEAD').stdout.strip()
    monkeypatch.setattr(hw, 'STATE_DIR', tmp_path / 'workspace-records')
    row = db.get_session(sid)
    row.update(worktree_path=str(worktree), backend_type='codex', task_id='', branch=branch,
               base_branch='main', status='idle')
    db.save_session(row)
    manager = SessionManager()
    live = SimpleNamespace(id=sid, _lifecycle_lock=asyncio.Lock(), backend_type='codex',
                           worktree_path=str(worktree), task_id='', branch=branch,
                           base_branch='main', needs_switch=False, status='idle', loaded=False, db_row=None,
                           name='synthetic-worker')
    manager.sessions[sid] = live
    monkeypatch.setattr(deps, 'manager', manager)
    entered, release, exited = threading.Event(), threading.Event(), threading.Event()
    attempted, acquired = asyncio.Event(), asyncio.Event()
    order = []
    real_lock = workspace.repo_mutation_lock

    @contextmanager
    def observed_lock(repo):
        try:
            with real_lock(repo):
                yield
        finally:
            order.append('thread_exit')
            exited.set()
    monkeypatch.setattr(workspace, 'repo_mutation_lock', observed_lock)

    def blocked_cleanup(*_args, **_kwargs):
        entered.set()
        assert release.wait(8), 'synthetic cleanup latch timed out'
        if cleanup_fails:
            raise RuntimeError('synthetic cleanup failure after release')
        return {'state': 'skipped', 'files': 0, 'bytes': 0}
    monkeypatch.setattr(worktree_cleanup, 'clean_worktree', blocked_cleanup)
    cleanup = asyncio.create_task(operations._clean_worktree_after_merge(
        {'session_id': sid, 'accepted_worker_branch': branch, 'accepted_worker_head': head,
         'request': {'merge_schema_version': 2, 'task_outcome': 'complete'}},
        {'git': {'target_branch': 'main', 'worker_branch': branch, 'worker_head': head}}))

    async def publish_new_hub_generation():
        attempted.set()
        async with manager.get_session_lock(sid), live._lifecycle_lock:
            acquired.set()
            await manager.transition_lifecycle(live, branch=branch, base_branch='main', task_id='43', needs_switch=False)
            current = db.get_session(sid)
            current['backend_type'] = 'hub'
            db.save_session(current)
            live.backend_type = 'hub'
            state = hw.WorkspaceState('hub-cafecafecafecafe', str(worktree), str(tmp_path / 'remote-generation-43'),
                                      project_id='synthetic-project-43', thread_id='synthetic-thread-43')
            state.save()
            order.append('publish43')
            return state.ws_id

    publisher = None
    premature = False
    try:
        assert await asyncio.to_thread(entered.wait, 6)
        cleanup.cancel()
        publisher = asyncio.create_task(publish_new_hub_generation())
        await asyncio.wait_for(attempted.wait(), 5)
        await scheduler_fence()
        if repeated and not cleanup.done():
            cleanup.cancel()
            await scheduler_fence()
            cleanup.cancel()
            await scheduler_fence()
        premature = acquired.is_set()
        # Unsafe code is allowed to finish its actual publisher while the worker
        # thread is held. Safe code never waits for a blocked publisher here.
        if premature:
            await asyncio.wait_for(publisher, 5)
        else:
            assert not cleanup.done()
            assert manager.get_session_lock(sid).locked() and live._lifecycle_lock.locked()
            fd = os.open(workspace._repo_lock_path(main), os.O_RDWR)
            try:
                with pytest.raises(BlockingIOError):
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally:
                os.close(fd)
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(cleanup, 10)
        new_id = await asyncio.wait_for(publisher, 5)
        assert await asyncio.to_thread(exited.wait, 8)
        assert order == ['thread_exit', 'publish43']
        assert not premature
        assert db.get_session(sid)['task_id'] == '43'
        assert db.get_session(sid)['backend_type'] == 'hub'
        assert not hw.WorkspaceState.load(new_id).archived
        assert not manager.get_session_lock(sid).locked() and not live._lifecycle_lock.locked()
    finally:
        release.set()
        if not exited.is_set():
            assert await asyncio.to_thread(exited.wait, 8)
        if not cleanup.done():
            try:
                await asyncio.wait_for(cleanup, 10)
            except asyncio.CancelledError:
                pass
        if publisher is not None and not publisher.done():
            await asyncio.wait_for(publisher, 5)
