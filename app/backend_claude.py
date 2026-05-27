"""ClaudeBackend — wraps claude-agent-sdk for persistent agent sessions."""

import asyncio
import json as _json
import logging
import shutil
from typing import AsyncIterator, Optional

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

from app.events import AgentEvent

logger = logging.getLogger(__name__)

_BLOCKED_TOOLS = {"AskUserQuestion", "Monitor"}
_ORCH_BLOCKED_TOOLS = {"AskUserQuestion", "Agent", "Monitor"}


def _make_auto_approve(is_orchestrator: bool = False):
    blocked = _ORCH_BLOCKED_TOOLS if is_orchestrator else _BLOCKED_TOOLS
    async def _auto_approve(tool_name, tool_input, _context=None):
        if tool_name in blocked:
            msg = f"{tool_name} is not available for orchestrators. Use spawn_worker instead." if tool_name == "Agent" else f"{tool_name} is not available in Orchestra."
            return PermissionResultDeny(message=msg)
        if isinstance(tool_input, dict) and tool_input.get("run_in_background"):
            return PermissionResultDeny(message="run_in_background is disabled in Orchestra — background processes are killed when your turn ends. Run synchronously instead.")
        return PermissionResultAllow(updated_input=tool_input)
    return _auto_approve


def _extract_tool_result(block) -> str:
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


