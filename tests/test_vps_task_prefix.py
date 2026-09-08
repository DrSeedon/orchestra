import pytest

@pytest.fixture
def task_db(tmp_path, monkeypatch):
    from app import db, tm
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'db.sqlite')
    db.init_db()
    with tm._conn() as c:
        tm.ensure_project(c, 'project', scope=str(tmp_path))
    return db, tm, str(tmp_path)


def test_prefix_is_persisted_only_for_new_tasks(task_db, monkeypatch):
    db, tm, scope = task_db
    old = tm.api_create_task('project', 'old')
    monkeypatch.setenv('ORCHESTRA_TASK_PREFIX', 'V-')
    new = tm.api_create_task('project', 'new')
    assert old['par'] == '1'
    assert new['par'] == 'V-2'
    assert tm.api_get_task('1', 'project')['title'] == 'old'
    assert tm.api_get_task('V-2', 'project')['title'] == 'new'
    with pytest.raises(ValueError):
        tm.resolve_scoped_task_identity(scope, '2')
    with pytest.raises(ValueError):
        tm.resolve_scoped_task_identity(scope, 'V-1')
    identity = tm.resolve_scoped_task_identity(scope, 'V-2')
    assert identity['ref_prefix'] == 'V'
    monkeypatch.delenv('ORCHESTRA_TASK_PREFIX')
    assert tm.api_get_task('V-2', 'project')['par'] == 'V-2'
    assert tm.create_task_for_scope(scope, 'local')['par'] == '3'


def test_git_preserves_node_prefix_and_keeps_legacy_aliases():
    from app.workspace import _normalize_task_id, _leading_task_refs
    assert _normalize_task_id('V-42') == 'V-42'
    assert _normalize_task_id('PAR-42') == '42'
    assert _leading_task_refs('V-42, #42: integrate') == ['V-42', '42']
    assert _leading_task_refs('refactor: use V-42 elsewhere') == []


@pytest.mark.asyncio
async def test_prefixed_assignment_reaches_real_merge(tmp_path, monkeypatch):
    import subprocess
    import uuid
    from pathlib import Path
    from app import tm, db, workspace
    import app.merge_operations as ops
    from tests.test_task_tracker_integration import _init_db, _make_git_scope, _save_worker, _prepare_merge
    _init_db()
    monkeypatch.setenv('ORCHESTRA_TASK_PREFIX', 'V-')
    repo = _make_git_scope(monkeypatch, tmp_path)
    scope = str(repo)
    with tm._conn() as c:
        tm.ensure_project(c, 'project', scope=scope)
        task = tm.create_task(c, 'project', 'VPS result', par_number=42, status='in_progress')
        c.execute("UPDATE tm_tasks SET worker_session_id='v-worker' WHERE id=?", (task['id'],))
    tree = workspace.create_worktree(scope, 'v-worker', task_id='V-42')
    assert tree.branch == 'task-V-42/v-worker'
    Path(tree.path, 'work.py').write_text('VALUE = 42\n')
    subprocess.run(['git','add','work.py'], cwd=tree.path, check=True)
    subprocess.run(['git','commit','-qm','V-42: deliver'], cwd=tree.path, check=True)
    head = subprocess.check_output(['git','rev-parse','HEAD'], cwd=tree.path, text=True).strip()
    _save_worker(session_id='v-worker', task_id='V-42', scope=scope, worktree_path=tree.path, branch=tree.branch)
    _prepare_merge(monkeypatch, session_id='v-worker', scope=scope)
    db.task_run_receipt_open(session_id='v-worker', worker_name='v-worker', scope=scope, task_id='V-42', task_stable_id='v-task')
    monkeypatch.setattr(ops, 'ensure_operation_runner', lambda *_: None)
    result, status = await ops.accept_merge_operation(
        operation_id=str(uuid.uuid4()), name='v-worker', scope=scope,
        expected_head=head, acceptance_note='Inspected result', accepting_actor='owner',
        task_outcome='complete', merge_schema_version=2,
    )
    assert status == 202, str(result)
    await ops._run_operation(result['operation_id'])
    final = ops.get_operation_result(result['operation_id'])
    assert final['operation_state'] == 'SUCCEEDED', str(final)
    assert tm.api_get_task('V-42', 'project')['status'] == 'done'


