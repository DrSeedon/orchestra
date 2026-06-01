# Task #39 — Research: 7 P0 bugs from review #35

Verified all line numbers against **current** code (worktree `task-39/fix-p0`). Code shifted slightly since review #35; corrected numbers below.

Files owned: `session.py`, `manager.py`, `backend_claude.py`, `workspace.py`, `main.py`.

---

## Bug 1 — `compact()` re-entry (session.py)

**Current code:** `compact()` at `session.py:591`.
- `self._compacting = True` at **line 609** — NO re-entrancy guard before it.
- `self.session_id = None` at **line 648**.
- `self._compacting = False` at **line 649** — cleared BEFORE the ack `self.send(...)` at **line 652**.
- `old_session_id = self.session_id` at **line 647** — dead (P3-3, assigned never read).

**Problem:**
- No guard → `_auto_compact()` (line 444, fires on `ctx_pct>90`) and a manual `compact_worker` MCP call can both enter `compact()` concurrently. They race on `self.session_id`, `self._backend` (set None in finally line 639), and `_listen_task` cancel. → `RuntimeError: not connected`, dangling client, or `session_id=None` permanently → **full context loss on next resume**.
- `_compacting` cleared at 649 before ack send at 652 → ack turn runs with `_compacting=False`. When that turn's `_handle_turn_end` runs (line 442 checks `ctx_pct>90 and not self._compacting`), if API context lags it can fire `_auto_compact()` again → recursive compact.

**Interaction:** `send()` at line 167 gates on `_compacting` (queues to `_pending_messages`). So the ack send at 652 must NOT be queued — it has to bypass the `send()` guard. Current code "works" only because `_compacting` is already False at 649, which is exactly the bug. Fix must keep `_compacting=True` across ack but send the ack through the backend directly (not via `self.send()`).

**Fix plan:** add `if self._compacting: return {"ok": False, "error": "compact already in progress"}` at top. Send ack via `backend.send()` directly inside lifecycle lock (mirror `_flush_pending` structure lines 470-479), clear `_compacting` after, then flush pending. Remove dead `old_session_id`.

---

## Bug 2 — compact 60s blind poll (session.py:654)

**Current code:** lines 654-661.
```python
for _ in range(60):
    await asyncio.sleep(1)
    if self.status == AgentStatus.IDLE and self._last_context.get("percentage", before_pct) < before_pct:
        break
after_pct = self._last_context.get("percentage", 0)
...
return {"ok": True, ...}   # line 661 — ALWAYS ok:True even on timeout
```

**Problem:** returns fabricated `{"ok": True}` after 60s regardless of whether the ack turn completed. `compact_worker` MCP reports success on a session still mid-turn. `after_pct` may equal `before_pct` (no actual compaction) yet reported as success.

**Fix plan:** track ack-turn completion via an `asyncio.Event` (or future) keyed to the turn generation, set it in `_handle_turn_end`. Await with timeout. On timeout → `return {"ok": False, "error": "ack turn did not complete", ...}`.

**Note:** the existing loop break condition also depends on context dropping (`< before_pct`), which the new event approach replaces cleanly. The event must be set for THIS compact's ack turn only — bind to `_turn_gen` captured after the ack send starts.

---

## Bug 3 — persist race (session.py:421, 704, 765)

**Current code:**
- `_persist()` at **line 765**: `run_in_executor(None, save_session, self._to_db_dict())`. `_to_db_dict()` (778) snapshots full row. Futures tracked in `_persist_futs` (line 767) but never ordered.
- `_handle_turn_end` calls `_persist()` at **line 438** (after setting status IDLE/WAITING) AND schedules `_refresh_context_from_api` as a task at **line 421**.
- `_refresh_context_from_api` calls `_persist()` at **line 704** — runs concurrently, full-row snapshot.

**Problem:** two `run_in_executor(save_session, ...)` calls with different snapshots commit on separate executor threads with NO ordering guarantee. A stale `status="running"` snapshot can overwrite a fresh `status="idle"`. `save_session` is an UPSERT (full row), so last-writer-wins on ALL fields.

Callers of `_persist()`: lines 164, 222, 228, 270, 297, 321, 438, 477, 483, 521, 527, 549, 574, 589, 689, 704, 733, 763.

**Fix plan (single-flight, ~10 lines, matches "one way" principle):** coalesce persists. Keep an in-flight flag + dirty flag. If a persist is running, mark dirty; when it finishes, if dirty, persist once more with the latest snapshot. This serializes writes per-session and guarantees the LAST snapshot wins (which is correct — most recent state). Replaces the free-floating `_persist_futs` set.

Chosen over field-scoped UPDATEs: single-flight is simpler, fixes ALL callers at once, and "last snapshot wins" is the desired semantics. `_drain_persist` (770, used in `change_orchestrator_scope`) must still work — adapt it to await the in-flight + any queued re-persist.

---

## Bug 4 — merge vs remove lock (workspace.py:573 vs :282)

**Current code:**
- `merge_worktree_to_main` (273) takes `fcntl.flock` on `repo/.git/orchestra-merge.lock` at lines 282-283.
- `switch_worktree_branch` (503) takes the SAME lock at 528-529.
- `remove_worktree` (573) takes **NO lock**. Runs `git worktree remove --force` at line 590.
- `manager.remove()` (manager.py:552) calls `remove_worktree` at line 560 via `asyncio.to_thread`.

