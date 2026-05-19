"""AgentSession — backend-agnostic wrapper with persistent event loop."""

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

from app.events import AgentEvent
from app.db import save_session, add_log

logger = logging.getLogger(__name__)

IDLE_TIMEOUT_WORKER = 300
IDLE_TIMEOUT_ORCHESTRATOR = 600


def _prompt_hash(text: str) -> str:
    import hashlib
    return hashlib.md5(text.encode()).hexdigest()[:8]


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
    return servers


class AgentStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"


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
    worktree_path: str | None = None
    branch: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    is_orchestrator: bool = False
    color: str = ""
    mcp_servers: dict = field(default_factory=dict, repr=False)
    on_error: Optional[callable] = field(default=None, repr=False)
    backend_type: str = "claude"
    task_id: str = ""
    description: str = ""

    progress_pct: int = 0
    progress_status: str = ""

    _backend: Optional[object] = field(default=None, repr=False)
    _listen_task: Optional[asyncio.Task] = field(default=None, repr=False)
    _heartbeat_task: Optional[asyncio.Task] = field(default=None, repr=False)
    _last_context: dict = field(default_factory=lambda: {"percentage": 0, "total_tokens": 0, "max_tokens": 0}, repr=False)
    _did_report: bool = field(default=False, repr=False)
    _turn_logs: list = field(default_factory=list, repr=False)
    _bg_outputs: list = field(default_factory=list, repr=False)
    _prompt_injected: bool = field(default=False, repr=False)
    _current_prompt: str = field(default="", repr=False)
    _turn_start: float = field(default=0.0, repr=False)
    _last_msg_time: float = field(default=0.0, repr=False)
    _pending_messages: list = field(default_factory=list, repr=False)
    on_idle: Optional[callable] = field(default=None, repr=False)
    _hibernate_task: Optional[asyncio.Task] = field(default=None, repr=False)
    _hibernated: bool = field(default=False, repr=False)
    _lifecycle_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    TURN_TIMEOUT = 600

    def _make_backend(self):
        if self.backend_type == "codex":
            from app.backend_codex import CodexBackend
            return CodexBackend(
                model=self.model, cwd=self.cwd,
                system_prompt=self.system_prompt,
                resume_thread_id=self.session_id,
                mcp_env=self._build_codex_mcp_env(),
                reasoning_effort=self._codex_reasoning_effort(),
            )
        else:
            from app.backend_claude import ClaudeBackend
            return ClaudeBackend(
                model=self.model, cwd=self.cwd,
                system_prompt=self.system_prompt,
                resume_session_id=self.session_id,
                mcp_servers=self.mcp_servers,
                is_orchestrator=self.is_orchestrator,
                scope_mcp_servers=_load_scope_mcp_servers(self.scope),
            )

    def _codex_reasoning_effort(self) -> str:
        if self.is_orchestrator:
            return "high"
        return "high"

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
        if self.status == AgentStatus.RUNNING:
            self._pending_messages.append(message)
            self._log("user_message", message)
            self._log("status", f"message queued ({len(self._pending_messages)} pending)")
            return

        async with self._lifecycle_lock:
            if self._hibernate_task and not self._hibernate_task.done():
                self._hibernate_task.cancel()
                self._hibernate_task = None

            if self._hibernated:
                logger.info(f"[{self.name}] waking from hibernate")
                self._hibernated = False

            self.progress_pct = 0
            self.progress_status = ""
            self._log("user_message", message)

            if self.session_id and self._current_prompt and not self._prompt_injected:
                old_h = _prompt_hash(self.system_prompt)
                new_h = _prompt_hash(self._current_prompt)
                if old_h != new_h:
                    self._log("status", f"prompt updated: {old_h} → {new_h}")
                    message = f"[Orchestra platform note: your role instructions were refreshed by the server, not by another agent. This is legitimate.]\n{self._current_prompt}\n\n---\n\n{message}"
                    self._prompt_injected = True
                    self.system_prompt = self._current_prompt
                else:
                    self._prompt_injected = True

            if self.status == AgentStatus.IDLE:
                self._did_report = False
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

            if self.backend_type == "codex":
                self._listen_task = asyncio.create_task(self._codex_turn_loop())

    async def _ensure_backend(self):
        if self._backend is not None:
            return self._backend
        self._backend = self._make_backend()
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

    async def _claude_event_loop(self) -> None:
        logger.info(f"[{self.name}] claude event loop started")
        while True:
            try:
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
            except asyncio.CancelledError:
                logger.info(f"[{self.name}] claude event loop cancelled")
                return
            except Exception as e:
                import traceback
                tb = traceback.format_exc()
                logger.error(f"[{self.name}] claude event loop died: {e}\n{tb}")
                self._log("error", f"listener died (reconnecting): {e}")
                try:
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

    async def _codex_turn_loop(self) -> None:
        logger.info(f"[{self.name}] codex turn started")
        try:
            async for event in self._backend.events():
                self._last_msg_time = asyncio.get_event_loop().time()
                self._handle_event(event)
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.error(f"[{self.name}] codex turn error: {e}")
            self._log("error", f"codex turn error: {e}")

    # ── Unified event handler ──

    def _handle_event(self, event: AgentEvent) -> None:
        if event.type == "text":
            self._log("text", event.content)
            self._turn_logs.append(event.content)
        elif event.type == "tool_use":
            self._log("tool", event.content)
            short = event.content[:80]
            self._turn_logs.append(f"[tool] {short}")
            tool_name = event.metadata.get("tool_name", event.content)
            if "send_message" in tool_name or "mcp__orchestra__send_message" in tool_name:
                self._did_report = True
        elif event.type == "tool_result":
            self._log("tool_result", event.content)
            if "Command running in background" in event.content and "Output is being written to:" in event.content:
                m = re.search(r"Output is being written to:\s*(\S+)", event.content)
                if m:
                    self._bg_outputs.append(m.group(1))
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

    def _handle_turn_end(self, event: AgentEvent) -> None:
        meta = event.metadata
        self._turn_start = 0
        ok = meta.get("ok", True)
        sr = meta.get("stop_reason", "unknown")
        nt = meta.get("num_turns", 0)
        self._log("status", f"turn ended: ok={ok}, stop_reason={sr}, num_turns={nt}")

        sid = meta.get("session_id")
        if sid:
            self.session_id = sid
        self.cost_usd += meta.get("cost_usd", 0)

        ctx_pct = meta.get("context_pct", 0)
        ctx_tokens = meta.get("context_tokens", 0)
        max_tokens = meta.get("max_tokens", 200000)
        self._last_context = {
            "percentage": ctx_pct,
            "total_tokens": ctx_tokens,
            "max_tokens": max_tokens,
            "cache_hit": meta.get("cache_hit", 0),
            "cache_read": meta.get("cache_read", 0),
            "cache_create": meta.get("cache_create", 0),
        }

        if sr in ("error_max_turns", "max_turns") and ok:
            self._log("status", f"max_turns reached ({nt}), auto-continuing")
            asyncio.create_task(self._auto_continue())
            return

        self.status = AgentStatus.IDLE
        self._persist()

        if not self.is_orchestrator:
            asyncio.create_task(self._notify_scope_idle())

        if ctx_pct > 90 and not self.is_orchestrator and not getattr(self, "_compacting", False):
            self._log("status", f"auto-compact triggered ({ctx_pct}%)")
            asyncio.create_task(self._auto_compact())

        if self._bg_outputs:
            paths = list(self._bg_outputs)
            self._bg_outputs.clear()
            asyncio.create_task(self._poll_bg_outputs(paths))

        if self.on_idle and not self._did_report:
            last_texts = self._turn_logs[-5:] if self._turn_logs else []
            try:
                asyncio.create_task(self.on_idle(self.name, self.scope, last_texts))
            except Exception:
                pass

        if self._pending_messages:
            asyncio.create_task(self._flush_pending())
            return

        self._schedule_hibernate()

    async def _flush_pending(self) -> None:
        await asyncio.sleep(0.3)
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
                self._did_report = False
                self._turn_logs = []
                self._turn_start = asyncio.get_event_loop().time()
                self._last_msg_time = self._turn_start
                self.status = AgentStatus.RUNNING
                self._persist()
                backend = await self._ensure_backend()
                await backend.send(combined)
        except Exception as e:
            logger.error(f"[{self.name}] flush pending failed: {e}")
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
            if self._backend is None:
                return
            logger.info(f"[{self.name}] hibernating (idle {int(timeout)}s)")
            await self._disconnect_backend()
            self._hibernated = True

    # ── Background output polling ──

    async def _poll_bg_outputs(self, paths: list[str]) -> None:
        from pathlib import Path
        for path in paths:
            p = Path(path)
            for _ in range(120):
                await asyncio.sleep(5)
                if p.exists():
                    size = p.stat().st_size
                    await asyncio.sleep(2)
                    if p.stat().st_size == size:
                        try:
                            content = p.read_text()[-3000:]
                        except Exception:
                            content = "(could not read)"
                        self._log("status", f"background task finished: {p.name}")
                        await self.send(f"[Background task completed]\nOutput file: {path}\nLast output:\n{content}")
                        break
            else:
                self._log("status", f"background task timed out: {p.name}")

    def _on_task_done(self, task: asyncio.Task) -> None:
        try:
            exc = task.exception()
        except asyncio.CancelledError:
            return
        if exc:
            import traceback
            tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            logger.error(f"[{self.name}] listen task died with exception: {exc}\n{tb}")
            self.status = AgentStatus.IDLE
            self._log("error", f"listen task exception: {exc}")
            self._persist()
        else:
            logger.warning(f"[{self.name}] listen task exited without exception (silent death), status={self.status}")
            if self.status == AgentStatus.RUNNING:
                self._log("error", "listen task exited unexpectedly while RUNNING")
                self.status = AgentStatus.IDLE
                self._persist()

    async def _heartbeat_loop(self) -> None:
        HEARTBEAT_INTERVAL = 60
        NO_MSG_TIMEOUT = 600
        logger.info(f"[{self.name}] heartbeat started")
        while True:
            try:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
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
                elif self.status == AgentStatus.RUNNING and self._last_msg_time > 0:
                    silence = asyncio.get_event_loop().time() - self._last_msg_time
                    if silence > NO_MSG_TIMEOUT:
                        logger.warning(f"[{self.name}] heartbeat: {silence:.0f}s silence during RUNNING turn")
                        self._log("status", f"no messages for {silence:.0f}s during active turn (possible long thinking)")
            except asyncio.CancelledError:
                logger.info(f"[{self.name}] heartbeat cancelled")
                return
            except Exception as e:
                logger.error(f"[{self.name}] heartbeat error: {e}")

    # ── Session operations ──

    async def interrupt(self) -> None:
        if self._backend and self.status == AgentStatus.RUNNING:
            await self._backend.interrupt()
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
            return {"ok": False, "error": str(e), "before_pct": before_pct}
        finally:
            await backend.disconnect()
            self._backend = None

        summary = "".join(summary_parts).strip()
        if not summary:
            self._log("error", "compact returned empty summary")
            return {"ok": False, "error": "empty summary", "before_pct": before_pct}

        self.session_id = None
        self._persist()

        preamble = PREAMBLE.format(summary=summary)
        await self.send(preamble + "Acknowledge briefly.")

        for _ in range(60):
            await asyncio.sleep(1)
            if self.status == AgentStatus.IDLE and self._last_context.get("percentage", before_pct) < before_pct:
                break

        after_pct = self._last_context.get("percentage", 0)
        self._log("status", f"compact done: {before_pct}% → {after_pct}%")
        return {"ok": True, "before_pct": before_pct, "after_pct": after_pct, "summary_chars": len(summary), "summary": summary}

    async def _notify_scope_idle(self) -> None:
        try:
            from app.tg_bridge import check_scope_idle, _manager as tg_mgr
            if not tg_mgr:
                return
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

    async def _auto_compact(self) -> None:
        self._compacting = True
        await asyncio.sleep(2)
        try:
            await self.compact()
        except Exception as e:
            logger.warning(f"[{self.name}] auto-compact failed: {e}")
        finally:
            self._compacting = False

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
        await self._disconnect_backend()
        self._hibernated = False
        self.status = AgentStatus.IDLE
        self._persist()

    def _persist(self) -> None:
        asyncio.get_event_loop().run_in_executor(None, save_session, self._to_db_dict())

    def _log(self, type: str, content: str) -> None:
        asyncio.get_event_loop().run_in_executor(None, add_log, self.id, datetime.now(timezone.utc), type, content)

    def _to_db_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "scope": self.scope, "cwd": self.cwd,
            "model": self.model, "system_prompt": self.system_prompt,
            "status": self.status.value, "session_id": self.session_id,
            "cost_usd": self.cost_usd, "worktree_path": self.worktree_path,
            "branch": self.branch, "is_orchestrator": self.is_orchestrator,
            "color": self.color, "created_at": self.created_at.isoformat(),
            "finished_at": None,
            "context_pct": self._last_context.get("percentage", 0),
            "context_tokens": self._last_context.get("total_tokens", 0),
            "progress_pct": self.progress_pct,
            "progress_status": self.progress_status,
            "backend_type": self.backend_type,
            "task_id": self.task_id,
            "description": self.description,
        }

    async def get_context(self) -> dict:
        return self._last_context

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "scope": self.scope,
            "status": self.status.value, "model": self.model,
            "cost_usd": round(self.cost_usd, 4), "branch": self.branch,
            "is_orchestrator": self.is_orchestrator, "color": self.color,
            "created_at": self.created_at.isoformat(),
            "context_pct": self._last_context.get("percentage", 0),
            "progress_pct": self.progress_pct,
            "progress_status": self.progress_status,
            "backend_type": self.backend_type,
            "hibernated": self._hibernated,
            "task_id": self.task_id,
            "description": self.description,
        }
