"""Task state in Git. Local operations never contact a remote.

Each task has one file. Git owns history and merge conflicts; SQLite is only a
projection, refreshed by the runtime after a successful local write or sync.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import copy
import fcntl
import hashlib
import json
import os
import re
import subprocess
import uuid

from app.task_refs import TaskRef, parse_task_ref


class TaskConflict(RuntimeError):
    """A concurrent edit, duplicate identity or native Git conflict needs resolution."""


_DEFAULTS = {
    'description': '', 'status': 'new', 'priority': 2, 'assignee': '', 'price_rub': 0,
    'acceptance': {'command': '', 'manifest_paths': [], 'required': False},
    'git_commits': [], 'evidence_refs': [],
}
_MUTABLE = frozenset({'title', *_DEFAULTS})
_STATUSES = frozenset({'backlog', 'new', 'in_progress', 'done', 'cancelled'})


def _bytes(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()


def _project(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r'[a-z0-9][a-z0-9._-]*', value):
        raise ValueError('project identity must be a path-safe stable identifier')
    return value


def _view(record: dict) -> dict:
    ref = TaskRef(record['origin'], record['number'])
    return {**copy.deepcopy(record), 'ref': ref.key, 'display_ref': ref.display,
            'revision': hashlib.sha256(_bytes(record)).hexdigest()}


def _validate(record: dict) -> None:
    required = {'schema_version', 'id', 'project_id', 'origin', 'number', 'created_at',
                'updated_at', 'creation_key', 'creation_fingerprint', *_MUTABLE}
    if set(record) != required or record['schema_version'] != 1:
        raise ValueError('invalid task record shape/version')
    if str(uuid.UUID(record['id'])) != record['id']:
        raise ValueError('task ID must be a canonical UUID')
    _project(record['project_id'])
    TaskRef(record['origin'], record['number'])
    if not isinstance(record['title'], str) or not record['title'].strip():
        raise ValueError('task title is required')
    for field in ('description', 'assignee', 'created_at', 'updated_at', 'creation_key', 'creation_fingerprint'):
        if not isinstance(record[field], str):
            raise ValueError(f'{field} must be a string')
    if record['status'] not in _STATUSES:
        raise ValueError('invalid task status')
    if type(record['priority']) is not int or not 0 <= record['priority'] <= 3:
        raise ValueError('priority must be between 0 and 3')
    if type(record['price_rub']) is not int or record['price_rub'] < 0:
        raise ValueError('task price must be a nonnegative integer')
    acceptance = record['acceptance']
    if not isinstance(acceptance, dict) or set(acceptance) != {'command', 'manifest_paths', 'required'}:
        raise ValueError('invalid acceptance shape')
    if (not isinstance(acceptance['command'], str) or type(acceptance['required']) is not bool
            or not isinstance(acceptance['manifest_paths'], list)
            or not all(isinstance(p, str) for p in acceptance['manifest_paths'])):
        raise ValueError('invalid acceptance values')
    if not isinstance(record['git_commits'], list) or not isinstance(record['evidence_refs'], list):
        raise ValueError('task references must be lists')
    _bytes(record)


class TaskStore:
    def __init__(self, root: Path, *, origin: str):
        self.root = Path(root).resolve()
        TaskRef(origin, 1)
        self.origin = origin

    def _git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        result = subprocess.run(['git', '-C', str(self.root), *args],
                                capture_output=True, text=True, timeout=60)
        if check and result.returncode:
            raise TaskConflict(result.stderr.strip() or result.stdout.strip() or 'Git operation failed')
        return result

    @contextmanager
    def _lock(self):
        path = Path(self._git('rev-parse', '--git-path', 'orchestra-tasks.lock').stdout.strip())
        if not path.is_absolute():
            path = self.root / path
        with path.open('a+b') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)

    def _ready(self):
        marker = self.root / 'task-store.json'
        if not marker.is_file() or json.loads(marker.read_text()) != {'schema_version': 1}:
            raise TaskConflict('task repository is not initialized')
        if self._git('ls-files', '-u').stdout:
            raise TaskConflict('task repository has unresolved Git conflicts')
        if self._git('status', '--porcelain', '--untracked-files=all', '--', 'projects').stdout:
            raise TaskConflict('task repository has uncommitted task changes')

    def initialize(self):
        with self._lock():
            path = self.root / 'task-store.json'
            if path.exists():
                self._ready()
                return
            self._commit_files({path: _bytes({'schema_version': 1})}, 'Initialize task store')

    @property
    def head(self) -> str:
        return self._git('rev-parse', 'HEAD').stdout.strip()

    def _path(self, record: dict) -> Path:
        return self.root / 'projects' / _project(record['project_id']) / 'tasks' / (record['id'] + '.json')

    def _records(self, project: str = '') -> list[dict]:
        base = self.root / 'projects'
        paths = (base / _project(project) / 'tasks').glob('*.json') if project else base.glob('*/tasks/*.json')
        records = []
        identities, refs, requests = set(), set(), set()
        for path in sorted(paths):
            record = json.loads(path.read_text())
            _validate(record)
            if path != self._path(record):
                raise TaskConflict('task identity does not match its file')
            ref = (record['project_id'], record['origin'], record['number'])
            request = (record['project_id'], record['origin'], record['creation_key'])
            if record['id'] in identities or ref in refs or request in requests:
                raise TaskConflict('task repository contains a duplicate identity/reference/request')
            identities.add(record['id']); refs.add(ref); requests.add(request)
            records.append(record)
        return records

    def _find(self, project: str, ref: str) -> dict:
        parsed = parse_task_ref(ref)
        for record in self._records(project):
            if (record['origin'], record['number']) == (parsed.origin, parsed.number):
                return record
        raise ValueError(f'{parsed.display} not found')

    def list(self, project: str = '') -> list[dict]:
        with self._lock():
            self._ready()
            return [_view(r) for r in self._records(project)]

    def get(self, project: str, ref: str) -> dict:
        with self._lock():
            self._ready()
            return _view(self._find(project, ref))

    def create(self, project: str, title: str, *, request_key: str, **fields: Any) -> dict:
        _project(project)
        if not isinstance(request_key, str) or not request_key.strip():
            raise ValueError('a caller-held creation request key is required')
        if set(fields) - (_MUTABLE - {'title'}):
            raise ValueError('unsupported task fields')
        body = {**copy.deepcopy(_DEFAULTS), **copy.deepcopy(fields), 'title': title}
        fingerprint = hashlib.sha256(_bytes(body)).hexdigest()
        with self._lock():
            self._ready()
            records = self._records(project)
            existing = next((r for r in records if r['origin'] == self.origin and r['creation_key'] == request_key), None)
            if existing:
                if existing['creation_fingerprint'] != fingerprint:
                    raise TaskConflict('creation key belongs to another task payload')
                return _view(existing)
            number = max((r['number'] for r in records if r['origin'] == self.origin), default=0) + 1
            now = datetime.now(timezone.utc).isoformat()
            record = {**body, 'schema_version': 1, 'project_id': project, 'origin': self.origin,
                      'number': number, 'id': str(uuid.uuid5(uuid.NAMESPACE_URL,
                          f'orchestra-task:{project}:{self.origin}:{request_key}')),
                      'created_at': now, 'updated_at': now, 'creation_key': request_key,
                      'creation_fingerprint': fingerprint}
            _validate(record)
            self._commit_files({self._path(record): _bytes(record)}, f'Create task {TaskRef(self.origin, number).display}')
            return _view(record)

    def update(self, project: str, ref: str, *, expected_revision: str, **fields: Any) -> dict:
        if set(fields) - _MUTABLE:
            raise ValueError('task identity and creation metadata are immutable')
        with self._lock():
            self._ready()
            old = self._find(project, ref)
            if _view(old)['revision'] != expected_revision:
                raise TaskConflict('task changed since it was read')
            if all(old[k] == v for k, v in fields.items()):
                return _view(old)
            record = {**old, **copy.deepcopy(fields), 'updated_at': datetime.now(timezone.utc).isoformat()}
            _validate(record)
            self._commit_files({self._path(record): _bytes(record)}, f'Update task {TaskRef(record["origin"], record["number"]).display}')
            return _view(record)

    def _commit_files(self, files: dict[Path, bytes], message: str):
        previous = {p: p.read_bytes() if p.exists() else None for p in files}
        relative = [str(p.relative_to(self.root)) for p in files]
        try:
            for path, content in files.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary = path.with_name('.' + path.name + '.' + uuid.uuid4().hex)
                try:
                    with temporary.open('wb') as stream:
                        stream.write(content); stream.flush(); os.fsync(stream.fileno())
                    os.replace(temporary, path)
                finally:
                    temporary.unlink(missing_ok=True)
            self._git('add', '--', *relative)
            self._git('commit', '--only', '-m', message, '--', *relative)
        except BaseException:
            # A failed commit leaves no accepted operation. Restore only our exact bytes.
            for path, content in files.items():
                if path.exists() and path.read_bytes() == content:
                    if previous[path] is None:
                        path.unlink()
                    else:
                        path.write_bytes(previous[path])
            self._git('reset', '-q', 'HEAD', '--', *relative, check=False)
            raise

    def sync(self, *, remote: str = 'origin') -> dict:
        # Network waits must not hold up unrelated local task writes.
        self._git('fetch', remote)
        with self._lock():
            self._ready()
            branch = self._git('symbolic-ref', '--short', 'HEAD').stdout.strip()
            result = self._git('merge', '--no-edit', f'{remote}/{branch}', check=False)
            if result.returncode:
                self._git('merge', '--abort', check=False)
                raise TaskConflict(result.stderr.strip() or result.stdout.strip())
            self._records()
            head = self.head
        self._git('push', remote, branch)
        return {'head': head}
