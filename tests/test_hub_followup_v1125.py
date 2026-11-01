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
async def started(tmp_path, monkeypatch):
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
    return SimpleNamespace(repo=repo, root=root, backend=backend, ssh=ssh, mc=mc,
                           state=state, observed=observed, session=session, branch=wt.branch)


@pytest_asyncio.fixture
async def continued(started, monkeypatch):
    from app.routes.sessions import execute_merge_session

    env = started
    repo, root = env.repo, env.root
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
    env.result = result
    return env


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


def local_snapshot(root):
    return {
        'head': git(root, 'rev-parse', 'HEAD'),
        'branch': git(root, 'branch', '--show-current'),
        'status': git(root, 'status', '--porcelain', '--untracked-files=all'),
        'index': git(root, 'ls-files', '--stage'),
        'staged': git(root, 'diff', '--cached', '--binary'),
        'history': git(root, 'log', '--format=%H %P'),
        'refs': git(root, 'show-ref'),
        'reflog': git(root, 'reflog', '--format=%H %gs'),
        'files': {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*')
                  if p.is_file() and p.name != '.git'},
    }


@pytest.mark.asyncio
@pytest.mark.parametrize('reconnect', [False, True])
async def test_unmerged_ready_commit_continues_on_diverged_branch(started, reconnect):
    env = started
    ready = git(env.root, 'rev-parse', 'HEAD').strip()
    assert git(env.root, 'rev-list', '--count', 'main..HEAD').strip() == '1'
    assert git(env.root, 'status', '--porcelain') == ''
    assert not (env.repo / 'task/output.txt').exists(), 'worker output is still unmerged'
    files = add_inputs(env, 1)
    # Even conflicting base content must not force reconciliation for a follow-up.
    (env.repo / 'task/seed.txt').write_text('independent main edit\n')
    git(env.repo, 'add', '.')
    git(env.repo, 'commit', '-qm', 'main advanced independently')
    before = local_snapshot(env.root)
    state = env.state
    provenance = dict(state.input_manifest)
    baseline = dict(state.manifest)
    if reconnect:
        env.backend._resume = state.ws_id
        env.backend._state = None
        await env.backend.connect()

    def add_changelog(remote):
        assert local_snapshot(env.root) == before, 'optional refresh must preserve the task branch'
        env.observed.append({str(p.relative_to(remote)): p.read_bytes()
                             for p in remote.rglob('*') if p.is_file()})
        (remote / 'task/CHANGELOG.md').write_text('Document completed worker output.\n')

    env.mc.hub_edit = add_changelog
    events = await _turn(env.backend, 'add CHANGELOG before acceptance')
    assert not [event.content for event in events if event.type == 'error']
    notes = [event.content for event in events if event.type == 'status']
    assert any('source refresh skipped' in note and 'diverged' in note
               and 'existing branch' in note and 'not refreshed' in note for note in notes), notes
    assert not any('source fast-forwarded' in note for note in notes)
    assert env.observed[-1]['task/output.txt'] == b'public derived output\n'
    assert env.observed[-1]['task/seed.txt'] == b'public seed\n'
    assert not files.keys() & env.observed[-1].keys(), 'skipped base inputs were not delivered'
    assert not (env.root / 'task/new-inputs').exists()
    assert (env.root / 'task/CHANGELOG.md').read_text() == 'Document completed worker output.\n'
    assert git(env.root, 'log', '-1', '--format=%P').strip() == ready
    assert git(env.root, 'rev-list', '--count', 'main..HEAD').strip() == '2'
    assert git(env.root, 'branch', '--show-current').strip() == env.branch
    assert git(env.root, 'status', '--porcelain') == ''
    assert env.backend._state.ws_id == state.ws_id
    assert env.backend._state.thread_id == state.thread_id
    assert env.backend._state.input_manifest == provenance
    assert all(env.backend._state.manifest[rel] == digest for rel, digest in baseline.items())
    assert [name for name, _ in env.mc.calls].count('t3_thread_launch') == 1
    assert [args['threadId'] for name, args in env.mc.calls if name == 't3_thread_send'] == [state.thread_id]
    assert not env.ssh.removed


