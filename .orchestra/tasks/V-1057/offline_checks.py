"""Offline method/SQL checks for the deliberately partial hub copy.

Not a substitute for uv/pytest: unavailable application modules and schema.sql are
represented by a minimal SQLite schema and import stubs. Production methods are
compiled from their actual source AST, without copying their implementations.
Run from the checkout root with python3; no providers, network, or extra packages.
"""
import ast
import asyncio
import enum
import importlib.util
import logging
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[3]
TASK = Path(__file__).resolve().parent
(TASK / "tmp").mkdir(exist_ok=True)
tempfile.tempdir = str(TASK / "tmp")
sys.path.insert(0, str(ROOT))
import app
print("app namespace:", list(app.__path__))
print("Mode: extracted production methods + minimal offline schema/import stubs")

mutation = sys.argv[1] if len(sys.argv) > 1 else ""


def module(name):
    result = ModuleType(name)
    sys.modules[name] = result
    parent, _, child = name.rpartition(".")
    setattr(sys.modules[parent], child, result)
    return result


def extract(target, path, *, functions=(), classes=None):
    source = ast.parse((ROOT / path).read_text())
    selected = []
    for node in source.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in functions:
            selected.append(node)
        if isinstance(node, ast.ClassDef) and node.name in (classes or {}):
            methods = classes[node.name]
            if methods is not None:
                node.decorator_list = []
                node.body = [member for member in node.body
                             if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
                             and member.name in methods]
            selected.append(node)
    tree = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
                            *selected], type_ignores=[])
    if path == "app/manager.py":
        if mutation == "no-abrupt-capture":
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.startswith(
                    "INSERT OR IGNORE INTO restart_cut_turns(session_id)"
                ):
                    node.value = node.value.replace("status IN ('running', 'interrupted')", "status = 'interrupted'")
        elif mutation == "drop-pending-on-startup":
            class DropPending(ast.NodeTransformer):
                def visit_Expr(self, node):
                    if any(isinstance(child, ast.Constant) and isinstance(child.value, str)
                           and child.value.startswith("UPDATE sessions SET status='idle'")
                           for child in ast.walk(node)):
                        return [node, ast.parse('c.execute("DELETE FROM restart_cut_turns")').body[0]]
                    return node
            tree = DropPending().visit(tree)
    ast.fix_missing_locations(tree)
    exec(compile(tree, str(ROOT / path), "exec"), target.__dict__)


class AgentStatus(str, enum.Enum):
    RUNNING = "running"
    INTERRUPTED = "interrupted"
    IDLE = "idle"
    WAITING = "waiting"


db = module("app.db")
db.__dict__.update(Path=Path, sqlite3=sqlite3, DB_PATH=TASK / "unused.db")
extract(db, "app/db.py", functions=("_conn", "_ensure_restart_cut_turns_schema", "acknowledge_restart_cut_turns",
                                   "_ensure_usage_analytics_schema", "_ensure_session_model_reasons_schema", "init_db"),
        classes={"OwnedConnection": None})
for node in ast.parse((ROOT / "app/db.py").read_text()).body:
    if isinstance(node, ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in {"_USAGE_ANALYTICS_INDEXES", "SCHEMA_VERSION"}:
                setattr(db, target.id, ast.literal_eval(node.value))
production_init_db = db.init_db


def init_db():
    with db._conn() as connection:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY, name TEXT, scope TEXT, cwd TEXT, model TEXT,
                created_at TEXT, status TEXT, session_id TEXT, parent_name TEXT,
                role TEXT, pipeline TEXT, is_orchestrator INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY, session_id TEXT, ts TEXT, type TEXT, content TEXT
            );
            CREATE TABLE IF NOT EXISTS turn_usage (ts TEXT);
            CREATE TABLE IF NOT EXISTS subagents (started_at TEXT);
            CREATE TABLE IF NOT EXISTS tool_errors (ts TEXT);
            CREATE TABLE IF NOT EXISTS voice_costs (ts TEXT);
        """)
        connection.execute("PRAGMA user_version=3")
    # Exercise the actual current-schema upgrade branch. Fresh database creation
    # from the unavailable schema.sql remains outside this offline check.
    production_init_db()


def add_log(session_id, ts, kind, content, *, provenance=None):
    with db._conn() as connection:
        connection.execute("INSERT INTO logs(session_id,ts,type,content) VALUES (?,?,?,?)",
                           (session_id, ts.isoformat(), kind, content))


db.init_db = init_db
db.add_log = add_log
module("app.events").MessageProvenance = SimpleNamespace
module("app.turn_signals").record_interrupted_by_restart = Mock()
module("app.bg_jobs").bg_manager = SimpleNamespace(has_active_jobs=Mock())
session = module("app.session")
session.__dict__.update(asyncio=asyncio, AgentStatus=AgentStatus)
extract(session, "app/session.py", classes={"AgentSession": ("stop", "interrupt")})
manager = module("app.manager")
manager.__dict__.update(
    asyncio=asyncio, Path=Path, logger=logging.getLogger("offline.manager"),
    AgentStatus=AgentStatus, MessageProvenance=SimpleNamespace,
    is_orchestrator_role=lambda role: role == "orchestrator",
    platform_interruption_notice=lambda reason, task: "Continue the task.",
    _RESTART_REPLAY_LIMIT=20000, list_latest_runtime_handoffs=lambda: [],
    spawn_supervised=lambda *args: None,
)
extract(manager, "app/manager.py", functions=("restart_notice_text",), classes={"SessionManager": (
    "__init__", "auto_resume_all", "_signal_restart_cut_turns", "_inject_restart_notice", "shutdown_all",
)})
# These are deliberate test seams; the tests replace both before exercising startup.
manager.SessionManager.reconcile_live_colors = lambda self: None
main = module("app.main")
main.drain_mutating_requests = Mock()
main.inflight_mutating_count = Mock()
module("app.routes").__path__ = [str(ROOT / "app/routes")]
system = module("app.routes.system")
import time
system.__dict__.update(time=time, os=os, logger=logging.getLogger("offline.system"),
                       manager=None, _drain_sessions=Mock(), _drain_restart_durable_state=Mock(),
                       _record_restart_outcome_bounded=Mock(), _arm_supervisor_exit_guard=Mock())
extract(system, "app/routes/system.py", functions=("_do_restart_service",))

spec = importlib.util.spec_from_file_location("offline_tests_1057", ROOT / "tests/test_restart_cut_recovery_1057.py")
tests = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tests)
if mutation:
    name = {"no-abrupt-capture": "test_abrupt_stop_running_is_resumed_once_without_cut_names",
            "drop-pending-on-startup": "test_second_crash_before_staggered_notice_keeps_cut_turn"}[mutation]
    suite = unittest.TestSuite([tests.RestartCutRecoveryTests(name)])
else:
    suite = unittest.defaultTestLoader.loadTestsFromModule(tests)
result = unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(not result.wasSuccessful())
