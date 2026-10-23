"""Stdlib-only fallback for the incomplete hub copy; NOT the required pytest suite.

Loads the production source with unavailable imports substituted. Real retry/watch/read,
sync-back and archive validation run; provisioning, Git commits and the activity renderer
are doubles. No credentials, provider calls or files outside this task directory.
Run with --disable-retry to reproduce the retry acceptance failure.
"""

import ast
import asyncio
import hashlib
import io
import logging
import sys
import tarfile
import tempfile
import types
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

ROOT = Path(__file__).resolve().parents[3]
ARTIFACTS = Path(__file__).resolve().parent
sys.dont_write_bytecode = True


def load_source(name, path, **bindings):
    tree = ast.parse(path.read_text(), filename=str(path))
    tree.body = [node for node in tree.body if not (
        isinstance(node, ast.ImportFrom) and (node.module or "").startswith("app"))]
    module = types.ModuleType(name)
    module.__file__ = str(path)
    module.__dict__.update(bindings)
    sys.modules[name] = module
    exec(compile(tree, str(path), "exec"), module.__dict__)
    return module


@dataclass
class Event:
    type: str
    content: str = ""
    metadata: dict = field(default_factory=dict)
    usage: object = None


class Stream:
    def __init__(self, run_id, cursor):
        self.cursor = cursor

    def feed(self, items):
        for item in items:
            self.cursor = max(self.cursor or 0, item["position"])
        return []

    def finish(self, reply):
        return []


class ClientError(RuntimeError):
    retryable = False


hw = load_source("offline_hub_workspace", ROOT / "app/hub_workspace.py",
                 MAX_OUTBOX_BYTES=65536, OUTBOX_NAME=".orchestra-outbox.jsonl",
                 publication_secrets=types.SimpleNamespace(HUB_SECRET_SHAPES=[]))
reply_tree = ast.parse((ROOT / "app/multicode_client.py").read_text())
reply_function = next(node for node in reply_tree.body
                      if isinstance(node, ast.FunctionDef) and node.name == "_last_assistant_text")
reply_ns = {"Any": object}
exec(compile(ast.Module(body=[reply_function], type_ignores=[]), "reply.py", "exec"), reply_ns)
hub = load_source("offline_backend_hub", ROOT / "app/backend_hub.py", hw=hw,
                  HubActivityStream=Stream, OUTBOX_NAME=hw.OUTBOX_NAME,
                  AgentEvent=Event, MultiCodeClient=object, MultiCodeError=ClientError,
                  _last_assistant_text=reply_ns["_last_assistant_text"])
if "--disable-retry" in sys.argv:
    sys.argv.remove("--disable-retry")
    hub.NO_WORK_RETRIES = 0

app = types.ModuleType("app")
app.__path__ = [str(ROOT / "app")]
pool = types.ModuleType("app.hub_pool")
pool.require_hub_capacity = AsyncMock(return_value=None)
quota = types.ModuleType("app.quota_gate")
quota.QuotaGateError = type("QuotaGateError", (RuntimeError,), {})
sys.modules.update({"app": app, "app.hub_pool": pool, "app.quota_gate": quota})


