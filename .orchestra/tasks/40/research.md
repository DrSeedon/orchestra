# Task #40 — Research: P1 bugs from review #35

Verified against actual code **after #39 P0 round** (commit `48be668`). Line numbers are current.

SDK confirmed: `claude-agent-sdk` 0.1.72 at `.venv/.../claude_agent_sdk/types.py`.

---

## Status of each of the 19 items

### SDK/CLI — `app/backend_claude.py`

**#1 — SDK errors silent (THE worst).** OPEN.
- `_convert` for `ResultMessage` (line 291-306) hardcodes `"ok": True` (line 293). `is_error`/`errors`/`permission_denials` never read.
- `_convert` for `AssistantMessage` (line 203-216) never reads `msg.error`.
- SDK fields **confirmed**: `ResultMessage.is_error: bool`, `.errors: list[str] | None`, `.permission_denials: list | None`, `.model_usage`. `AssistantMessage.error: AssistantMessageError | None`.
- Downstream: `_handle_turn_end` (session.py:398) reads `meta.get("ok", True)` → currently always True → IDLE + auto-report fires on auth/billing/rate-limit failure. Fail-silent, the exact anti-pattern the project forbids.

**#2 — ThinkingBlock dropped.** OPEN.
- `_convert` AssistantMessage loop (line 204-216) handles TextBlock/ToolUseBlock/ToolResultBlock/ServerToolResultBlock — no `ThinkingBlock`.
- SDK **confirmed**: `ThinkingBlock(thinking: str, signature: str)`, exported from `__init__`.

**#3 — `usage["iterations"]` dead branch.** OPEN.
- Lines 262-289: `iters = usage.get("iterations", [])` always `[]`. The `if iters:` cost loop (281-287) is dead; `else` (288-289) is the live path. `last = iters[-1] if iters else usage` (263) is noise.
- `"iterations"` confirmed absent from SDK. The per-model breakdown is `model_usage` (we never read it; not needed for cost — `total_cost_usd` already captured).

**#4 — `context_pct` from billing wrong.** OPEN.
- Lines 268-273: computes `ctx_pct` from `input+cache_create+cache_read` against `CONTEXT_LIMITS`. This is billing tokens for the last turn, not window occupancy. `_refresh_context_from_api` (session.py:729) overwrites it ~1s later with the authoritative `get_context_usage()` value → transient wrong %, and the >30% "context corrected" log (session.py:740) is just our bad estimate being fixed.

### Session — `app/session.py`

**#5 — session_id=None during compact.** ✅ FIXED by #39. Verified: `compact()` no longer nulls `session_id`; ack turn uses `_ensure_backend(force_fresh=True)` (line 678) which passes `resume=None` without mutating `self.session_id`. The DB row keeps the last good token. No action.

**#6 — cost under-counts after reconnect.** OPEN.
- `_handle_turn_end` line 406: `self.cost_usd += max(0, new_cost - self._last_cost)`. `total_cost_usd` is cumulative **per session_id**; after compact/reconnect the new session_id resets it to a smaller number → negative delta → clamped to 0 → first turn after every session change contributes $0. Same for `cost_usd_cached` (409). `self._last_cost` (407) not reset on session_id change. Detectable: `sid = meta.get("session_id")` already read at line 402.

**#7 — persist race.** ✅ FIXED by #39. Verified: `_persist()` (line 803) is single-flight via `_persist_loop` (818) with a dirty flag, one task at a time, `add_done_callback`. No action.

**#8 — stale-prompt on failed inject.** OPEN.
- `send()` lines 207-217: when templates changed, `self._template_hash = current_th` (214) and `self._prompt_injected = True` (217) are set **before** `await backend.send(message)` (235). If `_ensure_backend()` raises (line 230) the flags are already mutated and never rolled back → next send skips re-injecting the updated prompt. Worker runs rest of life on old instructions.

**#9 — auto-report wrong stop_reason.** OPEN.
- `_fire_auto_report` (375) correctly snapshots `last_texts` (385). BUT the manager callback `_on_worker_idle` (manager.py:805) **re-reads `worker_session._turn_logs` live** (817-821) to extract `stop_reason`. By the time the task runs, the next turn may have cleared `_turn_logs` (session.py:222/488) → wrong or missing stop_reason. The stop_reason should be captured at fire time and passed to the callback.

