"""Check date/statistics variants of the exact-session candidate lookup."""
from pathlib import Path
import json
import runpy
import sys
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
runpy.run_path(str(ROOT / 'tests/conftest.py'))
from app import db

db.DB_PATH = Path(__file__).resolve().parent / 'tmp/shapes.db'
db.init_db()
with db._conn() as c:
    c.executemany('INSERT INTO sessions(id,name,scope,cwd,model,created_at) VALUES(?,?,?,?,?,?)',
                  [('own', 'project-orchestrator', '/synthetic/own', '', 'test', '2026-10-25'),
                   ('foreign', 'project-orchestrator', '/synthetic/foreign', '', 'test', '2026-10-25')])
    c.executemany('INSERT INTO logs(session_id,ts,type,content) VALUES(?,?,?,?)',
                  [('own', '2026-10-25T14:30:00Z', 'text', '14:30')] * 8 +
                  [('foreign', '2026-10-25T14:30:00Z', 'text', 'noise')] * 16384)
    for analyzed in (False, True):
        if analyzed:
            c.execute('ANALYZE')
        for dates in ('', 'AND date(l.ts)=date(?)', 'AND date(l.ts)>=date(?)',
                      'AND date(l.ts)<=date(?)', 'AND date(l.ts)>=date(?) AND date(l.ts)<=date(?)'):
            query = ('SELECT l.id FROM logs l '
                     'WHERE l.session_id=(SELECT id FROM sessions WHERE scope=? AND name=?) ' + dates.replace('date(l.ts)', '+date(l.ts)') +
                     ' ORDER BY l.id DESC LIMIT ?')
            params = ('/synthetic/own', 'project-orchestrator', *(['2026-10-25'] * dates.count('?')), 10001)
            steps = [0]
            def progress():
                steps[0] += 1
                return 0
            c.set_progress_handler(progress, 1)
            rows = c.execute(query, params).fetchall()
            c.set_progress_handler(None, 0)
            print(json.dumps({'analyzed': analyzed, 'dates': dates, 'vm_steps': steps[0],
                              'plan': [r['detail'] for r in c.execute('EXPLAIN QUERY PLAN '+query, params)]}))
for suffix in ('', '-wal', '-shm'):
    Path(str(db.DB_PATH) + suffix).unlink(missing_ok=True)
