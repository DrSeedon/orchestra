"""Offline follow-up inputs: real Git/merge lifecycle, synthetic bytes, fake hub."""
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio

from app import db, hub_workspace as hw, tm, workspace
from app.session import AgentSession
from tests.task_seeds import create_task
from tests.test_hub_workspace import _backend, _turn, _offline_hub_pool
from tests.test_merge_worker_v1034 import git
from tests.test_task_tracker_integration import (
    _init_db, _make_git_scope, _save_worker, _prepare_merge,
)


@pytest_asyncio.fixture
async def continued(tmp_path, monkeypatch):
    from app.routes.sessions import execute_merge_session

    _init_db()
    repo = _make_git_scope(monkeypatch, tmp_path)
    # Source-only project: no project memory/layout is required.
    (repo / 'task').mkdir()
    (repo / 'task/seed.txt').write_text('public seed\n')
    git(repo, 'add', '.')
    git(repo, 'commit', '-qm', 'public seed')
    monkeypatch.setattr(hw, 'STATE_DIR', tmp_path / 'hub-state')
    monkeypatch.setattr(hw, 'known_secret_values', lambda extra=None: [])
    with tm._conn() as conn:
        tm.ensure_project(conn, 'project', scope=str(repo))
        task = create_task(conn, 'project', 'Public follow-up', par_number=42, status='in_progress')
        conn.execute('UPDATE tm_tasks SET worker_session_id=? WHERE id=?', ('followup', task['id']))
    wt = workspace.create_worktree(str(repo), 'followup', task_id='42')
    root = Path(wt.path)
    _save_worker(session_id='followup', task_id='42', scope=str(repo),
                 worktree_path=wt.path, branch=wt.branch)
    observed = []

    def edit(remote):
        observed.append({str(p.relative_to(remote)): p.read_bytes()
                         for p in remote.rglob('*') if p.is_file()})
        (remote / 'task/output.txt').write_text('public derived output\n')

    backend, ssh, mc = _backend(root, tmp_path, monkeypatch, edit)
    backend._paths = ['task']
    session = AgentSession(id='followup', name='followup', scope=str(repo), cwd=str(root),
                           worktree_path=wt.path, branch=wt.branch, base_branch='main')
    backend._bridge = session._hub_bridge()
    await _turn(backend, 'make output')
    state = backend._state
    head = git(root, 'rev-parse', 'HEAD').strip()
    found = _prepare_merge(monkeypatch, session_id='followup', scope=str(repo))
    result = await execute_merge_session(
        session_id=found.id, expected_name=found.name, expected_scope=str(repo),
        expected_branch=found.branch, expected_head=head,
        req={'scope': str(repo), 'task_outcome': 'continue', 'merge_schema_version': 2,
             'expected_head': head, 'acceptance_note': 'Verified public output.'},
    )
    assert result['ok'], result
    assert db.get_session(found.id)['task_id'] == '42'
    assert not db.get_session(found.id)['needs_switch']
    assert git(root, 'rev-parse', 'HEAD') == git(repo, 'rev-parse', 'main')
    assert not (repo / '.orchestra').exists()
    return SimpleNamespace(repo=repo, root=root, backend=backend, ssh=ssh, mc=mc,
                           state=state, observed=observed, result=result, branch=wt.branch)


def add_inputs(env, count=41):
    files = {f'task/new-inputs/public-{i:02}.txt':
             (f'public synthetic record {i:02}\n' * 2800).encode() for i in range(count)}
    for rel, data in files.items():
        path = env.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    git(env.repo, 'add', 'task/new-inputs')
    git(env.repo, 'commit', '-qm', 'new committed public inputs')
    return files


@pytest.mark.asyncio
async def test_continue_cleanup_keeps_workspace_and_history(continued, monkeypatch):
    from app.merge_operations import _clean_worktree_after_merge
    from tests.test_hub_inputs_v1062 import _Entering
    env = continued
    monkeypatch.setattr('app.backend_hub.MultiCodeClient.from_env', lambda: _Entering(env.mc))
    await _clean_worktree_after_merge(
        {'session_id': 'followup', 'request': {'merge_schema_version': 2, 'task_outcome': 'continue'}},
        {'git': {'target_branch': 'main'}},
    )
    assert env.state.path().exists(), 'continue must retain hub state and thread history'
    assert env.ssh.removed == []
    files = add_inputs(env)
    events = await _turn(env.backend, 'audit newly committed inputs')
    assert not [event.content for event in events if event.type == 'error']
    assert {rel: env.observed[-1].get(rel) for rel in files} == files
    assert env.backend._state.ws_id == env.state.ws_id
    assert env.backend._state.thread_id == env.state.thread_id
    assert [name for name, _ in env.mc.calls].count('t3_thread_launch') == 1
    assert [args['threadId'] for name, args in env.mc.calls if name == 't3_thread_send'] == [env.state.thread_id]