class Checks(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ARTIFACTS)
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root, self.remote = self.base / "worker", self.base / "hub"
        self.root.mkdir()
        self.remote.mkdir()
        for directory in (self.root, self.remote):
            (directory / "calc.py").write_text("original\n")
        digest = hashlib.sha256(b"original\n").hexdigest()
        state = types.SimpleNamespace(
            remote_dir=str(self.remote), manifest={"calc.py": digest}, uploaded=True,
            paths=["calc.py"], project_id="project", thread_id="", activity_pos=0,
            turns=0, hub_made=[], ws_id="hub-offline", path=lambda: self.root, save=Mock())
        self.backend = hub.HubBackend("hub-gpt-6.1-sol", str(self.root), paths=["calc.py"])
        self.backend._state = state
        self.backend._provision = AsyncMock(return_value=[])
        self.backend._preamble = lambda: "preamble\n"
        self.backend._run_outbox = AsyncMock(return_value="")
        self.failures, self.reason, self.status = 1, "provider disconnected", "failed"
        self.reason_source = "recentRuns"
        self.activity = []
        self.sends, self.calls = 0, []
        self.on_start = lambda: None
        self.activity_failure = False
        self.sync_failure = False

        async def get(remote_dir, out):
            if self.sync_failure:
                raise hw.HubWorkspaceError("sync unavailable")
            with tarfile.open(out, "w") as archive:
                archive.add(remote_dir, arcname=".")

        self.backend._ssh = types.SimpleNamespace(get=get)
        self.backend._client = AsyncMock(return_value=types.SimpleNamespace(tool_call=self.call))
        self.sleep = AsyncMock()
        patches = [
            patch.object(hub.asyncio, "sleep", self.sleep),
            patch.object(hw, "known_secret_values", lambda *a: []),
            patch.object(hw, "plan_upload", lambda *a: hw.UploadPlan(manifest=dict(state.manifest))),
            patch.object(hw, "local_scratch", lambda: Path(tempfile.mkdtemp(dir=self.base))),
            patch.object(hw, "commit_sync", Mock(return_value=("offline-commit-double", []))),
            patch.object(hub, "_branch_task_ref", lambda *a: "#V-1051"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    async def call(self, name, args):
        self.calls.append((name, args))
        if name in {"t3_thread_launch", "t3_thread_send"}:
            self.sends += 1
            self.on_start()
            return {"threadId": "thread", "runId": f"run-{self.sends}"}
        failed = self.sends <= self.failures
        run_id = f"run-{self.sends}"
        if name == "t3_thread_wait":
            result = {"status": self.status if failed else "completed"}
            if self.reason_source == "wait" and failed:
                result["error"] = self.reason
            return result
        if name == "t3_thread_read":
            if args["view"] == "activity":
                if self.activity_failure:
                    raise ClientError("activity unavailable")
                items = [{**item, "runId": run_id, "position": i + 10 * self.sends}
                         for i, item in enumerate(self.activity)]
                if self.reason_source == "activity" and failed:
                    items.append({"type": "error", "status": "failed", "runId": run_id,
                                  "position": 100 * self.sends, "text": self.reason})
            else:
                items = [] if failed else [{"type": "assistant_message", "runId": run_id, "text": "PONG"}]
            result = {"items": items, "hasMore": False}
            if self.reason_source in {"recentRuns", "runs"}:
                result[self.reason_source] = [
                    {"runId": "old", "error": "old failure must not leak"},
                    {"runId": run_id, "error": self.reason if failed else None}]
            return result
        raise AssertionError(name)

    async def turn(self):
        self.events = []
        try:
            async for event in self.backend._run_turn("task"):
                self.events.append(event)
        except hw.HubWorkspaceError as exc:
            return exc
        return None

    async def test_a_empty_failure_retries_then_success(self):
        self.assertIsNone(await self.turn())
        self.assertEqual(self.sends, 2)
        sends = [(n, a) for n, a in self.calls if n in {"t3_thread_launch", "t3_thread_send"}]
        self.assertEqual(sends[1][1], {"threadId": "thread", "message": sends[0][1]["message"], "mode": "auto"})
        self.assertTrue(any(e.type == "status" and "retry 1/2" in e.content for e in self.events))
        self.sleep.assert_awaited_once_with(1)

    async def test_b_exhaustion_reason_and_missing_reason(self):
        self.failures = 10
        self.reason = None
        error = await self.turn()
        self.assertIn("hub thread ended with status failed; no reason exposed by hub", str(error))
        self.assertEqual(self.sends, 3)
        self.assertEqual([c.args for c in self.sleep.await_args_list], [(1,), (2,)])

    async def test_c_changed_files_are_synced_without_retry(self):
        self.on_start = lambda: (self.remote / "calc.py").write_text("edited\n")
        error = await self.turn()
        self.assertIn("provider disconnected", str(error))
        self.assertNotIn("old failure", str(error))
        self.assertEqual(self.sends, 1)
        self.assertEqual((self.root / "calc.py").read_text(), "edited\n")

    async def test_d_limit_not_retried(self):
        self.reason = "usage_limit_reached"
        self.assertIsInstance(await self.turn(), hub.HubProviderLimit)
        self.assertEqual(self.sends, 1)

    async def test_e_venv_excluded_sibling_synced(self):
        self.failures = 0

        def create():
            env = self.remote / ".venv-v281"
            (env / "lib").mkdir(parents=True)
            (env / "lib/pkg.py").write_text("generated\n")
            (env / "pyvenv.cfg").write_text("home = /usr/bin\n")
            (self.remote / "sibling.py").write_text("keep\n")
        self.on_start = create
        self.assertIsNone(await self.turn())
        self.assertFalse((self.root / ".venv-v281").exists())
        self.assertEqual((self.root / "sibling.py").read_text(), "keep\n")
        self.assertTrue(any("Python virtualenv" in e.content for e in self.events))

    async def test_f_tool_prevents_retry(self):
        self.activity = [{"type": "command_execution", "status": "completed", "text": "$ true"}]
        self.assertIsNotNone(await self.turn())
        self.assertEqual(self.sends, 1)

    async def test_g_activity_failure_prevents_retry(self):
        self.activity_failure = True
        self.assertIsNotNone(await self.turn())
        self.assertEqual(self.sends, 1)

    async def test_h_sync_failure_prevents_retry(self):
        self.sync_failure = True
        self.assertIsNotNone(await self.turn())
        self.assertEqual(self.sends, 1)

    async def test_i_workspace_preparation_is_not_provider_tool_work(self):
        self.activity = [{"type": "command_execution", "status": "completed", "text": "Workspace ready",
                          "itemId": "turn-item:provider:codex:native-item:workspace-preparation%3Arun"}]
        self.assertIsNone(await self.turn())
        self.assertEqual(self.sends, 2)

    async def test_j_cancelled_without_work_retries(self):
        self.status = "cancelled"
        self.reason_source = "wait"
        self.assertIsNone(await self.turn())
        self.assertEqual(self.sends, 2)

    async def test_k_activity_reason_is_reported(self):
        self.reason_source = "activity"
        self.failures = 10
        error = await self.turn()
        self.assertIn("provider disconnected", str(error))
        self.assertEqual(self.sends, 3)

    async def test_l_venv_marker_last_and_prefix_sibling(self):
        out = self.base / "order.tar"
        with tarfile.open(out, "w") as archive:
            for rel in ("tools/env/lib/pkg.py", "tools/env-sibling/keep.py", "tools/env/pyvenv.cfg"):
                member = tarfile.TarInfo(rel)
                member.size = 5
                archive.addfile(member, io.BytesIO(b"keep\n"))
        result = hw.apply_changes(out, self.root, {}, known=[])
        self.assertEqual(result.changed, ["tools/env-sibling/keep.py"])
        self.assertEqual(result.rejected, [("tools/env", "Python virtualenv (contains pyvenv.cfg)")])


    async def test_m_old_venv_files_are_not_deleted(self):
        (self.root / "env").mkdir()
        old = self.root / "env/old.py"
        old.write_text("keep\n")
        manifest = {"env/old.py": hw.sha256_file(old)}
        out = self.base / "old.tar"
        with tarfile.open(out, "w") as archive:
            member = tarfile.TarInfo("env/pyvenv.cfg")
            member.size = 5
            archive.addfile(member, io.BytesIO(b"home\n"))
        result = hw.apply_changes(out, self.root, manifest, known=[])
        self.assertEqual(result.deleted, [])
        self.assertEqual(result.manifest, manifest)
        self.assertEqual(old.read_text(), "keep\n")

    async def test_n_abort_during_backoff_never_resends(self):
        async def abort(delay):
            self.backend._abort = True
        self.sleep.side_effect = abort
        self.assertIsNone(await self.turn())
        self.assertEqual(self.sends, 1)

    async def test_o_retry_send_error_never_relaunches(self):
        original = self.call

        async def call(name, args):
            if name == "t3_thread_send":
                raise ClientError("delivery uncertain")
            return await original(name, args)
        self.backend._client = AsyncMock(return_value=types.SimpleNamespace(tool_call=call))
        with self.assertRaisesRegex(ClientError, "delivery uncertain"):
            await self.turn()
        self.assertEqual(self.sends, 1)
        self.assertEqual(self.backend._state.thread_id, "thread")

    async def test_p_failed_with_reply_never_retries(self):
        original = self.call

        async def call(name, args):
            result = await original(name, args)
            if name == "t3_thread_read" and args.get("view") == "messages":
                result["items"] = [{"type": "assistant_message", "runId": "run-1", "text": "partial reply"}]
            return result
        self.backend._client = AsyncMock(return_value=types.SimpleNamespace(tool_call=call))
        self.assertIsNotNone(await self.turn())
        self.assertEqual(self.sends, 1)

    async def test_q_rolled_back_never_retries(self):
        self.status = "rolled_back"
        self.assertIsNotNone(await self.turn())
        self.assertEqual(self.sends, 1)

    async def test_r_incomplete_activity_pages_prevent_retry(self):
        original = self.call

        async def call(name, args):
            result = await original(name, args)
            if name == "t3_thread_read" and args.get("view") == "activity":
                result["hasMore"] = True
            return result
        self.backend._client = AsyncMock(return_value=types.SimpleNamespace(tool_call=call))
        self.assertIsNotNone(await self.turn())
        self.assertEqual(self.sends, 1)


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    print(f"Production sources: {hw.__file__}; {hub.__file__}")
    print(f"Synthetic app namespace: {app.__path__}; missing integrations are doubles.")
    unittest.main(verbosity=2)
