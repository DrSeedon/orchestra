"""AgentSession — SDK wrapper, persistent client with mid-turn injection."""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from claude_agent_sdk import (
    ClaudeSDKClient,
    ClaudeAgentOptions,
    AssistantMessage,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
    PermissionResultAllow,
    PermissionResultDeny,
    TaskStartedMessage,
    TaskProgressMessage,
    TaskNotificationMessage,
)
from claude_agent_sdk.types import (
    ToolResultBlock, ServerToolResultBlock, UserMessage,
)

from app.db import save_session, add_log

logger = logging.getLogger(__name__)


def _prompt_hash(text: str) -> str:
    import hashlib
    return hashlib.md5(text.encode()).hexdigest()[:8]


class AgentStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"


_BLOCKED_TOOLS = {"AskUserQuestion"}


async def _auto_approve(tool_name, tool_input, _context=None):
    if tool_name in _BLOCKED_TOOLS:
        return PermissionResultDeny(message=f"{tool_name} is not available in Orchestra. Make decisions yourself or ask via send_message.")
    if isinstance(tool_input, dict) and tool_input.get("run_in_background"):
        return PermissionResultDeny(message="run_in_background is disabled in Orchestra — background processes are killed when your turn ends. Run synchronously instead.")
    return PermissionResultAllow(updated_input=tool_input)


