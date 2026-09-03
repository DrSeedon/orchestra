#!/usr/bin/env python3
"""Mutation check: does the conformance gate actually catch broken MCP wiring?

Connect-only (no turn), printing the marker before every phase:
  1. baseline      — clean wiring                     -> must CONNECT
  2. mutant-shadow — `.mcp.json` declaring `orchestra` -> must REFUSE and name the file
  3. reverted      — file removed again                -> must CONNECT
  4. mutant-cmd    — launch plan points at a missing binary -> must REFUSE
  5. reverted-cmd  — plan restored                     -> must CONNECT

The mutations are data (a JSON file, an in-memory plan), not `.py` source, so there is no
`__pycache__` staleness to defeat — the reverted phases re-run the same module objects.
"""
import asyncio, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from app.backend_grok import GrokBackend, GrokMcpIsolationError
from app.manager import _make_mcp_config

MCP_JSON = ROOT / ".mcp.json"
SHADOW = json.dumps({"mcpServers": {"orchestra": {
    "type": "stdio", "command": "/nonexistent/python",
    "args": ["-m", "app.mcp_stdio"], "env": {"ORCHESTRA_ROLE": "shadow"}}}}, indent=2)


async def attempt(label: str, break_command: bool = False) -> str:
    servers = _make_mcp_config(f"grok-mut-{label}", "/home/kesha/orchestra", "worker")
    if break_command:
        servers["orchestra"]["command"] = "/nonexistent/python3"
    mcp_env = {k: str(v) for cfg in servers.values() for k, v in cfg.get("env", {}).items()}
    backend = GrokBackend(model="grok-4.5", cwd=str(ROOT), system_prompt="t",
                          mcp_env=mcp_env, mcp_servers=servers, reasoning_effort="low")
    try:
        await backend.connect()
        return f"CONNECTED tools={backend._mcp_tool_count} ready={sorted(backend._ready_servers)}"
    except GrokMcpIsolationError as exc:
        return f"REFUSED {exc}"
    except Exception as exc:
        return f"ERROR {type(exc).__name__}: {exc}"
    finally:
        await backend.disconnect()


async def phase(name: str, *, shadow: bool = False, break_command: bool = False) -> None:
    print(f"[{name}] .mcp.json present = {MCP_JSON.exists()}", flush=True)
    print(f"  -> {await attempt(name, break_command=break_command)}\n", flush=True)


async def main() -> None:
    await phase("baseline")

    MCP_JSON.write_text(SHADOW, encoding="utf-8")
    await phase("mutant-shadow")

    MCP_JSON.unlink()
    await phase("reverted")

    await phase("mutant-cmd", break_command=True)
    await phase("reverted-cmd")


asyncio.run(main())
