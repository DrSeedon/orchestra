"""Rebuild the deleted Git task store from the live SQLite projection (tm_tasks)."""
import json, sqlite3, subprocess, sys, hashlib
from pathlib import Path
sys.path.insert(0, '/home/kesha/orchestra')
from app.task_store import _bytes, _validate, SCHEMA_VERSION

target = Path(sys.argv[1]); laptop = Path('/home/kesha/orchestra/data/v655-recovery/projects')
old = {}
for p in laptop.rglob('*.json'):
    r = json.loads(p.read_text()); old[r['id']] = r
con = sqlite3.connect('file:/home/kesha/orchestra/data/orchestra.db?mode=ro', uri=True); con.row_factory = sqlite3.Row
rows = con.execute('SELECT t.*, p.canonical_id FROM tm_tasks t JOIN tm_projects p ON p.id=t.project_id').fetchall()
target.mkdir(parents=True)
(target / 'task-store.json').write_bytes(_bytes({'schema_version': SCHEMA_VERSION}))
reused = 0
for row in rows:
    prev = old.get(row['stable_id'])
    reused += prev is not None
    oracle = json.loads(row['acceptance_oracle_json'] or '{}')
    base_acc = (prev or {}).get('acceptance', {'manifest_paths': [], 'required': False})
    acceptance = {'command': row['acceptance_command'], 'manifest_paths': base_acc.get('manifest_paths', []),
                  'required': base_acc.get('required', False), **oracle}
    rec = {
        'schema_version': SCHEMA_VERSION, 'id': row['stable_id'], 'project_id': row['canonical_id'],
        'origin': row['ref_prefix'], 'number': row['par_number'], 'title': row['title'],
        'description': row['description'], 'status': row['status'], 'priority': row['priority'],
        'assignee': row['assignee'], 'price_rub': row['price_rub'], 'acceptance': acceptance,
        'git_commits': json.loads(row['git_commits'] or '[]'),
        'evidence_refs': (prev or {}).get('evidence_refs', []),
        'completed_at': row['completed_at'], 'tags': json.loads(row['tags'] or '[]'),
        'created_at': row['created_at'], 'updated_at': row['updated_at'],
        'creation_key': (prev or {}).get('creation_key') or 'recovered-' + row['stable_id'],
        'creation_fingerprint': (prev or {}).get('creation_fingerprint')
            or hashlib.sha256(('recovered:' + row['stable_id']).encode()).hexdigest(),
    }
    _validate(rec)
    path = target / 'projects' / rec['project_id'] / 'tasks' / (rec['id'] + '.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_bytes(rec))
print(f'records={len(rows)} reused_laptop_fields={reused}')
g = lambda *a: subprocess.run(['git', '-C', str(target), *a], check=True, capture_output=True, text=True)
g('init', '-q', '-b', 'main'); g('add', '-A')
g('commit', '-q', '-m', 'Recover task store from SQLite projection after accidental deletion (28.09.2026)')
print(g('rev-parse', 'HEAD').stdout.strip())
