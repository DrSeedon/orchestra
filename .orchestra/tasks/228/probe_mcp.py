"""Side-effect-free MCP server used by the #228 enforcement measurements."""

from mcp.server.fastmcp import FastMCP


mcp = FastMCP("probe")


@mcp.tool()
def echo_marker(value: str) -> str:
    return f"PROBE:{value}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
