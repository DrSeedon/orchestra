The new conformance check can still accept a worker whose required Orchestra MCP failed whenever another expected MCP provides tools. The added tests cover roster presence and aggregate tool count, but not mixed per-server startup outcomes.

Review comment:

- [P1] Track per-server MCP readiness before accepting startup — /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/grok-quota/app/backend_grok.py:616-619
  When a Grok session has Orchestra plus any scope/user MCP, `_x.ai/mcp/servers_updated` arrives before per-server status and lists configured entries even if one later reports unavailable. Adding every roster entry to `_started_servers` means a failed Orchestra server still satisfies `missing`; if another expected server contributes `mcpToolCount > 0`, `_verify_mcp_isolation()` accepts the connection without Orchestra tools. Track successful readiness and failed statuses per required identity instead of treating the pre-init roster as proof that each server started.

## Round (2026-07-28T14:06:57Z)

Apparently a roster is no longer proof of life—progress 🙃

## Re-review status

- Prior P1 — **FIXED**. Verification now requires per-server readiness, tracks failures, and waits within one shared 20-second deadline. The mixed failure regression correctly rejects unavailable Orchestra despite another ready MCP providing tools: [backend_grok.py](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/grok-quota/app/backend_grok.py:370), [test_backend_grok.py](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/grok-quota/tests/test_backend_grok.py:723).

## New findings

None.

## Verdict

**APPROVED** — no blocking issues found in the requested files.

Verified: `git diff --check` clean; `uv run pytest -q tests/test_backend_grok.py` → **78 passed**.

The roster is finally a guest list, not proof everyone entered the building.
