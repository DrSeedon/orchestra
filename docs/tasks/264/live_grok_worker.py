#!/usr/bin/env python3
"""Live end-to-end run of a Grok worker through Orchestra's real backend.

Not a hand-rolled ACP client: this builds `GrokBackend` exactly the way `_grok_factory`
does, connects (so `_verify_mcp_isolation` runs for real), and gives the agent a task that
can only be completed by calling an Orchestra MCP tool. Prints the tool calls it made.
"""
import asyncio, os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("ORCHESTRA_SKIP_DOTENV", "0")

from app.backend_grok import GrokBackend
from app.manager import _make_mcp_config

PROMPT = (
    "You are a test worker. Call the Orchestra MCP tool `list_agents` right now and reply "
    "with the number of agents it returned, in the form COUNT=<n>. Do not do anything else."
)


async def main() -> None:
    cwd = str(ROOT)
    assert not (Path(cwd) / ".mcp.json").exists(), (
        "this run must happen in a checkout without the colliding .mcp.json"
    )
    servers = _make_mcp_config("grok-live-264", "/home/kesha/orchestra", "worker")
    mcp_env = {k: str(v) for cfg in servers.values() for k, v in cfg.get("env", {}).items()}
    backend = GrokBackend(
        model="grok-4.5", cwd=cwd,
        system_prompt="You are an Orchestra worker. Be terse.",
        mcp_env=mcp_env, mcp_servers=servers, reasoning_effort="low",
    )
    await backend.connect()
    print(f"CONNECTED session={backend.session_id}")
    print(f"MCP tool count reported by Grok: {backend._mcp_tool_count}")
    print(f"started servers: {sorted(backend._started_servers)}")
    print(f"ready servers:   {sorted(backend._ready_servers)}")

    await backend.send(PROMPT)
    tool_calls, texts = [], []
    try:
        async with asyncio.timeout(240):
            async for ev in backend.events():
                kind = getattr(ev, "type", None) or getattr(ev, "kind", None)
                content = getattr(ev, "content", "")
                if kind == "tool_call":
                    tool_calls.append(content)
                    print(f"TOOL_CALL: {str(content)[:200]}")
                elif kind == "text":
                    texts.append(content)
                elif kind == "turn_end":
                    break
    except (TimeoutError, asyncio.TimeoutError):
        print("TIMEOUT waiting for turn_end")
    finally:
        print("--- assistant text ---")
        print("".join(str(t) for t in texts)[:2000])
        print(f"--- tool calls: {len(tool_calls)} ---")
        await backend.disconnect()


asyncio.run(main())
