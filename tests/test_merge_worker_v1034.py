"""V-1034: squash receipts, evidence budget, safe dirty target and acceptance."""
import copy
import json
import subprocess
from pathlib import Path
from tests.test_work_acceptance import work

import pytest

from tests.test_diff_budget import git_repo, wt_root, _commit_in_worktree


def git(repo, *args):
    return subprocess.run(['git', *args], cwd=repo, text=True, capture_output=True, check=True).stdout


def worker(git_repo, wt_root, path='feature.txt'):
    return _commit_in_worktree(git_repo, wt_root, 'worker', path, 'feature\n', 'V-1034: WIP unfinished')


def test_squash_uses_last_commit_subject(git_repo, wt_root):
    from app.workspace import merge_worktree_to_main
    wt = worker(git_repo, wt_root)
    (Path(wt.path) / 'feature.txt').write_text('finished\n')
    git(wt.path, 'add', '.')
    git(wt.path, 'commit', '-m', 'V-1034: Finished feature')
    result = merge_worktree_to_main(wt.path, str(git_repo))
    assert result['ok'], result
    assert git(git_repo, 'log', '-1', '--format=%s').strip() == 'V-1034: Finished feature'


def test_squash_uses_acceptance_first_line_with_validated_refs(git_repo, wt_root):
    from app.workspace import merge_worktree_to_main
    wt = worker(git_repo, wt_root)
    result = merge_worktree_to_main(
        wt.path, str(git_repo), expected_candidate_refs=['V-1034'],
        validated_task_refs=['V-1034'], primary_task_ref='V-1034',
        operation_id='receipt-id', acceptance_note='V-1034: Accepted the finished feature\nChecks passed.',
    )
    assert result['ok'], result
    assert git(git_repo, 'log', '-1', '--format=%s').strip() == 'V-1034: Accepted the finished feature'
    assert 'Orchestra-Operation: receipt-id' in git(git_repo, 'log', '-1', '--format=%B')


def test_evidence_excluded_and_reported_but_lookalike_counts(git_repo, wt_root):
    from app.workspace import merge_worktree_to_main
    from app.diff_budget import measure_insertion_counts, measure_insertions
    wt = _commit_in_worktree(git_repo, wt_root, 'evidence', '.orchestra/tasks/V-1034/copied.patch', 'x\n' * 2200, 'V-1034: Evidence')
    (Path(wt.path) / 'feature.txt').write_text('x\n' * 2000)
    git(wt.path, 'add', '.')
    git(wt.path, 'commit', '-m', 'V-1034: At the code budget')
    assert measure_insertion_counts(wt.path, 'main') == (2000, 2200)
    assert measure_insertions(wt.path, 'main') == 2000
    result = merge_worktree_to_main(wt.path, str(git_repo))
    assert result['ok'], result
    assert result['diff_insertions'] == 2000
    assert result['diff_excluded_insertions'] == 2200
    (Path(wt.path) / '.orchestra/tasks/V-1034/untracked.txt').write_text('x\n' * 17)
    (Path(wt.path) / '.orchestra/tasks-lookalike').write_text('x\n' * 2001)
    assert measure_insertion_counts(wt.path, 'main') == (2001, 17)


def test_budget_counts_rename_additions_at_destination(git_repo, wt_root):
    from app.diff_budget import measure_insertion_counts
    evidence = git_repo / '.orchestra/tasks/V-1034/evidence.txt'
    evidence.parent.mkdir(parents=True)
    evidence.write_text('x\n' * 2001)
    git(git_repo, 'add', '.')
    git(git_repo, 'commit', '-m', 'evidence base')
    wt = worker(git_repo, wt_root)
    git(wt.path, 'mv', '.orchestra/tasks/V-1034/evidence.txt', 'code.txt')
    with (Path(wt.path) / 'code.txt').open('a') as stream:
        stream.write('new code line\n')
    git(wt.path, 'commit', '-m', 'move evidence into code')
    assert measure_insertion_counts(wt.path, 'main') == (2, 0)