@pytest.mark.asyncio
async def test_followup_refreshes_local_source_before_remote_delta(continued):
    env = continued
    files = add_inputs(env)
    assert not (env.root / 'task/new-inputs').exists()
    events = await _turn(env.backend, 'read newly committed public inputs')
    assert not [event.content for event in events if event.type == 'error']
    actual = {rel: env.observed[-1].get(rel) for rel in files}
    assert actual == files, f'expected {len(files)} files, got {sum(v is not None for v in actual.values())}'
    assert git(env.root, 'rev-parse', 'HEAD') == git(env.repo, 'rev-parse', 'main')
    assert git(env.root, 'branch', '--show-current').strip() == env.branch
    assert env.backend._paths == ['task']


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['tracked', 'staged', 'untracked', 'diverged', 'ignored-collision', 'operation', 'binding'])
async def test_refresh_refuses_wip_without_upload_or_history_loss(continued, kind):
    env = continued
    files = add_inputs(env, 1)
    if kind == 'tracked':
        (env.root / 'task/seed.txt').write_text('local WIP\n')
    elif kind == 'staged':
        (env.root / 'task/seed.txt').write_text('staged WIP\n')
        git(env.root, 'add', 'task/seed.txt')
    elif kind == 'untracked':
        (env.root / 'task/untracked.txt').write_text('untracked WIP\n')
    elif kind == 'diverged':
        (env.root / 'task/seed.txt').write_text('committed worker WIP\n')
        git(env.root, 'add', '.')
        git(env.root, 'commit', '-qm', 'worker after continue')
        # Main also changes the same content: never choose one side automatically.
        (env.repo / 'task/seed.txt').write_text('different main edit\n')
        git(env.repo, 'add', '.')
        git(env.repo, 'commit', '-qm', 'base conflict')
    elif kind == 'ignored-collision':
        collision = env.root / next(iter(files))
        collision.parent.mkdir(parents=True)
        collision.write_text('ignored local data\n')
        git_dir = Path(git(env.root, 'rev-parse', '--git-common-dir').strip())
        (git_dir / 'info/exclude').write_text('task/new-inputs/\n')
    elif kind == 'operation':
        merge_head = Path(git(env.root, 'rev-parse', '--git-path', 'MERGE_HEAD').strip())
        merge_head.write_text(git(env.root, 'rev-parse', 'HEAD'))
    elif kind == 'binding':
        git(env.root, 'switch', '-c', 'unexpected-branch')
    before_head = git(env.root, 'rev-parse', 'HEAD')
    before_status = git(env.root, 'status', '--porcelain', '--untracked-files=all')
    before_index = git(env.root, 'ls-files', '--stage')
    before = {str(p.relative_to(env.root)): p.read_bytes() for p in env.root.rglob('*')
              if p.is_file() and p.name != '.git'}
    calls = len(env.mc.calls)
    manifest = dict(env.state.manifest)
    events = await _turn(env.backend, 'use newly committed public inputs')
    errors = [event.content for event in events if event.type == 'error']
    assert errors and 'source refresh' in errors[0], events
    assert not any(name in ('t3_thread_send', 't3_thread_launch') for name, _ in env.mc.calls[calls:])
    assert len(env.observed) == 1
    assert git(env.root, 'rev-parse', 'HEAD') == before_head
    assert git(env.root, 'status', '--porcelain', '--untracked-files=all') == before_status
    assert git(env.root, 'ls-files', '--stage') == before_index
    assert {str(p.relative_to(env.root)): p.read_bytes() for p in env.root.rglob('*')
            if p.is_file() and p.name != '.git'} == before
    assert env.backend._state.manifest == manifest
    assert env.backend._state.thread_id == env.state.thread_id
    assert env.state.path().exists() and not env.ssh.removed


