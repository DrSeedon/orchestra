"""Dependency-free checks of actual MCP/route/spawn functions extracted with AST.

The complete functions are compiled unchanged; HTTP and pre-admission collaborators
are fakes because FastAPI/httpx/MCP/pipeline assets are absent from this hub copy.
This supplements (does not replace) the regular pytest integration tests.
"""
import ast
import asyncio
import dataclasses
import json
import logging
import math
import re
import sys
import time
import types
import unittest
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def functions(path, names, extra=None, parent=None):
    tree = ast.parse(Path(path).read_text())
    body = tree.body
    if parent:
        body = next(n for n in body if isinstance(n, ast.ClassDef) and n.name == parent).body
    selected = [n for n in body if getattr(n, "name", None) in names]
    assert {n.name for n in selected} == set(names)
    for n in selected:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            n.decorator_list = []
    mod = types.ModuleType("v1036_extracted")
    mod.__dict__.update(
        asyncio=asyncio, json=json, math=math, re=re, time=time, uuid=uuid,
        Any=Any, Path=Path, dataclass=dataclasses.dataclass, field=dataclasses.field,
        logger=logging.getLogger("offline"),
    )
    mod.__dict__.update(extra or {})
    with patch.dict(sys.modules, {mod.__name__: mod}):
        code = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), *selected], type_ignores=[])
        ast.fix_missing_locations(code)
        exec(compile(code, str(path), "exec"), mod.__dict__)
    return mod


