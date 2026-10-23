"""V-1062: upload-origin raw inputs stay local, read-only and outside squash commits."""
import json
from pathlib import Path

import pytest

from app import hub_workspace as hw, workspace
from tests.test_diff_budget import git_repo, wt_root
from tests.test_hub_workspace import (
    _backend, _turn, _tar_of, _offline_hub_pool, _Entering,
)
from tests.test_merge_worker_v1034 import git

INPUT = 'sources/raw rows.txt'
RAW = 'synthetic original, do not publish\n'


@pytest.fixture
def env(git_repo, wt_root, tmp_path, monkeypatch):
    monkeypatch.setattr(hw, 'STATE_DIR', tmp_path / 'hub-state')
    monkeypatch.setattr(hw, 'known_secret_values', lambda extra=None: [])
    wt = workspace.create_worktree(str(git_repo), 'input-worker', base_branch='main')
    root = Path(wt.path)
    (root / INPUT).parent.mkdir()
    (root / INPUT).write_text(RAW)
    plan = hw.plan_upload(root, known=[])
    state = hw.WorkspaceState(hw.WorkspaceState.new_id(), str(root), '',
                              manifest=dict(plan.manifest), uploaded=True)
    hw.capture_inputs(root, state, plan.manifest)
    state.save()
    (root / 'output.txt').write_text('derived output\n')
    hw.commit_sync(root, ['output.txt'], [], 'V-1062: Derived output')
    return git_repo, root, state


def merge(env):
    repo, root, _ = env
    return workspace.merge_worktree_to_main(str(root), str(repo))


def test_unchanged_input_and_committed_output_merge_preserves_original(env):
    repo, root, state = env
    before = (root / INPUT).stat().st_mtime_ns
    result = merge(env)
    assert result['ok'], result
    assert (repo / 'output.txt').read_text() == 'derived output\n'
    assert not (repo / INPUT).exists()
    assert (root / INPUT).read_text() == RAW
    assert (root / INPUT).stat().st_mtime_ns == before
    assert INPUT not in git(repo, 'ls-tree', '-r', '--name-only', 'HEAD').splitlines()
    assert git(root, 'status', '--porcelain', '--untracked-files=all').strip() == f'?? "{INPUT}"'
    assert hw.WorkspaceState.load(state.ws_id).input_manifest == state.input_manifest


@pytest.mark.parametrize('kind', [
    'tracked', 'staged-output', 'new-output', 'changed-input', 'deleted-input',
    'staged-input', 'committed-input', 'symlink-input', 'parent-symlink',
    'ignored-changed-input', 'changed-after-refresh', 'same-directory-output',
])
def test_merge_refuses_dirty_or_colliding_work_without_losing_data(env, kind):
    repo, root, state = env
    if kind == 'tracked':
        (root / 'README.md').write_text('dirty tracked\n')
    elif kind in {'staged-output', 'new-output', 'same-directory-output'}:
        path = 'sources/new.txt' if kind == 'same-directory-output' else 'new.txt'
        (root / path).write_text('uncommitted output\n')
        if kind == 'staged-output':
            git(root, 'add', path)
    elif kind in {'changed-input', 'ignored-changed-input', 'changed-after-refresh'}:
        (root / INPUT).write_text('changed original\n')
        if kind == 'ignored-changed-input':
            common = Path(git(root, 'rev-parse', '--git-common-dir').strip())
            if not common.is_absolute():
                common = root / common
            (common / 'info/exclude').write_text('sources/\n')
        if kind == 'changed-after-refresh':
            # A later upload's mutable manifest must not authorize an edited input.
            plan = hw.plan_upload(root, known=[])
            hw.capture_inputs(root, state, plan.manifest)
            state.manifest = plan.manifest
            state.save()
    elif kind == 'deleted-input':
        (root / INPUT).unlink()
    elif kind in {'staged-input', 'committed-input'}:
        git(root, 'add', INPUT)
        if kind == 'committed-input':
            git(root, 'commit', '-qm', 'accidentally tracked source')
    elif kind == 'symlink-input':
        (root / INPUT).unlink()
        (root / INPUT).symlink_to('../README.md')
    elif kind == 'parent-symlink':
        (root / 'sources').rename(root / 'moved-sources')
        (root / 'sources').symlink_to('moved-sources', target_is_directory=True)
    before_target = git(repo, 'rev-parse', 'HEAD')
    before_worker = git(root, 'rev-parse', 'HEAD')
    before_status = git(root, 'status', '--porcelain', '--untracked-files=all')
    result = merge(env)
    assert not result['ok'], result
    assert result['commit_point'] == 'not_reached', result
    assert git(repo, 'rev-parse', 'HEAD') == before_target
    assert git(root, 'rev-parse', 'HEAD') == before_worker
    assert git(root, 'status', '--porcelain', '--untracked-files=all') == before_status


