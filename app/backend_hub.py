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
import re
import subprocess
import tarfile
import time
from pathlib import Path
from typing import AsyncIterator, Optional
from uuid import uuid4

from app import hub_workspace as hw
from app.hub_activity import HubActivityStream
from app.hub_outbox import OUTBOX_NAME, OutboxReport, parse_outbox
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
WAIT_SLICE_MS = 4_000   # also the poll interval of the live activity feed
NO_WORK_RETRIES = 2
# Count UTF-16 units conservatively for the hub's JavaScript message schema.
HUB_MESSAGE_MAX_UNITS = 120_000

PREAMBLE_BASE = (
    "You are a worker on a remote machine. Your current directory is a private copy of a "
    "repository (no .git, no remote). Edit files in place with your normal tools; when you "
    "finish, the platform copies every changed file back and commits it, so do not run git "
    "push/clone/commit, do not look for credentials or tokens (there are none), and do not "
    "create files outside this directory except uv's own cache as described below. "
    "Tests themselves must work offline. End with a concise "
    "report: what you changed, what you ran and its result, anything unfinished.\n\n"
)


OUTBOX_SECTION = (
    "<orchestra-link>\n"
    "## Reaching Orchestra (optional)\n"
    "You have no Orchestra tools. To reach it, append one JSON object per line to "
    f"`{OUTBOX_NAME}` in the root of this directory; the platform runs the lines when your turn "
    "ends. It is not part of your result and no answer arrives during this turn. Only these exist:\n"
    "{send_line}"
    '- `{{"tool":"update_progress","args":{{"percent":40,"status":"short phase description"}}}}`\n'
    '- `{{"tool":"update_checklist","args":{{"items":["step"],"completed":[],"current":0,'
    '"estimates_minutes":[5]}}}}` (each new or changed step needs a positive estimate in minutes)\n'
    "Nothing else is available from here: the task text already holds everything you need, and "
    "any other line in the file is dropped.\n"
    "</orchestra-link>\n\n"
)


def hub_preamble(who, task_ref: str = "", *, has_link: bool = False) -> str:
    """The trimmed prompt a hub model gets: role, task rules, the outbox tools, the report
    contract. It leaves out everything that assumes native MCP tools or the full pipeline."""
    from app.pipeline import DEFAULT_PIPELINE, prompt_path
    from app.prompting import safe_format_prompt

    parent = getattr(who, "parent_name", "") or ""
    try:
        role = prompt_path(getattr(who, "pipeline", "") or DEFAULT_PIPELINE, "hub/worker.md").read_text()
    except OSError:
        role = ""
    if role:
        role = safe_format_prompt(
            role, worker_name=getattr(who, "name", "") or "worker",
            orchestrator_name=parent or "orchestrator", scope=getattr(who, "scope", ""),
            branch=getattr(who, "branch", "") or "your branch").rstrip() + "\n\n"
    else:
        role = PREAMBLE_BASE
    where = (f"Put any notes, reports or other task artifacts under .orchestra/tasks/{task_ref}/ "
             "(create it); nowhere else outside the source tree.\n\n") if task_ref else ""
    link = ""
    if has_link:
        send = (f'- `{{"tool":"send_message","args":{{"message":"..."}}}}` goes to your orchestrator '
                f'{parent} only; any "to" is ignored\n') if parent else ""
        link = OUTBOX_SECTION.replace("{send_line}", send).replace("{{", "{").replace("}}", "}")
    return f"{role}{hw.HUB_UV_INSTRUCTIONS}{where}{link}Task:\n"


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


_HISTORY = re.compile(r"(<prior-conversation>)(.*?)(</prior-conversation>)", re.S)


class HubProviderLimit(hw.HubWorkspaceError):
    """Provider refused this turn because a usage or rate limit was reached."""


