"""Stdlib fallback for this incomplete hub copy; NOT the required pytest run.

Executes selected production definitions with explicit dependency fakes. It cannot
validate imports, the durable queue implementation, provider adapters or OS isolation.
All files and temporary artifacts stay in the supplied checkout; no provider/network I/O.
"""
from __future__ import annotations

import ast
import asyncio
import __future__
from dataclasses import dataclass
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from typing import Mapping
import unittest
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[3]
MUTATION = sys.argv.pop(1) if len(sys.argv) > 1 and sys.argv[1].startswith("mutate-") else ""


def definitions(path, names, namespace, *, owner=None):
    tree = ast.parse((ROOT / path).read_text(), filename=path)
    nodes = tree.body
    if owner:
        nodes = next(node for node in nodes if isinstance(node, ast.ClassDef) and node.name == owner).body
    selected = []
    for node in nodes:
        name = getattr(node, "name", None)
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
        if name in names:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                node.decorator_list = []
            if name == "change_model" and MUTATION == "mutate-release":
                class RemoveRelease(ast.NodeTransformer):
                    def visit_Await(self, node):
                        if isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Attribute):
                            if node.value.func.attr == "release_waiting":
                                return ast.copy_location(ast.Constant(value=None), node)
                        return node
                node = RemoveRelease().visit(node)
            selected.append(node)
    assert len(selected) == len(names), (path, names)
    module = ast.fix_missing_locations(ast.Module(body=selected, type_ignores=[]))
    exec(compile(module, path, "exec", flags=__future__.annotations.compiler_flag), namespace)


# Keep postponed annotations, including AdapterResult, without importing absent modules.
quota = ModuleType("v1056_quota_definitions")
sys.modules[quota.__name__] = quota
quota.__dict__.update(dataclass=dataclass, Mapping=Mapping, HARD_STOP_PCT=99.0)
definitions("app/quota_gate.py", {
    "WORKER_ADMISSION_RULE", "QuotaDecision", "QuotaGateError", "require_worker_admission",
}, quota.__dict__)
if MUTATION == "mutate-rule":
    quota.QuotaGateError.rule = "wrong_rule"
if MUTATION == "mutate-admission":
    quota.require_worker_admission = lambda decision: None
models = ModuleType("app.models")
models.hub_alternative_hint = lambda model: ""


def decision(state="blocked", provider="anthropic"):
    return quota.QuotaDecision(
        state=state, model="test-model", provider=provider, provider_label="Test pool",
        lane="claude", gated=True, utilization=100.0, progress=0.1, tolerance_pp=9.1,
        limit_pct=19.1, observed_at=None, valid_until=None, reset_at=None,
        window_starts_at=None, reason="test pool exhausted",
    )


class QuotaRefusalSmoke(unittest.TestCase):
    def test_subscription_and_hub_name_rule_and_preserve_contract(self):
        with patch.dict(sys.modules, {"app.models": models}):
            for provider in ("anthropic", "codex", "codex_spark", "hub_claude", "hub_codex"):
                with self.subTest(provider=provider):
                    with self.assertRaises(quota.QuotaGateError) as caught:
                        quota.require_worker_admission(decision(provider=provider))
                    error = caught.exception
                    body = error.envelope()["error"]
                    self.assertIn("Rule 'worker_quota_admission'", body["message"])
                    self.assertEqual(body["details"]["rule"], "worker_quota_admission")
                    self.assertEqual(body["details"]["provider"], provider)
                    self.assertEqual(body["code"], "weekly_quota_blocked")
                    self.assertFalse(body["retryable"])
                    self.assertEqual(error.status_code, 429)

    def test_allowing_states_and_original_decision_are_unchanged(self):
        for state in ("available", "unknown", "not_applicable"):
            row = decision(state)
            before = row.to_dict()
            quota.require_worker_admission(row)
            self.assertEqual(row.to_dict(), before)
            with self.assertRaises(ValueError):
                quota.QuotaGateError(row)

    def test_mcp_refusal_names_rule_without_overriding_fail_open_policy(self):
        class ToolError(Exception):
            def __init__(self, **values):
                self.__dict__.update(values)

        namespace = {"ApiToolError": ToolError}
        definitions("app/mcp_stdio.py", {"_quota_refusal_from_readiness"}, namespace)
        refusal = namespace["_quota_refusal_from_readiness"]
        with patch.dict(sys.modules, {"app.quota_gate": quota}):
            error = refusal("test-model", decision().to_dict())
        self.assertIn("Rule 'worker_quota_admission'", error.message)
        self.assertEqual(error.details["rule"], "worker_quota_admission")
        self.assertEqual(error.code, "weekly_quota_blocked")
        for state in ("unknown", "available", "not_applicable"):
            self.assertIsNone(refusal("test-model", decision(state).to_dict()))


class ChangeModelRouteSmoke(unittest.IsolatedAsyncioTestCase):
    async def test_release_observes_new_model_and_ignores_unsuccessful_changes(self):
        worker = SimpleNamespace(model="old")

        async def change(model, **kwargs):
            worker.model = model
            return {"ok": True, "changed": True, "model": model}

        worker.change_model = change
        seen = []

        async def release():
            seen.append(worker.model)

        queue = ModuleType("app.quota_queue")
        queue.release_waiting = release
        app_package = ModuleType("app")
        app_package.quota_queue = queue
        namespace = {
            "resolve_model": lambda model: model, "MODELS": {"new"},
            "ensure_spawn_allowed": lambda model: None,
            "ensure_dashboard_visible": lambda model: None,
            "manager": SimpleNamespace(ensure_loaded=AsyncMock(return_value=worker)),
            "JSONResponse": lambda body, status_code: (status_code, body),
        }
        definitions("app/routes/sessions.py", {"change_model"}, namespace)
        with patch.dict(sys.modules, {"app": app_package, "app.quota_queue": queue}):
            result = await namespace["change_model"]("worker", {"model": "new", "via": "mcp"})
            self.assertTrue(result["ok"])
            self.assertEqual(seen, ["new"])
            worker.change_model = AsyncMock(return_value={"ok": True, "changed": False})
            await namespace["change_model"]("worker", {"model": "new"})
            worker.change_model = AsyncMock(return_value={"ok": False, "error": "busy"})
            result = await namespace["change_model"]("worker", {"model": "new"})
            self.assertEqual(result[0], 409)
            self.assertEqual(seen, ["new"])

    async def test_open_workflow_dispatch_has_no_independent_boundary(self):
        # Evidence of the OPEN architectural fork, not a security acceptance test.
        namespace = {"asyncio": asyncio, "Path": Path}
        definitions("scripts/wf_run.py", {"_run_attempt"}, namespace, owner="WorkflowEngine")
        sink = AsyncMock(return_value="fake-provider-result")
        engine = SimpleNamespace(
            workspace_repo=None, _state_lock=asyncio.Lock(),
            journal=SimpleNamespace(append=lambda row: None), adapter=sink, usage_writer=None,
        )
        result, _ = await namespace["_run_attempt"](
            engine, "offline probe", model="claude-haiku-5-5", runtime="claude",
            scratch=ROOT / ".orchestra/tasks/V-1056", timeout=1, call_key="probe",
            attempt=1, event_id="probe", tools="all", network=False, mcp=False,
            system_prompt="", modules=(), capability_reason="offline evidence",
            billing_mode="subscription",
        )
        self.assertEqual(result, "fake-provider-result")
        sink.assert_awaited_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
