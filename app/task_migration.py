"""One-time conversion on private copies; the running service is never modified."""
from __future__ import annotations

from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import shutil

from app import db
from app.task_refs import project_key, TaskRef
from app.task_store import TaskStore, TaskConflict, _bytes, _validate, _DEFAULTS
import copy


def _creation_body(state: dict) -> dict:
    return {**copy.deepcopy(_DEFAULTS),
            **{k: state[k] for k in ('title', 'description', 'status', 'priority', 'assignee', 'price_rub')},
            'acceptance': {k: state['acceptance'][k] for k in ('command', 'manifest_paths', 'required')}}


def _old_request_fingerprint(state: dict, project: str) -> str:
    body = {'project_id': project, 'title': state['title'], 'price': state['price_rub'],
            'description': state['description'], 'assignee': state['assignee'],
            'status': state['status'], 'priority': state['priority'],
            'acceptance_command': state['acceptance']['command'].strip(),
            'acceptance_manifest': sorted(state['acceptance']['manifest_paths']),
            'acceptance_required': bool(state['acceptance']['required'])}
    return 'sha256:' + hashlib.sha256(json.dumps(body, ensure_ascii=False,
        sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def convert_tasks(connection, canonical: Path, registry: dict, mapping: dict | None = None) -> dict:
    """Match exact project/namespace/number identities, never titles or timestamps."""
    mapping = mapping or {}
    project_map, identity_map = mapping.get('projects', {}), mapping.get('identities', {})
    scopes = {(r.get('scope') or '').rstrip('/'): r['canonical_project_id'] for r in registry['entries']}
    projects = {}
    for row in connection.execute('SELECT id,scope FROM tm_projects ORDER BY id'):
        projects[row['id']] = scopes.get((row['scope'] or '').rstrip('/')) or project_key(row['id'])
    if len(set(projects.values())) != len(projects):
        raise TaskConflict('multiple local projects share a canonical identity; explicit mapping required')
    rows = [dict(r) for r in connection.execute('SELECT * FROM tm_tasks ORDER BY id')]
    by_ref = {(projects[r['project_id']], r.get('ref_prefix') or '', r['par_number']): r for r in rows}
    if len(by_ref) != len(rows):
        raise TaskConflict('duplicate SQL task references')
    request_table = connection.execute("SELECT 1 FROM sqlite_master WHERE name='tm_task_create_requests'").fetchone()
    requests = [dict(r) for r in connection.execute('SELECT * FROM tm_task_create_requests')] if request_table else []
    preserved_requests = set()
    records, bindings, differences = [], {}, []
    for path in sorted(canonical.rglob('state.json')):
        old = json.loads(path.read_text())
        if old.get('record_type') != 'task.state':
            continue
        portable_project = projects.get(old['project_id'], old['project_id'])
        key = (portable_project, old.get('ref_prefix') or '', old['display_number'])
        row = by_ref.pop(key, None)
        if row is None:
            raise TaskConflict(f'canonical task {key} has no unique SQL binding')
        # The executable acceptance contract and its audit are owned by runtime SQL.
        # Old Git states can lag this contract; preserve the actual gate, not its stale copy.
        oracle = json.loads(row.get('acceptance_oracle_json') or '{}')
        acceptance = {'command': row.get('acceptance_command') or '',
                      'manifest_paths': oracle.get('manifest_paths', []),
                      'required': oracle.get('required', False), **oracle}
        stable_id = identity_map.get(old['stable_id'], old['stable_id'])
        record = {
            'schema_version': 1, 'id': stable_id, 'project_id': project_map.get(portable_project, portable_project),
            'origin': key[1], 'number': key[2],
            **{k: old[k] for k in ('title', 'description', 'status', 'priority', 'price_rub', 'assignee', 'created_at', 'updated_at')},
            'completed_at': old.get('completed_at'),
            'acceptance': acceptance, 'git_commits': old['git_commit_refs'],
            'evidence_refs': old['evidence_refs'],
            'creation_key': f'migrated:{stable_id}',
            'creation_fingerprint': hashlib.sha256(_bytes(old)).hexdigest(),
        }
        binding_preserved = False
        if row.get('worker_session_id') and row['status'] == 'in_progress' and old['status'] in {'new', 'backlog'}:
            owner = connection.execute(
                'SELECT s.task_id,s.status,s.scope,p.scope AS project_scope FROM sessions s '
                'JOIN tm_projects p ON p.id=? WHERE s.id=?', (row['project_id'], row['worker_session_id'])).fetchone()
            if (owner and owner['status'] != 'archived' and owner['project_scope']
                    and (owner['scope'] or '').rstrip('/') == owner['project_scope'].rstrip('/')
                    and owner['task_id'] == TaskRef(key[1], key[2]).key):
                record['status'], record['completed_at'] = 'in_progress', None
                binding_preserved = True
        request = old.get('create_request')
        associated = [q for q in requests if q['project_id'] == row['project_id'] and q['par_number'] == row['par_number']]
        if request or associated:
            created = []
            for event_path in (path.parent / 'events').glob('*.json'):
                event = json.loads(event_path.read_text())
                if event.get('event_type') == 'task.created':
                    created.append(event['result_state'])
            if request:
                if len(created) != 1:
                    raise TaskConflict(f'creation history is missing or ambiguous for {stable_id}')
                initial = created[0]
            else:
                if len(associated) != 1:
                    raise TaskConflict(f'creation receipts are ambiguous for {stable_id}')
                request = associated[0]
                # A legacy ACTIVE_COMMITTED receipt can lack Git request metadata.
                # Recover only a payload proven by its original request hash.
                initial = next((state for state in [*created, old]
                    if _old_request_fingerprint(state, row['project_id']) == request['fingerprint']), None)
                if initial is None:
                    raise TaskConflict(f'original creation payload cannot be proven for {stable_id}')
            record['creation_key'] = request['request_key']
            record['creation_fingerprint'] = hashlib.sha256(_bytes(_creation_body(initial))).hexdigest()
            preserved_requests.add((row['project_id'], record['creation_key']))
        _validate(record)
        if stable_id in bindings:
            raise TaskConflict('duplicate canonical task UUID')
        bindings[stable_id] = row['id']
        fields = [k for k in ('title', 'description', 'status', 'priority', 'price_rub', 'assignee', 'completed_at')
                  if row.get(k) != record[k]]
        if any(acceptance[k] != old['acceptance'][k] for k in ('command', 'manifest_paths', 'required')):
            fields.append('acceptance')
        if binding_preserved:
            fields.append('active_binding_status')
        if fields:
            differences.append({'task_id': row['id'], 'stable_id': stable_id, 'fields': fields})
        records.append(record)
    if any((q['project_id'], q['request_key']) not in preserved_requests for q in requests):
        raise TaskConflict('unresolved task-create receipts must be recovered before migration')
    if by_ref:
        raise TaskConflict(f'{len(by_ref)} SQL tasks are absent from the canonical snapshot')
    projects = {key: project_map.get(value, value) for key, value in projects.items()}
    if len(set(projects.values())) != len(projects):
        raise TaskConflict('project mapping merges distinct local projects')
    return {'records': records, 'bindings': bindings, 'projects': projects,
            'differences': differences, 'sql_tasks': rows}


RETIRED_TABLES = frozenset({'jobs', 'inbox', 'tm_clients', 'tm_payments',
    'tm_payment_allocations', 'tm_sync_log', 'tm_task_create_requests'})
RETIRED_TASK_COLUMNS = frozenset({'paid_rub', 'paid_at', 'yougile_task_id'})


def _copy_runtime_tables(source: Path, target: Path) -> dict:
    db.init_db(target)
    preserved = {}
    with db._conn(target) as connection:
        connection.execute('PRAGMA foreign_keys=OFF')
        connection.execute('ATTACH DATABASE ? AS old', (str(source),))
        source_tables = {r[0] for r in connection.execute("SELECT name FROM old.sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        target_tables = {r[0] for r in connection.execute("SELECT name FROM main.sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        unknown = source_tables - target_tables - RETIRED_TABLES
        # Subsystems (for example quota control) own additional tables outside db.init_db.
        # Preserve their exact schema and rows; absence from the task schema is not obsolescence.
        extra_objects = []
        for table in sorted(unknown):
            definition = connection.execute("SELECT sql FROM old.sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()[0]
            connection.execute(definition)
            extra_objects.extend(r[0] for r in connection.execute(
                "SELECT sql FROM old.sqlite_master WHERE tbl_name=? AND type IN ('index','trigger') AND sql IS NOT NULL", (table,)))
        target_tables.update(unknown)
        connection.execute('BEGIN IMMEDIATE')
        for table in sorted(source_tables & target_tables):
            if not re.fullmatch('[a-z_]+', table):
                raise TaskConflict('unexpected table identifier')
            source_columns = {r[1] for r in connection.execute(f'PRAGMA old.table_info({table})')}
            target_columns = {r[1] for r in connection.execute(f'PRAGMA main.table_info({table})')}
            dropped = source_columns - target_columns
            historical_review = {'author_outcome','outcome_source','outcome_evidence_ref',
                'production_snapshot_sha256','production_diff_sha256','production_paths_json',
                'production_path_heads_json','coverage_outcome','decision_actor'}
            if table == 'review_receipts':
                for name in sorted(dropped & historical_review):
                    connection.execute(f'ALTER TABLE main.review_receipts ADD COLUMN "{name}" TEXT')
                    target_columns.add(name)
                dropped = source_columns - target_columns
            if dropped - (RETIRED_TASK_COLUMNS if table == 'tm_tasks' else set()):
                raise TaskConflict(f'unknown columns need explicit preservation: {table}: {sorted(dropped)}')
            columns = ','.join('"'+name+'"' for name in sorted(source_columns & target_columns))
            connection.execute(f'DELETE FROM main."{table}"')
            connection.execute(f'INSERT INTO main."{table}"({columns}) SELECT {columns} FROM old."{table}"')
            before = connection.execute(f'SELECT COUNT(*) FROM old."{table}"').fetchone()[0]
            after = connection.execute(f'SELECT COUNT(*) FROM main."{table}"').fetchone()[0]
            if before != after:
                raise TaskConflict(f'row count changed in {table}')
            preserved[table] = after
        sequence_exists = connection.execute("SELECT 1 FROM old.sqlite_master WHERE name='sqlite_sequence'").fetchone()
        if sequence_exists:
            for name, sequence in connection.execute('SELECT name,seq FROM old.sqlite_sequence'):
                if name in target_tables:
                    connection.execute('DELETE FROM main.sqlite_sequence WHERE name=?', (name,))
                    connection.execute('INSERT INTO main.sqlite_sequence(name,seq) VALUES(?,?)', (name, sequence))
        for definition in extra_objects:
            connection.execute(definition)
    return preserved


def prepare_migration(*, source_db: Path, source_repo: Path, registry_path: Path,
                      destination: Path, origin: str, mapping_path: Path | None = None) -> dict:
    """Build a reviewable DB/repo pair. Destination must be new; no live cutover."""
    source_db, source_repo, destination = map(Path, (source_db, source_repo, destination))
    if not source_db.is_file() or not source_repo.is_dir():
        raise ValueError('source database and canonical repository must exist')
    source_store = TaskStore(source_repo, origin=origin)
    before_head = source_store.head
    if source_store._git('status', '--porcelain', '--untracked-files=all').stdout:
        raise TaskConflict('source canonical repository has uncommitted data; finish recovery before migration')
    destination.mkdir(parents=True, exist_ok=False)
    target_db, target_repo = destination / 'orchestra.db', destination / 'tasks'
    snapshot = destination / 'source.sqlite'
    subprocess.run(['git', 'clone', '--no-hardlinks', '--no-local', str(source_repo), str(target_repo)],
                   check=True, capture_output=True, timeout=120)
    subprocess.run(['git', '-C', str(target_repo), 'remote', 'remove', 'origin'], check=True, capture_output=True)
    with closing(sqlite3.connect(source_db.resolve().as_uri() + '?mode=ro', uri=True)) as source:
        with closing(sqlite3.connect(snapshot)) as target:
            source.backup(target)
    if source_store.head != before_head or source_store._git('status', '--porcelain', '--untracked-files=all').stdout:
        raise TaskConflict('source canonical repository changed while taking the snapshot')
    registry = json.loads(Path(registry_path).read_text())
    mapping = json.loads(mapping_path.read_text()) if mapping_path else {}
    node = mapping.get('node', 'vps' if origin == 'V' else 'laptop')
    if node not in {'laptop', 'vps'}:
        raise ValueError('migration node must be laptop or vps')
    store = TaskStore(target_repo, origin=origin)
    source_head = store.head
    store._git('switch', '-C', 'main')
    with db._conn(snapshot) as connection:
        existing_errors = {tuple(r) for r in connection.execute('PRAGMA foreign_key_check')}
        plan = convert_tasks(connection, target_repo, registry, mapping)
        tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        retired = {table: [dict(r) for r in connection.execute(f'SELECT * FROM "{table}"')]
                   for table in sorted(RETIRED_TABLES & tables)}
    counts = _copy_runtime_tables(snapshot, target_db)
    receipt = {'node': node, 'source_head': source_head, 'identity_mapping': mapping.get('identities', {}), 'tasks': len(plan['records']),
               'differences': plan['differences'], 'projects': plan['projects'],
               'existing_foreign_key_errors': len(existing_errors), 'preserved_tables': counts,
               'retired_tables': {table: len(rows) for table, rows in retired.items()},
               'sql_tasks_sha256': hashlib.sha256(_bytes({'tasks': plan['sql_tasks']})).hexdigest()}
    archive = target_repo / 'migration-source'
    store._commit_files({archive / 'sql-tasks.json': _bytes({'tasks': plan['sql_tasks']}),
                         archive / 'retired-tables.json': _bytes(retired)},
                        'Preserve SQL task and retired-table snapshots before conversion')
    store.initialize()
    files = {store._path(r): _bytes(r) for r in plan['records']}
    files[target_repo / f'migration.{node}.json'] = _bytes(receipt)
    store._commit_files(files, 'Convert task states to one Git store')
    old_roots = [name for name in ('tasks', 'migration-source', 'evidence', 'knowledge', 'receipts', 'projection-outbox')
                 if (target_repo / name).exists()]
    if old_roots:
        kept = {'projects', 'task-store.json', f'migration.{node}.json'}
        top = set(store._git('ls-tree', '--name-only', 'HEAD').stdout.splitlines())
        if top - kept - set(old_roots):
            raise TaskConflict('unexpected canonical roots need explicit preservation')
        # This index belongs only to the fresh migration clone. Rebuild it in one pass;
        # git rm over the old VPS outbox (100k+ tiny files) spends minutes on per-file work.
        store._git('read-tree', '--empty')
        store._git('add', '--', *sorted(kept))
        store._git('commit', '-m', 'Retire old materializations after preserved conversion')
        for name in old_roots:
            shutil.rmtree(target_repo / name)
    foreign_key_errors = _project_migrated_database(target_db, store, plan, mapping, existing_errors)
    receipt['target_head'] = store.head
    receipt['remaining_foreign_key_errors'] = len(foreign_key_errors)
    (destination / 'report.json').write_bytes(_bytes(receipt))
    return receipt


def _project_migrated_database(target_db, store, plan, mapping, existing_errors):
    from app.task_runtime import TaskRuntime
    runtime = TaskRuntime(store, target_db)
    with db._conn(target_db) as connection:
        connection.execute('BEGIN IMMEDIATE')
        for project_id, canonical_id in plan['projects'].items():
            connection.execute('UPDATE tm_projects SET canonical_id=? WHERE id=?', (canonical_id, project_id))
        for stable_id, row_id in plan['bindings'].items():
            connection.execute('UPDATE tm_tasks SET stable_id=?,task_revision=? WHERE id=?', (stable_id, '', row_id))
        for previous, current in mapping.get('identities', {}).items():
            for table in ('portfolio_waits', 'review_receipts'):
                if connection.execute(f'SELECT 1 FROM {table} WHERE task_stable_id=? LIMIT 1', (previous,)).fetchone():
                    raise TaskConflict(f'UUID collision has {table} references; preserve their identity before conversion')
            connection.execute('UPDATE portfolio_task_links SET task_stable_id=? WHERE task_stable_id=?', (current, previous))
        connection.execute('DELETE FROM task_projection_meta')
    runtime.refresh()
    with db._conn(target_db) as connection:
        if connection.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise TaskConflict('migrated SQLite integrity check failed')
        foreign_key_errors = {tuple(r) for r in connection.execute('PRAGMA foreign_key_check')}
        retained_errors = {r for r in existing_errors if r[0] not in RETIRED_TABLES}
        if foreign_key_errors != retained_errors:
            raise TaskConflict('migration changed foreign-key violations in retained tables')
        actual = {r['stable_id']: r['id'] for r in connection.execute('SELECT id,stable_id FROM tm_tasks')}
        if actual != plan['bindings']:
            raise TaskConflict('migration changed local task IDs')
    return foreign_key_errors


def finalize_migration(*, source_db: Path, source_repo: Path, registry_path: Path,
                       prepared: Path, destination: Path, origin: str,
                       mapping_path: Path | None = None) -> dict:
    """After stopping the old writer, copy fresh runtime state into a prepared conversion.

    The expensive history conversion runs while the service is still available. Any task
    drift invalidates that preparation; callers must restart the old service and prepare again.
    This function never stops a service or installs its output.
    """
    prepared, destination = Path(prepared), Path(destination)
    report = json.loads((prepared / 'report.json').read_text())
    source_store = TaskStore(source_repo, origin=origin)
    store = TaskStore(prepared / 'tasks', origin=origin)
    def unchanged():
        for candidate, expected in ((source_store, report['source_head']), (store, report['target_head'])):
            if candidate.head != expected or candidate._git('status', '--porcelain', '--untracked-files=all').stdout:
                raise TaskConflict('task history changed after preparation; prepare again')
    unchanged()
    destination.mkdir(parents=True, exist_ok=False)
    snapshot, target = destination / 'source.sqlite', destination / 'orchestra.db'
    with closing(sqlite3.connect(Path(source_db).resolve().as_uri() + '?mode=ro', uri=True)) as source:
        with closing(sqlite3.connect(snapshot)) as copy:
            source.backup(copy)
    mapping = json.loads(mapping_path.read_text()) if mapping_path else {}
    registry = json.loads(Path(registry_path).read_text())
    with db._conn(snapshot) as connection:
        plan = convert_tasks(connection, source_repo, registry, mapping)
        existing_errors = {tuple(r) for r in connection.execute('PRAGMA foreign_key_check')}
    current = {r['id']: r for r in store.list()}
    if set(current) != {r['id'] for r in plan['records']} or any(
            any(current[r['id']][k] != value for k, value in r.items()) for r in plan['records']):
        raise TaskConflict('task contract changed after preparation; prepare again')
    counts = _copy_runtime_tables(snapshot, target)
    errors = _project_migrated_database(target, store, plan, mapping, existing_errors)
    unchanged()
    result = {'tasks': len(plan['records']), 'preserved_tables': counts,
              'remaining_foreign_key_errors': len(errors), 'source_head': source_store.head,
              'target_head': store.head, 'prepared': str(prepared)}
    (destination / 'report.json').write_bytes(_bytes(result))
    return result
