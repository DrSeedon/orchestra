import pytest
from app import db, tm
from tests.test_task_runtime import runtime


def test_public_api_has_one_owner_and_sticky_prefix(runtime):
    a = tm.api_create_task('local-project', 'Laptop', request_key='laptop-request-0001')
    runtime.store.origin = 'V'
    b = tm.api_create_task('local-project', 'VPS', request_key='remote-request-0001')
    assert (a['par'], b['par']) == ('1', 'V-1')
    tm.api_update_task('V-1', title='VPS edited', project='local-project')
    assert runtime.store.get('project', 'V-1')['title'] == 'VPS edited'
    assert tm.api_get_task('1', 'local-project')['title'] == 'Laptop'
    replay = tm.api_create_task('local-project', 'VPS', request_key='remote-request-0001')
    assert replay['id'] == b['id']
    assert tm.api_task_create_status('remote-request-0001', project_id='local-project')['task_id'] == b['id']
    assert tm.api_list_tasks('local-project')['count'] == 2


def test_public_cas_and_commit_linking_publish_to_git(runtime):
    tm.api_create_task('local-project', 'Task')
    identity = tm.resolve_scoped_task_identity('/project', '1')
    result = tm.api_update_task_if_current(identity, status='done')
    assert result['ok']
    assert runtime.store.get('project', '1')['status'] == 'done'
    assert not tm.api_update_task_if_current(identity, status='cancelled')['ok']
    assert tm.link_commits_to_task('1', [{'hash': 'abc', 'message': 'result'}], 'local-project')['added'] == 1
    assert runtime.store.get('project', '1')['git_commits'][0]['hash'] == 'abc'


def test_failed_git_update_rolls_back_sql(runtime, monkeypatch):
    task = tm.api_create_task('local-project', 'Before')
    def fail(*args, **kwargs):
        raise OSError('Git unavailable')
    monkeypatch.setattr(runtime.store, 'update', fail)
    with pytest.raises(OSError):
        tm.api_update_task('1', title='After', project='local-project')
    with db._conn() as connection:
        assert connection.execute('SELECT title FROM tm_tasks WHERE id=?', (task['id'],)).fetchone()[0] == 'Before'


def test_new_project_registration_binds_git_namespace(runtime):
    with db._conn() as connection:
        tm.ensure_project(connection, 'Other', scope='/other')
    task = tm.api_create_task('other', 'Portable project')
    assert runtime.store.get('other', task['par'])['title'] == 'Portable project'


@pytest.mark.parametrize('field,value', [('ref_prefix', 'V'), ('stable_id', 'foreign-task')])
def test_cached_identity_cannot_change_a_different_task(runtime, field, value):
    tm.api_create_task('local-project', 'Local')
    identity = tm.resolve_scoped_task_identity('/project', '1')
    identity[field] = value
    assert not tm.api_update_task_if_current(identity, status='done')['ok']
    assert runtime.store.get('project', '1')['status'] == 'new'