@pytest.mark.parametrize('target_path', [INPUT, 'sources', INPUT + '/child.txt'])
def test_target_tree_collisions_refuse_before_reset_can_destroy_inputs(env, target_path):
    repo, root, _ = env
    target = repo / target_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('target committed output\n')
    git(repo, 'add', target_path)
    git(repo, 'commit', '-qm', 'target collision')
    before = git(repo, 'rev-parse', 'HEAD')
    result = merge(env)
    assert not result['ok'], result
    assert 'collision' in result['error']
    assert git(repo, 'rev-parse', 'HEAD') == before
    assert (root / INPUT).read_text() == RAW


def test_without_provenance_an_untracked_file_is_still_refused(env):
    _, _, state = env
    state.path().unlink()
    result = merge(env)
    assert not result['ok'] and 'worker working tree is dirty' in result['error']


def test_existing_live_state_migrates_but_hub_output_is_never_an_input(env):
    _, root, state = env
    (root / 'forgotten-output.txt').write_text('hub output, not committed\n')
    state.manifest['forgotten-output.txt'] = hw.sha256_file(root / 'forgotten-output.txt')
    state.hub_made = ['forgotten-output.txt', 'output.txt']
    data = dict(state.__dict__)
    data.pop('input_manifest')  # exact pre-upgrade on-disk schema
    state.path().write_text(json.dumps(data))
    result = merge(env)
    assert not result['ok'] and 'forgotten-output.txt' in result['error']
    assert hw.WorkspaceState.load(state.ws_id).input_manifest == {INPUT: hw.sha256_file(root / INPUT)}
    (root / 'forgotten-output.txt').unlink()
    assert merge(env)['ok']


@pytest.mark.parametrize('mode', ['rewrite', 'delete', 'ancestor', 'descendant', 'alias'])
def test_sync_refuses_input_mutation_and_collisions_but_commits_outputs(env, tmp_path, mode):
    _, root, state = env
    files = {'README.md': (root / 'README.md').read_bytes(),
             'result.txt': b'valid derived output\n', INPUT: RAW.encode()}
    bad = INPUT
    if mode == 'rewrite':
        files[INPUT] = b'modified raw input\n'
    elif mode == 'delete':
        del files[INPUT]
    else:
        bad = {'ancestor': 'sources', 'descendant': INPUT + '/child',
               'alias': 'sources/./raw rows.txt'}[mode]
        files[bad] = b'colliding output\n'
    result = hw.apply_changes(_tar_of(files, tmp_path), root, state.manifest,
                              known=[], inputs=state.input_manifest)
    assert bad in dict(result.rejected), result
    assert (root / INPUT).read_text() == RAW
    assert INPUT not in result.changed + result.deleted
    sha, failed = hw.commit_sync(root, result.changed, result.deleted, 'V-1062: Safe sync')
    assert sha and not failed
    assert git(root, 'show', '--name-only', '--format=', 'HEAD').strip() == 'result.txt'
    assert INPUT not in git(root, 'ls-files').splitlines()


