"""CodexBackend — wraps Codex CLI subprocess for agent sessions."""

import asyncio
import json
import logging
import os
import shutil
from typing import AsyncIterator, Optional

from app.events import AgentEvent

logger = logging.getLogger(__name__)

CODEX_BIN = shutil.which("codex") or "/home/maxim/.npm-global/bin/codex"

CODEX_CONTEXT_LIMITS = {
    "gpt-5.5": 258400,
    "gpt-5.4": 258400,
    "gpt-5.4-mini": 258400,
}

CODEX_TOKEN_PRICES = {
    "gpt-5.5":      {"input": 5.0, "output": 30.0},
    "gpt-5.4":      {"input": 2.5, "output": 15.0},
    "gpt-5.4-mini": {"input": 0.3, "output": 1.25},
}


CODEX_REASONING_EFFORTS = {"minimal", "low", "medium", "high"}


class CodexBackend:
    def __init__(self, model: str, cwd: str, system_prompt: str = "",
                 resume_thread_id: str | None = None,
                 mcp_env: dict[str, str] | None = None,
                 reasoning_effort: str = "high"):
        self.model = model
        self.cwd = cwd
        self.system_prompt = system_prompt
        self._thread_id: str | None = resume_thread_id
        self._mcp_env: dict[str, str] = mcp_env or {}
        self.reasoning_effort = reasoning_effort if reasoning_effort in CODEX_REASONING_EFFORTS else "high"
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._stderr_task: Optional[asyncio.Task] = None
        self._last_stderr: str = ""
        self._got_turn_completed: bool = False

    @property
    def session_id(self) -> Optional[str]:
        return self._thread_id

    async def connect(self) -> None:
        pass

    async def send(self, message: str) -> None:
        self._got_turn_completed = False
        self._last_stderr = ""

        cmd = [CODEX_BIN]
        if self._thread_id:
            cmd += ["exec", "resume", "--json",
                    "--dangerously-bypass-approvals-and-sandbox",
                    self._thread_id, message]
        else:
            cmd += ["exec", "--json", "-m", self.model,
                    "--dangerously-bypass-approvals-and-sandbox",
                    "-C", self.cwd]
            if self.system_prompt:
                escaped = self.system_prompt.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
                cmd += ["-c", f'developer_instructions="{escaped}"']
            cmd += ["-c", f'model_reasoning_effort="{self.reasoning_effort}"']
            cmd.append(message)

        self._proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._build_env(),
            cwd=self.cwd,
        )
        self._stderr_task = asyncio.create_task(self._drain_stderr())

    async def events(self) -> AsyncIterator[AgentEvent]:
        if not self._proc or not self._proc.stdout:
            return

        async for raw_line in self._proc.stdout:
            line = raw_line.decode("utf-8").rstrip("\n")
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            etype = data.get("type", "")

            if etype == "thread.started":
                self._thread_id = data["thread_id"]
                yield AgentEvent("status", f"codex thread={self._thread_id}")

            elif etype == "item.completed":
                item = data.get("item", {})
                itype = item.get("type", "")

                if itype == "agent_message":
                    yield AgentEvent("text", item.get("text", ""))

                elif itype == "command_execution":
                    cmd_str = item.get("command", "")
                    yield AgentEvent("tool_use", f"Bash: {cmd_str}",
                                     metadata={"tool_name": "Bash", "short_name": "Bash"})
                    output = item.get("aggregated_output", "")
                    yield AgentEvent("tool_result", output,
                                     metadata={"exit_code": item.get("exit_code")})

                elif itype == "file_change":
                    changes = item.get("changes", [])
                    desc = ", ".join(f"{c.get('kind', '')} {c.get('path', '')}" for c in changes)
                    yield AgentEvent("file_change", desc)

                elif itype == "mcp_tool_call":
                    server = item.get("server", "")
                    tool = item.get("tool", "")
                    args_str = json.dumps(item.get("arguments", {}), ensure_ascii=False)[:200]
                    full_name = f"{server}__{tool}" if server else tool
                    yield AgentEvent("tool_use", f"{full_name}: {args_str}",
                                     metadata={"tool_name": full_name, "short_name": tool})
                    result = item.get("result")
                    if result:
                        content = result.get("content", [])
                        text = "\n".join(
                            b.get("text", str(b)) for b in content if isinstance(b, dict)
                        ) if content else str(result)
                        yield AgentEvent("tool_result", text[:2000])
                    error = item.get("error")
                    if error:
                        yield AgentEvent("error", error.get("message", str(error)))

                elif itype == "error":
                    yield AgentEvent("error", item.get("message", ""))

            elif etype == "item.started":
                item = data.get("item", {})
                itype = item.get("type", "")
                if itype == "command_execution":
                    yield AgentEvent("tool_use", f"Bash: {item.get('command', '')}",
                                     metadata={"tool_name": "Bash", "short_name": "Bash"})

            elif etype == "turn.completed":
                self._got_turn_completed = True
                usage = data.get("usage", {})
                input_t = usage.get("input_tokens", 0)
                cached_t = usage.get("cached_input_tokens", 0)
                output_t = usage.get("output_tokens", 0)

                ctx_window = CODEX_CONTEXT_LIMITS.get(self.model, 258400)
                ctx_pct = min(100, int(input_t * 100 / ctx_window)) if ctx_window else 0

                prices = CODEX_TOKEN_PRICES.get(self.model, {"input": 0, "output": 0})
                cost = (input_t * prices["input"] + output_t * prices["output"]) / 1_000_000

                yield AgentEvent("turn_end", f"stop_reason=end_turn", metadata={
                    "session_id": self._thread_id,
                    "ok": True,
                    "stop_reason": "end_turn",
                    "cost_usd": cost,
                    "context_pct": ctx_pct,
                    "context_tokens": input_t,
                    "max_tokens": ctx_window,
                    "cache_hit": int(cached_t * 100 / input_t) if input_t else 0,
                    "cache_read": cached_t,
                    "cache_create": 0,
                    "input_tokens": input_t,
                    "cached_input_tokens": cached_t,
                    "output_tokens": output_t,
                })

            elif etype == "turn.failed":
                error = data.get("error", {})
                yield AgentEvent("error", error.get("message", "turn failed"))

            elif etype == "error":
                yield AgentEvent("error", data.get("message", "codex error"))

        returncode = await self._proc.wait()

        if self._stderr_task:
            try:
                await asyncio.wait_for(self._stderr_task, timeout=5)
            except (asyncio.TimeoutError, Exception):
                pass

        if not self._got_turn_completed:
            yield AgentEvent("turn_end", f"stop_reason=process_exit_{returncode}", metadata={
                "session_id": self._thread_id,
                "ok": False,
                "stop_reason": f"process_exit_{returncode}",
                "returncode": returncode,
                "stderr_tail": self._last_stderr,
                "cost_usd": 0,
                "context_pct": 0,
                "context_tokens": 0,
                "max_tokens": CODEX_CONTEXT_LIMITS.get(self.model, 258400),
            })

        self._proc = None

    async def interrupt(self) -> None:
        if self._proc and self._proc.returncode is None:
            self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._proc.kill()

    async def disconnect(self) -> None:
        await self.interrupt()

    async def _drain_stderr(self) -> None:
        if not self._proc or not self._proc.stderr:
            return
        chunks = []
        while True:
            chunk = await self._proc.stderr.read(4096)
            if not chunk:
                break
            chunks.append(chunk)
        data = b"".join(chunks)
        self._last_stderr = data[-500:].decode("utf-8", errors="replace")

    def _build_env(self) -> dict:
        env = dict(os.environ)
        env.update(self._mcp_env)
        env.pop("HTTPS_PROXY", None)
        env.pop("HTTP_PROXY", None)
        return env
