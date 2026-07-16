"""CodexBackend — wraps Codex CLI subprocess for agent sessions."""

import asyncio
import json
import logging
import os
import shutil
from typing import AsyncIterator, Optional

from app.events import AgentEvent

logger = logging.getLogger(__name__)

CODEX_BIN = shutil.which("codex") or os.environ.get("CODEX_BIN", "codex")

# Context windows: value = usable prefill budget = model window × ~0.95 safety margin.
# GPT-5.6 (Sol/Terra/Luna): 1,050,000 window → 997,500 usable. 5.4/5.5: 272,000 → 258,400.
CODEX_CONTEXT_LIMITS = {
    "gpt-5.6-sol":   997500,
    "gpt-5.6-terra": 997500,
    "gpt-5.6-luna":  997500,
    "gpt-5.5": 258400,
    "gpt-5.4": 258400,
    "gpt-5.4-mini": 258400,
}

CODEX_TOKEN_PRICES = {
    "gpt-5.6-sol":   {"input": 5.0, "output": 30.0},
    "gpt-5.6-terra": {"input": 2.5, "output": 15.0},
    "gpt-5.6-luna":  {"input": 1.0, "output": 6.0},
    "gpt-5.5":      {"input": 5.0, "output": 30.0},
    "gpt-5.4":      {"input": 2.5, "output": 15.0},
    "gpt-5.4-mini": {"input": 0.3, "output": 1.25},
}


# GPT-5.6 reasoning ladder (light→low→medium→high→xhigh→max→ultra). "minimal" kept for
# 5.4/5.5 back-compat. "ultra" (parallel sub-agents) intentionally excluded — a special
# mode, not a plain effort level, and risky to trigger from a generic worker effort field.
CODEX_REASONING_EFFORTS = {"minimal", "low", "medium", "high", "xhigh", "max"}


class CodexBackend:
    def __init__(self, model: str, cwd: str, system_prompt: str = "",
                 resume_thread_id: str | None = None,
                 mcp_env: dict[str, str] | None = None,
                 mcp_servers: dict | None = None,
                 reasoning_effort: str = "high"):
        self.model = model
        self.cwd = cwd
        self.system_prompt = system_prompt
        self._thread_id: str | None = resume_thread_id
        self._mcp_env: dict[str, str] = mcp_env or {}
        self._mcp_servers: dict = mcp_servers or {}
        self.reasoning_effort = reasoning_effort if reasoning_effort in CODEX_REASONING_EFFORTS else "high"
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._stderr_task: Optional[asyncio.Task] = None
        self._last_stderr: str = ""
        self._got_turn_completed: bool = False

    @property
    def session_id(self) -> Optional[str]:
        return self._thread_id

    async def connect(self) -> None:
        # Codex launches a new subprocess per turn (stateless CLI), so connect is a no-op —
        # the actual process starts in send() when the first message arrives
        pass

    async def send(self, message: str) -> None:
        self._got_turn_completed = False
        self._last_stderr = ""

        # --dangerously-bypass-approvals-and-sandbox: the flag's own help says it's
        # "intended solely for running in environments that are externally sandboxed" —
        # which is exactly our case: every worker runs in an isolated git worktree as a
        # dedicated process, and an autonomous worker has no human to answer approval
        # prompts. -s workspace-write would block on approvals it can't resolve. The
        # worktree is the external sandbox this flag is designed for.
        # RISK (Sol): GPT-5.6 Sol has elevated reward-hacking (METR); no sandbox means it
        # can run arbitrary commands inside its worktree. Mitigate via worker prompt
        # (evidence-based done-conditions, tests outside write-scope), not this flag.
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
            # Per-worker MCP: inject each server as a -c mcp_servers.NAME={...} inline TOML
            # table. Codex otherwise only reads MCP from the global ~/.codex/config.toml,
            # which isn't per-worker and is absent on the VPS — so a codex worker would lack
            # Orchestra tools (send_message/spawn_worker/report). Mirrors what the Claude SDK
            # gets via mcp_servers=.
            for arg in self._mcp_config_args():
                cmd += ["-c", arg]
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

                # input_tokens are CUMULATIVE per thread (verified: turn1=16728 → turn2=33472
                # on resume — the full conversation is re-fed each turn). So this cost is
                # monotonically increasing per thread, and CostTracker's delta logic
                # (max(0, new_cost - last_cost)) already yields the correct per-turn cost —
                # same contract as the Claude SDK. Do NOT re-accumulate here (double-counts).
                prices = CODEX_TOKEN_PRICES.get(self.model, {"input": 0, "output": 0})
                cost = (input_t * prices["input"] + output_t * prices["output"]) / 1_000_000

                yield AgentEvent("turn_end", f"stop_reason=end_turn", metadata={
                    "session_id": self._thread_id,
                    "ok": True,
                    "stop_reason": "end_turn",
                    "cost_usd": cost,
                    "cost_usd_cached": cost,
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
            except asyncio.TimeoutError:
                pass
            except Exception as e:
                logger.warning(f"codex stderr drain failed: {e}")

        if not self._got_turn_completed:
            # Process exited without emitting turn.completed — treat as error turn
            # so session.py can update status and trigger auto-report
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

    @staticmethod
    def _toml_str(s: str) -> str:
        # TOML basic string: escape backslash and double-quote (control chars unlikely in
        # command/args/env values here). Keeps the -c inline table parseable.
        return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'

    def _mcp_config_args(self) -> list[str]:
        """Dotted `-c mcp_servers.NAME.FIELD=value` overrides, one field per entry.

        Translates the Orchestra mcp_servers dict (same shape the Claude SDK gets) into
        Codex config. Codex parses a whole-table value (`mcp_servers.NAME={...}`) as a
        *string* and rejects it (`expected struct RawMcpServerConfig`) — dotted leaf keys
        are the form it accepts (verified against CLI 0.144.3). `env` as a single inline
        table works; command/args go as separate keys. Only STDIO servers (command+args+env)
        are supported — Orchestra + scope .mcp.json servers are all STDIO. Unknown keys
        (alwaysLoad, type) are dropped."""
        args = []
        for name, cfg in self._mcp_servers.items():
            command = cfg.get("command")
            if not command:
                continue  # url/remote servers not expressible this way — skip, don't crash
            args.append(f"mcp_servers.{name}.command={self._toml_str(str(command))}")
            srv_args = cfg.get("args") or []
            args.append(f"mcp_servers.{name}.args=[" +
                        ", ".join(self._toml_str(str(a)) for a in srv_args) + "]")
            env = cfg.get("env") or {}
            if env:
                env_inline = ", ".join(f"{k}={self._toml_str(str(v))}" for k, v in env.items())
                args.append(f"mcp_servers.{name}.env={{" + env_inline + "}")
        return args

    def _build_env(self) -> dict:
        env = dict(os.environ)
        env.update(self._mcp_env)
        # Strip proxy for Codex: it talks directly to OpenAI, not Anthropic —
        # routing through Hiddify would break OpenAI connectivity
        env.pop("HTTPS_PROXY", None)
        env.pop("HTTP_PROXY", None)
        return env
