# Report #42 — Fix P2 Bugs from Review #35

## Summary

Fixed 11 P2/P3 issues from review #35 and removed ~95 lines of dead code. All changes are surgical — behavioral fixes to existing patterns, no new architecture.

## Changes

### Behavioral Fixes

1. **Reconnect backoff cap** (`session.py`): `_claude_event_loop` now has a `consecutive_failures` counter (max 5). Handles both exception-based failures AND normal `events()` exhaustion. On limit: proper `_disconnect_backend()` (not just `_backend=None`), `_turn_start` reset, IDLE status.

2. **Hibernate pending guard** (`session.py`): `_idle_hibernate` now checks `self._pending_messages` before disconnecting. Prevents hibernate from racing with queued work.

3. **GC task protection** (`session.py`): New `_spawn_bg()` helper stores task refs in `_background_tasks` set, removes on done, logs exceptions. Applied to 8 fire-and-forget `create_task` sites (refresh_context, auto_continue, notify_scope_idle, auto_compact, flush_pending ×3, codex flush_pending).

4. **rawMaxTokens** (`backend_claude.py`, `session.py`): `context_usage()` now returns `raw_max_tokens` from SDK. `_refresh_context_from_api` prefers it over `max_tokens` for accurate percentage denominator.

5. **Log retention + WAL checkpoint** (`db.py`, `manager.py`): New `cleanup_old_logs(days=7)` function with WAL checkpoint in separate transaction. Periodic task in manager runs every 6 hours, stored as `_cleanup_task`, cancelled on shutdown.

### Dead Code Removed (~95 lines)

- `app/backend.py` — 18-line unused `AgentBackend` Protocol, zero imports
- `db.py` — `get_orchestrators`, `get_resumable_orchestrators`, `mark_stale_sessions` (34 lines, zero production callers) + their tests (83 lines in `test_db.py`)
- `tg_bridge.py` — `_react_processing` no-op function + 6 call sites
- `tg_bridge.py` — `_send_expandable_return` merged into `_send_expandable` (added `body.rstrip()` + return value)
- `workspace.py` — `_ensure_repo_on_main` compatibility alias
- `manager.py` — `auto_resume_orchestrators` wrapper → `auto_resume_all` called directly

### Minor Fixes

- `_codex_reasoning_effort`: collapsed dead `if` branch (both arms returned "high")
- `_on_task_done`: reset `_turn_start = 0` on force-idle (prevents stale timeout math)
- `test_disallowed_tools`: fixed stale assertion (workers now have `_ALWAYS_DISALLOWED` tools)

## Files Changed

| File | +/- | Changes |
|------|-----|---------|
| app/session.py | +55/-39 | reconnect backoff, _spawn_bg, hibernate guard, rawMaxTokens, turn_start fixes |
| app/backend_claude.py | +1/-0 | raw_max_tokens in context_usage |
| app/db.py | +8/-30 | delete dead funcs, add cleanup_old_logs |
| app/manager.py | +17/-2 | periodic cleanup task, delete wrapper |
| app/tg_bridge.py | +3/-38 | delete _react_processing, merge expandables |
| app/main.py | +1/-1 | auto_resume_all |
| app/workspace.py | +0/-4 | delete alias |
| app/backend.py | +0/-17 | DELETE file |
| tests/test_db.py | +0/-83 | delete tests for removed functions |
| tests/test_disallowed_tools.py | +3/-1 | fix stale assertion |
| tests/test_manager.py | +1/-1 | update wrapper reference |
| **Total** | **+106/-201** | **net -95 lines** |

## Tests

- 195 passed, 5 skipped (pre-existing skips)
- 6 pre-existing failures (3 in test_session.py referencing removed `AUTO_REPORT_IDLE_SEC`, 2 in test_manager.py with DB/event loop issues, 1 stale test_disallowed_tools)
- My fix to test_disallowed_tools resolved 1 of the pre-existing failures
- No new test failures introduced

## Breaking Changes

None. All changes are internal — no API surface, no CLI, no config format changes.

## Codex Reviews

1. **Plan review** (gpt-5.5): Found 5 issues — all addressed before implementation:
   - Tests need updating for dead code removal ✅
   - Reconnect cap must disconnect properly, not just null backend ✅
   - events() normal exhaustion is another spin path ✅
   - _spawn_bg should log exceptions ✅
   - WAL checkpoint after commit ✅

2. **Implementation review** (gpt-5.5): Running — will append findings.
