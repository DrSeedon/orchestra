"""Run V-1035's unittest cases without installing SDK/HTTP dependencies.

The recovery methods are compiled verbatim from the source AST. Their containing
modules' unrelated imports are omitted. db, limit_wake, events and session_state
are imported normally. HTTP usage reads are mocked by the test suite. This checks
behavior, but does not replace the project's uv/pytest integration run.
"""
import ast
import asyncio
import io
import logging
import resource
import sys
import tempfile
import types
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT))
ARTIFACTS = ROOT / ".orchestra/tasks/V-1035"
tempfile.tempdir = str(ARTIFACTS)
resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))
logging.disable(logging.CRITICAL)

import app
from app import db, errtext, events, limit_wake, session_state, tasks

print("Imported app:", app.__file__)
print("Offline check: exact recovery methods extracted from source; no real SDK or HTTP imports.")


def extract_module(name, path, names, methods=None):
    source = Path(path).read_text()
    tree = ast.parse(source, filename=path)
    selected = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name in names:
            if isinstance(node, ast.ClassDef) and methods is not None:
                node.decorator_list = []
                node.body = [item for item in node.body if isinstance(
                    item, (ast.FunctionDef, ast.AsyncFunctionDef),
                ) and item.name in methods]
            selected.append(node)
        elif isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id in names for target in node.targets
        ):
            selected.append(node)
    selected.insert(0, ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0))
    module = types.ModuleType(name)
    module.__file__ = str(ROOT / path)
    module.__dict__.update({
        "asyncio": asyncio, "logger": logging.getLogger(name), "Path": Path,
        "MessageProvenance": events.MessageProvenance,
        "AgentStatus": session_state.AgentStatus,
        "platform_interruption_notice": session_state.platform_interruption_notice,
        "err_text": errtext.err_text, "spawn_supervised": tasks.spawn_supervised,
        "list_latest_runtime_handoffs": db.list_latest_runtime_handoffs,
        "is_orchestrator_role": lambda role: role in {"orchestrator", "sub-orchestrator"},
        "get_runtime": Mock(side_effect=AssertionError("unexpected runtime access")),
    })
    exec(compile(ast.fix_missing_locations(ast.Module(body=selected, type_ignores=[])), path, "exec"),
         module.__dict__)
    sys.modules[name] = module
    setattr(app, name.rsplit(".", 1)[-1], module)
    return module


manager = extract_module("app.manager", "app/manager.py", {"_RESTART_REPLAY_LIMIT", "restart_notice_text", "SessionManager"},
                         {"__init__", "auto_resume_all", "_signal_restart_cut_turns", "_inject_restart_notice"})
session = extract_module("app.session", "app/session.py", {"AgentSession"}, {"_persistent_event_loop"})
hibernate = extract_module("app.session_hibernate", "app/session_hibernate.py",
                           {"HEARTBEAT_INTERVAL", "HibernateManager"},
                           {"__init__", "heartbeat_loop", "_signal_silence_once"})

# Do not import FastAPI or read any provider configuration in the offline runner.
import app.routes
system = types.ModuleType("app.routes.system")
system.current_provider_usage = Mock(side_effect=AssertionError("unexpected HTTP usage read"))
sys.modules[system.__name__] = system
app.routes.system = system

from tests import test_interruption_honest_v1035 as checks

result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(checks))
if not result.wasSuccessful():
    sys.exit(1)

existing_test = "test_dead_listener_heartbeat_uses_session_reconnect_path"
existing_path = "tests/test_session_hibernate.py"
existing_tree = ast.parse(Path(existing_path).read_text(), filename=existing_path)
existing_node = next(node for node in existing_tree.body if isinstance(
    node, ast.AsyncFunctionDef,
) and node.name == existing_test)
existing_node.decorator_list = []
namespace = {
    "SimpleNamespace": types.SimpleNamespace, "AsyncMock": AsyncMock,
    "MagicMock": MagicMock, "asyncio": asyncio,
    "AgentStatus": session_state.AgentStatus, "HibernateManager": hibernate.HibernateManager,
}
exec(compile(ast.fix_missing_locations(ast.Module(body=[existing_node], type_ignores=[])),
             existing_path, "exec"), namespace)
with ExitStack() as patches:
    monkeypatch = types.SimpleNamespace(setattr=lambda obj, name, value: patches.enter_context(
        patch.object(obj, name, value),
    ))
    patches.enter_context(patch.object(hibernate, "get_runtime", return_value=types.SimpleNamespace(
        capabilities=types.SimpleNamespace(reconnect=True),
    )))
    asyncio.run(namespace[existing_test](monkeypatch))
print("Existing heartbeat regression passed (exact test body, isolated runtime metadata).")

if "--mutations" not in sys.argv:
    sys.exit(0)


