"""Two offline writers, native Git synchronization and per-record CAS."""
import json
import subprocess
from pathlib import Path

import pytest
from app.task_store import TaskStore, TaskConflict


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def identity(root):
    git(root, 'config', 'user.name', 'Task Store Test')
    git(root, 'config', 'user.email', 'tasks@example.invalid')


@pytest.fixture
def pair(tmp_path):
    hub = tmp_path / 'hub.git'
    subprocess.run(['git', 'init', '--bare', '--initial-branch=main', str(hub)], check=True, capture_output=True)
    local = tmp_path / 'local'
    subprocess.run(['git', 'clone', str(hub), str(local)], check=True, capture_output=True)
    identity(local)
    a = TaskStore(local, origin='')
    a.initialize()
    git(local, 'push', '-u', 'origin', 'main')
    remote = tmp_path / 'vps'
    subprocess.run(['git', 'clone', str(hub), str(remote)], check=True, capture_output=True)
    identity(remote)
    return a, TaskStore(remote, origin='V')


def test_offline_counters_and_git_merge_keep_both_tasks(pair):
    a, b = pair
    first = a.create('project', 'Laptop work', request_key='laptop-request')
    second = b.create('project', 'VPS work', request_key='vps-request')
    assert first['ref'] == '1'
    assert second['ref'] == 'V-1'
    assert first['id'] != second['id']
    a.sync()
    b.sync()
    a.sync()
    for store in (a, b):
        assert {(x['ref'], x['title']) for x in store.list('project')} == {('1', 'Laptop work'), ('V-1', 'VPS work')}
        assert store.get('project', 'V-1')['id'] == second['id']
    assert not list(a.root.rglob('current-head.json'))
    assert not list(a.root.rglob('pending-generation.json'))
    assert not list(a.root.glob('*.db'))


def test_idempotent_create_after_edit_and_conflicting_reuse(pair):
    a, _ = pair
    created = a.create('project', 'Original', request_key='same')
    a.update('project', '1', expected_revision=created['revision'], title='Edited')
    replay = a.create('project', 'Original', request_key='same')
    assert replay['id'] == created['id']
    assert replay['title'] == 'Edited'
    assert len(a.list('project')) == 1
    with pytest.raises(TaskConflict):
        a.create('project', 'Another', request_key='same')


def test_stale_revision_cannot_overwrite_task(pair):
    a, _ = pair
    first = a.create('project', 'Original', request_key='one')
    a.update('project', '1', expected_revision=first['revision'], status='in_progress')
    with pytest.raises(TaskConflict):
        a.update('project', '1', expected_revision=first['revision'], title='Stale')
    assert a.get('project', '1')['status'] == 'in_progress'


def test_conflicting_offline_updates_stop_sync_without_discarding_commits(pair):
    a, b = pair
    task = a.create('project', 'Original', request_key='one')
    a.sync(); b.sync()
    a.update('project', '1', expected_revision=task['revision'], title='Local change')
    b.update('project', '1', expected_revision=task['revision'], title='Remote change')
    local_head = git(a.root, 'rev-parse', 'HEAD')
    remote_head = git(b.root, 'rev-parse', 'HEAD')
    a.sync()
    with pytest.raises(TaskConflict):
        b.sync()
    assert git(b.root, 'rev-parse', 'HEAD') == remote_head
    assert git(b.root, 'merge-base', '--is-ancestor', local_head, 'origin/main') == ''
    assert b.get('project', '1')['title'] == 'Remote change'


def test_sync_validates_references_and_does_not_silently_renumber(pair):
    a, b = pair
    task = a.create('project', 'Original', request_key='one')
    a.sync(); b.sync()
    assert b.get('project', '#1')['ref'] == '1'
    assert b.create('project', 'New VPS task', request_key='two')['ref'] == 'V-1'
    with pytest.raises(ValueError):
        a.update('project', '1', expected_revision=task['revision'], origin='V')


def test_uncommitted_task_change_is_not_overwritten(pair):
    a, _ = pair
    task = a.create('project', 'Original', request_key='one')
    path = next((a.root / 'projects').rglob('*.json'))
    data = json.loads(path.read_text()); data['title'] = 'Manual change'
    path.write_text(json.dumps(data))
    with pytest.raises(TaskConflict):
        a.update('project', '1', expected_revision=task['revision'], title='Overwrite')
    assert 'Manual change' in path.read_text()


def test_lost_commit_acknowledgement_is_replayed_once(pair, monkeypatch):
    a, _ = pair
    original = a._git
    def lost_ack(*args, **kwargs):
        result = original(*args, **kwargs)
        if args[0] == 'commit':
            monkeypatch.setattr(a, '_git', original)
            raise TaskConflict('lost acknowledgement')
        return result
    monkeypatch.setattr(a, '_git', lost_ack)
    with pytest.raises(TaskConflict, match='lost acknowledgement'):
        a.create('project', 'Accepted task', request_key='lost')
    recovered = a.create('project', 'Accepted task', request_key='lost')
    assert recovered['ref'] == '1'
    assert len(a.list('project')) == 1


@pytest.mark.parametrize('damage', ['delete', 'renumber', 'invalid'])
def test_invalid_remote_cannot_advance_local_head(pair, damage):
    a, b = pair
    task = a.create('project', 'Original', request_key='one')
    a.sync(); b.sync()
    before = a.head
    path = b._path(task)
    if damage == 'delete':
        path.unlink()
    else:
        record = json.loads(path.read_text())
        record['number' if damage == 'renumber' else 'status'] = 7 if damage == 'renumber' else 'nonsense'
        path.write_text(json.dumps(record))
    git(b.root, 'add', '-A')
    git(b.root, 'commit', '-m', 'Manual damaged task edit')
    git(b.root, 'push', 'origin', 'main')
    with pytest.raises((TaskConflict, ValueError)):
        a.sync()
    assert a.head == before
    assert a.get('project', '1')['id'] == task['id']
    assert git(a.root, 'status', '--porcelain') == ''


def test_creation_retry_preserves_identity_after_node_prefix_changes(pair):
    a, _ = pair
    task = a.create('project', 'Accepted before prefix change', request_key='stable-request')
    a.origin = 'V'
    replay = a.create('project', 'Accepted before prefix change', request_key='stable-request')
    assert replay['id'] == task['id'] and replay['ref'] == '1'
    assert a.create('project', 'New VPS task', request_key='new-request')['ref'] == 'V-1'


def test_remote_project_symlink_cannot_redirect_task_writes(pair, tmp_path):
    a, b = pair
    outside = tmp_path / 'outside'
    (outside / 'tasks').mkdir(parents=True)
    (b.root / 'projects').mkdir()
    (b.root / 'projects' / 'foreign').symlink_to(outside, target_is_directory=True)
    git(b.root, 'add', 'projects')
    git(b.root, 'commit', '-m', 'Invalid project link')
    git(b.root, 'push', 'origin', 'main')
    head = a.head
    with pytest.raises(TaskConflict, match='symlinks'):
        a.sync()
    assert a.head == head
    with pytest.raises(TaskConflict, match='symlinks'):
        b.create('foreign', 'Must stay inside the repository', request_key='unsafe')
    assert not list((outside / 'tasks').iterdir())
