#!/usr/bin/env python3
"""One-shot runtime adapters for scripted workflows."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import shutil
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_create_tokens: int = 0


@dataclass(frozen=True)
class AdapterResult:
    text: str
    runtime: str
    model: str
    ok: bool
    stop_reason: str
    cost_usd: float | None
    usage: Usage = field(default_factory=Usage)
    cost_unaccounted: bool = False
    error: str = ""


def _nonnegative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"invalid {name}: {value!r}")
    return value


def parse_codex_output(raw: str, model: str) -> AdapterResult:
    messages: list[str] = []
    completions: list[dict] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        item = row.get("item") if isinstance(row, dict) else None
        if isinstance(item, dict) and item.get("type") == "agent_message":
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                messages.append(text.strip())
        if isinstance(row, dict) and row.get("type") == "turn.completed":
            completions.append(row.get("usage") or {})
    if len(completions) != 1:
        raise ValueError(f"Codex reported {len(completions)} completed usage events")
    if not messages:
        raise ValueError("Codex reported no agent message")
    usage = completions[0]
    values = {
        key: _nonnegative_int(usage.get(key, 0), f"Codex {key}")
        for key in (
            "input_tokens",
            "output_tokens",
            "cached_input_tokens",
            "cache_write_input_tokens",
        )
    }
    if values["input_tokens"] + values["output_tokens"] == 0:
        raise ValueError("Codex completed turn reported zero tokens")
    from app.backend_codex import _codex_cost

    return AdapterResult(
        text=messages[-1],
        runtime="codex",
        model=model,
        ok=True,
        stop_reason="end_turn",
        cost_usd=_codex_cost(
            model,
            values["input_tokens"],
            values["cached_input_tokens"],
            values["cache_write_input_tokens"],
            values["output_tokens"],
        ),
        usage=Usage(
            input_tokens=values["input_tokens"],
            output_tokens=values["output_tokens"],
            cache_read_tokens=values["cached_input_tokens"],
            cache_create_tokens=values["cache_write_input_tokens"],
        ),
    )


def parse_claude_output(raw: str, model: str) -> AdapterResult:
    try:
        row = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError(f"Claude returned invalid JSON: {error}") from error
    if not isinstance(row, dict):
        raise ValueError("Claude output is not a JSON object")
    usage = row.get("usage") or {}
    text = row.get("result")
    if row.get("is_error") or not isinstance(text, str) or not text.strip():
        raise ValueError(f"Claude returned no result: {str(row)[:300]}")
    cost = row.get("total_cost_usd")
    if isinstance(cost, bool) or not isinstance(cost, (int, float)) or cost < 0:
        raise ValueError(f"invalid Claude total_cost_usd: {cost!r}")
    return AdapterResult(
        text=text.strip(),
        runtime="claude",
        model=model,
        ok=True,
        stop_reason=str(row.get("stop_reason") or "end_turn"),
        cost_usd=float(cost),
        usage=Usage(
            input_tokens=_nonnegative_int(usage.get("input_tokens", 0), "Claude input_tokens"),
            output_tokens=_nonnegative_int(usage.get("output_tokens", 0), "Claude output_tokens"),
            cache_read_tokens=_nonnegative_int(
                usage.get("cache_read_input_tokens", 0), "Claude cache_read_input_tokens"
            ),
            cache_create_tokens=_nonnegative_int(
                usage.get("cache_creation_input_tokens", 0),
                "Claude cache_creation_input_tokens",
            ),
        ),
    )


def persist_turn_usage(
    *,
    result: AdapterResult,
    event_id: str,
    session_id: str,
    scope: str,
    task_id: str,
) -> bool:
    from app.db import turn_usage_add

    return turn_usage_add(
        event_id=event_id,
        session_id=session_id,
        scope=scope,
        task_id=task_id,
        runtime=result.runtime,
        model=result.model,
        ok=result.ok,
        stop_reason=result.stop_reason,
        cost_usd=result.cost_usd,
        cost_unaccounted=result.cost_unaccounted,
        input_tokens=result.usage.input_tokens,
        output_tokens=result.usage.output_tokens,
        cache_read_tokens=result.usage.cache_read_tokens,
        cache_create_tokens=result.usage.cache_create_tokens,
    )


async def _run_process(
    argv: list[str], prompt: str, cwd: Path, timeout: float,
    *, env: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env or os.environ.copy(),
            start_new_session=True,
        )
    except OSError as error:
        return 127, "", f"{type(error).__name__}: {error}"
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(prompt.encode()), timeout=max(1.0, timeout)
        )
    except asyncio.TimeoutError:
        if proc.returncode is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
            try:
                await asyncio.wait_for(proc.wait(), 3)
            except asyncio.TimeoutError:
                if proc.returncode is None:
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except (ProcessLookupError, PermissionError):
                        pass
                await proc.wait()
        return 124, "", f"timed out after {timeout:g}s"
    return (
        int(proc.returncode or 0),
        stdout.decode("utf-8", errors="replace"),
        stderr.decode("utf-8", errors="replace"),
    )


def _failed(runtime: str, model: str, reason: str, *, stop_reason: str) -> AdapterResult:
    return AdapterResult(
        text="",
        runtime=runtime,
        model=model,
        ok=False,
        stop_reason=stop_reason,
        cost_usd=None,
        cost_unaccounted=True,
        error=reason[:2000],
    )


def _prompt_with_rules(prompt: str, system_prompt: str) -> str:
    if not system_prompt.strip():
        return prompt
    return f"<workflow_rules>\n{system_prompt.strip()}\n</workflow_rules>\n\n{prompt}"


def _claude_tools(tools_level: str, network: bool) -> str:
    if tools_level == "all" and network:
        return "default"
    if tools_level == "all":
        return "Read,Write,Edit,Glob,Grep"
    if tools_level == "read" and network:
        return "Read,Glob,Grep,WebFetch,WebSearch"
    return "Read,Glob,Grep"


def _write_claude_mcp_config(cwd: Path, enabled: bool) -> Path:
    from app.runtime_registry import _load_scope_mcp_servers

    servers = _load_scope_mcp_servers(str(cwd)) if enabled else {}
    path = cwd / ".wf-mcp.json"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump({"mcpServers": servers}, fh, ensure_ascii=False)
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise PermissionError(f"unsafe MCP config permissions: {path}")
    return path


async def run_codex(
    prompt: str, *, model: str, cwd: Path, timeout: float,
    tools: str = "all", network: bool = True, mcp: bool = True,
    system_prompt: str = "", state_dir: Path | None = None,
) -> AdapterResult:
    binary = os.environ.get("WF_CODEX_BIN", "codex")
    sandbox = "danger-full-access" if tools == "all" and network else (
        "workspace-write" if tools == "all" else "read-only"
    )
    argv = [
        binary,
        "-m",
        model,
        "-s",
        sandbox,
        "-a",
        "never",
        "exec",
        "--ephemeral",
        "--ignore-rules",
        "-c",
        f'web_search="{"live" if network else "disabled"}"',
        "--skip-git-repo-check",
        "--json",
        "-",
    ]
    run_env = os.environ.copy()
    private_home = None
    if mcp:
        from app.backend_codex import CodexBackend, _write_private
        from app.runtime_registry import _load_scope_mcp_servers

        root = (state_dir or cwd).resolve()
        root.mkdir(parents=True, exist_ok=True)
        private_home = root / f".wf-codex-home-{uuid4().hex}"
        private_home.mkdir(mode=0o700)
        servers = _load_scope_mcp_servers(str(cwd))
        backend = CodexBackend(model=model, cwd=str(cwd), mcp_servers=servers)
        _write_private(private_home / "config.toml", backend._mcp_servers_toml() + "\n")
        base_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser()
        auth = base_home / "auth.json"
        if auth.is_file():
            (private_home / "auth.json").symlink_to(auth)
        run_env["CODEX_HOME"] = str(private_home)
    else:
        argv.insert(argv.index("--ignore-rules"), "--ignore-user-config")
    try:
        rc, stdout, stderr = await _run_process(
            argv, _prompt_with_rules(prompt, system_prompt), cwd, timeout, env=run_env
        )
    finally:
        if private_home is not None:
            shutil.rmtree(private_home)
    if rc != 0:
        return _failed("codex", model, stderr or stdout or f"exit code {rc}", stop_reason="timeout" if rc == 124 else "error")
    try:
        return parse_codex_output(stdout, model)
    except ValueError as error:
        return _failed("codex", model, str(error), stop_reason="invalid_output")


async def run_claude(
    prompt: str, *, model: str, cwd: Path, timeout: float,
    tools: str = "all", network: bool = True, mcp: bool = True,
    system_prompt: str = "", state_dir: Path | None = None,
) -> AdapterResult:
    binary = os.environ.get("WF_CLAUDE_BIN", "claude")
    mcp_config = _write_claude_mcp_config(cwd, mcp)
    argv = [
        binary,
        "-p",
        "--model",
        model,
        "--output-format",
        "json",
        "--setting-sources",
        "",
        "--strict-mcp-config",
        "--mcp-config",
        str(mcp_config),
        "--tools",
        _claude_tools(tools, network),
    ]
    if system_prompt.strip():
        argv.extend(["--system-prompt", system_prompt.strip()])
    try:
        rc, stdout, stderr = await _run_process(argv, prompt, cwd, timeout)
    finally:
        mcp_config.unlink(missing_ok=True)
    if rc != 0:
        return _failed("claude", model, stderr or stdout or f"exit code {rc}", stop_reason="timeout" if rc == 124 else "error")
    try:
        return parse_claude_output(stdout, model)
    except ValueError as error:
        return _failed("claude", model, str(error), stop_reason="invalid_output")


async def run_harness(
    prompt: str, *, model: str, cwd: Path, timeout: float,
    tools: str = "all", network: bool = True, mcp: bool = True,
    system_prompt: str = "", state_dir: Path | None = None,
) -> AdapterResult:
    from app.harness.oneshot import run_oneshot

    try:
        row = await asyncio.wait_for(
            run_oneshot(
                prompt=prompt, model=model, cwd=cwd, tools_level=tools,
                network=network, mcp=mcp, system_prompt=system_prompt,
            ),
            timeout=max(1.0, timeout),
        )
    except asyncio.TimeoutError:
        return _failed("harness", model, f"timed out after {timeout:g}s", stop_reason="timeout")
    except Exception as error:
        return _failed("harness", model, f"{type(error).__name__}: {error}", stop_reason="error")
    usage = row.get("usage") or {}
    return AdapterResult(
        text=str(row.get("text") or ""),
        runtime="harness",
        model=model,
        ok=bool(row.get("ok")),
        stop_reason=str(row.get("stop_reason") or "error"),
        cost_usd=float(row.get("cost_usd") or 0),
        usage=Usage(
            input_tokens=int(usage.get("input_tokens") or 0),
            output_tokens=int(usage.get("output_tokens") or 0),
        ),
        error=str(row.get("error") or ""),
    )


async def run_adapter(
    prompt: str, *, model: str, cwd: Path, timeout: float,
    tools: str = "all", network: bool = True, mcp: bool = True,
    system_prompt: str = "", state_dir: Path | None = None,
) -> AdapterResult:
    from app.models import backend_for_model

    runtime = backend_for_model(model)
    if runtime == "codex":
        return await run_codex(
            prompt, model=model, cwd=cwd, timeout=timeout, tools=tools,
            network=network, mcp=mcp, system_prompt=system_prompt,
            state_dir=state_dir,
        )
    if runtime == "claude":
        return await run_claude(
            prompt, model=model, cwd=cwd, timeout=timeout, tools=tools,
            network=network, mcp=mcp, system_prompt=system_prompt,
            state_dir=state_dir,
        )
    if runtime == "harness":
        return await run_harness(
            prompt, model=model, cwd=cwd, timeout=timeout, tools=tools,
            network=network, mcp=mcp, system_prompt=system_prompt,
            state_dir=state_dir,
        )
    return _failed(runtime, model, f"runtime '{runtime}' has no wf_run one-shot adapter", stop_reason="unsupported")
