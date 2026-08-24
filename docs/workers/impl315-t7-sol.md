# impl315-t7-sol

- FastMCP tool retirement can preserve old in-process callers by removing only `@mcp.tool()`; verify the real registry after `_apply_access_mode()`, and add the replacement tool to reducer/read-only positive whitelists.
