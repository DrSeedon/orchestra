"""ClaudeBackend — wraps claude-agent-sdk for persistent agent sessions."""

import asyncio
import hashlib
import importlib.metadata
import json as _json
import logging
import os
import re
import shlex
import shutil
import time
import uuid
from pathlib import Path
from typing import AsyncIterator, Optional

from claude_agent_sdk import (
    Transport,
    CLIConnectionError,
    ClaudeSDKClient,
    ClaudeAgentOptions,
    HookMatcher,
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

from app.errtext import err_text
from app.events import AgentEvent
from app.runtime_history import (
    CLAUDE_CLI_HISTORY_VERSION,
    CLAUDE_SDK_HISTORY_VERSION,
    HISTORICAL_TOOL_INSTRUCTION,
    ClaudeHistoryImport,
    ClaudeLogSessionStore,
    NativeHistoryImportError,
    NativeHistoryRejected,
    NativeHistoryUnsupported,
    build_model_visible_manifest,
    preflight_provider_context,
)
from app.usage_contract import AggregateUsage, TurnUsage, deferred_context

logger = logging.getLogger(__name__)

CLAUDE_INTERRUPT_TIMEOUT = 5.0
_BASH_CLASSIFIER_TIMEOUT = 0.1

_BLOCKED_TOOLS = {"AskUserQuestion", "Monitor"}
_ORCH_BLOCKED_TOOLS = {"AskUserQuestion", "Agent", "Monitor"}
# Orchestrators must use spawn_worker instead of the built-in Agent/Task tools —
# those bypass Orchestra's worktree isolation and session tracking.
# Blocked via disallowed_tools (not can_use_tool) because subagent launches arrive
# as TaskStartedMessage, which the permission callback never sees.
_ORCH_DISALLOWED_TOOLS = ["Task", "Agent"]
# ScheduleWakeup/Cron* removed for all agents — Orchestra manages scheduling via bg_jobs
_ALWAYS_DISALLOWED = ["ScheduleWakeup", "CronCreate", "CronDelete", "CronList", "Workflow"]


_SAFE_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,63}$")


def _safe_config_key(session_id: str | None) -> str:
    """Имя файла конфига из session id, либо случайное — но НИКОГДА из чужой строки.

    Значение приходит из env MCP-сервера, то есть из данных. Пропустив `../..`, мы дали бы
    запись за пределы каталога; пустое значение — общий файл на всех агентов сразу.
    """
    if session_id and _SAFE_KEY.match(session_id):
        return session_id
    return f"anon-{uuid.uuid4().hex}"


class InheritedFdTransport(Transport):
    """Drive the Claude SDK over pipes we did NOT open (#230 T3).

    The SDK accepts a custom transport (`ClaudeSDKClient(options, transport=...)`,
    client.py:68-72) and confines the whole process lifecycle to its own subprocess
    transport — so adopting a CLI that outlived a supervisor restart needs no SDK fork and
    no process object. `close()` deliberately does NOT kill anything: the CLI is not ours,
    it is mid-turn, and killing it is the exact thing #230 exists to stop.
    """

    #: frames are whole JSON lines; a 9000-byte message arrives across several reads
    _LIMIT = 16 * 1024 * 1024

    def __init__(self, fd_in: int, fd_out: int) -> None:
        self._fd_in = fd_in
        self._fd_out = fd_out
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._ready = False

    async def connect(self) -> None:
        if self._ready:
            return
        loop = asyncio.get_running_loop()
        reader = asyncio.StreamReader(limit=self._LIMIT)
        await loop.connect_read_pipe(
            lambda: asyncio.StreamReaderProtocol(reader), os.fdopen(self._fd_out, "rb", 0)
        )
        transport, protocol = await loop.connect_write_pipe(
            asyncio.streams.FlowControlMixin, os.fdopen(self._fd_in, "wb", 0)
        )
        self._reader = reader
        self._writer = asyncio.StreamWriter(transport, protocol, reader, loop)
        self._ready = True

    async def write(self, data: str) -> None:
        if not self._ready or self._writer is None:
            raise CLIConnectionError("InheritedFdTransport is not ready for writing")
        self._writer.write(data.encode("utf-8"))
        await self._writer.drain()

    async def read_messages(self) -> AsyncIterator[dict]:
        if self._reader is None:
            raise CLIConnectionError("InheritedFdTransport is not connected")
        while True:
            line = await self._reader.readline()
            if not line:
                return
            text = line.strip()
            if not text:
                continue
            try:
                yield _json.loads(text)
            except _json.JSONDecodeError:
                logger.warning("adopted Claude CLI emitted invalid JSON line")

    async def close(self) -> None:
        self._ready = False
        if self._writer is not None:
            self._writer.close()
            self._writer = None
        self._reader = None

    def is_ready(self) -> bool:
        return self._ready

    async def end_input(self) -> None:
        if self._writer is not None:
            self._writer.write_eof()


def _make_auto_approve(is_orchestrator: bool = False):
    blocked = _ORCH_BLOCKED_TOOLS if is_orchestrator else _BLOCKED_TOOLS
    async def _auto_approve(tool_name, tool_input, _context=None):
        if tool_name in blocked:
            msg = f"{tool_name} is not available for orchestrators. Use spawn_worker instead." if tool_name == "Agent" else f"{tool_name} is not available in Orchestra."
            return PermissionResultDeny(message=msg)
        return PermissionResultAllow(updated_input=tool_input)
    return _auto_approve


_BASH_CLASSIFICATIONS = {"recursive_rm", "world_writable", "curl_pipe_shell"}
_BASH_SEPARATORS = {";", "&&", "||", "|", "&", "(", ")", "\n"}
_BASH_PUNCTUATION = set("();<>|&\n")


