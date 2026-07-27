"""AgentSession — backend-agnostic wrapper with persistent event loop."""

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from functools import partial
from typing import TYPE_CHECKING, Awaitable, Callable, Optional

from app.events import AgentEvent
from app.models import backend_for_model, get_model_spec
from app.prompting import is_orchestrator_role, prompt_template_hash
from app.runtime_registry import (
    BackendBuildContext,
    _load_scope_mcp_servers,
    _load_user_mcp_servers,
    build_backend,
    get_runtime,
)
from app.session_cost import CostTracker
from app.session_hibernate import HibernateManager
from app.session_state import (  # noqa: F401 — re-exported: importers use app.session.AgentStatus
    AgentStatus, IDLE_TIMEOUT_ORCHESTRATOR, IDLE_TIMEOUT_WORKER,
)
from app.session_turns import TurnManager

if TYPE_CHECKING:
    from app.backend_protocol import BackendLike
from app.db import add_log, get_logs, save_session, tool_error_add

logger = logging.getLogger(__name__)


def _subscription_limit_kind(text: str) -> str | None:
    """Classify the canonical non-transient subscription-limit messages."""
    lowered = text.lower()
    if "monthly spend limit" in lowered:
        return "monthly"
    if any(marker in lowered for marker in (
        "session limit",
        "hit your session",
        "hit your usage limit",
        "usage limit",
        "subscription limit — ждём сброса квоты",
        "weekly usage limit",
        "weekly limit",
    )):
        return "timed"
    return None


def _is_terminal_subscription_limit(text: str) -> bool:
    """Known non-transient subscription limits that must never enter server retry."""
    return _subscription_limit_kind(text) is not None


def _claude_subscription_limit_active() -> bool:
    try:
        from app.routes.system import _usage_cache
        usage = _usage_cache.get("data") or {}
    except Exception:
        return False
    now = datetime.now(timezone.utc)
    for name in ("five_hour", "seven_day"):
        window = usage.get(name) or {}
        utilization = window.get("utilization")
        if not isinstance(utilization, (int, float)) or utilization < 100:
            continue
        resets_at = window.get("resets_at")
        if not resets_at:
            return True
        try:
            reset = datetime.fromisoformat(str(resets_at).replace("Z", "+00:00"))
            if reset.tzinfo is None:
                reset = reset.replace(tzinfo=timezone.utc)
            if reset > now:
                return True
        except (TypeError, ValueError):
            return True
    return False


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


_LAST_SUMMARY_MAX_CHARS = 4_000

# Compact summary is a multi-KB wall of text; logging it as "text" mirrors it to TG
# as agent speech. Off by default — the summary already lives in the agent's context
# and in the compact_worker result.
LOG_COMPACT_SUMMARY = os.getenv("LOG_COMPACT_SUMMARY", "0").strip().lower() in ("1", "true", "yes")


