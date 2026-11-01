"""Offline evidence for this partial copy, NOT a substitute for host integration tests.

Only two app modules were supplied. This explicit harness supplies missing import
interfaces and a synthetic SQLite schema; the actual merge_operations functions
accept, claim, run, finish, query and replay every tested operation unchanged.
Never loaded by the normal test command. Refuses a complete checkout.
"""
from contextlib import contextmanager
import importlib
from pathlib import Path
import sqlite3
import sys
import types


ROOT = Path(__file__).resolve().parents[3]
if (ROOT / "app/db.py").exists():
    raise SystemExit("Complete checkout: use the normal pytest command without this harness")
if Path.cwd() != ROOT:
    raise SystemExit("Run this harness from the source copy root")
# Absolute import origin without putting a private host/user path in public evidence.
sys.path.insert(0, "/proc/self/cwd")


def module(name, **members):
    value = types.ModuleType(name)
    value.__dict__.update(members)
    sys.modules[name] = value
    parent, _, child = name.rpartition(".")
    if parent:
        setattr(importlib.import_module(parent), child, value)
    return value


def forbidden(*_args, **_kwargs):
    raise AssertionError("Missing source interface must not be called by these checks")


module("app.task_refs", task_ref=lambda value, *_args, **_kwargs: str(value))
module("app.errtext", err_text=str)
module("app.acceptance", FAILED="failed", INCONCLUSIVE="inconclusive", PASSED="passed", SKIPPED="skipped")
module("app.workspace", inspect_worktree_identity=forbidden)
module("app.ia", __path__=[])
module("app.ia.merge_receipts", merge_receipt_configured=lambda: False)
db = module("app.db", DB_PATH=None)


@contextmanager
def connection():
    conn = sqlite3.connect(db.DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_db():
    with connection() as conn:
        conn.executescript("""
            CREATE TABLE merge_operations (
                operation_id TEXT PRIMARY KEY, operation_type TEXT, session_id TEXT,
                scope TEXT, worker_name TEXT, request_json TEXT, request_hash TEXT,
                dedupe_fingerprint TEXT, accepted_worker_branch TEXT, accepted_worker_head TEXT,
                accepted_base_branch TEXT, accepted_task_id TEXT, accepted_needs_switch INTEGER,
                accepted_admission_json TEXT DEFAULT '{}', state TEXT, commit_point TEXT,
                result_json TEXT, result_hash TEXT, created_at TEXT, updated_at TEXT,
                resolved_at TEXT, resolution_evidence_hash TEXT,
                owner_token TEXT DEFAULT '', started_at TEXT, finished_at TEXT,
                finalization_stage TEXT DEFAULT '', finalization_json TEXT DEFAULT '{}',
                terminal_worker_branch TEXT, terminal_worker_head TEXT,
                terminal_base_branch TEXT, terminal_task_id TEXT, terminal_needs_switch INTEGER
            );
            CREATE UNIQUE INDEX idx_merge_operations_active_session ON merge_operations(session_id)
                WHERE resolved_at IS NULL AND state IN ('PENDING','RUNNING','PARTIAL','UNKNOWN');
            CREATE TABLE sessions (id TEXT PRIMARY KEY, payload TEXT);
        """)


def save_session(row):
    import json
    with connection() as conn:
        conn.execute("INSERT OR REPLACE INTO sessions VALUES (?, ?)", (row["id"], json.dumps(row)))


def get_session(session_id):
    import json
    with connection() as conn:
        row = conn.execute("SELECT payload FROM sessions WHERE id=?", (session_id,)).fetchone()
    return json.loads(row["payload"]) if row else None


db._conn = connection
db.init_db = init_db
db.save_session = save_session
db.get_session = get_session
db.get_session_by_name = forbidden
# These imports are needed only to collect the supplied gate test module. Selected
# runner/batching tests never use its unavailable acceptance/task fixtures.
module("tests.task_seeds", create_task=forbidden)
module("tests.test_acceptance", _run_with_spy=forbidden, _session_row=forbidden, worker_head=forbidden)

import pytest
import app.merge_operations as operations
import app.merge_test_gate as gate

print("PARTIAL-COPY HARNESS: synthetic missing imports/schema; real operation and gate source")
assert Path(operations.__file__).samefile(ROOT / "app/merge_operations.py")
assert Path(gate.__file__).samefile(ROOT / "app/merge_test_gate.py")
print("Imported operations:", operations.__file__)
print("Imported gate:", gate.__file__)
if "--probe" in sys.argv:
    import json
    import os

    project = ROOT / ".orchestra/tasks/V-1145/tmp/cli-probe"
    project.mkdir(parents=True, exist_ok=True)
    if not (project / ".venv").exists():
        (project / ".venv").symlink_to(sys.prefix, target_is_directory=True)
    (project / "test_probe.py").write_text(
        "import threading\n"
        "def test_hang():\n    threading.Event().wait()\n"
        "def test_after_hang():\n    assert True\n",
    )
    os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    os.environ.pop("PYTEST_PLUGINS", None)
    os.environ.pop("PYTEST_ADDOPTS", None)
    for case in ("autoload_disabled", "timeout_plugin_explicitly_enabled"):
        if case == "timeout_plugin_explicitly_enabled":
            os.environ["PYTEST_ADDOPTS"] = "-p pytest_timeout"
            gate.PER_TEST_TIMEOUT_SECONDS = 1
        result = gate.run_pytest(str(project), ["test_probe.py"], timeout=10)
        print("CASE:", case)
        print(json.dumps(result, ensure_ascii=False, indent=2).replace(str(ROOT), "<COPY_ROOT>"))
    raise SystemExit(0)
if "--mutate-coarse-recovery" in sys.argv:
    sys.argv.remove("--mutate-coarse-recovery")
    original = operations._test_gate_recovery

    def coarse_recovery(evidence):
        action, details = original(evidence)
        if evidence["status"] != "failed":
            action = {"code": "TEST_GATE_UNFINISHED", "message": "legacy coarse diagnosis"}
        return action, details

    operations._test_gate_recovery = coarse_recovery
    print("MUTATION: every non-red gate gets the legacy timeout action")
if "--mutate-skipped-passed" in sys.argv:
    sys.argv.remove("--mutate-skipped-passed")
    original_batch = gate._batch_result

    def skipped_passed(*args, **kwargs):
        evidence = original_batch(*args, **kwargs)
        if evidence["status"] == "skipped":
            evidence.update(status="passed", reason="", exit_code=0)
        return evidence

    gate._batch_result = skipped_passed
    print("MUTATION: restore old PASSED aggregation for skipped batches")
raise SystemExit(pytest.main(sys.argv[1:]))
