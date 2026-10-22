"""V-1048: replacement workspaces must not leave frozen hub projects behind.

The transport tests use unittest as well as pytest so they can run offline on a
trimmed hub without the project's full pytest environment.
"""

import asyncio
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from app import backend_hub as hub, hub_workspace as hw
from app.multicode_client import MultiCodeError


class FakeSsh:
    def __init__(self, root):
        self.base = root
        self.base.mkdir()
        self.fail_remove = set()
        self.scrubbed = []

    async def root(self):
        return str(self.base)

    async def dir_for(self, ws_id):
        return str(self.base / ws_id)

    async def remove(self, remote_dir):
        if remote_dir in self.fail_remove:
            raise hw.HubWorkspaceError("offline simulated SSH failure")
        shutil.rmtree(remote_dir, ignore_errors=True)

    async def scrub_traces(self, ws_id, thread_id):
        self.scrubbed.append((ws_id, thread_id))

    async def list_workspaces(self):
        return [(p.name, p.stat().st_mtime) for p in self.base.iterdir() if p.is_dir()]


class FakeMc:
    def __init__(self):
        self.projects = {}
        self.threads = {}
        self.calls = []
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        self.closed = True

    async def tool_call(self, name, args):
        self.calls.append((name, args))
        if name == "t3_project_delete":
            self.projects.pop(args["projectId"], None)
            self.threads = {t: p for t, p in self.threads.items() if p != args["projectId"]}
        elif name == "t3_project_list":
            return {"projects": [{"id": p, "workspaceRoot": d} for p, d in self.projects.items()],
                    "nextCursor": None}
        elif name == "t3_thread_read":
            if args["threadId"] not in self.threads:
                raise MultiCodeError("thread_not_found")
            return {"items": []}
        elif name == "t3_project_create":
            project = "project-" + Path(args["workspaceRoot"]).name
            self.projects[project] = args["workspaceRoot"]
            return {"id": project}
        elif name == "t3_thread_launch":
            thread = "thread-" + args["projectId"]
            self.threads[thread] = args["projectId"]
            return {"threadId": thread, "runId": "run-1"}
        return {}


class _WorkspaceCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.worktree = self.root / "worktree"
        self.worktree.mkdir()
        self.ssh = FakeSsh(self.root / "remote")
        self.mc = FakeMc()
        self.patch(hw, "STATE_DIR", self.root / "records")
        self.patch(hw.HubSsh, "from_env", Mock(return_value=self.ssh))
        self.patch(hub.MultiCodeClient, "from_env", Mock(return_value=self.mc))
        self.patch(hub, "hub_configured", Mock(return_value=None))

    def patch(self, target, name, value):
        patcher = patch.object(target, name, value)
        patcher.start()
        self.addCleanup(patcher.stop)
        return value

    def workspace(self, suffix, worktree=None):
        ws_id = "hub-" + suffix * 16
        state = hw.WorkspaceState(ws_id, str(worktree or self.worktree), str(self.ssh.base / ws_id),
                                  project_id="project-" + suffix, thread_id="thread-" + suffix)
        Path(state.remote_dir).mkdir()
        state.save()
        self.mc.projects[state.project_id] = state.remote_dir
        self.mc.threads[state.thread_id] = state.project_id
        return state

    def assert_released(self, state):
        self.assertFalse(state.path().exists())
        self.assertFalse(Path(state.remote_dir).exists())
        self.assertNotIn(state.project_id, self.mc.projects)
        self.assertNotIn(state.thread_id, self.mc.threads)
        self.assertIn((state.ws_id, state.thread_id), self.ssh.scrubbed)

    def assert_kept(self, state):
        self.assertTrue(state.path().exists())
        self.assertTrue(Path(state.remote_dir).exists())
        self.assertIn(state.project_id, self.mc.projects)
        self.assertIn(state.thread_id, self.mc.threads)

    async def new_turn(self):
        from app import hub_pool

        backend = hub.HubBackend("hub-gpt-6.1-sol", str(self.worktree), paths=["owned"])
        backend._ssh, backend._mc = self.ssh, self.mc
        self.patch(hub_pool, "require_hub_capacity", AsyncMock(return_value=None))
        # The quota policy is outside this test; the trimmed hub lacks python-dotenv.
        quota = types.ModuleType("app.quota_gate")
        quota.QuotaGateError = type("QuotaGateError", (RuntimeError,), {})
        with patch.dict(sys.modules, {"app.quota_gate": quota}):
            self.patch(hw, "known_secret_values", Mock(return_value=[]))
            self.patch(hw, "plan_upload", Mock(return_value=hw.UploadPlan({}, [], 0)))
            self.patch(hw, "project_options", Mock(return_value=hw.ProjectOptions()))
            self.patch(hw, "require_scope", Mock())
            self.patch(backend, "_preamble", Mock(return_value=""))

            async def provision(mc, ssh, root, state, *args):
                Path(state.remote_dir).mkdir(exist_ok=True)
                state.project_id = (await mc.tool_call(
                    "t3_project_create", {"workspaceRoot": state.remote_dir}))["id"]
                state.uploaded = True
                state.save()
                return []

            async def watch(*args):
                backend._watch_status = "completed"
                if False:
                    yield

            self.patch(backend, "_provision", provision)
            self.patch(backend, "_watch", watch)
            self.patch(backend, "_read_reply", AsyncMock(return_value="done"))
            self.patch(backend, "_sync_back", AsyncMock(return_value="synced"))
            events = [event async for event in backend._run_turn("continue")]
        self.assertEqual(events[-1].type, "text")
        self.assertIn("done", events[-1].content)
        self.assertFalse(self.mc.closed, "replacement must not close the backend's client")
        return backend._state

