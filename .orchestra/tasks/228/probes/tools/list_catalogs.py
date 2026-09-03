"""List MCP tools from disposable Orchestra MCP subprocesses."""

import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


ROOT = Path(__file__).resolve().parents[5]


async def catalog(role: str, access_mode: str) -> dict:
    env = {
        **os.environ,
        "ORCHESTRA_ROLE": role,
        "ORCHESTRA_ACCESS_MODE": access_mode,
        "ORCHESTRA_URL": "http://127.0.0.1:9",
        "ORCHESTRA_SCOPE": str(ROOT),
        "WORKER_NAME": f"probe-{role}",
        "PARENT_NAME": "probe-parent" if role == "worker" else "",
        "INTERNAL_TOKEN": "",
    }
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "app.mcp_stdio"],
        cwd=str(ROOT),
        env=env,
    )
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            result = await session.list_tools()
            return {
                "role": role,
                "access_mode": access_mode,
                "count": len(result.tools),
                "names": sorted(tool.name for tool in result.tools),
            }


async def main() -> None:
    results = []
    for role in ("orchestrator", "worker"):
        for access_mode in ("full", "read-only"):
            results.append(await catalog(role, access_mode))
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