**Problem:** removing worker A's worktree while a merge is mid-`git checkout main`/`git merge --squash` can delete the working tree out from under the merge → merge aborts, repo left on wrong branch / stuck stash.

**Fix plan:** acquire the same `.git/orchestra-merge.lock` (LOCK_EX) at the top of `remove_worktree`, wrapping the `git worktree remove`. Use `_resolve_repo(worktree_path, repo_path)` to compute the lock path consistently with merge/switch. `remove_worktree` already resolves the repo dir manually (lines 578-589) for cwd; reuse `_resolve_repo` for the lock path (it's the same `.git` common dir).

**Edge case:** `remove_worktree` returns early at line 575 if `wt` doesn't exist — keep that BEFORE acquiring the lock (no point locking to remove nothing).

---

## Bug 5 — orphaned worktree on spawn crash (manager.py:527)

**Current code:** `create_session` try block creates worktree at **line 508** (`create_worktree`), sets `session.cwd/worktree_path/branch`. The `except Exception:` at **line 527** only calls `delete_session(session.id)` (528) then re-raises (529).

**Problem:** if `session.start()` (524), `_inject_skills_to_worktree` (512), or `_safe_format_prompt` (516) raises AFTER the worktree is created, the worktree is leaked on disk + as a registered git worktree. DB row deleted but worktree orphaned.

**Fix plan:** in the except block, if `session.worktree_path` was set, call `remove_worktree(repo_path, session.worktree_path)` (wrapped in try/except so cleanup failure doesn't mask the original error) before `delete_session` + re-raise. Must use `asyncio.to_thread` (consistent with line 560). `repo_path` is the function param (available in scope).

---

## Bug 6 — zombie CLI on connect timeout (backend_claude.py:128)

**Current code:** `connect()` at lines 128-134.
```python
async def connect(self) -> None:
    self._client = self._make_client()              # 129
    try:
        await asyncio.wait_for(self._client.connect(), timeout=60)   # 131
    except Exception as e:
        logger.error(...)                           # 133
        raise                                       # 134 — _client NOT cleaned up
```

**Problem:** `_client` is assigned at 129. If `connect()` times out / raises, `_client` stays set but the underlying CLI subprocess may be spawned and never disconnected → zombie process. Caller (`session._ensure_backend` line 245) sets `self._backend = None` on failure but never calls `backend.disconnect()`, so the half-connected client leaks.

**Fix plan:** in the except, attempt `await self._client.disconnect()` (best-effort, wrapped in try/except), set `self._client = None`, then re-raise. Mirrors the existing `disconnect()` pattern (155-161).

---

## Bug 7 — restart_cli → 500 (main.py:558)

**Current code:** lines 551-561.
```python
await session._disconnect_client()                  # 558 — method does NOT exist
session.status = session.status.__class__("idle")   # 559 — ugly workaround
session._persist()                                   # 560
```

**Problem:** `AgentSession` has `_disconnect_backend` (session.py:736), NOT `_disconnect_client`. Calling `restart_cli` → `AttributeError` → 500.

`AgentStatus` is NOT imported in main.py (only `is_orchestrator_role` imported locally at line 1099), hence the `status.__class__("idle")` hack.

**Fix plan:** change line 558 to `await session._disconnect_backend()`. Import `AgentStatus` from `app.session` and set `session.status = AgentStatus.IDLE` at 559. Add the import at the existing import section (or local import in the function, matching line 1099 style — prefer top-level import for cleanliness).

---

## Risks / cross-bug interactions

- **Bug 1 + Bug 2** both rewrite `compact()` — must be done together as one coherent rewrite. The ack-turn event (bug 2) plugs into the new ack-send path (bug 1).
- **Bug 1 + `_handle_turn_end`:** the auto-compact guard at line 442 already checks `not self._compacting`. Keeping `_compacting=True` across the ack turn means the ack turn's `_handle_turn_end` will NOT re-trigger auto-compact — that's the intended fix. But it also means the ack turn's pending-message flush (line 449) and hibernate (453) still run with `_compacting=True`... need to verify `_handle_turn_end` doesn't misbehave when `_compacting` is True. **Decision:** the ack-turn event must be set in `_handle_turn_end` regardless of `_compacting`; flush/hibernate at end of `_handle_turn_end` are fine (send() queueing is what we want suppressed, and we clear `_compacting` right after awaiting the event).
- **Bug 3 single-flight** touches `_persist`/`_drain_persist` used everywhere — low risk (pure serialization) but must preserve `_drain_persist` semantics for `change_orchestrator_scope`.
- **Bug 4/5** both use `remove_worktree` — fixing the lock (bug 4) automatically protects the spawn-crash cleanup (bug 5). Order: implement lock first.
- **P1-1 (session_id=None)** is NOT in scope (it's P1, not in the 7). Bug 1's rewrite still nulls session_id conceptually — but we should set the new session_id from the ack turn's ResultMessage. Current compact already captures session_id from the COMPACT_PROMPT turn (line 630-631). Keep that; do not regress into P1-1 territory but also don't fix it (out of scope) unless trivial.

## Out of scope (P1/P2/P3 — not touched)
P1-1..7, P2-1..4, P3-1..4. Mentioned only where they interact with a P0 fix.