class Edges(unittest.IsolatedAsyncioTestCase):
    def mcp(self, payload, status=202):
        response = types.SimpleNamespace(status_code=status, headers={}, text=json.dumps(payload), json=lambda: payload)
        client = types.SimpleNamespace(post=AsyncMock(return_value=response), get=AsyncMock(return_value=response))

        class Context:
            async def __aenter__(self):
                return client

            async def __aexit__(self, *_args):
                pass

        fake_http = types.SimpleNamespace(AsyncClient=lambda **_kw: Context(), RequestError=OSError)
        return functions("app/mcp_stdio.py", (
            "ApiToolError", "_api", "_auth_headers", "_response_error", "_safe_detail",
            "_safe_response_text", "_retry_after_seconds", "list_pending_deliveries",
            "_delivery_receipt_text", "_message_delivery_receipt_text",
        ), dict(
            httpx=fake_http, ORCHESTRA_URL="http://fixture", _INTERNAL_TOKEN="", SESSION_ID="",
            _MCP_PROOF="", _SENSITIVE_DETAIL_KEYS=("token",), _hub_hint=lambda *_: "hub hint",
            WORKER_NAME="sender",
        ))

    async def test_mcp_accepts_error_receipts_without_losing_identity(self):
        for state in ("WAITING_QUOTA", "FAILED_BEFORE_SUBMIT", "DELIVERY_UNKNOWN"):
            payload = {"ok": True, "delivery_id": "id", "delivery_state": state,
                       "error": {"code": state, "message": "original error"}, "next_action": {"eta_at": 123}}
            mcp = self.mcp(payload)
            self.assertEqual(await mcp._api("POST", "/send"), payload)

    async def test_mcp_still_raises_rejections_with_id(self):
        payload = {"ok": False, "delivery_id": "original-id",
                   "error": {"code": "DELIVERY_NOT_SUBMITTED", "message": "original error"}}
        mcp = self.mcp(payload, status=409)
        with self.assertRaises(mcp.ApiToolError) as caught:
            await mcp._api("POST", "/send")
        self.assertIn("original-id", caught.exception.message)
        self.assertIn("original error", caught.exception.message)

    async def test_mcp_pending_tool_forwards_target(self):
        mcp = self.mcp({"deliveries": []})
        mcp._api = AsyncMock(return_value={"deliveries": []})
        self.assertEqual(await mcp.list_pending_deliveries("worker"), {"deliveries": []})
        mcp._api.assert_awaited_once_with("GET", "/api/pending-deliveries", params={"target": "worker"})

    async def test_receipt_text_reports_failure_and_quota_eta(self):
        from app.quota_queue import quota_wait_action
        mcp = self.mcp({})
        for state in ("FAILED_BEFORE_SUBMIT", "WAITING_QUOTA"):
            row = {"delivery_id": "original-id", "delivery_state": state,
                   "acceptance": "ACCEPTED", "error": {"message": "verbatim failure"},
                   "next_action": quota_wait_action({"delivery_id": "original-id", "error_json": None})}
            text = mcp._message_delivery_receipt_text(row)
            self.assertIn("original-id", text)
            if state == "WAITING_QUOTA":
                self.assertIn("time unknown", text)
            else:
                self.assertIn("verbatim failure", text)
                self.assertIn("NOT delivered", text)
            initial = mcp._delivery_receipt_text("w", "m", dict(worktree_path="w", repo_path="r", git_common_dir="g", branch="b"), row)
            self.assertIn("original-id", initial)
            if state == "FAILED_BEFORE_SUBMIT":
                self.assertIn("verbatim failure", initial)

    async def test_spawn_admission_precedes_every_allocation_and_skips_orchestrator(self):
        class ReachedAllocation(Exception):
            pass

        class Refused(Exception):
            pass

        for state, orchestrator, planned in (
            ("blocked", False, True), ("available", False, True),
            ("unknown", False, True), ("blocked", True, True),
            ("blocked", False, False), ("available", False, False),
            ("unknown", False, False),
        ):
            with self.subTest(state=state, orchestrator=orchestrator, planned=planned):
                gate = types.ModuleType("app.quota_gate")
                gate.get_worker_admission = AsyncMock(return_value=types.SimpleNamespace(state=state))

                def require(decision):
                    if decision.state == "blocked":
                        raise Refused("use hubsol")

                gate.require_worker_admission = require
                models = types.ModuleType("app.models")
                models.validate_model_reason = lambda model, reason: reason
                pool = types.ModuleType("app.hub_pool")
                pool.require_hub_capacity = AsyncMock()
                task = types.ModuleType("app.tm")
                task.create_task_for_scope = Mock(side_effect=ReachedAllocation)
                task.resolve_scoped_task_identity = Mock(side_effect=ReachedAllocation)
                construct = Mock(side_effect=ReachedAllocation)
                worktree = Mock(side_effect=ReachedAllocation)
                method = functions("app/manager.py", ("_create_session_locked",), dict(
                    resolve_model=lambda m: m, ensure_spawn_allowed=lambda m: None,
                    ensure_dashboard_visible=lambda m: None, get_session_by_name=lambda *_: None,
                    validate_repo_root=lambda p: Path(p),
                    get_active_pipeline=lambda *a, **kw: "default",
                    get_active_profile=lambda *a, **kw: "personal", parse_disabled_tools=lambda _: [],
                    parse_owned_dirs=lambda _: [], validate_spawn=lambda *_: None,
                    AgentSession=construct, create_worktree=worktree,
                ), parent="SessionManager")._create_session_locked
                manager = types.SimpleNamespace(
                    _role_is_orchestrator=lambda *a: orchestrator, _ownership_prompt=lambda *_: "",
                    _resolve_role=lambda *_: "orchestrator", _resolve_pipeline=lambda *_: "default",
                    _resolve_profile=lambda *_: "personal", get_by_name=lambda *_: None,
                    _resolve_base_branch=Mock(side_effect=ReachedAllocation),
                )
                expected = Refused if state == "blocked" and planned and not orchestrator else ReachedAllocation
                with patch.dict(sys.modules, {"app.models": models, "app.quota_gate": gate,
                                             "app.hub_pool": pool, "app.tm": task}):
                    with self.assertRaises(expected):
                        await method(manager, name="new", scope="scope", cwd=".", model="chosen-model",
                                     use_worktree=True, repo_path=".", role="worker", parent_name="parent",
                                     planned_initial_turn=planned)
                if expected is Refused:
                    task.create_task_for_scope.assert_not_called()
                    construct.assert_not_called()
                    worktree.assert_not_called()
                    manager._resolve_base_branch.assert_not_called()
                    pool.require_hub_capacity.assert_not_awaited()
                if orchestrator or not planned:
                    gate.get_worker_admission.assert_not_awaited()
                else:
                    gate.get_worker_admission.assert_awaited_once_with("chosen-model")

    async def test_cancel_route_initial_fallback_and_pending_identity(self):
        class Response:
            def __init__(self, payload, status_code=200):
                self.payload, self.status_code = payload, status_code

        caller = lambda _request: (False, "source")
        routes = functions("app/routes/sessions.py", ("cancel_message_delivery", "list_pending_deliveries"),
                           dict(_delivery_caller=caller, JSONResponse=Response,
                                keyed_auth_required=lambda: Response({}, 403)))
        direct = types.ModuleType("app.message_deliveries")
        direct.cancel_message_delivery = Mock(return_value=({}, 404))
        direct.list_pending_deliveries = Mock(return_value=[])
        initial = types.ModuleType("app.initial_deliveries")
        initial.cancel_initial_delivery = Mock(return_value=({"ok": True, "delivery_state": "CANCELLED"}, 200))
        import app
        with patch.dict(sys.modules, {"app.message_deliveries": direct, "app.initial_deliveries": initial}), \
             patch.object(app, "message_deliveries", direct, create=True), patch.object(app, "initial_deliveries", initial, create=True):
            response = await routes.cancel_message_delivery("original-id")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.payload["delivery_state"], "CANCELLED")
            initial.cancel_initial_delivery.assert_called_once_with("original-id", "source")
            self.assertEqual(await routes.list_pending_deliveries("worker"), {"deliveries": []})
            direct.list_pending_deliveries.assert_called_once_with("source", "worker")
            routes._delivery_caller = lambda _: None
            self.assertEqual((await routes.list_pending_deliveries()).status_code, 403)


if __name__ == "__main__":
    unittest.main()
