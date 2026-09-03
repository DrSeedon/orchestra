# research-serena-agents

- Before any ephemeral Serena start: snapshot user `~/.serena/serena_config.yml` hash+mtime; assert `SERENA_HOME` is non-empty, resolves under the task scratch root, and appears non-empty in final argv; abort before launch otherwise; verify the user hash+mtime unchanged after every arm. Empty means fallback to user state and can rewrite the config while creating a log (#346).
- Codex CLI 0.149.1 `exec -c mcp_servers.*` can parse in `codex mcp list` yet still expose no MCP tool to Luna; forced-use positive control is mandatory before counting an MCP treatment. Removed `tool_search` flags and under-development code-mode flags did not fix this direct-CLI path in #346.
- For Serena/LSP evaluation, score semantic references separately from production-entry edges. Combining them hides the exact useful boundary: #346 measured semantic recall 1.0 and decorator/string/HTML/root-edge recall 0.125 on the same healthy server.
