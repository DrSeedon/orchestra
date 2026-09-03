# research-scaffold-overhead

- If the Codex tool surface omits Orchestra MCP tools, call the local stdio server with the
  installed Python `mcp` client; pass `env=dict(os.environ)`. Omitting `env` clears `PYTHONPATH`
  for the child and `app/mcp_stdio.py` fails before initialize with `ModuleNotFoundError: app`.
- `codex_review` rejects context without the literal structured `PROJECT CONTEXT` block before
  any model call. Include the current repo scale/users/stack/philosophy/severity fields on the
  first attempt.
