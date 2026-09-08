"""One Git task owner and one local projection, with no knowledge-index dependency."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import json
import os
import sqlite3
import threading

from app import db
from app.task_refs import TaskRef
from app.task_store import TaskStore, TaskConflict, _view


_ACTIVE: TaskRuntime | None = None


def task_key(row: dict) -> str:
    return TaskRef(str(row.get('task_origin') or ''), int(row['par_number'])).key


class TaskRuntime:
    def __init__(self, store: TaskStore, database: Path):
        self.store = store
        self.database = Path(database)

    @contextmanager
    def operation(self):
        # One lock order for every task operation: Git owner, then SQLite writer.
        with self.store._lock():
            self.refresh()
            yield self

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
        if len(rows) != 1:
            raise TaskConflict(f'project {record["project_id"]} needs one local project binding')
        project = dict(rows[0])
        existing = connection.execute('SELECT * FROM tm_tasks WHERE stable_id=?', (record['id'],)).fetchone()
        if existing and existing['task_revision'] == record['revision']:
            return dict(existing)
        acceptance = dict(record['acceptance'])
        command = acceptance.pop('command')
        oracle = acceptance if 'version' in acceptance else {}
        values = {
            'stable_id': record['id'], 'project_id': project['id'],
            'task_origin': record['origin'], 'par_number': record['number'],
            'title': record['title'], 'description': record['description'],
            'price_rub': record['price_rub'], 'status': record['status'],
            'assignee': record['assignee'], 'priority': record['priority'],
            'git_commits': json.dumps(record['git_commits'], ensure_ascii=False),
            'created_at': record['created_at'], 'updated_at': record['updated_at'],
            'completed_at': record['updated_at'] if record['status'] == 'done' else None,
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
        row = dict(connection.execute('SELECT * FROM tm_tasks WHERE id=?', (task_id,)).fetchone())
        project = connection.execute('SELECT canonical_id FROM tm_projects WHERE id=?', (row['project_id'],)).fetchone()
        if not project or not project[0] or not row['stable_id']:
            raise TaskConflict('task has no canonical binding')
        current = self.store.get(project[0], task_key(row))
        if current['id'] != row['stable_id']:
            raise TaskConflict('task reference points to another stable ID')
        oracle = json.loads(row['acceptance_oracle_json'] or '{}')
        acceptance = {'command': row['acceptance_command'], 'manifest_paths': [], 'required': False, **oracle}
        updated = self.store.update(project[0], task_key(row), expected_revision=row['task_revision'],
            title=row['title'], description=row['description'], status=row['status'],
            priority=row['priority'], assignee=row['assignee'], price_rub=row['price_rub'],
            acceptance=acceptance, git_commits=json.loads(row['git_commits'] or '[]'))
        head = self.store.head
        connection.execute('UPDATE tm_tasks SET task_revision=?,task_commit=? WHERE id=?',
                           (updated['revision'], head, task_id))
        self.seal(connection, head)
        return updated

    def create(self, project: dict, title: str, *, request_key: str, **fields) -> dict:
        with self.operation():
            if not project.get('canonical_id'):
                raise TaskConflict('project has no canonical binding')
            record = self.store.create(project['canonical_id'], title, request_key=request_key, **fields)
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