class _RunEvidence:
    """Run-scoped evidence; incomplete activity must never authorize replaying work."""

    def __init__(self, run_id: str):
        self.run_id = run_id
        self.reasons: list[str] = []
        self.limit: str | None = None
        self.tool_activity = False
        self.activity_complete = True

    def failure(self, value: object) -> None:
        self.limit = self.limit or _provider_limit(value)
        if isinstance(value, dict):
            for key in ("error", "errorMessage", "lastError", "failureReason", "reason", "message", "code"):
                self.failure(value.get(key))
        elif isinstance(value, list):
            for part in value:
                self.failure(part)
        elif isinstance(value, str) and value.strip() and value not in self.reasons:
            self.reasons.append(value.strip())

    def page(self, page: object) -> None:
        if not isinstance(page, dict):
            return
        # T3 currently returns recentRuns; also accept the runs field our client used.
        for run in (page.get("recentRuns") or []) + (page.get("runs") or []):
            if isinstance(run, dict) and (run.get("runId") or run.get("id")) == self.run_id:
                self.failure(run)
        thread = page.get("thread")
        if (isinstance(thread, dict) and thread.get("latestRunId") == self.run_id
                and thread.get("status") in {"failed", "cancelled", "rolled_back"}):
            self.failure(thread)
        for item in page.get("items") or []:
            if not isinstance(item, dict) or item.get("runId") != self.run_id:
                continue
            kind = str(item.get("type", "")).lower()
            # This broker-generated item is present before the provider starts.
            preparation = ":native-item:workspace-preparation" in str(item.get("itemId", ""))
            if not preparation and any(word in kind for word in (
                    "tool", "command", "file_change", "file_edit", "web_search", "image_generation")):
                self.tool_activity = True
            if item.get("status") == "failed" or "error" in kind:
                self.failure(item)
                self.failure(item.get("text"))
                self.failure(item.get("title"))

    def description(self) -> str:
        return "hub reason: " + "; ".join(self.reasons) if self.reasons else "no reason exposed by hub"


def _provider_limit(value: object, *, failed: bool = True) -> str | None:
    """Extract a safe limit category, without forwarding provider account identifiers."""
    if isinstance(value, dict):
        for key in ("error", "errorMessage", "lastError", "failureReason", "message", "code", "status"):
            found = _provider_limit(value.get(key), failed=failed)
            if found:
                return found
        return None
    if not isinstance(value, str):
        return None
    if not failed and not re.search(
        r"^\s*(?:error[: ]|rate[_ -]?limit|usage[_ -]?limit|too many requests|"
        r"you(?:'ve| have) (?:hit|reached)|(?:weekly|5h|5-hour) limit|"
        r"quota (?:exceeded|exhausted))", value, re.I,
    ):
        return None
    if re.search(r"context[_ -]?(?:length[_ -]?)?limit|token[_ -]?limit|max[_ -]?turns", value, re.I):
        return None
    patterns = (
        (r"rate[_ -]?limit|too many requests|\b429\b", "rate limit"),
        (r"weekly.{0,30}limit|limit.{0,30}weekly", "Weekly usage limit"),
        (r"(?:5h|5.hour|five.hour).{0,30}limit", "5h usage limit"),
        (r"usage[_ -]?(?:limit|cap)|quota[_ -]?(?:exceeded|exhausted)|"
         r"insufficient_quota|limit[_ -]?(?:reached|exceeded)|"
         r"you(?:'ve| have) hit your limit", "usage limit"),
    )
    return next((label for pattern, label in patterns if re.search(pattern, value, re.I)), None)


def _workspace_lost(exc: Exception) -> bool:
    """The hub says the project it was asked to start in does not exist (any more)."""
    if isinstance(exc, MultiCodeError) and (exc.retryable or exc.invalid_params):
        return False
    text = str(exc).lower()
    return "orchestration_error" in text or "not_found" in text or "not found" in text


def _redact_history(prompt: str, known: list[str]) -> str:
    """The conversation carried over from another runtime is masked, never refused; the rest of
    the prompt is still checked strictly by the caller."""
    return _HISTORY.sub(lambda m: m.group(1) + hw.redact_secrets(m.group(2), known) + m.group(3), prompt)


