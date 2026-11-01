"""Supplemental checks for the partial hub copy; NOT the required full suite.

Run unchanged regression test definitions from tests/test_error_watch.py without
its global conftest (which needs the rest of app). The two missing app imports
are explicit stubs: a local DB path and identity secret masking. No secret-mask
or application-wide integration behavior is verified by this harness.
"""

import ast
from pathlib import Path
import sys
from types import ModuleType


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
db_stub = ModuleType("app.db")
db_stub.DB_PATH = Path(__file__).parent / "tmp" / "unused.db"
mask_stub = ModuleType("app.secret_mask")
mask_stub.mask_secrets = lambda value: value
sys.modules["app.db"] = db_stub
sys.modules["app.secret_mask"] = mask_stub

test_path = ROOT / "tests" / "test_error_watch.py"
tree = ast.parse(test_path.read_text(encoding="utf-8"), filename=str(test_path))
selected = {
    "_event", "hub_finish_db", "_insert_error_rows",
    "test_bash_terminated_result_is_noise",
    "test_other_terminated_events_stay_actionable",
    "test_bash_terminated_scan_reports_noise_separately_from_other_tool",
}
tree.body = [
    node for node in tree.body
    if isinstance(node, (ast.Import, ast.ImportFrom))
    or isinstance(node, ast.FunctionDef) and node.name in selected
]
exec(compile(tree, str(test_path), "exec"), globals())