@pytest.mark.asyncio
async def test_refresh_preserves_frozen_input_and_reconnects_same_history(continued):
    env = continued
    original = env.root / 'task/original.txt'
    original.write_text('public untracked original\n')
    env.state.input_manifest = {'task/original.txt': hw.sha256_file(original)}
    env.state.manifest.update(env.state.input_manifest)
    env.state.save()
    (Path(env.state.remote_dir) / 'task/original.txt').write_bytes(original.read_bytes())
    files = add_inputs(env, 1)
    ws_id, thread_id = env.state.ws_id, env.state.thread_id
    # A fresh backend instance resumes the saved workspace; no persisted new fields needed.
    env.backend._resume = ws_id
    env.backend._state = None
    await env.backend.connect()
    events = await _turn(env.backend, 'resume with new inputs')
    assert not [event.content for event in events if event.type == 'error']
    assert env.backend._state.ws_id == ws_id
    assert env.backend._state.thread_id == thread_id
    assert env.backend._state.input_manifest == {'task/original.txt': hw.sha256_file(original)}
    assert original.read_text() == 'public untracked original\n'
    assert 'task/original.txt' not in git(env.root, 'ls-files').splitlines()
    assert all(env.observed[-1][rel] == data for rel, data in files.items())


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['changed', 'collision'])
async def test_refresh_refuses_frozen_input_changes_or_target_collision(continued, kind):
    env = continued
    original = env.root / 'task/original.txt'
    original.write_text('public immutable input\n')
    env.state.input_manifest = {'task/original.txt': hw.sha256_file(original)}
    env.state.save()
    add_inputs(env, 1)
    if kind == 'changed':
        original.write_text('edited original\n')
    else:
        (env.repo / 'task/original.txt').write_text('target collision\n')
        git(env.repo, 'add', '.')
        git(env.repo, 'commit', '-qm', 'colliding target input')
    before = original.read_bytes()
    head = git(env.root, 'rev-parse', 'HEAD')
    events = await _turn(env.backend, 'continue')
    assert any(event.type == 'error' for event in events)
    assert len(env.observed) == 1
    assert original.read_bytes() == before
    assert git(env.root, 'rev-parse', 'HEAD') == head


@pytest.mark.asyncio
async def test_followup_still_excludes_unowned_and_private_files(continued):
    env = continued
    files = add_inputs(env, 1)
    for rel in ['task/COMPANY-DATA.md', 'task/.env', 'unowned/public.txt']:
        path = env.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('synthetic excluded file\n')
    git(env.repo, 'add', '.')
    git(env.repo, 'commit', '-qm', 'synthetic guard fixtures')
    events = await _turn(env.backend, 'read allowed new input')
    assert not [event.content for event in events if event.type == 'error']
    assert all(env.observed[-1][rel] == data for rel, data in files.items())
    assert not {'task/COMPANY-DATA.md', 'task/.env', 'unowned/public.txt'} & env.observed[-1].keys()


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['rewrite', 'new-collision', 'deleted', 'symlink'])
async def test_remote_wip_blocks_refresh_before_send_and_preserves_recovery(continued, kind):
    env = continued
    files = add_inputs(env, 1)
    remote = Path(env.state.remote_dir)
    if kind in ('rewrite', 'deleted', 'symlink'):
        rel = 'task/seed.txt'
        (env.repo / rel).write_text('new committed seed\n')
        git(env.repo, 'add', '.')
        git(env.repo, 'commit', '-qm', 'new source version')
        if kind == 'rewrite':
            (remote / rel).write_text('unsynced remote WIP\n')
        else:
            (remote / rel).unlink()
            if kind == 'symlink':
                (remote / rel).symlink_to('output.txt')
    else:
        rel = next(iter(files))
        (remote / rel).parent.mkdir(parents=True)
        (remote / rel).write_text('unsynced remote output\n')
    before = {str(p.relative_to(remote)): p.read_bytes() for p in remote.rglob('*') if p.is_file()}
    manifest = dict(env.state.manifest)
    events = await _turn(env.backend, 'audit new committed source')
    errors = [event.content for event in events if event.type == 'error']
    assert errors and 'hub refresh:' in errors[0], events
    assert len(env.observed) == 1  # no provider turn on stale/conflicting input
    assert {str(p.relative_to(remote)): p.read_bytes() for p in remote.rglob('*') if p.is_file()} == before
    assert env.state.manifest == manifest
    assert env.state.path().exists() and not env.ssh.removed
    if kind == 'symlink':
        assert (remote / rel).is_symlink()
    # Explicitly restore the remote baseline, then the same history can continue.
    if (remote / rel).is_symlink():
        (remote / rel).unlink()
    if kind == 'new-collision':
        (remote / rel).unlink()
    else:
        (remote / rel).write_bytes(env.observed[0][rel])
    events = await _turn(env.backend, 'retry after explicit reconciliation')
    assert not [event.content for event in events if event.type == 'error']
    assert len(env.observed) == 2
    assert all(env.observed[-1][rel] == data for rel, data in files.items())


