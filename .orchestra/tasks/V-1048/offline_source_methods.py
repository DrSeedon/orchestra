"""Partial-environment checks, NOT a replacement for the required uv/pytest run.

The hub has httpx in an existing service interpreter but lacks pytest and dotenv.
Import the real backend and execute the unchanged session/manager method bodies
from their AST, with only their surrounding application dependencies substituted.
All assertions come from the committed regression tests.
"""

import ast
import asyncio
import io
import json
import logging
import os
import sys
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

import app
from app import backend_hub as hub
import test_hub_switch_orphan as regression


def method(source, cls, name):
    tree = ast.parse((ROOT / source).read_text())
    owner = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls)
    return next(n for n in owner.body if isinstance(n, ast.AsyncFunctionDef) and n.name == name)


def compile_method(node, namespace):
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])),
                 "<production method body>", "exec"), namespace)
    return namespace[node.name]


def partial_modules():
    session = types.ModuleType("app.session")
    session.save_session = Mock()
    namespace = session.__dict__
    namespace.update(asyncio=asyncio, json=json, datetime=datetime, timezone=timezone,
                     logger=logging.getLogger("app.session"), err_text=str,
                     get_model_spec=lambda _: SimpleNamespace(runtime="codex"),
                     empty_context=dict, _db_executor=lambda: None)

    class Session:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)
            self.session_id_history = []

        def _to_db_dict(self):
            return {"session_id": self.session_id, "model": self.model}

    Session._change_runtime_chat_locked = compile_method(
        method("app/session.py", "AgentSession", "_change_runtime_chat_locked"), namespace)
    session.AgentSession = Session
    manager = types.ModuleType("app.manager")
    manager.__dict__.update(asyncio=asyncio, os=os, logger=logging.getLogger("app.manager"),
                            get_all_sessions=Mock())
    manager.SessionManager = type("SessionManager", (), {
        "_periodic_hub_sweep": compile_method(
            method("app/manager.py", "SessionManager", "_periodic_hub_sweep"), manager.__dict__)})
    return session, manager


def check_suite(names, expect_success):
    suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(name, regression) for name in names)
    output = io.StringIO()
    result = unittest.TextTestRunner(stream=output, verbosity=1).run(suite)
    if expect_success != result.wasSuccessful() or result.errors:
        print(output.getvalue())
        raise SystemExit("unexpected regression result")
    return result.testsRun, len(result.failures)


def without_release(node):
    class RemoveRelease(ast.NodeTransformer):
        def visit_Try(self, current):
            if any(isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                   and call.func.id == "release_for_worktree" for call in ast.walk(current)):
                return ast.Pass()
            return self.generic_visit(current)
    return RemoveRelease().visit(node)


session, manager = partial_modules()
with patch.dict(sys.modules, {"app.session": session, "app.manager": manager}), \
        patch.object(app, "session", session, create=True), patch.object(app, "manager", manager, create=True):
    count, _ = check_suite(["HubSessionSwitchTests", "HubPeriodicSweepTests"], True)
    print(f"Partial source-method checks: {count} passed (session/manager surroundings substituted)")

    broken = compile_method(without_release(method("app/backend_hub.py", "HubBackend", "_run_turn")),
                            dict(hub.__dict__))
    with patch.object(hub.HubBackend, "_run_turn", broken):
        _, failed = check_suite(["HubWorkspaceLifecycleTests.test_fresh_backend_releases_all_previous_copies_only"], False)
    print(f"Mutation: removing replacement cleanup -> {failed} expected assertion failure")

    source = ast.parse((ROOT / "app/backend_hub.py").read_text())
    sweep = next(n for n in source.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "sweep_orphans")
    for node in ast.walk(sweep):
        if isinstance(node, ast.If) and any(isinstance(n, ast.Name) and n.id == "worktree" for n in ast.walk(node.test)):
            node.test = ast.parse("worktree in live and Path(state.worktree).is_dir()", mode="eval").body
            break
    with patch.object(hub, "sweep_orphans", compile_method(sweep, dict(hub.__dict__))):
        _, failed = check_suite(["HubWorkspaceLifecycleTests.test_sweep_uses_current_id_even_for_existing_worktree"], False)
    print(f"Mutation: restoring worktree-only sweep -> {failed} expected assertion failure")

    broken = compile_method(without_release(method("app/session.py", "AgentSession", "_change_runtime_chat_locked")),
                            session.__dict__)
    with patch.object(session.AgentSession, "_change_runtime_chat_locked", broken):
        _, failed = check_suite(["HubSessionSwitchTests.test_hub_to_local_releases_after_persisted_switch"], False)
    print(f"Mutation: removing hub-to-local cleanup -> {failed} expected assertion failure")

    periodic = method("app/manager.py", "SessionManager", "_periodic_hub_sweep")
    for node in ast.walk(periodic):
        if isinstance(node, ast.Try):
            node.body = [n for n in node.body if not isinstance(n, ast.For)]
            for assignment in node.body:
                if (isinstance(assignment, ast.Assign)
                        and any(isinstance(t, ast.Name) and t.id == "live" for t in assignment.targets)):
                    assignment.value = ast.parse(
                        "{r['worktree_path'] for r in rows if r.get('worktree_path')}", mode="eval").body
            break
    with patch.object(manager.SessionManager, "_periodic_hub_sweep",
                      compile_method(periodic, manager.__dict__)):
        _, failed = check_suite([
            "HubPeriodicSweepTests.test_running_backend_workspace_is_protected_before_db_catches_up"], False)
    print(f"Mutation: restoring path-only manager snapshot -> {failed} expected assertion failure")

print("Imported app resolves to this checkout:", Path(app.__file__).resolve() == ROOT / "app/__init__.py")