def _relative(event: AgentEvent, remote_dir: str) -> AgentEvent:
    """Show hub paths as worktree-relative ones: the chat is about the repo, not the hub's layout."""
    if remote_dir and remote_dir in event.content:
        event.content = event.content.replace(remote_dir + "/", "").replace(remote_dir, ".")
    return event


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
                 paths: list[str] | None = None, scope: str = "", paths_source=None, bridge=None,
                 pipeline: str = "", role: str = ""):
        if model not in HUB_MODELS:
            raise ValueError(f"unknown hub model '{model}'")
        self.model = model
        self._effort = effort
        self._pipeline = pipeline
        self._role = role
        self._effort_options: dict[tuple[str, str], tuple[str, tuple[str, ...]]] | None = None
        self.cwd = cwd
        self._resume = resume_session_id
        self._paths = paths
        # Live owner of the worker's owned_dirs: they change between turns (set_worker_owned_dirs), and the
        # upload must follow them. `paths` stays as the fixed value for a caller without such an owner.
        self._paths_source = paths_source
        self._bridge = bridge        # hub_outbox.HubBridge: the worker's identity and its outbox executor
        self._scope = scope
        self._state: Optional[hw.WorkspaceState] = None
        self._mc: Optional[MultiCodeClient] = None
        self._ssh: Optional[hw.HubSsh] = None
        self._pending: Optional[str] = None
        self._turn_active = False
        self._abort = False
        self._run_id: Optional[str] = None
        self._early_steer: list[str] = []
        self._turn_started: float | None = None
        self._watch_status = ''
        self._watch_limit: str | None = None
        self._run_evidence: _RunEvidence | None = None
        self._sync_no_work = False
        self._uv_ready = False

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

    async def _model_selection(self, mc: MultiCodeClient, model: str,
                               effort: str | None) -> dict:
        instance, hub_model = HUB_MODELS[model]
        selection = {"instanceId": instance, "model": hub_model}
        if effort is None:
            return selection
        if self._effort_options is None:
            capabilities = await mc.tool_call("orchestrator_capabilities", {})
            if not isinstance(capabilities, dict) or not isinstance(capabilities.get("providers"), list):
                raise ValueError("hub capabilities contain no provider model options")
            options = {}
            for provider in capabilities["providers"]:
                for advertised in provider.get("models", []):
                    for option in advertised.get("options", []):
                        # Codex/Grok use reasoningEffort; Claude advertises effort.
                        if option.get("id") in ("reasoningEffort", "effort") and option.get("type") == "select":
                            options[(provider["providerInstanceId"], advertised["id"])] = (
                                option["id"], tuple(value["id"] for value in option.get("options", [])))
                            break
            self._effort_options = options
        option_id, allowed = self._effort_options.get((instance, hub_model), ("reasoningEffort", ()))
        if effort not in allowed:
            raise ValueError(
                f"hub model '{model}' does not support effort '{effort}'; "
                f"allowed values: {', '.join(allowed) or '(none advertised)'}")
        selection["options"] = {option_id: effort}
        return selection

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
                await hw.check_workspace_file_policy(self._ssh, state)
                mc = await self._client()
                wire = await self._wire_message(mc, state, message)
                await mc.tool_call("t3_thread_send", {
                    "threadId": state.thread_id, "message": wire, "mode": "steer"})
                return
            except MultiCodeError as exc:
                if exc.retryable or exc.invalid_params:
                    raise  # Delivery may have succeeded; do not queue the same steer again.
                logger.warning("hub steer failed, queuing instead: %s", exc)
        self._early_steer.append(message)

    async def retarget_model(self, model: str) -> None:
        """Switch the hub model of this worker: the workspace stays, and the live hub thread is
        re-configured so its own history is kept. If the hub refuses (e.g. across providers), the
        next turn opens a new thread and says so, instead of failing the switch."""
        if model not in HUB_MODELS:
            raise ValueError(f"unknown hub model '{model}'")
        if self._turn_active:
            raise RuntimeError("cannot retarget a hub worker while a turn is active")
        if self._state is not None:
            await hw.check_workspace_file_policy(self._ssh, self._state)
        from app.hub_pool import require_hub_capacity

        await require_hub_capacity(model)
        effort = self._effort
        if self._pipeline and self._role:
            from app.pipeline import get_role, resolve_effort
            role = get_role(self._pipeline, self._role)
            if role is not None:
                effort = resolve_effort(role.effort, model, "hub")
        state = self._state
        mc = await self._client() if effort is not None or (state and state.thread_id) else None
        # Validation errors must propagate, not trigger the new-thread fallback.
        selection = await self._model_selection(mc, model, effort)
        if state and state.thread_id:
            try:
                await mc.tool_call("t3_thread_configure", {
                    "threadId": state.thread_id,
                    "modelSelection": selection})
            except MultiCodeError as exc:
                if exc.retryable or exc.invalid_params:
                    raise
                logger.warning("hub thread re-configure refused (%s); next turn starts a new thread", exc)
                state.thread_id = ""
                state.save()
                self._early_steer.append(
                    "[Note: the model was changed and the earlier hub conversation is not available "
                    "to you; the files in this directory contain the work done so far.]")
        self.model = model
        self._effort = effort

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
            limit = str(exc) if isinstance(exc, HubProviderLimit) else _provider_limit(str(exc))
            ok, stop_reason, detail = False, "hub_provider_limit" if limit else "hub_error", str(exc)
            if limit:
                from app.hub_pool import alternative_model, provider_for_model

                detail = (f"Hub {provider_for_model(self.model) or 'provider'} {limit}; "
                          f"use model='{alternative_model(self.model)}'")
                if self._bridge is not None:
                    try:
                        report = await self._bridge.run([
                            {"tool": "send_message", "args": {"message": detail}}])
                        if report.dropped:
                            detail += "; parent notification failed"
                    except Exception:
                        logger.exception("hub limit parent notification failed")
                        detail += "; parent notification failed"
            yield AgentEvent("error", f"Hub worker turn failed: {detail}",
                             metadata={"hub_provider_limit": bool(limit)})
        finally:
            self._turn_active = False
        if self._abort:
            ok, stop_reason = False, "interrupted"
        yield self._turn_end(ok, stop_reason, detail)

    async def _run_turn(self, message: str) -> AsyncIterator[AgentEvent]:
        from app.hub_pool import require_hub_capacity
        from app.quota_gate import QuotaGateError

        # Check retained evidence before replacing a released record or cleaning
        # up an older workspace. A new thread must not erase the incident trail.
        retained = hw.states_for_worktree(self.cwd)
        if self._state is not None:
            self._state.assert_file_policy()
        for previous in retained:
            previous.assert_file_policy()
        try:
            warning = await require_hub_capacity(self.model)
        except QuotaGateError as exc:
            raise hw.HubWorkspaceError(str(exc)) from exc
        if warning:
            yield AgentEvent("status", warning)
        self._watch_limit = None
        mc = await self._client()
        ssh = self._ssh
        assert ssh is not None
        for previous in retained:
            if previous.remote_dir:
                await hw.check_workspace_file_policy(ssh, previous)
        known = hw.known_secret_values([getattr(mc, "_token", "")])
        root = Path(self.cwd)
        state = self._state
        if state is not None and not state.path().exists():
            # Released behind this backend's back (merge, task switch, sweep): the hub project and
            # copy are gone, and saving this old record again would resurrect a dead workspace.
            logger.info("hub workspace %s was released; starting a new one", state.ws_id)
            state = self._state = None
        if state is None or not state.remote_dir:
            state = hw.WorkspaceState(
                ws_id=hw.WorkspaceState.new_id(), worktree=str(root.resolve()), remote_dir="")
            state.remote_dir = await ssh.dir_for(state.ws_id)
            self._state = state
            state.save()   # before any hub write, so a crash leaves a record the sweep can release
            try:
                await release_for_worktree(self.cwd, keep_ws_id=state.ws_id, ssh=ssh, mc=mc)
            except hw.HubFilePolicyError:
                raise
            except Exception as exc:
                logger.warning("hub previous workspace release incomplete (state kept for sweep): %s", exc)
        # A record exists from the first attempt on, but the workspace only from the first upload that
        # reached the hub: a turn that failed before it (e.g. tree too large) must retry as a first upload.
        fresh = not (state.uploaded or state.manifest)
        state.paths = self._current_paths(state)
        options = hw.project_options(self._scope)
        hw.require_scope(state.paths, options)
        plan = await asyncio.to_thread(hw.plan_upload, root, state.paths or None, known, options)
        yield AgentEvent("status", self._upload_note(fresh, plan))
        scratch = hw.local_scratch()
        try:
            for note in await self._provision(mc, ssh, root, state, plan, options, fresh, scratch):
                yield AgentEvent("status", note)
            steer_count = len(self._early_steer)
            prompt = self._prompt(message, first=not state.thread_id)
            async with _turn_slots():
                try:
                    await hw.check_workspace_file_policy(ssh, state)
                    run_id = await self._start(mc, state, prompt)
                except MultiCodeError as exc:
                    if not _workspace_lost(exc):
                        raise
                    # The hub project (or its copy) no longer exists: build the workspace again, once.
                    logger.warning("hub refused to start in %s (%s); recreating the project and re-uploading",
                                   state.ws_id, exc)
                    yield AgentEvent("status", "hub: the project is gone on the hub; recreating it and "
                                               "uploading again")
                    first_prompt = prompt if prompt.startswith(self._preamble()) else self._preamble() + prompt
                    state.project_id = state.thread_id = ""
                    state.manifest, state.hub_made, state.uploaded = {}, [], False
                    await ssh.remove(state.remote_dir)
                    plan = await asyncio.to_thread(hw.plan_upload, root, state.paths or None, known, options)
                    for note in await self._provision(mc, ssh, root, state, plan, options, True, scratch):
                        yield AgentEvent("status", note)
                    prompt = first_prompt
                    run_id = await self._start(mc, state, prompt)
                # Only acknowledge the snapshot included in the accepted turn. Steers
                # arriving during upload/start belong to the following turn.
                del self._early_steer[:steer_count]
                for attempt in range(NO_WORK_RETRIES + 1):
                    self._run_id = run_id
                    self._watch_limit = None
                    evidence = self._run_evidence = _RunEvidence(run_id)
                    stream = HubActivityStream(run_id, state.activity_pos or None)
                    async for event in self._watch(mc, state.thread_id, run_id, stream):
                        yield _relative(event, state.remote_dir)
                    status = self._watch_status
                    reply = await self._read_reply(mc, state.thread_id, run_id)
                    for event in stream.finish(reply):
                        yield _relative(event, state.remote_dir)
                    state.activity_pos = stream.cursor or 0
                    state.save()
                    self._sync_no_work = False
                    sync_error = None
                    try:
                        sync = await self._sync_back(ssh, state, root, scratch)
                    except (hw.HubWorkspaceError, OSError, tarfile.TarError) as exc:
                        sync = f"[hub sync FAILED: {exc}] the hub copy {state.ws_id} is kept for a retry"
                        sync_error = sync
                    failure = f"hub thread ended with status {status}; {evidence.description()}"
                    text = reply or f"(hub thread ended with status {status} without a reply)"
                    if not reply and status in {"failed", "cancelled", "rolled_back"}:
                        text += f"\n{evidence.description()}"
                    yield AgentEvent("text", f"{text}\n\n{sync}".strip())
                    limit = self._watch_limit or evidence.limit or _provider_limit(reply, failed=status == "failed")
                    if limit:
                        raise HubProviderLimit(limit)
                    if sync_error:
                        raise hw.HubWorkspaceError(sync_error)
                    if (status in {"failed", "cancelled"} and not reply and not self._abort
                            and not evidence.tool_activity and evidence.activity_complete
                            and self._sync_no_work and attempt < NO_WORK_RETRIES):
                        delay = attempt + 1
                        note = (f"hub: {failure}; no work detected; retry {attempt + 1}/{NO_WORK_RETRIES} "
                                f"on the same thread in {delay}s")
                        logger.warning("%s", note)
                        yield AgentEvent("status", note)
                        await asyncio.sleep(delay)
                        if self._abort:
                            return
                        # Never use _start here: its refused-thread fallback can change threads.
                        # An uncertain send is propagated, never replayed.
                        await hw.check_workspace_file_policy(ssh, state)
                        wire = await self._wire_message(mc, state, prompt)
                        sent = await mc.tool_call("t3_thread_send", {
                            "threadId": state.thread_id, "message": wire, "mode": "auto"})
                        if not isinstance(sent, dict) or not sent.get("runId"):
                            raise MultiCodeError("MultiCode retry send returned no runId")
                        run_id = sent["runId"]
                        continue
                    if status in {"failed", "cancelled", "rolled_back"}:
                        raise hw.HubWorkspaceError(failure)
                    break
        finally:
            self._run_id = None
            hw.rmtree_quiet(scratch)

    async def _provision(self, mc: MultiCodeClient, ssh: hw.HubSsh, root: Path, state: hw.WorkspaceState,
                         plan: hw.UploadPlan, options: hw.ProjectOptions, fresh: bool, scratch: Path) -> list[str]:
        """Bring the hub copy up to date with the worktree and make sure the hub project exists."""
        notes: list[str] = []
        hw.assert_file_policy(plan.manifest)
        await hw.check_workspace_file_policy(ssh, state)
        # Freeze old upload provenance before refreshing the mutable sync baseline.
        hw.capture_inputs(root, state, state.manifest if not fresh else plan.manifest)
        self._uv_ready = False
        if {"pyproject.toml", "uv.lock"} <= plan.manifest.keys():
            await ssh.ensure_uv(scratch)
            self._uv_ready = True
        tar_path = scratch / "in.tar"
        if fresh and options.persistent:
            sent, dropped = await hw.provision_from_base(ssh, root, self._scope, plan, state.remote_dir)
            notes.append(f"hub: persistent project copy reused ({sent} changed files sent, {dropped} removed)")
            state.manifest = dict(plan.manifest)
            state.uploaded = True
            state.save()
        elif fresh:
            await asyncio.to_thread(hw.write_tar, root, sorted(plan.manifest), tar_path)
            await ssh.put(state.remote_dir, tar_path)
            state.manifest = dict(plan.manifest)
            state.uploaded = True
            state.save()
        else:
            send, drop = hw.local_delta(root, plan, state.manifest, keep=set(state.hub_made))
            if send:
                await asyncio.to_thread(hw.write_tar, root, send, tar_path)
                await ssh.put(state.remote_dir, tar_path)
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
        return notes

    def _current_paths(self, state: hw.WorkspaceState) -> list[str]:
        if self._paths_source is not None:
            return list(self._paths_source() or [])      # empty = ownership cleared = no narrowing
        return list(self._paths or state.paths or [])

    def _upload_note(self, fresh: bool, plan: hw.UploadPlan) -> str:
        skipped = f", {len(plan.skipped)} excluded (credentials/limits)" if plan.skipped else ""
        kind = "uploading" if fresh else "refreshing"
        extra = ""
        if plan.materialized:
            extra += f"; added to the sparse checkout: {', '.join(plan.materialized)}"
        if plan.new_paths:
            extra += f"; new: {', '.join(plan.new_paths)}"
        return f"hub: {kind} {len(plan.manifest)} files ({plan.total_bytes // 1024} KiB){skipped}{extra}"

    def _prompt(self, message: str, *, first: bool) -> str:
        parts = list(self._early_steer) + [message]
        body = "\n\n".join(parts)
        if not first:
            # Also update a thread that predates uv provisioning, or resumed without PATH.
            return (hw.HUB_UV_INSTRUCTIONS if self._uv_ready else "") + body
        return self._preamble() + body

    def _preamble(self) -> str:
        task = _branch_task_ref(self.cwd).lstrip("#")
        who = self._bridge.identity() if self._bridge is not None else None
        return hub_preamble(who, task if task != "hub" else "", has_link=self._bridge is not None)

    async def _wire_message(self, mc: MultiCodeClient, state: hw.WorkspaceState, prompt: str) -> str:
        known = hw.known_secret_values([getattr(mc, "_token", "")])
        prompt = _redact_history(prompt, known)
        hw.assert_no_secret(prompt, known, "the task prompt")
        units = len(prompt.encode("utf-16-le", errors="surrogatepass")) // 2
        if units <= HUB_MESSAGE_MAX_UNITS:
            return prompt
        if self._ssh is None:
            raise hw.HubWorkspaceError("hub workspace transport is unavailable for the task prompt")
        data = prompt.encode("utf-8")
        scratch = hw.local_scratch()
        try:
            rel = await self._ssh.put_prompt(state.remote_dir, data, scratch)
        finally:
            hw.rmtree_quiet(scratch)
        logger.info("hub message via workspace: %d UTF-16 units, %d UTF-8 bytes", units, len(data))
        return (
            f"Read ./{rel} in full before acting. It is the complete message for this turn "
            f"({len(data)} UTF-8 bytes), delivered through the private workspace because it "
            "exceeds the hub message field limit. Read in chunks if needed; follow all its "
            "instructions and preserve their order. Do not edit this broker input file."
        )

    async def _start(self, mc: MultiCodeClient, state: hw.WorkspaceState, prompt: str) -> str:
        # A reconstructed backend can resume a thread created with an older effort.
        selection = await self._model_selection(mc, self.model, self._effort)
        if state.thread_id:
            try:
                wire = await self._wire_message(mc, state, prompt)
                if self._effort is not None:
                    await mc.tool_call("t3_thread_configure", {
                        "threadId": state.thread_id, "modelSelection": selection})
                sent = await mc.tool_call("t3_thread_send", {
                    "threadId": state.thread_id, "message": wire, "mode": "auto"})
            except MultiCodeError as exc:
                # Delivery is uncertain on transport errors. Launching again can duplicate work.
                if exc.retryable or exc.invalid_params:
                    raise
                logger.warning("hub thread %s unusable (%s); starting a new one", state.thread_id, exc)
                preamble = self._preamble()
                if not prompt.startswith(preamble):
                    prompt = preamble + prompt
            else:
                if not isinstance(sent, dict) or not sent.get("runId"):
                    raise MultiCodeError("MultiCode send returned no runId")
                return sent["runId"]
        wire = await self._wire_message(mc, state, prompt)
        launched = await mc.tool_call("t3_thread_launch", {
            "title": f"{state.ws_id}", "projectId": state.project_id, "message": wire,
            "runtimeMode": "full-access",
            "modelSelection": selection,
        })
        if not isinstance(launched, dict) or not launched.get("threadId"):
            raise MultiCodeError("MultiCode launch returned no threadId")
        state.thread_id = launched["threadId"]
        state.save()
        run_id = launched.get("runId")
        if not run_id:
            raise MultiCodeError("MultiCode launch returned no runId")
        return run_id

    async def _watch(self, mc: MultiCodeClient, thread_id: str, run_id: str,
                     stream: HubActivityStream) -> AsyncIterator[AgentEvent]:
        """Wait for the run, translating new timeline items into events every poll slice."""
        limit = float(os.environ.get("MULTICODE_HUB_TURN_TIMEOUT_S", "14400"))
        deadline = time.monotonic() + limit
        while True:
            waited = await self._watch_call(mc, "t3_thread_wait", {
                "threadId": thread_id, "runId": run_id, "timeoutMs": WAIT_SLICE_MS})
            status = waited.get("status", "") if isinstance(waited, dict) else ""
            status_limit = _provider_limit(status)
            terminal = not (isinstance(waited, dict) and waited.get("timedOut")) and (status in TERMINAL or status_limit is not None)
            for event in await self._poll(mc, thread_id, stream):
                yield event
            if terminal:
                if self._run_evidence is not None:
                    self._run_evidence.failure(waited)
                self._watch_limit = self._watch_limit or status_limit or _provider_limit(waited)
                self._watch_status = status
                return
            if self._abort:
                self._watch_status = "interrupted"
                return
            if time.monotonic() > deadline:
                with contextlib.suppress(Exception):
                    await mc.tool_call("t3_thread_interrupt", {"threadId": thread_id})
                raise MultiCodeError("hub thread exceeded the turn time limit")

    async def _watch_call(self, mc: MultiCodeClient, name: str, arguments: dict):
        """Bounded recovery for read calls only; never replay a send or launch here."""
        last_error = None
        try:
            async with asyncio.timeout(60):
                for attempt in range(5):
                    try:
                        return await mc.tool_call(name, arguments)
                    except MultiCodeError as exc:
                        if not exc.retryable or attempt == 4 or self._abort:
                            raise
                        last_error = exc
                        delay = 2 ** attempt
                        logger.warning("hub %s failed; retrying in %ss: %s", name, delay, exc)
                        await asyncio.sleep(delay)
        except TimeoutError:
            if last_error is not None:
                raise last_error from None
            raise MultiCodeError("hub watch request exceeded 60 seconds", retryable=True) from None

    async def _poll(self, mc: MultiCodeClient, thread_id: str, stream: HubActivityStream) -> list[AgentEvent]:
        """New timeline items since the cursor. A failed poll only loses live detail, never the turn."""
        events: list[AgentEvent] = []
        try:
            for _ in range(20):
                args = {"threadId": thread_id, "view": "activity", "limit": 100, "maxCharsPerItem": 6000}
                if stream.cursor is not None:
                    args["afterPosition"] = stream.cursor
                page = await self._watch_call(mc, "t3_thread_read", args)
                if self._run_evidence is not None:
                    self._run_evidence.page(page)
                    if not isinstance(page, dict) or not isinstance(page.get("items"), list):
                        self._run_evidence.activity_complete = False
                items = page.get("items", []) if isinstance(page, dict) else []
                events.extend(stream.feed(items))
                if not (isinstance(page, dict) and page.get("hasMore")) or not items:
                    if isinstance(page, dict) and page.get("hasMore") and self._run_evidence is not None:
                        self._run_evidence.activity_complete = False
                    break
            else:
                if self._run_evidence is not None:
                    self._run_evidence.activity_complete = False
        except MultiCodeError as exc:
            if self._run_evidence is not None:
                self._run_evidence.activity_complete = False
            logger.warning("hub activity poll failed: %s", exc)
        return events

    async def _read_reply(self, mc: MultiCodeClient, thread_id: str, run_id: str) -> str:
        read = await self._watch_call(mc, "t3_thread_read", {
            "threadId": thread_id, "view": "messages", "limit": 100})
        if isinstance(read, dict):
            if self._run_evidence is not None:
                self._run_evidence.page(read)
            for run in (read.get("recentRuns") or []) + (read.get("runs") or []):
                if isinstance(run, dict) and (run.get("id") or run.get("runId")) == run_id:
                    self._watch_limit = self._watch_limit or _provider_limit(run)
        return _last_assistant_text(read, run_id) or ""

    async def _sync_back(self, ssh: hw.HubSsh, state: hw.WorkspaceState, root: Path,
                         scratch: Path) -> str:
        await hw.check_workspace_file_policy(ssh, state)
        out = scratch / "out.tar"
        await ssh.get(state.remote_dir, out)
        before = dict(state.manifest)
        hw.capture_inputs(root, state, state.manifest)
        result = await asyncio.to_thread(hw.apply_changes, out, root, state.manifest,
                                        inputs=state.input_manifest)
        if any(hw._company_path(rel) for rel, _ in result.rejected):
            # The snapshot is new evidence, including if someone later removes
            # the file. Preserve it as a latch without rewriting old provenance.
            state.file_policy_blocked = True
        no_work = not (result.changed or result.deleted or result.conflicts
                       or result.rejected or result.outbox or result.manifest != before)
        state.manifest = result.manifest
        state.hub_made = sorted((set(state.hub_made) | {r for r, d in result.manifest.items()
                                                         if before.get(r) != d}) & set(result.manifest))
        state.turns += 1
        outbox_line = await self._run_outbox(ssh, state, result.outbox)
        commit, unstaged = "", []
        if result.changed or result.deleted:
            message = f"{_branch_task_ref(self.cwd)}: hub worker turn {state.turns} ({self.model})"
            try:
                commit, unstaged = await asyncio.to_thread(
                    hw.commit_sync, root, result.changed, result.deleted, message)
            except (hw.HubWorkspaceError, subprocess.SubprocessError) as exc:
                commit = f"NOT COMMITTED ({exc})"
        state.save()
        lines = [f"[hub sync] changed {len(result.changed)}, deleted {len(result.deleted)}"
                 + (f", commit {commit}" if commit else "")]
        lines.append(f"return archive {out.stat().st_size} bytes; "
                     f"transport limit {hw.MAX_TOTAL_BYTES * 2} bytes; workspace {state.ws_id}")
        if outbox_line:
            lines.append(outbox_line)
        if unstaged:
            lines.append("left uncommitted in the worktree (git refused them): "
                         + "; ".join(f"{p} ({why})" for p, why in unstaged[:20]))
        if result.conflicts:
            lines.append("conflicts (both sides changed, hub copy NOT applied): "
                         + ", ".join(result.conflicts[:20]))
        if result.rejected:
            lines.append("rejected: " + "; ".join(f"{p} ({why})" for p, why in result.rejected[:20]))
        self._sync_no_work = no_work
        return "\n".join(lines)

    async def _run_outbox(self, ssh: hw.HubSsh, state: hw.WorkspaceState, data: bytes) -> str:
        """Run what the hub agent queued for Orchestra, then empty the file on the hub."""
        if not data.strip():
            return ""
        entries, dropped = parse_outbox(data)
        report = OutboxReport(dropped=dropped)
        try:
            await ssh.delete_files(state.remote_dir, [OUTBOX_NAME])   # each entry runs at most once
        except hw.HubWorkspaceError as exc:
            report.dropped.append(f"outbox not cleared on the hub, entries skipped: {exc}")
            entries = []
        if entries and self._bridge is None:
            report.dropped.append(f"{len(entries)} entries: this worker has no Orchestra link")
        elif entries:
            ran = await self._bridge.run(entries)
            report.done, report.dropped = ran.done, report.dropped + ran.dropped
        for reason in report.dropped:
            logger.warning("hub outbox of %s: dropped %s", state.ws_id, reason)
        return report.summary()

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


