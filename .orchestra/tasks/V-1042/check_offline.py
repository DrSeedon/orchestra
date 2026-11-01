"""Limited stdlib checks for the supplied partial checkout; not the pytest gate."""
from __future__ import annotations

import ast
import copy
import os
import subprocess
import sys
import tempfile
import types
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def definition(path, name):
    tree = ast.parse((ROOT / path).read_text(), filename=path)
    return next(node for node in tree.body if getattr(node, "name", None) == name)


def execute(node, namespace):
    exec(compile(ast.Module(body=[node], type_ignores=[]), "<extracted source>", "exec"), namespace)


def check_child_logging():
    child_node = definition("tests/test_fan_terminal_kind.py", "_Child")
    manager_node = definition("app/session_turns.py", "TurnManager")
    manager_node.body = [
        method for method in manager_node.body
        if getattr(method, "name", None) in {"__init__", "fire_auto_report"}
    ]
    namespace = {"is_successful_silent_turn": lambda *_: False}
    execute(manager_node, namespace)
    execute(child_node, namespace)
    import app

    # Only the already-released fan lookup is available in this partial checkout.
    fan = types.ModuleType("app.fan_barrier")
    fan.should_buffer = lambda *_: False
    with patch.dict(sys.modules, {"app.fan_barrier": fan}), patch.object(app, "fan_barrier", fan, create=True):
        child = namespace["_Child"]("c1", did_report=True, turn_logs=["result"])
        namespace["TurnManager"](child).fire_auto_report()
        assert len(child.logs) == 1 and child.logs[0][0] == "status"
        assert child._auto_report_task is None
        print("PASS: actual fire_auto_report logs the explicit-report skip using the fixed stub")

        reverted = copy.deepcopy(child_node)
        reverted.body = [method for method in reverted.body if getattr(method, "name", None) != "_log"]
        execute(reverted, namespace)
        child = namespace["_Child"]("c1", did_report=True, turn_logs=["result"])
        try:
            namespace["TurnManager"](child).fire_auto_report()
        except AttributeError as error:
            assert "_log" in str(error)
            print("RED confirmed: removing _Child._log reproduces", repr(error))
        else:
            raise AssertionError("reverting the stub fix did not reproduce the failure")


def check_fixture_override():
    node = definition("tests/conftest.py", "_isolate_forbidden_strings")
    node.decorator_list = []
    namespace = {}
    execute(node, namespace)
    import app

    from app import forbidden_strings as module
    sandbox = ROOT / ".orchestra/tasks/V-1042"

    class EnvironmentPatch:
        def setenv(self, name, value):
            os.environ[name] = value

    with patch.dict(sys.modules, {"app.forbidden_strings": module}), patch.object(app, "forbidden_strings", module, create=True), patch.dict(os.environ, {module.ENV_VAR: "inherited-live-path"}):
        namespace["_isolate_forbidden_strings"](sandbox, EnvironmentPatch())
        assert os.environ[module.ENV_VAR] == str(sandbox / "forbidden-strings.txt")
        print("PASS: fixture overrides an inherited path with a nonexistent sandbox list")


class MonkeyPatch:
    def __init__(self, stack):
        self.stack = stack

    def setenv(self, name, value):
        self.stack.enter_context(patch.dict(os.environ, {name: value}))

    def setattr(self, owner, name, value):
        self.stack.enter_context(patch.object(owner, name, value))


