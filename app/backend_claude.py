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
    ThinkingBlock,
    ToolUseBlock,
    PermissionResultAllow,
    PermissionResultDeny,
    TaskStartedMessage,
    TaskProgressMessage,
    TaskNotificationMessage,
    SystemMessage,
    StreamEvent,
)
from claude_agent_sdk.types import (
    ToolResultBlock, ServerToolResultBlock, UserMessage,
)

from app.events import AgentEvent

logger = logging.getLogger(__name__)

_BLOCKED_TOOLS = {"AskUserQuestion", "Monitor"}
_ORCH_BLOCKED_TOOLS = {"AskUserQuestion", "Agent", "Monitor"}
# Orchestrators must use spawn_worker instead of the built-in Agent/Task tools —
# those bypass Orchestra's worktree isolation and session tracking.
# Blocked via disallowed_tools (not can_use_tool) because subagent launches arrive
# as TaskStartedMessage, which the permission callback never sees.
_ORCH_DISALLOWED_TOOLS = ["Task", "Agent"]
# ScheduleWakeup/Cron* removed for all agents — Orchestra manages scheduling via bg_jobs
_ALWAYS_DISALLOWED = ["ScheduleWakeup", "CronCreate", "CronDelete", "CronList", "Workflow"]


def _make_auto_approve(is_orchestrator: bool = False):
    blocked = _ORCH_BLOCKED_TOOLS if is_orchestrator else _BLOCKED_TOOLS
    async def _auto_approve(tool_name, tool_input, _context=None):
        if tool_name in blocked:
            msg = f"{tool_name} is not available for orchestrators. Use spawn_worker instead." if tool_name == "Agent" else f"{tool_name} is not available in Orchestra."
            return PermissionResultDeny(message=msg)
        if isinstance(tool_input, dict) and tool_input.get("run_in_background"):
            # run_in_background spawns a detached process that dies when the CLI turn ends —
            # use bg_create MCP tool instead for actual background work
            return PermissionResultDeny(message="run_in_background is disabled in Orchestra — background processes are killed when your turn ends. Run synchronously instead.")
        return PermissionResultAllow(updated_input=tool_input)
    return _auto_approve


