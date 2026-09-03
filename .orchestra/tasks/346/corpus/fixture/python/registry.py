from python.framework import mcp, router


@router.post("/api/models/refresh")  # G346_R2_ROUTE_DECORATOR
def refresh_models_endpoint() -> dict:  # G346_R2_ROUTE_DEF
    return {"ok": True}


@mcp.tool()  # G346_R2_TOOL_DECORATOR
def update_progress(percent: int) -> dict:  # G346_R2_TOOL_DEF
    return {"percent": percent}


MOUNTED_ROUTERS = [router]  # G346_R2_ROUTER_MOUNT
MCP_MANAGER = mcp  # G346_R2_TOOL_MOUNT