@pytest.mark.asyncio
async def test_hub_turn_merge_release_and_next_upload_keep_inputs(env, tmp_path, monkeypatch):
    repo, root, old = env
    old.path().unlink()
    def edit(remote):
        assert (remote / INPUT).read_text() == RAW
        (remote / 'output.txt').write_text('hub derived output\n')
    backend, ssh, mc = _backend(root, tmp_path, monkeypatch, edit)
    await _turn(backend, 'derive outputs')
    state = backend._state
    assert state.input_manifest == {INPUT: hw.sha256_file(root / INPUT)}
    assert INPUT not in git(root, 'ls-files').splitlines()
    result = merge(env)
    assert result['ok'], result
    # The same cleanup invoked after merge_worker(continue) releases only hub state.
    from app.merge_operations import _clean_worktree_after_merge
    monkeypatch.setattr('app.backend_hub.MultiCodeClient.from_env', lambda: _Entering(mc))
    monkeypatch.setattr('app.merge_operations.get_session',
                        lambda sid: {'worktree_path': str(root)})
    await _clean_worktree_after_merge({'session_id': 'worker'}, {'git': {'target_branch': 'main'}})
    assert not state.path().exists()
    assert (root / INPUT).read_text() == RAW
    assert not (repo / INPUT).exists()
    await _turn(backend, 'continue the task')
    assert backend._state.ws_id != state.ws_id
    assert (Path(backend._state.remote_dir) / INPUT).read_text() == RAW
    assert backend._state.input_manifest == {INPUT: hw.sha256_file(root / INPUT)}


def test_input_allowance_does_not_bypass_publication_guard(env, tmp_path, monkeypatch):
    from app import forbidden_strings
    _, root, _ = env
    forbidden = tmp_path / 'synthetic-forbidden.txt'
    forbidden.write_text('SYNTHETIC_PUBLICATION_SENTINEL\n')
    monkeypatch.setenv(forbidden_strings.ENV_VAR, str(forbidden))
    (root / 'output.txt').write_text('SYNTHETIC_PUBLICATION_SENTINEL\n')
    git(root, 'add', 'output.txt')
    git(root, 'commit', '-qm', 'V-1062: Unsafe synthetic output')
    result = merge(env)
    assert not result['ok'] and result['code'] == 'FORBIDDEN_STRING', result
    assert (root / INPUT).read_text() == RAW


@pytest.mark.asyncio
async def test_merge_worker_continue_retains_task_and_uploads_original_again(tmp_path, monkeypatch):
    from tests.test_task_tracker_integration import (
        _init_db, _make_git_scope, _save_worker, _prepare_merge,
    )
    from tests.task_seeds import create_task as seed_task
    from app import tm, db
    from app.routes.sessions import execute_merge_session
    from app.merge_operations import _clean_worktree_after_merge
    _init_db()
    repo = _make_git_scope(monkeypatch, tmp_path)
    monkeypatch.setattr(hw, 'STATE_DIR', tmp_path / 'hub-state')
    monkeypatch.setattr(hw, 'known_secret_values', lambda extra=None: [])
    with tm._conn() as conn:
        tm.ensure_project(conn, 'project', scope=str(repo))
        task = seed_task(conn, 'project', 'Input-only hub workflow', par_number=42, status='in_progress')
        conn.execute('UPDATE tm_tasks SET worker_session_id=? WHERE id=?', ('hub-input-worker', task['id']))
    wt = workspace.create_worktree(str(repo), 'hub-input-worker', task_id='42')
    root = Path(wt.path)
    (root / INPUT).parent.mkdir()
    (root / INPUT).write_text(RAW)
    def edit(remote):
        assert (remote / INPUT).read_text() == RAW
        (remote / 'output.txt').write_text('derived from preserved source\n')
    backend, ssh, mc = _backend(root, tmp_path, monkeypatch, edit)
    monkeypatch.setattr('app.backend_hub.MultiCodeClient.from_env', lambda: _Entering(mc))
    await _turn(backend, 'create output')
    state = backend._state
    head = git(root, 'rev-parse', 'HEAD').strip()
    _save_worker(session_id='hub-input-worker', task_id='42', scope=str(repo),
                 worktree_path=wt.path, branch=wt.branch)
    found = _prepare_merge(monkeypatch, session_id='hub-input-worker', scope=str(repo))
    result = await execute_merge_session(
        session_id=found.id, expected_name=found.name, expected_scope=str(repo),
        expected_branch=found.branch, expected_head=head,
        req={'scope': str(repo), 'task_outcome': 'continue', 'merge_schema_version': 2,
             'expected_head': head, 'acceptance_note': 'Verified outputs and read-only input preservation.'},
    )
    assert result['ok'], result
    assert result['task_outcome'] == 'continue'
    assert db.get_session(found.id)['task_id'] == '42'
    assert not db.get_session(found.id)['needs_switch']
    await _clean_worktree_after_merge({'session_id': found.id}, {'git': {'target_branch': 'main'}})
    assert not state.path().exists()
    assert (root / INPUT).read_text() == RAW
    assert not (repo / INPUT).exists()
    await _turn(backend, 'continue the same task')
    assert backend._state.ws_id != state.ws_id
    assert (Path(backend._state.remote_dir) / INPUT).read_text() == RAW
    assert INPUT not in git(root, 'ls-files').splitlines()


