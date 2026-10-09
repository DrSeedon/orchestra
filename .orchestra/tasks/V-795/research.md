# V-795 — MCP tools in `claude -p` workflow calls

Question: with mcp=True, are scope MCP server tools auto-denied in `run_claude` (they are not in `--allowedTools`)?

Measurement (HEAD 8609532e, 2026-10-09): scratch git repo /tmp/v795scope with `.mcp.json` declaring a stdio FastMCP server `probe` exposing read tool `echo_ping` (returns `PROBE-TOKEN-7731`). Workflow run `V-795-b3` (wf_run.py from worktree, one `haiku` task, tools=all, network=True, mcp=True defaults), prompt: call `echo_ping` and answer with the string. Result: `PROBE-TOKEN-7731`, cost $0.0026, complete. The server was connected and the tool executed with only `--tools Read,Write,Edit,Glob,Grep,WebFetch,WebSearch --allowedTools <same>`.

Conclusion: no denial; `claude -p --strict-mcp-config --mcp-config` MCP tools are not blocked by the permission gate nor filtered by `--tools` in this CLI version. No code change. Limit: one server, one read tool, stdio transport; servers needing their own approval or other transports untested (the real seedon `yandex-direct` was not called to avoid touching an ad account).
