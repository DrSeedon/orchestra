"""Explicit fixtures for historical SQL task scenarios, backed by the real Git store."""
import copy
import hashlib
import json
import uuid
from app import tm
from app.task_refs import project_key
from app.task_refs import new_task_prefix
from app.task_store import _DEFAULTS, _bytes, _validate


def create_task(connection, project_id, title, price_rub=0, description='', assignee='',
                status='new', par_number=None, priority=2, acceptance_command='',
                acceptance_manifest=None, acceptance_required=False, acceptance_actor=None):
    runtime = tm.active_runtime()
    number = par_number if par_number is not None else connection.execute(
        'SELECT COALESCE(MAX(par_number),0)+1 FROM tm_tasks WHERE project_id=? AND ref_prefix=?',
        (project_id, new_task_prefix())).fetchone()[0]
    project = connection.execute('SELECT * FROM tm_projects WHERE id=?', (project_id,)).fetchone()
    canonical_id = project['canonical_id'] or project_key(project_id)
    connection.execute('UPDATE tm_projects SET canonical_id=? WHERE id=?', (canonical_id, project_id))
    acceptance_manifest = tm._normalize_acceptance_manifest(acceptance_manifest)
    acceptance = {'command': acceptance_command, 'manifest_paths': acceptance_manifest or [], 'required': acceptance_required}
    if acceptance_manifest or acceptance_required:
        acceptance.update(json.loads(tm._acceptance_oracle_json(required=acceptance_required,
            manifest=acceptance_manifest or [], revision=1, actor=tm._normalize_acceptance_actor(acceptance_actor))))
    now, stable_id = tm._now(), str(uuid.uuid4())
    record = {**copy.deepcopy(_DEFAULTS), 'schema_version': 1, 'id': stable_id,
        'project_id': canonical_id, 'origin': new_task_prefix(), 'number': number,
        'title': title, 'description': description, 'assignee': assignee, 'status': status,
        'price_rub': price_rub, 'priority': priority, 'acceptance': acceptance,
        'created_at': now, 'updated_at': now, 'creation_key': 'seed:'+stable_id,
        'creation_fingerprint': hashlib.sha256(stable_id.encode()).hexdigest()}
    _validate(record)
    with runtime.store._lock():
        runtime.store._commit_files({runtime.store._path(record): _bytes(record)}, 'Seed test task')
        from app.task_store import _view
        task = runtime.project(connection, _view(record), runtime.store.head)
        runtime.seal(connection, runtime.store.head)
    return task