@pytest.mark.asyncio
@pytest.mark.parametrize('guard', [
    'MERGE_HEAD', 'CHERRY_PICK_HEAD', 'REVERT_HEAD', 'rebase-merge', 'rebase-apply',
    'binding', 'detached', 'broken-index', 'missing-base',
])
async def test_diverged_followup_keeps_git_and_binding_guards(started, guard):
    env = started
    add_inputs(env, 1)
    if guard in ('MERGE_HEAD', 'CHERRY_PICK_HEAD', 'REVERT_HEAD', 'rebase-merge', 'rebase-apply'):
        marker = Path(git(env.root, 'rev-parse', '--git-path', guard).strip())
        if guard.startswith('rebase-'):
            marker.mkdir()
        else:
            marker.write_text(git(env.root, 'rev-parse', 'HEAD'))
    elif guard == 'binding':
        git(env.root, 'switch', '-c', 'unexpected-branch')
    elif guard == 'detached':
        git(env.root, 'switch', '--detach')
    elif guard == 'broken-index':
        index = Path(git(env.root, 'rev-parse', '--git-path', 'index').strip())
        index.write_bytes(b'broken synthetic index')
    else:
        env.session.base_branch = 'missing-base'
    head = git(env.root, 'rev-parse', 'HEAD')
    branch = git(env.root, 'rev-parse', '--abbrev-ref', 'HEAD')
    files = {str(p.relative_to(env.root)): p.read_bytes() for p in env.root.rglob('*')
             if p.is_file() and p.name != '.git'}
    remote = Path(env.state.remote_dir)
    remote_before = {str(p.relative_to(remote)): p.read_bytes() for p in remote.rglob('*') if p.is_file()}
    manifest, provenance = dict(env.state.manifest), dict(env.state.input_manifest)
    calls = len(env.mc.calls)
    events = await _turn(env.backend, 'add changelog')
    assert any(event.type == 'error' and 'source refresh' in event.content for event in events), events
    assert not any(event.type == 'status' and 'source refresh skipped' in event.content for event in events)
    assert not any(name in ('t3_thread_send', 't3_thread_launch') for name, _ in env.mc.calls[calls:])
    assert len(env.observed) == 1
    assert git(env.root, 'rev-parse', 'HEAD') == head
    assert git(env.root, 'rev-parse', '--abbrev-ref', 'HEAD') == branch
    assert {str(p.relative_to(env.root)): p.read_bytes() for p in env.root.rglob('*')
            if p.is_file() and p.name != '.git'} == files
    assert {str(p.relative_to(remote)): p.read_bytes() for p in remote.rglob('*') if p.is_file()} == remote_before
    assert env.state.manifest == manifest and env.state.input_manifest == provenance
    assert env.state.path().exists() and not env.ssh.removed
    if guard == 'broken-index':
        assert index.read_bytes() == b'broken synthetic index'


@pytest.mark.asyncio
@pytest.mark.parametrize('probe,returncode', [('base', 128), ('worker', 128), ('base', None), ('worker', None)])
async def test_ancestry_inspection_errors_do_not_become_skips(started, monkeypatch, probe, returncode):
    import subprocess

    env = started
    add_inputs(env, 1)
    original = hw._git_out
    head = git(env.root, 'rev-parse', 'HEAD').strip()

    def fail(root, *args):
        if args[:2] == ('merge-base', '--is-ancestor') and ((args[2] == head) == (probe == 'worker')):
            return None if returncode is None else subprocess.CompletedProcess(args, returncode, b'', b'Git error')
        return original(root, *args)

    monkeypatch.setattr(hw, '_git_out', fail)
    before = local_snapshot(env.root)
    events = await _turn(env.backend, 'continue after Git inspection failure')
    assert any(event.type == 'error' and 'ancestry' in event.content for event in events), events
    assert local_snapshot(env.root) == before
    assert len(env.observed) == 1