def _disallowed_tools(is_orchestrator: bool) -> list[str]:
    """Инструменты, полностью убираемые из набора модели (через CLI),
    а не через can_use_tool. Оркестратор делегирует через spawn_worker,
    поэтому субагентов ему отнимаем; воркерам — оставляем.
    ScheduleWakeup/Cron* убираем у ВСЕХ — Orchestra управляет scheduling сама."""
    base = list(_ALWAYS_DISALLOWED)
    if is_orchestrator:
        base.extend(_ORCH_DISALLOWED_TOOLS)
    return base


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
                 scope_mcp_servers: dict | None = None,
                 config_dir: str = "",
                 inherit_claude_md: bool = True,
                 user_mcp_servers: dict | None = None):
        self.model = model
        self.cwd = cwd
        self.system_prompt = system_prompt
        self._resume_id = resume_session_id
        self._mcp_servers = mcp_servers or {}
        self._scope_mcp_servers = scope_mcp_servers or {}
        self._is_orchestrator = is_orchestrator
        # Профиль Claude (F1/F4 резолвятся против него): пустой → env процесса
        # orchestra (back-compat, 1:1 upstream).
        self._config_dir = config_dir
        # F4: наследовать ли user/project CLAUDE.md + настройки профиля.
        self._inherit_claude_md = inherit_claude_md
        # F2: user-MCP из профильного .claude.json (базовый слой merge).
        self._user_mcp_servers = user_mcp_servers or {}
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
                env[_k.lower()] = os.environ[_k]
        # #56: kill non-essential background haiku calls (tips/banter/flavor) + telemetry
        env["DISABLE_NON_ESSENTIAL_MODEL_CALLS"] = "1"
        env["DISABLE_TELEMETRY"] = "1"
        # Профиль: переопределяем CLAUDE_CONFIG_DIR подпроцесса (SDK строит
        # env как {**os.environ, **options.env}). Пусто → наследуем env процесса
        # orchestra (back-compat). expanduser — на случай "~" в config_dir.
        if self._config_dir:
            env["CLAUDE_CONFIG_DIR"] = os.path.expanduser(self._config_dir)
        agent_uid = os.environ.get("ORCHESTRA_AGENT_UID")
        options = ClaudeAgentOptions(
            model=self.model, cwd=self.cwd, cli_path=cli,
            permission_mode="default", can_use_tool=_make_auto_approve(self._is_orchestrator),
            disallowed_tools=_disallowed_tools(self._is_orchestrator),
            include_partial_messages=True, max_turns=200,
            max_buffer_size=50 * 1024 * 1024,
            env=env,
            user=agent_uid,
        )
        if resume_id:
            options.resume = resume_id
        else:
            options.system_prompt = {"type": "preset", "preset": "claude_code", "append": self.system_prompt}
        # MCP merge order: user < scope < instance — more specific wins.
        # Instance (Orchestra's own server) always overrides to prevent hijacking.
        merged_mcp = {
            **self._user_mcp_servers,
            **self._scope_mcp_servers,
            **self._mcp_servers,
        }
        if merged_mcp:
            options.mcp_servers = merged_mcp
        # F4: inherit_claude_md=False → только local-слой (нет user/project
        # CLAUDE.md и настроек); иначе — полный набор, как в upstream.
        options.setting_sources = (
            ["user", "project", "local"] if self._inherit_claude_md else ["local"]
        )
        # F1: options.skills НЕ задаём НИКОГДА. Ветка "skills-список → options.skills"
        # сознательно НЕ реализована (B4: default 1:1 upstream — его роли имеют
        # skills-списки, но скиллы инъектятся через _inject_skills_to_worktree,
        # не через options.skills). Единственное действие F1 — gating инъекции
        # в manager.create_session при skills=="all".
        return ClaudeSDKClient(options=options)

    async def _cleanup_failed_client(self) -> None:
        if self._client:
            try:
                await self._client.disconnect()
            except BaseException:
                pass
            self._client = None

    async def connect(self) -> None:
        self._client = self._make_client()
        try:
            await asyncio.wait_for(self._client.connect(), timeout=60)
        except BaseException as e:
            logger.error(f"ClaudeBackend connect failed: {e}")
            await self._cleanup_failed_client()
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
            except Exception as e:
                logger.warning(f"ClaudeBackend disconnect failed: {e}")
            self._client = None

    async def context_usage(self) -> dict | None:
        if not self._client:
            return None
        try:
            u = await asyncio.wait_for(self._client.get_context_usage(), timeout=5)
            return {
                "percentage": int(u.get("percentage", 0)),
                "total_tokens": u.get("totalTokens", 0),
                "max_tokens": u.get("maxTokens", 0),
                "raw_max_tokens": u.get("rawMaxTokens", 0),
                "auto_compact": u.get("isAutoCompactEnabled", False),
                "auto_compact_threshold": u.get("autoCompactThreshold", 0),
            }
        except asyncio.TimeoutError:
            return None
        except Exception as e:
            logger.debug(f"get_context_usage failed: {e}")
            return None

    async def reconnect(self) -> None:
        await self.disconnect()
        await asyncio.sleep(2)
        self._client = self._make_client()
        try:
            await asyncio.wait_for(self._client.connect(), timeout=60)
        except BaseException as e:
            logger.error(f"ClaudeBackend reconnect failed: {e}")
            await self._cleanup_failed_client()
            raise

    def _convert(self, msg) -> list[AgentEvent]:
        events = []
        if isinstance(msg, StreamEvent):
            # v1 streaming scope: ONLY main-agent text. Skip subagent partials
            # (parent_tool_use_id set) and non-text deltas (thinking/tool-arg/sig).
            # The final AssistantMessage still carries everything and is persisted.
            ev = msg.event or {}
            if msg.parent_tool_use_id is not None:
                return events
            if ev.get("type") != "content_block_delta":
                return events
            delta = ev.get("delta") or {}
            if delta.get("type") != "text_delta":
                return events
            text = delta.get("text") or ""
            if text:
                events.append(AgentEvent("stream", text))
            return events

        if isinstance(msg, AssistantMessage):
            for block in msg.content:
                if isinstance(block, TextBlock) and block.text:
                    events.append(AgentEvent("text", block.text))
                elif isinstance(block, ThinkingBlock) and block.thinking:
                    events.append(AgentEvent("thinking", block.thinking))
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
            err = getattr(msg, "error", None)
            if err:
                events.append(AgentEvent("error", f"model error: {err}"))

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

            is_err = bool(getattr(msg, "is_error", False))
            err_list = getattr(msg, "errors", None) or []
            denials = getattr(msg, "permission_denials", None) or []

            cost = getattr(msg, "total_cost_usd", 0) or 0
            usage = getattr(msg, "usage", None)
            max_tokens = 200000
            cache_hit = 0
            cache_read = 0
            cache_create = 0
            input_tokens = 0
            output_tokens = 0
            cost_cached = 0.0

            if usage and isinstance(usage, dict):
                cache_create = usage.get("cache_creation_input_tokens", 0) or 0
                cache_read = usage.get("cache_read_input_tokens", 0) or 0
                input_tokens = usage.get("input_tokens", 0) or 0
                output_tokens = usage.get("output_tokens", 0) or 0
                cache_total = cache_create + cache_read

                from app.models import CONTEXT_LIMITS, TOKEN_PRICES
                max_tokens = CONTEXT_LIMITS.get(self.model, 200000)
                cache_hit = int(cache_read * 100 / cache_total) if cache_total else 0

                prices = TOKEN_PRICES.get(self.model)
                if prices:
                    p_in = prices["input"]
                    p_out = prices["output"]
                    # Recalculate cost from real TOKEN_PRICES (SDK uses hardcoded Claude prices)
                    real_cost = (input_tokens * p_in + output_tokens * p_out) / 1_000_000
                    if not self.model.startswith("claude-"):
                        cost = real_cost
                    # Anthropic cache pricing: cache_read = 10% of input, cache_create = 125%
                    cost_cached = (input_tokens * p_in + cache_read * p_in * 0.1 + cache_create * p_in * 1.25 + output_tokens * p_out) / 1_000_000

            if denials:
                logger.info(f"[{self.model}] {len(denials)} permission denial(s) this turn")

            events.append(AgentEvent("turn_end", f"stop_reason={sr}, num_turns={nt}", metadata={
                "session_id": self._session_id,
                "ok": not is_err,
                "is_error": is_err,
                "errors": err_list,
                "stop_reason": sr,
                "num_turns": nt,
                "cost_usd": cost,
                "cost_usd_cached": round(cost_cached, 6),
                "context_pct": 0,
                "context_tokens": 0,
                "max_tokens": max_tokens,
                "cache_hit": cache_hit,
                "cache_read": cache_read,
                "cache_create": cache_create,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            }))

        if (isinstance(msg, SystemMessage)
                and not isinstance(msg, (TaskStartedMessage, TaskProgressMessage, TaskNotificationMessage))
                and getattr(msg, "subtype", "") == "compact_boundary"):
            data = getattr(msg, "data", {}) or {}
            meta = data.get("compactMetadata", data)
            pre = meta.get("preTokens", 0)
            post = meta.get("postTokens", 0)
            trigger = meta.get("trigger", "unknown")
            events.append(AgentEvent("status",
                f"CLI auto-compacted ({trigger}): {pre:,}→{post:,} tokens"))

        return events
