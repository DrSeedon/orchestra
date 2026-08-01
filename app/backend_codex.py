"""CodexBackend — wraps Codex CLI subprocess for agent sessions."""

import asyncio
import json
import logging
import os
import shutil
import sys
import uuid
from pathlib import Path
from typing import AsyncIterator, Optional

from app.backend_jsonrpc import JsonRpcStdioTransport, bounded_tool_arguments
from app.events import AgentEvent
from app.usage_contract import AggregateUsage, TurnUsage, current_context

logger = logging.getLogger(__name__)

CODEX_BIN = shutil.which("codex") or os.environ.get("CODEX_BIN", "codex")

# Effective context budgets reported by the ChatGPT-auth Codex runtime. The public API
# advertises a larger GPT-5.6 window, but that is a different surface; local rollout
# token_count events are the runtime source of truth and may override these fallbacks.
CODEX_CONTEXT_LIMITS = {
    "gpt-5.3-codex-spark": 128000,
    "gpt-5.6-sol":   258400,
    "gpt-5.6-terra": 258400,
    "gpt-5.6-luna":  258400,
    "gpt-5.5": 258400,
    "gpt-5.4": 258400,
    "gpt-5.4-mini": 258400,
}

CODEX_TOKEN_PRICES = {
    "gpt-5.6-sol":   {"input": 5.0, "cached": 0.5, "output": 30.0},
    "gpt-5.6-terra": {"input": 2.5, "cached": 0.25, "output": 15.0},
    "gpt-5.6-luna":  {"input": 1.0, "cached": 0.1, "output": 6.0},
    "gpt-5.5":      {"input": 5.0, "cached": 0.5, "output": 30.0},
    "gpt-5.4":      {"input": 2.5, "cached": 0.25, "output": 15.0},
    "gpt-5.4-mini": {"input": 0.3, "cached": 0.03, "output": 1.25},
}


# GPT-5.6 reasoning ladder (light→low→medium→high→xhigh→max→ultra). "minimal" kept for
# 5.4/5.5 back-compat. "ultra" (parallel sub-agents) intentionally excluded — a special
# mode, not a plain effort level, and risky to trigger from a generic worker effort field.
CODEX_REASONING_EFFORTS = {"minimal", "low", "medium", "high", "xhigh", "max"}
CODEX_SILENCE_HEARTBEAT_SECONDS = 30
CODEX_COMPACT_TIMEOUT_SECONDS = 120
CODEX_PROCESS_TIMEOUT_SECONDS = 5

_scope_support_cache: tuple[bool, dict[str, str], str] | None = None


async def _run_process(
    *cmd: str,
    env: dict[str, str] | None = None,
    timeout: float = CODEX_PROCESS_TIMEOUT_SECONDS,
) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except BaseException:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
        raise
    return (
        int(proc.returncode or 0),
        stdout.decode(errors="replace").strip(),
        stderr.decode(errors="replace").strip(),
    )


def _scope_unit(prefix: str = "orchestra-codex") -> str:
    return f"{prefix}-{os.getpid()}-{uuid.uuid4().hex}.scope"


async def _codex_scope_support() -> tuple[bool, dict[str, str], str]:
    global _scope_support_cache
    if _scope_support_cache is not None:
        return _scope_support_cache
    try:
        runtime_dir = Path(f"/run/user/{os.getuid()}")
        bus = runtime_dir / "bus"
        commands = {
            name: shutil.which(name)
            for name in ("loginctl", "systemd-run", "systemctl")
        }
        missing = [name for name, path in commands.items() if not path]
        if missing:
            raise RuntimeError(f"missing commands: {', '.join(missing)}")
        if not bus.is_socket():
            raise RuntimeError(f"systemd user bus is unavailable: {bus}")

        env = dict(os.environ)
        env["XDG_RUNTIME_DIR"] = str(runtime_dir)
        env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={bus}"
        rc, linger, stderr = await _run_process(
            commands["loginctl"], "show-user", str(os.getuid()),
            "-p", "Linger", "--value",
        )
        if rc or linger.lower() != "yes":
            detail = stderr or f"Linger={linger or 'unknown'}"
            raise RuntimeError(f"systemd user manager is not persistent: {detail}")

        unit = _scope_unit("orchestra-codex-probe")
        probe = (
            "from pathlib import Path; "
            "row = next(line for line in Path('/proc/self/cgroup').read_text().splitlines() "
            "if line.startswith('0::')); "
            "path = row.split('::', 1)[1]; "
            "events = (Path('/sys/fs/cgroup') / path.lstrip('/') / 'cgroup.events').read_text(); "
            "print(path); print(events)"
        )
        rc, cgroup, stderr = await _run_process(
            commands["systemd-run"], "--user", "--scope", "--quiet", "--collect",
            f"--unit={unit}", "--", sys.executable, "-c", probe,
            env=env,
        )
        if rc:
            raise RuntimeError(stderr or f"disposable scope exited with code {rc}")
        lines = cgroup.splitlines()
        control_group = lines[0] if lines else ""
        events = dict(
            line.split(maxsplit=1)
            for line in lines[1:]
            if " " in line
        )
        if unit not in control_group:
            raise RuntimeError(
                f"disposable process was not attached to {unit}: {control_group}"
            )
        if events.get("populated") != "1":
            raise RuntimeError(
                f"disposable scope has no usable cgroup.events: {events}"
            )
        _scope_support_cache = (True, env, "")
    except Exception as exc:
        reason = f"{type(exc).__name__}: {exc}"
        logger.warning(
            "Codex verified process scope unavailable; direct launch remains enabled "
            "but hibernation is disabled: %s",
            reason,
        )
        _scope_support_cache = (False, {}, reason)
    return _scope_support_cache


def _codex_cost(model: str, input_tokens: int, cached_input_tokens: int,
                output_tokens: int) -> float:
    """API-equivalent cost with cached input charged at its actual lower rate."""
    prices = CODEX_TOKEN_PRICES.get(model)
    if not prices:
        return 0.0
    cached = min(max(0, cached_input_tokens), max(0, input_tokens))
    fresh = max(0, input_tokens - cached)
    return (fresh * prices["input"] + cached * prices["cached"]
            + max(0, output_tokens) * prices["output"]) / 1_000_000


