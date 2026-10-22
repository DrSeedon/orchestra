"""HubBackend — a worker whose model runs on the MultiCode hub (BackendLike), V-1008.

One send()/events() pair is one turn. The first turn uploads the worker's worktree (only what
the task needs, no credentials) to a private directory on the hub, registers it as a hub
project and launches a full-access thread there. Every turn ends by importing the hub copy
back into the worktree and committing it on the worker's own branch, so the ordinary
merge_worker path applies. The hub thread has no git remote, token or key: the broker moves
all files.
"""

import asyncio
import contextlib
import logging
import os
import subprocess
import tarfile
import time
from pathlib import Path
from typing import AsyncIterator, Optional
from uuid import uuid4

from app import hub_workspace as hw
from app.events import AgentEvent
from app.multicode_client import MultiCodeClient, MultiCodeError, _last_assistant_text
from app.usage_contract import AggregateUsage, TurnUsage, current_context

logger = logging.getLogger(__name__)

# Orchestra model id -> (hub provider instance, hub model id). The only place that maps them.
HUB_MODELS: dict[str, tuple[str, str]] = {
    "hub-claude-haiku-5-5": ("claudeAgent", "claude-haiku-5-5"),
    "hub-claude-sonnet-5-5": ("claudeAgent", "claude-sonnet-5-5"),
    "hub-claude-opus-5-5": ("claudeAgent", "claude-opus-5-5"),
    "hub-gpt-6-luna": ("codex", "gpt-6-luna"),
    "hub-gpt-6.1-sol": ("codex", "gpt-6.1-sol"),
    "hub-grok-4.7": ("grok", "grok-4.7"),
}
TERMINAL = {"completed", "failed", "interrupted", "cancelled", "rolled_back"}
WAIT_SLICE_MS = 20_000

PREAMBLE = (
    "You are a worker on a remote machine. Your current directory is a private copy of a "
    "repository (no .git, no remote). Edit files in place with your normal tools; when you "
    "finish, the platform copies every changed file back and commits it, so do not run git "
    "push/clone/commit, do not look for credentials or tokens (there are none), and do not "
    "create files outside this directory. Run tests that work offline. End with a concise "
    "report: what you changed, what you ran and its result, anything unfinished.\n\n"
    "Task:\n"
)


_slots: asyncio.Semaphore | None = None


def _turn_slots() -> asyncio.Semaphore:
    """The hub is shared by many users: cap our concurrent hub turns (MULTICODE_HUB_MAX_THREADS)."""
    global _slots
    if _slots is None:
        _slots = asyncio.Semaphore(max(1, int(os.environ.get("MULTICODE_HUB_MAX_THREADS", "3"))))
    return _slots


def hub_configured() -> str | None:
    """None when hub workers can run; else the exact list of missing settings."""
    missing = []
    if not os.environ.get("MULTICODE_MCP_BASE", "").strip():
        missing.append("MULTICODE_MCP_BASE")
    if not (os.environ.get("MULTICODE_MCP_TOKEN", "").strip()
            or os.environ.get("MULTICODE_MCP_TOKEN_FILE", "").strip()):
        missing.append("MULTICODE_MCP_TOKEN or MULTICODE_MCP_TOKEN_FILE")
    if hw.HubSsh.from_env() is None:
        missing.append("MULTICODE_HUB_SSH and MULTICODE_HUB_SSH_KEY")
    return ("hub workers are not configured; set " + ", ".join(missing)) if missing else None


def _branch_task_ref(cwd: str) -> str:
    try:
        branch = subprocess.run(["git", "-C", cwd, "rev-parse", "--abbrev-ref", "HEAD"],
                                capture_output=True, text=True, timeout=30).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "hub"
    head = branch.split("/")[0]
    return "#" + head[len("task-"):] if head.startswith("task-") else "hub"