**#10 — auto_resume_all drops waiting state.** OPEN.
- `auto_resume_all` (manager.py:887): `UPDATE sessions SET status='idle' WHERE status != 'idle'` flips `waiting` → `idle`. `was_running` (880) only captures `running`. Resumable filter (884) is `status IN ('running','idle')` — **`waiting` rows are excluded from resume entirely** AND get flipped to idle in DB. A worker parked on a bg job loses its waiting state on restart. Note: bg jobs themselves survive (separate table), but status no longer reflects parked.

**#11 — _flush_pending loses batch on error.** OPEN.
- `_flush_pending` (464): `msgs = list(...)` (470) then `self._pending_messages.clear()` (471). On exception in the try (495-498) `msgs` is NOT requeued → batch lost. (Note: the `if self._compacting` branch at 482-485 DOES requeue — only the outer `except` is missing it.)

### Workspace / Manager

**#12 — squash stats first-ref-only.** PARTIALLY OPEN.
- `_build_squash_message` (workspace.py:178) already uses `.finditer()` (183) → message lists all refs. ✅
- BUT `_parse_merged_commits` (line 441) still uses `_TASK_REF_RE.search(message)` (457) → attributes file stats to **only the first ref**. Co-referenced tasks get zero stats in `by_par`. This feeds `link_commits_to_task` (main.py:758-760). Fix: iterate `.finditer()` and attribute the commit to each distinct ref.

**#13 — _log/_persist thread-pool contention.** OPEN.
- `_log` (session.py:831) and `_persist_loop` (823) use the **default** executor (`run_in_executor(None, ...)`) — shared with `asyncio.to_thread` git ops. Each `add_log`/`save_session` opens a fresh `_conn()` (3 PRAGMAs). Under 10 agents, hundreds of logs/sec choke the pool that merges/spawns also use. Fix: dedicated `ThreadPoolExecutor` for DB writes.

**#14 — blocking subprocess at resume.** OPEN.
- `_load_from_db` (manager.py:729-732): synchronous `subprocess.run(["git","rev-parse",...])` in the event loop during mass resume. (`_auto_commit_if_dirty` is correctly wrapped in `to_thread` at line 505 — inconsistent.) Fix: `await asyncio.to_thread(...)`.

**#15 — `_session_locks` unused, no scope-lock.** CORRECTED → mostly N/A.
- Architecture review's correction stands: `get_session_lock` IS used (main.py:753 merge, 795 switch-branch). NOT dead code.
- The real HTTP-spawn-vs-queue TOCTOU is a genuine but **P2-ish** concern; the reliability review flagged it P1 but the fix (scope-level spawn lock) is a larger design change. **Recommend deferring** — `change_orchestrator_scope` already documents and partially mitigates the TOCTOU under `_lifecycle_lock` (manager.py:598). The minor `_session_locks` leak (never evicted) is P3. **No code change in this round** unless orchestrator insists; will note in plan.

**#16 — merge chain on shared pool / blocks event loop.** OPEN (more severe than stated).
- `merge_worktree_to_main` (main.py:755) and `switch_worktree_branch` (main.py:797) are called **synchronously inside async endpoints** — NOT via `to_thread`. `fcntl.flock(LOCK_EX)` (blocking) + ~10 `subprocess.run` block the **entire event loop** until the lock is free. Fix: wrap both calls in `asyncio.to_thread`. (This subsumes the "dedicated git executor" suggestion — for ~10 users, `to_thread` on the default pool is enough; merges serialize on the file lock anyway.)

**#17 — `_pending_messages` lost on restart.** OPEN but **recommend DEFER**.
- `_pending_messages` (session.py:107) is memory-only. Lost on restart mid-turn. Persisting to an inbox table is a real feature with migration + load-path wiring + dedup-on-resume complexity. For ~10 users this is a rare edge (restart exactly while a message is queued mid-turn). **Recommend deferring to its own task** — it's the heaviest item and orthogonal to the rest. Will flag in plan; orchestrator decides.

