import json
import sqlite3
import uuid
from pathlib import Path

import pytest
from app import db
from app.task_migration import prepare_migration
from app.task_store import TaskStore, TaskConflict
from tests.test_git_task_store import git, identity


@pytest.fixture
def migration_source(tmp_path, monkeypatch):
    database = tmp_path / 'source.db'
    monkeypatch.setattr(db, 'DB_PATH', database)
    db.init_db()
    stable_id = str(uuid.uuid4())
    with db._conn() as connection:
        connection.execute("INSERT INTO tm_projects(id,name,scope,created_at) VALUES('project','Project','/project','then')")
        connection.execute("INSERT INTO tm_tasks(id,project_id,par_number,title,status,created_at,updated_at,completed_at) VALUES(71,'project',1,'SQL title','done','then','later','completed')")
    source = tmp_path / 'source'
    source.mkdir()
    git(source, 'init', '--initial-branch=main')
    identity(source)
    state = {'record_type': 'task.state', 'stable_id': stable_id, 'project_id': 'project',
             'display_number': 1, 'title': 'Canonical title', 'description': '', 'status': 'done',
             'priority': 2, 'price_rub': 0, 'assignee': '', 'created_at': 'then', 'updated_at': 'later',
             'completed_at': 'completed', 'git_commit_refs': [], 'evidence_refs': [],
             'acceptance': {'command': '', 'manifest_paths': [], 'required': False}}
    old_path = source / 'tasks' / 'projects' / 'project' / 'tasks' / stable_id / 'state.json'
    old_path.parent.mkdir(parents=True)
    old_path.write_text(json.dumps(state))
    git(source, 'add', '.')
    git(source, 'commit', '-m', 'Old task history')
    registry = tmp_path / 'registry.json'
    registry.write_text(json.dumps({'entries': [{'scope': '/project', 'canonical_project_id': 'project'}]}))
    return dict(source_db=database, source_repo=source, registry_path=registry,
                destination=tmp_path / 'converted', origin='V')


def test_private_conversion_preserves_ids_history_and_existing_numbers(migration_source, monkeypatch):
    # Disposable clone commits use the test identity, without altering user Git config.
    for key, value in {'GIT_AUTHOR_NAME': 'Test', 'GIT_COMMITTER_NAME': 'Test',
                       'GIT_AUTHOR_EMAIL': 'test@example.invalid', 'GIT_COMMITTER_EMAIL': 'test@example.invalid'}.items():
        monkeypatch.setenv(key, value)
    before = git(migration_source['source_repo'], 'rev-parse', 'HEAD')
    report = prepare_migration(**migration_source)
    target = migration_source['destination']
    store = TaskStore(target / 'tasks', origin='V')
    task = store.get('project', '1')
    assert task['title'] == 'Canonical title'
    assert task['completed_at'] == 'completed'
    assert report['differences'][0]['fields'] == ['title']
    assert store.create('project', 'New VPS', request_key='new')['ref'] == 'V-1'
    with db._conn(target / 'orchestra.db') as connection:
        row = connection.execute('SELECT * FROM tm_tasks').fetchone()
        assert row['id'] == 71 and row['title'] == 'Canonical title' and row['ref_prefix'] == ''
    assert git(migration_source['source_repo'], 'rev-parse', 'HEAD') == before
    with sqlite3.connect(migration_source['source_db']) as connection:
        assert connection.execute('SELECT title FROM tm_tasks').fetchone()[0] == 'SQL title'
    assert not (target / 'tasks' / 'tasks').exists()
    assert 'SQL title' in git(target / 'tasks', 'show', 'HEAD~2:migration-source/sql-tasks.json')
    assert git(target / 'tasks', 'remote') == ''
    with pytest.raises(FileExistsError):
        prepare_migration(**migration_source)


def test_completion_date_survives_later_edits(pair):
    a, _ = pair
    task = a.create('project', 'Done', request_key='done', status='done')
    edited = a.update('project', task['ref'], expected_revision=task['revision'], title='Corrected title')
    assert edited['completed_at'] == task['completed_at']


from tests.test_git_task_store import pair


def test_joined_histories_keep_old_numbers_and_distinct_identities(migration_source, monkeypatch):
    from scripts.join_task_stores import join
    from app.task_runtime import TaskRuntime
    from pathlib import Path
    import uuid
    for key, value in {'GIT_AUTHOR_NAME': 'Test', 'GIT_COMMITTER_NAME': 'Test',
                       'GIT_AUTHOR_EMAIL': 'test@example.invalid', 'GIT_COMMITTER_EMAIL': 'test@example.invalid'}.items():
        monkeypatch.setenv(key, value)
    base = migration_source['destination'].parent
    original = json.loads(next(migration_source['source_repo'].rglob('state.json')).read_text())['stable_id']
    renamed = str(uuid.uuid5(uuid.NAMESPACE_URL, 'vps:'+original))
    mapping = base / 'mapping.json'
    mapping.write_text(json.dumps({'node': 'vps', 'projects': {'project': 'vps-project'},
                                  'identities': {original: renamed}}))
    local_dir, remote_dir = base / 'laptop', base / 'vps'
    prepare_migration(**{**migration_source, 'destination': local_dir, 'origin': ''})
    prepare_migration(**{**migration_source, 'destination': remote_dir, 'mapping_path': mapping})
    common = base / 'common'
    join(local_dir / 'tasks', remote_dir / 'tasks', common)
    store = TaskStore(common, origin='')
    assert {(r['project_id'], r['ref'], r['id']) for r in store.list()} == {
        ('project', '1', original), ('vps-project', '1', renamed)}
    runtime = TaskRuntime(store, local_dir / 'orchestra.db')
    runtime.refresh()
    with db._conn(local_dir / 'orchestra.db') as connection:
        assert connection.execute('SELECT id FROM tm_tasks WHERE stable_id=?', (original,)).fetchone()[0] == 71
        assert connection.execute('SELECT COUNT(*) FROM tm_tasks').fetchone()[0] == 2
