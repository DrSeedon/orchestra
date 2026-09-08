"""One Git task owner and one local projection, with no knowledge-index dependency."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import json
import os
import sqlite3
import threading

from app import db
from app.task_refs import task_ref
from app.task_store import TaskStore, TaskConflict


_ACTIVE: TaskRuntime | None = None


class TaskRuntime:
    def __init__(self, store: TaskStore, database: Path):
        self.store = store
        self.database = Path(database)
        self._operation = threading.local()

    @contextmanager
    def operation(self):
        # One lock order for every task operation: Git owner, then SQLite writer.
        with self.store._lock():
            depth = getattr(self._operation, 'depth', 0)
            if not depth:
                self.refresh()
            self._operation.depth = depth + 1
            try:
                yield self
            finally:
                self._operation.depth = depth

    def refresh(self):
        with self.store._lock():
            self.store._ready()
            head = self.store.head
            with db._conn(self.database) as connection:
                meta = connection.execute('SELECT git_head FROM task_projection_meta WHERE singleton=1').fetchone()
                if meta and meta[0] == head:
                    return
                records = self.store.list()
                ids = {r['id'] for r in records}
                previous = connection.execute('SELECT stable_id FROM tm_tasks').fetchall()
                if any(not r[0] for r in previous):
                    raise TaskConflict('task projection contains unmigrated rows')
                if any(r[0] not in ids for r in previous):
                    raise TaskConflict('Git removed task history; restore the task record or cancel it explicitly')
                connection.execute('BEGIN IMMEDIATE')
                for record in records:
                    self.project(connection, record, head)
                self.seal(connection, head)

    def project(self, connection: sqlite3.Connection, record: dict, head: str) -> dict:
        rows = connection.execute('SELECT * FROM tm_projects WHERE canonical_id=?', (record['project_id'],)).fetchall()
        if not rows:
            canonical_id = record['project_id']
            local_id = 'git:' + canonical_id
            from app.tm import _generate_prefix
            connection.execute(
                "INSERT INTO tm_projects(id,name,prefix,scope,created_at,canonical_id) VALUES(?,?,?,NULL,?,?)",
                (local_id, canonical_id, _generate_prefix(connection, local_id), record['created_at'], canonical_id))
            rows = connection.execute('SELECT * FROM tm_projects WHERE id=?', (local_id,)).fetchall()
        if len(rows) != 1:
            raise TaskConflict(f'project {record["project_id"]} needs one local project binding')
        project = dict(rows[0])
        existing = connection.execute('SELECT * FROM tm_tasks WHERE stable_id=?', (record['id'],)).fetchone()
        if existing and (existing['project_id'] != project['id']
                or existing['ref_prefix'] != record['origin'] or existing['par_number'] != record['number']):
            raise TaskConflict('Git changed the immutable identity of an existing task')
        if existing and existing['task_revision'] == record['revision']:
            return dict(existing)
        acceptance = dict(record['acceptance'])
        command = acceptance.pop('command')
        oracle = acceptance if 'version' in acceptance else {}
        values = {
            'stable_id': record['id'], 'project_id': project['id'],
            'ref_prefix': record['origin'], 'par_number': record['number'],
            'title': record['title'], 'description': record['description'],
            'price_rub': record['price_rub'], 'status': record['status'],
            'assignee': record['assignee'], 'priority': record['priority'],
            'git_commits': json.dumps(record['git_commits'], ensure_ascii=False),
            'created_at': record['created_at'], 'updated_at': record['updated_at'],
            'completed_at': record['completed_at'],
            'acceptance_command': command,
            'acceptance_oracle_json': json.dumps(oracle, ensure_ascii=False, sort_keys=True),
            'task_revision': record['revision'], 'task_commit': head,
        }
        columns = ','.join(values)
        binds = ','.join(':'+k for k in values)
        updates = ','.join(f'{k}=excluded.{k}' for k in values if k not in {'stable_id', 'created_at'})
        connection.execute(
            f'INSERT INTO tm_tasks({columns}) VALUES({binds}) '
            f"ON CONFLICT(stable_id) WHERE stable_id<>'' DO UPDATE SET {updates},sync_revision=tm_tasks.sync_revision+1",
            values,
        )
        return dict(connection.execute('SELECT * FROM tm_tasks WHERE stable_id=?', (record['id'],)).fetchone())

    @staticmethod
    def seal(connection: sqlite3.Connection, head: str):
        connection.execute('INSERT INTO task_projection_meta(singleton,git_head) VALUES(1,?) '
                           'ON CONFLICT(singleton) DO UPDATE SET git_head=excluded.git_head', (head,))

    def publish(self, connection: sqlite3.Connection, task_id: int) -> dict:
        if not getattr(self._operation, 'depth', 0):
            raise RuntimeError('task publication requires a Git operation before the SQL transaction')
        row = dict(connection.execute('SELECT * FROM tm_tasks WHERE id=?', (task_id,)).fetchone())
        project = connection.execute('SELECT canonical_id FROM tm_projects WHERE id=?', (row['project_id'],)).fetchone()
        if not project or not project[0] or not row['stable_id']:
            raise TaskConflict('task has no canonical binding')
        current = self.store.get(project[0], task_ref(row))
        if current['id'] != row['stable_id']:
            raise TaskConflict('task reference points to another stable ID')
        oracle = json.loads(row['acceptance_oracle_json'] or '{}')
        acceptance = {'command': row['acceptance_command'], 'manifest_paths': [], 'required': False, **oracle}
        updated = self.store.update(project[0], task_ref(row), expected_revision=row['task_revision'],
            title=row['title'], description=row['description'], status=row['status'],
            priority=row['priority'], assignee=row['assignee'], price_rub=row['price_rub'],
            acceptance=acceptance, git_commits=json.loads(row['git_commits'] or '[]'),
            completed_at=row['completed_at'])
        head = self.store.head
        connection.execute('UPDATE tm_tasks SET task_revision=?,task_commit=? WHERE id=?',
                           (updated['revision'], head, task_id))
        self.seal(connection, head)
        return updated

    def create(self, project: dict, title: str, *, request_key: str, **fields) -> dict:
        with self.operation():
            if not project.get('canonical_id'):
                raise TaskConflict('project has no canonical binding')
            from app.task_refs import parse_task_ref
            reserved = set()
            if project.get('scope'):
                root = Path(project['scope']) / '.orchestra' / 'tasks'
                for path in root.iterdir() if root.is_dir() else ():
                    if path.is_dir():
                        try:
                            ref = parse_task_ref(path.name)
                        except ValueError:
                            continue
                        if ref.origin == self.store.origin:
                            reserved.add(ref.number)
            record = self.store.create(project['canonical_id'], title, request_key=request_key,
                                       reserved_numbers=reserved, **fields)
            with db._conn(self.database) as connection:
                connection.execute('BEGIN IMMEDIATE')
                row = self.project(connection, record, self.store.head)
                self.seal(connection, self.store.head)
            return row

    def sync(self) -> dict:
        result = self.store.sync()
        self.refresh()
        return result


def active_runtime() -> TaskRuntime:
    if _ACTIVE is None:
        raise TaskConflict('task storage is not initialized')
    return _ACTIVE


@contextmanager
def task_runtime_mode(runtime: TaskRuntime):
    global _ACTIVE
    if _ACTIVE is not None:
        raise RuntimeError('task storage already has an owner')
    _ACTIVE = runtime
    try:
        runtime.refresh()
        yield runtime
    finally:
        _ACTIVE = None


def production_runtime() -> TaskRuntime:
    """Open the migrated private repository, or initialize an empty installation."""
    import subprocess
    from app.task_refs import new_task_prefix
    root = Path(os.environ.get('ORCHESTRA_TASK_REPOSITORY') or db.DB_PATH.parent / 'tasks')
    if not (root / '.git').exists():
        with db._conn() as connection:
            if connection.execute('SELECT 1 FROM tm_tasks LIMIT 1').fetchone():
                raise TaskConflict('migrate task storage and set ORCHESTRA_TASK_REPOSITORY before starting')
        root.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(['git', 'init', '--initial-branch=main', str(root)], check=True, capture_output=True)
        TaskStore(root, origin=new_task_prefix()).initialize()
    return TaskRuntime(TaskStore(root, origin=new_task_prefix()), db.DB_PATH)