@pytest.mark.parametrize('staged', [False, True])
def test_unrelated_dirty_target_survives_and_stays_out_of_commit(git_repo, wt_root, staged):
    from app.workspace import merge_worktree_to_main
    wt = worker(git_repo, wt_root)
    readme = git_repo / 'README.md'
    readme.write_text('another session staged\n')
    if staged:
        git(git_repo, 'add', 'README.md')
        readme.write_text('another session unstaged\n')
    before = git(git_repo, 'status', '--porcelain')
    index_before = git(git_repo, 'show', ':README.md')
    result = merge_worktree_to_main(wt.path, str(git_repo))
    assert result['ok'], result
    assert readme.read_text() == ('another session unstaged\n' if staged else 'another session staged\n')
    assert git(git_repo, 'status', '--porcelain') == before
    assert git(git_repo, 'show', ':README.md') == index_before
    assert git(git_repo, 'show', 'HEAD:README.md') == '# test\n'
    assert git(git_repo, 'show', 'HEAD:feature.txt') == 'feature\n'
    assert git(git_repo, 'stash', 'list') == ''


@pytest.mark.parametrize('path', ['feature.txt', 'folder', 'odd\tfile.txt'])
def test_overlapping_dirty_target_refused_with_paths(git_repo, wt_root, path):
    from app.workspace import merge_worktree_to_main
    wt = worker(git_repo, wt_root, 'folder/child.txt' if path == 'folder' else path)
    (git_repo / path).write_text('do not overwrite\n')
    before = git(git_repo, 'rev-parse', 'HEAD')
    result = merge_worktree_to_main(wt.path, str(git_repo))
    assert not result['ok']
    assert 'target working tree is dirty' in result['error']
    assert path in result['error']
    assert git(git_repo, 'rev-parse', 'HEAD') == before
    assert (git_repo / path).read_text() == 'do not overwrite\n'


def test_dirty_target_commit_failure_preserves_index_and_content(git_repo, wt_root):
    from app.workspace import merge_worktree_to_main
    wt = worker(git_repo, wt_root)
    readme = git_repo / 'README.md'
    readme.write_text('staged\n')
    git(git_repo, 'add', 'README.md')
    readme.write_text('unstaged\n')
    before = git(git_repo, 'rev-parse', 'HEAD')
    status = git(git_repo, 'status', '--porcelain')
    hook = git_repo / '.git/hooks/pre-commit'
    hook.write_text('#!/bin/sh\nexit 1\n')
    hook.chmod(0o755)
    result = merge_worktree_to_main(wt.path, str(git_repo))
    assert result['state'] == 'failed', result
    assert result['commit_point'] == 'rolled_back'
    assert git(git_repo, 'rev-parse', 'HEAD') == before
    assert git(git_repo, 'show', ':README.md') == 'staged\n'
    assert readme.read_text() == 'unstaged\n'
    assert git(git_repo, 'status', '--porcelain') == status
    assert not (git_repo / 'feature.txt').exists()


@pytest.mark.parametrize('note', ['', ' ', 'placeholder', '-', 'tbd', ' TBD ', 'x' * 14])
def test_acceptance_refuses_empty_short_and_placeholder(note):
    from app.merge_operations import acceptance_input_error
    assert 'acceptance_note' in acceptance_input_error('a' * 40, note)


@pytest.mark.parametrize('sha', ['', 'abcdef', 'a' * 39, 'a' * 41, 'z' * 40])
def test_acceptance_requires_full_sha(sha):
    from app.merge_operations import acceptance_input_error
    assert acceptance_input_error(sha, 'Accepted after checking the diff') == 'expected_head must be the full 40-character SHA from worker_wip'


def test_acceptance_allows_boundary_and_full_sha():
    from app.merge_operations import acceptance_input_error
    assert acceptance_input_error('a' * 40, 'Accepted: done!!') == ''


def receipt(state='SUCCEEDED'):
    return {
        'operation_id': 'operation', 'operation_state': state, 'commit_point': 'REACHED',
        'git': {'target_after': 'b' * 40, 'commits_merged': 2, 'worker_branch': 'task-V-1034/worker',
                'diff_insertions': 20, 'diff_excluded_insertions': 800},
        'test_gate': {'status': 'FAILED', 'failed_tests': ['tests/test_x.py::test_failure'],
                      'passed_tests': ['passing'] * 1000, 'output': 'large log' * 10000,
                      'mutation_gate': {'status': 'SKIPPED', 'reason': 'tests_failed', 'output': 'more' * 10000}},
        'admission': {'long': 'details' * 10000},
        'next_action': {'code': 'NONE', 'message': 'Done'},
    }


