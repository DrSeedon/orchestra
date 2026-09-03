# Report: Worker Visibility Between Orchestrators

## What was done

3 changes to limit worker visibility between orchestrators and prevent "two masters" conflicts:

1. **Prompt visibility** (`manager.py`) — `_workers_block()` now filters workers by `parent_name`. Orchestrator's system prompt shows only its own workers under "Your current workers" and other orchestrators' workers under "Other orchestrators' workers" with a warning not to task them directly. Legacy workers (empty `parent_name`) are treated as "mine" for backward compatibility.

2. **list_agents grouping** (`mcp_stdio.py`) — Output is now grouped into 3 sections: Orchestrators, Your workers, Other orchestrators' workers. Foreign workers show their owner name. Warning text discourages direct tasking.

3. **send_message warning** (`mcp_stdio.py` + `main.py`) — When sending to a worker owned by a different orchestrator, the MCP tool returns a warning suggesting to message the owner orchestrator instead. The send API now exposes `parent_name` in its response.

## Files changed
- `app/manager.py` (+31/-10) — `_workers_block(scope, orchestrator_name)`, `ROLE_SYSTEM_PROMPT(role, scope, name)`, 4 call sites updated
- `app/mcp_stdio.py` (+34/-3) — `list_agents()` grouping, `send_message()` warning, `_ORCH_ROLES` constant
- `app/main.py` (+2/-1) — expose `parent_name` in send response

## Tests
- 199 passed, 5 skipped, 6 pre-existing failures (all confirmed on main)
- 54 manager + mcp_stdio tests pass (0 new failures)
- Pre-existing failures: `test_remove_deletes`, `test_passes_orch_names`, 4x `test_auto_report_*` (missing AUTO_REPORT_IDLE_SEC)

## Breaking changes
None. `parent_name` in send response is additive. Empty `parent_name` handled as legacy (shows in "your workers").

## Codex review
Codex CLI was 403-blocked (Cloudflare). Self-reviewed instead.