@pytest.mark.asyncio
@pytest.mark.parametrize('attempt', ['rewrite', 'delete'])
async def test_rejected_hub_input_is_restored_by_next_upload(env, tmp_path, monkeypatch, attempt):
    _, root, old = env
    old.path().unlink()
    calls = []
    def edit(remote):
        assert (remote / INPUT).read_text() == RAW
        calls.append('turn')
        if len(calls) == 1:
            if attempt == 'rewrite':
                (remote / INPUT).write_text('hub tried to rewrite original\n')
            else:
                (remote / INPUT).unlink()
        (remote / 'output.txt').write_text(f'derived output {len(calls)}\n')
    backend, ssh, mc = _backend(root, tmp_path, monkeypatch, edit)
    events = await _turn(backend, 'first')
    assert any('read-only hub input' in e.content for e in events)
    assert (root / INPUT).read_text() == RAW
    assert INPUT not in backend._state.manifest
    assert INPUT in backend._state.input_manifest
    await _turn(backend, 'restore input and continue')
    assert len(calls) == 2
    assert (Path(backend._state.remote_dir) / INPUT).read_text() == RAW
    assert INPUT not in git(root, 'ls-files').splitlines()
    assert backend._state.manifest[INPUT] == backend._state.input_manifest[INPUT]


def test_missing_readonly_inputs_do_not_weaken_truncated_snapshot_guard(env, tmp_path):
    _, root, state = env
    for i in range(25):
        rel = f'sources/input-{i}.txt'
        (root / rel).write_text('synthetic source\n')
        digest = hw.sha256_file(root / rel)
        state.manifest[rel] = digest
        state.input_manifest[rel] = digest
    result = hw.apply_changes(_tar_of({}, tmp_path), root, state.manifest,
                              known=[], inputs=state.input_manifest)
    assert not result.deleted
    assert (root / 'README.md').is_file()
    assert any('truncated snapshot' in why for _, why in result.rejected)
    assert (root / INPUT).read_text() == RAW