def test_compact_receipt_retains_only_failure_ids_and_required_fields():
    from app.mcp_stdio import _merge_tool_result
    full = receipt()
    original = copy.deepcopy(full)
    result = _merge_tool_result(full).structuredContent['result']
    assert result['operation_state'] == 'SUCCEEDED'
    assert result['git']['target_after'] == 'b' * 40
    assert result['git']['commits_merged'] == 2
    assert result['git']['diff_excluded_insertions'] == 800
    assert result['test_gate'] == {'status': 'FAILED', 'reason': '', 'failed_tests': ['tests/test_x.py::test_failure']}
    assert result['mutation_gate']['status'] == 'SKIPPED'
    assert result['next_action'] == full['next_action']
    assert len(json.dumps(result)) < 2000
    assert full == original
    assert _merge_tool_result(full, verbose=True).structuredContent['result'] == full


@pytest.mark.asyncio
async def test_public_merge_worker_verbose_is_presentation_only(monkeypatch):
    import app.mcp_stdio as mcp
    bodies = []
    async def api(method, path, **kwargs):
        bodies.append(kwargs.get('json'))
        return {'result': receipt()}
    monkeypatch.setattr(mcp, '_api', api)
    compact = await mcp.merge_worker('worker', operation_id='operation')
    verbose = await mcp.merge_worker('worker', operation_id='operation', verbose=True)
    assert 'output' not in compact.structuredContent['result']['test_gate']
    assert verbose.structuredContent['result']['test_gate']['output'] == receipt()['test_gate']['output']
    assert bodies[0] == bodies[1]


@pytest.mark.asyncio
@pytest.mark.parametrize('note', ['', 'placeholder', 'tbd', '-', 'Too short'])
async def test_acceptance_is_enforced_before_operation_creation(work, note):
    from tests.test_work_acceptance import submit
    result, status = await submit(work, acceptance_note=note)
    assert status == 409, result
    assert result['error']['code'] == 'WORK_ACCEPTANCE_REQUIRED'
    with work[0]._conn() as conn:
        assert conn.execute('SELECT count(*) FROM merge_operations').fetchone()[0] == 0


@pytest.mark.asyncio
async def test_short_sha_is_refused_before_operation_creation(work):
    from tests.test_work_acceptance import submit
    result, status = await submit(work, expected_head=work[3]('sid')['worker_head'][:12])
    assert status == 409, result
    assert result['error']['message'] == 'expected_head must be the full 40-character SHA from worker_wip'


@pytest.mark.asyncio
async def test_legacy_operation_replay_does_not_require_new_acceptance(monkeypatch):
    import uuid
    from app import merge_operations as operations
    key = str(uuid.uuid4())
    request = operations.normalize_request(name='worker', scope='scope', target='main')
    stored = {'operation_id': key, 'operation_state': 'FAILED'}
    monkeypatch.setattr(operations, 'get_operation_record', lambda _: {
        'request_hash': operations.request_hash(request), 'state': 'FAILED',
        'result': stored, 'finalization_stage': '',
    })
    monkeypatch.setattr(operations, '_replay_drift', lambda _: None)
    result, status = await operations.accept_merge_operation(operation_id=key, name='worker', scope='scope', target='main')
    assert status == 200
    assert result == stored


def test_unrelated_untracked_target_is_preserved(git_repo, wt_root):
    from app.workspace import merge_worktree_to_main
    wt = worker(git_repo, wt_root)
    local = git_repo / 'notes/other-session.md'
    local.parent.mkdir()
    local.write_text('private work\n')
    result = merge_worktree_to_main(wt.path, str(git_repo))
    assert result['ok'], result
    assert local.read_text() == 'private work\n'
    assert git(git_repo, 'status', '--porcelain') == '?? notes/\n'
    assert 'notes/other-session.md' not in git(git_repo, 'ls-tree', '-r', '--name-only', 'HEAD')


def test_dirty_rename_source_overlaps_worker(git_repo, wt_root):
    from app.workspace import merge_worktree_to_main
    wt = worker(git_repo, wt_root, 'README.md')
    git(git_repo, 'mv', 'README.md', 'renamed.md')
    before = git(git_repo, 'status', '--porcelain', '-z')
    result = merge_worktree_to_main(wt.path, str(git_repo))
    assert not result['ok']
    assert 'README.md' in result['error']
    assert git(git_repo, 'status', '--porcelain', '-z') == before


def test_budget_counts_survive_operation_normalization():
    from app.merge_operations import normalize_merge_result
    raw = {'ok': True, 'state': 'merged', 'commit_point': 'target_committed',
           'target_before': 'a' * 40, 'target_after': 'b' * 40, 'commits_merged': 1,
           'diff_insertions': 2000, 'diff_excluded_insertions': 2200}
    result = normalize_merge_result('operation', raw, {})
    assert result['git']['diff_insertions'] == 2000
    assert result['git']['diff_excluded_insertions'] == 2200


