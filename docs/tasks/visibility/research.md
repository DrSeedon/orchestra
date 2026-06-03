# Research: Worker Visibility Between Orchestrators

## Current Architecture

### 1. `_workers_block()` in `manager.py:67-85`
Generates the "Your current workers" section for orchestrator system prompts.
**Bug**: Filters by `scope == scope` only — shows ALL non-orchestrator workers in the scope, regardless of who spawned them. A sub-orchestrator sees workers of the parent orchestrator and vice versa.

### 2. `list_agents()` in `mcp_stdio.py:176-197`
MCP tool for agents. Lists all sessions in scope with no grouping or ownership info. Every orchestrator sees every worker as if it were their own.

### 3. `send_message()` in `mcp_stdio.py:165-172`
No ownership check. Returns "Message sent to '{to}'" with no warning about cross-ownership.

### 4. Session data model (`session.py`, `db.py`)
- `parent_name` field exists on all sessions, set at spawn time via `spawn_worker` → `create_session`
- Available in both `to_dict()` (runtime) and DB `get_all_sessions()` (persistence)
- Orchestrators spawned without parent have `parent_name == ""`

## Files Affected

| File | Function | Change |
|------|----------|--------|
| `app/manager.py` | `_workers_block()` | Filter by `parent_name == orchestrator_name` |
| `app/mcp_stdio.py` | `list_agents()` | Group by ownership (your workers vs others) |
| `app/mcp_stdio.py` | `send_message()` | Add warning when messaging foreign worker |

## Key Considerations

1. **Orchestrator name identification**: `_workers_block()` doesn't receive the orchestrator name — it receives `scope`. Need to pass orchestrator name or infer it. Looking at callers: `ROLE_SYSTEM_PROMPT()` → called from `create_session()` and `_load_from_db()` where name IS available.

2. **`list_agents()` caller identity**: The MCP tool knows its caller via `WORKER_NAME` env var (set in `_make_mcp_config`). This is the calling agent's name — available globally.

3. **Legacy compatibility**: Workers spawned before `parent_name` was introduced have `parent_name == ""`. These should still appear (as "unowned" or in current orchestrator's list for backward compat).

4. **`_workers_block` signature change**: Currently `_workers_block(scope: str)`. Need to add `orchestrator_name` param. Callers in `ROLE_SYSTEM_PROMPT()` don't have the name — but `create_session()` and `_load_from_db()` do, so we can thread it through.

## Risks

- **Prompt injection size**: If many "other workers" exist, the prompt grows. Keep it compact — just names with parent attribution.
- **WORKER_NAME reliability**: Already used for spawn, send_message sender — proven reliable.
- **Empty parent_name**: Legacy sessions — show them in "your workers" for the root orchestrator, or as "unowned" for sub-orchestrators. Simplest: show in "your workers" if parent_name is empty (backward compatible).
