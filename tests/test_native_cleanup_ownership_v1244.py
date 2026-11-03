"""Existing session/lifecycle/repository ownership spans native cleanup awaits."""
import asyncio
import fcntl
import os
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app import deps, hub_workspace as hw, merge_operations as operations, workspace, worktree_cleanup
from app.manager import SessionManager
from tests.test_worktree_cleanup_v984 import setup, git


@pytest.mark.asyncio
@pytest.mark.parametrize('pause_at', ['resolve', 'clean'])
async def test_new_generation_publisher_waits_for_cleanup_owner(setup, tmp_path, monkeypatch, pause_at):
    main, wt = setup
    monkeypatch.setattr(hw, 'STATE_DIR', tmp_path / 'records')
    sid = 'native-generation-owner'
    branch = git(wt, 'branch', '--show-current').stdout.strip()
    head = git(wt, 'rev-parse', 'HEAD').stdout.strip()
    row = {'id': sid, 'backend_type': 'codex', 'worktree_path': str(wt), 'task_id': '', 'branch': branch, 'status': 'idle'}
    manager = SessionManager()
    live = SimpleNamespace(_lifecycle_lock=asyncio.Lock(), backend_type='codex', worktree_path=str(wt),
                           task_id='', branch=branch, status='idle')
    manager.sessions[sid] = live
    monkeypatch.setattr(deps, 'manager', manager)
    monkeypatch.setattr(operations, 'get_session', lambda _: dict(row))
    entered, release = threading.Event(), threading.Event()
    attempted, published = asyncio.Event(), asyncio.Event()
    order = []

    def resolve(*_):
        if pause_at == 'resolve':
            entered.set()
            assert release.wait(8), 'resolution latch timed out'
        return main

    def clean(*_args, **_kwargs):
        assert not published.is_set()
        assert manager.get_session_lock(sid).locked() and live._lifecycle_lock.locked()
        order.append('clean')
        if pause_at == 'clean':
            entered.set()
            assert release.wait(8), 'cleanup latch timed out'
        return {'state': 'skipped'}

    monkeypatch.setattr(workspace, '_resolve_repo', resolve)
    monkeypatch.setattr(worktree_cleanup, 'clean_worktree', clean)
    cleanup = asyncio.create_task(operations._clean_worktree_after_merge(
        {'session_id': sid, 'accepted_worker_branch': branch, 'accepted_worker_head': head,
         'request': {'merge_schema_version': 2, 'task_outcome': 'complete'}},
        {'git': {'target_branch': 'main'}}))

    async def publisher():
        attempted.set()
        # Same ownership order as dispatch/branch publication and model change.
        async with manager.get_session_lock(sid), live._lifecycle_lock:
            row.update(task_id='43', branch='task-43/worker', backend_type='hub')
            live.task_id, live.branch, live.backend_type = '43', 'task-43/worker', 'hub'
            new = hw.WorkspaceState('hub-bbbbbbbbbbbbbbbb', str(wt), str(tmp_path / 'generation43'),
                                    thread_id='thread-task-43', project_id='project-task-43')
            new.save()
            order.append('publish')
            published.set()

    publish = None
    try:
        assert await asyncio.to_thread(entered.wait, 8)
        publish = asyncio.create_task(publisher())
        await asyncio.wait_for(attempted.wait(), 4)
        assert not published.is_set()
        assert manager.get_session_lock(sid).locked() and live._lifecycle_lock.locked()
        if pause_at == 'clean':
            # Actual kernel lock proof, not another unlocked metadata read.
            fd = os.open(workspace._repo_lock_path(main), os.O_RDWR)
            try:
                with pytest.raises(BlockingIOError):
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally:
                os.close(fd)
    finally:
        release.set()
        await asyncio.wait_for(cleanup, 12)
        if publish is not None:
            await asyncio.wait_for(publish, 12)
    assert order == ['clean', 'publish']
    assert row['task_id'] == '43'
    assert not hw.WorkspaceState.load('hub-bbbbbbbbbbbbbbbb').archived


@pytest.mark.asyncio
async def test_generation_published_at_resolution_await_is_held(setup, tmp_path, monkeypatch):
    main, wt = setup
    monkeypatch.setattr(hw, 'STATE_DIR', tmp_path / 'records')
    manager = SessionManager()
    monkeypatch.setattr(deps, 'manager', manager)
    monkeypatch.setattr(operations, 'get_session', lambda _: {'backend_type': 'codex', 'worktree_path': str(wt), 'task_id': ''})
    new = hw.WorkspaceState('hub-bbbbbbbbbbbbbbbb', str(wt), str(tmp_path / 'generation43'), thread_id='thread-task-43')
    def resolve(*_):
        new.save()
        return main
    monkeypatch.setattr(workspace, '_resolve_repo', resolve)
    clean = Mock(return_value={'state': 'skipped'})
    monkeypatch.setattr(worktree_cleanup, 'clean_worktree', clean)
    await operations._clean_worktree_after_merge(
        {'session_id': 'publication-during-resolve', 'request': {'merge_schema_version': 2, 'task_outcome': 'complete'}},
        {'git': {'target_branch': 'main'}})
    assert not hw.WorkspaceState.load(new.ws_id).archived
    clean.assert_not_called()


@pytest.mark.asyncio
async def test_hub_before_first_workspace_publication_is_not_optional_cleanup(setup, monkeypatch):
    main, wt = setup
    monkeypatch.setattr(deps, 'manager', SessionManager())
    monkeypatch.setattr(operations, 'get_session', lambda _: {'backend_type': 'hub', 'worktree_path': str(wt)})
    resolve = Mock(side_effect=AssertionError('Hub cleanup has no generation ownership'))
    clean = Mock()
    monkeypatch.setattr(workspace, '_resolve_repo', resolve)
    monkeypatch.setattr(worktree_cleanup, 'clean_worktree', clean)
    await operations._clean_worktree_after_merge({'session_id': 'hub-before-publication'}, {'git': {'target_branch': 'main'}})
    resolve.assert_not_called()
    clean.assert_not_called()