class HubBackend:
    def __init__(self, model: str, cwd: str, system_prompt: str = "",
                 resume_session_id: str | None = None, effort: str | None = None,
                 paths: list[str] | None = None):
        if model not in HUB_MODELS:
            raise ValueError(f"unknown hub model '{model}'")
        self.model = model
        self.cwd = cwd
        self._resume = resume_session_id
        self._paths = paths
        self._state: Optional[hw.WorkspaceState] = None
        self._mc: Optional[MultiCodeClient] = None
        self._ssh: Optional[hw.HubSsh] = None
        self._pending: Optional[str] = None
        self._turn_active = False
        self._abort = False
        self._run_id: Optional[str] = None
        self._early_steer: list[str] = []
        self._turn_started: float | None = None

    @property
    def session_id(self) -> Optional[str]:
        return self._state.ws_id if self._state else self._resume

    async def connect(self) -> None:
        problem = hub_configured()
        if problem:
            raise RuntimeError(problem)
        self._ssh = hw.HubSsh.from_env()
        self._state = hw.WorkspaceState.load(self._resume) if self._resume else None
        if self._state and os.path.realpath(self._state.worktree) != os.path.realpath(self.cwd):
            self._state = None
        logger.info("HubBackend connected: model=%s workspace=%s", self.model, self.session_id)

    async def _client(self) -> MultiCodeClient:
        if self._mc is None:
            client = MultiCodeClient.from_env()
            await client.__aenter__()
            self._mc = client
        return self._mc

    async def send(self, message: str) -> None:
        if self._ssh is None:
            raise RuntimeError("HubBackend not connected")
        if not self._turn_active:
            self._pending = message
            self._abort = False
            self._turn_active = True
            return
        # Mid-turn: steer the running hub thread (it picks the text up between its steps).
        state, run_id = self._state, self._run_id
        if state and state.thread_id and run_id:
            try:
                await (await self._client()).tool_call("t3_thread_send", {
                    "threadId": state.thread_id, "message": message, "mode": "steer"})
                return
            except MultiCodeError as exc:
                logger.warning("hub steer failed, queuing instead: %s", exc)
        self._early_steer.append(message)

    async def interrupt(self) -> None:
        self._abort = True
        state = self._state
        if state and state.thread_id:
            with contextlib.suppress(Exception):
                await (await self._client()).tool_call(
                    "t3_thread_interrupt", {"threadId": state.thread_id, "reason": "interrupted by Orchestra"})

    async def disconnect(self) -> None:
        # The hub workspace survives a reconnect/hibernate; only release_for_worktree() or an
        # explicit kill/merge removes it.
        self._abort = True
        self._turn_active = False
        if self._mc is not None:
            with contextlib.suppress(Exception):
                await self._mc.__aexit__(None, None, None)
            self._mc = None

    async def reconnect(self) -> None:
        await self.disconnect()
        await self.connect()

    # ── turn ──

    async def events(self) -> AsyncIterator[AgentEvent]:
        if not self._turn_active or self._pending is None or self._ssh is None:
            return
        message, self._pending = self._pending, None
        self._turn_started = time.perf_counter()
        ok, stop_reason, detail = True, "end_turn", ""
        reply = ""
        try:
            async for event in self._run_turn(message):
                if event.type == "text":
                    reply = event.content
                yield event
        except asyncio.CancelledError:
            self._turn_active = False
            raise
        except (hw.HubWorkspaceError, MultiCodeError, ValueError, OSError) as exc:
            ok, stop_reason, detail = False, "hub_error", str(exc)
            yield AgentEvent("error", f"Hub worker turn failed: {detail}")
        finally:
            self._turn_active = False
        if self._abort:
            ok, stop_reason = False, "interrupted"
        yield self._turn_end(ok, stop_reason, detail)

    async def _run_turn(self, message: str) -> AsyncIterator[AgentEvent]:
        mc = await self._client()
        ssh = self._ssh
        assert ssh is not None
        known = hw.known_secret_values([getattr(mc, "_token", "")])
        root = Path(self.cwd)
        state = self._state
        fresh = state is None or not state.remote_dir
        if fresh:
            state = hw.WorkspaceState(
                ws_id=hw.WorkspaceState.new_id(), worktree=str(root.resolve()), remote_dir="",
                paths=list(self._paths or []))
            state.remote_dir = await ssh.dir_for(state.ws_id)
            self._state = state
            state.save()   # before any hub write, so a crash leaves a record the sweep can release
        plan = await asyncio.to_thread(hw.plan_upload, root, state.paths or None, known)
        yield AgentEvent("status", self._upload_note(fresh, plan))
        scratch = hw.local_scratch()
        try:
            tar_path = scratch / "in.tar"
            if fresh:
                await asyncio.to_thread(hw.write_tar, root, sorted(plan.manifest), tar_path)
                await ssh.put(state.remote_dir, tar_path, fresh=True)
                state.manifest = dict(plan.manifest)
                state.save()
            else:
                send, drop = hw.local_delta(root, plan, state.manifest)
                if send:
                    await asyncio.to_thread(hw.write_tar, root, send, tar_path)
                    await ssh.put(state.remote_dir, tar_path, fresh=False)
                await ssh.delete_files(state.remote_dir, drop)
                for rel in send:
                    state.manifest[rel] = plan.manifest[rel]
                for rel in drop:
                    state.manifest.pop(rel, None)
                state.save()
            if not state.project_id:
                project = await mc.tool_call("t3_project_create", {
                    "title": f"orchestra {state.ws_id}", "workspaceRoot": state.remote_dir})
                state.project_id = project["id"] if isinstance(project, dict) else ""
                if not state.project_id:
                    raise hw.HubWorkspaceError("hub project registration returned no id")
                state.save()
            prompt = self._prompt(message, first=not state.thread_id)
            hw.assert_no_secret(prompt, known, "the task prompt")
            async with _turn_slots():
                run_id = await self._start(mc, state, prompt)
                self._run_id = run_id
                status = await self._wait(mc, state.thread_id, run_id)
                reply = await self._read_reply(mc, state.thread_id, run_id)
            try:
                sync = await self._sync_back(ssh, state, root, scratch)
            except (hw.HubWorkspaceError, OSError, tarfile.TarError) as exc:
                sync = f"[hub sync FAILED: {exc}] the hub copy {state.ws_id} is kept for a retry"
            text = reply or f"(hub thread ended with status {status} without a reply)"
            yield AgentEvent("text", f"{text}\n\n{sync}".strip())
            if status in {"failed", "cancelled", "rolled_back"}:
                raise hw.HubWorkspaceError(f"hub thread ended with status {status}")
        finally:
            self._run_id = None
            hw.rmtree_quiet(scratch)

    def _upload_note(self, fresh: bool, plan: hw.UploadPlan) -> str:
        skipped = f", {len(plan.skipped)} excluded (credentials/limits)" if plan.skipped else ""
        kind = "uploading" if fresh else "refreshing"
        return f"hub: {kind} {len(plan.manifest)} files ({plan.total_bytes // 1024} KiB){skipped}"

    def _prompt(self, message: str, *, first: bool) -> str:
        parts = list(self._early_steer) + [message]
        self._early_steer = []
        body = "\n\n".join(parts)
        return PREAMBLE + body if first else body

    async def _start(self, mc: MultiCodeClient, state: hw.WorkspaceState, prompt: str) -> str:
        if state.thread_id:
            try:
                sent = await mc.tool_call("t3_thread_send", {
                    "threadId": state.thread_id, "message": prompt, "mode": "auto"})
                return sent["runId"]
            except (MultiCodeError, KeyError, TypeError) as exc:
                logger.warning("hub thread %s unusable (%s); starting a new one", state.thread_id, exc)
                state.thread_id = ""
                prompt = PREAMBLE + prompt
        instance, hub_model = HUB_MODELS[self.model]
        launched = await mc.tool_call("t3_thread_launch", {
            "title": f"{state.ws_id}", "projectId": state.project_id, "message": prompt,
            "runtimeMode": "full-access",
            "modelSelection": {"instanceId": instance, "model": hub_model},
        })
        if not isinstance(launched, dict) or not launched.get("threadId"):
            raise MultiCodeError("MultiCode launch returned no threadId")
        state.thread_id = launched["threadId"]
        state.save()
        run_id = launched.get("runId")
        if not run_id:
            raise MultiCodeError("MultiCode launch returned no runId")
        return run_id

    async def _wait(self, mc: MultiCodeClient, thread_id: str, run_id: str) -> str:
        limit = float(os.environ.get("MULTICODE_HUB_TURN_TIMEOUT_S", "14400"))
        deadline = time.monotonic() + limit
        while True:
            waited = await mc.tool_call("t3_thread_wait", {
                "threadId": thread_id, "runId": run_id, "timeoutMs": WAIT_SLICE_MS})
            status = waited.get("status", "") if isinstance(waited, dict) else ""
            if not (isinstance(waited, dict) and waited.get("timedOut")) and status in TERMINAL:
                return status
            if self._abort:
                return "interrupted"
            if time.monotonic() > deadline:
                with contextlib.suppress(Exception):
                    await mc.tool_call("t3_thread_interrupt", {"threadId": thread_id})
                raise MultiCodeError("hub thread exceeded the turn time limit")

    async def _read_reply(self, mc: MultiCodeClient, thread_id: str, run_id: str) -> str:
        read = await mc.tool_call("t3_thread_read", {
            "threadId": thread_id, "view": "messages", "limit": 100})
        return _last_assistant_text(read, run_id) or ""

    async def _sync_back(self, ssh: hw.HubSsh, state: hw.WorkspaceState, root: Path,
                         scratch: Path) -> str:
        out = scratch / "out.tar"
        await ssh.get(state.remote_dir, out)
        result = await asyncio.to_thread(hw.apply_changes, out, root, state.manifest)
        state.manifest = result.manifest
        state.turns += 1
        commit = ""
        if result.changed or result.deleted:
            message = f"{_branch_task_ref(self.cwd)}: hub worker turn {state.turns} ({self.model})"
            try:
                commit = await asyncio.to_thread(
                    hw.commit_sync, root, result.changed, result.deleted, message)
            except (hw.HubWorkspaceError, subprocess.SubprocessError) as exc:
                commit = f"NOT COMMITTED ({exc})"
        state.save()
        lines = [f"[hub sync] changed {len(result.changed)}, deleted {len(result.deleted)}"
                 + (f", commit {commit}" if commit else "")]
        if result.conflicts:
            lines.append("conflicts (both sides changed, hub copy NOT applied): "
                         + ", ".join(result.conflicts[:20]))
        if result.rejected:
            lines.append("rejected: " + "; ".join(f"{p} ({why})" for p, why in result.rejected[:20]))
        return "\n".join(lines)

    # ── accounting ──

    def _turn_end(self, ok: bool, stop_reason: str, detail: str) -> AgentEvent:
        usage = TurnUsage(
            AggregateUsage.normalized(),
            current_context(None, 200000,
                            unknown_reason="the hub does not report token usage to the broker"),
        )
        elapsed = (None if self._turn_started is None
                   else max(0, round((time.perf_counter() - self._turn_started) * 1000)))
        content = f"stop_reason={stop_reason}" + (f" ({detail})" if detail else "")
        return AgentEvent("turn_end", content, metadata={
            "event_id": str(uuid4()),
            "session_id": self.session_id,
            "ok": ok,
            "stop_reason": stop_reason,
            "num_turns": 1,
            "cost_usd": 0.0,
            "cost_usd_cached": 0.0,
            "cost_is_delta": True,
            "cache_hit": 0.0,
            "billing_mode": "free",
            "cost_unaccounted": False,
            "provider_source_records": [],
            "turn_duration_ms": elapsed,
            "api_duration_ms": None,
            "reasoning_tokens": None,
            "duration_basis": "turn" if elapsed is not None else None,
            **usage.metadata(),
        }, usage=usage)

    def build_handoff_manifest(self, prepared, *, validation_profile: bool):
        from app.runtime_history import build_model_visible_manifest

        return build_model_visible_manifest(
            runtime="hub", model=self.model, effective_window=200000, system_prompt="",
            prepared=prepared, validation_profile=validation_profile,
            project_docs=getattr(prepared, "project_docs", ()), mcp_servers={})


