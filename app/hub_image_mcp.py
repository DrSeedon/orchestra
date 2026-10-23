"""Small stdio MCP server for subscription hub image generation."""

from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent
from pydantic import Field

from app.hub_image import generate_image

mcp = FastMCP("Orchestra hub images")


@mcp.tool()
async def hub_generate_image(
    prompt: Annotated[str, Field(min_length=1, max_length=16000)],
    count: Annotated[int, Field(ge=1, le=4)] = 1,
    size: str = "",
    timeout_seconds: Annotated[int, Field(ge=1, le=1800)] = 300,
) -> CallToolResult:
    """Draw images using hub Codex's built-in generator; return local PNG paths.

    Size is a prompt hint (auto, WIDTHxHEIGHT or aspect such as 16:9), not an
    enforced pixel size. Uses the hub subscription, with no paid API fallback.
    Total bound is timeout_seconds plus at most 60 seconds for cleanup.
    """
    import json

    result = await generate_image(prompt, count=count, size=size, timeout_seconds=timeout_seconds)
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(result))],
                          isError=not result["ok"], structuredContent=result)


if __name__ == "__main__":
    mcp.run(transport="stdio")
