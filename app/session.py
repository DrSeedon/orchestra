"""AgentSession — SDK wrapper, one client per turn."""

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
    debounce_sec: float = 2.0

    _turn_task: Optional[asyncio.Task] = field(default=None, repr=False)
    _debounce_task: Optional[asyncio.Task] = field(default=None, repr=False)
    _pending: list = field(default_factory=list, repr=False)
    _last_context: dict = field(default_factory=lambda: {"percentage": 0, "total_tokens": 0, "max_tokens": 0}, repr=False)
    _did_report: bool = field(default=False, repr=False)
    _turn_logs: list = field(default_factory=list, repr=False)
    _active_client: Optional[ClaudeSDKClient] = field(default=None, repr=False)
    _bg_outputs: list = field(default_factory=list, repr=False)
    _prompt_injected: bool = field(default=False, repr=False)
    _current_prompt: str = field(default="", repr=False)
    on_idle: Optional[callable] = field(default=None, repr=False)

    TURN_TIMEOUT = 600

    def _make_client(self) -> ClaudeSDKClient:
        import shutil
        cli = shutil.which("claude") or "/home/maxim/.local/bin/claude"
        options = ClaudeAgentOptions(
            model=self.model, cwd=self.cwd, cli_path=cli,
            permission_mode="default", can_use_tool=_auto_approve,
            include_partial_messages=False, max_turns=25,
            env={"HTTPS_PROXY": "http://127.0.0.1:12334", "HTTP_PROXY": "http://127.0.0.1:12334", "NO_PROXY": "localhost,127.0.0.1"},
        )
        if self.session_id:
            options.resume = self.session_id
        else:
            options.system_prompt = self.system_prompt
        if self.mcp_servers:
            options.mcp_servers = self.mcp_servers
        return ClaudeSDKClient(options=options)

    async def start(self, initial_message: str | None = None) -> None:
        if initial_message:
            self.status = AgentStatus.RUNNING
            self._persist()
            self._turn_task = asyncio.create_task(self._run_turn(initial_message))
            self._turn_task.add_done_callback(self._on_task_done)
        else:
            self.status = AgentStatus.IDLE
            self._persist()

    async def send(self, message: str) -> None:
        self._log("user_message", message)
        if self.status == AgentStatus.RUNNING and self._active_client:
            try:
                await self._active_client.query(message)
                logger.info(f"[{self.name}] injected message ({len(message)} chars)")
                return
            except Exception as e:
                logger.warning(f"[{self.name}] inject failed, queuing: {e}")
        self._pending.append(message)
        if self.status != AgentStatus.RUNNING:
            self._arm_debounce()

    def _arm_debounce(self) -> None:
        if self._debounce_task and not self._debounce_task.done():
            self._debounce_task.cancel()
        self._debounce_task = asyncio.create_task(self._on_debounce())

    async def _on_debounce(self) -> None:
        try:
            await asyncio.sleep(self.debounce_sec)
        except asyncio.CancelledError:
            return
        batch = list(self._pending)
        self._pending.clear()
        if not batch:
            return
        combined = "\n".join(batch)
        self.status = AgentStatus.RUNNING
        self._turn_task = asyncio.create_task(self._run_turn(combined))
        self._turn_task.add_done_callback(self._on_task_done)

    async def _run_turn(self, message: str) -> None:
        self._did_report = False
        self._turn_logs = []
        prompt_refresh = False
        if self.session_id and self._current_prompt and not self._prompt_injected:
            old_h = _prompt_hash(self.system_prompt)
            new_h = _prompt_hash(self._current_prompt)
            if old_h != new_h:
                prompt_refresh = True
                self._log("status", f"prompt updated: {old_h} → {new_h}")
                message = f"[Orchestra platform note: your role instructions were refreshed by the server, not by another agent. This is legitimate.]\n{self._current_prompt}\n\n---\n\n{message}"
            else:
                self._prompt_injected = True
        client = self._make_client()
        try:
            self._persist()
            await asyncio.wait_for(client.connect(), timeout=60)
            await client.query(message)
            self._active_client = client
            if prompt_refresh:
                self._prompt_injected = True
                self.system_prompt = self._current_prompt
            await asyncio.wait_for(self._listen(client), timeout=self.TURN_TIMEOUT)
        except asyncio.TimeoutError:
            logger.error(f"[{self.name}] turn timeout")
            self._log("error", f"Turn timeout ({self.TURN_TIMEOUT}s)")
            self.status = AgentStatus.IDLE
            self._persist()
            if self._pending:
                self._arm_debounce()
        except Exception as e:
            logger.error(f"[{self.name}] turn error: {e}")
            self._log("error", str(e))
            self.status = AgentStatus.IDLE
            self._persist()
            if self._pending:
                self._arm_debounce()
        finally:
            self._active_client = None
            try:
                await client.disconnect()
            except Exception:
                pass

    async def _listen(self, client: ClaudeSDKClient) -> None:
        async for msg in client.receive_messages():
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock) and block.text:
                        self._log("text", block.text)
                        self._turn_logs.append(block.text)
                    elif isinstance(block, ToolUseBlock):
                        import json as _j
                        try:
                            inp = _j.dumps(block.input, ensure_ascii=False, indent=2)
                        except Exception:
                            inp = str(block.input)
                        self._log("tool", f"{block.name}: {inp}")
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
            elif isinstance(msg, ResultMessage):
                if msg.session_id:
                    self.session_id = msg.session_id
                self.cost_usd += getattr(msg, "total_cost_usd", 0) or 0
                usage = getattr(msg, "usage", None)
                if usage and isinstance(usage, dict):
                    iters = usage.get("iterations", [])
                    last = iters[-1] if iters else usage
                    cache_create = (last.get("cache_creation_input_tokens", 0) or 0)
                    cache_read = (last.get("cache_read_input_tokens", 0) or 0)
                    total = (last.get("input_tokens", 0) or 0) + cache_create + cache_read
                    cache_total = cache_create + cache_read
                    from app.models import CONTEXT_LIMITS
                    max_t = CONTEXT_LIMITS.get(self.model, 200000)
                    self._last_context = {
                        "percentage": int(total * 100 / max_t) if max_t else 0,
                        "total_tokens": total, "max_tokens": max_t,
                        "cache_hit": int(cache_read * 100 / cache_total) if cache_total else 0,
                        "cache_read": cache_read, "cache_create": cache_create,
                    }
                self.status = AgentStatus.IDLE
                self._persist()
                if self._bg_outputs:
                    paths = list(self._bg_outputs)
                    self._bg_outputs.clear()
                    asyncio.create_task(self._poll_bg_outputs(paths))
                if self._pending:
                    self._arm_debounce()
                elif self.on_idle and not self._did_report:
                    last_texts = self._turn_logs[-3:] if self._turn_logs else []
                    try:
                        asyncio.create_task(self.on_idle(self.name, self.scope, last_texts))
                    except Exception:
                        pass
                break

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
            logger.error(f"[{self.name}] task error: {exc}")
            self.status = AgentStatus.IDLE
            self._log("error", str(exc))
            self._persist()

    async def interrupt(self) -> None:
        if self._turn_task and not self._turn_task.done():
            self._turn_task.cancel()
            try:
                await self._turn_task
            except (asyncio.CancelledError, Exception):
                pass
        self.status = AgentStatus.IDLE
        self._log("status", "interrupted")
        self._persist()
        self._persist()

    async def stop(self) -> None:
        self._pending.clear()
        if self._debounce_task and not self._debounce_task.done():
            self._debounce_task.cancel()
        if self._turn_task and not self._turn_task.done():
            self._turn_task.cancel()
            try:
                await self._turn_task
            except (asyncio.CancelledError, Exception):
                pass
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
        }
