# Review #35 — Correctness & Race Conditions

Scope: `app/backend_claude.py`, `app/session.py`, `app/manager.py`, `app/workspace.py`
Reviewer: review-correctness (Opus). Focus: real bugs that break the system, not style.

Severity: **P0** = crash/data loss · **P1** = wrong behavior · **P2** = degradation · **P3** = smell.

---

## P0 — Crash / Data Loss

### P0-1 — `compact()` re-entry corrupts session: `_compacting` cleared before `send()`, opens window for double-compact and lost messages
`app/session.py:649-652`

`compact()` sets `self._compacting = False` (line 649) **before** calling `self.send(preamble...)` (line 652). The whole point of `_compacting` is to gate `send()` into the pending-queue (lines 167-171) and to gate `_handle_turn_end`'s auto-compact trigger (line 442 `not self._compacting`). By clearing it one line too early:

1. The acknowledge turn started by `send()` (652) runs with `_compacting=False`. When that turn ends, `_handle_turn_end` runs the `ctx_pct > 90` check (line 442). If the summary turn still reports high context (the API refresh in `_refresh_context_from_api` can lag), it fires **`_auto_compact()` again → recursive compact** while we're still inside the first one.
2. Any message that arrived during the COMPACT_PROMPT turn (lines 625-632) was queued because `_compacting` was True. But nothing flushes `_pending_messages` here — `send()` at 652 goes through the lifecycle lock and starts a brand-new turn ignoring the queue. The queued messages are only flushed on the *next* `turn_end`. Acceptable, but combined with (1) the queued user messages can interleave with a second compaction.

**Worse:** there is **no re-entrancy guard at the top of `compact()`**. `_auto_compact` (line 710) and a manual `compact_worker` MCP call can both call `compact()` concurrently. Two compactions race on `self.session_id` (set to None at 648, then read by the resume path in `_make_backend`), on `self._backend` (both do `backend = self._backend or self._make_backend()` then `self._backend = None` in finally), and on cancelling `_listen_task`. Result: one compaction disconnects the backend the other is mid-send on → `RuntimeError: not connected` or a dangling client, and `session_id` can end up None permanently → **next resume starts a fresh session, full context loss.**

**Fix:**
```python
async def compact(self) -> dict:
    if self._compacting:
        return {"ok": False, "error": "compact already in progress"}
    self._compacting = True
    try:
        ... # all the body
        # keep _compacting True across the ack send:
        preamble = PREAMBLE.format(summary=summary)
        await self.send(preamble + "Acknowledge briefly.")  # but send() gates on _compacting!
    finally:
        self._compacting = False
```
Note the tension: `send()` (167) queues when `_compacting` is True, but compact's own ack send (652) must NOT be queued. Resolve by sending the ack through the backend directly (bypass `send()`), then clear `_compacting`, then flush pending. Minimal version:
```python
    old_session_id = self.session_id
    self.session_id = None
    preamble = PREAMBLE.format(summary=summary)
    async with self._lifecycle_lock:
        self._bump_turn_gen(); self._turn_logs = []
        self._turn_start = asyncio.get_event_loop().time()
        self.status = AgentStatus.RUNNING; self._persist()
        backend = await self._ensure_backend()
        await backend.send(preamble + "Acknowledge briefly.")
    self._compacting = False
    if self._pending_messages:
        asyncio.create_task(self._flush_pending())
```
and add the `if self._compacting: return ...` guard at the top.

---

### P0-2 — `compact()` cancels the listen task but the new turn never gets a listener → permanent zombie
`app/session.py:612-617, 638-652`

