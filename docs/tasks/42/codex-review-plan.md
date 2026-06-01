# Codex Review: Plan #42

## Verdict

The plan is directionally good for an MVP, but I would not execute it as-is. Most fixes are small and should work, but there are two correctness gaps in the reconnect/task handling work and the "dead code" deletions are not test-safe in the current repo.

## Findings

### Blocking: DB helper deletion breaks existing tests

`app/db.py:639-672` may have zero production callers, but it does not have zero callers in the repo. `tests/test_db.py:231`, `tests/test_db.py:247`, `tests/test_db.py:260`, `tests/test_db.py:273`, `tests/test_db.py:288`, `tests/test_db.py:297`, and `tests/test_db.py:305` import the helpers directly. Deleting `get_orchestrators()`, `get_resumable_orchestrators()`, and `mark_stale_sessions()` will make the test suite fail at import time.

If the functions are intentionally dead, the plan also needs to delete or rewrite those tests around `auto_resume_all()` / current startup behavior. The "Any tests (there are none to update)" note is false.

### Blocking: `auto_resume_orchestrators` deletion also breaks a test

The wrapper at `app/manager.py:939-940` has one production caller in `app/main.py:38`, but it also has a test caller at `tests/test_manager.py:250`. Changing only `main.py` is not enough. Either update that test to call `auto_resume_all()` or keep the wrapper until tests are migrated.

### Blocking: reconnect cap can leak the Claude backend

The proposed reconnect-limit branch in `AgentSession._claude_event_loop()` sets `self._backend = None` and returns. That drops the reference without calling `disconnect()` on the current `ClaudeBackend`, so a live SDK client / CLI process can be leaked on the exact failure path this fix targets.

Use `await self._disconnect_backend()` or capture the backend and `await backend.disconnect()` before clearing it. Also reset `_turn_start` when forcing the session idle, matching the stale-timeout fix in `_on_task_done()`.

### Suggestion: reconnect cap misses silent `events()` exhaustion

`_claude_event_loop()` at `app/session.py:286-301` uses `while True` around `async for event in self._backend.events()`. The plan only increments `consecutive_failures` inside `except Exception`. If `events()` returns normally without yielding, the loop immediately calls it again with no sleep, no reconnect, and no counter increment. That is another spin path.

After the `async for` completes normally, count it as a listener failure, sleep/reconnect, or return idle. Otherwise the proposed cap only handles exception-based failure loops.

### Suggestion: `_spawn_bg` should log exceptions and include the Codex pending flush site

Keeping references in `_background_tasks` is fine, but the helper should consume `task.exception()` in the done callback and log failures. Otherwise failures in `_refresh_context_from_api()`, `_notify_scope_idle()`, `_auto_compact()`, or `_flush_pending()` can still become "Task exception was never retrieved" warnings with weak operational visibility.

The call-site list also misses `app/session.py:351`, where `_codex_turn_loop()` schedules `_flush_pending()`. If the helper is meant to cover unowned fire-and-forget session tasks, include that site too. The plan says "6 call sites", lists 7, and the current file has 8 relevant unowned session call sites.

### Suggestion: log cleanup should checkpoint outside the delete transaction

`cleanup_old_logs()` is useful, but the proposed implementation runs `DELETE` and then `PRAGMA wal_checkpoint(TRUNCATE)` in the same `with _conn()` block. In sqlite3, the delete opens a write transaction that is normally committed when the context manager exits. Running a checkpoint while that transaction is still active can fail or fail to truncate usefully.

Commit first, then checkpoint on a clean connection or after leaving the transaction. Also store the periodic cleanup task on `SessionManager` like `_spawn_task`; an untracked infinite cleanup loop is harder to cancel and debug.

## Item-by-item Review

### 1.1 Reconnect backoff cap

Partially works. Counting consecutive exception failures and bailing after 5 is reasonable for an MVP. Fix the backend cleanup leak and the silent `events()` exhaustion path before implementing.

### 1.2 Hibernate checks pending messages

Safe and useful. Adding `if self._pending_messages: return` after the status check in `_idle_hibernate()` prevents an idle disconnect from racing queued work. The lifecycle lock already makes this a low-risk guard.

### 1.3 Fire-and-forget `create_task` refs

Reasonable cleanup, but not sufficient as specified. Add exception retrieval/logging in the done callback and include the Codex `_flush_pending()` site. Stored tasks such as `_listen_task`, `_heartbeat_task`, `_hibernate_task`, `_auto_report_task`, and `_persist_task` should remain separate.

### 1.4 `_codex_reasoning_effort` and `_on_task_done`

Safe. Collapsing `_codex_reasoning_effort()` to `return "high"` has no behavior change. Resetting `_turn_start` when `_on_task_done()` forces idle is correct; apply the same idea to other force-idle listener failure paths.

### 2.1 `rawMaxTokens` from `context_usage`

Likely works for live sessions and matches the SDK research in the repo. Keep the fallback to `maxTokens`. This does not fully fix stale/inactive session display because `app/main.py:470-472` still returns `max_tokens: 200000` for DB-backed sessions, and `manager._load_from_db()` seeds max tokens from `CONTEXT_LIMITS`, but that is acceptable for MVP if the bug is only live context display.

### 3.1 Delete DB dead functions

Runtime-safe for `app/` based on grep, but not repo-safe because tests import them. Update/delete the tests in the same change.

### 3.2 Add log retention + WAL checkpoint

Good operationally. Implement the checkpoint after commit, and make the manager cleanup loop a stored task. Seven-day retention is reasonable for a small-team MVP if nobody relies on old logs for audit/debugging.

### 4.1 Delete `_react_processing`

Safe. It is an awaited no-op at `app/tg_bridge.py:376-377`; deleting the function and call sites should not affect behavior.

### 4.2 Merge `_send_expandable_return` into `_send_expandable`

Mostly safe. Preserve the existing `body = body.rstrip()` behavior from `_send_expandable_return()` when merging; the two functions are not quite identical today. Returning the message from `_send_expandable()` is backward-compatible for callers that ignore the return value.

### 5.1 Delete `app/backend.py`

Safe for runtime: no `app/` imports it. It is referenced only by archived docs/research. For an MVP with no public package API, deletion is fine.

### 5.2 Delete `_ensure_repo_on_main` alias

Safe. Grep shows only the alias assignment, and the project explicitly avoids compatibility shims.

### 5.3 Delete `auto_resume_orchestrators` wrapper

Safe only if tests are updated. Production caller can move from `auto_resume_orchestrators()` to `auto_resume_all()`, but `tests/test_manager.py:250` must move too.

## Recommended Plan Adjustments

1. Keep the current implementation order, but add test updates to the plan.
2. In reconnect-limit handling, disconnect the backend before dropping it, handle normal `events()` exhaustion, and clear `_turn_start`.
3. Make `_spawn_bg()` log task exceptions and cover all unowned session fire-and-forget sites.
4. Commit log deletion before WAL checkpointing, and store the cleanup loop task on the manager.
5. Run at least `uv run python -m pytest tests/test_db.py tests/test_manager.py -q`; then run the full suite if practical.
