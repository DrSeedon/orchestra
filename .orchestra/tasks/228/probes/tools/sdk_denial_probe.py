"""Exercise SDK permission denial and Orchestra's event conversion without a DB."""

import asyncio
import dataclasses
import json
import sys
from pathlib import Path

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKClient,
    PermissionResultAllow,
    PermissionResultDeny,
)

from app.backend_claude import ClaudeBackend


HERE = Path(__file__).resolve().parent


def plain(value):
    if dataclasses.is_dataclass(value):
        return {field.name: plain(getattr(value, field.name)) for field in dataclasses.fields(value)}
    if isinstance(value, list):
        return [plain(item) for item in value]
    if isinstance(value, dict):
        return {key: plain(item) for key, item in value.items()}
    return value


async def permission(tool_name, tool_input, _context):
    if tool_name == "mcp__probe__ping":
        return PermissionResultDeny(message="DENIED_BY_PROBE_EXACT_MCP_TOOL")
    return PermissionResultAllow(updated_input=tool_input)


async def main() -> None:
    options = ClaudeAgentOptions(
        model="claude-sonnet-4-6",
        cwd=str(HERE),
        cli_path="/usr/bin/claude",
        system_prompt="Use tools exactly as requested. Be concise.",
        mcp_servers={
            "probe": {
                "command": sys.executable,
                "args": [str(HERE / "probe_server.py")],
            }
        },
        strict_mcp_config=True,
        setting_sources=[],
        permission_mode="default",
        can_use_tool=permission,
        max_turns=4,
        extra_args={"no-session-persistence": None},
    )
    converter = ClaudeBackend(model="claude-sonnet-4-6", cwd=str(HERE))
    async with ClaudeSDKClient(options=options) as client:
        await client.query(
            "Call mcp__probe__ping exactly once. If it is denied, report the exact denial text."
        )
        async for message in client.receive_response():
            raw = plain(message)
            events = [plain(event) for event in converter._convert(message)]
            print(json.dumps({"sdk_message": raw, "orchestra_events": events}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