`compact()` cancels `self._listen_task` (612) and in `finally` sets `self._backend = None` (639). Then `send(preamble...)` (652) calls `_ensure_backend()` which **only creates a new `_listen_task` when it had to create a new backend** (`_ensure_backend` 236-252: the `create_task(_claude_event_loop())` is reached because `_backend is None` here, so this path is OK). **But** the `for _ in range(60)` poll (654-657) waits for `status == IDLE`. If the ack turn's `turn_end` never arrives (SDK hiccup), `compact()` returns `{"ok": True}` after 60s regardless, while `_compacting` is already False and a turn may still be RUNNING. The caller (`compact_worker` MCP) reports success on a session that's still mid-turn. Lower impact than P0-1 but the 60s blind poll with a hardcoded success return is a real correctness gap: **`after_pct` is read (659) with no guarantee the new turn finished**, so the reported compaction result can be a lie (`before_pct == after_pct` reported as success).

**Fix:** track the ack turn via an event/future set in `_handle_turn_end` for this generation, await it with timeout, and return `{"ok": False, "error": "ack turn did not complete"}` on timeout instead of a fabricated success.

---

### P0-3 — `_handle_turn_end` mutates state then schedules async work, but reads `self.status`/context concurrently with `_refresh_context_from_api` and auto-compact
`app/session.py:421, 440, 444`

