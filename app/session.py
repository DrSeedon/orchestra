"""AgentSession — single SDK wrapper for both orchestrator and worker sessions."""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
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
        subtype="result",
        duration_ms=0,
        duration_api_ms=0,
        is_error=False,
        num_turns=1,
        session_id=session_id,
        total_cost_usd=cost,
    )


def _create_client(model: str, cwd: str, system_prompt: str,
                   session_id: str | None, auto_approve,
                   mcp_servers: dict | None = None) -> ClaudeSDKClient:
    options = ClaudeAgentOptions(
        model=model,
        cwd=cwd,
        permission_mode="default",
        can_use_tool=auto_approve,
        system_prompt=system_prompt,
        include_partial_messages=True,
    )
    if session_id:
        options.resume = session_id
    if mcp_servers:
        options.mcp_servers = mcp_servers
    return ClaudeSDKClient(options=options)


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
    mcp_servers: dict = field(default_factory=dict, repr=False)

    _client: Optional[ClaudeSDKClient] = field(default=None, repr=False)
    _turn_task: Optional[asyncio.Task] = field(default=None, repr=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    _pending: list = field(default_factory=list, repr=False)
    _debounce_task: Optional[asyncio.Task] = field(default=None, repr=False)
    _is_connected: bool = field(default=False, repr=False)
    debounce_sec: float = 2.0

    async def start(self, initial_message: str | None = None) -> None:
        self._client = _create_client(
            self.model, self.cwd,
            self.system_prompt, self.session_id, self._auto_approve,
            self.mcp_servers or None,
        )
        if initial_message:
            self.status = AgentStatus.RUNNING
            self._persist()
            self._turn_task = asyncio.create_task(self._run_turn(initial_message))
        else:
            await self._client.connect()
            self._is_connected = True
            self.status = AgentStatus.IDLE
            self._persist()

    async def send(self, message: str) -> None:
        if self.status in (AgentStatus.STOPPED, AgentStatus.ERROR):
            raise RuntimeError(f"cannot send to session in {self.status} state")

        if self.status == AgentStatus.RUNNING:
            self._log("user_message", message)
            if self._client and self._is_connected:
                try:
                    await self._client.query(message)
                except Exception as e:
                    logger.warning(f"inject failed: {e}")
            return

        self._pending.append(message)
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
        if self._client:
            try:
                await self._client.disconnect()
            except Exception:
                pass
            self._is_connected = False
        self._client = _create_client(
            self.model, self.cwd,
            self.system_prompt, self.session_id, self._auto_approve,
            self.mcp_servers or None,
        )
        self.status = AgentStatus.RUNNING
        self._turn_task = asyncio.create_task(self._run_turn(combined))

    async def _run_turn(self, message: str) -> None:
        async with self._lock:
            try:
                self._persist()
                self._log("user_message", message)
                if not self._client_connected():
                    await self._client.connect()
                    self._is_connected = True
                await self._client.query(message)
                await self._listen_loop()
            except Exception as e:
                self.status = AgentStatus.ERROR
                self._log("error", str(e))
                self._persist()
                raise

    async def _listen_loop(self) -> None:
        async for msg in self._client.receive_messages():
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock) and block.text:
                        self._log("text", block.text)
                    elif isinstance(block, ToolUseBlock):
                        self._log("tool", f"{block.name}: {str(block.input)[:200]}")
            elif isinstance(msg, ResultMessage):
                if msg.session_id:
                    self.session_id = msg.session_id
                self.cost_usd += getattr(msg, "total_cost_usd", 0) or 0
                self.status = AgentStatus.IDLE
                self._persist()
                break

    async def interrupt(self) -> None:
        if self._client:
            await self._client.interrupt()
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
        if self._client:
            try:
                await self._client.disconnect()
            except Exception:
                pass
            self._is_connected = False
        self.status = AgentStatus.STOPPED
        self._persist()
        if self.worktree_path:
            from app.workspace import remove_worktree
            remove_worktree(self.cwd, self.worktree_path)

    def _client_connected(self) -> bool:
        return self._client is not None and self._is_connected

    def _persist(self) -> None:
        save_session(self._to_db_dict())

    def _log(self, type: str, content: str) -> None:
        add_log(self.id, datetime.now(timezone.utc), type, content)

    def _to_db_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "scope": self.scope,
            "cwd": self.cwd,
            "model": self.model,
            "system_prompt": self.system_prompt,
            "status": self.status.value,
            "session_id": self.session_id,
            "cost_usd": self.cost_usd,
            "worktree_path": self.worktree_path,
            "branch": self.branch,
            "is_orchestrator": self.is_orchestrator,
            "created_at": self.created_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat()
                if self.status in (AgentStatus.STOPPED, AgentStatus.ERROR) else None,
        }

    async def get_context(self) -> dict:
        if self._client and self._is_connected:
            try:
                usage = await self._client.get_context_usage()
                return {"percentage": usage.get("percentage", 0), "total_tokens": usage.get("totalTokens", 0), "max_tokens": usage.get("maxTokens", 0)}
            except Exception:
                pass
        return {"percentage": 0, "total_tokens": 0, "max_tokens": 0}

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "scope": self.scope,
            "status": self.status.value,
            "model": self.model,
            "cost_usd": round(self.cost_usd, 4),
            "branch": self.branch,
            "is_orchestrator": self.is_orchestrator,
            "created_at": self.created_at.isoformat(),
        }

    @staticmethod
    async def _auto_approve(tool_name, tool_input, _context=None):
        logger.info(f"auto-approve: {tool_name}")
        return PermissionResultAllow(updated_input=tool_input)
