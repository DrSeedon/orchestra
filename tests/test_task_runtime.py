import subprocess
from pathlib import Path

import pytest
import app.db as db
from app.task_runtime import TaskRuntime
from app.task_store import TaskStore


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'runtime.db')
    db.init_db()
    with db._conn() as connection:
        connection.execute("INSERT INTO tm_projects(id,name,scope,created_at,canonical_id) VALUES('local-project','Project','/project','now','project')")
    root = tmp_path / 'tasks'
    subprocess.run(['git','init','--initial-branch=main',str(root)],check=True,capture_output=True)
    subprocess.run(['git','-C',str(root),'config','user.name','Task Test'],check=True)
    subprocess.run(['git','-C',str(root),'config','user.email','test@example.invalid'],check=True)
    store = TaskStore(root,origin='')
    store.initialize()
    return TaskRuntime(store,db.DB_PATH)


def test_origin_numbers_share_one_sqlite_projection(runtime):
    a = runtime.create({'canonical_id':'project'},'Local',request_key='local')
    runtime.store.origin = 'V'
    b = runtime.create({'canonical_id':'project'},'Remote',request_key='remote')
    with db._conn() as connection:
        rows = connection.execute('SELECT task_origin,par_number FROM tm_tasks ORDER BY id').fetchall()
    assert [tuple(r) for r in rows] == [('',1),('V',1)]
    assert a['id'] != b['id']
    db.init_db()  # Reopening schema must not recreate the old number-only constraint.


def test_canonical_commit_survives_projection_failure(runtime,monkeypatch):
    original = runtime.project
    def fail(*args):raise OSError('projection unavailable')
    monkeypatch.setattr(runtime,'project',fail)
    with pytest.raises(OSError):
        runtime.create({'canonical_id':'project'},'Committed',request_key='one')
    monkeypatch.setattr(runtime,'project',original)
    runtime.refresh()
    with db._conn() as connection:
        rows=connection.execute('SELECT * FROM tm_tasks').fetchall()
    assert len(rows)==1 and rows[0]['title']=='Committed'
    replay=runtime.create({'canonical_id':'project'},'Committed',request_key='one')
    assert replay['id']==rows[0]['id']


def test_sqlite_failure_does_not_lose_git_update(runtime):
    row=runtime.create({'canonical_id':'project'},'Before',request_key='one')
    with pytest.raises(ValueError):
        with runtime.operation():
            with db._conn() as connection:
                connection.execute('BEGIN IMMEDIATE')
                connection.execute("UPDATE tm_tasks SET title='After' WHERE id=?",(row['id'],))
                runtime.publish(connection,row['id'])
                raise ValueError('lost SQL commit')
    runtime.refresh()
    with db._conn() as connection:
        assert connection.execute('SELECT title FROM tm_tasks WHERE id=?',(row['id'],)).fetchone()[0]=='After'
