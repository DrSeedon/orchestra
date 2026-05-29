# #25 — validate_spawn — RESEARCH

## Goal
Add `can_spawn: [role1, role2]` to role YAML frontmatter. On `spawn_worker`, validate that the **parent** (spawner) role is allowed to spawn the **child** role. Empty/absent `can_spawn` = anything allowed.

## Current architecture

### Role frontmatter parsing
- `_parse_role_frontmatter(text)` (`app/manager.py:92`) — splits `---` YAML, returns `(meta, body)`.
- Role files live in `app/prompts/roles/*.md`: `orchestrator.md`, `worker.md`, `full-cycle.md`.
- Frontmatter fields already used: `name`, `label`, `model`, `skills`, `when`, `not_for`, `description`, `prompt`.
- `_roles_catalog()` (`app/manager.py:166`) already reads frontmatter per role file — good template for a `_read_role_meta(role)` helper.

### Who is the "parent"?
In `create_session` (`app/manager.py:305`):
- `parent_name` is passed in, or resolved via `_find_orchestrator_name(scope)` for non-orchestrators (line 328-329).
- The spawner of a worker via `spawn_worker` MCP tool is identified by `WORKER_NAME` env in `mcp_stdio.py`. **BUT** `spawn_worker` currently does NOT pass any `parent_name` / sender to the API. The POST body (`app/mcp_stdio.py:67`) has no parent field.

This is the crux: **to validate "parent role allows child role", we need the parent's role.** Today the parent role is not transmitted on spawn.

### How to get the parent role
The MCP server knows `WORKER_NAME` (the caller) and `ROLE` (env `ORCHESTRA_ROLE`) — see `app/mcp_stdio.py:22-23`. So the spawner's own role IS available in the MCP process as the `ROLE` env var.

Two ways to validate:
- **A. Validate in `create_session`** by looking up the parent session's role from DB/registry using `parent_name`. Requires `spawn_worker` to send `parent_name`. Robust — parent role is authoritative from the session record.
- **B. Send the caller's role directly** from MCP (`ROLE` env) as `parent_role` in the POST body, validate against it. Simpler, but trusts the env var.

Option A is cleaner (single source of truth = session record) and `parent_name` is already a `create_session` param + `CreateSessionRequest` field (`app/main.py:104`). We just need `spawn_worker` to populate it with `WORKER_NAME`.

## Files affected
- `app/prompts/roles/orchestrator.md` — add `can_spawn` (e.g. all worker roles). Actually orchestrator should be able to spawn anything → leave `can_spawn` absent (= allow all), OR list explicitly. Per spec, absent = allow all, so orchestrator needs no change unless we want to restrict.
- `app/manager.py`:
  - New helper `_role_can_spawn(role) -> list[str] | None` reading `can_spawn` from frontmatter.
  - In `create_session`: after resolving parent, if parent has a role with non-empty `can_spawn` and child `role` not in it → raise `ValueError`.
- `app/mcp_stdio.py` — `spawn_worker`: send `parent_name=WORKER_NAME` in POST body (so parent can be resolved). Note: orchestrator's `WORKER_NAME` env is its own name.
- Tests: `tests/test_manager.py`.

## Risks / edge cases
- **Parent not found** (no parent_name resolvable, e.g. top-level orchestrator spawn): can't determine parent role → **allow** (fail-open). Spec says empty/absent can_spawn = allow; absent parent should also not block.
- **Parent role file missing** `can_spawn` → allow all.
- **Empty list `can_spawn: []`** — spec says "Пустой can_spawn ... = разрешено всё". So `[]` = allow all (treat empty list same as absent). Confirmed by spec wording.
- **Case sensitivity** of role names — match exactly as written in frontmatter / role param.
- **Self-spawn / recursion** — not in scope, ignore.
- **Existing spawn flow must not break**: orchestrator (no can_spawn) spawning worker/full-cycle must still work → fail-open covers it.
- **API consistency**: `create_session` is also called directly (not just via spawn_worker) — e.g. orchestrator creation, tests. Those pass no parent or a parent without can_spawn → allowed. Good.

## Where validation must live
Put it in `manager.create_session` (not just the API endpoint) so it's enforced regardless of entry point, and so tests can target it directly. The `_spawn_worker_loop` queue path also calls `create_session`, so it's covered.

## Recommendation
Option A: `spawn_worker` sends `parent_name=WORKER_NAME`; `create_session` resolves parent role and validates `can_spawn`. Fail-open when parent role unknown or `can_spawn` empty/absent. Add a `_role_can_spawn` helper mirroring `_load_role_skills`.
