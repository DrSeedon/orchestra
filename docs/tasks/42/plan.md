# Plan #42 — Fix P2 Bugs from Review #35

## Overview

11 items: 5 behavioral fixes + ~95 lines dead code removal + 1 minor P3 fix.
Grouped by file for minimal diff churn.

---

## Group 1: session.py (4 changes)

### 1.1 Reconnect backoff cap
**File:** `app/session.py`, method `_claude_event_loop` (lines 284-326)
**Problem:** `while True` loop with only 2s sleep from `reconnect()`. If reconnect succeeds but `events()` immediately fails, it spins forever. Also: if `events()` exhausts normally without yielding, the loop immediately re-enters with no sleep.
**Fix:** Add a `consecutive_failures` counter. Reset to 0 when a successful event is received. Increment on `except Exception` AND on normal `events()` exhaustion (after the `async for` completes). After 5 consecutive failures:
1. Call `await self._disconnect_backend()` (NOT just `self._backend = None` — avoids leaking CLI process)
2. Reset `self._turn_start = 0` (avoid stale timeout)
3. Set `status=IDLE`, persist, return.

Also handle normal `events()` exhaustion: after the `async for` loop body, increment failures, log, and attempt reconnect (same as exception path).

```python
async def _claude_event_loop(self) -> None:
    logger.info(f"[{self.name}] claude event loop started")
    consecutive_failures = 0
    while True:
        try:
            if self._backend is None:
                return
            async for event in self._backend.events():
                self._last_msg_time = asyncio.get_event_loop().time()
                # ... existing timeout check ...
                self._handle_event(event)
                consecutive_failures = 0  # reset on successful event
            # events() exhausted normally — treat as failure
            consecutive_failures += 1
            logger.warning(f"[{self.name}] events() exhausted normally (attempt {consecutive_failures})")
            if consecutive_failures >= 5:
                # give up — disconnect properly
                ... (see below)
            # attempt reconnect (same as exception path)
            ...
        except asyncio.CancelledError:
            return
        except Exception as e:
            consecutive_failures += 1
            if consecutive_failures >= 5:
                logger.error(f"[{self.name}] reconnect limit ({consecutive_failures} failures)")
                self._log("error", f"backend unstable, giving up")
                self._turn_start = 0
                await self._disconnect_backend()
                if self.status == AgentStatus.RUNNING:
                    self.status = AgentStatus.IDLE
                    self._persist()
                return
            # existing reconnect logic ...
```

### 1.2 Hibernate checks pending messages
**File:** `app/session.py`, method `_idle_hibernate` (line 552-554)
**Problem:** Hibernate can disconnect backend while `_pending_messages` has queued work.
**Fix:** Add `if self._pending_messages: return` after the `status != IDLE` check (line 554). 1 line.

```python
# After line 554 (if self.status != AgentStatus.IDLE: return):
if self._pending_messages:
    return
```

### 1.3 Fire-and-forget `create_task` refs (GC protection)
**File:** `app/session.py`
**Problem:** `asyncio.create_task()` called without storing reference — Python GC can collect the task before it completes.
**Fix:** Add a `_background_tasks: set` field to `AgentSession`. Wrap fire-and-forget `create_task` calls in a helper `_spawn_bg(coro)` that adds to the set and removes via `add_done_callback`. Apply to 6 call sites:
- line 457: `_refresh_context_from_api()`
- line 466: `_auto_continue()`
- line 485: `_notify_scope_idle()`
- line 489: `_auto_compact()`
- line 495: `_flush_pending()` (in `_handle_turn_end`)
- line 603: `_flush_pending()` (in `_heartbeat_loop`)
- line 732: `_flush_pending()` (in `compact` finally)

Also include `_flush_pending()` in codex `_codex_turn_loop` finally (line 351).

Note: `_listen_task`, `_heartbeat_task`, `_hibernate_task`, `_auto_report_task`, `_persist_task` already stored — skip those.

```python
# New field in AgentSession dataclass:
_background_tasks: set = field(default_factory=set, repr=False)

# New helper method:
def _spawn_bg(self, coro) -> asyncio.Task:
    task = asyncio.create_task(coro)
    self._background_tasks.add(task)
    def _on_done(t):
        self._background_tasks.discard(t)
        if not t.cancelled():
            exc = t.exception()
            if exc:
                logger.warning(f"[{self.name}] background task failed: {exc}")
    task.add_done_callback(_on_done)
    return task
```

Then replace `asyncio.create_task(self._xxx())` with `self._spawn_bg(self._xxx())` at all 8 unowned sites:
- line 351: `_flush_pending()` (codex turn loop)
- line 457: `_refresh_context_from_api()`
- line 466: `_auto_continue()`
- line 485: `_notify_scope_idle()`
- line 489: `_auto_compact()`
- line 495: `_flush_pending()` (handle_turn_end)
- line 603: `_flush_pending()` (heartbeat)
- line 732: `_flush_pending()` (compact finally)

