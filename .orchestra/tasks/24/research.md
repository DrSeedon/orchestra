# #24 — MCP per agent — RESEARCH

## Goal
Allow `spawn_worker` to attach custom MCP servers to a worker, merged with the default Orchestra MCP server.

## Current architecture (how MCP gets to a worker)

1. **`manager._make_mcp_config(name, scope, role)`** (`app/manager.py:238`) builds the dict:
   ```python
   {"orchestra": {"command": ..., "args": ..., "env": {...}, "alwaysLoad": True}}
   ```
   This is the ONLY MCP config produced today. It is assigned to `AgentSession.mcp_servers` both in `create_session` (line 341) and in `_load_from_db` (line 505).

2. **`AgentSession.mcp_servers`** (`app/session.py:79`) — a dict field, passed to `ClaudeBackend(mcp_servers=...)` in `_make_backend` (line 138).

3. **Scope-level MCP** already exists: `_load_scope_mcp_servers(scope)` (`app/session.py:30`) reads `.claude/settings.json`, `.claude/settings.local.json`, `.mcp.json` from the scope dir and passes them as `scope_mcp_servers` to ClaudeBackend (line 140). It strips any key named `orchestra`. **So there is already a precedent for merging extra servers** — but it's file-based per-scope, not per-spawn.

4. **Codex backend** (`backend_codex`) ignores `mcp_servers` dict structure except to flatten `env` vars via `_build_codex_mcp_env` (`app/session.py:148`). Custom MCP servers would NOT reach a Codex worker the same way — only their env vars get flattened. Worth noting as a limitation.

## Data flow for the new param

`spawn_worker(mcp_servers=JSON str)` → MCP stdio
  → POST `/api/sessions` body `mcp_servers` (dict)
  → `CreateSessionRequest.mcp_servers` (`app/main.py:91`)
  → `manager.create_session(mcp_servers=...)`
  → merge into `_make_mcp_config` result
  → `AgentSession.mcp_servers`

## Files that will be affected
- `app/mcp_stdio.py` — `spawn_worker` tool: add `mcp_servers: str = ""` (JSON string), parse, include in POST body.
- `app/main.py` — `CreateSessionRequest`: add `mcp_servers: dict = {}`. Pass to `manager.create_session`.
- `app/manager.py`:
  - `_make_mcp_config(name, scope, role, extra: dict | None = None)` — merge extra servers (never let them override `"orchestra"`).
  - `create_session(..., mcp_servers: dict | None = None)` — pass extra to `_make_mcp_config`.
  - `_spawn_worker_loop` — forward `job.get("mcp_servers")` (only relevant if spawn goes through the queue; current HTTP path calls create_session directly, queue path is for `enqueue_worker_spawn`).
- Tests: `tests/test_manager.py`, `tests/test_mcp_stdio.py`.

## Persistence problem (CRITICAL EDGE CASE)
`_load_from_db` (`app/manager.py:466`) **rebuilds** `mcp_servers` from `_make_mcp_config(name, scope, role)` on every server restart/resume — it does NOT read custom servers from DB. So if we only pass custom servers at `create_session` time, **they are LOST on restart** (the worker resumes with only the default `orchestra` server).

Options:
- **A. Persist custom servers** — add a `mcp_servers TEXT` (JSON) column to `sessions`, store the *custom* part, re-merge in `_load_from_db`. Survives restart. More work (migration + serialize/deserialize).
- **B. Don't persist** — custom MCP only lives for the current process lifetime. Simpler, but a restart silently drops the worker's custom tools. Surprising/fragile.

The task spec (#24) does not mention restart survival, but #26 (cron) explicitly requires "survive restart", implying persistence is a project value. **Recommend Option A** — persist the custom (non-orchestra) part in a new column, re-merge on resume. This matches the existing `_load_scope_mcp_servers` philosophy (extra servers always reconstructed) but for per-spawn config we need DB storage since it's not file-derived.

## Risks / edge cases
- **`orchestra` key collision**: custom dict must never override the default orchestra server. Merge order: start with orchestra, then add custom keys, explicitly drop/skip a custom `"orchestra"` key (log a warning).
- **Invalid JSON** from `spawn_worker` string param → return a clear error, don't crash the spawn.
- **`mcp_servers` must be `dict`** at the API layer; if someone passes a non-dict, Pydantic rejects it.
- **Codex workers**: custom servers only contribute env vars, not actual MCP connections. Document this; don't silently pretend it works.
- Empty/missing `mcp_servers` = current behavior unchanged (only orchestra).

## External references
- claude-agent-sdk `mcp_servers` config shape: `{name: {"command", "args", "env", ...}}` — matches existing `_make_mcp_config` and `_load_scope_mcp_servers`.

## Recommendation
Implement with **persistence (Option A)**: new `mcp_servers` column storing the custom-only JSON, merged on both create and resume. Guard the `orchestra` key. Validate JSON in the MCP tool layer.
