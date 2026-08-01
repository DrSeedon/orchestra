# #103 — Implementation report

## Result

Both lifecycle guards now decide whether committed worker content is already represented in the configured base by content, not commit identity. Squash-merged branches can switch or be deleted without manual Git commands, while real worker-only content still blocks before any reset, checkout, branch creation, or removal.

## Tickets

- **T1 complete:** `branch_content_status()` keeps the ancestry fast path and uses a sanitized `merge-tree` fallback. It disables custom merge drivers, the built-in `union` driver, and renormalization; all detector errors and timeouts fail closed. `force` is now an actual boolean parameter through HTTP route and MCP tool.
- **T2 complete:** `delete_session()` uses the same detector while preserving running-worker, child-worker, dirty-tree, and explicit-force guards.

## Files

- `app/workspace.py` — shared content detector and switch guard.
- `app/routes/sessions.py` — public `force` validation/forwarding and deletion guard.
- `app/mcp_stdio.py` — public `switch_worker_branch(force=False)` contract.
- `tests/test_workspace.py`, `tests/test_api.py`, `tests/test_mcp_stdio.py` — squash, real-unmerged, detached HEAD, failures, route/MCP forwarding, custom-driver and `union` regressions.
- `docs/tasks/103/codex-review-impl.md` — adversarial review and resolved findings.

Implementation commit `1cee6e5`: 7 files, +713/-32.

## Verification

- Targeted suite: `tests/test_workspace.py tests/test_api.py tests/test_mcp_stdio.py -q` — **176 passed**.
- Fresh nested parent/child repository under `/tmp`: multi-commit squash plus later parent-only commit switched successfully; worker-only sibling stayed on its original HEAD/branch and no target ref was created.
- Read-only live audit after the final merge-driver hardening: 94 active session rows; 49 ancestry allows, 4 content-noop allows, 9 content-change blocks, 6 conflict blocks, 8 dirty worktrees skipped, 18 missing worktrees, **0 detector errors**.
- Codex review round 1 found two real false-allow paths (`merge=union` and config subsection names containing `=`). Both were reproduced in `/tmp`, fixed, regression-tested, and round 2 returned `VERDICT: APPROVED`.

## Compatibility and remaining work

No breaking API change: `force` defaults to `false`. No service restart or deployment was performed. Full repository pytest was not rerun in the recovery turn; the three affected suites above are the verified test artifact.