@pytest.mark.asyncio
async def test_live_declared_base_is_used_instead_of_assuming_main(continued):
    env = continued
    git(env.repo, 'switch', '-c', 'declared-base')
    files = add_inputs(env, 1)
    # Bind through the real session bridge; it must read the current base every turn.
    session = AgentSession(id='followup', name='followup', scope=str(env.repo), cwd=str(env.root),
                           branch=env.branch, base_branch='main')
    env.backend._bridge = session._hub_bridge()
    session.base_branch = 'declared-base'
    events = await _turn(env.backend, 'read committed declared-base input')
    assert not [event.content for event in events if event.type == 'error']
    assert all(env.observed[-1][rel] == data for rel, data in files.items())
    assert git(env.root, 'rev-parse', 'HEAD') == git(env.repo, 'rev-parse', 'declared-base')
    assert git(env.root, 'rev-parse', 'HEAD') != git(env.repo, 'rev-parse', 'main')


@pytest.mark.asyncio
async def test_upload_failure_after_delivery_retries_without_losing_history(continued, monkeypatch):
    env = continued
    files = add_inputs(env, 1)
    put = env.ssh.put
    manifest = dict(env.state.manifest)

    async def uncertain(remote_dir, tar_path):
        await put(remote_dir, tar_path)
        raise hw.HubWorkspaceError('synthetic lost upload acknowledgement')

    monkeypatch.setattr(env.ssh, 'put', uncertain)
    events = await _turn(env.backend, 'new inputs with uncertain upload')
    assert any(event.type == 'error' for event in events)
    assert len(env.observed) == 1
    assert env.state.manifest == manifest
    monkeypatch.setattr(env.ssh, 'put', put)
    events = await _turn(env.backend, 'retry the same input delivery')
    assert not [event.content for event in events if event.type == 'error']
    assert all(env.observed[-1][rel] == data for rel, data in files.items())
    assert [name for name, _ in env.mc.calls].count('t3_thread_launch') == 1


@pytest.mark.asyncio
async def test_new_input_total_limit_refuses_before_remote_write(continued, monkeypatch):
    env = continued
    files = add_inputs(env, 1)
    manifest = dict(env.state.manifest)
    with monkeypatch.context() as scoped:
        scoped.setattr(hw, 'project_options', lambda scope: hw.ProjectOptions(max_total_bytes=100))
        events = await _turn(env.backend, 'guarded new inputs')
    assert any(event.type == 'error' and 'too large' in event.content for event in events)
    assert len(env.observed) == 1
    assert env.state.manifest == manifest
    assert not (Path(env.state.remote_dir) / 'task/new-inputs').exists()
    events = await _turn(env.backend, 'retry with ordinary limits')
    assert not [event.content for event in events if event.type == 'error']
    assert all(env.observed[-1][rel] == data for rel, data in files.items())


def test_plain_directory_and_broken_git_remain_distinct(tmp_path, monkeypatch):
    root = tmp_path / 'plain'
    root.mkdir()
    assert hw.refresh_source(root, 'worker', 'main') == ''
    (root / '.git').write_text('gitdir: missing-private-git\n')
    with pytest.raises(hw.HubWorkspaceError, match='invalid Git metadata'):
        hw.refresh_source(root, 'worker', 'main')
    monkeypatch.setattr(hw, '_git_out', lambda *args: None)
    with pytest.raises(hw.HubWorkspaceError, match='cannot inspect Git source'):
        hw.refresh_source(root, 'worker', 'main')


@pytest.mark.asyncio
async def test_continue_without_hub_state_keeps_ordinary_cleanup(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock, Mock
    from app import merge_operations, worktree_cleanup

    release = AsyncMock()
    clean = Mock(return_value={'state': 'skipped'})
    monkeypatch.setattr(merge_operations, 'get_session', lambda sid: {'worktree_path': str(tmp_path)})
    monkeypatch.setattr(hw, 'states_for_worktree', lambda path: [])
    monkeypatch.setattr('app.backend_hub.release_for_worktree', release)
    monkeypatch.setattr(workspace, '_resolve_repo', lambda *args: tmp_path)
    monkeypatch.setattr(worktree_cleanup, 'clean_worktree', clean)
    await merge_operations._clean_worktree_after_merge(
        {'session_id': 'ordinary', 'request': {'merge_schema_version': 2, 'task_outcome': 'continue'}},
        {'git': {'target_branch': 'main'}},
    )
    release.assert_awaited_once_with(str(tmp_path))
    clean.assert_called_once_with(str(tmp_path), main_checkout=str(tmp_path), target_ref='main', apply=True)
