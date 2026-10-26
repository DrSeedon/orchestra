"""Compare the actual before/after functions with isolated production-schema SQLite."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import runpy
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
TASK = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
runpy.run_path(str(ROOT / 'tests/conftest.py'))
import app
from app import db

assert Path(app.__file__).resolve() == ROOT / 'app/__init__.py'
print(json.dumps({'actual_app_import': str(Path(app.__file__).resolve()),
                  'sqlite_version': db.sqlite3.sqlite_version,
                  'baseline_sha256': hashlib.sha256((TASK / 'baseline_search.py').read_bytes()).hexdigest()}))
namespace = dict(vars(db))
exec(compile((TASK / 'baseline_search.py').read_text(), '<supplied-search>', 'exec'), namespace)
before, after = namespace['search_logs'], db.search_logs
connect = db._conn
for padding in (64, 32_768):
    for foreign in (0, 16_384, 65_536):
        for shape in ('recent-eight', 'rare-seven', 'zero'):
            db.DB_PATH = TASK / 'tmp/profile.db'
            db.init_db()
            with connect() as c:
                c.executemany('INSERT INTO sessions(id,name,scope,cwd,model,created_at) VALUES(?,?,?,?,?,?)',
                    [('own', 'project-orchestrator', '/synthetic/own', '', 'test', '2026-10-25'),
                     ('foreign', 'project-orchestrator', '/synthetic/foreign', '', 'test', '2026-10-25')])
                c.executemany('INSERT INTO logs(session_id,ts,type,content) VALUES(?,?,?,?)',
                    [('own', '2026-10-25T12:00:00Z', 'text', 'z' * padding +
                      ('14:30' if (shape == 'recent-eight' and i > 1044 or shape == 'rare-seven' and i <= 7) else ''))
                     for i in range(1, 1053)])
                c.executemany('INSERT INTO logs(session_id,ts,type,content) VALUES(?,?,?,?)',
                    (('foreign', '2026-10-25T12:00:00Z' if i % 2 else '2020-01-01T12:00:00Z',
                      'text', 'noise') for i in range(foreign)))
            samples = {}
            expected = None
            # Paired before/after/after/before, no VM instrumentation in timed runs.
            for label, function in [('before', before), ('after', after), ('after', after), ('before', before)]:
                start = time.perf_counter()
                result = function('14:30', scope='/synthetic/own', agent='project-orchestrator',
                                  date_from='2026-10-25', limit=8)
                elapsed = time.perf_counter() - start
                expected = result if expected is None else expected
                assert result == expected
                samples.setdefault(label, []).append(elapsed)
            steps = {}
            plans = {}
            for label, function in [('before', before), ('after', after)]:
                work = [0]
                @contextmanager
                def observed():
                    with connect() as c:
                        class Probe:
                            def execute(self, sql, params=()):
                                if sql.lstrip().startswith('SELECT l.id') and 'WHERE l.id = ' not in sql:
                                    plans[label] = [r['detail'] for r in c.execute('EXPLAIN QUERY PLAN ' + sql, params)]
                                return c.execute(sql, params)
                        def progress():
                            work[0] += 100
                            return 0
                        c.set_progress_handler(progress, 100)
                        yield Probe()
                db._conn = namespace['_conn'] = observed
                try:
                    assert function('14:30', scope='/synthetic/own', agent='project-orchestrator',
                                    date_from='2026-10-25', limit=8) == expected
                finally:
                    db._conn = namespace['_conn'] = connect
                steps[label] = work[0]
            print(json.dumps({'own_rows': 1052, 'foreign_rows': foreign, 'padding': padding, 'shape': shape,
                              'seconds': samples, 'vm_steps_rounded_down_to_100': steps, 'plans': plans,
                              'scanned': expected['scanned'], 'ids': [r['id'] for r in expected['results']]}), flush=True)
            for suffix in ('', '-wal', '-shm'):
                Path(str(db.DB_PATH) + suffix).unlink(missing_ok=True)
