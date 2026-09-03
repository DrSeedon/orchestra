# Research #42 — P2 Bugs from Review #35

## What changed since review #35

**#39 (P0 fixes):** compact re-entry guard, session_id handling, persist single-flight, zombie CLI cleanup, flush_pending error recovery, force_fresh backend.
**#40 (P1 fixes):** error states surfaced (is_error/errors), ThinkingBlock handled, cost reset on session_id change, template_hash after send, auto_report captures stop_reason, waiting state preserved in resume, _disconnect_client→_disconnect_backend fixed, tm.py DB path fixed, DB executor separated, git rev-parse→to_thread, iterations dead branch removed.

## P2 findings — verification against current code

### STILL OPEN

| # | Source | Issue | Status | Notes |
|---|--------|-------|--------|-------|
| 1 | correctness P2-1 | Reconnect loop spins without backoff/limit | **OPEN** | session.py:284-326 — still `while True` with only reconnect's 2s sleep. No failure counter. |
| 2 | correctness P2-3 | Hibernate ignores pending messages | **OPEN** | session.py:552-554 — checks `status != IDLE` and `_backend is None`, but NOT `_pending_messages`. |
| 3 | reliability P2 (disk) | No log retention, no WAL checkpoint | **OPEN** | No `DELETE FROM logs` or `wal_checkpoint` anywhere in codebase. |
| 4 | reliability P2 (GC) | `create_task` without reference → GC can kill | **OPEN** | session.py lines 457, 466, 485, 489 — fire-and-forget tasks with no stored reference. `_hibernate_task`, `_listen_task`, `_heartbeat_task`, `_auto_report_task`, `_persist_task` are stored. But `_refresh_context_from_api`, `_auto_continue`, `_notify_scope_idle`, `_auto_compact`, `_flush_pending` (3 call sites) are not. |
| 5 | architecture P2 | Dead module `app/backend.py` (AgentBackend Protocol) | **OPEN** | 18 lines, zero imports. |
| 6 | architecture P2 | Dead DB functions: `get_orchestrators`, `get_resumable_orchestrators`, `mark_stale_sessions` | **OPEN** | db.py:639-672, zero callers. |
| 7 | architecture P2 | Dead no-op `_react_processing` + 6 call sites | **OPEN** | tg_bridge.py:376-377, called at 1009, 1032, 1061, 1073, 1087, 1099. |
| 8 | architecture P2 | Dead alias `_ensure_repo_on_main` | **OPEN** | workspace.py:164, zero callers. |
| 9 | architecture P2 | Redundant wrapper `auto_resume_orchestrators` | **OPEN** | manager.py:939-940, one caller at main.py:38. Just `await self.auto_resume_all()`. |
| 10 | architecture P2 | Duplicate `_send_expandable_return` vs `_send_expandable` | **OPEN** | tg_bridge.py:394 and 469 — identical except `_return` returns the message. Callers at 938, 957 need the return; 469 doesn't return. |
| 11 | sdk P2-9 | `maxTokens` vs `rawMaxTokens` mismatch | **OPEN** | backend_claude.py:181 reads `maxTokens` (post-autocompact-buffer). CONTEXT_LIMITS uses raw values. Denominator mismatch for percentage. |
| 12 | sdk P2-12 | Unused SDK options (max_budget_usd, fallback_model) | **DEFERRED** | Not a bug, feature request. Skip for this task. |
| 13 | sdk P2-5 | Blocked-tools list may be stale | **DEFERRED** | Can't verify without calling `get_server_info()`. Low impact — extra names are silently ignored by CLI. |
| 14 | sdk P2-6 | `betas` not passed for 1M context | **DEFERRED** | The `[1m]` suffix is working. Belt-and-suspenders but not a bug. |
| 15 | correctness P3-1 | `_codex_reasoning_effort` dead branch | **OPEN** | session.py:166-169 — both arms return "high". |
| 16 | correctness P3-3 | `old_session_id` computed but unused | **CLOSED** | Already removed in #39. |
| 17 | correctness P3-4 | `_on_task_done` doesn't clear `_turn_start` | **OPEN** | session.py:574-579 — sets status IDLE but leaves `_turn_start` non-zero. |