def replace_function(module, path, qualname, before, after):
    source = Path(path).read_text()
    if source.count(before) != 1:
        raise AssertionError(f"mutation match is not unique: {path}: {before}")
    tree = ast.parse(source.replace(before, after), filename=path)
    parts = qualname.split(".")
    nodes = tree.body
    owner = module
    for part in parts[:-1]:
        nodes = next(node for node in nodes if isinstance(node, ast.ClassDef) and node.name == part).body
        owner = getattr(owner, part)
    node = next(node for node in nodes if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == parts[-1])
    namespace = module.__dict__.copy()
    fragment = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), node], type_ignores=[])
    exec(compile(ast.fix_missing_locations(fragment), path, "exec"), module.__dict__, namespace)
    original = getattr(owner, parts[-1])
    setattr(owner, parts[-1], namespace[parts[-1]])
    return owner, parts[-1], original


mutations = [
    ("restart loses refusal explanation", manager, "app/manager.py", "restart_notice_text",
     '+ platform_interruption_notice("Orchestra restart", row.get("task_id") or "")', '+ ""',
     checks.NoticeTests, "test_saved_restart_explains_cli_refusal_before_restored_conversation"),
    ("restart sent to parent", manager, "app/manager.py", "SessionManager._inject_restart_notice",
     'session.id, restart_notice_text(row), provenance=provenance', '"parent", restart_notice_text(row), provenance=provenance',
     checks.DeliveryTests, "test_restart_routes_to_cut_worker_without_parent_or_native_session"),
    ("cut worker never resumed", manager, "app/manager.py", "SessionManager.auto_resume_all",
     'elif row["id"] in was_running:', 'elif False:',
     checks.DeliveryTests, "test_restart_routes_to_cut_worker_without_parent_or_native_session"),
    ("restart ignores manual stop", manager, "app/manager.py", "SessionManager._inject_restart_notice",
     'if getattr(session, "_manually_interrupted", False) is True:', 'if False:',
     checks.DeliveryTests, "test_manual_stop_during_restart_stagger_cancels_automatic_continuation"),
    ("limit loses refusal explanation", limit_wake, "app/limit_wake.py", "run_wake_job",
     '+ platform_interruption_notice("subscription limit", agent.get("task_id") or "")', '+ "Continue your work."',
     checks.DeliveryTests, "test_limit_reset_resumes_worker_directly_with_current_task_for_both_providers"),
    ("limit sent to parent", limit_wake, "app/limit_wake.py", "run_wake_job",
     'session.id, message, provenance=provenance', '"parent", message, provenance=provenance',
     checks.DeliveryTests, "test_limit_reset_resumes_worker_directly_with_current_task_for_both_providers"),
    ("limit loses task reference", limit_wake, "app/limit_wake.py", "run_wake_job",
     'agent.get("task_id") or ""', '""',
     checks.DeliveryTests, "test_limit_reset_resumes_worker_directly_with_current_task_for_both_providers"),
    ("restart continuation excluded from limit wake", limit_wake, "app/limit_wake.py", "_not_worth_waking",
     'and not _is_interruption_recovery_log(row)', 'and True',
     checks.NoticeTests, "test_recovery_after_limit_is_not_filtered_as_an_incidental_system_notice"),
    ("limit ignores manual stop", limit_wake, "app/limit_wake.py", "run_wake_job",
     'or getattr(session, "_manually_interrupted", False) is True', 'or False',
     checks.DeliveryTests, "test_limit_reset_does_not_override_manual_stop_or_newer_turn"),
    ("limit duplicates a reconciled claim", limit_wake, "app/limit_wake.py", "run_wake_job",
     'if _wake_token_seen(target_id, delivery["token"]):', 'if False:',
     checks.DeliveryTests, "test_replayed_claim_is_reconciled_without_another_wake"),
    ("listener loses honest notice", session, "app/session.py", "AgentSession._persistent_event_loop",
     '"[system] " + platform_interruption_notice("backend disconnect", self.task_id)', '"[system] Continue."',
     checks.DeliveryTests, "test_reconnected_listener_sends_honest_continuation_with_provenance"),
    ("heartbeat loses honest notice", hibernate, "app/session_hibernate.py", "HibernateManager.heartbeat_loop",
     '"[system] " + platform_interruption_notice(\n                                "backend disconnect", getattr(s, "task_id", ""),\n                            )', '"[system] Continue."',
     checks.DeliveryTests, "test_heartbeat_reconnect_uses_same_honest_notice"),
    ("heartbeat requires optional task metadata", hibernate, "app/session_hibernate.py", "HibernateManager.heartbeat_loop",
     'getattr(s, "task_id", "")', 's.task_id',
     checks.DeliveryTests, "test_heartbeat_without_task_metadata_still_delivers_continuation"),
]

for label, module, path, qualname, before, after, case, test in mutations:
    owner, name, original = replace_function(module, path, qualname, before, after)
    output = io.StringIO()
    try:
        result = unittest.TextTestRunner(stream=output).run(unittest.TestSuite([case(test)]))
    finally:
        setattr(owner, name, original)
    if result.errors or not result.failures:
        print("Mutation NOT killed by an assertion:", label)
        print(output.getvalue())
        sys.exit(1)
    print("KILLED:", label)
print(f"All {len(mutations)} mutations killed by behavioral assertions; source files unchanged.")
