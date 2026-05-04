"""AgentSession — SDK wrapper, one client per turn (connect→query→receive→disconnect)."""

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
)
from claude_agent_sdk.types import (
    StreamEvent, ToolResultBlock, ServerToolResultBlock, UserMessage,
)

from app.db import save_session, add_log

logger = logging.getLogger(__name__)


class AgentStatus(str, Enum):
    STARTING = "starting"
    RUNNING = "running"
    IDLE = "idle"
    STOPPED = "stopped"
    ERROR = "error"


def _make_result_message(session_id: str = "", cost: float = 0.0) -> ResultMessage:
    return ResultMessage(
        subtype="result", duration_ms=0, duration_api_ms=0,
        is_error=False, num_turns=1, session_id=session_id, total_cost_usd=cost,
    )


async def _auto_approve(tool_name, tool_input, _context=None):
    return PermissionResultAllow(updated_input=tool_input)


def _extract_tool_result(block) -> str:
    import json as _json
    raw = getattr(block, 'content', '')
    if isinstance(raw, list):
        parts = []
        for item in raw:
            if isinstance(item, dict):
                parts.append(item.get('text', str(item)))
            else:
                parts.append(str(item))
        text = '\n'.join(parts)
    elif isinstance(raw, dict):
        text = raw.get('text', str(raw))
    else:
        text = str(raw)
    try:
        parsed = _json.loads(text)
        if isinstance(parsed, dict) and 'result' in parsed:
            return str(parsed['result'])[:500]
    except (ValueError, TypeError):
        pass
    return text[:500]


@dataclass
class AgentSession:
    id: str
    name: str
    scope: str
    cwd: str
    model: str = "claude-sonnet-4-6"
    system_prompt: str = ""
    status: AgentStatus = AgentStatus.STARTING
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

    TURN_TIMEOUT = 300

    def _make_client(self) -> ClaudeSDKClient:
        import shutil
        cli = shutil.which("claude") or "/home/maxim/.local/bin/claude"
        options = ClaudeAgentOptions(
            model=self.model,
            cwd=self.cwd,
            cli_path=cli,
            permission_mode="default",
            can_use_tool=_auto_approve,
            system_prompt=self.system_prompt,
            include_partial_messages=False,
            max_turns=25,
        )
        if self.session_id:
            options.resume = self.session_id
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
        if self.status in (AgentStatus.STOPPED, AgentStatus.ERROR):
            raise RuntimeError(f"cannot send to session in {self.status} state")
        self._log("user_message", message)
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
        """One turn = create client → connect → query → receive → disconnect."""
        client = self._make_client()
        try:
            self._persist()
            await asyncio.wait_for(client.connect(), timeout=60)
            await client.query(message)
            await asyncio.wait_for(self._listen(client), timeout=self.TURN_TIMEOUT)
        except asyncio.TimeoutError:
            logger.error(f"[{self.name}] turn timeout")
            self._log("error", f"Turn timeout ({self.TURN_TIMEOUT}s)")
            self.status = AgentStatus.ERROR
            self._persist()
        except Exception as e:
            logger.error(f"[{self.name}] turn error: {e}")
            self._log("error", str(e))
            self.status = AgentStatus.ERROR
            self._persist()
        finally:
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
                    elif isinstance(block, ToolUseBlock):
                        self._log("tool", f"{block.name}: {str(block.input)[:200]}")
                    elif isinstance(block, (ToolResultBlock, ServerToolResultBlock)):
                        self._log("tool_result", _extract_tool_result(block))
            elif isinstance(msg, UserMessage):
                if hasattr(msg, 'content') and isinstance(msg.content, list):
                    for block in msg.content:
                        if isinstance(block, (ToolResultBlock, ServerToolResultBlock)):
                            self._log("tool_result", _extract_tool_result(block))
            elif isinstance(msg, ResultMessage):
                if msg.session_id:
                    self.session_id = msg.session_id
                self.cost_usd += getattr(msg, "total_cost_usd", 0) or 0
                self.status = AgentStatus.IDLE
                self._persist()
                if self._pending:
                    self._arm_debounce()
                break

    def _on_task_done(self, task: asyncio.Task) -> None:
        try:
            exc = task.exception()
        except asyncio.CancelledError:
            return
        if exc:
            logger.error(f"[{self.name}] task error: {exc}")
            self.status = AgentStatus.ERROR
            self._log("error", str(exc))
            self._persist()
            if self.on_error:
                self.on_error(self.id)

    async def interrupt(self) -> None:
        if self._turn_task and not self._turn_task.done():
            self._turn_task.cancel()
            self._log("status", "interrupted")

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
        self.status = AgentStatus.STOPPED
        if not self.is_orchestrator:
            self.name = f"{self.name}-{self.id[:6]}"
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
            "finished_at": datetime.now(timezone.utc).isoformat()
                if self.status in (AgentStatus.STOPPED, AgentStatus.ERROR) else None,
        }

    async def get_context(self) -> dict:
        return {"percentage": 0, "total_tokens": 0, "max_tokens": 0}

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "scope": self.scope,
            "status": self.status.value, "model": self.model,
            "cost_usd": round(self.cost_usd, 4), "branch": self.branch,
            "is_orchestrator": self.is_orchestrator, "color": self.color,
            "created_at": self.created_at.isoformat(),
        }