def _read_rollout_context(path: Path) -> dict[str, int] | None:
    """Return the last model-call context from a Codex rollout, or None fail-soft.

    `turn.completed.usage` is cumulative work for the thread and cannot represent the
    currently occupied window. Internal rollout token_count events expose both the last
    call and the runtime-provided effective model_context_window.
    """
    latest = None
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except (json.JSONDecodeError, TypeError):
                    continue
                payload = row.get("payload") or {}
                if row.get("type") != "event_msg" or payload.get("type") != "token_count":
                    continue
                info = payload.get("info") or {}
                usage = info.get("last_token_usage") or {}
                window = info.get("model_context_window")
                input_tokens = usage.get("input_tokens")
                if not isinstance(window, int) or window <= 0:
                    continue
                if not isinstance(input_tokens, int) or input_tokens < 0:
                    continue
                cached = usage.get("cached_input_tokens", 0)
                latest = {
                    "input_tokens": input_tokens,
                    "cached_input_tokens": cached if isinstance(cached, int) else 0,
                    "model_context_window": window,
                }
    except (FileNotFoundError, OSError):
        return None
    return latest


def _read_rollout_totals(path: Path) -> dict[str, int] | None:
    latest = None
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except (json.JSONDecodeError, TypeError):
                    continue
                payload = row.get("payload") or {}
                if row.get("type") != "event_msg" or payload.get("type") != "token_count":
                    continue
                total = ((payload.get("info") or {}).get("total_token_usage") or {})
                input_tokens = total.get("input_tokens")
                if not isinstance(input_tokens, int) or input_tokens < 0:
                    continue
                latest = {
                    "input_tokens": input_tokens,
                    "cached_input_tokens": max(0, int(total.get("cached_input_tokens") or 0)),
                    "output_tokens": max(0, int(total.get("output_tokens") or 0)),
                }
    except (FileNotFoundError, OSError, ValueError, TypeError):
        return None
    return latest


def _usage_delta(current: dict[str, int], baseline: dict[str, int] | None) -> dict[str, int]:
    baseline = baseline or {}
    result = {}
    for key in ("input_tokens", "cached_input_tokens", "output_tokens"):
        value = max(0, int(current.get(key) or 0))
        before = max(0, int(baseline.get(key) or 0))
        result[key] = value - before if value >= before else value
    return result


def _tool_arguments_json(arguments) -> str:
    return json.dumps(
        bounded_tool_arguments(arguments if isinstance(arguments, dict) else {}),
        ensure_ascii=False,
    )


ORCHESTRA_FULL_MCP_TOOLS = (
    "spawn_worker", "acquire_test_lock", "release_test_lock", "test_lock_status",
    "send_message", "list_agents", "list_orchestrators", "get_worker_logs",
    "compact_worker", "kill_worker", "stop_worker", "rename_worker",
    "send_file", "update_progress", "change_worker_model", "merge_worker",
    "switch_worker_branch", "check_conflict", "worker_wip", "report_bug",
    "update_worker_description", "update_worker_prompt", "get_worker_info",
    "task_create", "task_update", "task_list", "task_get", "payment_receive",
    "payment_status", "bg_create", "bg_list", "bg_cancel", "search_memory",
    "codex_review",
)


class CodexProtocolError(RuntimeError):
    """JSON-RPC error returned by Codex app-server."""

    def __init__(self, method: str, error: dict):
        self.method = method
        self.error = error
        super().__init__(f"{method}: {error.get('message', 'Codex app-server error')}")


