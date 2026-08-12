"""Side-effect-free MCP server used by the #228 enforcement probes."""

from mcp.server.fastmcp import FastMCP


mcp = FastMCP("probe")


@mcp.tool()
def ping() -> str:
    """Return a fixed value without reading or changing external state."""
    return "probe-pong"


@mcp.tool()
def second() -> str:
    """A second inert tool for exact-name filtering checks."""
    return "probe-second"


if __name__ == "__main__":
    mcp.run(transport="stdio")