def _bounded_summary(summary: str) -> str:
    summary = summary.strip()
    if len(summary) <= _LAST_SUMMARY_MAX_CHARS:
        return summary
    marker = "\n\n[… summary truncated …]\n\n"
    head = (_LAST_SUMMARY_MAX_CHARS - len(marker)) // 2
    tail = _LAST_SUMMARY_MAX_CHARS - len(marker) - head
    return summary[:head] + marker + summary[-tail:]


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
    base_branch: str = ""
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
    effort: str | None = None
    runtime_handoff: str = ""
    last_summary: str = ""
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
    _log_futures: set = field(default_factory=set, repr=False)
    _last_context: dict = field(default_factory=lambda: {"percentage": 0, "total_tokens": 0, "max_tokens": 0}, repr=False)
    _did_report: bool = field(default=False, repr=False)
    _turn_logs: list = field(default_factory=list, repr=False)
    _tool_names_by_id: dict = field(default_factory=dict, repr=False)
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
    _spawn_repo_path: str = field(default="", repr=False)
    _spawn_git_common_dir: str = field(default="", repr=False)
    _auto_continue_count: int = field(default=0, repr=False)
    _rate_limit_retries: int = field(default=0, repr=False)
    _server_error_retries: int = field(default=0, repr=False)
    _session_limit_hit: bool = field(default=False, repr=False)
    _manually_interrupted: bool = field(default=False, repr=False)
    _precompact_timer_task: asyncio.Task | None = field(default=None, repr=False)
    _precompact_timer: dict | None = field(default=None, repr=False)

    AUTO_CONTINUE_MAX = 5
    RATE_LIMIT_MAX_RETRIES = 3
    RATE_LIMIT_DELAY = 30
    SERVER_ERROR_MAX_RETRIES = 3
    SERVER_ERROR_RETRY_DELAY = 5
    PRECOMPACT_DELAY_SECONDS = 55 * 60
    PRECOMPACT_CONTEXT_THRESHOLD = 20
    CODEX_PRECOMPACT_DELAY_SECONDS = 25 * 60
    CODEX_PRECOMPACT_CONTEXT_THRESHOLD = 60
    CLAUDE_CACHE_WINDOW_SECONDS = 60 * 60
    # ChatGPT-auth Codex publishes no contractual cache TTL. Keep a five-minute
    # safety margin before the observed/documented ~30-minute reference window.
    CODEX_CACHE_WINDOW_SECONDS = 30 * 60

    def _precompact_payload(self, payload: dict) -> str:
        return json.dumps(payload, ensure_ascii=False)

    def _precompact_policy(self) -> dict | None:
        if self.backend_type == "claude":
            return {
                "delay_seconds": self.PRECOMPACT_DELAY_SECONDS,
                "cache_window_seconds": self.CLAUDE_CACHE_WINDOW_SECONDS,
                "context_threshold": self.PRECOMPACT_CONTEXT_THRESHOLD,
                "arm_threshold": 0,
                "compact_mode": "handoff",
            }
        if self.backend_type == "codex":
            return {
                "delay_seconds": self.CODEX_PRECOMPACT_DELAY_SECONDS,
                "cache_window_seconds": self.CODEX_CACHE_WINDOW_SECONDS,
                "context_threshold": self.CODEX_PRECOMPACT_CONTEXT_THRESHOLD,
                "arm_threshold": self.CODEX_PRECOMPACT_CONTEXT_THRESHOLD,
                "compact_mode": "native",
            }
        return None

    def _cancel_precompact_timer(self, reason: str = "activity") -> None:
        if self._precompact_timer_task and not self._precompact_timer_task.done():
            self._precompact_timer_task.cancel()
        self._precompact_timer_task = None
        if self._precompact_timer:
            payload = {
                "event": "precompact_timer_cancelled",
                "scheduled_at": self._precompact_timer.get("scheduled_at"),
                "reason": reason,
            }
            self._log("status", f"precompact timer cancelled: {self._precompact_payload(payload)}")
        self._precompact_timer = None

    def _note_next_precompact_activity(self) -> None:
        if not self._precompact_timer:
            return
        fired_at = self._precompact_timer.get("fired_at")
        if not fired_at:
            self._cancel_precompact_timer(reason="activity_before_fire")
            return
        if not self._precompact_timer.get("next_activity"):
            next_activity = datetime.now(timezone.utc)
            try:
                elapsed = (
                    next_activity
                    - datetime.fromisoformat(self._precompact_timer["scheduled_at"])
                )
                cache_window_seconds = int(
                    self._precompact_timer.get(
                        "cache_window_seconds",
                        self.CLAUDE_CACHE_WINDOW_SECONDS,
                    )
                )
                crossed_cache_window = (
                    elapsed >= timedelta(seconds=cache_window_seconds)
                )
                crossed_60m = elapsed >= timedelta(minutes=60)
            except Exception:
                crossed_cache_window = False
                crossed_60m = False
            self._precompact_timer["next_activity"] = next_activity.isoformat()
            self._precompact_timer["crossed_cache_window"] = crossed_cache_window
            self._precompact_timer["crossed_60m"] = crossed_60m
            self._log(
                "status",
                f"precompact timer outcome: {self._precompact_payload(self._precompact_timer)}",
            )
            self._precompact_timer = None

    def _schedule_precompact_timer(self, context_pct: int) -> None:
        if self._precompact_timer is not None:
            return
        policy = self._precompact_policy()
        if policy is None or context_pct < policy["arm_threshold"]:
            return
        self._precompact_timer = {
            "scheduled_at": datetime.now(timezone.utc).isoformat(),
            "role": self.role,
            "backend": self.backend_type,
            "context_pct": context_pct,
            **policy,
        }
        self._log(
            "status",
            f"precompact timer scheduled: {self._precompact_payload(self._precompact_timer)}",
        )
        self._precompact_timer_task = self._spawn_bg(self._run_precompact_timer())

    async def _run_precompact_timer(self) -> None:
        try:
            delay = (
                self._precompact_timer.get("delay_seconds")
                if self._precompact_timer
                else self.PRECOMPACT_DELAY_SECONDS
            )
            await asyncio.sleep(delay)
            await self._fire_precompact_timer()
        except asyncio.CancelledError:
            pass

    async def _fire_precompact_timer(self) -> None:
        state = self._precompact_timer
        self._precompact_timer_task = None
        if not state:
            return

        fired_at = datetime.now(timezone.utc)
        state["fired_at"] = fired_at.isoformat()
        state["context_pct"] = self._last_context.get("percentage", 0)

        if self.status != AgentStatus.IDLE:
            state["skip_reason"] = "not_idle"
            self._log(
                "status",
                f"precompact timer skipped: {self._precompact_payload(state)}",
            )
            self._precompact_timer = None
            return

        from app.bg_jobs import bg_manager
        if bg_manager and bg_manager.has_active_jobs(self.id):
            state["skip_reason"] = "active_bg_jobs"
            self._log(
                "status",
                f"precompact timer skipped: {self._precompact_payload(state)}",
            )
            self._precompact_timer = None
            return

        policy = self._precompact_policy()
        if policy is None or state.get("backend") != self.backend_type:
            state["skip_reason"] = "backend_changed"
            self._log(
                "status",
                f"precompact timer skipped: {self._precompact_payload(state)}",
            )
            self._precompact_timer = None
            return

        threshold = int(state.get("context_threshold", policy["context_threshold"]))
        if self._last_context.get("percentage", 0) < threshold:
            state["skip_reason"] = "low_context"
            self._log(
                "status",
                f"precompact timer skipped: {self._precompact_payload(state)}",
            )
            self._precompact_timer = None
            return

        state["role"] = self.role
        state["backend"] = self.backend_type
        self._log(
            "status",
            f"precompact timer fired: {self._precompact_payload(state)}",
        )
        result = await self.compact()
        state["compact_result"] = result
        self._log(
            "status",
            f"precompact timer compacted: {self._precompact_payload(state)}",
        )

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
        spec = get_model_spec(self.model)
        context = BackendBuildContext(
            model=self.model,
            provider=spec.provider,
            cwd=self.cwd,
            system_prompt=self.system_prompt,
            resume_session_id=None if force_fresh else self.session_id,
            mcp_servers=self.mcp_servers,
            is_orchestrator=self.is_orchestrator,
            scope=self.scope,
            pipeline=self.pipeline,
            role=self.role,
            profile=self.profile,
            effort=self.effort,
            context_limit=spec.context_length,
        )
        return build_backend(self.backend_type, context)

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

    async def start(self, initial_message: str | None = None) -> None:
        if initial_message:
            await self.send(initial_message)
        else:
            self.status = AgentStatus.IDLE
            self._persist()

    async def send(self, message: str) -> None:
        original_user_message = message
        # Retry budgets belong to one logical request. A real new message resets both;
        # each internal retry preserves only its own failure class.
        if not message.startswith("[system] Retrying after rate limit."):
            self._rate_limit_retries = 0
        if not message.startswith("[system] Retrying after transient server error."):
            self._server_error_retries = 0
            self._session_limit_hit = False

        self._note_next_precompact_activity()
        if self._compacting:
            self._pending_messages.append(message)
            self._log("user_message", message)
            self._log("status", f"message queued (compact in progress, {len(self._pending_messages)} pending)")
            return

        capabilities = get_runtime(self.backend_type).capabilities
        if self.status == AgentStatus.RUNNING:
            if not capabilities.mid_turn_inject:
                self._pending_messages.append(message)
                self._log("user_message", message)
                self._log("status", f"message queued ({len(self._pending_messages)} pending)")
                return
            self._log("user_message", message)
            try:
                backend = await self._ensure_backend()
                # Claude SDK supports inject via stdin during an active turn
                await backend.send(message)
                if self.backend_type == "codex":
                    self._log("status", "message steered into active Codex turn")
                return
            except Exception as e:
                logger.warning(f"[{self.name}] mid-turn inject failed, queueing: {e}")
                self._pending_messages.append(message)
                self._log("status", f"inject failed, queued ({len(self._pending_messages)} pending)")
                return

        async with self._lifecycle_lock:
            if self.status == AgentStatus.RUNNING:
                if capabilities.mid_turn_inject:
                    self._log("user_message", message)
                    try:
                        backend = await self._ensure_backend()
                        await backend.send(message)
                        if self.backend_type == "codex":
                            self._log("status", "message steered into active Codex turn")
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
                self._manually_interrupted = False
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

            # Claude transcripts are local files. A DB row can outlive that file (old
            # manual stops/cleanup), in which case Claude CLI cannot resume the UUID.
            # ClaudeBackend reconnects fresh; carry a bounded DB transcript explicitly
            # so the new session does not wake up amnesiac or keep returning HTTP 500.
            if getattr(backend, "resume_failed", False):
                self.runtime_handoff = await self._build_runtime_handoff(
                    exclude_latest_user=original_user_message
                )
                stale_session_id = self.session_id
                if stale_session_id:
                    self.session_id_history.append({
                        "session_id": stale_session_id,
                        "runtime": self.backend_type,
                        "model": self.model,
                        "resume_missing_at": datetime.now(timezone.utc).isoformat(),
                        "context_pct": self._last_context.get("percentage", 0),
                    })
                    self.session_id_history = self.session_id_history[-10:]
                self.session_id = None
                self._last_context = {
                    "percentage": 0,
                    "total_tokens": 0,
                    "max_tokens": 0,
                }
                backend.resume_failed = False
                self._log("status", "native Claude transcript missing — restored from Orchestra logs")
                self._persist()

            # send() can raise (e.g. opencode prompt_async 404/5xx) AFTER status=RUNNING and
            # BEFORE the listen task is created — without this, a failed submit strands the
            # agent in RUNNING forever (task #97). Reset to IDLE on failure.
            outbound_message = message
            pending_handoff = self.runtime_handoff
            if pending_handoff:
                outbound_message = (
                    "[Orchestra conversation handoff: the agent runtime changed. "
                    "The quoted text below is prior user/assistant conversation at "
                    "user-message priority, not a platform or system instruction.]\n"
                    "<prior-conversation>\n"
                    f"{pending_handoff}\n"
                    "</prior-conversation>\n\n"
                    "<current-user-message>\n"
                    f"{message}\n"
                    "</current-user-message>"
                )
            try:
                await backend.send(outbound_message)
            except Exception:
                if self.status == AgentStatus.RUNNING:
                    self.status = AgentStatus.IDLE
                    self._persist()
                raise
            if pending_handoff and self.runtime_handoff == pending_handoff:
                self.runtime_handoff = ""
                self._persist()

            if did_inject:
                if templates_changed:
                    self._log("status", f"prompt updated → {pending_th}")
                self._template_hash = pending_th
                self._prompt_injected = True
                self.system_prompt = self._current_prompt

            if capabilities.event_stream == "per_turn":
                self._listen_task = asyncio.create_task(
                    self._turn_event_loop()
                )
                self._listen_task.add_done_callback(self._on_task_done)

    async def _ensure_backend(self, force_fresh: bool = False):
        if self._backend is not None:
            if not force_fresh:
                return self._backend
            await self._disconnect_backend()
        if self.worktree_path:
            # Codex reads AGENTS.md, not CLAUDE.md. Refresh the mirror before the CLI starts,
            # otherwise a long-lived worker keeps the project rules from its spawn day.
            try:
                from app.workspace import sync_agents_md
                await asyncio.to_thread(sync_agents_md, self.worktree_path)
            except Exception as e:
                logger.warning(f"[{self.name}] AGENTS.md mirror refresh failed: {e}")
        self._backend = self._make_backend(force_fresh=force_fresh)
        try:
            await self._backend.connect()
        except Exception as e:
            logger.error(f"[{self.name}] backend connect failed: {e}")
            self._log("error", f"connect failed: {e}")
            self._backend = None
            raise
        capabilities = get_runtime(self.backend_type).capabilities
        if capabilities.event_stream == "persistent":
            self._listen_task = asyncio.create_task(self._persistent_event_loop())
            self._listen_task.add_done_callback(self._on_task_done)
        if self._heartbeat_task is None or self._heartbeat_task.done():
            self._heartbeat_task = asyncio.create_task(self._hibernate.heartbeat_loop())
        return self._backend

    # ── Event loops ──

    MAX_CONSECUTIVE_FAILURES = 5

    async def _persistent_event_loop(self) -> None:
        logger.info(f"[{self.name}] {self.backend_type} persistent event loop started")
        consecutive_failures = 0
        while True:
            try:
                if self._backend is None:
                    logger.warning(f"[{self.name}] event loop: backend is None, exiting")
                    return
                async for event in self._backend.events():
                    self._last_msg_time = asyncio.get_event_loop().time()
                    self._handle_event(event)
                    consecutive_failures = 0
                # Persistent streams may return without error when the upstream closes.
                # During shutdown/restart this is normal — don't spam the user
                if self.status == AgentStatus.IDLE:
                    logger.info(f"[{self.name}] listener stream ended (agent idle/stopped — normal on restart)")
                    return
                consecutive_failures += 1
                logger.warning(f"[{self.name}] events() exhausted normally (attempt {consecutive_failures}/{self.MAX_CONSECUTIVE_FAILURES})")
                self._log("status", f"listener stream ended unexpectedly (attempt {consecutive_failures})")
            except asyncio.CancelledError:
                logger.info(f"[{self.name}] persistent event loop cancelled")
                return
            except Exception as e:
                consecutive_failures += 1
                import traceback
                tb = traceback.format_exc()
                logger.error(f"[{self.name}] persistent event loop died: {e}\n{tb}")
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

    async def _turn_event_loop(self) -> None:
        logger.info(f"[{self.name}] {self.backend_type} turn started")
        try:
            async for event in self._backend.events():
                self._last_msg_time = asyncio.get_event_loop().time()
                # thread.started is emitted before turn.completed. Store it now so an
                # interrupted long turn can resume instead of silently starting fresh.
                early_session_id = event.metadata.get("session_id") if event.type == "status" else None
                if early_session_id and early_session_id != self.session_id:
                    self.session_id = early_session_id
                    self._persist()
                self._handle_event(event)
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.error(f"[{self.name}] {self.backend_type} turn error: {e}")
            self._log("error", f"{self.backend_type} turn error: {e}")
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
        if event.type in ("thinking_stream", "tool_stream", "tool_patch", "turn_diff"):
            # Codex app-server exposes fine-grained activity that is valuable live but
            # would flood the DB. The authoritative thinking/tool/file events are still
            # persisted when their item completes.
            from app.live_broker import broker
            payload = {"type": event.type, "content": event.content}
            for key in ("activity", "item_id", "tool_use_id", "turn_id", "stream"):
                value = event.metadata.get(key)
                if value:
                    payload[key] = value
            broker.publish(self.id, payload)
            return
        tool_use_id = str(event.metadata.get("tool_use_id") or "")
        if event.type == "tool_use" and tool_use_id:
            self._tool_names_by_id[tool_use_id] = (
                event.metadata.get("tool_name") or "unknown"
            )
        elif event.type == "tool_result" and tool_use_id:
            remembered_name = self._tool_names_by_id.pop(tool_use_id, "unknown")
            tool_name = event.metadata.get("tool_name") or remembered_name
            if event.metadata.get("is_error"):
                self._submit_db_write(
                    tool_error_add,
                    self.name,
                    self.scope,
                    tool_name,
                    event.content,
                    runtime=self.backend_type,
                    tool_use_id=tool_use_id,
                )
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
            # Subscription limits arrive as text before the generic rate_limit error.
            if _is_terminal_subscription_limit(event.content):
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
        elif event.type in ("plan", "warning", "review"):
            self._log(event.type, event.content)
        elif event.type == "turn_end":
            self._turns.handle_turn_end(event)
        elif event.type == "error":
            # rate_limit → single retry-status log (skip raw error to avoid duplicate
            # "model error: rate_limit" + "rate limited — retry" on one event)
            if "rate_limit" in event.content:
                # Terminal subscription/usage limits — never retry
                if self._session_limit_hit or _is_terminal_subscription_limit(event.content):
                    self._log("error", "⏳ subscription limit — ждём сброса квоты. НЕ ретраим")
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
                self._manually_interrupted = False
                self._did_report = False
                self._turns.bump_turn_gen()
                self._turn_logs = []
                self._turn_start = asyncio.get_event_loop().time()
                self._last_msg_time = self._turn_start
                self.status = AgentStatus.RUNNING
                self._persist()
                backend = await self._ensure_backend()
                await backend.send(combined)
                if get_runtime(self.backend_type).capabilities.event_stream == "per_turn":
                    self._listen_task = asyncio.create_task(self._turn_event_loop())
                    self._listen_task.add_done_callback(self._on_task_done)
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
        async with self._lifecycle_lock:
            backend = self._backend if self.status == AgentStatus.RUNNING else None
            # Publish the stop before waiting for the SDK control acknowledgement. This
            # prevents concurrent messages from being injected into the turn being
            # interrupted; they will start a clean turn after this lock is released.
            self._turns.cancel_auto_report()
            self._cancel_precompact_timer("interrupt")
            self._turn_start = 0
            self._manually_interrupted = True
            self.status = AgentStatus.IDLE
            self._log("status", "interrupted")
            self._persist()

            if backend:
                acknowledged = await backend.interrupt()
                if acknowledged is False and self._backend is backend:
                    self._log("error", "interrupt was not acknowledged; disconnecting backend")
                    await self._disconnect_backend()

    async def _compact_codex_context(self) -> dict:
        if self._compacting:
            return {"ok": False, "error": "compact already in progress"}
        if self.status == AgentStatus.RUNNING:
            return {"ok": False, "error": "cannot compact while agent is running"}

        if self._precompact_timer and not self._precompact_timer.get("fired_at"):
            self._cancel_precompact_timer("manual_compact")
        self._compacting = True
        before_pct = self._last_context.get("percentage", 0)
        thread_id = self.session_id
        self._log(
            "status",
            f"compact started (native Codex, context {before_pct}%, thread={thread_id})",
        )
        try:
            async with self._lifecycle_lock:
                backend = await self._ensure_backend()
                compact_context = getattr(backend, "compact_context", None)
                if not callable(compact_context):
                    raise RuntimeError("Codex backend does not support native compact")
                self._hibernated = False
                result = await compact_context()

            context_tokens = result.get("context_tokens")
            max_tokens = result.get("max_tokens")
            if isinstance(max_tokens, int) and max_tokens > 0:
                self._last_context["max_tokens"] = max_tokens
            if isinstance(context_tokens, int) and context_tokens >= 0:
                self._last_context["total_tokens"] = context_tokens
                if isinstance(max_tokens, int) and max_tokens > 0:
                    self._last_context["percentage"] = round(
                        context_tokens * 100 / max_tokens
                    )

            after_pct = self._last_context.get("percentage", 0)
            summary = result.get("summary")
            if not summary:
                try:
                    summary = await self._build_runtime_handoff()
                except Exception as exc:
                    logger.debug(f"[{self.name}] Codex compact handoff snapshot failed: {exc}")
            if summary:
                self.last_summary = _bounded_summary(summary)
            self._persist()
            await self._drain_persist()
            self._log(
                "status",
                f"compact done (native Codex): {before_pct}% → {after_pct}%, "
                f"thread={self.session_id}",
            )
            return {
                "ok": True,
                "mode": "native",
                "before_pct": before_pct,
                "after_pct": after_pct,
                "thread_id": self.session_id,
                "context_tokens": context_tokens,
            }
        except Exception as exc:
            self._log("error", f"native Codex compact failed: {exc}")
            return {
                "ok": False,
                "mode": "native",
                "error": str(exc),
                "before_pct": before_pct,
                "thread_id": self.session_id,
            }
        finally:
            self._compacting = False
            if self._pending_messages:
                self._spawn_bg(self._flush_pending())
            elif self.status == AgentStatus.IDLE:
                self._hibernate.schedule()

    async def compact(self) -> dict:
        if self.backend_type == "codex":
            return await self._compact_codex_context()

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
        if _claude_subscription_limit_active():
            error = "Claude subscription limit active; compact postponed until quota reset"
            self._log("error", error)
            return {"ok": False, "error": error}
        self._session_limit_hit = False
        self._compacting = True
        before_pct = self._last_context.get("percentage", 0)
        pre_compact_session_id = self.session_id
        self._log("status", f"compact started (context {before_pct}%, pre_session={pre_compact_session_id})")

        def abort_compact(error: str) -> dict:
            self.session_id = pre_compact_session_id
            self._compacting = False
            if self._pending_messages:
                self._spawn_bg(self._flush_pending())
            return {"ok": False, "error": error, "before_pct": before_pct}

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
                            summary_parts.append(f"\n[tool] {event.content[:200]}\n")
                        elif event.type == "tool_result":
                            self._log("tool_result", event.content[:500])
                            summary_parts.append(f"\n[tool_result] {event.content[:200]}\n")
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
                return abort_compact(last_error)
            finally:
                try:
                    await backend.disconnect()
                except Exception:
                    pass
                self._backend = None

            summary = "".join(summary_parts).strip()

            summary_lower = summary.lower()
            terminal_limit = (
                len(summary) < COMPACT_MIN_SUMMARY_LEN
                and summary.count("\n") <= 2
                and _is_terminal_subscription_limit(summary)
            )
            provider_error = (
                len(summary) < COMPACT_MIN_SUMMARY_LEN
                and summary.count("\n") <= 2
                and any(pattern in summary_lower for pattern in _GARBAGE_PATTERNS)
            )
            if not summary:
                last_error = "empty summary"
            elif terminal_limit:
                last_error = "Claude subscription limit active; compact aborted"
            elif provider_error:
                last_error = "provider error returned instead of compact summary"
            else:
                last_error = ""

            if last_error:
                self._log("error", f"compact attempt {attempt}/{COMPACT_MAX_RETRIES}: {last_error}")
                self.session_id = pre_compact_session_id
                if not terminal_limit and attempt < COMPACT_MAX_RETRIES:
                    self._log("status", f"compact retry in {COMPACT_RETRY_DELAY * attempt}s...")
                    await asyncio.sleep(COMPACT_RETRY_DELAY * attempt)
                    continue
                return abort_compact(last_error)

            if attempt > 1:
                self._log("status", f"compact succeeded on attempt {attempt}")
            break

        preamble = PREAMBLE.format(summary=summary)
        self._compact_ack_event = asyncio.Event()
        ack_event = self._compact_ack_event
        try:
            async with self._lifecycle_lock:
                self._manually_interrupted = False
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
                self.session_id = pre_compact_session_id
                self.status = AgentStatus.IDLE
                self._persist()
                return {"ok": False, "error": "ack turn did not complete", "before_pct": before_pct}
            if self._session_limit_hit:
                error = "Claude subscription limit hit during compact acknowledgement"
                self._log("error", error)
                await self._disconnect_backend()
                self.session_id = pre_compact_session_id
                self.status = AgentStatus.IDLE
                self._persist()
                return {"ok": False, "error": error, "before_pct": before_pct}
        finally:
            self._compact_ack_event = None
            self._compact_ack_gen = -1
            self._compacting = False
            if self._pending_messages:
                self._spawn_bg(self._flush_pending())

        self.last_summary = _bounded_summary(summary)
        if pre_compact_session_id:
            self.session_id_history.append({
                "session_id": pre_compact_session_id,
                "runtime": self.backend_type,
                "model": self.model,
                "compacted_at": datetime.now(timezone.utc).isoformat(),
                "context_pct": before_pct,
            })
            self.session_id_history = self.session_id_history[-10:]
        self._persist()
        await self._drain_persist()
        if LOG_COMPACT_SUMMARY:
            self._log("text", f"📋 **Compact summary:**\n\n{summary}")
        after_pct = self._last_context.get("percentage", 0)
        self._log("status", f"compact done: {before_pct}% → {after_pct}% (summary {len(summary)} chars)")
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

    async def _retry_after_server_error(self, delay: int, expected_turn_gen: int) -> None:
        """Resume through a fresh SDK transport after an upstream stream failure."""
        await asyncio.sleep(delay)
        try:
            async with self._lifecycle_lock:
                # A real user message already started a newer turn; it supersedes this
                # automatic retry and must not be duplicated.
                if self._turn_gen != expected_turn_gen or self.status != AgentStatus.IDLE:
                    return
                await self._disconnect_backend()
            await self.send(
                "[system] Retrying after transient server error. Continue where you "
                "left off. Do not repeat completed research; execute the pending "
                "deliverable now."
            )
            logger.info(f"[{self.name}] server-error retry after {delay}s")
        except Exception as e:
            logger.warning(f"[{self.name}] server-error retry failed: {e}")
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

    async def _build_runtime_handoff(self, exclude_latest_user: str = "") -> str:
        """Build a bounded provider-neutral transcript for a new native runtime."""
        if self._log_futures:
            await asyncio.gather(*tuple(self._log_futures), return_exceptions=True)
        logs = await asyncio.get_running_loop().run_in_executor(
            _db_executor(),
            lambda: get_logs(self.id, limit=120),
        )
        labels = {"user_message": "User", "text": "Assistant"}
        blocks: list[str] = []
        total = 0
        max_chars = 32_000
        skipped_latest_user = False
        for entry in reversed(logs):
            label = labels.get(entry.get("type"))
            content = str(entry.get("content") or "").strip()
            if not label or not content:
                continue
            if (
                exclude_latest_user
                and not skipped_latest_user
                and label == "User"
                and content == exclude_latest_user.strip()
            ):
                skipped_latest_user = True
                continue
            if content.startswith("[Orchestra platform note:"):
                continue
            content = content[:6_000]
            block = f"{label}:\n{content}"
            if total + len(block) > max_chars:
                remaining = max_chars - total
                if remaining > 200:
                    blocks.append(block[-remaining:])
                break
            blocks.append(block)
            total += len(block)
        return "\n\n".join(reversed(blocks))

    async def change_model(self, new_model: str) -> dict:
        old_model = self.model
        if old_model == new_model:
            return {"ok": True, "model": new_model, "changed": False}
        if self.status == AgentStatus.RUNNING:
            return {"ok": False, "error": "cannot change model while running"}

        old_runtime = self.backend_type or backend_for_model(old_model)
        new_runtime = get_model_spec(new_model).runtime
        runtime_changed = old_runtime != new_runtime
        native_session_reset = (
            runtime_changed
            or not get_runtime(new_runtime).capabilities.resume_across_models
        )
        if native_session_reset:
            if runtime_changed and self.last_summary:
                self.runtime_handoff = _bounded_summary(self.last_summary)
            else:
                self.runtime_handoff = await self._build_runtime_handoff()
            # Legacy history predates runtime/model metadata. Cross-runtime switching
            # used to be forbidden, so those native IDs belong to the current runtime.
            for entry in self.session_id_history:
                entry.setdefault("runtime", old_runtime)
                entry.setdefault("model", old_model)
            if self.session_id:
                self.session_id_history.append({
                    "session_id": self.session_id,
                    "runtime": old_runtime,
                    "model": old_model,
                    "switched_at": datetime.now(timezone.utc).isoformat(),
                })
                self.session_id_history = self.session_id_history[-10:]

        self._log(
            "status",
            f"model change: {old_model} ({old_runtime}) → {new_model} ({new_runtime})",
        )
        await self._disconnect_backend()
        if native_session_reset:
            self.session_id = None
            self._last_context = {"percentage": 0, "total_tokens": 0, "max_tokens": 0}
        self.model = new_model
        self.backend_type = new_runtime
        self._prompt_injected = False
        self._hibernated = False
        self._persist()
        snapshot = self._to_db_dict()
        await asyncio.get_running_loop().run_in_executor(_db_executor(), save_session, snapshot)
        return {
            "ok": True,
            "model": new_model,
            "old_model": old_model,
            "runtime": new_runtime,
            "old_runtime": old_runtime,
            "runtime_changed": runtime_changed,
            "native_session_reset": native_session_reset,
            "changed": True,
        }

    async def _disconnect_backend(self) -> None:
        if self._hibernate_task and not self._hibernate_task.done() and self._hibernate_task is not asyncio.current_task():
            self._hibernate_task.cancel()
            self._hibernate_task = None
        if (self._heartbeat_task and not self._heartbeat_task.done()
                and self._heartbeat_task is not asyncio.current_task()):
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
        self._cancel_precompact_timer("stop")
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

    def _submit_db_write(self, operation, *args, **kwargs) -> None:
        """Run non-critical telemetry outside the event loop and surface failures."""
        future = asyncio.get_running_loop().run_in_executor(
            _db_executor(),
            partial(operation, *args, **kwargs),
        )
        self._log_futures.add(future)

        def completed(done) -> None:
            self._log_futures.discard(done)
            try:
                done.result()
            except Exception as error:
                logger.error(f"[{self.name}] telemetry write failed: {error}")

        future.add_done_callback(completed)

    def _log(self, type: str, content: str, *, event_id: str = "") -> None:
        # Fire-and-forget on dedicated DB pool — keeps event loop non-blocking for log-heavy turns
        future = asyncio.get_event_loop().run_in_executor(
            _db_executor(),
            add_log,
            self.id,
            datetime.now(timezone.utc),
            type,
            content,
            event_id,
        )
        self._log_futures.add(future)
        future.add_done_callback(self._log_futures.discard)

    def _persist_subagent(self, meta: dict, ended: bool = False) -> None:
        """Upsert sub-agent telemetry from a Task* event. Fire-and-forget.

        Only the fields the event carries are passed — subagent_upsert's
        NULLIF-COALESCE keeps prior values, so progress never wipes start's data.
        Lifecycle timestamps are captured before the executor can reorder jobs.
        """
        task_id = meta.get("subagent_id")
        if not task_id:
            return
        event_at = datetime.now(timezone.utc).isoformat()
        fields = {k: meta[k] for k in (
            "sdk_session_id", "tool_use_id", "description", "task_type", "status",
            "last_tool_name", "output_file", "summary", "raw_json",
            "total_tokens", "tool_uses", "duration_ms",
        ) if k in meta}
        if meta.get("phase") == "start":
            fields["started_at"] = event_at
        if ended or meta.get("phase") == "end":
            fields["ended_at"] = event_at
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
            "branch": self.branch, "base_branch": self.base_branch,
            "needs_switch": int(self.needs_switch),
            "is_orchestrator": self.is_orchestrator,
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
            "effort": self.effort or "",
            "runtime_handoff": self.runtime_handoff,
            "last_summary": self.last_summary,
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
            "base_branch": self.base_branch,
            "needs_switch": self.needs_switch,
            "is_orchestrator": self.is_orchestrator,
            "role": self.role, "parent_id": self.parent_id, "parent_name": self.parent_name,
            "color": self.color,
            "created_at": self.created_at.isoformat(),
            "context_pct": self._last_context.get("percentage", 0),
            "progress_pct": self.progress_pct,
            "progress_status": self.progress_status,
            "backend_type": self.backend_type,
            "runtime": self.backend_type,
            "provider": get_model_spec(self.model).provider,
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