`_handle_turn_end` fires three `asyncio.create_task()` calls — `_refresh_context_from_api` (421), `_notify_scope_idle` (440), `_auto_compact` (444) — and these run **after** the function returns, concurrently with the next `send()`. The ordering bug: `_refresh_context_from_api` (691) writes `self._last_context["percentage"]` and calls `self._persist()`. `_auto_compact` (710) → `compact()` reads `self._last_context["percentage"]` at 608. Meanwhile the hibernate task may have already disconnected the backend (so `_refresh_context_from_api`'s `self._backend` check at 692 races with `_disconnect_backend` setting it None). These are individually guarded by `if not self._backend`, but the **`_persist()` calls race**: `_refresh_context_from_api._persist()` and `_handle_turn_end._persist()` (438) both run `run_in_executor(save_session, self._to_db_dict())`. `_to_db_dict()` snapshots mutable state at call time; two snapshots taken microseconds apart can be written to SQLite **out of order** (executor threads, no ordering guarantee), so a stale `status="running"` snapshot can overwrite a fresh `status="idle"`. See P1-3 for the systemic version.

**Fix:** serialize persists per-session (single-flight or a monotonic version column). At minimum, have `_refresh_context_from_api` update only context fields via a targeted UPDATE rather than a full-row `save_session` that can clobber status/cost.

---

### P0-4 — Worktree merge does not hold a lock against worktree removal / concurrent session teardown
`app/workspace.py:252` (`merge_worktree_to_main`) vs `app/manager.py:552-563` (`remove`)

`merge_worktree_to_main` takes a **file lock on `.git/orchestra-merge.lock`** (261) which serializes two merges against each other — good. But `remove()` (manager 552) calls `remove_worktree` (560) with **no such lock**. If the orchestrator merges worker A while killing worker A (or B in the same repo), `git worktree remove --force` (workspace 565) can run while the merge is mid-`git checkout main` / `git stash pop`, leaving the repo on the wrong branch or with a stuck stash. Worse: removing worker A's worktree while its branch is being squash-merged can delete the branch's working tree out from under `git merge --squash` → merge aborts with a confusing error, and the `finally` restore (377) may run against a now-inconsistent repo. **Two merges are serialized; merge-vs-remove and merge-vs-switch_branch are not** (switch_worktree_branch does take the same lock at 502, so that pair is fine; remove is the hole).

**Fix:** acquire the same `.git/orchestra-merge.lock` in `remove_worktree`/`remove()` before touching the worktree, or refuse removal while a merge lock is held.

---

## P1 — Wrong Behavior

### P1-1 — `session_id` set to None during compact is observable by other coroutines → stale resume
`app/session.py:648`

`self.session_id = None` (648) is set, then `send()` (652) reads it via `_make_backend` → `resume_id = self._session_id or self._resume_id`. Between 648 and the new turn obtaining a fresh `session_id` from `ResultMessage` (backend_claude 232-233), **any concurrent path that persists** (e.g. a queued `_persist` from `_refresh_context_from_api`) writes `session_id=NULL` to the DB. If the server restarts in that window, `auto_resume_all` (manager 878-881) filters `WHERE session_id IS NOT NULL` → **the session is silently not resumed**. The agent vanishes after a restart that lands mid-compact.

**Fix:** don't null `session_id` in memory; pass `resume=None` explicitly into the next backend build instead (add a `force_fresh` flag to `_make_backend`). Keep the DB row's `session_id` pointing at the last good token until the new one lands.

### P1-2 — `cost_usd` / token totals double-count or lose data across reconnect
`app/session.py:399-407`

`_handle_turn_end` does `self.cost_usd += max(0, new_cost - self._last_cost)` and `self._last_cost = new_cost`. `new_cost` is `total_cost_usd` from the `ResultMessage`, which the SDK reports **cumulatively per session_id**. After a `reconnect()` (backend_claude 181) or compact (new session_id), the SDK's cumulative cost **resets to a smaller number** for the new session. Then `new_cost - self._last_cost` is negative → clamped to 0 by `max(0, …)`, so the **first turn after every reconnect/compact contributes $0 cost** (under-count). Conversely `total_turns += nt` (405) uses per-turn `num_turns`, which is fine. Token totals (406-407) use per-turn deltas — fine. Only cost is wrong, and only mildly (under-reports). Monopoly-money project, so **P1 not P0**, but the dashboard cost is provably wrong after any compaction.

**Fix:** reset `self._last_cost = 0` whenever `session_id` changes (detect in `_handle_turn_end` when `sid != previous`).

### P1-3 — Persist races: full-row `save_session` from multiple coroutines can resurrect stale status/cost
`app/session.py:765-768`

`_persist()` snapshots the *entire* row via `_to_db_dict()` and writes it on a thread-pool executor with **no ordering guarantee**. Callers: `_handle_turn_end` (438), `_refresh_context_from_api` (704), `interrupt` (589), `_flush_pending` (477), `_idle_hibernate` indirectly, etc. Two near-simultaneous persists with different snapshots → SQLite `ON CONFLICT DO UPDATE` applies whichever executor thread commits last. Observed consequences: status flips back to `running` after going idle; a refreshed-but-stale cost overwrites a newer one. The `_drain_persist` helper (770) is only awaited in `change_orchestrator_scope` — everywhere else persists float free.

**Fix:** make `_persist` single-flight (coalesce: if a persist is in-flight, mark dirty and re-persist once it completes) OR move to field-scoped UPDATEs. The single-flight pattern is ~10 lines and matches the project's "one way" principle.

### P1-4 — `_template_hash` update on injection is lost if the inject turn fails
`app/session.py:208-213`

In `send()`, when templates changed, `self._template_hash = current_th` (210) and `self._prompt_injected = True` (213) are set **before** the turn is actually sent (231). If `_ensure_backend()` raises (225-229), the function sets status IDLE and re-raises, but `_template_hash`/`_prompt_injected` are **already mutated** and never rolled back. Next `send()` sees `_prompt_injected=True` → **skips re-injecting the updated prompt**, so the worker runs the rest of its life on the *old* instructions even though the hash claims it's updated. Silent stale-prompt bug.

**Fix:** set `_prompt_injected`/`_template_hash` only after `await backend.send(message)` succeeds (move past line 231).

### P1-5 — `_fire_auto_report` reads `_turn_logs` that the next turn clears → empty/over-stale reports
`app/session.py:379, 447` + `216`/`473`

`_fire_auto_report` (369) captures `last_texts = self._turn_logs[-5:]` synchronously (379) — good, it copies. But it's called at line 447 **after** `_handle_turn_end` already set `self.status = IDLE` (437) and **before** `_schedule_hibernate` (453). If a `send()` lands between turn_end and the auto-report task actually running `on_idle`, `send()` resets `self._turn_logs = []` (216) under the lifecycle lock. Since `last_texts` was already copied, the report content is safe — **but** `_make_idle_callback._on_worker_idle` (manager 812) re-reads `worker_session._turn_logs` live for the stop_reason (813), which by then may be the *next* turn's logs or empty → wrong `stop_reason` appended to the report, or none.

**Fix:** pass the stop_reason into the `on_idle` callback alongside `last_texts` instead of re-reading `_turn_logs` live in the callback.

### P1-6 — `auto_resume_all` flips ALL non-idle rows to idle before resume, losing `waiting` (bg-job) state
`app/manager.py:882`

`c.execute("UPDATE sessions SET status='idle' WHERE status != 'idle'")` resets `running` **and `waiting`** to `idle`. A session that was `waiting` on a background job (session 434) loses that state on restart; `was_running` (875) only captured `running`, so `waiting` sessions get neither a restart notice nor their waiting status back. The bg job (if it survives) will still try to wake the agent, but the agent's status no longer reflects that it's parked. Minor divergence, but it's a documented feature ("bg jobs survive hibernate") that's broken across restart.

**Fix:** capture `waiting` ids too and restore them, or re-derive waiting state from `bg_manager.has_active_jobs` during resume.

### P1-7 — `_parse_merged_commits` attributes a multi-task squash commit's stats to ONLY the first task ref; co-referenced tasks get zero
`app/workspace.py:424` (corrected after Codex cross-review — original draft had the symptom backwards)

`_parse_merged_commits` walks `old_head..HEAD` and attributes file stats by parsing the task ref **from the squash commit's message** using `_TASK_REF_RE.search(message)` (424) — which returns **only the first match**. A squash commit whose message references both `#10` and `#11` (because `_build_squash_message` concatenates all sub-commit refs) is therefore attributed entirely to `#10`; **`#11` silently gets nothing** in the returned `by_par` dict. Downstream payment/stat distribution under-reports for every co-referenced task after the first. (My initial draft claimed double-counting via `.finditer`; the code actually uses `.search`, so the real bug is under-attribution, not double-count.) P1 — wrong stats, no crash.

**Fix:** iterate refs — `for m in _TASK_REF_RE.finditer(message): ...` — and attribute the commit to each referenced task (or document a deliberate first-ref-wins rule and have `_build_squash_message` not emit the others).

---

## P2 — Degradation

### P2-1 — `_claude_event_loop` reconnect loop can spin tightly on repeated immediate failures
`app/session.py:256-298`

On exception, the loop reconnects (285) and `continue`s the outer `while True`. `reconnect()` (backend_claude 181) sleeps 2s, but if `events()` immediately raises again (e.g. backend returns instantly because client is None after a failed connect), the loop re-enters, reconnects, and on **success of reconnect but immediate re-failure of events()** there's no backoff between iterations beyond reconnect's own 2s. Under a persistently broken backend this is a 2s-interval spin logging errors forever (status was set IDLE only on reconnect *failure*, 295-298). Tolerable but noisy and resource-wasting.

**Fix:** add a failure counter; after N consecutive reconnects, give up → set IDLE, `_backend=None`, stop.

### P2-2 — ~~`get_session_lock` is dead code~~ → **CORRECTED to P3**: minor unbounded Lock dict, but the helper IS used
`app/manager.py:333-338`

**Correction (Codex cross-review):** my "zero callers" claim was a scoping error — I grepped only the 4 review files. `get_session_lock` has **two live callers** in `app/main.py:752` and `app/main.py:794` (`async with manager.get_session_lock(session_id):`), serializing per-session API operations. **Not dead code.** The only residual issue is that `_session_locks` never evicts on `remove()`, so it accumulates one `asyncio.Lock` per distinct session id for the process lifetime — a slow, bounded leak that's negligible for an MVP. Downgraded to **P3**; optional fix: `pop` the lock in `remove()`.

### P2-3 — `_idle_hibernate` checks `status != IDLE` but not pending messages → can hibernate with queued work
`app/session.py:495-507`

`_idle_hibernate` re-checks `status != IDLE` under the lock (501) but not `self._pending_messages`. If a message was queued (e.g. during compact) and the flush task hasn't flipped status to RUNNING yet (there's a 0.3s sleep in `_flush_pending` 456), hibernate can disconnect the backend (506) right as the flush is about to send. `_flush_pending` then calls `_ensure_backend()` (478) which reconnects — so it self-heals, but you pay a disconnect+reconnect and a possible lost-turn window. Cheap guard avoids it.

