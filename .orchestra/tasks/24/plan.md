# #24 — MCP per agent — PLAN

## Decision recap (from orchestrator)
- Option A: persist custom servers. New column `mcp_servers_custom TEXT DEFAULT ''` on `sessions`.
- Store ONLY the custom part (never the `orchestra` server).
- Re-merge in `_load_from_db` so custom servers survive restart.
- Guard `orchestra` key — log a warning if custom config tries to override it; drop it.
- Codex limitation — document, don't fix.

## Data model
- `sessions.mcp_servers_custom` — JSON string of the custom-only dict `{name: {command, args, env, ...}}`. Empty string = none.
- The runtime `AgentSession.mcp_servers` always = `{orchestra: ...}` merged with custom. Never persisted as a whole (orchestra config is reconstructed); only the custom part is stored.

## Changes

### 1. `app/db.py` — schema + migration + save/persist
- **Schema** (`init_db`, sessions CREATE TABLE): no change needed to CREATE for fresh DBs IF we add the column there too — but to keep one source of truth, add `mcp_servers_custom TEXT DEFAULT ''` to the CREATE TABLE AND a `_migrate` ALTER for existing DBs.
  - Add to CREATE TABLE sessions (after `color TEXT DEFAULT ''` or near other text cols).
  - In `_migrate`: `if "mcp_servers_custom" not in cols: c.execute("ALTER TABLE sessions ADD COLUMN mcp_servers_custom TEXT DEFAULT ''")`.
- **`save_session`**: add `s.setdefault("mcp_servers_custom", "")`; add column to INSERT column list, VALUES, and ON CONFLICT DO UPDATE SET.

### 2. `app/session.py` — carry + persist the custom part
- Add dataclass field: `mcp_servers_custom: dict = field(default_factory=dict, repr=False)` (the custom-only dict, kept separately so persistence stores exactly it).
- `_to_db_dict`: add `"mcp_servers_custom": json.dumps(self.mcp_servers_custom) if self.mcp_servers_custom else ""`.
  - `json` already imported in session.py (used by `_load_scope_mcp_servers`).

### 3. `app/manager.py` — merge helper + create + resume
- **`_make_mcp_config(name, scope, role, extra: dict | None = None)`**: after building the orchestra entry, merge:
  ```python
  cfg = {"orchestra": {...}}
  if extra:
      for k, v in extra.items():
          if k == "orchestra":
              logger.warning(f"custom MCP server '{k}' would override Orchestra MCP — ignored")
              continue
          cfg[k] = v
  return cfg
  ```
- **`create_session(..., mcp_servers: dict | None = None)`**: 
  - Sanitize: strip `orchestra` key from incoming custom dict up front (so the stored custom part is clean), keep the rest as `custom`.
  - Pass `extra=custom` to `_make_mcp_config`.
  - Set `session.mcp_servers_custom = custom` (so `_to_db_dict` persists it). Set via constructor kwarg.
- **`_load_from_db`**: read `db_row.get("mcp_servers_custom")`, JSON-parse, pass as `extra` to `_make_mcp_config(...)` AND set `mcp_servers_custom=` on the reconstructed session. This is the restart-survival path.
  - **Codex #24-1 (ACK):** parsed JSON MUST be type-checked. If the column holds a non-object JSON (`[]`, `"x"`, `null`), `_make_mcp_config(extra=...)` would crash on `extra.items()` and break restart-survival for that session. Use a shared sanitizer:
    ```python
    def _parse_custom_mcp(raw) -> dict:
        if not raw:
            return {}
        try:
            v = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            logger.warning("invalid mcp_servers_custom JSON; ignoring"); return {}
        if not isinstance(v, dict):
            logger.warning(f"mcp_servers_custom is not an object ({type(v).__name__}); ignoring"); return {}
        return {k: val for k, val in v.items() if k != "orchestra"}
    ```
    Use the SAME sanitizer on the create-path (before storing) and the load-path (after reading). Single source of truth for sanitization.

### 4. `app/main.py` — request model + passthrough
- `CreateSessionRequest`: add `mcp_servers: dict = {}`.
- `create_session` endpoint: pass `mcp_servers=req.mcp_servers` to `manager.create_session`.

### 5. `app/mcp_stdio.py` — spawn_worker param
- Add `mcp_servers: str = ""` (JSON string) to `spawn_worker` signature.
- Parse:
  ```python
  custom = {}
  if mcp_servers:
      try:
          custom = json.loads(mcp_servers)
          if not isinstance(custom, dict):
              return "Error: mcp_servers must be a JSON object {name: {command, args, env}}"
      except json.JSONDecodeError as e:
          return f"Error: invalid mcp_servers JSON: {e}"
  ```
  `json` already imported in mcp_stdio.py.
- Add `if custom: body["mcp_servers"] = custom`.
- Update the tool docstring to document the param shape AND the Codex limitation: "Custom MCP servers attach to Claude workers; for Codex workers only their env vars are propagated."

### 6. `_spawn_worker_loop` (queue path)
- The queue job dict (`enqueue_worker_spawn`) → `create_session`. Add `mcp_servers=job.get("mcp_servers")` to the `create_session` call in `_spawn_worker_loop` for completeness. (Current HTTP spawn path does NOT use the queue, but keep parity.)

## Merge semantics
Runtime `mcp_servers` = `{orchestra: <always>} ∪ custom(minus orchestra)`. Stored `mcp_servers_custom` = custom(minus orchestra). On resume, re-merge → identical runtime config. Orchestra server is authoritative and never overridable.

## What NOT to touch
- Do NOT touch `_load_scope_mcp_servers` (scope-level file MCP) — orthogonal, keeps working.
- Do NOT change Codex backend MCP handling.
- Do NOT persist the orchestra server entry.

## Tests
`tests/test_manager.py`:
1. `test_make_mcp_config_merges_custom` — extra server appears alongside orchestra.
2. `test_make_mcp_config_custom_cannot_override_orchestra` — custom `orchestra` key ignored, default kept.
3. `test_create_session_persists_custom_mcp` — create with mcp_servers, then `get_session_by_name` row has `mcp_servers_custom` JSON with the custom server.
4. `test_load_from_db_restores_custom_mcp` — seed DB row with `mcp_servers_custom`, `_load_from_db` → session.mcp_servers contains both orchestra + custom.

`tests/test_mcp_stdio.py`:
5. `test_spawn_worker_invalid_mcp_json` — bad JSON string → error message, no spawn.
6. (if existing spawn tests mock _api) assert body includes mcp_servers when valid.

`tests/test_db.py`:
7. `test_save_session_roundtrips_mcp_custom` — save with mcp_servers_custom, read back equal.

## Risks / edge cases
- Old DB rows have no column until `_migrate` runs → default `''` → parsed to `{}` → only orchestra. Safe.
- `mcp_servers_custom` empty string vs `{}` — `_to_db_dict` stores `''` when empty; loader treats `''`/None as `{}`.
- Pydantic `dict` type rejects non-object JSON at API layer; MCP layer also guards.
- Large/secret env in custom servers persisted to DB — acceptable (same as INTERNAL_TOKEN handling); note it.
