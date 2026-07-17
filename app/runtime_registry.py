"""Agent runtime registry and backend construction.

Models/providers describe what is called; runtimes describe the agent harness used
to call it (Claude Code SDK, Codex CLI, OpenCode, or an external plugin).
"""

from __future__ import annotations

import importlib
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

from app.backend_protocol import BackendLike

logger = logging.getLogger(__name__)

EventStreamMode = Literal["persistent", "per_turn"]


@dataclass(frozen=True)
class RuntimeCapabilities:
    event_stream: EventStreamMode
    mid_turn_inject: bool
    reconnect: bool
    hibernate: bool
    process_liveness: bool = False
    resume: bool = True
    resume_across_models: bool = True
    subagents: bool = True

    def to_dict(self) -> dict:
        return {
            "event_stream": self.event_stream,
            "mid_turn_inject": self.mid_turn_inject,
            "reconnect": self.reconnect,
            "hibernate": self.hibernate,
            "process_liveness": self.process_liveness,
            "resume": self.resume,
            "resume_across_models": self.resume_across_models,
            "subagents": self.subagents,
        }


@dataclass(frozen=True)
class BackendBuildContext:
    model: str
    provider: str
    cwd: str
    system_prompt: str
    resume_session_id: str | None
    mcp_servers: dict
    is_orchestrator: bool
    scope: str
    pipeline: str
    role: str
    profile: str
    effort: str | None
    context_limit: int


@dataclass(frozen=True)
class RuntimeDefinition:
    id: str
    capabilities: RuntimeCapabilities
    factory: Callable[[BackendBuildContext], BackendLike]


_RUNTIMES: dict[str, RuntimeDefinition] = {}
_PLUGINS_LOADED = False


def register_runtime(definition: RuntimeDefinition, *, replace: bool = False) -> None:
    if not definition.id:
        raise ValueError("runtime id must not be empty")
    if definition.id in _RUNTIMES and not replace:
        raise ValueError(f"runtime '{definition.id}' is already registered")
    _RUNTIMES[definition.id] = definition


def unregister_runtime(runtime_id: str) -> None:
    if runtime_id in BUILTIN_RUNTIMES:
        raise ValueError(f"cannot unregister builtin runtime '{runtime_id}'")
    _RUNTIMES.pop(runtime_id, None)


def load_runtime_plugins() -> None:
    """Import admin-configured plugins; each module calls register_runtime()."""
    global _PLUGINS_LOADED
    if _PLUGINS_LOADED:
        return
    _PLUGINS_LOADED = True
    for module_name in os.environ.get("ORCHESTRA_RUNTIME_PLUGINS", "").split(","):
        module_name = module_name.strip()
        if module_name:
            importlib.import_module(module_name)


def get_runtime(runtime_id: str) -> RuntimeDefinition:
    load_runtime_plugins()
    try:
        return _RUNTIMES[runtime_id]
    except KeyError as exc:
        raise ValueError(f"unknown agent runtime '{runtime_id}'") from exc


def build_backend(runtime_id: str, context: BackendBuildContext) -> BackendLike:
    definition = get_runtime(runtime_id)
    backend = definition.factory(context)
    if not isinstance(backend, BackendLike):
        raise TypeError(f"runtime '{runtime_id}' returned an incompatible backend")
    if definition.capabilities.reconnect and not callable(
        getattr(backend, "reconnect", None)
    ):
        raise TypeError(f"runtime '{runtime_id}' declares reconnect without reconnect()")
    if definition.capabilities.process_liveness and not hasattr(backend, "is_alive"):
        raise TypeError(f"runtime '{runtime_id}' declares process_liveness without is_alive")
    return backend


def _load_scope_mcp_servers(scope: str) -> dict:
    servers = {}
    for name in ("settings.json", "settings.local.json"):
        path = Path(scope) / ".claude" / name
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text())
            for key, value in data.get("mcpServers", {}).items():
                if key != "orchestra":
                    servers[key] = value
        except Exception as exc:
            logger.warning("Failed to parse MCP servers from %s: %s", path, exc)
    mcp_json = Path(scope) / ".mcp.json"
    if mcp_json.is_file():
        try:
            data = json.loads(mcp_json.read_text())
            for key, value in data.get("mcpServers", {}).items():
                if key != "orchestra":
                    servers[key] = value
        except Exception as exc:
            logger.warning("Failed to parse .mcp.json from %s: %s", mcp_json, exc)
    return servers


