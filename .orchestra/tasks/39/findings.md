# Task #39 Plan Review — Findings

Adversarial review of `docs/tasks/39/plan.md`, focused on the three open questions plus any P0-adjacent breakage found while tracing the affected code.

## High severity

### 1. `session_id = None` is required for compaction, but persisting null is not required and is avoidable

The plan's final decision says to keep `self.session_id = None` and accept the restart window as out of scope. That is too weak for a P0 compact rewrite.

What is true:
- If the ack turn uses `_ensure_backend()` with the compact-summary turn's `session_id`, it resumes the old/full SDK session and defeats compaction.
- Therefore the ack turn must start a fresh SDK/CLI session with no resume token.

What is false:
- It does not follow that the persisted `sessions.session_id` must be nulled.

Safer design:
- Keep the old `self.session_id` in memory/DB until the fresh ack turn completes.
- Create the ack backend in forced-fresh mode (`resume_session_id=None` / `resume_thread_id=None`) without mutating `self.session_id` first.
- When the ack `turn_end` arrives, `_handle_turn_end()` replaces `self.session_id` with the new fresh token and persists it.
- If the process crashes mid-compact, restart resumes the old token rather than losing all context. That is strictly better than persisting `NULL`.

Current plan failure mode:
- The proposed ack block calls `self._persist()` before `_ensure_backend()`.
- If `self.session_id` has been set to `None` before that, the DB row is nulled during the ack turn.
- A crash/restart before the ack `turn_end` permanently loses the resume token.

Recommendation: add a fresh-backend path instead of persisting `None`. For example, add an optional `resume: bool = True`/`force_fresh: bool = False` path to backend construction, or manually instantiate the backend for the ack turn with no resume token while leaving `self.session_id` unchanged until the new `turn_end`.

### 2. Ack-turn event can be set by non-ack turns; `_compacting` does not fully serialize senders

The plan says only the ack turn can run while `_compact_ack_event` is set because `_compacting` gates `send()`. That is not true for all paths.

Counterexamples in current code:
- `_flush_pending()` bypasses `send()` entirely and directly calls `_ensure_backend()` + `backend.send()` after a 0.3s sleep.
- A `_flush_pending()` task may have been scheduled before `compact()` sets `_compacting = True`.
- `_handle_turn_end()` itself schedules `_flush_pending()` when `_pending_messages` exists, even during compact.
- Heartbeat reconnect also directly calls `self._backend.send(...)` while status is `RUNNING`.

What breaks:
- A pending flush can start a non-ack turn while `_compact_ack_event` is non-`None`.
- `_handle_turn_end()` will set the ack event for that turn, making `compact()` return success even if the actual ack never completed.
- The flushed user message may also run without the compact summary or on the wrong fresh/resumed backend, depending on timing.

Recommendation:
- Bind the ack event to a specific turn generation/id, not just “event exists”. Capture `ack_turn_gen` after `_bump_turn_gen()` and only set the event if the ending turn matches it.
- Make `_flush_pending()` respect `_compacting` at entry, or cancel/drain any already-scheduled flush before starting compact.
- Suppress `_fire_auto_report()` and pending-flush scheduling for the internal ack turn, or explicitly defer them until compact cleanup.

### 3. `create_task` in `_persist()` is runtime-safe for current callers, but the proposed implementation needs stronger guards

I found `_persist()` call sites in `app/session.py`, `app/main.py`, and `app/tools.py`. They are all reached from async FastAPI/MCP/event-loop paths or event-loop callbacks. So `asyncio.create_task()` is not worse than the existing `asyncio.get_event_loop().run_in_executor(...)` assumption for current runtime callers.

However, the plan should be tightened:
- Use `asyncio.get_running_loop().create_task(...)` for explicit failure if someone calls `_persist()` off-loop.
- Keep the `try/except` inside `_persist_loop()` as the plan already refines; otherwise one DB exception kills future coalesced writes until another `_persist()` starts a new task.
- Add a done callback or equivalent logging/retrieval for `_persist_task` exceptions. `_drain_persist(return_exceptions=True)` only helps code paths that drain; most persists are fire-and-forget.
- Update existing tests that inspect `_persist_futs`; replacing it with a single task will break `tests/test_manager.py` expectations around draining stale persists.

## Medium severity

### 4. Fix 5 does not clean up worktrees if `create_worktree()` raises after `git worktree add`

The plan's cleanup only runs when `session.worktree_path` is set. In `create_session()`, that field is assigned only after `create_worktree(...)` returns.

If `create_worktree()` succeeds at `git worktree add` but raises later while copying project files, the worktree exists but `session.worktree_path` is still `None`, so the proposed except block will not remove it.

Recommendation:
- Either make `create_worktree()` internally roll back on any post-add failure, or track the intended/generated path before calling it and clean that path on failure.

### 5. Fix 6 handles initial `connect()` timeout but not `reconnect()` timeout/cancellation

The plan fixes `ClaudeBackend.connect()`, but `ClaudeBackend.reconnect()` still does:
- `self._client = self._make_client()`
- `await asyncio.wait_for(self._client.connect(), timeout=60)`

If reconnect connect times out, `_client` remains set and may leak the CLI subprocess in the same way. Heartbeat and listener recovery use `reconnect()`, so this is not just theoretical.

Also, `except Exception` does not catch `asyncio.CancelledError` on modern Python, so caller cancellation during connect can still skip cleanup. If cancellation cleanup matters, catch `BaseException`, disconnect, then re-raise.

## Answers to Open Questions

1. **`asyncio.create_task` safety:** safe for current production call sites, all are event-loop paths. Use `get_running_loop().create_task()` and add exception retrieval/logging. Update tests that depend on `_persist_futs`.
2. **Nulling `session_id`:** a fresh/no-resume ack backend is required; persisting `session_id = None` is not. Do not resume the old token for ack, but also do not write `NULL` to DB before a replacement token exists.
3. **Ack false positives:** yes, false positives are possible. `_flush_pending()` and heartbeat can bypass the `send()` guard, and `_handle_turn_end()` is not bound to the ack turn. Bind by turn generation and block/defer direct senders during compact.
