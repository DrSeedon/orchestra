"""AgentSession — backend-agnostic wrapper with persistent event loop."""

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from app.events import AgentEvent
from app.prompting import is_orchestrator_role

if TYPE_CHECKING:
    from app.backend_protocol import BackendLike
from app.db import save_session, add_log

logger = logging.getLogger(__name__)

import concurrent.futures
_DB_EXECUTOR: Optional[concurrent.futures.ThreadPoolExecutor] = None


def _db_executor() -> concurrent.futures.ThreadPoolExecutor:
    """Dedicated pool for DB writes so logs/persists don't contend with git ops
    on the default executor (used by asyncio.to_thread)."""
    global _DB_EXECUTOR
    if _DB_EXECUTOR is None:
        _DB_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="db")
    return _DB_EXECUTOR


IDLE_TIMEOUT_WORKER = 300
IDLE_TIMEOUT_ORCHESTRATOR = 600



def _load_scope_mcp_servers(scope: str) -> dict:
    servers = {}
    for name in ("settings.json", "settings.local.json"):
        path = Path(scope) / ".claude" / name
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text())
            for k, v in data.get("mcpServers", {}).items():
                if k != "orchestra":
                    servers[k] = v
        except Exception as e:
            logger.warning(f"Failed to parse MCP servers from {path}: {e}")
    mcp_json = Path(scope) / ".mcp.json"
    if mcp_json.is_file():
        try:
            data = json.loads(mcp_json.read_text())
            for k, v in data.get("mcpServers", {}).items():
                if k != "orchestra":
                    servers[k] = v
        except Exception as e:
            logger.warning(f"Failed to parse .mcp.json from {mcp_json}: {e}")
    return servers


class AgentStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    WAITING = "waiting"