def check_scanner_regressions():
    from app import forbidden_strings

    namespace = {
        "subprocess": subprocess, "Path": Path, "forbidden_strings": forbidden_strings,
        "SECRET": "hub-user-7f3a91",
        "pytest": types.SimpleNamespace(raises=lambda kind, match: unittest.TestCase().assertRaisesRegex(kind, match)),
    }
    names = (
        "_git", "_repo", "_branch", "_rules",
        "test_blocks_added_line_and_names_rule_without_value",
        "test_blocks_commit_message_and_path",
        "test_allows_clean_change_and_removal_of_a_leak",
        "test_missing_list_allows_everything",
        "test_default_list_is_isolated_from_live_checkout",
        "test_orphan_branch_is_scanned_without_a_merge_base",
        "test_merge_base_failure_is_not_treated_as_unrelated_history",
    )
    for name in names:
        node = definition("tests/test_publish_guard.py", name)
        node.decorator_list = []
        execute(node, namespace)
    fixture = definition("tests/conftest.py", "_isolate_forbidden_strings")
    fixture.decorator_list = []
    execute(fixture, namespace)

    def run(name, *args):
        with tempfile.TemporaryDirectory(dir=ROOT / ".orchestra/tasks/V-1042") as directory, ExitStack() as stack:
            temporary = Path(directory)
            monkeypatch = MonkeyPatch(stack)
            namespace["_isolate_forbidden_strings"](temporary, monkeypatch)
            if name == "test_merge_base_failure_is_not_treated_as_unrelated_history":
                args = (monkeypatch,)
            namespace[name](temporary, *args)

    for name in names[4:]:
        if name == "test_orphan_branch_is_scanned_without_a_merge_base":
            for location in ("content", "shared_content", "path", "message", "clean"):
                run(name, location)
                print(f"PASS: {name}[{location}]")
        else:
            run(name)
            print("PASS:", name)

    node = copy.deepcopy(fixture)
    node.body[-1] = ast.copy_location(ast.Pass(), node.body[-1])
    execute(node, namespace)
    with patch.dict(os.environ, {forbidden_strings.ENV_VAR: str(ROOT / ".orchestra/tasks/V-1042/inherited-list.txt")}):
        try:
            run("test_default_list_is_isolated_from_live_checkout")
        except AssertionError:
            print("RED confirmed: disabling the fixture override fails the added isolation regression")
        else:
            raise AssertionError("fixture mutation survived")
    execute(fixture, namespace)

    scanner = definition("app/forbidden_strings.py", "scan_range")
    original_patch = ast.parse('patch = git("diff", "--no-renames", "-U0", f"{base}...{head}")').body[0]
    retained = []
    for node in scanner.body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id in {"merge_base", "diff_refs"} for target in node.targets):
            continue
        if isinstance(node, ast.If) and ast.unparse(node.test) == "merge_base.returncode not in (0, 1)":
            continue
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "patch" for target in node.targets):
            node = ast.copy_location(original_patch, node)
        retained.append(node)
    scanner.body = retained
    mutated = dict(vars(forbidden_strings))
    execute(scanner, mutated)
    with patch.object(forbidden_strings, "scan_range", mutated["scan_range"]):
        for location in ("content", "shared_content", "path", "message", "clean"):
            try:
                run("test_orphan_branch_is_scanned_without_a_merge_base", location)
            except RuntimeError as error:
                assert "no merge base" in str(error)
                print(f"RED confirmed: reverting the scanner fallback fails orphan regression [{location}]")
            else:
                raise AssertionError("scanner mutation survived")

    source = (ROOT / "app/forbidden_strings.py").read_text()
    target_diff = source.replace('(\"4b825dc642cb6eb9a060e54bf8d69288fbee4904\", head)', '(base, head)')
    assert target_diff != source
    mutated = dict(vars(forbidden_strings))
    exec(compile(target_diff, "<target-tip mutation>", "exec"), mutated)
    with patch.object(forbidden_strings, "scan_range", mutated["scan_range"]):
        try:
            run("test_orphan_branch_is_scanned_without_a_merge_base", "shared_content")
        except AssertionError:
            print("RED confirmed: target-tip diff misses shared forbidden content; empty-tree regression catches it")
        else:
            raise AssertionError("target-tip mutation survived")


if __name__ == "__main__":
    for relative in (
        "app/forbidden_strings.py", "tests/conftest.py", "tests/test_fan_terminal_kind.py", "tests/test_publish_guard.py",
    ):
        compile((ROOT / relative).read_text(), str(ROOT / relative), "exec")
    print("PASS: changed Python files compile")
    check_child_logging()
    check_fixture_override()
    check_scanner_regressions()
    import app

    print("app search locations:", list(app.__path__))
    print("app.__file__:", app.__file__)
    print("LIMIT: full application dependencies and pytest are absent; this is not the pytest gate")