class HubWorkspaceLifecycleTests(_WorkspaceCase):
    async def test_release_for_worktree_keeps_replacement_and_borrowed_client(self):
        old = self.workspace("a")
        current = self.workspace("b")
        released = await hub.release_for_worktree(
            str(self.worktree), keep_ws_id=current.ws_id, ssh=self.ssh, mc=self.mc)
        self.assertEqual(released, [old.ws_id])
        self.assert_released(old)
        self.assert_kept(current)
        self.assertFalse(self.mc.closed)

    async def test_fresh_backend_releases_all_previous_copies_only(self):
        old = self.workspace("a")
        old.uploaded = True
        old.save()
        older = self.workspace("b")
        foreign_tree = self.root / "other-worktree"
        foreign_tree.mkdir()
        foreign = self.workspace("c", foreign_tree)
        new = await self.new_turn()
        self.assertNotEqual(new.ws_id, old.ws_id)
        self.assert_released(old)
        self.assert_released(older)
        self.assert_kept(new)
        self.assert_kept(foreign)

    async def test_reprovision_after_failed_upload_releases_previous(self):
        old = self.workspace("a")
        self.assertFalse(old.uploaded)
        new = await self.new_turn()
        self.assertNotEqual(new.ws_id, old.ws_id)
        self.assert_released(old)
        self.assert_kept(new)

    async def test_release_failure_does_not_block_new_turn_and_sweep_retries(self):
        old = self.workspace("a")
        self.ssh.fail_remove.add(old.remote_dir)
        with self.assertLogs(hub.logger, level="WARNING") as logged:
            new = await self.new_turn()
        self.assertIn("state kept for sweep", " ".join(logged.output))
        self.assertTrue(old.path().exists())
        self.assert_kept(new)
        self.ssh.fail_remove.clear()
        report = await hub.sweep_orphans({str(self.worktree): new.ws_id})
        self.assertEqual(report["released"], [old.ws_id])
        self.assertEqual(report["errors"], [])
        self.assert_released(old)
        self.assert_kept(new)

    async def test_sweep_uses_current_id_even_for_existing_worktree(self):
        old = self.workspace("a")
        current = self.workspace("b")
        alias = self.root / "worktree-alias"
        alias.symlink_to(self.worktree, target_is_directory=True)
        report = await hub.sweep_orphans({str(alias): current.ws_id})
        self.assertEqual(report["released"], [old.ws_id])
        self.assertEqual(report["kept"], 1)
        self.assertEqual(report["errors"], [])
        self.assert_released(old)
        self.assert_kept(current)

    async def test_sweep_releases_hub_copy_after_switch_to_local_or_before_next_turn(self):
        for sid in ("", "local-session"):
            with self.subTest(session_id=sid):
                old = self.workspace("a")
                report = await hub.sweep_orphans({str(self.worktree): sid})
                self.assertEqual(report["released"], [old.ws_id])
                self.assert_released(old)

    async def test_sweep_keeps_failed_record_and_current_copy(self):
        old = self.workspace("a")
        current = self.workspace("b")
        self.ssh.fail_remove.add(old.remote_dir)
        report = await hub.sweep_orphans({str(self.worktree): current.ws_id})
        self.assertEqual(report["released"], [])
        self.assertTrue(any(old.ws_id in error for error in report["errors"]))
        self.assertTrue(old.path().exists())
        self.assert_kept(current)

    async def test_legacy_set_caller_conservatively_keeps_live_copy(self):
        current = self.workspace("a")
        report = await hub.sweep_orphans({str(self.worktree)})
        self.assertEqual(report["kept"], 1)
        self.assert_kept(current)

    async def test_in_place_hub_model_switch_keeps_workspace(self):
        from app import hub_pool

        state = self.workspace("a")
        backend = hub.HubBackend("hub-claude-opus-5-5", str(self.worktree))
        backend._state, backend._mc = state, self.mc
        self.patch(hub_pool, "require_hub_capacity", AsyncMock(return_value=None))
        await backend.retarget_model("hub-gpt-6.1-sol")
        self.assertEqual(backend.session_id, state.ws_id)
        self.assert_kept(state)
        self.assertFalse(any(name == "t3_project_delete" for name, _ in self.mc.calls))