class ClaudeBackend:
    def __init__(self, model: str, cwd: str, system_prompt: str = "",
                 resume_session_id: str | None = None,
                 mcp_servers: dict | None = None,
                 is_orchestrator: bool = False,
                 scope_mcp_servers: dict | None = None):
        self.model = model
        self.cwd = cwd
        self.system_prompt = system_prompt
        self._resume_id = resume_session_id
        self._mcp_servers = mcp_servers or {}
        self._scope_mcp_servers = scope_mcp_servers or {}
        self._is_orchestrator = is_orchestrator
        self._client: Optional[ClaudeSDKClient] = None
        self._session_id: str | None = resume_session_id

    @property
    def session_id(self) -> Optional[str]:
        return self._session_id

    def _make_client(self) -> ClaudeSDKClient:
        import os
        cli = shutil.which("claude") or os.environ.get("CLAUDE_CLI_PATH", "claude")
        resume_id = self._session_id or self._resume_id
        env = {}
        for _k in ("HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY"):
            if os.environ.get(_k):
                env[_k] = os.environ[_k]
        options = ClaudeAgentOptions(
            model=self.model, cwd=self.cwd, cli_path=cli,
            permission_mode="default", can_use_tool=_make_auto_approve(self._is_orchestrator),
            include_partial_messages=False, max_turns=200,
            max_buffer_size=50 * 1024 * 1024,
            env=env,
        )
        if resume_id:
            options.resume = resume_id
        else:
            options.system_prompt = {"type": "preset", "preset": "claude_code", "append": self.system_prompt}
        merged_mcp = {**self._scope_mcp_servers, **self._mcp_servers}
        if merged_mcp:
            options.mcp_servers = merged_mcp
        options.setting_sources = ["user", "project", "local"]
        return ClaudeSDKClient(options=options)

    async def connect(self) -> None:
        self._client = self._make_client()
        try:
            await asyncio.wait_for(self._client.connect(), timeout=60)
        except Exception as e:
            logger.error(f"ClaudeBackend connect failed: {e}")
            raise

    async def send(self, message: str) -> None:
        if not self._client:
            raise RuntimeError("ClaudeBackend not connected")
        await self._client.query(message)

    async def events(self) -> AsyncIterator[AgentEvent]:
        if not self._client:
            return
        async for msg in self._client.receive_messages():
            for event in self._convert(msg):
                yield event

    async def interrupt(self) -> None:
        if self._client:
            try:
                await self._client.interrupt()
            except Exception as e:
                logger.warning(f"ClaudeBackend interrupt failed: {e}")

    async def disconnect(self) -> None:
        if self._client:
            try:
                await self._client.disconnect()
            except Exception:
                pass
            self._client = None

    async def reconnect(self) -> None:
        await self.disconnect()
        await asyncio.sleep(2)
        self._client = self._make_client()
        await asyncio.wait_for(self._client.connect(), timeout=60)

    def _convert(self, msg) -> list[AgentEvent]:
        events = []
        if isinstance(msg, AssistantMessage):
            for block in msg.content:
                if isinstance(block, TextBlock) and block.text:
                    events.append(AgentEvent("text", block.text))
                elif isinstance(block, ToolUseBlock):
                    try:
                        inp = _json.dumps(block.input, ensure_ascii=False, indent=2)
                    except Exception:
                        inp = str(block.input)
                    short_name = block.name.split('__')[-1] if '__' in block.name else block.name
                    events.append(AgentEvent("tool_use", f"{block.name}: {inp}",
                                             metadata={"tool_name": block.name, "short_name": short_name}))
                elif isinstance(block, (ToolResultBlock, ServerToolResultBlock)):
                    events.append(AgentEvent("tool_result", _extract_tool_result(block)))

        elif isinstance(msg, UserMessage):
            if hasattr(msg, 'content') and isinstance(msg.content, list):
                for block in msg.content:
                    if isinstance(block, (ToolResultBlock, ServerToolResultBlock)):
                        events.append(AgentEvent("tool_result", _extract_tool_result(block)))

        elif isinstance(msg, TaskStartedMessage):
            desc = getattr(msg, "description", "") or ""
            task_type = getattr(msg, "task_type", "") or ""
            task_id = getattr(msg, "task_id", "") or ""
            events.append(AgentEvent("subagent_start", f"{desc} | type={task_type} | id={task_id}"))

        elif isinstance(msg, TaskProgressMessage):
            desc = getattr(msg, "description", "") or ""
            last_tool = getattr(msg, "last_tool_name", "") or ""
            usage = getattr(msg, "usage", None)
            tokens = usage.total_tokens if usage and hasattr(usage, "total_tokens") else 0
            events.append(AgentEvent("subagent_progress", f"{desc} | tool={last_tool} | tokens={tokens}"))

        elif isinstance(msg, TaskNotificationMessage):
            desc = getattr(msg, "description", "") or ""
            status = getattr(msg, "status", "") or ""
            summary = getattr(msg, "summary", "") or ""
            events.append(AgentEvent("subagent_end", f"{desc} | status={status} | {summary[:500]}"))

        elif isinstance(msg, ResultMessage):
            sr = getattr(msg, "stop_reason", None) or "unknown"
            nt = getattr(msg, "num_turns", 0) or 0
            if msg.session_id:
                self._session_id = msg.session_id

            cost = getattr(msg, "total_cost_usd", 0) or 0
            usage = getattr(msg, "usage", None)
            ctx_pct = 0
            ctx_tokens = 0
            max_tokens = 200000
            cache_hit = 0
            cache_read = 0
            cache_create = 0
            input_tokens = 0
            output_tokens = 0
            cost_cached = 0.0

            if usage and isinstance(usage, dict):
                iters = usage.get("iterations", [])
                last = iters[-1] if iters else usage
                cache_create = last.get("cache_creation_input_tokens", 0) or 0
                cache_read = last.get("cache_read_input_tokens", 0) or 0
                input_tokens = last.get("input_tokens", 0) or 0
                output_tokens = last.get("output_tokens", 0) or 0
                total = input_tokens + cache_create + cache_read
                cache_total = cache_create + cache_read

                from app.models import CONTEXT_LIMITS, TOKEN_PRICES
                max_tokens = CONTEXT_LIMITS.get(self.model, 200000)
                ctx_pct = int(total * 100 / max_tokens) if max_tokens else 0
                ctx_tokens = total
                cache_hit = int(cache_read * 100 / cache_total) if cache_total else 0

                prices = TOKEN_PRICES.get(self.model)
                if prices:
                    p_in = prices["input"]
                    p_out = prices["output"]
                    if iters:
                        for it in iters:
                            i_in = it.get("input_tokens", 0) or 0
                            i_cr = it.get("cache_read_input_tokens", 0) or 0
                            i_cc = it.get("cache_creation_input_tokens", 0) or 0
                            i_out = it.get("output_tokens", 0) or 0
                            cost_cached += (i_in * p_in + i_cr * p_in * 0.1 + i_cc * p_in * 1.25 + i_out * p_out) / 1_000_000
                    else:
                        cost_cached = (input_tokens * p_in + cache_read * p_in * 0.1 + cache_create * p_in * 1.25 + output_tokens * p_out) / 1_000_000

            events.append(AgentEvent("turn_end", f"stop_reason={sr}, num_turns={nt}", metadata={
                "session_id": self._session_id,
                "ok": True,
                "stop_reason": sr,
                "num_turns": nt,
                "cost_usd": cost,
                "cost_usd_cached": round(cost_cached, 6),
                "context_pct": ctx_pct,
                "context_tokens": ctx_tokens,
                "max_tokens": max_tokens,
                "cache_hit": cache_hit,
                "cache_read": cache_read,
                "cache_create": cache_create,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            }))

        return events