def _load_user_mcp_servers(config_dir: str) -> dict:
    """Load profile-level Claude MCP servers without allowing Orchestra override."""
    servers: dict = {}
    base = Path(os.path.expanduser(config_dir)) if config_dir else Path.home()
    path = base / ".claude.json"
    if not path.is_file():
        return servers
    try:
        data = json.loads(path.read_text())
        for key, value in data.get("mcpServers", {}).items():
            if key != "orchestra":
                servers[key] = value
    except Exception as exc:
        logger.warning("Failed to parse user MCP servers from %s: %s", path, exc)
    return servers


def _claude_factory(context: BackendBuildContext) -> BackendLike:
    from app.backend_claude import ClaudeBackend
    from app.db import get_profile
    from app.pipeline import get_role

    try:
        role = get_role(context.pipeline, context.role)
    except FileNotFoundError:
        role = None
    inherit = role.inherit_claude_md if role else True
    config_dir = ""
    if context.profile:
        profile = get_profile(context.profile)
        config_dir = profile["config_dir"] if profile else ""
    user_mcp = (
        _load_user_mcp_servers(config_dir)
        if role is not None and role.mcp_servers == "all"
        else {}
    )
    return ClaudeBackend(
        model=context.model,
        cwd=context.cwd,
        system_prompt=context.system_prompt,
        resume_session_id=context.resume_session_id,
        mcp_servers=context.mcp_servers,
        is_orchestrator=context.is_orchestrator,
        scope_mcp_servers=_load_scope_mcp_servers(context.scope),
        config_dir=config_dir,
        inherit_claude_md=inherit,
        user_mcp_servers=user_mcp,
        effort=context.effort,
    )


def _codex_factory(context: BackendBuildContext) -> BackendLike:
    from app.backend_codex import CodexBackend
    from app.pipeline import get_role
    from app.prompting import read_skills_content

    try:
        role = get_role(context.pipeline, context.role)
    except FileNotFoundError:
        role = None
    skills = role.skills if role and isinstance(role.skills, list) else []
    skills_block = read_skills_content(skills)
    mcp_env = {
        key: str(value)
        for config in context.mcp_servers.values()
        for key, value in config.get("env", {}).items()
    }
    return CodexBackend(
        model=context.model,
        cwd=context.cwd,
        system_prompt=context.system_prompt + skills_block,
        resume_thread_id=context.resume_session_id,
        mcp_env=mcp_env,
        mcp_servers=context.mcp_servers,
        reasoning_effort=context.effort or "high",
    )


def _opencode_factory(context: BackendBuildContext) -> BackendLike:
    from app.backend_opencode import OpenCodeBackend

    return OpenCodeBackend(
        model=context.model,
        cwd=context.cwd,
        system_prompt=context.system_prompt,
        resume_session_id=context.resume_session_id,
        mcp_servers=context.mcp_servers,
        is_orchestrator=context.is_orchestrator,
        context_limit=context.context_limit,
        provider_id=context.provider,
    )


BUILTIN_RUNTIMES = ("claude", "codex", "opencode")

register_runtime(RuntimeDefinition(
    id="claude",
    capabilities=RuntimeCapabilities(
        event_stream="persistent",
        mid_turn_inject=True,
        reconnect=True,
        hibernate=True,
    ),
    factory=_claude_factory,
))
register_runtime(RuntimeDefinition(
    id="codex",
    capabilities=RuntimeCapabilities(
        event_stream="per_turn",
        mid_turn_inject=False,
        reconnect=False,
        hibernate=False,
        process_liveness=True,
        resume_across_models=False,
    ),
    factory=_codex_factory,
))
register_runtime(RuntimeDefinition(
    id="opencode",
    capabilities=RuntimeCapabilities(
        event_stream="per_turn",
        mid_turn_inject=False,
        reconnect=False,
        hibernate=False,
        process_liveness=True,
    ),
    factory=_opencode_factory,
))
