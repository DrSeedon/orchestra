"""Supplemental AST check for the sparse hub copy; NOT the repository integration run.

Run with --confcutdir=.orchestra/tasks/V-1147. Execute the checked-in regression
unchanged, using the real preamble/parser/executor definitions. Missing role/prompt
and delivery-receipt dependencies are synthetic; no network or API is used.
"""

import ast
import json
import os
from pathlib import Path
import re
import sys
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]


def load_definitions(path, namespace, names):
    tree = ast.parse(path.read_text(), filename=str(path))
    tree.body = [node for node in tree.body if getattr(node, "name", None) in names
                 or isinstance(node, ast.Assign)
                 and any(isinstance(target, ast.Name) and target.id in names for target in node.targets)]
    exec(compile(tree, str(path), "exec"), namespace)


ob = ModuleType("_v1147_outbox")
sys.modules[ob.__name__] = ob
outbox_path = ROOT / "app/hub_outbox.py"
outbox_tree = ast.parse(outbox_path.read_text(), filename=str(outbox_path))
outbox_tree.body = [node for node in outbox_tree.body
                    if not isinstance(node, ast.ImportFrom) or node.module != "app.message_deliveries"]
ob.report_receipt_accepted = lambda result: result == {"ok": True}
exec(compile(outbox_tree, str(outbox_path), "exec"), ob.__dict__)

backend_namespace = {"hw": SimpleNamespace(HUB_UV_INSTRUCTIONS=""), "OUTBOX_NAME": ob.OUTBOX_NAME}
load_definitions(ROOT / "app/backend_hub.py", backend_namespace,
                 {"PREAMBLE_BASE", "OUTBOX_SECTION", "hub_preamble"})
if os.environ.get("V1147_ORIGINAL_DEFECT") == "1":
    original = 'OUTBOX_SECTION.replace("{send_line}", send).replace("{{", "{").replace("}}", "}")'
    fixed = 'OUTBOX_SECTION.replace("{{", "{").replace("}}", "}").replace("{send_line}", send)'
    source = (ROOT / "app/backend_hub.py").read_text()
    assert source.count(fixed) == 1, "mutation must restore exactly the original production expression"
    tree = ast.parse(source.replace(fixed, original))
    tree.body = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "hub_preamble"]
    exec(compile(tree, str(ROOT / "app/backend_hub.py"), "exec"), backend_namespace)
backend_hub = SimpleNamespace(hub_preamble=backend_namespace["hub_preamble"])


@pytest.fixture(autouse=True, params=["fallback", "synthetic-role"])
def synthetic_prompt_dependencies(monkeypatch, tmp_path, request):
    role = tmp_path / "worker.md"
    if request.param == "synthetic-role":
        role.write_text("Worker {worker_name}, parent {orchestrator_name}, branch {branch}, scope {scope}.")
    pipeline = ModuleType("app.pipeline")
    pipeline.DEFAULT_PIPELINE = "default"
    pipeline.prompt_path = lambda *args: role
    prompting = ModuleType("app.prompting")
    prompting.safe_format_prompt = lambda text, **kwargs: text.format(**kwargs)
    monkeypatch.setitem(sys.modules, "app.pipeline", pipeline)
    monkeypatch.setitem(sys.modules, "app.prompting", prompting)


load_definitions(ROOT / "tests/test_hub_workspace.py", globals(), {
    "_who", "_Calls", "_prompt_outbox_examples",
    "test_hub_preamble_examples_are_valid_outbox_requests",
    "test_outbox_parsing_keeps_only_the_three_tools_and_reports_the_rest",
    "test_send_message_always_goes_to_the_parent_and_ignores_to_and_file_path",
    "test_progress_and_checklist_are_the_workers_own_and_bad_arguments_never_reach_the_api",
})