class CodexBackend(JsonRpcStdioTransport):
    """Persistent Codex app-server client with native turn steering.

    One app-server process owns one resumable thread. `send()` starts a turn while idle
    and uses `turn/steer` while that turn is in flight, matching the native Codex TUI.
    """

    RUNTIME_LABEL = "Codex app-server"

    def __init__(self, model: str, cwd: str, system_prompt: str = "",
                 resume_thread_id: str | None = None,
                 mcp_env: dict[str, str] | None = None,
                 mcp_servers: dict | None = None,
                 reasoning_effort: str = "high",
                 is_orchestrator: bool = False):
        self.model = model
        self.cwd = cwd
        self.system_prompt = system_prompt
        self._thread_id: str | None = resume_thread_id
        self._mcp_env: dict[str, str] = mcp_env or {}
        self._mcp_servers: dict = mcp_servers or {}
        self._is_orchestrator = is_orchestrator
        self.reasoning_effort = (
            reasoning_effort if reasoning_effort in CODEX_REASONING_EFFORTS else "high"
        )
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._reader_task: Optional[asyncio.Task] = None
        self._stderr_task: Optional[asyncio.Task] = None
        self._notifications: asyncio.Queue[dict] = asyncio.Queue()
        self._pending_requests: dict[int, asyncio.Future] = {}
        self._request_seq = 0
        self._write_lock = asyncio.Lock()
        self._active_turn_id: str | None = None
        self._events_active = False
        self._disconnecting = False
        self._last_stderr = ""
        self._last_turn_error: dict = {}
        self._started_items: set[str] = set()
        self._subagent_descriptions: dict[str, str] = {}
        self._rollout_path: Path | None = None
        self._usage_baseline: dict[str, int] | None = None
        self._thread_usage_total: dict[str, int] | None = None
        self._last_call_usage: dict[str, int] | None = None
        self._model_context_window = CODEX_CONTEXT_LIMITS.get(model, 258400)
        self._compact_future: asyncio.Future | None = None
        self._compact_notifications: asyncio.Queue[dict] | None = None
        self._compact_context_tokens: int | None = None
        self._scope_unit: str | None = None
        self._scope_env: dict[str, str] = {}
        self._hibernate_safe = False
        self._scope_reason = "scope preflight has not run"
        self._teardown_error: str | None = None

    @property
    def session_id(self) -> Optional[str]:
        return self._thread_id

    @property
    def hibernate_safe(self) -> bool:
        return self._hibernate_safe

    @property
    def hibernate_unavailable_reason(self) -> str:
        return self._scope_reason

    @property
    def has_owned_processes(self) -> bool:
        return self._proc is not None or self._scope_unit is not None

    async def connect(self) -> None:
        if self.is_alive and not self._teardown_error:
            return

        if self.has_owned_processes:
            await self.disconnect()
        self._notifications = asyncio.Queue()
        self._disconnecting = False
        self._last_stderr = ""
        codex_cmd = [CODEX_BIN]
        codex_cmd += ["-c", f"model_reasoning_effort={self._toml_str(self.reasoning_effort)}"]
        if self._is_orchestrator:
            # Match Claude: an Orchestra orchestrator delegates through tracked
            # worktree workers, not invisible native subagents in its own checkout.
            codex_cmd += ["-c", "features.multi_agent=false"]
        # Managed workers are research/implementation agents, so expose current web
        # results explicitly instead of inheriting a user's cached/disabled setting.
        codex_cmd += ["-c", 'web_search="live"']
        for arg in self._mcp_config_args():
            codex_cmd += ["-c", arg]
        codex_cmd += ["app-server", "--stdio"]

        scope_ok, scope_env, scope_reason = await _codex_scope_support()
        env = self._build_env()
        self._hibernate_safe = scope_ok
        self._scope_reason = scope_reason
        if scope_ok:
            self._scope_unit = _scope_unit()
            self._scope_env = scope_env
            env.update({
                key: scope_env[key]
                for key in ("XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS")
            })
            cmd = [
                shutil.which("systemd-run") or "systemd-run",
                "--user", "--scope", "--quiet", "--collect",
                f"--unit={self._scope_unit}", "--", *codex_cmd,
            ]
        else:
            self._scope_unit = None
            self._scope_env = {}
            cmd = codex_cmd

        try:
            self._proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                cwd=self.cwd,
                limit=16 * 1024 * 1024,
            )
            self._reader_task = asyncio.create_task(self._read_stdout())
            self._stderr_task = asyncio.create_task(self._drain_stderr())
            await self._request("initialize", {
                "clientInfo": {
                    "name": "orchestra",
                    "title": "Orchestra",
                    "version": "1",
                },
            })
            await self._notify("initialized", {})
            params = {
                "cwd": self.cwd,
                "model": self.model,
                "approvalPolicy": "never",
                "sandbox": "danger-full-access",
            }
            if self.system_prompt:
                params["developerInstructions"] = self.system_prompt
            requested_thread_id = self._thread_id
            if requested_thread_id:
                params["threadId"] = requested_thread_id
                result = await self._request("thread/resume", params)
            else:
                result = await self._request("thread/start", params)
            thread_id = ((result.get("thread") or {}).get("id"))
            if not thread_id:
                raise RuntimeError("Codex app-server returned no thread id")
            if requested_thread_id and thread_id != requested_thread_id:
                raise RuntimeError(
                    "Codex app-server resumed a different thread: "
                    f"requested={requested_thread_id}, returned={thread_id}"
                )
            self._thread_id = thread_id
            self._rollout_path = None
            self._teardown_error = None
        except BaseException:
            await self.disconnect()
            raise

    async def send(self, message: str) -> None:
        if self._teardown_error or not self.is_alive:
            await self.connect()
        if not self._thread_id:
            raise RuntimeError("Codex thread is not initialized")

        user_input = [{"type": "text", "text": message}]
        if self._active_turn_id:
            await self._request("turn/steer", {
                "threadId": self._thread_id,
                "expectedTurnId": self._active_turn_id,
                "input": user_input,
            })
            return
        if self._events_active:
            # The server completed the old turn but session.py has not left its event
            # iterator yet. Queue at the session layer so the new turn gets a listener.
            raise RuntimeError("Codex turn is settling; queue this message")

        self._last_turn_error = {}
        self._last_call_usage = None
        self._started_items.clear()
        self._usage_baseline = (
            dict(self._thread_usage_total)
            if self._thread_usage_total is not None
            else (self._runtime_totals() if self._thread_id else None)
        )
        result = await self._request("turn/start", {
            "threadId": self._thread_id,
            "input": user_input,
            "model": self.model,
            "effort": self.reasoning_effort,
        })
        turn_id = ((result.get("turn") or {}).get("id"))
        if not turn_id:
            raise RuntimeError("Codex app-server returned no turn id")
        self._active_turn_id = turn_id

    async def events(self) -> AsyncIterator[AgentEvent]:
        if not self.is_alive:
            return
        expected_turn_id = self._active_turn_id
        self._events_active = True
        try:
            while True:
                try:
                    message = await asyncio.wait_for(
                        self._notifications.get(),
                        timeout=CODEX_SILENCE_HEARTBEAT_SECONDS,
                    )
                except asyncio.TimeoutError:
                    if not self._active_turn_id:
                        return
                    yield AgentEvent(
                        "thinking_stream",
                        "Still working · no new events for 30s. Steered messages wait for the next model checkpoint.",
                        {"activity": "waiting", "item_id": self._active_turn_id},
                    )
                    continue
                method = message.get("method", "")
                params = message.get("params") or {}
                thread_id = params.get("threadId")
                if thread_id and self._thread_id and thread_id != self._thread_id:
                    continue
                if not self._lifecycle_belongs_to_turn(message, expected_turn_id):
                    continue
                for event in self._convert_notification(message):
                    yield event
                if method in ("turn/completed", "_process/exited"):
                    return
        finally:
            self._events_active = False

    @staticmethod
    def _lifecycle_belongs_to_turn(message: dict, expected_turn_id: str | None) -> bool:
        method = message.get("method", "")
        if method not in ("turn/started", "turn/completed"):
            return True
        received_turn_id = str(
            (((message.get("params") or {}).get("turn") or {}).get("id")) or ""
        )
        if received_turn_id == expected_turn_id:
            return True
        logger.debug(
            "Codex ignored lifecycle event for another turn: "
            "method=%s received_turn_id=%s expected_turn_id=%s",
            method,
            received_turn_id,
            expected_turn_id,
        )
        return False

    async def interrupt(self) -> bool:
        if not self._active_turn_id or not self._thread_id or not self.is_alive:
            return False
        try:
            await asyncio.wait_for(self._request("turn/interrupt", {
                "threadId": self._thread_id,
                "turnId": self._active_turn_id,
            }), timeout=5)
            return True
        except Exception as exc:
            logger.warning("Codex turn interrupt failed: %s", exc)
            return False

    async def compact_context(self) -> dict:
        """Compact the current Codex thread without replacing its thread id."""
        if not self.is_alive:
            raise RuntimeError("Codex app-server is not running")
        if not self._thread_id:
            raise RuntimeError("Codex thread is not initialized")
        if self._active_turn_id:
            raise RuntimeError("cannot compact Codex context during an active turn")
        if self._compact_future and not self._compact_future.done():
            raise RuntimeError("Codex context compact already in progress")

        future = asyncio.get_running_loop().create_future()
        compact_notifications: asyncio.Queue[dict] = asyncio.Queue()
        self._compact_future = future
        self._compact_notifications = compact_notifications
        self._compact_context_tokens = None
        try:
            async with asyncio.timeout(CODEX_COMPACT_TIMEOUT_SECONDS):
                await self._request(
                    "thread/compact/start",
                    {"threadId": self._thread_id},
                )
                result = await future
                await self._drain_compact_lifecycle(compact_notifications)
                # The usage notification normally precedes contextCompaction completion,
                # but yield once for app-server versions that emit it immediately after.
                await asyncio.sleep(0)
            context_tokens = self._compact_context_tokens
            if context_tokens is None:
                runtime_context = self._runtime_context()
                if runtime_context:
                    context_tokens = int(runtime_context.get("input_tokens") or 0)
                    runtime_window = runtime_context.get("model_context_window")
                    if isinstance(runtime_window, int) and runtime_window > 0:
                        self._model_context_window = runtime_window
            result["context_tokens"] = context_tokens
            result["max_tokens"] = self._model_context_window
            return result
        finally:
            if self._compact_future is future:
                self._compact_future = None
            if self._compact_notifications is compact_notifications:
                self._compact_notifications = None
            if not future.done():
                future.cancel()
            elif not future.cancelled():
                future.exception()

    async def _drain_compact_lifecycle(
        self,
        notifications: asyncio.Queue[dict],
    ) -> None:
        compact_turn_id: str | None = None
        while True:
            message = await notifications.get()
            method = message.get("method", "")
            turn_id = str(
                (((message.get("params") or {}).get("turn") or {}).get("id")) or ""
            )
            if method == "turn/started":
                compact_turn_id = turn_id
            elif method == "turn/completed":
                if compact_turn_id is None:
                    raise RuntimeError(
                        "Codex compact completed without a preceding turn/started"
                    )
                if self._lifecycle_belongs_to_turn(message, compact_turn_id):
                    return

    async def _scope_populated(self) -> bool:
        unit = self._scope_unit
        if not unit:
            return False
        systemctl = shutil.which("systemctl") or "systemctl"
        rc, stdout, stderr = await _run_process(
            systemctl, "--user", "show", unit,
            "-p", "LoadState", "-p", "ActiveState", "-p", "ControlGroup",
            "--no-pager",
            env=self._scope_env,
        )
        if rc:
            raise RuntimeError(stderr or f"systemctl show exited with code {rc}")
        state = {}
        for line in stdout.splitlines():
            key, separator, value = line.partition("=")
            if separator:
                state[key] = value
        if state.get("LoadState") == "not-found":
            return False
        control_group = state.get("ControlGroup", "")
        if control_group:
            events_path = Path("/sys/fs/cgroup") / control_group.lstrip("/") / "cgroup.events"
            try:
                events = dict(
                    line.split(maxsplit=1)
                    for line in events_path.read_text().splitlines()
                    if " " in line
                )
            except OSError as exc:
                raise RuntimeError(
                    f"cannot verify Codex scope {unit}: {type(exc).__name__}: {exc}"
                ) from exc
            if "populated" in events:
                return events["populated"] == "1"
        return state.get("ActiveState") not in ("inactive", "failed", "")

    async def _signal_scope(self, signal_name: str) -> None:
        if not await self._scope_populated():
            return
        systemctl = shutil.which("systemctl") or "systemctl"
        rc, _, stderr = await _run_process(
            systemctl, "--user", "kill", f"--signal={signal_name}",
            "--kill-whom=all", self._scope_unit or "",
            env=self._scope_env,
        )
        if rc and await self._scope_populated():
            raise RuntimeError(
                stderr or f"systemctl kill {signal_name} exited with code {rc}"
            )

    async def _wait_scope_empty(self) -> None:
        async with asyncio.timeout(CODEX_PROCESS_TIMEOUT_SECONDS):
            while await self._scope_populated():
                await asyncio.sleep(0.05)

    async def _wait_owned_process(self, proc: asyncio.subprocess.Process) -> None:
        if proc.returncode is not None:
            return
        await asyncio.wait_for(
            asyncio.shield(proc.wait()),
            timeout=CODEX_PROCESS_TIMEOUT_SECONDS,
        )

    async def _disconnect_scoped(self, proc: asyncio.subprocess.Process | None) -> None:
        await self._signal_scope("TERM")
        try:
            if proc:
                await self._wait_owned_process(proc)
            await self._wait_scope_empty()
        except TimeoutError:
            await self._signal_scope("KILL")
            if proc:
                await self._wait_owned_process(proc)
            await self._wait_scope_empty()

    async def _disconnect_direct(self, proc: asyncio.subprocess.Process) -> None:
        if proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(
                    asyncio.shield(proc.wait()),
                    timeout=CODEX_PROCESS_TIMEOUT_SECONDS,
                )
            except TimeoutError:
                proc.kill()
                await proc.wait()

    async def _finalize_disconnect(self) -> None:
        for task in (self._reader_task, self._stderr_task):
            if task and not task.done():
                task.cancel()
        for future in self._pending_requests.values():
            if not future.done():
                future.set_exception(RuntimeError("Codex app-server disconnected"))
        self._pending_requests.clear()
        if self._compact_future and not self._compact_future.done():
            self._compact_future.set_exception(
                RuntimeError("Codex app-server disconnected during context compact")
            )
        self._proc = None
        self._scope_unit = None
        self._reader_task = None
        self._stderr_task = None
        self._active_turn_id = None
        self._teardown_error = None

    async def disconnect(self) -> None:
        proc = self._proc
        if proc is None and self._scope_unit is None:
            return
        self._disconnecting = True
        try:
            if self._active_turn_id and proc and proc.returncode is None:
                await self.interrupt()
            if self._scope_unit:
                await self._disconnect_scoped(proc)
            elif proc:
                await self._disconnect_direct(proc)
            await self._finalize_disconnect()
        except BaseException as exc:
            self._teardown_error = f"{type(exc).__name__}: {exc}"
            raise

    async def _read_stdout(self) -> None:
        proc = self._proc
        if not proc or not proc.stdout:
            return
        try:
            while True:
                raw = await proc.stdout.readline()
                if not raw:
                    break
                try:
                    message = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    logger.warning("Codex app-server emitted invalid JSONL")
                    continue
                request_id = message.get("id")
                if request_id is not None and message.get("method"):
                    # Autonomous workers have no interactive approval/elicitation UI.
                    # `approvalPolicy=never` should prevent these requests; reject any
                    # unexpected one explicitly so the turn fails instead of deadlocking.
                    await self._write({
                        "id": request_id,
                        "error": {
                            "code": -32601,
                            "message": (
                                f"Orchestra does not implement client request "
                                f"{message.get('method')}"
                            ),
                        },
                    })
                    continue
                if request_id is not None:
                    future = self._pending_requests.get(request_id)
                    if future and not future.done():
                        if "error" in message:
                            future.set_exception(
                                CodexProtocolError("request", message.get("error") or {})
                            )
                        else:
                            future.set_result(message.get("result") or {})
                    continue
                if message.get("method"):
                    if message["method"] == "thread/tokenUsage/updated":
                        self._record_token_usage(message.get("params") or {})
                    self._complete_compaction_from_notification(message)
                    notifications = self._compact_notifications
                    if notifications is None:
                        notifications = self._notifications
                    await notifications.put(message)
        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.exception("Codex app-server reader failed: %s", exc)
        finally:
            returncode = await proc.wait()
            error = RuntimeError(f"Codex app-server exited with code {returncode}")
            for future in self._pending_requests.values():
                if not future.done():
                    future.set_exception(error)
            if self._compact_future and not self._compact_future.done():
                self._compact_future.set_exception(error)
            if not self._disconnecting:
                await self._notifications.put({
                    "method": "_process/exited",
                    "params": {
                        "returncode": returncode,
                        "stderr": self._last_stderr,
                    },
                })

    def _record_token_usage(self, params: dict) -> None:
        usage = params.get("tokenUsage") or {}
        total = usage.get("total") or {}
        last = usage.get("last") or {}
        self._thread_usage_total = self._usage_breakdown(total)
        self._last_call_usage = self._usage_breakdown(last)
        context_tokens = last.get("totalTokens")
        if isinstance(context_tokens, int) and context_tokens >= 0:
            self._compact_context_tokens = context_tokens
        window = usage.get("modelContextWindow")
        if isinstance(window, int) and window > 0:
            self._model_context_window = window

    def _complete_compaction_from_notification(self, message: dict) -> bool:
        method = message.get("method", "")
        params = message.get("params") or {}
        thread_id = params.get("threadId")
        if thread_id and thread_id != self._thread_id:
            return False

        item = params.get("item") or {}
        completed = (
            method in ("context/compacted", "thread/compacted")
            or (
                method == "item/completed"
                and item.get("type") == "contextCompaction"
            )
        )
        if not completed:
            return False

        future = self._compact_future
        if future and not future.done():
            future.set_result({
                "ok": True,
                "thread_id": self._thread_id,
                "context_tokens": self._compact_context_tokens,
                "max_tokens": self._model_context_window,
            })
        return True

    def _convert_notification(self, message: dict) -> list[AgentEvent]:
        method = message.get("method", "")
        params = message.get("params") or {}

        if method == "thread/started":
            thread_id = ((params.get("thread") or {}).get("id") or params.get("threadId"))
            if not thread_id:
                return []
            self._thread_id = thread_id
            self._rollout_path = None
            return [AgentEvent(
                "status",
                f"codex thread={thread_id}",
                metadata={"session_id": thread_id},
            )]

        if method == "turn/started":
            turn_id = ((params.get("turn") or {}).get("id"))
            if turn_id:
                self._active_turn_id = turn_id
            return [AgentEvent("status", f"codex turn={turn_id} started")]

        if method == "thread/tokenUsage/updated":
            self._record_token_usage(params)
            return []

        if method == "error":
            error = params.get("error") or {}
            self._last_turn_error = error
            content = error.get("message") or "Codex error"
            if params.get("willRetry"):
                return [AgentEvent("status", f"codex reconnecting: {content}")]
            model_error = self._classify_error(error)
            if model_error == "rate_limit":
                content = f"rate_limit: {content}"
            return [AgentEvent("error", content, metadata={"model_error": model_error})]

        if method == "model/rerouted":
            return [AgentEvent("status", f"model rerouted: {json.dumps(params, ensure_ascii=False)}")]

        if method in ("context/compacted", "thread/compacted"):
            return [AgentEvent("status", "codex context compacted")]

        if method in (
            "item/reasoning/summaryTextDelta",
            "item/reasoning/textDelta",
            "item/plan/delta",
        ):
            activity = "plan" if method == "item/plan/delta" else "reasoning"
            return [AgentEvent(
                "thinking_stream",
                params.get("delta", ""),
                metadata={
                    "activity": activity,
                    "item_id": params.get("itemId", ""),
                },
            )]

        if method == "turn/plan/updated":
            return [AgentEvent("plan", json.dumps({
                "explanation": params.get("explanation"),
                "plan": params.get("plan") or [],
            }, ensure_ascii=False))]

        if method == "turn/diff/updated":
            return [AgentEvent(
                "turn_diff",
                params.get("diff", ""),
                metadata={"turn_id": params.get("turnId", "")},
            )]

        if method in (
            "item/commandExecution/outputDelta",
            "item/fileChange/outputDelta",
        ):
            return [AgentEvent(
                "tool_stream",
                params.get("delta", ""),
                metadata={"tool_use_id": params.get("itemId", "")},
            )]

        if method == "item/commandExecution/terminalInteraction":
            return [AgentEvent(
                "tool_stream",
                params.get("stdin", ""),
                metadata={
                    "tool_use_id": params.get("itemId", ""),
                    "stream": "stdin",
                },
            )]

        if method == "item/fileChange/patchUpdated":
            return [AgentEvent(
                "tool_patch",
                json.dumps({"changes": params.get("changes") or []}, ensure_ascii=False),
                metadata={"tool_use_id": params.get("itemId", "")},
            )]

        if method == "item/started":
            item = params.get("item") or {}
            item_id = str(item.get("id") or "")
            if item_id:
                self._started_items.add(item_id)
            return self._item_started(item)

        if method == "item/completed":
            return self._item_completed(params.get("item") or {})

        if method == "item/mcpToolCall/progress":
            return [AgentEvent(
                "tool_stream",
                params.get("message", ""),
                metadata={"tool_use_id": params.get("itemId", "")},
            )]

        if method == "item/agentMessage/delta":
            return [AgentEvent("stream", params.get("delta", ""))]

        if method in ("warning", "guardianWarning", "deprecationNotice", "configWarning"):
            content = (
                params.get("message")
                or params.get("summary")
                or "Codex warning"
            )
            details = params.get("details")
            if details:
                content = f"{content}\n{details}"
            return [AgentEvent("warning", content)]

        if method == "mcpServer/startupStatus/updated":
            name = params.get("name") or "unknown"
            status = params.get("status") or "unknown"
            if status in ("starting", "ready"):
                return []
            detail = params.get("error") or params.get("failureReason") or ""
            content = f"codex mcp {name}: {status}"
            if detail:
                content = f"{content} — {detail}"
            event_type = "warning" if status in ("failed", "cancelled") else "status"
            return [AgentEvent(event_type, content)]

        if method in ("hook/started", "hook/completed"):
            run = params.get("run") or {}
            phase = "started" if method.endswith("/started") else "completed"
            label = run.get("eventName") or run.get("id") or "hook"
            status = run.get("status") or phase
            duration = run.get("durationMs")
            suffix = f" · {duration}ms" if duration is not None else ""
            return [AgentEvent("status", f"codex hook {label}: {status}{suffix}")]

        if method in ("item/autoApprovalReview/started", "item/autoApprovalReview/completed"):
            phase = "started" if method.endswith("/started") else "completed"
            return [AgentEvent("status", f"codex approval review {phase}")]

        if method == "model/safetyBuffering/updated" and params.get("showBufferingUi"):
            reasons = ", ".join(params.get("reasons") or [])
            return [AgentEvent("warning", f"Codex safety buffering: {reasons or params.get('model', '')}")]

        if method == "turn/completed":
            turn = params.get("turn") or {}
            self._active_turn_id = None
            return self._turn_completed(turn)

        if method == "_process/exited":
            self._active_turn_id = None
            normalized_usage = TurnUsage(
                AggregateUsage.normalized(),
                current_context(
                    None,
                    self._model_context_window,
                    unknown_reason="Codex exited before reporting current context",
                ),
            )
            return [AgentEvent("turn_end", "stop_reason=process_exit", metadata={
                "session_id": self._thread_id,
                "ok": False,
                "stop_reason": f"process_exit_{params.get('returncode')}",
                "returncode": params.get("returncode"),
                "stderr_tail": params.get("stderr", ""),
                "model_error": "server_error",
                "errors": ["server_error"],
                "cost_usd": 0,
                **normalized_usage.metadata(),
            }, usage=normalized_usage)]

        return []

    def _item_started(self, item: dict) -> list[AgentEvent]:
        item_type = item.get("type", "")
        item_id = str(item.get("id") or "")
        if item_type == "commandExecution":
            payload = {
                "command": item.get("command", ""),
                "cwd": item.get("cwd", self.cwd),
                "command_actions": item.get("commandActions") or [],
            }
            return [self._tool_use(
                "Bash",
                json.dumps(payload, ensure_ascii=False),
                item_id,
            )]
        if item_type == "fileChange":
            payload = {
                "changes": item.get("changes") or [],
                "status": item.get("status", ""),
            }
            return [self._tool_use(
                "FileChange",
                json.dumps(payload, ensure_ascii=False),
                item_id,
            )]
        if item_type == "mcpToolCall":
            server, tool = item.get("server", ""), item.get("tool", "")
            name = f"mcp__{server}__{tool}" if server else tool
            return [self._tool_use(
                name,
                _tool_arguments_json(item.get("arguments")),
                item_id,
                short_name=tool,
            )]
        if item_type == "dynamicToolCall":
            return [self._tool_use(
                item.get("tool", "tool"),
                _tool_arguments_json(item.get("arguments")),
                item_id,
            )]
        if item_type == "webSearch":
            return [self._tool_use(
                "WebSearch",
                json.dumps({
                    "query": item.get("query", ""),
                    "action": item.get("action"),
                }, ensure_ascii=False),
                item_id,
            )]
        if item_type == "imageView":
            return [self._tool_use(
                "ViewImage",
                json.dumps({"file_path": item.get("path", "")}, ensure_ascii=False),
                item_id,
            )]
        if item_type == "imageGeneration":
            return [self._tool_use(
                "ImageGeneration",
                json.dumps({"status": item.get("status", "")}, ensure_ascii=False),
                item_id,
            )]
        if item_type == "sleep":
            return [self._tool_use(
                "Sleep",
                json.dumps({"duration_ms": item.get("durationMs", 0)}),
                item_id,
            )]
        if item_type == "collabAgentToolCall":
            return self._collab_events(item, completed=False)
        if item_type == "contextCompaction":
            return [AgentEvent("status", "codex compacting context")]
        return []

    def _item_completed(self, item: dict) -> list[AgentEvent]:
        item_type = item.get("type", "")
        item_id = str(item.get("id") or "")
        unseen = bool(item_id and item_id not in self._started_items)
        events: list[AgentEvent] = []

        if item_type == "agentMessage":
            text = item.get("text", "")
            if text:
                events.append(AgentEvent("text", text))
        elif item_type == "reasoning":
            parts = item.get("summary") or item.get("content") or []
            text = "\n".join(str(part) for part in parts if part)
            if text:
                events.append(AgentEvent("thinking", text))
        elif item_type == "plan":
            if item.get("text"):
                events.append(AgentEvent("thinking", item["text"]))
        elif item_type == "commandExecution":
            if unseen:
                events.extend(self._item_started(item))
            output = item.get("aggregatedOutput")
            exit_code = item.get("exitCode")
            failed = exit_code is not None and exit_code != 0
            if output is not None or failed:
                events.append(AgentEvent(
                    "tool_result",
                    str(output) if output is not None else f"command exited with code {exit_code}",
                    metadata={
                        "exit_code": exit_code,
                        "tool_use_id": item_id,
                        "tool_name": "Bash",
                        "is_error": failed,
                    },
                ))
        elif item_type == "fileChange":
            if unseen:
                events.extend(self._item_started(item))
            events.append(AgentEvent(
                "tool_result",
                json.dumps({
                    "status": item.get("status", ""),
                    "files": len(item.get("changes") or []),
                }, ensure_ascii=False),
                metadata={"tool_use_id": item_id},
            ))
        elif item_type == "mcpToolCall":
            server, tool = item.get("server", ""), item.get("tool", "")
            name = f"mcp__{server}__{tool}" if server else tool
            if unseen:
                events.append(self._tool_use(
                    name,
                    _tool_arguments_json(item.get("arguments")),
                    item_id,
                    short_name=tool,
                ))
            if item.get("result") is not None:
                events.append(AgentEvent(
                    "tool_result",
                    self._result_text(item["result"]),
                    metadata={
                        "tool_use_id": item_id,
                        "tool_name": name,
                        "is_error": False,
                    },
                ))
            if item.get("error"):
                error = item["error"]
                error_text = (
                    error.get("message", str(error))
                    if isinstance(error, dict)
                    else str(error)
                )
                events.append(AgentEvent(
                    "tool_result",
                    error_text,
                    metadata={
                        "tool_use_id": item_id,
                        "tool_name": name,
                        "is_error": True,
                    },
                ))
                events.append(AgentEvent(
                    "error",
                    error_text,
                ))
        elif item_type == "dynamicToolCall":
            if unseen:
                events.extend(self._item_started(item))
            content = item.get("contentItems")
            failed = item.get("success") is False or item.get("status") == "failed"
            if content is not None or failed:
                events.append(AgentEvent(
                    "tool_result",
                    self._result_text(content) if content is not None else json.dumps({
                        "status": item.get("status"),
                        "success": item.get("success"),
                    }),
                    metadata={
                        "tool_use_id": item_id,
                        "tool_name": item.get("tool", "tool"),
                        "is_error": failed,
                    },
                ))
        elif item_type == "webSearch":
            if unseen:
                events.extend(self._item_started(item))
            events.append(AgentEvent(
                "tool_result",
                json.dumps({
                    "query": item.get("query", ""),
                    "action": item.get("action"),
                    "status": "completed",
                }, ensure_ascii=False),
                metadata={"tool_use_id": item_id},
            ))
        elif item_type == "imageView":
            if unseen:
                events.extend(self._item_started(item))
            events.append(AgentEvent(
                "tool_result",
                json.dumps({
                    "status": "viewed",
                    "file_path": item.get("path", ""),
                }, ensure_ascii=False),
                metadata={"tool_use_id": item_id},
            ))
        elif item_type == "imageGeneration":
            if unseen:
                events.extend(self._item_started(item))
            events.append(AgentEvent(
                "tool_result",
                json.dumps({
                    "result": item.get("result"),
                    "saved_path": item.get("savedPath"),
                    "status": item.get("status", ""),
                    "revised_prompt": item.get("revisedPrompt"),
                }, ensure_ascii=False),
                metadata={"tool_use_id": item_id},
            ))
        elif item_type == "sleep":
            if unseen:
                events.extend(self._item_started(item))
            events.append(AgentEvent(
                "tool_result",
                json.dumps({"status": "completed", "duration_ms": item.get("durationMs", 0)}),
                metadata={"tool_use_id": item_id},
            ))
        elif item_type == "collabAgentToolCall":
            events.extend(self._collab_events(item, completed=True))
        elif item_type == "subAgentActivity":
            sub_id = item.get("agentThreadId", "")
            kind = item.get("kind", "activity")
            agent_path = item.get("agentPath", "")
            events.append(AgentEvent(
                "subagent_progress",
                f"{agent_path} | type=codex | id={sub_id} | tool={kind}",
                metadata={"subagent_id": sub_id, "status": kind, "phase": "progress"},
            ))
        elif item_type == "contextCompaction":
            events.append(AgentEvent("status", "codex context compacted"))
        elif item_type in ("enteredReviewMode", "exitedReviewMode"):
            phase = "entered" if item_type == "enteredReviewMode" else "exited"
            events.append(AgentEvent("review", json.dumps({
                "phase": phase,
                "review": item.get("review", ""),
            }, ensure_ascii=False)))

        if item_id:
            self._started_items.discard(item_id)
        return events

    def _collab_events(self, item: dict, *, completed: bool) -> list[AgentEvent]:
        tool = item.get("tool", "")
        receiver_ids = item.get("receiverThreadIds") or [item.get("id", "")]
        agent_states = item.get("agentsStates") or {}
        events = []
        for sub_id in receiver_ids:
            prompt = item.get("prompt") or ""
            if tool == "spawnAgent" and prompt:
                self._subagent_descriptions[sub_id] = prompt
            description = prompt or self._subagent_descriptions.get(sub_id) or tool
            agent_state = agent_states.get(sub_id) or {}
            agent_status = agent_state.get("status", "")
            summary = agent_state.get("message") or ""
            metadata = {
                "subagent_id": sub_id,
                "tool_use_id": item.get("id", ""),
                "description": description,
                "task_type": "codex",
                "status": agent_status or item.get("status", ""),
                "summary": summary,
            }
            if tool == "spawnAgent" and not completed:
                metadata["phase"] = "start"
                content = (
                    f"{description} | type=codex | id={sub_id} | "
                    f"tool_use_id={item.get('id', '')}"
                )
                events.append(AgentEvent("subagent_start", content, metadata))
            elif completed and (
                tool == "closeAgent"
                or agent_status in {"interrupted", "completed", "errored", "shutdown", "notFound"}
            ):
                metadata["phase"] = "end"
                content = (
                    f"{description} | type=codex | id={sub_id} | "
                    f"tool_use_id={item.get('id', '')} | status={metadata['status']}"
                    f"{' | ' + summary[:500] if summary else ''}"
                )
                events.append(AgentEvent("subagent_end", content, metadata))
            else:
                metadata["phase"] = "progress"
                content = (
                    f"{description} | type=codex | id={sub_id} | "
                    f"tool_use_id={item.get('id', '')} | tool={tool}"
                )
                events.append(AgentEvent("subagent_progress", content, metadata))
        return events

    def _turn_completed(self, turn: dict) -> list[AgentEvent]:
        status = turn.get("status", "failed")
        error = turn.get("error") or self._last_turn_error or {}
        ok = status == "completed"
        model_error = "" if ok else self._classify_error(error)
        stop_reason = {
            "completed": "end_turn",
            "interrupted": "interrupted",
            "failed": "error",
        }.get(status, status)

        totals = self._thread_usage_total or self._runtime_totals() or {}
        delta = _usage_delta(totals, self._usage_baseline)
        turn_input = delta["input_tokens"]
        turn_cached = delta["cached_input_tokens"]
        turn_output = delta["output_tokens"]
        context = self._last_call_usage or self._runtime_context()
        if context:
            ctx_tokens = int(context.get("input_tokens") or 0)
            ctx_window = int(
                context.get("model_context_window") or self._model_context_window
            )
        else:
            ctx_tokens = None
            ctx_window = self._model_context_window
        normalized_usage = TurnUsage(
            AggregateUsage.normalized(
                input_tokens=turn_input,
                output_tokens=turn_output,
                cache_read_tokens=turn_cached,
            ),
            current_context(
                ctx_tokens,
                ctx_window,
                semantics_known=context is not None,
                unknown_reason="Codex did not report last-call context",
            ),
        )
        cost = _codex_cost(self.model, turn_input, turn_cached, turn_output)
        metadata = {
            "event_id": str(turn.get("id") or ""),
            "session_id": self._thread_id,
            "ok": ok,
            "stop_reason": stop_reason,
            "cost_usd": cost,
            "cost_usd_cached": cost,
            "cost_is_delta": True,
            "cache_hit": int(turn_cached * 100 / turn_input) if turn_input else 0,
            **normalized_usage.metadata(),
            "model_error": model_error,
            "errors": [model_error] if model_error else [],
        }
        events = []
        if not ok and error.get("message"):
            events.append(AgentEvent("error", error["message"], {"model_error": model_error}))
        events.append(AgentEvent(
            "turn_end",
            f"stop_reason={stop_reason}",
            metadata=metadata,
            usage=normalized_usage,
        ))
        self._last_turn_error = {}
        return events

    @staticmethod
    def _usage_breakdown(data: dict) -> dict[str, int]:
        return {
            "input_tokens": max(0, int(data.get("inputTokens") or 0)),
            "cached_input_tokens": max(0, int(data.get("cachedInputTokens") or 0)),
            "output_tokens": max(0, int(data.get("outputTokens") or 0)),
        }

    @staticmethod
    def _classify_error(error: dict) -> str:
        info = error.get("codexErrorInfo")
        if isinstance(info, dict) and any(key in info for key in (
            "httpConnectionFailed",
            "responseStreamConnectionFailed",
            "responseStreamDisconnected",
            "responseTooManyFailedAttempts",
        )):
            return "server_error"
        if info in ("serverOverloaded", "internalServerError"):
            return "server_error"
        if info in ("usageLimitExceeded", "sessionBudgetExceeded"):
            return "rate_limit"
        if info == "contextWindowExceeded":
            return "context_window"
        message = str(error.get("message") or "").lower()
        if any(part in message for part in (
            "connection refused", "stream disconnected", "network error",
            "tls", "unexpected eof", "error sending request",
        )):
            return "server_error"
        return "error"

    @staticmethod
    def _tool_use(name: str, summary: str, item_id: str,
                  short_name: str | None = None) -> AgentEvent:
        if item_id:
            try:
                payload = json.loads(summary)
            except (json.JSONDecodeError, TypeError):
                payload = None
            if isinstance(payload, dict):
                payload["_codex_item_id"] = item_id
                summary = json.dumps(payload, ensure_ascii=False)
        short = short_name or name
        return AgentEvent(
            "tool_use",
            f"{name}: {summary}",
            metadata={
                "tool_name": name,
                "short_name": short,
                "tool_use_id": item_id,
            },
        )

    @staticmethod
    def _result_text(result) -> str:
        if isinstance(result, dict):
            content = result.get("content")
            if isinstance(content, list):
                parts = []
                for block in content:
                    if isinstance(block, dict):
                        parts.append(str(block.get("text", block)))
                    else:
                        parts.append(str(block))
                return "\n".join(parts)[:20_000]
            return json.dumps(result, ensure_ascii=False)[:20_000]
        if isinstance(result, list):
            return "\n".join(
                block.get("text", str(block)) if isinstance(block, dict) else str(block)
                for block in result
            )[:20_000]
        return str(result)[:20_000]

    def _runtime_context(self) -> dict[str, int] | None:
        if not self._thread_id:
            return None
        if self._rollout_path is None or not self._rollout_path.exists():
            root = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser()
            sessions = root / "sessions"
            try:
                matches = list(sessions.glob(f"**/*{self._thread_id}.jsonl"))
            except OSError:
                matches = []
            if not matches:
                return None
            self._rollout_path = max(matches, key=lambda p: p.stat().st_mtime)
        return _read_rollout_context(self._rollout_path)

    def _runtime_totals(self) -> dict[str, int] | None:
        # Locate the rollout through the same path/cache as context extraction.
        self._runtime_context()
        if self._rollout_path is None:
            return None
        return _read_rollout_totals(self._rollout_path)

    @staticmethod
    def _toml_str(s: str) -> str:
        # TOML basic string: escape backslash and double-quote (control chars unlikely in
        # command/args/env values here). Keeps the -c inline table parseable.
        return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'

    def _mcp_config_args(self) -> list[str]:
        """Translate per-worker MCP into Codex dotted config overrides.

        Explicit `enabled=true` prevents a globally disabled/read-only native Orchestra
        entry from leaking into managed workers. The worker tool allowlist overrides the
        native read-only list while the MCP process also enforces its access mode.
        """
        args = []
        for name, cfg in self._mcp_servers.items():
            command = cfg.get("command")
            url = cfg.get("url")
            if not command and not url:
                continue
            args.append(f"mcp_servers.{name}.enabled=true")
            if command:
                args.append(f"mcp_servers.{name}.command={self._toml_str(str(command))}")
                srv_args = cfg.get("args") or []
                args.append(f"mcp_servers.{name}.args=[" +
                            ", ".join(self._toml_str(str(a)) for a in srv_args) + "]")
                env = cfg.get("env") or {}
                if env:
                    env_inline = ", ".join(
                        f"{k}={self._toml_str(str(v))}" for k, v in env.items()
                    )
                    args.append(f"mcp_servers.{name}.env={{" + env_inline + "}")
            else:
                args.append(f"mcp_servers.{name}.url={self._toml_str(str(url))}")
            enabled_tools = cfg.get("enabled_tools")
            if name == "orchestra" and enabled_tools is None:
                enabled_tools = ORCHESTRA_FULL_MCP_TOOLS
            if enabled_tools is not None:
                args.append(
                    f"mcp_servers.{name}.enabled_tools=["
                    + ", ".join(self._toml_str(str(tool)) for tool in enabled_tools)
                    + "]"
                )
        return args

    def _build_env(self) -> dict:
        env = dict(os.environ)
        env.update(self._mcp_env)
        # Codex, Claude, Cursor, and Orchestra intentionally share the proxy selected in
        # Orchestra's .env. The launcher wrapper also reloads that file, but preserving the
        # inherited values keeps direct CODEX_BIN deployments consistent and testable.
        return env
