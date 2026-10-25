"""Run committed behavioral regressions against a source baseline or inline route."""
from pathlib import Path
import runpy
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
runpy.run_path(str(ROOT / "tests/conftest.py"))
from app import db
from app.routes import sessions
import pytest

mode = sys.argv[1]
if mode == "baseline":
    namespace = vars(db)
    exec(compile(Path(__file__).with_name("baseline_search.py").read_text(),
                 "<public-baseline-search>", "exec"), namespace)
    db.search_logs = namespace["search_logs"]
    sessions.search_logs = db.search_logs
    selected = "narrow_search or casefold_expansion or mcp_chain"
elif mode == "inline":
    async def inline(function, *args, **kwargs):
        return function(*args, **kwargs)

    sessions.run_in_threadpool = inline
    selected = "blocked_sqlite"
elif mode == "snapshot":
    import inspect

    source = inspect.getsource(db.search_logs).replace('        c.execute("BEGIN")\n', '')
    exec(compile(source, "<search-without-read-transaction>", "exec"), vars(db))
    selected = "one_snapshot"
else:
    raise ValueError(mode)

raise SystemExit(pytest.main([
    "tests/test_log_search_v1078.py", "-q", "--tb=short", "-k", selected,
    "--basetemp=.orchestra/tasks/V-1078/tmp/mutation-" + mode,
]))
