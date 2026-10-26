"""Offline plan and VM-work probe with the production schema and indexes."""
from pathlib import Path
import hashlib
import json
import runpy
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
runpy.run_path(str(ROOT / 'tests/conftest.py'))
from app import db
import app

TASK = Path(__file__).resolve().parent
print(json.dumps({'app_import': '/<hub-copy>/app/__init__.py',
                  'actual_import_sha256': hashlib.sha256(str(Path(app.__file__).resolve()).encode()).hexdigest(),
                  'belongs_to_checkout': Path(app.__file__).resolve() == ROOT / 'app/__init__.py'}))
db.DB_PATH = TASK / 'tmp/probe.db'
db.init_db()
with db._conn() as c:
    c.executemany('INSERT INTO sessions(id,name,scope,cwd,model,created_at) VALUES(?,?,?,?,?,?)',
                  [('own', 'project-orchestrator', '/synthetic/own', '', 'test', '2026-10-25'),
                   ('foreign', 'project-orchestrator', '/synthetic/foreign', '', 'test', '2026-10-25')])
    c.executemany('INSERT INTO logs(session_id,ts,type,content) VALUES(?,?,?,?)',
                  [('own', '2026-10-25T14:30:00Z', 'text', '14:30')] * 8)
    base = 's.id=l.session_id AND s.scope=? AND s.name=? AND date(l.ts)>=date(?)'
    params = ('/synthetic/own', 'project-orchestrator', '2026-10-25', 10001)
    queries = {
        'logs_outer': f'SELECT l.id FROM logs l CROSS JOIN sessions s WHERE {base} ORDER BY l.id DESC LIMIT ?',
        'sessions_outer': f'SELECT l.id FROM sessions s CROSS JOIN logs l WHERE {base} ORDER BY l.id DESC LIMIT ?',
        'scalar_session': 'SELECT l.id FROM logs l WHERE l.session_id=(SELECT id FROM sessions WHERE scope=? AND name=?) AND date(l.ts)>=date(?) ORDER BY l.id DESC LIMIT ?',
    }
    for count in (0, 16384):
        if count:
            c.executemany('INSERT INTO logs(session_id,ts,type,content) VALUES(?,?,?,?)',
                          [('foreign', '2026-10-25T14:30:00Z', 'text', 'noise')] * count)
        for name, query in queries.items():
            plan = [r['detail'] for r in c.execute('EXPLAIN QUERY PLAN ' + query, params)]
            work = [0]
            def progress():
                work[0] += 1
                return 0
            c.set_progress_handler(progress, 1)
            start = time.perf_counter()
            rows = c.execute(query, params).fetchall()
            elapsed = time.perf_counter() - start
            c.set_progress_handler(None, 0)
            print(json.dumps({'variant': name, 'foreign_rows': count, 'plan': plan,
                              'vm_steps': work[0], 'seconds': elapsed, 'ids': [r['id'] for r in rows]}))
for suffix in ('', '-wal', '-shm'):
    Path(str(db.DB_PATH) + suffix).unlink(missing_ok=True)
