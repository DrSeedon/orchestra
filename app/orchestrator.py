"""Orchestrator — persistent SDK session that spawns and manages worker agents."""

import asyncio
import logging
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
from claude_agent_sdk.types import (
    AgentDefinition,
    TaskNotificationMessage,
    TaskProgressMessage,
    TaskStartedMessage,
    SystemMessage,
    RateLimitEvent,
)

from app.db import add_callback

logger = logging.getLogger(__name__)

WORKER_MD_PATH = Path.home() / ".claude" / "agents" / "worker.md"


def _load_worker_md() -> str:
    if WORKER_MD_PATH.exists():
        return WORKER_MD_PATH.read_text()
    return ""


class Orchestrator:
    def __init__(self):
        self._client: Optional[ClaudeSDKClient] = None
        self._connected = False
        self._listen_task: Optional[asyncio.Task] = None
        self._workers: dict[str, dict] = {}  # task_id → worker info
        self._worker_md = _load_worker_md()
        self._session_id: Optional[str] = None
        self._session_file = Path(__file__).parent.parent / "data" / "orchestrator_session"
        self._load_session()

    def _load_session(self):
        if self._session_file.exists():
            sid = self._session_file.read_text().strip()
            if sid:
                self._session_id = sid
                logger.info(f"Loaded orchestrator session: {sid[:8]}...")

    def _save_session(self):
        self._session_file.parent.mkdir(parents=True, exist_ok=True)
        self._session_file.write_text(self._session_id or "")

    async def start(self, cwd: str = "/mnt/data/Projects/Python/Parsing"):
        if self._connected:
            return

        options = ClaudeAgentOptions(
            model="claude-opus-4-6[1m]",
            cwd=cwd,
            max_turns=200,
            permission_mode="bypassPermissions",
            can_use_tool=self._auto_approve,
            include_partial_messages=True,
            system_prompt=self._orchestrator_prompt(),
        )
        if self._session_id:
            options.resume = self._session_id

        self._client = ClaudeSDKClient(options=options)
        await self._client.connect()
        self._connected = True
        logger.info("Orchestrator connected")

    def _orchestrator_prompt(self) -> str:
        return """Ты — Orchestra Orchestrator, CTO-агент.
Ты управляешь worker-агентами: спавнишь их через Agent tool, получаешь notifications когда они закончат.
Каждый worker работает в изолированном worktree.

Когда тебе приходит задача от пользователя:
1. Создай worktree для worker'а
2. Спавни Agent с задачей
3. Жди TaskNotification
4. Когда worker закончит — прочитай результат и отчитайся

Worker system prompt загружается из ~/.claude/agents/worker.md автоматически.
"""

    async def spawn_worker(self, name: str, task: str, repo_path: str,
                           model: str = "claude-sonnet-4-6") -> dict:
        if not self._connected:
            raise RuntimeError("Orchestrator not connected")

        import subprocess
        wt_base = Path(__file__).parent.parent / "worktrees"
        wt_base.mkdir(exist_ok=True)
        wt_path = str(wt_base / name)
        branch = f"feat/{name}"

        if Path(wt_path).exists():
            subprocess.run(["git", "worktree", "remove", wt_path, "--force"],
                           cwd=repo_path, capture_output=True)
        result = subprocess.run(
            ["git", "worktree", "add", wt_path, "-b", branch],
            cwd=repo_path, capture_output=True, text=True,
        )
        if result.returncode != 0:
            subprocess.run(["git", "worktree", "add", wt_path, branch],
                           cwd=repo_path, capture_output=True, text=True)

        import shutil
        repo = Path(repo_path)
        wt = Path(wt_path)
        for fname in ("CLAUDE.md", ".mcp.json", ".env"):
            src = repo / fname
            if not src.exists():
                src = repo.parent / fname
            if src.exists():
                shutil.copy2(str(src), str(wt / fname))

        prompt = f"""Spawn a background Agent to do this task in worktree {wt_path}:

Task: {task}
Repo: {repo_path}
Branch: {branch}
Model: {model}
Worker name: {name}

Use the Agent tool with:
- description: "{name}"
- prompt: the task above
- model: "{model}"
- run_in_background: true
- isolation: "worktree" is already done manually, cwd should be {wt_path}

After spawning, report back what you did."""

        await self._client.query(prompt)
        worker_info = {
            "name": name,
            "task": task,
            "repo_path": repo_path,
            "branch": branch,
            "model": model,
            "worktree_path": wt_path,
            "status": "spawning",
        }
        self._workers[name] = worker_info
        return worker_info

    async def listen(self):
        if not self._client:
            return
        async for msg in self._client.receive_messages():
            if isinstance(msg, TaskStartedMessage):
                logger.info(f"Task started: {msg.task_id} - {msg.description}")
                add_callback(msg.task_id, f"STARTED: {msg.description}")

            elif isinstance(msg, TaskProgressMessage):
                logger.info(f"Task progress: {msg.task_id} - {msg.description}")

            elif isinstance(msg, TaskNotificationMessage):
                logger.info(f"Task done: {msg.task_id} status={msg.status} summary={msg.summary}")
                add_callback(msg.task_id, f"{msg.status.upper()}: {msg.summary}")

            elif isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock) and block.text:
                        logger.info(f"Orchestrator: {block.text[:200]}")
                        add_callback("orchestrator", block.text)
                    elif isinstance(block, ToolUseBlock):
                        logger.info(f"Orchestrator tool: {block.name}")
                        add_callback("orchestrator", f"🔧 {block.name}")

            elif isinstance(msg, ResultMessage):
                if msg.session_id:
                    self._session_id = msg.session_id
                    self._save_session()
                cost = getattr(msg, 'total_cost_usd', 0) or 0
                logger.info(f"Orchestrator result: cost=${cost:.4f}")
                break

    async def send(self, message: str):
        if not self._client or not self._connected:
            raise RuntimeError("Not connected")
        await self._client.query(message)
        asyncio.create_task(self._listen_bg())

    async def _listen_bg(self):
        try:
            await self.listen()
        except Exception as e:
            logger.error(f"Listen error: {e}", exc_info=True)

    async def stop(self):
        if self._client:
            try:
                await self._client.disconnect()
            except Exception:
                pass
        self._connected = False

    @staticmethod
    async def _auto_approve(tool_name, tool_input, _context=None):
        logger.debug(f"Auto-approve: {tool_name}")
        return PermissionResultAllow(updated_input=tool_input)


orchestrator = Orchestrator()
