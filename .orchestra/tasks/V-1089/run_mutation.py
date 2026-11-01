"""Run real committed tests against in-memory mutants; never change source files."""
from pathlib import Path
import inspect
import runpy
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
runpy.run_path(str(ROOT / 'tests/conftest.py'))
from app import db
from app.routes import sessions
import pytest

mode = sys.argv[1]
source = inspect.getsource(db.search_logs)
if mode == 'baseline':
    source = Path(__file__).with_name('baseline_search.py').read_text()
    paths = ['tests/test_log_search_v1089.py']
    selected = 'work_is_independent or missing_exact_agent or work_deadline'
elif mode == 'global-day-index':
    source = source.replace('day = "+date(l.ts)" if exact_session else "date(l.ts)"',
                            'day = "date(l.ts)"')
    paths = ['tests/test_log_search_v1089.py']
    selected = 'work_is_independent'
elif mode == 'snapshot':
    source = source.replace('        c.execute("BEGIN")\n', '')
    paths = ['tests/test_log_search_v1089.py']
    selected = 'snapshot_survives'
elif mode == 'single-day-session':
    source = source.replace(' and not single_day', '')
    paths = ['tests/test_log_search_v1089.py']
    selected = 'single_day_keeps'
elif mode == 'scope':
    source = source.replace('SELECT id FROM sessions WHERE scope = ? AND name = ?',
                            'SELECT id FROM sessions WHERE name = ? ORDER BY scope LIMIT 1')
    source = source.replace('params.extend((scope, agent))', 'params.extend((agent,))')
    paths = ['tests/test_log_search_v1089.py']
    selected = 'utc_dates_full_unicode'
elif mode == 'payload-prefix':
    source = source.replace('content = str(row["content"] or "")',
                            'content = str(row["content"] or "")[:10000]')
    paths = ['tests/test_log_search_v1089.py']
    selected = 'utc_dates_full_unicode'
elif mode == 'candidate-cap':
    db.LOG_SEARCH_SCAN_LIMIT = 100
    paths = ['tests/test_log_search_v1089.py']
    selected = 'candidate_cap'
elif mode == 'inline':
    async def inline(function, *args, **kwargs):
        return function(*args, **kwargs)
    sessions.run_in_threadpool = inline
    paths = ['tests/test_log_search_v1078.py']
    selected = 'blocked_sqlite'
else:
    raise ValueError(mode)
if mode not in ('candidate-cap', 'inline'):
    assert source != inspect.getsource(db.search_logs)
    exec(compile(source, '<search-mutation-' + mode + '>', 'exec'), vars(db))
    sessions.search_logs = db.search_logs
raise SystemExit(pytest.main([
    *paths, '-q', '--tb=short', '-k', selected,
    '--basetemp=.orchestra/tasks/V-1089/tmp/mutation-' + mode,
]))