def _extract_tool_result(block) -> str:
    import json as _json
    raw = getattr(block, 'content', '')
    if isinstance(raw, list):
        parts = [item.get('text', str(item)) if isinstance(item, dict) else str(item) for item in raw]
        text = '\n'.join(parts)
    elif isinstance(raw, dict):
        text = raw.get('text', str(raw))
    else:
        text = str(raw)
    try:
        parsed = _json.loads(text)
        if isinstance(parsed, dict) and 'result' in parsed:
            return str(parsed['result'])
    except (ValueError, TypeError):
        pass
    return text


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

    progress_pct: int = 0
    progress_status: str = ""

    total_turns: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tool_calls: int = 0

    _client: Optional[ClaudeSDKClient] = field(default=None, repr=False)
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

    TURN_TIMEOUT = 600

    def _make_client(self) -> ClaudeSDKClient:
        import shutil
        cli = shutil.which("claude") or "/home/maxim/.local/bin/claude"
        options = ClaudeAgentOptions(
            model=self.model, cwd=self.cwd, cli_path=cli,
            permission_mode="default", can_use_tool=_auto_approve,
            include_partial_messages=False, max_turns=200,
            max_buffer_size=50 * 1024 * 1024,
            env={"HTTPS_PROXY": "http://127.0.0.1:12334", "HTTP_PROXY": "http://127.0.0.1:12334", "NO_PROXY": "localhost,127.0.0.1"},
        )
        if self.session_id:
            options.resume = self.session_id
        else:
            options.system_prompt = {"type": "preset", "preset": "claude_code", "append": self.system_prompt}
        if self.mcp_servers:
            options.mcp_servers = self.mcp_servers
        return ClaudeSDKClient(options=options)

    async def start(self, initial_message: str | None = None) -> None:
        if initial_message:
            await self.send(initial_message)
        else:
            self.status = AgentStatus.IDLE
            self._persist()

    async def send(self, message: str) -> None:
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
        was_running = self.status == AgentStatus.RUNNING
        if was_running:
            self._pending_messages.append(message)
            self._log("status", f"queued mid-turn message ({len(self._pending_messages)} pending)")
        if self.status == AgentStatus.IDLE:
            self._did_report = False
            self._turn_logs = []
            self._turn_start = asyncio.get_event_loop().time()
            self.status = AgentStatus.RUNNING
            self._persist()
        try:
            client = await self._ensure_client()
        except Exception:
            self.status = AgentStatus.IDLE
            self._persist()
            raise
        await client.query(message)

    async def _ensure_client(self) -> ClaudeSDKClient:
        if self._client is not None:
            return self._client
        client = self._make_client()
        try:
            await asyncio.wait_for(client.connect(), timeout=60)
        except Exception as e:
            logger.error(f"[{self.name}] client connect failed: {e}")
            self._log("error", f"connect failed: {e}")
            raise
        self._client = client
        self._listen_task = asyncio.create_task(self._persistent_listen())
        self._listen_task.add_done_callback(self._on_task_done)
        if self._heartbeat_task is None or self._heartbeat_task.done():
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        return self._client

    async def _persistent_listen(self) -> None:
        logger.info(f"[{self.name}] persistent listener started")
        while True:
            try:
                async for msg in self._client.receive_messages():
                    self._last_msg_time = asyncio.get_event_loop().time()
                    if self._turn_start and (asyncio.get_event_loop().time() - self._turn_start) > self.TURN_TIMEOUT:
                        logger.error(f"[{self.name}] turn timeout")
                        self._log("error", f"Turn timeout ({self.TURN_TIMEOUT}s)")
                        self._turn_start = 0
                        self.status = AgentStatus.IDLE
                        self._persist()
                        await self.send("[system] Turn timed out. Continue where you left off.")
                        continue
                    if isinstance(msg, AssistantMessage):
                        for block in msg.content:
                            if isinstance(block, TextBlock) and block.text:
                                self._log("text", block.text)
                                self._turn_logs.append(block.text)
                            elif isinstance(block, ToolUseBlock):
                                self.total_tool_calls += 1
                                import json as _j
                                try:
                                    inp = _j.dumps(block.input, ensure_ascii=False, indent=2)
                                except Exception:
                                    inp = str(block.input)
                                self._log("tool", f"{block.name}: {inp}")
                                short_name = block.name.split('__')[-1] if '__' in block.name else block.name
                                short_inp = str(block.input)[:80]
                                self._turn_logs.append(f"[tool] {short_name}: {short_inp}")
                                if block.name in ("mcp__orchestra__send_message", "send_message"):
                                    self._did_report = True
                            elif isinstance(block, (ToolResultBlock, ServerToolResultBlock)):
                                result_text = _extract_tool_result(block)
                                self._log("tool_result", result_text)
                                if "Command running in background" in result_text and "Output is being written to:" in result_text:
                                    import re
                                    m = re.search(r"Output is being written to:\s*(\S+)", result_text)
                                    if m:
                                        self._bg_outputs.append(m.group(1))
                    elif isinstance(msg, UserMessage):
                        if hasattr(msg, 'content') and isinstance(msg.content, list):
                            for block in msg.content:
                                if isinstance(block, (ToolResultBlock, ServerToolResultBlock)):
                                    self._log("tool_result", _extract_tool_result(block))
                    elif isinstance(msg, TaskStartedMessage):
                        desc = getattr(msg, "description", "") or ""
                        task_type = getattr(msg, "task_type", "") or ""
                        task_id = getattr(msg, "task_id", "") or ""
                        self._log("subagent_start", f"{desc} | type={task_type} | id={task_id}")
                    elif isinstance(msg, TaskProgressMessage):
                        desc = getattr(msg, "description", "") or ""
                        last_tool = getattr(msg, "last_tool_name", "") or ""
                        usage = getattr(msg, "usage", None)
                        tokens = usage.total_tokens if usage and hasattr(usage, "total_tokens") else 0
                        self._log("subagent_progress", f"{desc} | tool={last_tool} | tokens={tokens}")
                    elif isinstance(msg, TaskNotificationMessage):
                        desc = getattr(msg, "description", "") or ""
                        status = getattr(msg, "status", "") or ""
                        summary = getattr(msg, "summary", "") or ""
                        self._log("subagent_end", f"{desc} | status={status} | {summary[:500]}")
                    elif isinstance(msg, ResultMessage):
                        self._turn_start = 0
                        sr = getattr(msg, "stop_reason", None) or "unknown"
                        nt = getattr(msg, "num_turns", 0) or 0
                        self._log("status", f"turn ended: stop_reason={sr}, num_turns={nt}")
                        if msg.session_id:
                            self.session_id = msg.session_id
                        self.cost_usd += getattr(msg, "total_cost_usd", 0) or 0
                        self.total_turns += getattr(msg, "num_turns", 0) or 0
                        usage = getattr(msg, "usage", None)
                        if usage and isinstance(usage, dict):
                            iters = usage.get("iterations", [])
                            last = iters[-1] if iters else usage
                            cache_create = (last.get("cache_creation_input_tokens", 0) or 0)
                            cache_read = (last.get("cache_read_input_tokens", 0) or 0)
                            input_t = (last.get("input_tokens", 0) or 0) + cache_create + cache_read
                            output_t = (last.get("output_tokens", 0) or 0)
                            cache_total = cache_create + cache_read
                            self.total_input_tokens += input_t
                            self.total_output_tokens += output_t
                            from app.models import CONTEXT_LIMITS
                            max_t = CONTEXT_LIMITS.get(self.model, 200000)
                            self._last_context = {
                                "percentage": int(input_t * 100 / max_t) if max_t else 0,
                                "total_tokens": input_t, "max_tokens": max_t,
                                "cache_hit": int(cache_read * 100 / cache_total) if cache_total else 0,
                                "cache_read": cache_read, "cache_create": cache_create,
                            }
                        if self._pending_messages:
                            combined = "\n\n".join(
                                f"[system] The user sent a new message while you were working:\n{m}"
                                for m in self._pending_messages
                            )
                            self._pending_messages.clear()
                            self._log("status", f"flushing {len(self._pending_messages) or 'queued'} pending messages")
                            self._turn_start = asyncio.get_event_loop().time()
                            await self._client.query(combined + "\n\nIMPORTANT: After completing your current task, you MUST address the user's message above. Do not ignore it.")
                            continue
                        if self._turn_start:
                            elapsed = asyncio.get_event_loop().time() - self._turn_start
                            if elapsed < 3:
                                await asyncio.sleep(3 - elapsed)
                        self.status = AgentStatus.IDLE
                        self._persist()
                        if not self.is_orchestrator:
                            asyncio.create_task(self._notify_scope_idle())
                        if self._last_context.get("percentage", 0) > 90 and not self.is_orchestrator and not getattr(self, "_compacting", False):
                            self._log("status", f"auto-compact triggered ({self._last_context['percentage']}%)")
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
            except asyncio.CancelledError:
                logger.info(f"[{self.name}] persistent listener cancelled")
                self._client = None
                return
            except Exception as e:
                import traceback
                tb = traceback.format_exc()
                logger.error(f"[{self.name}] persistent listener died: {e}\n{tb}")
                self._log("error", f"listener died (reconnecting): {e}")
                try:
                    if self._client:
                        await self._client.disconnect()
                except Exception:
                    pass
                self._client = None
                await asyncio.sleep(2)
                try:
                    self._client = self._make_client()
                    await asyncio.wait_for(self._client.connect(), timeout=60)
                    logger.info(f"[{self.name}] listener reconnected after error")
                    self._log("status", "listener reconnected")
                    if self.status == AgentStatus.RUNNING:
                        await self._client.query("[system] Connection was restored after interruption. Continue your work.")
                    continue
                except Exception as re:
                    logger.error(f"[{self.name}] listener reconnect failed: {re}")
                    self._log("error", f"listener reconnect failed: {re}")
                    self._client = None
                    if self.status == AgentStatus.RUNNING:
                        self.status = AgentStatus.IDLE
                        self._persist()
                    return

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
        NO_MSG_TIMEOUT = 300
        logger.info(f"[{self.name}] heartbeat started")
        while True:
            try:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                if self._client is None:
                    continue
                task_dead = self._listen_task is None or self._listen_task.done()
                if task_dead and self.status == AgentStatus.RUNNING:
                    logger.warning(f"[{self.name}] heartbeat: listener dead but status=RUNNING — reconnecting")
                    self._log("error", "heartbeat detected dead listener, reconnecting")
                    try:
                        self._client = self._make_client()
                        await asyncio.wait_for(self._client.connect(), timeout=60)
                        self._listen_task = asyncio.create_task(self._persistent_listen())
                        self._listen_task.add_done_callback(self._on_task_done)
                        await self._client.query("[system] Connection was restored after interruption. Continue your work.")
                        logger.info(f"[{self.name}] heartbeat reconnect OK")
                    except Exception as e:
                        logger.error(f"[{self.name}] heartbeat reconnect failed: {e}")
                        self._log("error", f"heartbeat reconnect failed: {e}")
                        self._client = None
                        self.status = AgentStatus.IDLE
                        self._persist()
                elif self.status == AgentStatus.RUNNING and self._last_msg_time > 0:
                    silence = asyncio.get_event_loop().time() - self._last_msg_time
                    if silence > NO_MSG_TIMEOUT:
                        logger.warning(f"[{self.name}] heartbeat: {silence:.0f}s silence during RUNNING turn")
                        self._log("error", f"no messages for {silence:.0f}s during active turn (possible hang)")
            except asyncio.CancelledError:
                logger.info(f"[{self.name}] heartbeat cancelled")
                return
            except Exception as e:
                logger.error(f"[{self.name}] heartbeat error: {e}")

    async def interrupt(self) -> None:
        if self._client and self.status == AgentStatus.RUNNING:
            try:
                await self._client.interrupt()
            except Exception as e:
                logger.warning(f"[{self.name}] interrupt failed: {e}")
        self.status = AgentStatus.IDLE
        self._log("status", "interrupted")
        self._persist()

    async def compact(self) -> dict:
        COMPACT_PROMPT = (
            "[SYSTEM: Context compaction requested]\n\n"
            "Summarize our conversation so far. Output plain text, ~800 tokens max:\n\n"
            "INTENT: What you are working on (1-2 sentences).\n"
            "DECISIONS: Key decisions made (bullet points).\n"
            "FILES: Files touched with brief notes (path — what was done).\n"
            "PENDING: Open questions, TODOs, next steps.\n"
            "RECENT: Last 3-5 exchanges for continuity.\n\n"
            "Output ONLY the summary. No commentary."
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
        client = self._client or self._make_client()
        need_connect = self._client is None
        try:
            if need_connect:
                await asyncio.wait_for(client.connect(), timeout=60)
            await client.query(COMPACT_PROMPT)
            async for msg in client.receive_messages():
                if isinstance(msg, AssistantMessage):
                    for block in msg.content:
                        if isinstance(block, TextBlock) and block.text:
                            summary_parts.append(block.text)
                elif isinstance(msg, ResultMessage):
                    if msg.session_id:
                        self.session_id = msg.session_id
                    break
        except Exception as e:
            self._log("error", f"compact failed: {e}")
            return {"ok": False, "error": str(e), "before_pct": before_pct}
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass
            self._client = None

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
        old_model = self.model
        if old_model == new_model:
            return {"ok": True, "model": new_model, "changed": False}
        if self.status == AgentStatus.RUNNING:
            return {"ok": False, "error": "cannot change model while running"}
        self._log("status", f"model change: {old_model} → {new_model}")
        await self._disconnect_client()
        self.model = new_model
        self._persist()
        return {"ok": True, "model": new_model, "old_model": old_model, "changed": True}

    async def _disconnect_client(self) -> None:
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except (asyncio.CancelledError, Exception):
                pass
            self._heartbeat_task = None
        if self._listen_task and not self._listen_task.done():
            self._listen_task.cancel()
            try:
                await self._listen_task
            except (asyncio.CancelledError, Exception):
                pass
        if self._client:
            try:
                await self._client.disconnect()
            except Exception:
                pass
            self._client = None

    async def stop(self) -> None:
        await self._disconnect_client()
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
            "total_turns": self.total_turns,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_tool_calls": self.total_tool_calls,
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
            "total_turns": self.total_turns,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_tool_calls": self.total_tool_calls,
        }