@pytest.mark.parametrize('status', ['PASSED', 'FAILED', 'SKIPPED'])
def test_compact_mutation_gate_status_and_only_failures(status):
    from app.mcp_stdio import _merge_tool_result
    full = receipt()
    full['test_gate']['mutation_gate'] = {
        'status': status, 'failed_tests': ['tests/test_x.py::test_mutant'],
        'passed_tests': ['passing'], 'output': 'long log' * 1000,
    }
    compact = _merge_tool_result(full).structuredContent['result']['mutation_gate']
    assert compact['status'] == status
    assert compact['failed_tests'] == (['tests/test_x.py::test_mutant'] if status == 'FAILED' else [])
    assert 'output' not in compact
    assert 'passed_tests' not in compact


def test_dirty_target_gitignore_union_preserves_staged_work(git_repo, wt_root):
    from app.workspace import merge_worktree_to_main
    (git_repo / '.gitignore').write_text('base\n')
    git(git_repo, 'add', '.gitignore')
    git(git_repo, 'commit', '-m', 'ignore base')
    wt = worker(git_repo, wt_root)
    (Path(wt.path) / '.gitignore').write_text('base\nworker\n')
    git(wt.path, 'add', '.gitignore')
    git(wt.path, 'commit', '-m', 'V-1034: worker ignores')
    (git_repo / '.gitignore').write_text('base\nmain\n')
    git(git_repo, 'add', '.gitignore')
    git(git_repo, 'commit', '-m', 'main ignores')
    (git_repo / 'README.md').write_text('other staged work\n')
    git(git_repo, 'add', 'README.md')
    result = merge_worktree_to_main(wt.path, str(git_repo))
    assert result['ok'], result
    assert (git_repo / '.gitignore').read_text() == 'base\nmain\nworker\n'
    assert git(git_repo, 'show', ':README.md') == 'other staged work\n'
    assert git(git_repo, 'show', 'HEAD:README.md') == '# test\n'


@pytest.mark.asyncio
async def test_session_execution_forwards_acceptance_headline(tmp_path, monkeypatch):
    from tests.test_task_tracker_integration import _commit_file, _init_db, _make_git_scope, _prepare_merge, _save_worker
    from tests.task_seeds import create_task as seed_task
    from app.routes.sessions import execute_merge_session
    from app import tm, workspace
    _init_db()
    repo = _make_git_scope(monkeypatch, tmp_path)
    scope = str(repo)
    with tm._conn() as conn:
        tm.ensure_project(conn, 'project', scope=scope)
        task = seed_task(conn, 'project', 'Pinned work', par_number=42, status='in_progress')
        conn.execute('UPDATE tm_tasks SET worker_session_id=? WHERE id=?', ('worker-1034', task['id']))
    tree = workspace.create_worktree(scope, 'worker-1034', task_id='42')
    head = _commit_file(tree.path, 'work.py', '#42: WIP result shown to parent')
    _save_worker(session_id='worker-1034', task_id='42', scope=scope, worktree_path=tree.path, branch=tree.branch)
    found = _prepare_merge(monkeypatch, session_id='worker-1034', scope=scope)
    result = await execute_merge_session(
        session_id=found.id, expected_name=found.name, expected_scope=scope,
        expected_branch=found.branch, expected_head=head,
        req={'scope': scope, 'task_outcome': 'continue', 'merge_schema_version': 2,
             'expected_head': head, 'acceptance_note': 'Accepted the finished feature\nDiff and tests reviewed.'},
    )
    assert result['ok'], result
    assert git(repo, 'log', '-1', '--format=%s').strip() == '#42: Accepted the finished feature'


@pytest.mark.parametrize('code', ['TEST_GATE_FAILED', 'TEST_GATE_INCONCLUSIVE', 'TEST_MUTATION_GATE_FAILED'])
def test_compact_gate_error_does_not_echo_logs(code):
    from app.mcp_stdio import _merge_tool_result
    full = receipt('FAILED')
    full['error'] = {'code': code, 'message': 'RAW_OUTPUT' * 10000, 'details': {'output': 'RAW_OUTPUT' * 10000}}
    compact = _merge_tool_result(full)
    assert compact.isError
    assert 'RAW_OUTPUT' not in compact.model_dump_json()
    assert compact.structuredContent['result']['error']['code'] == code
