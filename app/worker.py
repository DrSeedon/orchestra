"""Worker — one Claude Code agent session in an isolated git worktree."""

import asyncio
import logging
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
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

logger = logging.getLogger(__name__)


class WorkerStatus(str, Enum):
    PENDING = "pending"
    SPAWNING = "spawning"
    WORKING = "working"
    IDLE = "idle"
    DONE = "done"
    ERROR = "error"
    KILLED = "killed"


@dataclass
class WorkerLog:
    ts: datetime
    type: str  # text | tool | error | status
    content: str


@dataclass
class Worker:
    name: str
    task: str
    repo_path: str
    branch: str = ""
    model: str = "claude-sonnet-4-6"
    system_prompt: str = ""
    status: WorkerStatus = WorkerStatus.PENDING
    worktree_path: str = ""
    session_id: Optional[str] = None
    logs: list[WorkerLog] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    cost_usd: float = 0.0
    context_pct: float = 0.0
    _client: Optional[ClaudeSDKClient] = field(default=None, repr=False)
    _task: Optional[asyncio.Task] = field(default=None, repr=False)

    def _log(self, type: str, content: str):
        self.logs.append(WorkerLog(ts=datetime.utcnow(), type=type, content=content))
        if len(self.logs) > 500:
            self.logs = self.logs[-300:]

    def _setup_worktree(self):
        wt_base = Path(self.repo_path) / "workers"
        wt_base.mkdir(exist_ok=True)
        self.worktree_path = str(wt_base / self.name)
        self.branch = f"feat/{self.name}"

        if Path(self.worktree_path).exists():
            subprocess.run(["git", "worktree", "remove", self.worktree_path, "--force"],
                           cwd=self.repo_path, capture_output=True)

        result = subprocess.run(
            ["git", "worktree", "add", self.worktree_path, "-b", self.branch],
            cwd=self.repo_path, capture_output=True, text=True,
        )
        if result.returncode != 0:
            subprocess.run(
                ["git", "worktree", "add", self.worktree_path, self.branch],
                cwd=self.repo_path, capture_output=True, text=True,
            )
        self._log("status", f"worktree created: {self.worktree_path}")

    async def spawn(self):
        self.status = WorkerStatus.SPAWNING
        self._log("status", "spawning")

        self._setup_worktree()

        options = ClaudeAgentOptions(
            model=f"{self.model}[1m]",
            cwd=self.worktree_path,
            max_turns=50,
            permission_mode="default",
            can_use_tool=self._auto_approve,
            include_partial_messages=True,
        )
        if self.system_prompt:
            options.system_prompt = self.system_prompt
        if self.session_id:
            options.resume = self.session_id

        self._client = ClaudeSDKClient(options=options)
        await self._client.connect()
        self.status = WorkerStatus.WORKING
        self._log("status", "connected, sending task")

        self._task = asyncio.create_task(self._run_loop())

    async def _run_loop(self):
        try:
            await self._client.query(self.task)
            async for msg in self._client.receive_messages():
                if isinstance(msg, AssistantMessage):
                    for block in msg.content:
                        if isinstance(block, TextBlock) and block.text:
                            self._log("text", block.text[:500])
                        elif isinstance(block, ToolUseBlock):
                            self._log("tool", f"{block.name}: {str(block.input)[:200]}")
                elif isinstance(msg, ResultMessage):
                    if msg.session_id:
                        self.session_id = msg.session_id
                    self.cost_usd += getattr(msg, 'total_cost_usd', 0) or 0
                    self.status = WorkerStatus.DONE
                    self._log("status", f"done, cost=${self.cost_usd:.4f}")
                    break
        except Exception as e:
            self.status = WorkerStatus.ERROR
            self._log("error", str(e))
            logger.error(f"Worker {self.name} error: {e}", exc_info=True)

    async def inject(self, message: str) -> bool:
        if not self._client or self.status != WorkerStatus.WORKING:
            return False
        try:
            await self._client.query(message)
            self._log("status", f"injected: {message[:100]}")
            return True
        except Exception as e:
            self._log("error", f"inject failed: {e}")
            return False

    async def interrupt(self):
        if self._client:
            try:
                await self._client.interrupt()
                self._log("status", "interrupted")
            except Exception as e:
                self._log("error", f"interrupt failed: {e}")

    async def kill(self):
        if self._task and not self._task.done():
            self._task.cancel()
        if self._client:
            try:
                await self._client.disconnect()
            except Exception:
                pass
        self.status = WorkerStatus.KILLED
        self._log("status", "killed")
        self._cleanup_worktree()

    def _cleanup_worktree(self):
        if self.worktree_path and Path(self.worktree_path).exists():
            subprocess.run(
                ["git", "worktree", "remove", self.worktree_path, "--force"],
                cwd=self.repo_path, capture_output=True,
            )

    @staticmethod
    async def _auto_approve(tool_name, tool_input, _context=None):
        return PermissionResultAllow(updated_input=tool_input)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "task": self.task[:200],
            "status": self.status.value,
            "branch": self.branch,
            "model": self.model,
            "cost_usd": round(self.cost_usd, 4),
            "context_pct": self.context_pct,
            "created_at": self.created_at.isoformat(),
            "logs_count": len(self.logs),
            "last_log": self.logs[-1].content[:100] if self.logs else "",
        }