### 1.4 Minor: `_codex_reasoning_effort` dead branch + `_on_task_done` stale `_turn_start`
**File:** `app/session.py`
**Problem 1:** `_codex_reasoning_effort` (lines 166-169) — both branches return "high". Dead `if`.
**Fix:** Collapse to `return "high"`. 3 lines → 1 line.

**Problem 2:** `_on_task_done` (lines 576-579) — sets status IDLE but doesn't reset `_turn_start`, causing stale timeout math on next resumed turn.
**Fix:** Add `self._turn_start = 0` before status change. 1 line.

---

## Group 2: backend_claude.py (1 change)

### 2.1 Use `rawMaxTokens` from context_usage
**File:** `app/backend_claude.py`, method `context_usage` (lines 173-189)
**Problem:** Returns `maxTokens` (post-autocompact-buffer), but `CONTEXT_LIMITS` in models.py uses raw values → denominator mismatch for percentage.
**Fix:** Also return `rawMaxTokens` if available, prefer it in session.py's `_refresh_context_from_api`.

```python
# In context_usage() return dict, add:
"raw_max_tokens": u.get("rawMaxTokens", 0),
```

Then in `session.py` `_refresh_context_from_api` (line 775-776), prefer raw_max_tokens:
```python
raw_max = usage.get("raw_max_tokens") or usage.get("max_tokens")
if raw_max:
    self._last_context["max_tokens"] = raw_max
```

---

## Group 3: db.py (2 changes)

### 3.1 Delete dead functions + their tests
**File:** `app/db.py`, lines 639-672
**Delete:** `get_orchestrators()`, `get_resumable_orchestrators()`, `mark_stale_sessions()` — zero production callers.
**File:** `tests/test_db.py` — delete test functions that import/test these dead functions (lines 231-310, ~7 test functions).

### 3.2 Add log retention + WAL checkpoint
**File:** `app/db.py`
**Add function:** (checkpoint AFTER commit, not inside the write transaction)
```python
def cleanup_old_logs(days: int = 7) -> int:
    with _conn() as c:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        cur = c.execute("DELETE FROM logs WHERE ts < ?", (cutoff,))
        deleted = cur.rowcount
    # checkpoint AFTER transaction commits (separate connection or after context manager)
    with _conn() as c:
        c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return deleted
```

**File:** `app/manager.py`, method `start_background_tasks` — add a periodic cleanup task stored on `self._cleanup_task` (not fire-and-forget) that runs `cleanup_old_logs()` every 6 hours. Cancel in `shutdown_all()`.

---

## Group 4: tg_bridge.py (2 changes)

### 4.1 Delete `_react_processing` + 6 call sites
**File:** `app/tg_bridge.py`
**Delete:** Function at line 376-377 + calls at lines 1009, 1032, 1061, 1073, 1087, 1099.
7 deletions total.

### 4.2 Merge `_send_expandable_return` into `_send_expandable`
**File:** `app/tg_bridge.py`
**Problem:** `_send_expandable` (line 469) and `_send_expandable_return` (line 394) are identical except `_return` returns the message object.
**Fix:** Make `_send_expandable` return the message object (add `return` to both `await bot.send_message` calls) AND add `body = body.rstrip()` (present in `_return` variant but missing from `_send_expandable`). Delete `_send_expandable_return`. Update callers at lines 938, 957 to use `_send_expandable`.

---

## Group 5: Dead code cleanup (3 files)

### 5.1 Delete `app/backend.py`
Entire file — `AgentBackend` Protocol, 18 lines, zero imports.

### 5.2 Delete `_ensure_repo_on_main` alias
**File:** `app/workspace.py`, line 163-164. Delete the alias + comment.

### 5.3 Delete `auto_resume_orchestrators` wrapper
**File:** `app/manager.py`, lines 939-940. Delete.
**File:** `app/main.py`, line 38. Change `auto_resume_orchestrators()` → `auto_resume_all()`.
**File:** `tests/test_manager.py`, line 250. Change `auto_resume_orchestrators()` → `auto_resume_all()`.

---

## What NOT to touch

- Anything in P0/P1 scope (already fixed in #39/#40)
- SDK options (max_budget_usd, fallback_model) — feature requests, not bugs
- Blocked-tools verification — can't verify without runtime
- Betas flag for 1M context — working via suffix, belt-and-suspenders not needed now
- Any UI/template files

## Execution order

1. session.py changes (all 4 together)
2. backend_claude.py rawMaxTokens
3. db.py dead functions + cleanup
4. tg_bridge.py cleanup
5. workspace.py, manager.py, main.py, backend.py dead code
6. Test: `UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest -x -q` (includes updated tests)
7. Git commit: `#42: fix P2 bugs — reconnect backoff, hibernate guard, GC task refs, log retention, dead code cleanup (~95 lines removed)`