### CLOSED BY #39/#40

| # | Source | Was | Why closed |
|---|--------|-----|-----------|
| P0-1 | compact re-entry | compact re-entry guard | #39: `if self._compacting: return` + `_compact_ack_event` + `force_fresh` |
| P0-2 | compact blind poll | fabricated success after 60s | #39: replaced with `_compact_ack_event.wait()` + proper timeout error |
| P0-3 | persist races | full-row persist from multiple coroutines | #39: `_persist_loop` single-flight pattern |
| P1-1 | session_id=None | observable by other coroutines | #39: `force_fresh` flag to `_make_backend` instead of nulling session_id |
| P1-2 | cost under-count | first turn after reconnect/compact | #40: `_last_cost = 0` reset when session_id changes |
| P1-3 | persist races | unordered full-row persists | #39: `_persist_loop` coalescing |
| P1-4 | template_hash | set before send succeeds | #40: moved after `await backend.send(message)` |
| P1-5 | auto-report | re-reads live _turn_logs | #40: captures `stop_reason` at fire time |
| P1-6 | resume waiting | drops waiting state | #40: `was_waiting` set captured + restored |
| arch P0 | _disconnect_client | AttributeError | #40: fixed to `_disconnect_backend` |
| arch P1 | tm.py DB path | split-brain DB | #40: `from app.db import _conn` |
| sdk P1-1 | iterations dead code | `usage["iterations"]` dead branch | #40: removed |
| sdk P1-3 | ThinkingBlock | silently dropped | #40: handled |
| sdk P1-4 | error states | always ok=True | #40: `is_error`/`errors` surfaced |
| reliability P2 | tg poll churn | fresh connection per tick | Already fixed: reuses `_poll_conn`, adaptive backoff |
| reliability P2 | dashboard SSE poll | 0.5s constant | Already has `idle_ticks` adaptive (0.5s→3.0s) |
| reliability P1 | git rev-parse blocking | sync in event loop | #40: `asyncio.to_thread` |
| reliability P1 | _flush_pending msg loss | batch lost on error | #39: `self._pending_messages[0:0] = msgs` |

## Files that will be affected

1. **app/session.py** — reconnect backoff, hibernate pending check, create_task refs, _codex_reasoning_effort, _on_task_done._turn_start
2. **app/backend_claude.py** — rawMaxTokens
3. **app/db.py** — delete dead functions, add log retention + WAL checkpoint
4. **app/tg_bridge.py** — delete _react_processing + calls, merge _send_expandable variants
5. **app/workspace.py** — delete _ensure_repo_on_main alias
6. **app/manager.py** — delete auto_resume_orchestrators wrapper
7. **app/main.py** — call auto_resume_all directly
8. **app/backend.py** — DELETE entire file

## Risks

- **Dead code removal** is safe — grep-verified zero callers for all targets.
- **`_send_expandable` merge** — callers that need the return value (stream_logs) must use the returning version. Fix: make `_send_expandable` return the message (like `_send_expandable_return` does), then delete `_send_expandable_return`.
- **Reconnect backoff** — must reset counter on successful event receipt, not just on successful reconnect.
- **Log retention** — need to pick a sane default (e.g. 7 days). Must be a background task, not inline.
- **GC task refs** — adding a `_background_tasks` set is mechanical but touches many lines.
- **rawMaxTokens** — SDK may return 0 for rawMaxTokens if it's not populated; need fallback.

## Summary

**11 items to fix** (skipping 3 deferred). ~95 lines of dead code to remove. 6 behavioral fixes. All surgical, no architecture changes.