async def release_for_worktree(worktree: str, *, keep_ws_id: str = "",
                               ssh: hw.HubSsh | None = None, mc=None) -> list[str]:
    """Remove the worktree's hub workspaces, optionally keeping its replacement.
    Supplied transports belong to the caller and are not closed here.
    Returns the workspace ids that were cleaned; a failure is raised after the rest ran."""
    states = [state for state in hw.states_for_worktree(worktree) if state.ws_id != keep_ws_id]
    if not states:
        return []
    cleaned: list[str] = []
    errors: list[str] = []
    ssh = ssh or hw.HubSsh.from_env()
    owns_client = mc is None and hub_configured() is None
    if owns_client:
        mc = MultiCodeClient.from_env()
        await mc.__aenter__()
    try:
        for state in states:
            try:
                await hw.release_workspace(state, ssh, mc)
                cleaned.append(state.ws_id)
            except hw.HubFilePolicyError:
                raise
            except hw.HubWorkspaceError as exc:
                errors.append(f"{state.ws_id}: {exc}")
    finally:
        if owns_client:
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


async def sweep_orphans(live_worktrees: set[str] | dict[str, str], *, min_age: float = ORPHAN_MIN_AGE_S) -> dict:
    """Release hub workspaces whose worker is gone, and hub leftovers that have no local record.

    The mapping identifies each worktree's current workspace; older copies of a live worker
    are orphans too. Legacy set callers provide no ownership information, so keep their live
    copies conservatively. Hub-side debris (directories and projects under
    our root with no record) is removed only when older than `min_age`, which is longer than any
    upload, because the record is written before the first hub write."""
    report: dict = {"released": [], "remote_dirs": [], "projects": [], "kept": 0, "errors": []}
    states = _all_states()
    if hub_configured() is not None:
        if states:
            report["errors"].append(hub_configured())
        return report
    live = {os.path.realpath(p) for p in live_worktrees if p}
    current = ({os.path.realpath(p): ws_id for p, ws_id in live_worktrees.items() if p}
               if isinstance(live_worktrees, dict) else None)
    ssh = hw.HubSsh.from_env()
    async with MultiCodeClient.from_env() as mc:
        for state in states:
            worktree = os.path.realpath(state.worktree)
            if (worktree in live and Path(state.worktree).is_dir()
                    and (current is None or current.get(worktree) == state.ws_id)):
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
