"""Limited stdlib-only fallback, not a substitute for the required pytest checks.

Import real app.models with an unused httpx stub; stub the hub configuration
boundary because the private copy lacks backend_hub's dependencies. Execute the
new test bodies unchanged, stripping pytest decorators only. No E2E simulation.
"""

import ast
import importlib
from pathlib import Path
import sys
import types
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True
sys.modules["httpx"] = types.ModuleType("httpx")
hub = types.ModuleType("app.backend_hub")
hub.hub_configured = lambda: "not configured"
sys.modules["app.backend_hub"] = hub
models = importlib.import_module("app.models")
print(f"Imported app: {list(importlib.import_module('app').__path__)}")
print(f"Imported app.models: {models.__file__}")


class MonkeyPatch:
    def __init__(self):
        self.patches = []

    def setattr(self, target, value):
        p = patch(target, value)
        p.start()
        self.patches.append(p)

    def undo(self):
        for p in reversed(self.patches):
            p.stop()


source = (ROOT / "app/models.py").read_text()
tree = ast.parse((ROOT / "tests/test_models.py").read_text())
tests = [node for node in tree.body if isinstance(node, ast.FunctionDef)
         and node.name.startswith("test_hub_alternative_hint_")]
namespace = {"hub_alternative_hint": models.hub_alternative_hint}
for node in tests:
    node.decorator_list = []
exec(compile(ast.Module(body=tests, type_ignores=[]), "tests/test_models.py", "exec"), namespace)
cases = {
    "test_hub_alternative_hint_defaults_to_sol_for_any_work":
        [None, "claude-opus-5-5[1m]", "gpt-6.1-sol", "sonnet", "sol"],
    "test_hub_alternative_hint_is_empty_when_unconfigured":
        [None, "claude-opus-5-5[1m]", "gpt-6.1-sol"],
    "test_hub_alternative_hint_is_empty_for_other_runtimes_and_unknown_models":
        ["hubsol", "hubsonnet", "grok", "missing-model"],
}


def run_case(name, model):
    monkeypatch = MonkeyPatch()
    try:
        namespace[name](model, monkeypatch)
    finally:
        monkeypatch.undo()


for name, inputs in cases.items():
    for model in inputs:
        run_case(name, model)
print("PASS: all 12 new hint test cases (stdlib fallback)")

old_return = '''    choice = {"codex": "'hubsol'", "claude": "'hubsonnet'"}.get(
        runtime, "'hubsol' (Codex-class work) or 'hubsonnet' (Claude-class work)")
    return (f"The MultiCode hub pool has its own quota: spawn the worker with model={choice} "
            "instead of waiting.")'''
hint = next(n for n in ast.parse(source).body
            if isinstance(n, ast.FunctionDef) and n.name == "hub_alternative_hint")
fixed_hint = ast.get_source_segment(source, hint)
old_hint = fixed_hint[:fixed_hint.index('    return ("The MultiCode')]
old_hint = old_hint.replace("    if model_id:", "    runtime = None\n    if model_id:") + old_return
mutants = [
    ("old routing text", old_hint, list(cases)[0]),
    ("ignore missing hub configuration", fixed_hint.replace(
        "if hub_configured() is not None:", "if False:"), list(cases)[1]),
    ("hint for other runtimes", fixed_hint.replace(
        'if runtime not in ("claude", "codex"):', "if False:"), list(cases)[2]),
]
for label, mutant_source, test_name in mutants:
    mutant_namespace = dict(vars(models))
    exec(compile(mutant_source, "<mutation>", "exec"), mutant_namespace)
    namespace["hub_alternative_hint"] = mutant_namespace["hub_alternative_hint"]
    rejected = 0
    for model in cases[test_name]:
        try:
            run_case(test_name, model)
        except AssertionError:
            rejected += 1
    assert rejected, f"Mutation survived: {label}"
    print(f"PASS: mutation rejected: {label} ({rejected} cases)")

for path in ("app/models.py", "tests/test_models.py", "tests/test_quota_admission_e2e.py"):
    compile((ROOT / path).read_text(), str(ROOT / path), "exec")
print("PASS: syntax compilation for all 3 changed source/test files")