### Architecture

**#18 — split-brain DB (tm.py).** OPEN.
- `app/tm.py:16` hardcodes `DB_PATH = .../data/orchestra.db` and `:22` its own `_conn()` — ignores `ORCHESTRA_DB_PATH`. `db.py` honors it via `_resolve_db_path` (db.py:12). Bites tests + parallel worktrees (split tasks vs sessions into two files). Fix: delete tm.py's `DB_PATH`+`_conn`, `from app.db import _conn`. Pure deletion (~12 lines). Must verify all tm.py `_conn()` callers still work (same signature).

**#19 — stream_logs DB poll churn.** OPEN.
- `get_logs` (db.py:564) opens fresh `_conn()` each call. Two pollers:
  - main.py `stream_session_logs` (486): `while True: get_logs(...); sleep(0.5)` per SSE connection.
  - tg_bridge.py `stream_logs` (876): `while True: get_logs(...); sleep(2)` per orchestrator topic.
- Fix (MVP): (a) reuse one connection per loop instead of reconnecting each tick; (b) back off interval when last poll returned 0 rows (0.5s→3s idle for SSE; 2s→5s for TG). `idx_logs_session` already makes the query cheap — the connect churn is the waste.
- Simplest clean approach: add a `get_logs(..., conn=None)` optional-connection param to db.py, open one connection at loop start, pass it in. Adaptive backoff: track empty-poll count.

---

## Affected files
- `app/backend_claude.py` — #1, #2, #3, #4 (the `_convert` ResultMessage + AssistantMessage paths)
- `app/session.py` — #6 (cost reset), #8 (inject flag ordering), #11 (flush requeue), #13 (DB executor), #9 (pass stop_reason via on_idle)
- `app/manager.py` — #9 (on_idle callback signature), #10 (resume waiting), #14 (to_thread rev-parse), #13 (DB executor wiring if shared)
- `app/workspace.py` — #12 (`_parse_merged_commits` finditer)
- `app/main.py` — #16 (to_thread merge/switch), #19 (SSE poll connection reuse + backoff)
- `app/tg_bridge.py` — #19 (TG poll connection reuse + backoff)
- `app/tm.py` — #18 (delete dup DB_PATH/_conn)
- `app/db.py` — #19 (optional `conn` param on get_logs), maybe a `get_db_executor()` helper for #13

## Already fixed (verify-only) — no action
- **#5** session_id during compact (force_fresh)
- **#7** persist single-flight

## Recommend DEFER (flag to orchestrator)
- **#15** scope-level spawn lock — larger design change, partially mitigated already
- **#17** persist `_pending_messages` — heavy feature (inbox table + resume wiring), rare edge for 10 users

## Risks / edge cases
- **#1**: must not break the happy path — `ok` must stay True when `is_error` False. `permission_denials` is informational (don't flip `ok` on denial alone — a denied tool is normal). Map `ok = not is_error`.
- **#4**: removing billing-derived ctx_pct means `_handle_turn_end` gets `context_pct=0` until the API refresh lands. Acceptable (refresh fires immediately, line 427) but the `turn ended (... ctx:0%)` log will briefly show 0%. Could keep `_last_context` from previous turn instead of overwriting with 0.
- **#6**: reset must use the session_id comparison — but `_handle_turn_end` sets `self.session_id = sid` at 404 BEFORE the cost calc at 406. Must capture `old_sid` before line 404.
- **#9**: changing `on_idle` signature touches both the call (session.py:389) and the def (manager.py:805) + `_fire_auto_report` must compute stop_reason from its snapshot.
- **#12**: `link_commits_to_task` is called per ref (main.py:758) — once stats attribute to all refs, each ref links its own commit list. Verify no double-payment logic downstream.
- **#13**: dedicated executor must be created lazily on the running loop and shut down cleanly; tests that assert on `run_in_executor` may need updating.
- **#19**: SSE generator must close its connection on disconnect (`request.is_disconnected()`); TG loop runs forever — connection leak if not closed on cancel. Use try/finally.
