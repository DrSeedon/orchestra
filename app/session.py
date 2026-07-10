"""AgentSession — backend-agnostic wrapper with persistent event loop."""

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable, Optional

from app.events import AgentEvent
from app.models import backend_for_model
from app.prompting import is_orchestrator_role, prompt_template_hash
from app.session_cost import CostTracker
from app.session_hibernate import HibernateManager
from app.session_state import (  # noqa: F401 — re-exported: importers use app.session.AgentStatus
    AgentStatus, IDLE_TIMEOUT_ORCHESTRATOR, IDLE_TIMEOUT_WORKER,
)
from app.session_turns import TurnManager

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
        # 4 workers: enough for concurrent log/persist bursts without starving the event loop
        _DB_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="db")
    return _DB_EXECUTOR


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


def _load_user_mcp_servers(config_dir: str) -> dict:
    """F2: user-MCP из top-level ``.claude.json`` профиля.

    ``config_dir`` непуст → ``<config_dir>/.claude.json``; пуст → ``~/.claude.json``
    (env процесса orchestra). Берёт ключ ``mcpServers``, пропуская ``orchestra``
    (серверный MCP подмешивается отдельно и не должен подменяться профилем).
    Зеркалит стиль ``_load_scope_mcp_servers``: ошибки парсинга — warning, не падаем.

    ВНИМАНИЕ: личный профиль CLI хранит ``.claude.json`` в HOME root
    (``~/.claude.json``), а НЕ внутри ``~/.claude/``. Поэтому для личного профиля
    держим ``config_dir=""`` (сид-профиль ``personal`` так и сидится). Если задать
    ``config_dir="~/.claude"`` — функция пойдёт в ``~/.claude/.claude.json``,
    которого нет, и вернёт пусто. Рабочий профиль (``~/.claude-work``) хранит
    ``.claude.json`` ВНУТРИ config dir — для него путь верный.
    """
    servers: dict = {}
    base = Path(os.path.expanduser(config_dir)) if config_dir else Path.home()
    path = base / ".claude.json"
    if not path.is_file():
        return servers
    try:
        data = json.loads(path.read_text())
        for k, v in data.get("mcpServers", {}).items():
            if k != "orchestra":
                servers[k] = v
    except Exception as e:
        logger.warning(f"Failed to parse user MCP servers from {path}: {e}")
    return servers


