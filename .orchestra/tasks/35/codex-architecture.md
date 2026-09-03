## Summary

`docs/tasks/35/review-architecture.md` is not present in this checkout, so I could not review the full architecture-finding list. I verified the two named findings against actual code.

> Note (review-architecture worker): Codex's `codex_review` MCP tool runs in the **source repo** cwd, not the worker's worktree, so it could not see `review-architecture.md` (which lives only on the worker branch — that's why the file appeared "missing"). It validated the two findings I passed inline via `context=`. The full finding list is in `review-architecture.md` on this branch.

## Findings

**blocking:** `app/main.py:558` calls `session._disconnect_client()`, but `AgentSession` defines `_disconnect_backend()` at `app/session.py:736` and other lifecycle call sites use `_disconnect_backend()`. This route will crash with `AttributeError` when `/api/sessions/{name}/restart-cli` is used. The finding is correct.

**suggestion:** `app/tm.py:16-23` hardcodes `data/orchestra.db` and opens SQLite directly, while `app/db.py:12-25` honors `ORCHESTRA_DB_PATH`. The finding is correct, but severity should be scoped: it is not a universal production blocker if the default DB path is used. It does break env-selected DB isolation for tests/worktrees/alternate deployments and can split task-manager data from the main app DB.

**question:** The requested source file is missing. If there were additional architecture findings in `review-architecture.md`, they could not be validated here.

## Verdict

Both named findings are real. The restart endpoint issue is accurately blocking because it crashes that API path. The task-manager DB-path issue is a real architecture/config consistency bug, but calling it broadly blocking would be overstated for the current MVP unless `ORCHESTRA_DB_PATH` is part of the active runtime/test workflow.