from tests.test_task_par_collision_406 import canonical_tasks


def test_prefix_through_canonical_facade_and_replay(canonical_tasks, monkeypatch):
    tm, store, database = canonical_tasks
    monkeypatch.setenv('ORCHESTRA_TASK_PREFIX', 'V-')
    key = 'prefix-request-000001'
    result = tm.api_create_task('orchestra', 'prefixed', request_key=key)
    assert result['par'] == 'V-1', result
    assert next(iter(store._states().values()))['ref_prefix'] == 'V'
    assert store.task_get('1', project='orchestra')['ref_prefix'] == 'V'
    assert tm.api_create_task('orchestra', 'prefixed', request_key=key)['par'] == 'V-1'
    assert tm.api_get_task('V-1', 'orchestra')['par'] == 'V-1'
    assert tm.api_list_tasks('orchestra')['tasks'][0]['par'] == 'V-1'
    changed = tm.api_update_task('V-1', title='renamed', project='orchestra')
    assert changed['par'] == 'V-1'
    assert store.task_get('1', project='orchestra')['title'] == 'renamed'


def test_ready_publication_and_restart_preserve_prefixed_assignment(task_db, monkeypatch):
    from app.session import AgentSession
    db, tm, scope = task_db
    monkeypatch.setenv('ORCHESTRA_TASK_PREFIX', 'V-')
    created = tm.api_create_task('project', 'spawn')
    identity = tm.resolve_scoped_task_identity(scope, created['par'])
    session = AgentSession(id='published', name='published', scope=scope, cwd=scope,
                           task_id=created['par'], branch='task-V-1/published')
    db.publish_ready_session(session._to_db_dict(), identity)
    db.init_db()
    with db._conn() as c:
        rows = c.execute("SELECT task_id,status FROM review_receipts WHERE subject_kind='task_run' AND session_id='published'").fetchall()
    assert [tuple(row) for row in rows] == [('V-1', 'requested')]
    assert tm.resolve_scoped_task_identity(scope, 'V-1')['ref_prefix'] == 'V'


def test_foreign_node_number_is_unresolved_not_linked_to_local_task(task_db):
    db, tm, scope = task_db
    local = tm.api_create_task('project', 'local')
    assert local['par'] == '1'
    result = tm.resolve_scoped_task_identities(scope, ['V-1', '1'], skip_unknown=True)
    assert result['canonical_refs'] == ['V-1', '1']
    assert result['unresolved_refs'] == ['V-1']
    assert [task['id'] for task in result['tasks']] == [local['id']]


def test_usage_links_the_full_prefixed_reference(task_db, monkeypatch):
    from datetime import datetime, timezone
    from tests.test_usage_analytics import _seed_session
    from app.usage_analytics import _task_summary
    db, tm, scope = task_db
    monkeypatch.setenv('ORCHESTRA_TASK_PREFIX', 'V-')
    created = tm.api_create_task('project', 'completed', status='done')
    now = datetime.now(timezone.utc).isoformat()
    with db._conn() as c:
        _seed_session(c, 'cost-worker', 'gpt-5.6-sol', 'codex')
        c.execute('UPDATE tm_tasks SET completed_at=? WHERE id=?', (now, created['id']))
        c.execute("INSERT INTO turn_usage(event_id,ts,session_id,scope,task_id,runtime,model,ok,stop_reason,cost_usd,input_tokens,output_tokens,cache_read_tokens,cache_create_tokens) VALUES (?,?,?,?,?,'codex','gpt-5.6-sol',1,'end_turn',1,1,1,0,0)",
                  ('v-cost', now, 'cost-worker', scope, created['par']))
        assert _task_summary(c, '-1 days')['linked_completed_tasks'] == 1