@dataclass
class AgentSession:
    id: str
    name: str
    scope: str
    cwd: str
    model: str = "claude-sonnet-5[1m]"
    system_prompt: str = ""
    status: AgentStatus = AgentStatus.IDLE
    session_id: str | None = None
    session_id_history: list = field(default_factory=list, repr=False)
    cost_usd: float = 0.0
    cost_usd_cached: float = 0.0
    worktree_path: str | None = None
    branch: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    role: str = "worker"
    parent_id: str = ""
    parent_name: str = ""
    pipeline: str = ""
    profile: str = ""
    _is_orchestrator: bool | None = field(default=None, repr=False)
    color: str = ""
    mcp_servers: dict = field(default_factory=dict, repr=False)
    mcp_servers_custom: dict = field(default_factory=dict, repr=False)
    on_error: Optional[callable] = field(default=None, repr=False)
    backend_type: str = "claude"
    task_id: str = ""
    description: str = ""
    owned_dirs: list = field(default_factory=list, repr=False)
    tg_topic: bool = False

    needs_switch: bool = False
    last_task_sender: str = ""

    # False → detached DB-hydrate (manager._hydrate_row): data only, no backend/tasks.
    # NEVER call start()/send()/_persist() on a detached session.
    loaded: bool = True
    # raw DB row of a detached session — preserves legacy response shape (richer than to_dict)
    db_row: Optional[dict] = field(default=None, repr=False)

    progress_pct: int = 0
    progress_status: str = ""

    total_turns: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cache_read_tokens: int = 0
    total_cache_create_tokens: int = 0
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
    _turn_cost: float = field(default=0.0, repr=False)
    _context_cost: float = field(default=0.0, repr=False)
    _session_cost: float = field(default=0.0, repr=False)
    _last_cost_cached: float = field(default=0.0, repr=False)
    _last_turn_ok: bool = field(default=True, repr=False)
    _last_stop_reason: str = field(default="", repr=False)
    _lifecycle_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    _persist_task: Optional[asyncio.Task] = field(default=None, repr=False)
    _persist_dirty: bool = field(default=False, repr=False)
    _turn_gen: int = field(default=0, repr=False)
    _auto_report_task: Optional[asyncio.Task] = field(default=None, repr=False)
    _spawn_warning: str = field(default="", repr=False)
    _auto_continue_count: int = field(default=0, repr=False)
    _rate_limit_retries: int = field(default=0, repr=False)
    _session_limit_hit: bool = field(default=False, repr=False)

    TURN_TIMEOUT = 600
    AUTO_CONTINUE_MAX = 5
    RATE_LIMIT_MAX_RETRIES = 3
    RATE_LIMIT_DELAY = 30

    def __post_init__(self) -> None:
        # Systems over state (ECS): cost/turn/hibernate methods live in systems,
        # all fields stay on the session (persistence reads them directly)
        self._cost = CostTracker(self)
        self._turns = TurnManager(self)
        self._hibernate = HibernateManager(self)

    @property
    def is_orchestrator(self) -> bool:
        if self._is_orchestrator is not None:
            return self._is_orchestrator
        return is_orchestrator_role(self.role)

    @is_orchestrator.setter
    def is_orchestrator(self, value: bool) -> None:
        self._is_orchestrator = value

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
        elif self.backend_type == "opencode":
            from app.backend_opencode import OpenCodeBackend
            return OpenCodeBackend(
                model=self.model, cwd=self.cwd,
                system_prompt=self.system_prompt,
                resume_session_id=resume,
                mcp_servers=self.mcp_servers,
                is_orchestrator=self.is_orchestrator,
            )
        else:
            from app.backend_claude import ClaudeBackend
            from app.pipeline import get_role
            from app.db import get_profile
            # Резолв роли: нет манифеста → чистый upstream-fallback
            # (inherit=True, config_dir по профилю, user_mcp пуст — как сегодня).
            try:
                rr = get_role(self.pipeline, self.role)
            except FileNotFoundError:
                rr = None
            inherit = rr.inherit_claude_md if rr else True
            config_dir = ""
            if self.profile:
                p = get_profile(self.profile)
                config_dir = p["config_dir"] if p else ""
            # F2: user-MCP подмешиваем ТОЛЬКО при mcp_servers=="all" (tasks-pm);
            # default/список — без user-MCP (1:1 upstream).
            user_mcp: dict = {}
            if rr is not None and rr.mcp_servers == "all":
                user_mcp = _load_user_mcp_servers(config_dir)
            return ClaudeBackend(
                model=self.model, cwd=self.cwd,
                system_prompt=self.system_prompt,
                resume_session_id=resume,
                mcp_servers=self.mcp_servers,
                is_orchestrator=self.is_orchestrator,
                scope_mcp_servers=_load_scope_mcp_servers(self.scope),
                config_dir=config_dir,
                inherit_claude_md=inherit,
                user_mcp_servers=user_mcp,
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
                # Codex backend is a one-shot subprocess; mid-turn inject isn't supported
                self._pending_messages.append(message)
                self._log("user_message", message)
                self._log("status", f"message queued ({len(self._pending_messages)} pending)")
                return
            self._log("user_message", message)
            try:
                backend = await self._ensure_backend()
                # Claude SDK supports inject via stdin during an active turn
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
                # Inject updated system prompt once per session — workers list, role
                # catalog, and template content drift as other agents spawn/die.
                # Only on first message after resume; subsequent turns use cached prompt.
                current_th = prompt_template_hash(self.role)
                old_th = self._template_hash or current_th
                templates_changed = old_th != current_th
                pending_th = current_th
                message = f"[Orchestra platform note: {'your role instructions were updated.' if templates_changed else 'refreshed context (worker list, etc.).'} This is from the server, not another agent.]\n{self._current_prompt}\n\n---\n\n{message}"
                did_inject = True

            if self.status in (AgentStatus.IDLE, AgentStatus.WAITING):
                self._did_report = False
                self._turns.bump_turn_gen()
                self._turn_logs = []
                self._turn_start = asyncio.get_event_loop().time()
                self._last_msg_time = self._turn_start
                self.status = AgentStatus.RUNNING
                self._persist()
                asyncio.create_task(self._notify_scope_running())

            try:
                backend = await self._ensure_backend()
            except Exception:
                self.status = AgentStatus.IDLE
                self._persist()
                raise

            # send() can raise (e.g. opencode prompt_async 404/5xx) AFTER status=RUNNING and
            # BEFORE the listen task is created — without this, a failed submit strands the
            # agent in RUNNING forever (task #97). Reset to IDLE on failure.
            try:
                await backend.send(message)
            except Exception:
                if self.status == AgentStatus.RUNNING:
                    self.status = AgentStatus.IDLE
                    self._persist()
                raise

            if did_inject:
                if templates_changed:
                    self._log("status", f"prompt updated → {pending_th}")
                self._template_hash = pending_th
                self._prompt_injected = True
                self.system_prompt = self._current_prompt

            if self.backend_type in ("codex", "opencode"):
                self._listen_task = asyncio.create_task(
                    self._codex_turn_loop() if self.backend_type == "codex"
                    else self._claude_event_loop()
                )
                self._listen_task.add_done_callback(self._on_task_done)

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
        if self.backend_type not in ("codex", "opencode"):
            self._listen_task = asyncio.create_task(self._claude_event_loop())
            self._listen_task.add_done_callback(self._on_task_done)
        if self._heartbeat_task is None or self._heartbeat_task.done():
            self._heartbeat_task = asyncio.create_task(self._hibernate.heartbeat_loop())
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
                        self._turn_start = asyncio.get_event_loop().time()
                        # Keep status=RUNNING — agent is actively being continued
                        await self._backend.send("[system] Turn timed out. Continue where you left off.")
                        continue
                    self._handle_event(event)
                    consecutive_failures = 0
                # For opencode: events() finishing = turn done (per-turn generator, not persistent stream).
                # Exit cleanly — next send() will start a new listen task.
                if self.backend_type == "opencode":
                    logger.info(f"[{self.name}] opencode turn completed normally, status={self.status}")
                    if self.status == AgentStatus.RUNNING:
                        self.status = AgentStatus.IDLE
                        self._persist()
                    return
                # For claude: events() returns without error when SDK stream closes unexpectedly
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
                if self.backend_type == "opencode":
                    logger.info(f"[{self.name}] opencode listener ended, status={self.status}")
                    if self.status == AgentStatus.RUNNING:
                        self.status = AgentStatus.IDLE
                        self._persist()
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
                    self._hibernate.schedule()

    # ── Unified event handler ──

    def _handle_event(self, event: AgentEvent) -> None:
        if event.type == "stream":
            # Live partials: push to in-memory broker for SSE fan-out, NEVER persist.
            # The final "text" event (below) is the DB source of truth.
            from app.live_broker import broker
            broker.publish(self.id, {"type": "stream", "content": event.content})
            return
        if event.type == "subagent_stream":
            # Live sub-agent output → broker only (ephemeral, like main stream).
            # subagent_id lets the UI nest it under the right sub-agent block.
            from app.live_broker import broker
            broker.publish(self.id, {"type": "subagent_stream", "content": event.content,
                                     "subagent_id": event.metadata.get("subagent_id", "")})
            return
        # Sub-agent tool_use/text/tool_result (tagged with subagent_id) → broker ONLY
        # (ephemeral live nesting under the sub-agent block). NOT persisted — the DB
        # record is subagent_start/end; persisting these too would double-render them
        # (once in the accordion via broker, once in the main flow on reload).
        sub_id = event.metadata.get("subagent_id")
        if sub_id and event.type in ("tool_use", "tool_result", "text", "thinking"):
            from app.live_broker import broker
            broker.publish(self.id, {"type": "subagent_event", "event_type": event.type,
                                     "content": event.content[:2000], "subagent_id": sub_id})
            return
        if event.type == "text":
            from app.live_broker import broker
            broker.clear_accum(self.id)
            # Session limit comes as text "You've hit your session limit", not as error event
            if "session limit" in event.content.lower() or "hit your session" in event.content.lower():
                self._session_limit_hit = True
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
            self._turns.handle_turn_end(event)
        elif event.type == "error":
            # rate_limit → single retry-status log (skip raw error to avoid duplicate
            # "model error: rate_limit" + "rate limited — retry" on one event)
            if "rate_limit" in event.content:
                # Session limit text arrives BEFORE the error event as text "You've hit your session limit"
                if self._session_limit_hit:
                    self._log("error", f"⏳ session limit (подписка) — ждём сброса окна. НЕ ретраим")
                    self._session_limit_hit = False
                elif self._rate_limit_retries < self.RATE_LIMIT_MAX_RETRIES:
                    self._rate_limit_retries += 1
                    delay = self.RATE_LIMIT_DELAY * self._rate_limit_retries
                    self._log("status", f"⏳ rate limit (Anthropic сервер) — повтор через {delay}s ({self._rate_limit_retries}/{self.RATE_LIMIT_MAX_RETRIES})")
                    self._spawn_bg(self._rate_limit_retry(delay))
                else:
                    self._log("error", f"rate limit — gave up after {self.RATE_LIMIT_MAX_RETRIES} retries")
            else:
                self._log("error", event.content)
        elif event.type == "subagent_start":
            self._log("subagent_start", event.content)
            self._persist_subagent(event.metadata)
        elif event.type == "subagent_progress":
            self._log("subagent_progress", event.content)
            self._persist_subagent(event.metadata)
        elif event.type == "subagent_end":
            self._log("subagent_end", event.content)
            self._persist_subagent(event.metadata, ended=True)
        elif event.type == "status":
            self._log("status", event.content)

    async def _flush_pending(self) -> None:
        # Brief delay: let the just-finished turn fully settle (persist, hibernate schedule)
        # before starting the next one — avoids nested lock acquisition from the same coroutine
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
            # Batch queued messages into one turn to avoid spawning N sequential turns —
            # each turn has ~3s round-trip overhead and occupies the lifecycle lock
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
                self._turns.bump_turn_gen()
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

    def _on_task_done(self, task: asyncio.Task) -> None:
        try:
            exc = task.exception()
        except asyncio.CancelledError:
            return
        if exc:
            import traceback
            tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            logger.error(f"[{self.name}] listen task died with exception: {exc}\n{tb}")
            self._log("error", f"listen task died: {exc}")
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

    # ── Session operations ──

    async def interrupt(self) -> None:
        if self._backend and self.status == AgentStatus.RUNNING:
            await self._backend.interrupt()
        self._turns.cancel_auto_report()
        self.status = AgentStatus.IDLE
        self._log("status", "interrupted")
        self._persist()

    async def compact(self) -> dict:
        _ORCH_PRESAVE = (
            "BEFORE writing the summary — persist your knowledge to files so it survives compact:\n"
            "1. CLAUDE.md — append key decisions, new rules, patterns discovered this session (section '## Session notes')\n"
            "2. TODO.md — add new items, remove done items\n"
            "3. BUGS.md — add found bugs, close fixed ones\n"
            "4. docs/ — save any research or analysis worth keeping\n"
            "Use Edit/Write tools NOW. Then write the summary below.\n\n"
        )
        COMPACT_PROMPT = (
            "[SYSTEM: Context compaction requested — handoff summary]\n\n"
            + (_ORCH_PRESAVE if self.is_orchestrator else "")
            + "Write a detailed handoff summary so your next session can continue seamlessly. "
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
        COMPACT_MAX_RETRIES = 3
        COMPACT_RETRY_DELAY = 30
        COMPACT_MIN_SUMMARY_LEN = 200
        _GARBAGE_PATTERNS = ["rate limit", "rate_limit", "api error", "overloaded", "temporarily limiting", "server error", "session limit", "hit your session"]

        if self._compacting:
            return {"ok": False, "error": "compact already in progress"}
        if self.status == AgentStatus.RUNNING:
            return {"ok": False, "error": "cannot compact while agent is running"}
        self._compacting = True
        before_pct = self._last_context.get("percentage", 0)
        pre_compact_session_id = self.session_id
        self._log("status", f"compact started (context {before_pct}%, pre_session={pre_compact_session_id})")

        if self._listen_task and not self._listen_task.done():
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.warning(f"[{self.name}] listen task failed during compact: {e}")

        summary = ""
        last_error = ""
        for attempt in range(1, COMPACT_MAX_RETRIES + 1):
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
                        elif event.type == "tool":
                            self._log("tool", event.content)
                        elif event.type == "tool_result":
                            self._log("tool_result", event.content[:500])
                        elif event.type == "turn_end":
                            if event.metadata.get("session_id"):
                                self.session_id = event.metadata["session_id"]
                            break
            except Exception as e:
                last_error = str(e)
                self._log("error", f"compact attempt {attempt}/{COMPACT_MAX_RETRIES} failed: {e}")
                try:
                    await backend.disconnect()
                except Exception:
                    pass
                self._backend = None
                if attempt < COMPACT_MAX_RETRIES:
                    self._log("status", f"compact retry in {COMPACT_RETRY_DELAY * attempt}s...")
                    await asyncio.sleep(COMPACT_RETRY_DELAY * attempt)
                    continue
                self._compacting = False
                return {"ok": False, "error": last_error, "before_pct": before_pct}
            finally:
                try:
                    await backend.disconnect()
                except Exception:
                    pass
                self._backend = None

            summary = "".join(summary_parts).strip()
            summary_lower = summary.lower()
            is_garbage = any(p in summary_lower for p in _GARBAGE_PATTERNS)
            is_too_short = len(summary) < COMPACT_MIN_SUMMARY_LEN

            if not summary or is_garbage or is_too_short:
                reason = "empty" if not summary else f"garbage ({summary[:100]}...)" if is_garbage else f"too short ({len(summary)} chars)"
                last_error = f"invalid summary: {reason}"
                self._log("error", f"compact attempt {attempt}/{COMPACT_MAX_RETRIES}: {last_error}")
                if attempt < COMPACT_MAX_RETRIES:
                    self._log("status", f"compact retry in {COMPACT_RETRY_DELAY * attempt}s...")
                    await asyncio.sleep(COMPACT_RETRY_DELAY * attempt)
                    continue
                self._compacting = False
                return {"ok": False, "error": last_error, "before_pct": before_pct}

            if attempt > 1:
                self._log("status", f"compact succeeded on attempt {attempt}")
            break
        self._log("text", f"📋 **Compact summary:**\n\n{summary}")

        preamble = PREAMBLE.format(summary=summary)
        if pre_compact_session_id:
            self.session_id_history.append({
                "session_id": pre_compact_session_id,
                "compacted_at": datetime.now(timezone.utc).isoformat(),
                "context_pct": before_pct,
            })
            MAX_HISTORY = 10
            self.session_id_history = self.session_id_history[-MAX_HISTORY:]
        self._compact_ack_event = asyncio.Event()
        ack_event = self._compact_ack_event
        try:
            async with self._lifecycle_lock:
                self._did_report = False
                self._turns.bump_turn_gen()
                self._compact_ack_gen = self._turn_gen
                self._turn_logs = []
                self._turn_start = asyncio.get_event_loop().time()
                self._last_msg_time = self._turn_start
                self.status = AgentStatus.RUNNING
                self._persist()
                backend = await self._ensure_backend(force_fresh=True)
                self._log("user_message", preamble + "Acknowledge briefly.")
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
        # wired callback (set by tg_bridge.start_bridge) — session does not import tg_bridge
        if on_scope_idle is None:
            return
        try:
            await on_scope_idle(self)
        except Exception as e:
            logger.warning(f"[{self.name}] TG scope-idle notify failed: {e}")

    async def _notify_scope_running(self) -> None:
        if on_scope_running is None:
            return
        try:
            await on_scope_running(self)
        except Exception as e:
            logger.warning(f"[{self.name}] TG scope-running notify failed: {e}")

    async def _rate_limit_retry(self, delay: int) -> None:
        await asyncio.sleep(delay)
        try:
            await self.send("[system] Retrying after rate limit. Continue where you left off.")
            logger.info(f"[{self.name}] rate-limit retry after {delay}s")
        except Exception as e:
            logger.warning(f"[{self.name}] rate-limit retry failed: {e}")
            self.status = AgentStatus.IDLE
            self._persist()

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
        snapshot = self._to_db_dict()
        await asyncio.get_running_loop().run_in_executor(_db_executor(), save_session, snapshot)
        return {"ok": True, "model": new_model, "old_model": old_model, "changed": True}

    async def _disconnect_backend(self) -> None:
        if self._hibernate_task and not self._hibernate_task.done() and self._hibernate_task is not asyncio.current_task():
            self._hibernate_task.cancel()
            self._hibernate_task = None
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.warning(f"[{self.name}] heartbeat task failed on disconnect: {e}")
            self._heartbeat_task = None
        backend = self._backend
        self._backend = None
        if self._listen_task and not self._listen_task.done():
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.warning(f"[{self.name}] listen task failed on disconnect: {e}")
        if backend:
            await backend.disconnect()

    async def stop(self) -> None:
        self._log("status", "⏹️ stopped (manual interrupt)")
        self._turns.cancel_auto_report()
        await self._disconnect_backend()
        self._hibernated = False
        self.status = AgentStatus.IDLE
        self._persist()

    def _persist(self) -> None:
        # Coalesce rapid successive calls: mark dirty, let one active task drain them all —
        # prevents N DB writes when status/cost/context all change in the same event loop tick
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
        # Fire-and-forget on dedicated DB pool — keeps event loop non-blocking for log-heavy turns
        asyncio.get_event_loop().run_in_executor(_db_executor(), add_log, self.id, datetime.now(timezone.utc), type, content)

    def _persist_subagent(self, meta: dict, ended: bool = False) -> None:
        """Upsert sub-agent telemetry from a Task* event. Fire-and-forget.

        Only the fields the event carries are passed — subagent_upsert's
        NULLIF-COALESCE keeps prior values, so progress never wipes start's data.
        """
        task_id = meta.get("subagent_id")
        if not task_id:
            return
        fields = {k: meta[k] for k in (
            "sdk_session_id", "tool_use_id", "description", "task_type", "status",
            "last_tool_name", "output_file", "summary", "raw_json",
            "total_tokens", "tool_uses", "duration_ms",
        ) if k in meta}
        if ended:
            fields["ended_at"] = datetime.now(timezone.utc).isoformat()
        from app.db import subagent_upsert
        asyncio.get_event_loop().run_in_executor(
            _db_executor(), lambda: subagent_upsert(self.id, task_id, **fields))

    def _to_db_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "scope": self.scope, "cwd": self.cwd,
            "model": self.model, "system_prompt": self.system_prompt,
            "status": self.status.value, "session_id": self.session_id,
            "cost_usd": self.cost_usd, "cost_usd_cached": self.cost_usd_cached,
            "context_cost": self._context_cost,
            "worktree_path": self.worktree_path,
            "branch": self.branch, "is_orchestrator": self.is_orchestrator,
            "role": self.role, "parent_id": self.parent_id, "parent_name": self.parent_name,
            "pipeline": self.pipeline,
            "profile": self.profile,
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
            "total_cache_read_tokens": self.total_cache_read_tokens,
            "total_cache_create_tokens": self.total_cache_create_tokens,
            "total_tool_calls": self.total_tool_calls,
            "template_hash": self._template_hash,
            "mcp_servers_custom": json.dumps(self.mcp_servers_custom) if self.mcp_servers_custom else "",
            "owned_dirs": json.dumps(self.owned_dirs) if self.owned_dirs else "",
            "tg_topic": int(self.tg_topic),
            "session_id_history": json.dumps(self.session_id_history) if self.session_id_history else "[]",
        }

    async def get_context(self) -> dict:
        return self._last_context

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "scope": self.scope,
            "cwd": self.cwd, "worktree_path": self.worktree_path,
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
            "total_cache_read_tokens": self.total_cache_read_tokens,
            "total_cache_create_tokens": self.total_cache_create_tokens,
            "total_tool_calls": self.total_tool_calls,
        }


# ── Wired callbacks: assigned by tg_bridge.start_bridge, reset by stop_bridge.
# Session fires events without importing tg_bridge (cycle cut). Declared after
# the class — module-level annotations evaluate eagerly (PEP 526), a pre-class
# AgentSession reference would NameError on import.
on_scope_idle: "Callable[[AgentSession], Awaitable[None]] | None" = None
on_scope_running: "Callable[[AgentSession], Awaitable[None]] | None" = None
