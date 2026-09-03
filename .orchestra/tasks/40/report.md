# Task #40 — Final Report: 13 P1 fixes from review #35

## Summary
Fixed 13 P1 bugs (deduplicated from review #35), verified against current code post-#39.
2 items (#5, #7) were already fixed by #39 — verified, no action.
2 items (#15, #17) deferred to separate tasks (orchestrator-approved).

## Fixes by file

### app/backend_claude.py (+/- in `_convert`)
- **#1 SDK errors silent** — read `is_error`/`errors`/`permission_denials`; `turn_end` meta now `ok = not is_error` + `is_error`/`errors`. `AssistantMessage.error` surfaced as an `error` event. `permission_denials` is informational (logged, does NOT flip `ok` — per orchestrator decision).
- **#2 ThinkingBlock** — added `ThinkingBlock` import + branch → `"thinking"` event.
- **#3 dead `iterations`** — deleted the phantom `usage["iterations"]` branch; cost from flat usage dict.
- **#4 billing ctx_pct** — stopped computing context % from billing tokens; `context_pct`/`context_tokens` now 0, `get_context_usage()` is the single source.

### app/session.py
- **#2** — `_handle_event` handles `"thinking"` (logged, not appended to `_turn_logs`).
- **#4** — `_handle_turn_end` keeps previous `_last_context["percentage"]` when incoming is 0; auto-compact trigger reads `live_pct` from `_last_context`.
- **#6 cost under-count** — reset `_last_cost`/`_last_cost_cached` to 0 when `session_id` changes (before the `self.session_id = sid` assignment).
- **#8 stale prompt** — inject flags (`_template_hash`, `_prompt_injected`, `system_prompt`) committed AFTER `backend.send()` succeeds; a failed connect no longer leaves a false "injected" flag.
- **#9 wrong stop_reason** — `_fire_auto_report` captures `_last_stop_reason` at fire time and passes it to `on_idle`; skips report when `_last_turn_ok` is False (don't auto-report a failed turn as success).
- **#11 lost batch** — `_flush_pending` requeues `msgs` at front on error.
- **#13 pool contention** — dedicated `_db_executor()` (ThreadPoolExecutor max_workers=4) for `_log`/`_persist`, separate from git ops on the default pool.
- New fields: `_last_turn_ok`, `_last_stop_reason`.

### app/manager.py
- **#9** — `_on_worker_idle` signature `(... , stop_reason="")`; dropped the dead live `_turn_logs` scan for `stop_reason=` (it never matched).
- **#10 waiting lost** — `auto_resume_all` captures `was_waiting`, includes `waiting` in the resumable filter, and restores WAITING status post-load if bg jobs are still active.
- **#14 blocking subprocess** — git `rev-parse` at resume wrapped in `asyncio.to_thread`.

### app/workspace.py
- **#12 squash stats** — `_parse_merged_commits` uses `.finditer()`, attributes each commit's stats to ALL referenced task refs (not just the first).

### app/main.py
- **#16 event-loop block** — `merge_worktree_to_main` and `switch_worktree_branch` (both do `fcntl.flock` + ~10 subprocess) now run via `asyncio.to_thread`.
- **#19 SSE poll churn** — `stream_session_logs` reuses one SQLite connection per generator (passed to `get_logs`), adaptive backoff 0.5s→3s when idle, closes conn in `finally`.

### app/tg_bridge.py
- **#19 TG poll churn** — `stream_logs` reuses one connection, adaptive backoff 2s→5s when idle.

### app/db.py
- **#19** — `get_logs(..., conn=None)` optional connection; closes only connections it opened.

### app/tm.py
- **#18 split-brain DB** — deleted duplicate `DB_PATH` + `_conn()`, now `from app.db import _conn` (honors `ORCHESTRA_DB_PATH`). Verified `tm._conn is db._conn`. Removed orphaned `Path` import.

## Tests
- `UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest -q` → **201 passed**, 5 skipped.
- 7 failures are **PRE-EXISTING** (confirmed via `git stash` — they fail identically on clean HEAD `48be668`):
  - `test_disallowed_tools::test_worker_keeps_subagent_tool` (stale: asserts `== []` but `_ALWAYS_DISALLOWED` has 4 tools)
  - 4× `test_auto_report_*` (reference nonexistent `app.session.AUTO_REPORT_IDLE_SEC`)
  - `test_manager::test_remove_deletes_from_dict_and_db`, `test_passes_orch_names_to_tg_bridge_when_flag_set`
- My changes introduce **0 new failures**. All `app/` modules import cleanly.

## Codex review
- See `docs/tasks/40/codex-review-impl.md` (run via `codex exec` on the diff — MCP codex_review was non-functional, bash approved by orchestrator).
- **0 BLOCKING**, 2 suggestions — both applied:
  1. #10 waiting-restore was worker-loop-only → applied to orchestrator resume loop too (orchestrators can own bg jobs).
  2. tg_bridge `_poll_conn` now wrapped in `try/finally: close()` around the loop (explicit close on task cancel, not GC-only).
- Codex independently verified: #6 reset ordering correct, #8 flags-after-send correct, #13 persist still single-flight per session, #19 reads hold no read transaction between polls.

## Breaking changes
- None external. `on_idle` signature gained a defaulted `stop_reason` param (one internal caller). `get_logs` gained an optional `conn` param (backward-compatible). No DB schema changes.

## Known issues / tradeoffs
- Pre-existing broken tests (7) left untouched — out of P1 scope (confirmed failing on clean HEAD `48be668`). Recommend a separate cleanup task. They are: `test_disallowed_tools::test_worker_keeps_subagent_tool`, 4× `test_auto_report_*` (missing `AUTO_REPORT_IDLE_SEC`), `test_remove_deletes_from_dict_and_db`, `test_passes_orch_names_to_tg_bridge_when_flag_set`.

## Deferred (separate tasks)
- **#15** scope-level spawn lock (TOCTOU on HTTP spawn) — larger design change.
- **#17** persist `_pending_messages` to inbox table — heavy feature, rare edge.