**Fix:** `if self.status != AgentStatus.IDLE or self._pending_messages: return` at line 501.

### P2-4 — `_load_from_db` runs `git rev-parse` synchronously in the event loop during resume
`app/manager.py:723-733`

`auto_resume_all` → `_load_from_db` calls `subprocess.run(["git", "rev-parse", ...])` (724) **without** `asyncio.to_thread`. During mass resume of many workers this blocks the event loop per worker (each git call is ~10-50ms but serialized and blocking). Same pattern in `_auto_commit_if_dirty` is correctly wrapped in `asyncio.to_thread` (manager 505). Inconsistent and blocks startup.

**Fix:** wrap the branch-detection subprocess in `asyncio.to_thread`.

---

## P3 — Smells

### P3-1 — `_codex_reasoning_effort` always returns `"high"` for both branches
`app/session.py:147-150` — the `if self.is_orchestrator` is dead; both return `"high"`. Collapse to `return "high"`.

### P3-2 — `_extract_tool_result` swallows JSON with a top-level `result` key only
`app/backend_claude.py:73-79` — if the tool result JSON is a list or a dict without `result`, it returns the raw text. Fine, but the `try/except (ValueError, TypeError)` won't catch a `KeyError` — there is none here, just noting the narrow contract. No action.

### P3-3 — `old_session_id` computed but unused
`app/session.py:647` — `old_session_id = self.session_id` is assigned and never read. Dead. Remove.