class _InvalidBashClassification(Exception):
    pass


def _command_basename(segment: list[str]) -> str | None:
    if not segment:
        return None
    command = segment[0]
    if not command or command.startswith("-"):
        return None
    return os.path.basename(command)


def _split_bash_punctuation(tokens: list[str]) -> list[str]:
    normalized: list[str] = []
    for token in tokens:
        if not token or any(char not in _BASH_PUNCTUATION for char in token):
            normalized.append(token)
            continue
        index = 0
        while index < len(token):
            pair = token[index:index + 2]
            if pair in {"&&", "||"}:
                normalized.append(pair)
                index += 2
            else:
                normalized.append(token[index])
                index += 1
    return normalized


def _heredoc_declarations(
    line: str, quote: str | None
) -> tuple[list[tuple[str, bool]], str | None]:
    declarations: list[tuple[str, bool]] = []
    index = 0
    while index < len(line):
        char = line[index]
        if quote is not None:
            if quote == '"' and char == "\\":
                index += 2
                continue
            if char == quote:
                quote = None
            index += 1
            continue
        if char in {"'", '"'}:
            quote = char
            index += 1
            continue
        if char == "\\":
            index += 2
            continue
        if char == "#" and (
            index == 0 or line[index - 1].isspace() or line[index - 1] in ";&|()"
        ):
            break
        if not line.startswith("<<", index) or line.startswith("<<<", index):
            index += 1
            continue

        cursor = index + 2
        strip_tabs = cursor < len(line) and line[cursor] == "-"
        cursor += strip_tabs
        while cursor < len(line) and line[cursor] in " \t":
            cursor += 1
        delimiter: list[str] = []
        word_quote: str | None = None
        while cursor < len(line):
            token_char = line[cursor]
            if word_quote is not None:
                if word_quote == '"' and token_char == "\\" and cursor + 1 < len(line):
                    delimiter.append(line[cursor + 1])
                    cursor += 2
                    continue
                if token_char == word_quote:
                    word_quote = None
                else:
                    delimiter.append(token_char)
                cursor += 1
                continue
            if token_char in {"'", '"'}:
                word_quote = token_char
                cursor += 1
                continue
            if token_char == "\\" and cursor + 1 < len(line):
                delimiter.append(line[cursor + 1])
                cursor += 2
                continue
            if token_char.isspace() or token_char in ";&|()<>":
                break
            delimiter.append(token_char)
            cursor += 1
        if delimiter:
            declarations.append(("".join(delimiter), strip_tabs))
        index = max(cursor, index + 2)
    return declarations, quote


def _without_heredoc_bodies(command: str) -> str:
    pending: list[tuple[str, bool]] = []
    quote: str | None = None
    output: list[str] = []
    for line in command.splitlines(keepends=True):
        if pending:
            candidate = line.rstrip("\r\n")
            delimiter, strip_tabs = pending[0]
            if strip_tabs:
                candidate = candidate.lstrip("\t")
            if candidate == delimiter:
                pending.pop(0)
            if line.endswith(("\n", "\r")):
                output.append("\n")
            continue
        output.append(line)
        declarations, quote = _heredoc_declarations(line, quote)
        pending.extend(declarations)
    return "".join(output)


def _bash_segments(tokens: list[str]) -> tuple[list[list[str]], list[str | None]]:
    segments: list[list[str]] = []
    leading_separators: list[str | None] = []
    current: list[str] = []
    pending_separator: str | None = None
    for token in tokens:
        if token in _BASH_SEPARATORS:
            if current:
                segments.append(current)
                leading_separators.append(pending_separator)
                current = []
                pending_separator = token
            elif token not in {"(", ")"} and not (
                token == "\n" and pending_separator is not None
            ):
                pending_separator = token
        else:
            current.append(token)
    if current:
        segments.append(current)
        leading_separators.append(pending_separator)
    return segments, leading_separators


def _classify_bash_payload(tool_input: dict) -> str | None:
    """Classify the small, deliberately conservative Bash grammar used by the pilot."""
    if not isinstance(tool_input, dict):
        return None
    command = tool_input.get("command")
    if not isinstance(command, str):
        return None
    command = _without_heredoc_bodies(command)
    lexer = shlex.shlex(command, posix=True, punctuation_chars="();<>|&\n")
    lexer.whitespace_split = True
    lexer.whitespace = " \t\r"
    lexer.commenters = ""
    tokens = _split_bash_punctuation(list(lexer))
    segments, leading_separators = _bash_segments(tokens)

    for segment in segments:
        name = _command_basename(segment)
        if name == "rm":
            for token in segment[1:]:
                if token == "--":
                    break
                if token.startswith("--"):
                    if len(token) >= 3 and "--recursive".startswith(token):
                        return "recursive_rm"
                    continue
                if token.startswith("-") and "r" in token[1:].lower():
                    return "recursive_rm"
        elif name == "chmod":
            options_done = False
            for token in segment[1:]:
                if not options_done and token == "--":
                    options_done = True
                    continue
                if not options_done and token.startswith("--reference="):
                    break
                if not options_done and token.startswith("-"):
                    continue
                if token in {"777", "0777"}:
                    return "world_writable"
                break

    for index in range(len(segments) - 1):
        if leading_separators[index + 1] != "|":
            continue
        if _command_basename(segments[index]) != "curl":
            continue
        if _command_basename(segments[index + 1]) in {"sh", "bash"}:
            return "curl_pipe_shell"
    return None