@pytest.mark.parametrize('kind', ['unchanged', 'changed', 'output', 'collision', 'checkout-failure'])
def test_branch_switch_preserves_only_verified_inputs_and_rollback(env, monkeypatch, kind):
    repo, root, state = env
    # Outputs are already committed. A continued task may choose a new branch.
    original_branch = git(root, 'branch', '--show-current').strip()
    original_head = git(root, 'rev-parse', 'HEAD')
    if kind == 'changed':
        (root / INPUT).write_text('changed input\n')
    elif kind == 'output':
        (root / 'new-output.txt').write_text('not committed\n')
    elif kind == 'collision':
        (repo / 'sources').mkdir()
        (repo / INPUT).write_text('colliding target output\n')
        git(repo, 'add', INPUT)
        git(repo, 'commit', '-qm', 'target collision')
    elif kind == 'checkout-failure':
        git(repo, 'branch', 'continued-task', 'main')
        real_git = workspace._git_cmd
        def fail_checkout(args, **kwargs):
            if args == ['git', 'checkout', 'continued-task']:
                import subprocess
                return subprocess.CompletedProcess(args, 1, '', 'injected checkout failure')
            return real_git(args, **kwargs)
        monkeypatch.setattr(workspace, '_git_cmd', fail_checkout)
    result = workspace.switch_worktree_branch(str(root), 'continued-task', 'main', force=True)
    assert result['ok'] == (kind == 'unchanged'), result
    if kind != 'changed':
        assert (root / INPUT).read_text() == RAW
    assert INPUT not in git(root, 'ls-files').splitlines()
    if kind == 'checkout-failure':
        assert result.get('state') != 'rollback_failed', result
        assert 'injected checkout failure' in result['error']
        assert git(repo, 'rev-parse', 'continued-task') == git(repo, 'rev-parse', 'main')
        assert git(root, 'rev-parse', 'HEAD') == original_head
        assert git(root, 'branch', '--show-current').strip() == original_branch


def test_legacy_staged_input_refusal_can_recover_after_unstage(env):
    _, root, state = env
    data = dict(state.__dict__)
    data.pop('input_manifest')
    state.path().write_text(json.dumps(data))
    git(root, 'add', INPUT)
    result = merge(env)
    assert not result['ok'] and 'staged changes' in result['error']
    assert hw.WorkspaceState.load(state.ws_id).input_manifest is None
    git(root, 'reset', '-q', 'HEAD', '--', INPUT)
    assert merge(env)['ok']
    assert (root / INPUT).read_text() == RAW


def test_many_inputs_merge_to_checked_out_parent_branch(env):
    repo, root, state = env
    for i in range(993):
        rel = f'sources/row-{i}.csv'
        (root / rel).write_text(f'synthetic,{i}\n')
        digest = hw.sha256_file(root / rel)
        state.input_manifest[rel] = digest
        state.manifest[rel] = digest
    state.save()
    git(repo, 'checkout', '-b', 'parent-task')
    result = workspace.merge_worktree_to_main(str(root), str(repo), target_branch='parent-task')
    assert result['ok'], result
    assert (repo / 'output.txt').is_file()
    assert not (repo / 'sources').exists()
    assert len(list((root / 'sources').iterdir())) == 994
    assert git(root, 'ls-files', 'sources') == ''


def test_large_raw_inputs_do_not_consume_published_output_budget(env):
    from app.diff_budget import measure_insertion_counts
    _, root, state = env
    (root / INPUT).write_text('synthetic original row\n' * 2500)
    digest = hw.sha256_file(root / INPUT)
    state.input_manifest[INPUT] = state.manifest[INPUT] = digest
    state.save()
    assert measure_insertion_counts(str(root), 'main')[0] == 2501  # WIP default is unchanged
    result = merge(env)
    assert result['ok'], result
    assert result['diff_insertions'] == 1
    assert result['diff_budget_waived'] is False
    assert (root / INPUT).read_text().count('\n') == 2500


@pytest.mark.parametrize('action', ['rewrite', 'delete'])
def test_local_alias_cannot_overwrite_or_delete_original_through_old_manifest(env, tmp_path, action):
    _, root, state = env
    (root / 'alias').symlink_to('sources', target_is_directory=True)
    alias = 'alias/raw rows.txt'
    manifest = {**state.manifest, alias: state.input_manifest[INPUT]}
    files = {INPUT: RAW.encode(), 'README.md': (root / 'README.md').read_bytes(),
             'result.txt': b'valid derived output\n'}
    if action == 'rewrite':
        files[alias] = b'overwrite through local parent symlink\n'
    result = hw.apply_changes(_tar_of(files, tmp_path), root, manifest,
                              known=[], inputs=state.input_manifest)
    assert alias in dict(result.rejected)
    assert (root / INPUT).read_text() == RAW
    assert 'result.txt' in result.changed
    assert alias not in result.changed + result.deleted