@pytest.mark.asyncio
async def test_refresh_waits_for_existing_repository_writer(continued, monkeypatch):
    import asyncio
    from contextlib import contextmanager
    import threading

    env = continued
    add_inputs(env, 1)
    original_lock = workspace.repo_mutation_lock
    original_inspect = workspace.inspect_worktree_identity
    attempting, inspected = threading.Event(), threading.Event()

    @contextmanager
    def lock(repo):
        attempting.set()
        with original_lock(repo):
            yield

    def inspect(root):
        inspected.set()
        return original_inspect(root)

    monkeypatch.setattr(workspace, 'repo_mutation_lock', lock)
    monkeypatch.setattr(workspace, 'inspect_worktree_identity', inspect)
    before = local_snapshot(env.root)
    refresh = None
    try:
        with original_lock(env.repo):
            refresh = asyncio.create_task(asyncio.to_thread(hw.refresh_source, env.root, env.branch, 'main'))
            assert await asyncio.to_thread(attempting.wait, 5), 'refresh never reached the repository lock'
            assert not inspected.is_set(), 'identity inspection ran before obtaining the writer lock'
            assert local_snapshot(env.root) == before
    finally:
        if refresh is not None:
            note = await asyncio.wait_for(refresh, 10)
    assert inspected.is_set() and 'source fast-forwarded' in note
    assert git(env.root, 'rev-parse', 'HEAD') == git(env.repo, 'rev-parse', 'main')


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['rewrite', 'new-collision'])
async def test_skipped_refresh_still_protects_unsynced_remote_work(started, kind):
    env = started
    add_inputs(env, 1)
    rel = 'task/seed.txt' if kind == 'rewrite' else 'task/local-output.txt'
    baseline = env.state.manifest.get(rel)
    (env.root / rel).write_text('new committed worker content\n')
    git(env.root, 'add', rel)
    git(env.root, 'commit', '-qm', 'worker owns this new content')
    remote = Path(env.state.remote_dir)
    (remote / rel).write_text('unsynced remote content\n')
    before = local_snapshot(env.root)
    manifest = dict(env.state.manifest)
    events = await _turn(env.backend, 'continue with existing worker branch')
    assert any(event.type == 'status' and 'source refresh skipped' in event.content for event in events)
    assert any(event.type == 'error' and 'remote WIP conflict' in event.content for event in events), events
    assert local_snapshot(env.root) == before
    assert (remote / rel).read_text() == 'unsynced remote content\n'
    assert len(env.observed) == 1 and env.state.manifest == manifest
    assert env.state.path().exists() and not env.ssh.removed
    if baseline:
        (remote / rel).write_bytes(env.observed[0][rel])
    else:
        (remote / rel).unlink()
    events = await _turn(env.backend, 'retry after explicit remote reconciliation')
    assert not [event.content for event in events if event.type == 'error']
    assert env.observed[-1][rel] == b'new committed worker content\n'
    assert local_snapshot(env.root) == before
    assert env.backend._state.thread_id == env.state.thread_id


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['tracked', 'staged', 'untracked', 'rename'])
async def test_dirty_checkout_skips_optional_ff_and_keeps_local_work(continued, kind):
    env = continued
    files = add_inputs(env, 1)
    if kind == 'untracked':
        (env.root / 'task/untracked.txt').write_text('untracked WIP\n')
    elif kind == 'rename':
        git(env.root, 'mv', 'task/seed.txt', 'task/renamed.txt')
    else:
        (env.root / 'task/seed.txt').write_text('local WIP\n')
        if kind == 'staged':
            git(env.root, 'add', 'task/seed.txt')
            (env.root / 'task/seed.txt').write_text('unstaged WIP over staged WIP\n')
    before = local_snapshot(env.root)
    events = await _turn(env.backend, 'continue with existing task data')
    assert not [event.content for event in events if event.type == 'error']
    notes = [event.content for event in events if event.type == 'status']
    assert any('source refresh skipped' in note and 'local changes' in note
               and 'existing branch' in note and 'not refreshed' in note for note in notes), notes
    assert local_snapshot(env.root) == before
    assert len(env.observed) == 2
    assert not files.keys() & env.observed[-1].keys()
    assert env.observed[-1] == before['files']
    assert env.backend._state.thread_id == env.state.thread_id
    assert not env.ssh.removed


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['ignored-collision', 'operation', 'binding'])
async def test_refresh_refuses_wip_without_upload_or_history_loss(continued, kind):
    env = continued
    files = add_inputs(env, 1)
    if kind == 'ignored-collision':
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
@pytest.mark.parametrize('kind', ['changed', 'missing', 'head-collision', 'collision', 'diverged-collision'])
async def test_refresh_refuses_frozen_input_changes_or_target_collision(continued, kind):
    env = continued
    original = env.root / 'task/original.txt'
    original.write_text('public immutable input\n')
    env.state.input_manifest = {'task/original.txt': hw.sha256_file(original)}
    env.state.save()
    add_inputs(env, 1)
    if kind == 'changed':
        original.write_text('edited original\n')
    elif kind == 'missing':
        original.unlink()
    elif kind == 'head-collision':
        git(env.root, 'add', 'task/original.txt')
        git(env.root, 'commit', '-qm', 'tracked original conflicts with frozen provenance')
    else:
        (env.repo / 'task/original.txt').write_text('target collision\n')
        git(env.repo, 'add', '.')
        git(env.repo, 'commit', '-qm', 'colliding target input')
        if kind == 'diverged-collision':
            (env.root / 'task/worker.txt').write_text('ready worker output\n')
            git(env.root, 'add', 'task/worker.txt')
            git(env.root, 'commit', '-qm', 'worker diverged from base')
    before = original.read_bytes() if original.exists() else None
    head = git(env.root, 'rev-parse', 'HEAD')
    events = await _turn(env.backend, 'continue')
    if kind == 'diverged-collision':
        assert not [event.content for event in events if event.type == 'error']
        assert len(env.observed) == 2
        assert env.observed[-1]['task/original.txt'] == before
        assert env.backend._state.input_manifest == {'task/original.txt': hw.sha256_file(original)}
        assert any(event.type == 'status' and 'source refresh skipped' in event.content for event in events)
    else:
        assert any(event.type == 'error' for event in events)
        assert len(env.observed) == 1
    assert (original.read_bytes() if original.exists() else None) == before
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