def _pretool_output(classification: str | None = None) -> dict:
    decision: dict = {"hookEventName": "PreToolUse"}
    reasons = {
        "background": "run_in_background is blocked; use bg_create(type=run) instead.",
        "recursive_rm": "Recursive rm is blocked; move targets to trash instead.",
        "world_writable": "World-writable chmod is blocked; use a least-privilege mode.",
        "curl_pipe_shell": "Direct curl-to-shell is blocked; inspect downloaded content first.",
    }
    if classification in reasons:
        decision["permissionDecision"] = "deny"
        decision["permissionDecisionReason"] = reasons[classification]
    return {"hookSpecificOutput": decision}


def _make_pretooluse_hooks(classifier):
    if not callable(classifier):
        logger.error("managed Bash PreToolUse hook unavailable; failed open: classifier is not callable")
        return None

    # Resolve the module-level classifier at call time so a live hook cannot retain a
    # stale implementation after a controlled code reload, and tests can exercise failures.
    uses_module_classifier = classifier is _classify_bash_payload

    async def _bash_pretooluse(payload, _tool_use_id=None, _context=None):
        tool_input = payload.get("tool_input") if isinstance(payload, dict) else {}
        try:
            if isinstance(tool_input, dict) and tool_input.get("run_in_background") is True:
                return _pretool_output("background")
            active_classifier = globals().get("_classify_bash_payload") if uses_module_classifier else classifier
            result = await asyncio.wait_for(
                asyncio.to_thread(active_classifier, tool_input),
                timeout=_BASH_CLASSIFIER_TIMEOUT,
            )
            if result is not None and (
                not isinstance(result, str) or result not in _BASH_CLASSIFICATIONS
            ):
                raise _InvalidBashClassification
            return _pretool_output(result)
        except asyncio.TimeoutError as exc:
            logger.error(
                "managed Bash PreToolUse failed open (%s): classifier deadline exceeded",
                type(exc).__name__,
            )
        except _InvalidBashClassification:
            logger.error("managed Bash PreToolUse failed open: invalid classifier result")
        except Exception as exc:
            logger.error(
                "managed Bash PreToolUse failed open (%s): classifier failure",
                type(exc).__name__,
            )
        return _pretool_output()

    return [HookMatcher(matcher="Bash", hooks=[_bash_pretooluse])]


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


# Above 2^53 an integer no longer survives a float64 JSON parse, and every hop between the
# model and an MCP server that is written in JS does exactly that parse. 19-digit ids are
# normal for Yandex.Direct, Telegram and Discord. A schema typed `string` rejects the rounded
# value loudly; a schema that accepts `number` takes it silently and the write lands on
# somebody else's object. See docs/tasks/129/research.md.
_FLOAT64_SAFE_INT = 2 ** 53


def _oversized_ints(value, path: str = ""):
    """Yield (json path, value) for every int in a tool argument that exceeds 2^53."""
    if isinstance(value, bool):
        return
    if isinstance(value, int):
        if abs(value) > _FLOAT64_SAFE_INT:
            yield path or "<root>", value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _oversized_ints(item, f"{path}.{key}")
    elif isinstance(value, list):
        for i, item in enumerate(value):
            yield from _oversized_ints(item, f"{path}[{i}]")