### P3-4 — `_on_task_done` sets status IDLE on "silent death" but doesn't clear `_turn_start`
`app/session.py:523-527` — leaves `_turn_start` non-zero, so a later resumed turn's timeout math (265) compares against a stale start time and can trigger a spurious immediate "turn timeout". Minor; reset `_turn_start = 0` there.

---

## Summary table

| ID | Sev | File:line | One-liner |
|----|-----|-----------|-----------|
| P0-1 | P0 | session.py:649 | `_compacting` cleared before ack send → recursive/concurrent compact, lost session_id |
| P0-2 | P0 | session.py:654 | compact 60s blind poll returns fabricated success |
| P0-3 | P0 | session.py:421,704 | full-row persist races between turn_end and context refresh |
| P0-4 | P0 | workspace.py:252 vs manager.py:560 | merge holds lock; remove_worktree doesn't → repo corruption |
| P1-1 | P1 | session.py:648 | session_id=None observable → not resumed after restart |
| P1-2 | P1 | session.py:400 | cost under-counts first turn after every reconnect/compact |
| P1-3 | P1 | session.py:765 | unordered full-row persists resurrect stale status |
| P1-4 | P1 | session.py:208-213 | stale-prompt: inject flags set before send succeeds |
| P1-5 | P1 | manager.py:813 | auto-report re-reads live _turn_logs → wrong stop_reason |
| P1-6 | P1 | manager.py:882 | resume drops `waiting` bg-job state |
| P1-7 | P1 | workspace.py:424 | squash stats go to first task ref only; co-refs get zero (corrected) |
| P2-1 | P2 | session.py:285 | reconnect loop can spin without backoff cap |
| P2-2 | P3 | manager.py:333 | `_session_locks` never evicted (minor leak; NOT dead — used in main.py) |
| P2-3 | P2 | session.py:501 | hibernate ignores pending messages |
| P2-4 | P2 | manager.py:724 | blocking git rev-parse in event loop on resume |
| P3-1..4 | P3 | various | dead code / minor cleanups |

**Top fixes by impact:** P0-1 (compact re-entry) and P1-1/P0-2 (session_id loss) are the highest-value — they cause real context loss, the worst failure mode for this system. P0-4 (merge vs remove lock) is the highest data-integrity risk on the git side.
