"""Limited stdlib fallback: source-extracted functions, not the required pytest run.

The hub copy omits app dependencies and most app modules. Storage, manager and
assignment seams below are test doubles; Git checks use private local repositories.
"""
import ast
import asyncio
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[3]
ARTIFACTS = Path(__file__).resolve().parent


def extract(path, names, namespace):
    tree = ast.parse((ROOT / path).read_text(), filename=path)
    nodes = [node for node in tree.body if getattr(node, "name", None) in names]
    assert {node.name for node in nodes} == set(names)
    module = ast.Module(body=nodes, type_ignores=[])
    exec(compile(ast.unparse(module), path, "exec", flags=__import__("__future__").annotations.compiler_flag), namespace)


class AdmissionChecks(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.calls = []
        self.ns = dict(asyncio=asyncio, hashlib=hashlib, json=json, re=re,
                       time=time, uuid=uuid, MERGE_BUSY_WAIT_SECONDS=0.02,
                       _RESOLVE_HINT="Resolve {operation_id}")
        extract("app/merge_operations.py", [
            "_json", "_hash", "_text", "_error", "_action", "_blocking_action",
            "_base_result", "normalize_request", "request_hash", "_operation_id",
            "acceptance_input_error", "_elapsed_ms", "_busy_worker_result",
            "_blocked_by_active", "_active_operation_result", "_head_matches",
            "_current_session_status", "_wait_for_session_idle", "accept_merge_operation",
        ], self.ns)
        self.session = SimpleNamespace(status=SimpleNamespace(value="idle"))
        manager = SimpleNamespace(get=lambda _: self.session)
        deps = ModuleType("app.deps")
        deps.manager = manager
        review = ModuleType("app.work_review")
        review.assignment = lambda *_: None
        self.modules = patch.dict(sys.modules, {"app.deps": deps, "app.work_review": review})
        self.modules.start()
        self.addCleanup(self.modules.stop)
        self.ns.update(
            get_operation_record=lambda _: None,
            get_session_by_name=lambda *_: {"id": "sid", "branch": "worker"},
            get_active_operation_for_session=lambda _: None,
            _session_snapshot=self.snapshot,
            _prepare_admission_snapshot=lambda *_: {},
            accept_operation_snapshot=lambda **kw: (
                {"operation_state": "PENDING", "operation_id": kw["operation_id"]}, True, 202),
            record_phase_duration=lambda *_a, **_kw: None,
            ensure_operation_runner=lambda _: self.calls.append("runner"),
        )

    def snapshot(self, _):
        self.calls.append("snapshot")
        return {"session_id": "sid", "worker_head": "b" * 40, "worker_branch": "worker"}

    async def submit(self, **extra):
        args = dict(operation_id=str(uuid.uuid4()), name="worker", scope="/scope", target="main")
        args.update(extra)
        return await self.ns["accept_merge_operation"](**args)

    async def test_active_precedes_missing_acceptance(self):
        for state in ("PENDING", "RUNNING", "PARTIAL", "UNKNOWN"):
            with self.subTest(state=state):
                result = {"operation_id": "active", "operation_state": state}
                self.ns["get_active_operation_for_session"] = lambda _: {
                    "state": state, "result": result, "operation_id": "active"}
                answer, status = await self.submit()
                self.assertEqual(answer["operation_id"], "active")
                self.assertEqual(status, 202 if state in ("PENDING", "RUNNING") else 200)
                self.assertEqual(self.calls, [])

    async def test_busy_precedes_missing_acceptance(self):
        self.session.status.value = "running"
        result, status = await self.submit()
        self.assertEqual(status, 409)
        self.assertEqual(result["error"]["code"], "WORKER_BUSY")
        self.assertEqual(self.calls, [])

    async def test_running_timeout_precedes_missing_acceptance(self):
        self.session.status.value = "running"
        async def wait():
            await asyncio.Event().wait()
        self.session.wait_for_turn_completion = wait
        result, status = await self.submit()
        self.assertEqual((status, result["error"]["code"]), (409, "WORKER_BUSY"))
        self.assertEqual(self.calls, [])

    async def test_idle_invalid_inputs_never_snapshot(self):
        for head, note in [("", "Accepted after inspecting the diff"),
                           ("b" * 12, "Accepted after inspecting the diff"),
                           ("b" * 40, "placeholder"), ("b" * 40, "-"),
                           ("b" * 40, "tbd"), ("b" * 40, "x" * 14)]:
            with self.subTest(head=head, note=note):
                result, status = await self.submit(expected_head=head, acceptance_note=note)
                self.assertEqual((status, result["error"]["code"]), (409, "WORK_ACCEPTANCE_REQUIRED"))
                self.assertEqual(self.calls, [])

    async def finish(self):
        self.calls.append("wait")
        self.session.status.value = "idle"
        return True

    async def test_finished_worker_still_requires_acceptance(self):
        self.session.status.value = "running"
        self.session.wait_for_turn_completion = self.finish
        result, status = await self.submit()
        self.assertEqual((status, result["error"]["code"]), (409, "WORK_ACCEPTANCE_REQUIRED"))
        self.assertEqual(self.calls, ["wait"])

    async def test_finished_worker_with_acceptance_is_admitted(self):
        self.session.status.value = "running"
        self.session.wait_for_turn_completion = self.finish
        result, status = await self.submit(expected_head="b" * 40, acceptance_note="Accepted after inspecting the diff")
        self.assertEqual((status, result["operation_state"]), (202, "PENDING"))
        self.assertEqual(self.calls, ["wait", "snapshot", "runner"])
        self.assertIn("pre_operation", result["phase_durations_ms"])

    async def test_full_but_different_head_is_rejected(self):
        result, status = await self.submit(expected_head="c" * 40, acceptance_note="Accepted after inspecting the diff")
        self.assertEqual((status, result["error"]["code"]), (409, "WORK_HEAD_CHANGED"))
        self.assertEqual(self.calls, ["snapshot"])

    async def test_worker_becoming_busy_during_snapshot_is_rejected(self):
        def snapshot(sid):
            self.session.status.value = "running"
            return self.snapshot(sid)
        self.ns["_session_snapshot"] = snapshot
        result, status = await self.submit(expected_head="b" * 40, acceptance_note="Accepted after inspecting the diff")
        self.assertEqual((status, result["error"]["code"]), (409, "WORKER_BUSY"))
        self.assertEqual(self.calls, ["snapshot"])

    async def test_legacy_replay_does_not_require_new_acceptance(self):
        request = self.ns["normalize_request"](name="worker", scope="/scope", target="main")
        stored = {"operation_state": "SUCCEEDED"}
        self.ns["get_operation_record"] = lambda _: {
            "request_hash": self.ns["request_hash"](request), "state": "SUCCEEDED", "result": stored}
        self.ns["_replay_drift"] = lambda _: None
        result, status = await self.submit()
        self.assertEqual((result, status), (stored, 200))
        self.assertEqual(self.calls, [])

    async def test_pre_fix_validation_order_is_detected(self):
        tree = ast.parse((ROOT / "app/merge_operations.py").read_text())
        fn = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "accept_merge_operation")
        start = next(i for i, n in enumerate(fn.body) if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "input_error" for t in n.targets))
        validation = fn.body[start:start + 2]
        del fn.body[start:start + 2]
        position = next(i for i, n in enumerate(fn.body) if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "row" for t in n.targets))
        fn.body[position:position] = validation
        mutated = dict(self.ns)
        exec(compile(ast.unparse(ast.Module(body=[fn], type_ignores=[])), "mutation", "exec", flags=__import__("__future__").annotations.compiler_flag), mutated)
        self.session.status.value = "running"
        result, status = await mutated["accept_merge_operation"](operation_id=str(uuid.uuid4()), name="worker", scope="/scope")
        self.assertEqual((status, result["error"]["code"]), (409, "WORK_ACCEPTANCE_REQUIRED"))


class GitAndPresentationChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ARTIFACTS / "tmp")
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Offline Test")
        self.git("config", "user.email", "offline@example.invalid")
        self.git("commit", "--allow-empty", "-m", "V-1044: Root commit")
        self.root = self.git("rev-parse", "HEAD").strip()
        self.ns = dict(re=re, json=json)
        source = (ROOT / "app/workspace.py").read_text()
        constants = source[source.index("_HEADER_TASK_REFS_RE ="):source.index("def _leading_task_refs")]
        exec(constants, self.ns)
        extract("app/workspace.py", ["_leading_task_refs", "_extract_task_refs", "_strip_leading_task_refs", "_build_squash_message", "_validated_squash_message", "_get_commit_messages", "_parse_merged_commits"], self.ns)
        self.ns["_git_cmd"] = lambda args, **kw: subprocess.run(["/usr/bin/git", *args[1:]], **kw)

    def git(self, *args):
        return subprocess.run(["/usr/bin/git", *args], cwd=self.repo, capture_output=True, text=True, check=True).stdout

    def test_root_parent_inspection_is_empty_and_safe(self):
        self.assertEqual(self.git("log", "-1", "--format=%P", self.root).strip(), "")
        self.assertEqual(self.ns["_build_squash_message"]("worker", ["V-1044: Root commit"]), "V-1044: Root commit")

    def test_root_base_squash_preserves_headline_trailer_and_parent(self):
        self.git("checkout", "-b", "worker")
        self.git("commit", "--allow-empty", "-m", "V-1044: WIP")
        self.git("commit", "--allow-empty", "-m", "V-1044: Finished result")
        messages = self.ns["_get_commit_messages"](str(self.repo), "worker", "main")
        self.assertEqual(self.ns["_build_squash_message"]("worker", messages).splitlines()[0], "V-1044: Finished result")
        subject = self.ns["_validated_squash_message"]("worker", messages, ["V-1044"], "V-1044", "operation", "Accepted the finished result\nChecks passed")
        self.git("checkout", "main")
        self.git("commit", "--allow-empty", "-m", subject)
        self.assertEqual(self.git("log", "-1", "--format=%s").strip(), "V-1044: Accepted the finished result")
        self.assertEqual(self.git("log", "-1", "--format=%P").strip(), self.root)
        self.assertEqual(self.git("log", "-1", "--format=%B").count("Orchestra-Operation: operation"), 1)
        self.assertEqual(len(self.ns["_parse_merged_commits"](str(self.repo), self.root)["V-1044"]), 1)

    def test_substituted_task_ref_is_rejected_with_current_builder_signature(self):
        real_builder = self.ns["_build_squash_message"]
        self.ns["_build_squash_message"] = lambda branch, messages, acceptance_note="": real_builder(branch, messages, acceptance_note).replace("#42", "#77")
        with self.assertRaisesRegex(ValueError, "squash subject task refs changed"):
            self.ns["_validated_squash_message"]("worker", ["#42: Result"], ["42"], "42")

    def reconcile(self, *, expected_tree=None):
        extract("app/merge_operations.py", ["_repo_for_scope", "reconcile_prepared_commit"], self.ns)
        workspace = ModuleType("app.workspace")
        workspace._parse_merged_commits = self.ns["_parse_merged_commits"]
        payload = {"target_before": self.root, "target_branch": "main"}
        if expected_tree is not None:
            payload["expected_tree"] = expected_tree
        record = {"scope": str(self.repo), "operation_id": "operation",
                  "finalization_json": json.dumps(payload)}
        with patch.dict(sys.modules, {"app.workspace": workspace}):
            return self.ns["reconcile_prepared_commit"](record)

    def test_unchanged_root_is_not_a_completed_merge(self):
        result = self.reconcile()
        self.assertFalse(result["reached"])

    def test_checkpoint_recovery_after_root_requires_exact_trailer_and_tree(self):
        self.git("commit", "--allow-empty", "-m", "V-1044: Accepted result\n\nOrchestra-Operation: operation")
        head = self.git("rev-parse", "HEAD").strip()
        tree = self.git("rev-parse", "HEAD^{tree}").strip()
        result = self.reconcile(expected_tree=tree)
        self.assertTrue(result["reached"])
        self.assertEqual(result["target_after"], head)
        self.assertEqual(result["payload"]["stage"], "PENDING")
        self.assertEqual(result["payload"]["commits"]["V-1044"][0]["hash"], head[:7])
        self.assertIsNone(self.reconcile(expected_tree="f" * 40))
        self.git("commit", "--amend", "--allow-empty", "-m", "V-1044: Foreign result\n\nOrchestra-Operation: foreign")
        self.assertIsNone(self.reconcile(expected_tree=tree))

    def test_unrelated_root_is_not_claimed_as_checkpoint_recovery(self):
        self.git("checkout", "--orphan", "replacement")
        self.git("commit", "--allow-empty", "-m", "V-1044: Foreign root\n\nOrchestra-Operation: operation")
        self.git("branch", "-f", "main", "HEAD")
        self.assertIsNone(self.reconcile())

    def test_compact_output_removes_logs_and_preserves_original(self):
        extract("app/mcp_stdio.py", ["_compact_merge_result"], self.ns)
        result = {"operation_state": "FAILED", "test_gate": {"status": "FAILED", "failed_tests": ["test_a"], "output": "x" * 10000}}
        before = json.dumps(result)
        compact = self.ns["_compact_merge_result"](result)
        self.assertEqual(compact["test_gate"]["failed_tests"], ["test_a"])
        self.assertNotIn("output", compact["test_gate"])
        self.assertEqual(json.dumps(result), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