class ClaudeBackend:
    def __init__(self, model: str, cwd: str, system_prompt: str = "",
                 resume_session_id: str | None = None,
                 mcp_servers: dict | None = None,
                 is_orchestrator: bool = False,
                 scope_mcp_servers: dict | None = None,
                 config_dir: str = "",
                 inherit_claude_md: bool = True,
                 user_mcp_servers: dict | None = None,
                 effort: str | None = None,
                 history_import: object | None = None,
                 validation_profile: bool = False):
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
        self._effort = effort
        if history_import is not None and not isinstance(history_import, ClaudeHistoryImport):
            raise TypeError("history_import must be ClaudeHistoryImport")
        self._history_import = history_import
        self._validation_profile = validation_profile
        self._client: Optional[ClaudeSDKClient] = None
        self._session_id: str | None = resume_session_id
        self.resume_failed = False
        self._stderr_tail = ""
        self._pending_model_error = ""
        # SDK content events point at parent tool_use_id, while Task* lifecycle
        # messages use task_id. Keep the bridge so live output and persisted
        # lifecycle records address the same UI card.
        self._subagent_tool_to_task: dict[str, str] = {}
        self._subagent_descriptions: dict[str, str] = {}
        self._subagent_types: dict[str, str] = {}
        # #224: имя файла конфига. Идентичность берём ТОЛЬКО из доверенного сервера
        # `orchestra` — плоский merge сюда пускать нельзя: кастомный сервер со спавна
        # перетирает чужие ключи и может подсунуть `../..` (см. CodexBackend).
        # Суффикс на ЭКЗЕМПЛЯР обязателен: при реконнекте создаётся новый бэкенд той же
        # сессии, и при общем имени файла `disconnect()` старого уносил бы конфиг живого —
        # перезапуск MCP-сервера остался бы без конфигурации.
        self._mcp_config_key = (
            _safe_config_key(
                (self._mcp_servers.get("orchestra", {}).get("env") or {}).get("ORCHESTRA_SESSION_ID")
            )
            + "-" + uuid.uuid4().hex[:8]
        )
        self._mcp_config_path: Path | None = None

    @property
    def session_id(self) -> Optional[str]:
        return self._session_id

    def build_handoff_manifest(self, prepared, *, validation_profile: bool):
        from app.models import get_model_spec

        return build_model_visible_manifest(
            runtime="claude",
            model=self.model,
            effective_window=get_model_spec(self.model).context_length,
            system_prompt=self.system_prompt,
            prepared=prepared,
            validation_profile=validation_profile,
            project_docs=getattr(prepared, "project_docs", ()),
            mcp_servers={
                **self._user_mcp_servers,
                **self._scope_mcp_servers,
                **self._mcp_servers,
            },
        )

    def handoff_expected_capabilities(self) -> dict:
        from app.models import get_model_spec

        tool_material = self._expected_normal_tool_material()
        return {
            "runtime": "claude",
            "model": self.model,
            "effective_window": get_model_spec(self.model).context_length,
            "cli_version": CLAUDE_CLI_HISTORY_VERSION,
            "sdk_version": CLAUDE_SDK_HISTORY_VERSION,
            "system_prompt_sha256": hashlib.sha256(
                self.system_prompt.encode("utf-8")
            ).hexdigest(),
            "normal_tool_fingerprint": hashlib.sha256(
                _json.dumps(
                    tool_material,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
            "validation_surface": "sdk-tools-empty",
            "raw_ref_runtime_tool": False,
        }

    def _expected_normal_tool_material(self) -> dict:
        merged_mcp = {
            **self._user_mcp_servers,
            **self._scope_mcp_servers,
            **self._mcp_servers,
        }
        return {
            "builtin_surface": {
                "preset": "claude_code",
                "cli_version": CLAUDE_CLI_HISTORY_VERSION,
            },
            "tools": None,
            "allowed_tools": [],
            "disallowed_tools": _disallowed_tools(self._is_orchestrator),
            "mcp_servers": merged_mcp,
            "setting_sources": (
                ["user", "project", "local"]
                if self._inherit_claude_md else ["local"]
            ),
            "permission_mode": "default",
            "can_use_tool": True,
            "hooks": (
                {"PreToolUse": [{
                    "matcher": "Bash", "hook_count": 1, "timeout": None,
                }]}
                if os.environ.get("CLAUDE_BASH_HOOK_ENABLED") == "1"
                else {}
            ),
        }

    async def verify_handoff_validation_surface(self) -> dict:
        """Prove the pinned CLI and the SDK options that removed all tools."""
        if not self._validation_profile or self._client is None:
            return {"ok": False, "validation_tools_empty": False}
        versions = await self._verify_pinned_versions()
        options = self._client.options
        tools_empty = (
            options.tools == []
            and options.allowed_tools == []
            and options.disallowed_tools == ["*"]
            and not options.mcp_servers
            and options.setting_sources == ["local"]
        )
        return {
            "ok": tools_empty,
            "validation_tools_empty": tools_empty,
            "raw_ref_runtime_tool": False,
            **versions,
        }

    def _normal_options_tool_material(self) -> dict:
        if self._client is None:
            return {}
        options = self._client.options
        configured_mcp: dict = {}
        if options.mcp_servers:
            try:
                if isinstance(options.mcp_servers, (str, Path)):
                    configured_mcp = _json.loads(
                        Path(options.mcp_servers).read_text()
                    ).get("mcpServers", {})
                elif isinstance(options.mcp_servers, dict):
                    configured_mcp = dict(options.mcp_servers)
            except (OSError, ValueError, TypeError):
                return {}
        hooks = {}
        for event, matchers in (options.hooks or {}).items():
            hooks[str(event)] = [
                {
                    "matcher": getattr(matcher, "matcher", None),
                    "hook_count": len(getattr(matcher, "hooks", ()) or ()),
                    "timeout": getattr(matcher, "timeout", None),
                }
                for matcher in matchers
            ]
        return {
            "builtin_surface": {
                "preset": "claude_code",
                "cli_version": CLAUDE_CLI_HISTORY_VERSION,
            },
            "tools": options.tools,
            "allowed_tools": list(options.allowed_tools or []),
            "disallowed_tools": list(options.disallowed_tools or []),
            "mcp_servers": configured_mcp,
            "setting_sources": list(options.setting_sources or []),
            "permission_mode": options.permission_mode,
            "can_use_tool": callable(options.can_use_tool),
            "hooks": hooks,
        }

    async def verify_handoff_normal_surface(
        self,
        *,
        prepared,
        expected_configuration_sha256: str,
        expected_descriptor: dict,
    ) -> dict:
        """Inspect the connected normal client before the source is released."""
        if self._validation_profile or self._client is None:
            return {"ok": False, "failure": {
                "kind": "capability_unsupported", "structured": True,
                "detail": "normal handoff client is not connected",
            }}
        try:
            versions = await self._verify_pinned_versions()
            options = self._client.options
            manifest = self.build_handoff_manifest(
                prepared, validation_profile=False
            )
            context = await self.context_usage()
            query = getattr(self._client, "_query", None)
            initialization = getattr(query, "_initialization_result", None)
            mcp_status = (
                await query.get_mcp_status()
                if query is not None and callable(getattr(query, "get_mcp_status", None))
                else None
            )
            tool_material = self._normal_options_tool_material()
            tool_fingerprint = hashlib.sha256(_json.dumps(
                tool_material,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")).hexdigest()
            context_available = bool(
                isinstance(context, dict)
                and isinstance(context.get("total_tokens"), int)
                and int(context["total_tokens"]) >= 0
                and isinstance(context.get("max_tokens"), int)
                and int(context["max_tokens"]) > 0
            )
            live_preflight = None
            if context_available:
                live_preflight = preflight_provider_context(
                    native_context_tokens=int(context["total_tokens"]),
                    effective_window=min(
                        int(manifest.effective_window), int(context["max_tokens"])
                    ),
                    configuration_sha256=manifest.configuration_sha256,
                )
            options_match = bool(
                options.model == self.model
                and options.resume == self.session_id
                and options.system_prompt is None
                and tool_material
                and tool_fingerprint
                == expected_descriptor.get("normal_tool_fingerprint")
            )
            initialization_ok = bool(
                isinstance(initialization, dict)
                and isinstance(initialization.get("commands"), list)
                and isinstance(initialization.get("agents"), list)
                and isinstance(initialization.get("models"), list)
            )
            expected_mcp_names = set(tool_material.get("mcp_servers") or {})
            live_mcp_names = {
                str(item.get("name") or "")
                for item in (
                    mcp_status.get("mcpServers", [])
                    if isinstance(mcp_status, dict) else []
                )
                if isinstance(item, dict) and item.get("name")
            }
            mcp_surface_ok = bool(
                isinstance(mcp_status, dict)
                and expected_mcp_names == live_mcp_names
            )
            versions_match = all(
                versions.get(key) == expected_descriptor.get(key)
                for key in ("cli_version", "sdk_version")
            )
            configuration_match = (
                manifest.configuration_sha256 == expected_configuration_sha256
            )
            ok = bool(
                options_match
                and initialization_ok
                and mcp_surface_ok
                and versions_match
                and configuration_match
                and live_preflight is not None
                and live_preflight.fits
            )
            failure = None
            if live_preflight is not None and not live_preflight.fits:
                failure = {
                    "kind": "context_overflow",
                    "structured": True,
                    "detail": "normal target live context does not fit reserves",
                }
            elif not ok:
                failure = {
                    "kind": "capability_unsupported",
                    "structured": True,
                    "detail": "normal target live capability receipt mismatch",
                }
            surface = {
                "initialization": {
                    key: initialization.get(key)
                    for key in (
                        "commands", "agents", "output_style",
                        "available_output_styles", "models",
                    )
                    if isinstance(initialization, dict) and key in initialization
                },
                "tool_material": tool_material,
                "mcp_status": mcp_status,
            }
            return {
                "ok": ok,
                "failure": failure,
                "configuration_sha256": manifest.configuration_sha256,
                "normal_tool_fingerprint": tool_fingerprint,
                "live_surface_sha256": hashlib.sha256(_json.dumps(
                    surface,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")).hexdigest(),
                "live_context_preflight": (
                    live_preflight.as_dict() if live_preflight else None
                ),
                **versions,
            }
        except NativeHistoryImportError as error:
            return {"ok": False, "failure": {
                "kind": "capability_unsupported", "structured": True,
                "detail": err_text(error),
            }}
        except Exception as error:
            return {"ok": False, "failure": {
                "kind": type(error).__name__, "structured": False,
                "detail": err_text(error),
            }}

    def _write_mcp_config(self, servers: dict) -> Path:
        """Записать конфиг MCP в приватный файл и вернуть путь.

        Каталог держим вне любого чекаута: worktree удаляются вместе с воркерами, а
        конфиг обязан пережить весь коннект. `/tmp` тоже не годится — там tmpfs (RAM).
        """
        for name, cfg in servers.items():
            # Одинокие суррогатные кодовые точки из caller-supplied JSON не кодируются в
            # UTF-8 и уронили бы саму запись файла — отказываем ЯВНО, называя сервер.
            if any("\ud800" <= ch <= "\udfff" for ch in str(name)):
                raise ValueError(f"MCP server name contains a lone surrogate: {name!r}")
            kind = cfg.get("type") if isinstance(cfg, dict) else None
            if kind is not None and kind not in ("stdio", "http", "sse"):
                # in-process sdk-сервер — объект в памяти, файлом его не объявить.
                # Молча потерять его тулы нельзя: падаем громко (#224 T7).
                raise ValueError(
                    f"MCP server '{name}' has type={kind!r}: such a server cannot be "
                    f"declared in a config file and its tools would be silently lost"
                )
        root = Path.home() / ".orchestra" / "mcp-config"
        root.mkdir(parents=True, exist_ok=True)
        os.chmod(root, 0o700)
        path = root / f"{self._mcp_config_key}.json"
        # Сразу 0600 и атомарно: окно 0644 между созданием и chmod — тот самый зазор,
        # через который эта задача и текла; а os.replace не даёт прочитать полуфайл.
        tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "w") as fh:
                fh.write(_json.dumps({"mcpServers": servers}))
            os.chmod(tmp, 0o600)
            os.replace(tmp, path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        self._mcp_config_path = path
        return path

    def _remove_mcp_config(self) -> None:
        if self._mcp_config_path is None:
            return
        try:
            self._mcp_config_path.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("could not remove MCP config %s: %s", self._mcp_config_path, exc)
        self._mcp_config_path = None

    def replace_history_import(self, history_import: ClaudeHistoryImport) -> None:
        if not isinstance(history_import, ClaudeHistoryImport):
            raise TypeError("history_import must be ClaudeHistoryImport")
        expected_session_id = self._session_id or self._resume_id
        if expected_session_id and history_import.session_id != expected_session_id:
            raise ValueError(
                "replacement history must keep the current Claude session id"
            )
        self._history_import = history_import

    def _make_client(self) -> ClaudeSDKClient:
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
        pretooluse_hooks = None
        if os.environ.get("CLAUDE_BASH_HOOK_ENABLED") == "1":
            pretooluse_hooks = _make_pretooluse_hooks(_classify_bash_payload)
        options = ClaudeAgentOptions(
            model=self.model, cwd=self.cwd, cli_path=cli,
            permission_mode="default", can_use_tool=_make_auto_approve(self._is_orchestrator),
            disallowed_tools=_disallowed_tools(self._is_orchestrator),
            hooks={"PreToolUse": pretooluse_hooks} if pretooluse_hooks is not None else None,
            include_partial_messages=True, max_turns=200,
            max_buffer_size=50 * 1024 * 1024,
            env=env,
            user=agent_uid,
            stderr=self._capture_stderr,
        )
        if self._validation_profile:
            # The validation turn has no authority to perform work. ``tools=[]`` is
            # the SDK's mechanical surface control; prompt instructions are not used.
            options.tools = []
            options.allowed_tools = []
            options.disallowed_tools = ["*"]
        if self._effort:
            eff = self._effort
            if eff == "xhigh" and "claude" in (self.model or ""):
                eff = "high"
            options.effort = eff
        if self._history_import:
            options.resume = self._history_import.session_id
            options.session_store = ClaudeLogSessionStore(self._history_import)
            options.system_prompt = {
                "type": "preset",
                "preset": "claude_code",
                "append": f"{self.system_prompt}\n\n{HISTORICAL_TOOL_INSTRUCTION}",
            }
        elif resume_id:
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
            # #224: dict SDK сериализует прямо в argv (subprocess_cli.py:384-390), а str/Path
            # отдаёт как путь (391-393). Значения секретов в argv читает процесс ЛЮБОГО uid —
            # hidepid не включён. Отдаём путь к файлу 600.
            options.mcp_servers = str(self._write_mcp_config(merged_mcp))
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

    async def _verify_pinned_versions(self) -> dict[str, str]:
        sdk_version = importlib.metadata.version("claude-agent-sdk")
        if sdk_version != CLAUDE_SDK_HISTORY_VERSION:
            raise NativeHistoryUnsupported(
                "native Claude history requires claude-agent-sdk "
                f"{CLAUDE_SDK_HISTORY_VERSION}, got {sdk_version}"
            )
        cli = shutil.which("claude") or os.environ.get("CLAUDE_CLI_PATH", "claude")
        try:
            process = await asyncio.create_subprocess_exec(
                cli,
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as error:
            raise NativeHistoryUnsupported(
                f"cannot verify Claude CLI history version: {err_text(error)}"
            ) from error
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=10)
        except asyncio.TimeoutError as error:
            process.kill()
            await process.wait()
            raise NativeHistoryUnsupported(
                f"cannot verify Claude CLI history version: {err_text(error)}"
            ) from error
        version_text = (stdout or stderr).decode(errors="replace").strip()
        actual_version = version_text.split(maxsplit=1)[0] if version_text else ""
        if process.returncode != 0 or actual_version != CLAUDE_CLI_HISTORY_VERSION:
            actual = version_text or f"exit {process.returncode}"
            raise NativeHistoryUnsupported(
                f"native Claude history requires CLI {CLAUDE_CLI_HISTORY_VERSION}, got {actual}"
            )
        return {"cli_version": actual_version, "sdk_version": sdk_version}

    async def _verify_history_versions(self) -> None:
        if self._history_import:
            await self._verify_pinned_versions()

    def _history_rejection(self, error: BaseException) -> NativeHistoryRejected | None:
        if not self._history_import:
            return None
        detail = f"{err_text(error)}\n{self._stderr_tail}".lower()
        markers = (
            "no conversation found with session id",
            "invalid transcript",
            "failed to parse transcript",
            "malformed transcript",
        )
        if not any(marker in detail for marker in markers):
            return None
        return NativeHistoryRejected(
            "Claude 2.1.197 rejected Orchestra-rendered SessionStore history"
        )

    async def _cleanup_failed_client(self) -> None:
        if self._client:
            try:
                await self._client.disconnect()
            except BaseException:
                pass
            self._client = None

    async def connect(self) -> None:
        self.resume_failed = False
        self._stderr_tail = ""
        await self._verify_history_versions()
        self._client = self._make_client()
        try:
            await asyncio.wait_for(self._client.connect(), timeout=60)
        except BaseException as e:
            await self._cleanup_failed_client()
            history_rejection = self._history_rejection(e)
            if history_rejection:
                raise history_rejection from e
            if self._history_import:
                logger.error(
                    "ClaudeBackend history connect failed: %s%s",
                    err_text(e),
                    f" | stderr: {self._stderr_tail[-1000:]}" if self._stderr_tail else "",
                )
                raise
            if (
                not isinstance(e, asyncio.CancelledError)
                and (self._session_id or self._resume_id)
                and not self._resume_transcript_exists()
            ):
                stale_id = self._session_id or self._resume_id
                logger.warning(
                    "Claude resume transcript %s is missing; starting fresh transport",
                    str(stale_id)[:8],
                )
                self._session_id = None
                self._resume_id = None
                self.resume_failed = True
                self._client = self._make_client()
                try:
                    await asyncio.wait_for(self._client.connect(), timeout=60)
                    return
                except BaseException as fresh_error:
                    await self._cleanup_failed_client()
                    logger.error(
                        "ClaudeBackend fresh connect after stale resume failed: %s%s",
                        err_text(fresh_error),
                        f" | stderr: {self._stderr_tail[-1000:]}" if self._stderr_tail else "",
                    )
                    raise
            logger.error(
                "ClaudeBackend connect failed: %s%s",
                err_text(e),
                f" | stderr: {self._stderr_tail[-1000:]}" if self._stderr_tail else "",
            )
            raise

    def _capture_stderr(self, line: str) -> None:
        self._stderr_tail = (self._stderr_tail + str(line))[-4000:]

    def _resume_transcript_exists(self) -> bool:
        resume_id = self._session_id or self._resume_id
        if not resume_id:
            return False
        if self._config_dir:
            root = Path(os.path.expanduser(self._config_dir))
        elif os.environ.get("CLAUDE_CONFIG_DIR"):
            root = Path(os.path.expanduser(os.environ["CLAUDE_CONFIG_DIR"]))
        else:
            root = Path.home() / ".claude"
        projects = root / "projects"
        if not projects.is_dir():
            return False
        try:
            return next(projects.glob(f"**/{resume_id}.jsonl"), None) is not None
        except OSError:
            return False

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

    async def interrupt(self) -> bool:
        """Interrupt the active turn, returning whether the CLI acknowledged it.

        The SDK's control request waits up to 60 seconds by default. Orchestra needs a
        short bound so a broken control channel cannot leave the Stop request hanging;
        the session layer hard-disconnects this backend when False is returned.
        """
        if not self._client:
            return True
        try:
            await asyncio.wait_for(
                self._client.interrupt(),
                timeout=CLAUDE_INTERRUPT_TIMEOUT,
            )
            return True
        except asyncio.TimeoutError:
            logger.error(
                "ClaudeBackend interrupt was not acknowledged within %.1fs",
                CLAUDE_INTERRUPT_TIMEOUT,
            )
            return False
        except Exception as e:
            logger.warning(f"ClaudeBackend interrupt failed: {e}")
            return False

    async def disconnect(self) -> None:
        client = self._client
        try:
            if client:
                await client.disconnect()
        except Exception as e:
            logger.warning(f"ClaudeBackend disconnect failed: {e}")
            raise
        finally:
            self._client = None
            # Владелец жизненного цикла конфига — сам бэкенд: файл обязан жить
            # весь коннект и удаляться даже при ошибке SDK disconnect.
            self._remove_mcp_config()

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
        try:
            await self._verify_history_versions()
        finally:
            await self.disconnect()
        await asyncio.sleep(2)
        self._client = self._make_client()
        try:
            await asyncio.wait_for(self._client.connect(), timeout=60)
        except BaseException as e:
            logger.error(f"ClaudeBackend reconnect failed: {e}")
            await self._cleanup_failed_client()
            raise

    @staticmethod
    def _task_usage(usage) -> dict:
        """Extract TaskUsage (total_tokens/tool_uses/duration_ms) — TypedDict or obj."""
        if not usage:
            return {}
        get = usage.get if isinstance(usage, dict) else lambda k, d=0: getattr(usage, k, d)
        return {
            "total_tokens": get("total_tokens", 0) or 0,
            "tool_uses": get("tool_uses", 0) or 0,
            "duration_ms": get("duration_ms", 0) or 0,
        }

    def _resolve_subagent_id(self, parent_tool_use_id):
        if parent_tool_use_id is None:
            return None
        return self._subagent_tool_to_task.get(
            str(parent_tool_use_id),
            str(parent_tool_use_id),
        )

    @staticmethod
    def _tag_sub(event: AgentEvent, sub_id) -> AgentEvent:
        """Mark an event as belonging to a sub-agent so the UI nests it.

        sub_id None (main agent) → event unchanged. Otherwise stamp subagent_id;
        the type is preserved (tool_use stays tool_use) — the frontend groups by
        subagent_id, not by a renamed type."""
        if sub_id is not None:
            event.metadata = {**event.metadata, "subagent_id": sub_id}
        return event

    def _convert(self, msg) -> list[AgentEvent]:
        events = []
        if isinstance(msg, StreamEvent):
            # Main-agent text partials → "stream". Subagent partials (parent_tool_use_id
            # set) → "subagent_stream" tagged with sub_id so the UI nests them under the
            # sub-agent block instead of dropping them (which looked like a hang).
            ev = msg.event or {}
            if ev.get("type") != "content_block_delta":
                return events
            delta = ev.get("delta") or {}
            if delta.get("type") != "text_delta":
                return events
            text = delta.get("text") or ""
            if not text:
                return events
            sub_id = self._resolve_subagent_id(msg.parent_tool_use_id)
            if sub_id is not None:
                events.append(AgentEvent("subagent_stream", text, metadata={"subagent_id": sub_id}))
            else:
                events.append(AgentEvent("stream", text))
            return events

        if isinstance(msg, AssistantMessage):
            # Subagent messages carry parent_tool_use_id → tag events so the UI groups
            # them under the sub-agent block instead of mixing with the parent's stream.
            sub_id = self._resolve_subagent_id(
                getattr(msg, "parent_tool_use_id", None)
            )
            for block in msg.content:
                if isinstance(block, TextBlock) and block.text:
                    events.append(self._tag_sub(AgentEvent("text", block.text), sub_id))
                elif isinstance(block, ThinkingBlock) and block.thinking:
                    events.append(self._tag_sub(AgentEvent("thinking", block.thinking), sub_id))
                elif isinstance(block, ToolUseBlock):
                    try:
                        inp = _json.dumps(block.input, ensure_ascii=False, indent=2)
                    except Exception:
                        inp = str(block.input)
                    for field, big in _oversized_ints(block.input):
                        logger.warning(
                            "big-int tool arg: %s %s = %d exceeds 2^53 — precision is not "
                            "guaranteed past a JS JSON.parse; ids must be passed as strings",
                            block.name, field, big,
                        )
                    short_name = block.name.split('__')[-1] if '__' in block.name else block.name
                    events.append(self._tag_sub(AgentEvent("tool_use", f"{block.name}: {inp}",
                                             metadata={
                                                 "tool_name": block.name,
                                                 "short_name": short_name,
                                                 "tool_use_id": block.id,
                                             }), sub_id))
                elif isinstance(block, (ToolResultBlock, ServerToolResultBlock)):
                    events.append(self._tag_sub(AgentEvent(
                        "tool_result",
                        _extract_tool_result(block),
                        metadata={
                            "tool_use_id": getattr(block, "tool_use_id", "") or "",
                            "is_error": bool(getattr(block, "is_error", False)),
                        },
                    ), sub_id))
            err = getattr(msg, "error", None)
            if err:
                self._pending_model_error = str(err)
                events.append(AgentEvent(
                    "error",
                    f"model error: {err}",
                    metadata={"model_error": str(err)},
                ))

        elif isinstance(msg, UserMessage):
            sub_id = self._resolve_subagent_id(
                getattr(msg, "parent_tool_use_id", None)
            )
            if hasattr(msg, 'content') and isinstance(msg.content, list):
                for block in msg.content:
                    if isinstance(block, (ToolResultBlock, ServerToolResultBlock)):
                        events.append(self._tag_sub(AgentEvent(
                            "tool_result",
                            _extract_tool_result(block),
                            metadata={
                                "tool_use_id": getattr(block, "tool_use_id", "") or "",
                                "is_error": bool(getattr(block, "is_error", False)),
                            },
                        ), sub_id))

        elif isinstance(msg, TaskStartedMessage):
            desc = getattr(msg, "description", "") or ""
            task_type = getattr(msg, "task_type", "") or ""
            task_id = getattr(msg, "task_id", "") or ""
            tool_use_id = getattr(msg, "tool_use_id", "") or ""
            if task_id:
                self._subagent_descriptions[task_id] = desc
                self._subagent_types[task_id] = task_type
            if task_id and tool_use_id:
                self._subagent_tool_to_task[tool_use_id] = task_id
            events.append(AgentEvent(
                "subagent_start",
                f"{desc} | type={task_type} | id={task_id} | "
                f"tool_use_id={tool_use_id}",
                                     metadata={"subagent_id": task_id, "phase": "start",
                                               "description": desc, "task_type": task_type,
                                               "sdk_session_id": getattr(msg, "session_id", "") or "",
                                               "tool_use_id": tool_use_id}))

        elif isinstance(msg, TaskProgressMessage):
            desc = getattr(msg, "description", "") or ""
            last_tool = getattr(msg, "last_tool_name", "") or ""
            task_id = getattr(msg, "task_id", "") or ""
            tool_use_id = getattr(msg, "tool_use_id", "") or ""
            if task_id and desc:
                self._subagent_descriptions[task_id] = desc
            if task_id and tool_use_id:
                self._subagent_tool_to_task[tool_use_id] = task_id
            desc = desc or self._subagent_descriptions.get(task_id, "")
            task_type = self._subagent_types.get(task_id, "")
            u = self._task_usage(getattr(msg, "usage", None))
            events.append(AgentEvent("subagent_progress",
                                     f"{desc} | type={task_type} | id={task_id} | "
                                     f"tool_use_id={tool_use_id} | tool={last_tool} | "
                                     f"tokens={u.get('total_tokens', 0)}",
                                     metadata={"subagent_id": task_id, "phase": "progress",
                                               "description": desc, "task_type": task_type,
                                               "last_tool_name": last_tool,
                                               "sdk_session_id": getattr(msg, "session_id", "") or "",
                                               "tool_use_id": tool_use_id,
                                               **u}))

        elif isinstance(msg, TaskNotificationMessage):
            status = getattr(msg, "status", "") or ""
            summary = getattr(msg, "summary", "") or ""
            task_id = getattr(msg, "task_id", "") or ""
            tool_use_id = getattr(msg, "tool_use_id", "") or ""
            if task_id and tool_use_id:
                self._subagent_tool_to_task[tool_use_id] = task_id
            desc = self._subagent_descriptions.get(task_id, "")
            task_type = self._subagent_types.get(task_id, "")
            output_file = getattr(msg, "output_file", "") or ""
            u = self._task_usage(getattr(msg, "usage", None))
            data = getattr(msg, "data", None)
            events.append(AgentEvent(
                "subagent_end",
                f"{desc} | type={task_type} | id={task_id} | "
                f"tool_use_id={tool_use_id} | status={status} | {summary[:500]}",
                                     metadata={"subagent_id": task_id, "phase": "end",
                                               "description": desc, "task_type": task_type,
                                               "status": status,
                                               "summary": summary, "output_file": output_file,
                                               "sdk_session_id": getattr(msg, "session_id", "") or "",
                                               "tool_use_id": tool_use_id,
                                               "raw_json": _json.dumps(data, ensure_ascii=False) if data else "",
                                               **u}))

        elif isinstance(msg, ResultMessage):
            sr = getattr(msg, "stop_reason", None) or "unknown"
            nt = getattr(msg, "num_turns", 0) or 0
            if msg.session_id:
                self._session_id = msg.session_id

            model_error = self._pending_model_error
            self._pending_model_error = ""
            is_err = bool(getattr(msg, "is_error", False) or model_error)
            err_list = list(getattr(msg, "errors", None) or [])
            if model_error and model_error not in err_list:
                err_list.append(model_error)
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

            turn_usage = TurnUsage(
                AggregateUsage.normalized(
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cache_read_tokens=cache_read,
                    cache_create_tokens=cache_create,
                    model_calls=nt or None,
                ),
                deferred_context(max_tokens, "claude_context_usage"),
            )
            events.append(AgentEvent("turn_end", f"stop_reason={sr}, num_turns={nt}", metadata={
                "event_id": getattr(msg, "uuid", None) or "",
                "session_id": self._session_id,
                "ok": not is_err,
                "is_error": is_err,
                "errors": err_list,
                "model_error": model_error,
                "stop_reason": sr,
                "num_turns": nt,
                "cost_usd": cost,
                "cost_usd_cached": round(cost_cached, 6),
                "cache_hit": cache_hit,
                **turn_usage.metadata(),
            }, usage=turn_usage))

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