@dataclass
class AgentSession:
    id: str
    name: str
    scope: str
    cwd: str
    model: str = "claude-sonnet-4-6"
    system_prompt: str = ""
    status: AgentStatus = AgentStatus.IDLE
    session_id: str | None = None
    cost_usd: float = 0.0
    cost_usd_cached: float = 0.0
    worktree_path: str | None = None
    branch: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    role: str = "worker"
    parent_id: str = ""
    parent_name: str = ""
    color: str = ""
    mcp_servers: dict = field(default_factory=dict, repr=False)
    mcp_servers_custom: dict = field(default_factory=dict, repr=False)
    on_error: Optional[callable] = field(default=None, repr=False)
    backend_type: str = "claude"
    task_id: str = ""
    description: str = ""
    owned_dirs: list = field(default_factory=list, repr=False)
    tg_topic: bool = False

    progress_pct: int = 0
    progress_status: str = ""

    total_turns: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tool_calls: int = 0

    _backend: Optional["BackendLike"] = field(default=None, repr=False)
    _listen_task: Optional[asyncio.Task] = field(default=None, repr=False)
    _heartbeat_task: Optional[asyncio.Task] = field(default=None, repr=False)
    _background_tasks: set = field(default_factory=set, repr=False)
    _last_context: dict = field(default_factory=lambda: {"percentage": 0, "total_tokens": 0, "max_tokens": 0}, repr=False)
    _did_report: bool = field(default=False, repr=False)
    _turn_logs: list = field(default_factory=list, repr=False)
    _prompt_injected: bool = field(default=False, repr=False)
    _current_prompt: str = field(default="", repr=False)
    _template_hash: str = field(default="", repr=False)
    _turn_start: float = field(default=0.0, repr=False)
    _last_msg_time: float = field(default=0.0, repr=False)
    _pending_messages: list = field(default_factory=list, repr=False)
    on_idle: Optional[callable] = field(default=None, repr=False)
    _hibernate_task: Optional[asyncio.Task] = field(default=None, repr=False)
    _hibernated: bool = field(default=False, repr=False)
    _compacting: bool = field(default=False, repr=False)
    _compact_ack_event: Optional[asyncio.Event] = field(default=None, repr=False)
    _compact_ack_gen: int = field(default=-1, repr=False)
    _last_cost: float = field(default=0.0, repr=False)
    _last_cost_cached: float = field(default=0.0, repr=False)
    _last_turn_ok: bool = field(default=True, repr=False)
    _last_stop_reason: str = field(default="", repr=False)
    _lifecycle_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    _persist_task: Optional[asyncio.Task] = field(default=None, repr=False)
    _persist_dirty: bool = field(default=False, repr=False)
    _turn_gen: int = field(default=0, repr=False)
    _auto_report_task: Optional[asyncio.Task] = field(default=None, repr=False)
    _spawn_warning: str = field(default="", repr=False)

    TURN_TIMEOUT = 600

    @property
    def is_orchestrator(self) -> bool:
        return is_orchestrator_role(self.role)

    def _make_backend(self, force_fresh: bool = False):
        resume = None if force_fresh else self.session_id
        if self.backend_type == "codex":
            from app.backend_codex import CodexBackend
            return CodexBackend(
                model=self.model, cwd=self.cwd,
                system_prompt=self.system_prompt,
                resume_thread_id=resume,
                mcp_env=self._build_codex_mcp_env(),
                reasoning_effort=self._codex_reasoning_effort(),
            )
        else:
            from app.backend_claude import ClaudeBackend
            return ClaudeBackend(
                model=self.model, cwd=self.cwd,
                system_prompt=self.system_prompt,
                resume_session_id=resume,
                mcp_servers=self.mcp_servers,
                is_orchestrator=self.is_orchestrator,
                scope_mcp_servers=_load_scope_mcp_servers(self.scope),
            )

    def _codex_reasoning_effort(self) -> str:
        return "high"

    def _spawn_bg(self, coro) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self._background_tasks.add(task)
        def _on_done(t):
            self._background_tasks.discard(t)
            if not t.cancelled():
                exc = t.exception()
                if exc:
                    logger.warning(f"[{self.name}] background task failed: {exc}")
        task.add_done_callback(_on_done)
        return task

    def _build_codex_mcp_env(self) -> dict[str, str]:
        env = {}
        for _name, cfg in self.mcp_servers.items():
            for k, v in cfg.get("env", {}).items():
                env[k] = str(v)
        return env

    async def start(self, initial_message: str | None = None) -> None:
        if initial_message:
            await self.send(initial_message)
        else:
            self.status = AgentStatus.IDLE
            self._persist()

    async def send(self, message: str) -> None:
        if self._compacting:
            self._pending_messages.append(message)
            self._log("user_message", message)
            self._log("status", f"message queued (compact in progress, {len(self._pending_messages)} pending)")
            return

        if self.status == AgentStatus.RUNNING:
            if self.backend_type == "codex":
                self._pending_messages.append(message)
                self._log("user_message", message)
                self._log("status", f"message queued ({len(self._pending_messages)} pending)")
                return
            self._log("user_message", message)
            try:
                backend = await self._ensure_backend()
                await backend.send(message)
                return
            except Exception as e:
                logger.warning(f"[{self.name}] mid-turn inject failed, queueing: {e}")
                self._pending_messages.append(message)
                self._log("status", f"inject failed, queued ({len(self._pending_messages)} pending)")
                return

        async with self._lifecycle_lock:
            if self.status == AgentStatus.RUNNING:
                if self.backend_type != "codex":
                    self._log("user_message", message)
                    try:
                        backend = await self._ensure_backend()
                        await backend.send(message)
                        return
                    except Exception as e:
                        logger.warning(f"[{self.name}] mid-turn inject failed in lock, queueing: {e}")
                self._pending_messages.append(message)
                self._log("user_message", message)
                self._log("status", f"message queued (race, {len(self._pending_messages)} pending)")
                return

            if self._hibernate_task and not self._hibernate_task.done():
                self._hibernate_task.cancel()
                self._hibernate_task = None

            if self._hibernated:
                logger.info(f"[{self.name}] waking from hibernate")
                self._hibernated = False

            self.progress_pct = 0
            self.progress_status = ""
            self._log("user_message", message)

            did_inject = False
            pending_th = ""
            templates_changed = False
            if self.session_id and self._current_prompt and not self._prompt_injected:
                from app.prompting import prompt_template_hash
                current_th = prompt_template_hash(self.role)
                old_th = self._template_hash or current_th
                templates_changed = old_th != current_th
                pending_th = current_th
                message = f"[Orchestra platform note: {'your role instructions were updated.' if templates_changed else 'refreshed context (worker list, etc.).'} This is from the server, not another agent.]\n{self._current_prompt}\n\n---\n\n{message}"
                did_inject = True

            if self.status in (AgentStatus.IDLE, AgentStatus.WAITING):
                self._did_report = False
                self._bump_turn_gen()
                self._turn_logs = []
                self._turn_start = asyncio.get_event_loop().time()
                self._last_msg_time = self._turn_start
                self.status = AgentStatus.RUNNING
                self._persist()

            try:
                backend = await self._ensure_backend()
            except Exception:
                self.status = AgentStatus.IDLE
                self._persist()
                raise

            await backend.send(message)

            if did_inject:
                if templates_changed:
                    self._log("status", f"prompt updated → {pending_th}")
                self._template_hash = pending_th
                self._prompt_injected = True
                self.system_prompt = self._current_prompt

            if self.backend_type == "codex":
                self._listen_task = asyncio.create_task(self._codex_turn_loop())

    async def _ensure_backend(self, force_fresh: bool = False):
        if self._backend is not None:
            if not force_fresh:
                return self._backend
            await self._disconnect_backend()
        self._backend = self._make_backend(force_fresh=force_fresh)
        try:
            await self._backend.connect()
        except Exception as e:
            logger.error(f"[{self.name}] backend connect failed: {e}")
            self._log("error", f"connect failed: {e}")
            self._backend = None
            raise
        if self.backend_type != "codex":
            self._listen_task = asyncio.create_task(self._claude_event_loop())
            self._listen_task.add_done_callback(self._on_task_done)
        if self._heartbeat_task is None or self._heartbeat_task.done():
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        return self._backend

    # ── Event loops ──

    MAX_CONSECUTIVE_FAILURES = 5

    async def _claude_event_loop(self) -> None:
        logger.info(f"[{self.name}] claude event loop started")
        consecutive_failures = 0
        while True:
            try:
                if self._backend is None:
                    logger.warning(f"[{self.name}] event loop: backend is None, exiting")
                    return
                async for event in self._backend.events():
                    self._last_msg_time = asyncio.get_event_loop().time()
                    if self._turn_start and (asyncio.get_event_loop().time() - self._turn_start) > self.TURN_TIMEOUT:
                        logger.error(f"[{self.name}] turn timeout")
                        self._log("error", f"Turn timeout ({self.TURN_TIMEOUT}s)")
                        self._turn_start = 0
                        self.status = AgentStatus.IDLE
                        self._persist()
                        await self._backend.send("[system] Turn timed out. Continue where you left off.")
                        continue
                    self._handle_event(event)
                    consecutive_failures = 0
                # events() exhausted normally — treat as failure
                consecutive_failures += 1
                logger.warning(f"[{self.name}] events() exhausted normally (attempt {consecutive_failures}/{self.MAX_CONSECUTIVE_FAILURES})")
                self._log("error", f"listener stream ended unexpectedly (attempt {consecutive_failures})")
            except asyncio.CancelledError:
                logger.info(f"[{self.name}] claude event loop cancelled")
                return
            except Exception as e:
                consecutive_failures += 1
                import traceback
                tb = traceback.format_exc()
                logger.error(f"[{self.name}] claude event loop died: {e}\n{tb}")
                self._log("error", f"listener died (attempt {consecutive_failures}): {e}")

            if consecutive_failures >= self.MAX_CONSECUTIVE_FAILURES:
                logger.error(f"[{self.name}] reconnect limit reached ({consecutive_failures} consecutive failures), giving up")
                self._log("error", f"backend unstable: {consecutive_failures} consecutive failures, giving up")
                self._turn_start = 0
                await self._disconnect_backend()
                if self.status == AgentStatus.RUNNING:
                    self.status = AgentStatus.IDLE
                    self._persist()
                return

            try:
                if self._backend is None:
                    return
                await self._backend.reconnect()
                logger.info(f"[{self.name}] listener reconnected after error")
                self._log("status", "listener reconnected")
                if self.status == AgentStatus.RUNNING:
                    await self._backend.send("[system] Connection was restored after interruption. Continue your work.")
                continue
            except Exception as re_err:
                logger.error(f"[{self.name}] listener reconnect failed: {re_err}")
                self._log("error", f"listener reconnect failed: {re_err}")
                self._backend = None
                if self.status == AgentStatus.RUNNING:
                    self.status = AgentStatus.IDLE
                    self._persist()
                return

    CODEX_TURN_TIMEOUT = 600

    async def _codex_turn_loop(self) -> None:
        logger.info(f"[{self.name}] codex turn started")
        try:
            async with asyncio.timeout(self.CODEX_TURN_TIMEOUT):
                async for event in self._backend.events():
                    self._last_msg_time = asyncio.get_event_loop().time()
                    self._handle_event(event)
        except TimeoutError:
            logger.error(f"[{self.name}] codex turn timed out ({self.CODEX_TURN_TIMEOUT}s)")
            self._log("error", f"codex turn timed out ({self.CODEX_TURN_TIMEOUT}s), killing backend")
            await self._disconnect_backend()
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.error(f"[{self.name}] codex turn error: {e}")
            self._log("error", f"codex turn error: {e}")
        finally:
            if self.status == AgentStatus.RUNNING:
                self.status = AgentStatus.IDLE
                self._persist()
                if self._pending_messages:
                    self._spawn_bg(self._flush_pending())
                else:
                    self._schedule_hibernate()

    # ── Unified event handler ──

    def _handle_event(self, event: AgentEvent) -> None:
        if event.type == "text":
            self._log("text", event.content)
            self._turn_logs.append(event.content)
        elif event.type == "thinking":
            self._log("thinking", event.content)
        elif event.type == "tool_use":
            self.total_tool_calls += 1
            self._log("tool", event.content)
            short = event.content[:80]
            self._turn_logs.append(f"[tool] {short}")
            tool_name = event.metadata.get("tool_name", event.content)
            if "send_message" in tool_name or "mcp__orchestra__send_message" in tool_name:
                self._did_report = True
        elif event.type == "tool_result":
            self._log("tool_result", event.content)
        elif event.type == "file_change":
            self._log("tool", f"file: {event.content}")
            self._turn_logs.append(f"[tool] file: {event.content[:60]}")
        elif event.type == "turn_end":
            self._handle_turn_end(event)
        elif event.type == "error":
            self._log("error", event.content)
        elif event.type == "subagent_start":
            self._log("subagent_start", event.content)
        elif event.type == "subagent_progress":
            self._log("subagent_progress", event.content)
        elif event.type == "subagent_end":
            self._log("subagent_end", event.content)
        elif event.type == "status":
            self._log("status", event.content)

    def _cancel_auto_report(self) -> None:
        if self._auto_report_task and not self._auto_report_task.done():
            self._auto_report_task.cancel()
        self._auto_report_task = None

    def _bump_turn_gen(self) -> None:
        """Новый ход начался — инвалидируем отложенный авто-репорт прошлого хода."""
        self._turn_gen += 1
        self._cancel_auto_report()

    def _fire_auto_report(self) -> None:
        """Send auto-report to parent immediately when worker goes idle.
        Orchestrators don't auto-report — they reply to user directly.
        Skipped if worker already sent explicit send_message, has pending messages,
        or was interrupted/stopped by user.
        """
        if self.is_orchestrator or not self.on_idle or self._did_report:
            return
        if self._pending_messages or self._compacting:
            return
        if not self._last_turn_ok:
            return
        last_texts = self._turn_logs[-5:] if self._turn_logs else []
        stop_reason = self._last_stop_reason

        async def _do_report():
            try:
                await self.on_idle(self.name, self.scope, last_texts, stop_reason)
            except Exception as e:
                logger.error(f"Auto-report failed for {self.name}: {e}")

        self._auto_report_task = asyncio.create_task(_do_report())

    def _handle_turn_end(self, event: AgentEvent) -> None:
        meta = event.metadata
        self._turn_start = 0
        ok, sr, nt = self._apply_turn_result(meta)
        self._update_context_from_turn(meta)
        self._spawn_bg(self._refresh_context_from_api())

        if not ok:
            errors = meta.get("errors") or []
            err_txt = "; ".join(str(e) for e in errors) if errors else sr
            self._log("error", f"turn FAILED: {err_txt}")

        if sr in ("error_max_turns", "max_turns") and ok:
            self._log("status", f"max_turns reached ({nt}), auto-continuing")
            self._spawn_bg(self._auto_continue())
            return

        cost = meta.get("cost_usd", 0)
        live_pct = self._last_context.get("percentage", 0)
        ctx_s = f"ctx:{live_pct}%" if live_pct else ""
        self._log("status", f"turn ended ({sr}, {nt} turns, ${cost:.2f} {ctx_s})")

        self._finish_turn_status()
        self._after_turn_idle_actions(live_pct)

    def _apply_turn_result(self, meta: dict) -> tuple[bool, str, int]:
        """Update session_id, costs, token totals from turn metadata."""
        ok = meta.get("ok", True)
        sr = meta.get("stop_reason", "unknown")
        nt = meta.get("num_turns", 0)
        self._last_turn_ok = ok
        self._last_stop_reason = sr

        sid = meta.get("session_id")
        if sid and sid != self.session_id:
            self._last_cost = 0.0
            self._last_cost_cached = 0.0
        if sid:
            self.session_id = sid
        new_cost = meta.get("cost_usd", 0)
        self.cost_usd += max(0, new_cost - self._last_cost)
        self._last_cost = new_cost
        new_cost_cached = meta.get("cost_usd_cached", 0)
        self.cost_usd_cached += max(0, new_cost_cached - self._last_cost_cached)
        self._last_cost_cached = new_cost_cached
        self.total_turns += nt
        self.total_input_tokens += meta.get("input_tokens", 0)
        self.total_output_tokens += meta.get("output_tokens", 0)
        return ok, sr, nt

    def _update_context_from_turn(self, meta: dict) -> None:
        """Update context window stats from turn metadata."""
        ctx_pct = meta.get("context_pct", 0)
        ctx_tokens = meta.get("context_tokens", 0)
        if ctx_pct:
            self._last_context["percentage"] = ctx_pct
            self._last_context["total_tokens"] = ctx_tokens
        self._last_context["max_tokens"] = meta.get("max_tokens", 200000)
        self._last_context["cache_hit"] = meta.get("cache_hit", 0)
        self._last_context["cache_read"] = meta.get("cache_read", 0)
        self._last_context["cache_create"] = meta.get("cache_create", 0)

    def _finish_turn_status(self) -> None:
        """Set IDLE or WAITING based on bg jobs, then persist."""
        from app.bg_jobs import bg_manager
        if bg_manager and bg_manager.has_active_jobs(self.id):
            self.status = AgentStatus.WAITING
            self._log("status", "waiting for bg jobs")
        else:
            self.status = AgentStatus.IDLE
        self._persist()

    def _after_turn_idle_actions(self, live_pct: int) -> None:
        """Post-turn actions: compact ack, scope idle, auto-compact, auto-report, flush/hibernate."""
        if self._compact_ack_event is not None and self._turn_gen == self._compact_ack_gen:
            self._compact_ack_event.set()

        self._spawn_bg(self._notify_scope_idle())

        if live_pct > 90 and not self.is_orchestrator and not self._compacting:
            self._log("status", f"auto-compact triggered ({live_pct}%)")
            self._spawn_bg(self._auto_compact())

        self._fire_auto_report()

        if self._pending_messages:
            self._spawn_bg(self._flush_pending())
            return

        self._schedule_hibernate()

    async def _flush_pending(self) -> None:
        await asyncio.sleep(0.3)
        if self._compacting:
            return
        if not self._pending_messages:
            return
        msgs = list(self._pending_messages)
        self._pending_messages.clear()
        if len(msgs) == 1:
            combined = msgs[0]
        else:
            combined = "\n".join(
                f"--- message {i+1}/{len(msgs)} ---\n{m}"
                for i, m in enumerate(msgs)
            )
        self._log("status", f"delivering {len(msgs)} queued message(s)")
        try:
            async with self._lifecycle_lock:
                if self._compacting:
                    # compact grabbed the lock first — requeue, compact's finally re-flushes
                    self._pending_messages[0:0] = msgs
                    return
                self._did_report = False
                self._bump_turn_gen()
                self._turn_logs = []
                self._turn_start = asyncio.get_event_loop().time()
                self._last_msg_time = self._turn_start
                self.status = AgentStatus.RUNNING
                self._persist()
                backend = await self._ensure_backend()
                await backend.send(combined)
        except Exception as e:
            logger.error(f"[{self.name}] flush pending failed: {e}")
            self._pending_messages[0:0] = msgs
            self.status = AgentStatus.IDLE
            self._persist()

    # ── Hibernate (idle resource optimization) ──

    def _schedule_hibernate(self) -> None:
        if self._hibernate_task and not self._hibernate_task.done():
            self._hibernate_task.cancel()
        if self.backend_type != "claude":
            return
        timeout = IDLE_TIMEOUT_ORCHESTRATOR if self.is_orchestrator else IDLE_TIMEOUT_WORKER
        self._hibernate_task = asyncio.create_task(self._idle_hibernate(timeout))

    async def _idle_hibernate(self, timeout: float) -> None:
        try:
            await asyncio.sleep(timeout)
        except asyncio.CancelledError:
            return
        async with self._lifecycle_lock:
            if self.status != AgentStatus.IDLE:
                return
            if self._pending_messages:
                return
            if self._backend is None:
                return
            logger.info(f"[{self.name}] hibernating (idle {int(timeout)}s)")
            await self._disconnect_backend()
            self._hibernated = True

    def _on_task_done(self, task: asyncio.Task) -> None:
        try:
            exc = task.exception()
        except asyncio.CancelledError:
            return
        if exc:
            import traceback
            tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            logger.error(f"[{self.name}] listen task died with exception: {exc}\n{tb}")
            self._turn_start = 0
            self.status = AgentStatus.IDLE
            self._log("error", f"listen task exception: {exc}")
            self._persist()
        else:
            logger.warning(f"[{self.name}] listen task exited without exception (silent death), status={self.status}")
            if self.status == AgentStatus.RUNNING:
                self._log("error", "listen task exited unexpectedly while RUNNING")
                self._turn_start = 0
                self.status = AgentStatus.IDLE
                self._persist()

    ZOMBIE_TIMEOUT_CODEX = 600
    ZOMBIE_TIMEOUT_CLAUDE = 1800

    async def _heartbeat_loop(self) -> None:
        HEARTBEAT_INTERVAL = 60
        logger.info(f"[{self.name}] heartbeat started")
        while True:
            try:
                await asyncio.sleep(HEARTBEAT_INTERVAL)

                if self.status == AgentStatus.RUNNING and self._last_msg_time > 0:
                    silence = asyncio.get_event_loop().time() - self._last_msg_time
                    zombie_timeout = self.ZOMBIE_TIMEOUT_CODEX if self.backend_type == "codex" else self.ZOMBIE_TIMEOUT_CLAUDE
                    if silence > zombie_timeout:
                        if self.backend_type == "codex" or self._backend is None:
                            logger.error(f"[{self.name}] heartbeat: zombie detected ({silence:.0f}s silence, backend={'alive' if self._backend else 'dead'})")
                            self._log("error", f"zombie detected: {silence:.0f}s silence, auto-recovering")
                            if self._backend:
                                await self._disconnect_backend()
                            self.status = AgentStatus.IDLE
                            self._persist()
                            if self._pending_messages:
                                self._spawn_bg(self._flush_pending())
                        else:
                            logger.warning(f"[{self.name}] heartbeat: {silence:.0f}s silence during RUNNING turn")
                            self._log("status", f"no messages for {silence:.0f}s during active turn (possible long thinking)")

                if self._backend is None:
                    continue

                task_dead = self._listen_task is None or self._listen_task.done()
                if task_dead and self.status == AgentStatus.RUNNING and self.backend_type != "codex":
                    logger.warning(f"[{self.name}] heartbeat: listener dead but status=RUNNING — reconnecting")
                    self._log("error", "heartbeat detected dead listener, reconnecting")
                    try:
                        await self._backend.reconnect()
                        self._listen_task = asyncio.create_task(self._claude_event_loop())
                        self._listen_task.add_done_callback(self._on_task_done)
                        await self._backend.send("[system] Connection was restored after interruption. Continue your work.")
                        logger.info(f"[{self.name}] heartbeat reconnect OK")
                    except Exception as e:
                        logger.error(f"[{self.name}] heartbeat reconnect failed: {e}")
                        self._log("error", f"heartbeat reconnect failed: {e}")
                        self._backend = None
                        self.status = AgentStatus.IDLE
                        self._persist()
            except asyncio.CancelledError:
                logger.info(f"[{self.name}] heartbeat cancelled")
                return
            except Exception as e:
                logger.error(f"[{self.name}] heartbeat error: {e}")

    # ── Session operations ──

    async def interrupt(self) -> None:
        if self._backend and self.status == AgentStatus.RUNNING:
            await self._backend.interrupt()
        self._cancel_auto_report()
        self.status = AgentStatus.IDLE
        self._log("status", "interrupted")
        self._persist()

    async def compact(self) -> dict:
        COMPACT_PROMPT = (
            "[SYSTEM: Context compaction requested — handoff summary]\n\n"
            "Write a detailed handoff summary so your next session can continue seamlessly. "
            "Be as thorough as possible — this is the ONLY context your next session will have. No length limit.\n\n"
            "INTENT: What you are working on and why (2-3 sentences with full context).\n"
            "DECISIONS: All key decisions made during this session (bullet points, include reasoning).\n"
            "FILES: Every file touched with what was done (path — description of change).\n"
            "PENDING: Open questions, unfinished work, TODOs, blockers, next steps.\n"
            "RECENT: Last 5-10 exchanges in detail — what was asked, what you did, what the result was.\n"
            "BUGS: Any bugs found, workarounds applied, things that didn't work.\n"
            "IMPORTANT CONTEXT: Anything the next session MUST know — credentials paths, API quirks, "
            "user preferences, patterns discovered, traps to avoid.\n\n"
            "Output ONLY the summary. No commentary. Be specific — names, paths, numbers, not vague descriptions."
        )
        PREAMBLE = "[PREVIOUS CONTEXT SUMMARY — context was compacted]\n\n{summary}\n\n[END OF SUMMARY — continue naturally]\n\n"

        if self._compacting:
            return {"ok": False, "error": "compact already in progress"}
        self._compacting = True
        before_pct = self._last_context.get("percentage", 0)
        self._log("status", f"compact started (context {before_pct}%)")

        if self._listen_task and not self._listen_task.done():
            self._listen_task.cancel()
            try:
                await self._listen_task
            except (asyncio.CancelledError, Exception):
                pass

        summary_parts = []
        backend = self._backend or self._make_backend()
        need_connect = self._backend is None
        try:
            async with self._lifecycle_lock:
                if need_connect:
                    await backend.connect()
                await backend.send(COMPACT_PROMPT)
                async for event in backend.events():
                    if event.type == "text":
                        summary_parts.append(event.content)
                    elif event.type == "turn_end":
                        if event.metadata.get("session_id"):
                            self.session_id = event.metadata["session_id"]
                        break
        except Exception as e:
            self._log("error", f"compact failed: {e}")
            self._compacting = False
            return {"ok": False, "error": str(e), "before_pct": before_pct}
        finally:
            await backend.disconnect()
            self._backend = None

        summary = "".join(summary_parts).strip()
        if not summary:
            self._log("error", "compact returned empty summary")
            self._compacting = False
            return {"ok": False, "error": "empty summary", "before_pct": before_pct}

        preamble = PREAMBLE.format(summary=summary)
        self._compact_ack_event = asyncio.Event()
        ack_event = self._compact_ack_event
        try:
            async with self._lifecycle_lock:
                self._did_report = False
                self._bump_turn_gen()
                self._compact_ack_gen = self._turn_gen
                self._turn_logs = []
                self._turn_start = asyncio.get_event_loop().time()
                self._last_msg_time = self._turn_start
                self.status = AgentStatus.RUNNING
                self._persist()
                backend = await self._ensure_backend(force_fresh=True)
                await backend.send(preamble + "Acknowledge briefly.")

            try:
                await asyncio.wait_for(ack_event.wait(), timeout=60)
            except asyncio.TimeoutError:
                self._log("error", "compact ack turn did not complete (60s)")
                # stop the still-running ack turn so it can't interleave with the next send
                await self._disconnect_backend()
                self.status = AgentStatus.IDLE
                self._persist()
                return {"ok": False, "error": "ack turn did not complete", "before_pct": before_pct}
        finally:
            self._compact_ack_event = None
            self._compact_ack_gen = -1
            self._compacting = False
            if self._pending_messages:
                self._spawn_bg(self._flush_pending())

        after_pct = self._last_context.get("percentage", 0)
        self._log("status", f"compact done: {before_pct}% → {after_pct}%")
        return {"ok": True, "before_pct": before_pct, "after_pct": after_pct, "summary_chars": len(summary), "summary": summary}

    async def _notify_scope_idle(self) -> None:
        try:
            from app.tg_bridge import check_scope_idle, _manager as tg_mgr
            if not tg_mgr:
                return
            if self.is_orchestrator:
                orch_name = self.name
            else:
                orch_name = None
                for s in tg_mgr.sessions.values():
                    if s.is_orchestrator and s.scope == self.scope:
                        orch_name = s.name
                        break
            if orch_name:
                await check_scope_idle(orch_name, self.scope)
        except Exception:
            pass

    async def _auto_continue(self) -> None:
        await asyncio.sleep(1)
        try:
            await self.send("[system] Turn limit reached. Continue where you left off.")
            logger.info(f"[{self.name}] auto-continue after max_turns")
        except Exception as e:
            logger.warning(f"[{self.name}] auto-continue failed: {e}")
            self.status = AgentStatus.IDLE
            self._persist()

    async def _refresh_context_from_api(self) -> None:
        if not self._backend or not hasattr(self._backend, 'context_usage'):
            return
        try:
            usage = await asyncio.wait_for(self._backend.context_usage(), timeout=5)
            if usage and usage.get("percentage") is not None:
                old_pct = self._last_context.get("percentage", 0)
                self._last_context["percentage"] = usage["percentage"]
                self._last_context["total_tokens"] = usage.get("total_tokens", 0)
                raw_max = usage.get("raw_max_tokens") or usage.get("max_tokens")
                if raw_max:
                    self._last_context["max_tokens"] = raw_max
                if abs(old_pct - usage["percentage"]) > 30:
                    logger.info(f"[{self.name}] context corrected: {old_pct}% → {usage['percentage']}%")
                self._persist()
        except asyncio.TimeoutError:
            logger.debug(f"[{self.name}] context refresh timeout (5s)")
        except Exception as e:
            logger.debug(f"[{self.name}] context refresh failed: {e}")

    async def _auto_compact(self) -> None:
        await asyncio.sleep(2)
        try:
            await self.compact()
        except Exception as e:
            logger.warning(f"[{self.name}] auto-compact failed: {e}")

    async def change_model(self, new_model: str) -> dict:
        from app.models import backend_for_model
        old_model = self.model
        if old_model == new_model:
            return {"ok": True, "model": new_model, "changed": False}
        if self.status == AgentStatus.RUNNING:
            return {"ok": False, "error": "cannot change model while running"}

        old_backend = backend_for_model(old_model)
        new_backend_type = backend_for_model(new_model)
        if old_backend != new_backend_type:
            return {"ok": False, "error": f"Cannot change from {old_backend} to {new_backend_type}. Kill and respawn."}

        self._log("status", f"model change: {old_model} → {new_model}")
        await self._disconnect_backend()
        self.model = new_model
        self._persist()
        return {"ok": True, "model": new_model, "old_model": old_model, "changed": True}

    async def _disconnect_backend(self) -> None:
        if self._hibernate_task and not self._hibernate_task.done() and self._hibernate_task is not asyncio.current_task():
            self._hibernate_task.cancel()
            self._hibernate_task = None
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except (asyncio.CancelledError, Exception):
                pass
            self._heartbeat_task = None
        backend = self._backend
        self._backend = None
        if self._listen_task and not self._listen_task.done():
            self._listen_task.cancel()
            try:
                await self._listen_task
            except (asyncio.CancelledError, Exception):
                pass
        if backend:
            await backend.disconnect()

    async def stop(self) -> None:
        self._cancel_auto_report()
        await self._disconnect_backend()
        self._hibernated = False
        self.status = AgentStatus.IDLE
        self._persist()

    def _persist(self) -> None:
        self._persist_dirty = True
        if self._persist_task and not self._persist_task.done():
            return
        self._persist_task = asyncio.get_running_loop().create_task(self._persist_loop())
        self._persist_task.add_done_callback(self._on_persist_done)

    def _on_persist_done(self, task: asyncio.Task) -> None:
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[{self.name}] persist task crashed: {e}")

    async def _persist_loop(self) -> None:
        while self._persist_dirty:
            self._persist_dirty = False
            snapshot = self._to_db_dict()
            try:
                await asyncio.get_running_loop().run_in_executor(_db_executor(), save_session, snapshot)
            except Exception as e:
                logger.error(f"[{self.name}] persist failed: {e}")

    async def _drain_persist(self) -> None:
        if self._persist_task and not self._persist_task.done():
            await asyncio.gather(self._persist_task, return_exceptions=True)

    def _log(self, type: str, content: str) -> None:
        asyncio.get_event_loop().run_in_executor(_db_executor(), add_log, self.id, datetime.now(timezone.utc), type, content)

    def _to_db_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "scope": self.scope, "cwd": self.cwd,
            "model": self.model, "system_prompt": self.system_prompt,
            "status": self.status.value, "session_id": self.session_id,
            "cost_usd": self.cost_usd, "cost_usd_cached": self.cost_usd_cached,
            "worktree_path": self.worktree_path,
            "branch": self.branch, "is_orchestrator": self.is_orchestrator,
            "role": self.role, "parent_id": self.parent_id, "parent_name": self.parent_name,
            "color": self.color, "created_at": self.created_at.isoformat(),
            "finished_at": None,
            "context_pct": self._last_context.get("percentage", 0),
            "context_tokens": self._last_context.get("total_tokens", 0),
            "progress_pct": self.progress_pct,
            "progress_status": self.progress_status,
            "backend_type": self.backend_type,
            "task_id": self.task_id,
            "description": self.description,
            "total_turns": self.total_turns,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_tool_calls": self.total_tool_calls,
            "template_hash": self._template_hash,
            "mcp_servers_custom": json.dumps(self.mcp_servers_custom) if self.mcp_servers_custom else "",
            "owned_dirs": json.dumps(self.owned_dirs) if self.owned_dirs else "",
            "tg_topic": int(self.tg_topic),
        }

    async def get_context(self) -> dict:
        return self._last_context

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "scope": self.scope,
            "status": self.status.value, "model": self.model,
            "cost_usd": round(self.cost_usd, 4),
            "cost_usd_cached": round(self.cost_usd_cached, 4),
            "branch": self.branch,
            "is_orchestrator": self.is_orchestrator,
            "role": self.role, "parent_id": self.parent_id, "parent_name": self.parent_name,
            "color": self.color,
            "created_at": self.created_at.isoformat(),
            "context_pct": self._last_context.get("percentage", 0),
            "progress_pct": self.progress_pct,
            "progress_status": self.progress_status,
            "backend_type": self.backend_type,
            "hibernated": self._hibernated,
            "task_id": self.task_id,
            "description": self.description,
            "owned_dirs": self.owned_dirs,
            "tg_topic": self.tg_topic,
            "system_prompt": self.system_prompt[:500] if self.system_prompt else "",
            "total_turns": self.total_turns,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_tool_calls": self.total_tool_calls,
        }
