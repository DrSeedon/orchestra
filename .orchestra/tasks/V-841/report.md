# V-841 — Bound worker log snapshots on the server

## Change

`get_worker_logs(limit=N)` previously requested `/api/sessions/{name}/logs` with `after_id=0`, let the endpoint return its default 5,000 rows, then sliced the list to N in the MCP process. The endpoint already accepted `limit` and `app.db.get_logs` already implements an indexed descending tail query followed by reversal into chronological order; the route simply did not pass its limit to that query.

The MCP client now forwards `limit`. For cold snapshots (`after_id <= 0` and no `before_id`), the route passes an explicitly supplied, bounded limit to `get_logs`; its existing `idx_logs_session(session_id, id DESC)` index supplies the newest rows, and `get_logs` returns those rows in ascending id order. When `limit` is omitted, the route calls `get_logs` without a limit and preserves its former 5,000-row default. `before_id` keeps its former 500-row default and backward paging path. Positive `after_id` keeps the old 5,000-row default when limit is omitted and honors an explicitly supplied limit. The separate SSE route was not changed.

Caller search covered `app/`, `scripts/`, and `tests/`. `app/session.py::_compact_prompt` fetches the raw transcript with no `limit`; it therefore retains the old 5,000-row maximum. `app/mcp_stdio.py::get_worker_logs` passes an explicit limit. Both dashboard history requests in `app/static/js/app.js` use `before_id` plus an explicit limit; load-older paging remains on that path. `tests/test_api.py` has no-limit requests for an empty log and a missing session. SSE consumers use `/stream`, not this endpoint. No `/api/sessions/{name}/logs` call was found under `scripts/`.

## Verification

Focused command before the omitted-limit correction: `uv run --frozen python -m pytest tests/test_session_logs_conditional.py tests/test_mcp_stdio.py -q` — **141 passed**. After the correction, `uv run --frozen python -m pytest tests/test_session_logs_conditional.py -q` — **3 passed**, including the existing `after_id` page and the added no-limit case returning all 1,200 fixture rows. Imported modules were `/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-api/app/routes/sessions.py` and `/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-api/app/mcp_stdio.py`. `git diff --check` passed.

Committed regression tests fail under both relevant mutations. Restoring `logs[-limit:]` in the MCP tool caused `test_get_worker_logs_requests_limit_from_server_without_client_slicing` to return only three of five fake API rows and fail. Removing the route's `limit=limit` argument caused `test_logs_limit_returns_latest_rows_in_order_and_after_id_still_pages` to return all 1,200 fixture rows instead of the latest three and fail. The tests also check ascending row order and a positive `after_id` page.

## SQLite backup measurement

The measurement used SQLite's online `backup()` API to copy the main checkout database to the task directory, then invoked the actual `/api/sessions/{name}/logs` handler against that copy. The session contained 12,641 rows with 22,969,589 content characters. The old behavior was reproduced by making the handler's `get_logs` call ignore the requested limit and use the former 5,000-row default. The new behavior used `limit=3`.

| Path | Rows | Response bytes | Handler + JSON time |
|---|---:|---:|---:|
| Previous 5,000-row snapshot | 5,000 | 13,101,592 | 0.6997 s |
| New `limit=3` snapshot | 3 | 1,077 | 0.00356 s |

`EXPLAIN QUERY PLAN` on the backup reported `SEARCH logs USING INDEX idx_logs_session (session_id=?)`. This is one local snapshot and one measurement pass; it shows the endpoint's indexed query path but does not characterize cold-cache or cross-machine timing. The 4,110,827,520-byte temporary backup and its SQLite sidecars were removed after measurement and were never staged.

The first measurement process stopped after the backup because executing a script from `.orchestra/tasks/V-841/` did not put the worktree root on `sys.path`. The temporary copy was moved to trash, the script was adjusted to include the repository root, and the successful repeat above completed; the copy and sidecars were removed.

## Omitted-limit regression follow-up

The initial change accidentally applied the route's `limit=500` default even when the caller omitted `limit`. This would have truncated raw transcripts after compaction. The route now distinguishes an omitted query parameter (`None`) from an explicit limit and retains `get_logs`'s original 5,000-row default for no-limit snapshots. A committed test seeds 1,200 rows and verifies an omitted limit returns all 1,200 in chronological order. Mutation check: changing the route parameter default back to 500 caused that test to fail with 500 rows instead of 1,200; the original parameter handling was restored and the test passed. Commits: `1f33681b` (initial bounded snapshot), `3c7b5bdd` (measurement), `2fc905a7` (preserve omitted-limit snapshots).

## Runtime

This change modifies Python in `app/`; **an Orchestra restart is required after merge** for the live API route to use the server-side bound.