class HubSessionSwitchTests(_WorkspaceCase):
    """Also exercise the real session method when the full project deps are installed."""

    async def switch_runtime(self, save_error=None):
        from app import session as module

        session = module.AgentSession(id="worker", name="worker", scope=str(self.worktree),
                                      cwd=str(self.worktree), worktree_path=str(self.worktree),
                                      model="hub-gpt-6.1-sol", backend_type="hub", session_id=self.old.ws_id)
        session._build_runtime_handoff = AsyncMock(return_value="recent chat")
        session._drain_persist = AsyncMock()
        session._disconnect_backend = AsyncMock()
        session._cancel_precompact_timer = Mock()
        session._log = Mock()
        self.patch(module, "save_session", Mock(side_effect=save_error))
        result = await session._change_runtime_chat_locked("gpt-6.1-sol", session.model, "hub")
        return session, result

    async def test_hub_to_local_releases_after_persisted_switch(self):
        self.old = self.workspace("a")
        session, result = await self.switch_runtime()
        self.assertTrue(result["ok"])
        self.assertEqual(session.session_id, "")
        self.assert_released(self.old)

    async def test_failed_switch_preserves_old_workspace(self):
        self.old = self.workspace("a")
        session, result = await self.switch_runtime(OSError("simulated DB save failure"))
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "text_tail_persistence_failed")
        self.assertEqual(session.session_id, self.old.ws_id)
        self.assert_kept(self.old)

    async def test_cleanup_failure_is_logged_without_rejecting_runtime_switch(self):
        self.old = self.workspace("a")
        self.ssh.fail_remove.add(self.old.remote_dir)
        with self.assertLogs("app.session", level="WARNING") as logged:
            session, result = await self.switch_runtime()
        self.assertTrue(result["ok"])
        self.assertEqual(session.session_id, "")
        self.assertTrue(self.old.path().exists())
        self.assertIn("state kept for sweep", " ".join(logged.output))


class HubPeriodicSweepTests(_WorkspaceCase):
    async def sweep_snapshot(self, current_session_id, backend_session_id):
        from app import manager as module

        old = self.workspace("a")
        current = self.workspace("b") if backend_session_id else None
        manager = object.__new__(module.SessionManager)
        manager.sessions = {"worker": SimpleNamespace(
            worktree_path=str(self.worktree), session_id=current_session_id,
            _backend=SimpleNamespace(session_id=current.ws_id) if current else None)}
        self.patch(module, "get_all_sessions", Mock(return_value=[{
            "worktree_path": str(self.worktree), "session_id": old.ws_id}]))
        self.patch(module.asyncio, "sleep", AsyncMock(side_effect=[None, asyncio.CancelledError]))
        sweep = self.patch(hub, "sweep_orphans", AsyncMock(wraps=hub.sweep_orphans))
        with self.assertRaises(asyncio.CancelledError):
            await manager._periodic_hub_sweep()
        self.assert_released(old)
        sweep.assert_awaited_once_with({str(self.worktree): current.ws_id if current else ""})
        if current:
            self.assert_kept(current)

    async def test_running_backend_workspace_is_protected_before_db_catches_up(self):
        await self.sweep_snapshot("hub-aaaaaaaaaaaaaaaa", True)

    async def test_loaded_runtime_switch_overrides_stale_db_workspace_id(self):
        await self.sweep_snapshot("", False)