async def release_for_worktree(worktree: str) -> list[str]:
    """Remove every hub workspace that belongs to this worktree (worker killed or merged).
    Returns the workspace ids that were cleaned; a failure is raised after the rest ran."""
    states = hw.states_for_worktree(worktree)
    if not states:
        return []
    cleaned: list[str] = []
    errors: list[str] = []
    ssh = hw.HubSsh.from_env()
    mc = None
    if hub_configured() is None:
        mc = MultiCodeClient.from_env()
        await mc.__aenter__()
    try:
        for state in states:
            try:
                await hw.release_workspace(state, ssh, mc)
                cleaned.append(state.ws_id)
            except hw.HubWorkspaceError as exc:
                errors.append(f"{state.ws_id}: {exc}")
    finally:
        if mc is not None:
            await mc.__aexit__(None, None, None)
    if errors:
        raise hw.HubWorkspaceError("; ".join(errors))
    return cleaned


ORPHAN_MIN_AGE_S = 3600


def _all_states() -> list[hw.WorkspaceState]:
    if not hw.STATE_DIR.is_dir():
        return []
    return [st for p in sorted(hw.STATE_DIR.glob("hub-*.json"))
            if (st := hw.WorkspaceState.load(p.stem)) is not None]


async def sweep_orphans(live_worktrees: set[str], *, min_age: float = ORPHAN_MIN_AGE_S) -> dict:
    """Release hub workspaces whose worker is gone, and hub leftovers that have no local record.

    A workspace belongs to a live worker when its worktree is still registered for a session, so
    an idle-but-alive worker keeps its copy. Hub-side debris (directories and projects under
    our root with no record) is removed only when older than `min_age`, which is longer than any
    upload, because the record is written before the first hub write."""
    report: dict = {"released": [], "remote_dirs": [], "projects": [], "kept": 0, "errors": []}
    states = _all_states()
    if hub_configured() is not None:
        if states:
            report["errors"].append(hub_configured())
        return report
    live = {os.path.realpath(p) for p in live_worktrees if p}
    ssh = hw.HubSsh.from_env()
    async with MultiCodeClient.from_env() as mc:
        for state in states:
            if os.path.realpath(state.worktree) in live and Path(state.worktree).is_dir():
                report["kept"] += 1
                continue
            try:
                await hw.release_workspace(state, ssh, mc)
                report["released"].append(state.ws_id)
            except hw.HubWorkspaceError as exc:
                report["errors"].append(f"{state.ws_id}: {exc}")
        known = {st.ws_id for st in _all_states()}
        root = await ssh.root()
        dirs = dict(await ssh.list_workspaces())
        now = time.time()

        def stale(ws_id: str) -> bool:
            return ws_id not in known and (ws_id not in dirs or now - dirs[ws_id] > min_age)

        cursor = None
        while True:
            page = await mc.tool_call("t3_project_list", {"limit": 100, **({"cursor": cursor} if cursor else {})})
            for project in page.get("projects", []):
                workspace = str(project.get("workspaceRoot") or "")
                ws_id = os.path.basename(workspace)
                if os.path.dirname(workspace) != root or not hw._WS_ID.match(ws_id) or not stale(ws_id):
                    continue
                threads = []
                try:
                    listed = await mc.tool_call("t3_thread_list", {"projectId": project["id"], "limit": 100})
                    threads = [t["threadId"] for t in listed.get("threads", [])]
                    await mc.tool_call("t3_project_delete", {"projectId": project["id"], "force": True})
                    for thread_id in threads or [""]:
                        await ssh.scrub_traces(ws_id, thread_id)
                    report["projects"].append(ws_id)
                except (MultiCodeError, hw.HubWorkspaceError) as exc:
                    report["errors"].append(f"project {ws_id}: {exc}")
            cursor = page.get("nextCursor")
            if cursor is None:
                break
        for ws_id in sorted(dirs):
            if stale(ws_id):
                try:
                    await ssh.remove(f"{root}/{ws_id}")
                    await ssh.scrub_traces(ws_id, "")
                    report["remote_dirs"].append(ws_id)
                except hw.HubWorkspaceError as exc:
                    report["errors"].append(f"dir {ws_id}: {exc}")
    return report
