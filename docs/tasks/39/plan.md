# Task #39 — Implementation Plan: 7 P0 bug fixes (v2 — post-Codex)

Based on `research.md`. **Revised after Codex review** (`docs/tasks/39/findings.md`) — 5 findings incorporated, see "Codex revisions" markers.

Order chosen to minimize cross-bug churn: small surgical fixes first (6, 7, 5, 4), then the persist refactor (3), then the compact rewrite (1+2) which depends on all the rest being stable.

Worktree: `task-39/fix-p0`. Files: `backend_claude.py`, `main.py`, `manager.py`, `workspace.py`, `session.py`.

---

## Fix 6 — zombie CLI on connect timeout (backend_claude.py) — **Codex #5 expanded**

**Location:** `connect()` lines 128-134 AND `reconnect()` lines 181-185.

**Codex #5:** `reconnect()` has the SAME leak (used by heartbeat + listener recovery — not theoretical). And `except Exception` does NOT catch `asyncio.CancelledError` → caller cancellation during connect skips cleanup. Use `BaseException`, disconnect, re-raise.

**Shared cleanup helper** (DRY, both paths use it):
```python
async def _cleanup_failed_client(self) -> None:
    if self._client:
        try:
            await self._client.disconnect()
        except BaseException:
            pass
        self._client = None
```

**connect():**
```python
async def connect(self) -> None:
    self._client = self._make_client()
    try:
        await asyncio.wait_for(self._client.connect(), timeout=60)
    except BaseException as e:
        logger.error(f"ClaudeBackend connect failed: {e}")
        await self._cleanup_failed_client()
        raise
```

**reconnect():**
```python
async def reconnect(self) -> None:
    await self.disconnect()
    await asyncio.sleep(2)
    self._client = self._make_client()
    try:
        await asyncio.wait_for(self._client.connect(), timeout=60)
    except BaseException as e:
        logger.error(f"ClaudeBackend reconnect failed: {e}")
        await self._cleanup_failed_client()
        raise
```

**Invariant:** after a failed `connect()`/`reconnect()` (including timeout AND cancellation), `self._client is None` and no subprocess leaks.
**Note:** catching `BaseException` then re-raising preserves `CancelledError` propagation (we re-raise) — cooperative cancellation still works, we just clean up first.
**Test:** unit — mock `_make_client` to return a client whose `.connect()` raises and `.disconnect()` records a call; assert `disconnect` called and `_client is None` after `connect()` raises. Repeat for `reconnect()`. Add a CancelledError case.

---

## Fix 7 — restart_cli → 500 (main.py)

**Location:** lines 551-561.

**Change:**
- Add top-level import: `from app.session import AgentStatus` (near existing imports).
- Line 558: `await session._disconnect_client()` → `await session._disconnect_backend()`
- Line 559: `session.status = session.status.__class__("idle")` → `session.status = AgentStatus.IDLE`

**Invariant:** POST `/api/sessions/{name}/restart-cli` returns `{"ok": True}`, status becomes IDLE, backend disconnected.
**Test:** smoke — call endpoint on a loaded session, assert 200 + status idle. (Manual; no SDK mock needed.)

---

## Fix 4 — merge vs remove lock (workspace.py)

**Location:** `remove_worktree()` lines 573-595.

**Change:** acquire `fcntl.flock` on `repo/.git/orchestra-merge.lock` (LOCK_EX) around the `git worktree remove`. Use `_resolve_repo(worktree_path, repo_path)` for the lock path (same `.git` common dir as merge/switch use).

```python
def remove_worktree(repo_path: str, worktree_path: str) -> None:
    wt = Path(worktree_path)
    if not wt.exists():
        return
    repo = _resolve_repo(str(wt), repo_path)
    lock_path = repo / ".git" / "orchestra-merge.lock"
    cwd = repo_path
    git_file = wt / ".git"
    if git_file.exists() and git_file.is_file():
        ... # existing cwd-resolution block unchanged
    with open(lock_path, "w") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        try:
            result = subprocess.run(
                ["git", "worktree", "remove", str(wt), "--force"],
                cwd=cwd, capture_output=True, text=True,
            )
            if result.returncode != 0:
                logger.warning(f"worktree remove failed: {result.stderr}")
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)
```

**Invariant:** `remove_worktree` and `merge_worktree_to_main` are mutually exclusive on the same repo.
**Edge case:** `if not wt.exists(): return` stays BEFORE lock acquisition.
**Edge case:** `_resolve_repo` may fail if wt's `.git` is already gone — but we returned early if `wt` doesn't exist; if wt exists but git metadata is broken, `_resolve_repo` falls back to `repo_path` (line 122). Lock path resolves either way.
**Test:** integration is heavy (real git). Minimal: assert the lock file is opened/flocked (mock `fcntl.flock`, assert called with LOCK_EX before subprocess.run). Lower priority — covered by code review.

---

## Fix 5 — orphaned worktree on spawn crash (manager.py + workspace.py) — **Codex #4 expanded**

**Two leak windows:**
- **(A)** `create_worktree()` succeeds (`git worktree add` at workspace.py:98), then `shutil.copy2` of PROJECT_FILES (101-106) raises → worktree exists on disk+git, but `Worktree` never returned, so `session.worktree_path` stays None. The manager except block (which checks `session.worktree_path`) won't clean it.
- **(B)** `create_worktree()` returns OK, `session.worktree_path` set, then `_inject_skills`/`_safe_format_prompt`/`session.start()` (manager 512-524) raises.

**Fix A — rollback inside `create_worktree` (workspace.py):** wrap the post-`git worktree add` steps so any failure removes the just-created worktree before re-raising. Self-cleaning at the source = "fail loud + clean" in one place.
```python
    if result.returncode != 0:
        raise RuntimeError(f"git worktree add failed: {result.stderr.strip()}")
    try:
        for fname in PROJECT_FILES:
            src = repo / fname
            if not src.exists():
                src = repo.parent / fname
            if src.exists():
                shutil.copy2(str(src), str(wt_path / fname))
    except Exception:
        # roll back the worktree we just created
        subprocess.run(["git", "worktree", "remove", str(wt_path), "--force"],
                       cwd=str(repo), capture_output=True, text=True)
        raise
    return Worktree(path=str(wt_path), branch=branch)
```
(Rollback uses a direct `git worktree remove` — NOT `remove_worktree()` — to avoid re-entering the merge lock from inside create, and because the repo cwd is already known here. Acceptable: this is the create-failure path, merge can't be touching a worktree that was just being born.)

**Fix B — manager except block (manager.py:527-529):**
```python
        except Exception:
            if session.worktree_path:
                try:
                    await asyncio.to_thread(remove_worktree, repo_path, session.worktree_path)
                except Exception:
                    pass
            delete_session(session.id)
            raise
```

**Invariant:** no worktree leaks on disk/in git regardless of WHERE `create_session` fails.
**Note:** `remove_worktree` already imported in manager.py (line 560). `repo_path` is the function param. With Fix 4, the manager-path cleanup takes the merge lock (single lock, no deadlock).
**Test:**
- (B) unit — mock `session.start` to raise, assert `remove_worktree` called + `delete_session` called.
- (A) unit — monkeypatch `shutil.copy2` to raise inside `create_worktree`, assert `git worktree remove` invoked and exception propagates. (May be heavy with real git — minimal version: assert the rollback subprocess call happens via mock.)

---

## Fix 3 — persist race: single-flight (session.py)

**Location:** `_persist()` line 765, `_drain_persist()` line 770, field `_persist_futs` line 115.

**Design:** coalesce. One persist runs at a time. If a persist is requested while one is in-flight, mark dirty; when the in-flight finishes, if dirty, run once more with the LATEST snapshot. Last snapshot wins = correct (most recent state).

**Change fields (line 115):**
```python
    _persist_task: Optional[asyncio.Task] = field(default=None, repr=False)
    _persist_dirty: bool = field(default=False, repr=False)
```
(remove `_persist_futs`)

**Change `_persist` (765) — Codex #3: `get_running_loop` + done-callback:**
```python
def _persist(self) -> None:
    self._persist_dirty = True
    if self._persist_task and not self._persist_task.done():
        return
    self._persist_task = asyncio.get_running_loop().create_task(self._persist_loop())
    self._persist_task.add_done_callback(self._on_persist_done)

def _on_persist_done(self, task: asyncio.Task) -> None:
    try:
        task.result()
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error(f"[{self.name}] persist task crashed: {e}")
```
- `get_running_loop()` → explicit `RuntimeError` if ever called off-loop (fail loud) instead of silently scheduling on a wrong loop.
- done-callback retrieves the task exception so a fire-and-forget persist crash gets logged, not swallowed (`_drain_persist` only helps drained paths).

**`_persist_loop` (with internal guard so one DB error doesn't kill future writes):**
```python
async def _persist_loop(self) -> None:
    while self._persist_dirty:
        self._persist_dirty = False
        snapshot = self._to_db_dict()
        try:
            await asyncio.get_running_loop().run_in_executor(None, save_session, snapshot)
        except Exception as e:
            logger.error(f"[{self.name}] persist failed: {e}")
```

**Change `_drain_persist` (770):**
```python
async def _drain_persist(self) -> None:
    if self._persist_task and not self._persist_task.done():
        await asyncio.gather(self._persist_task, return_exceptions=True)
```
**Note:** `_persist_loop` catches its own DB errors, so by the time `_drain_persist` awaits the task it won't raise — `gather(return_exceptions=True)` is belt-and-suspenders.

**Invariants:**
- At most one `save_session` executor call in flight per session.
- The final state always reaches the DB (dirty flag re-triggers).
- Snapshot taken inside the loop (fresh) — captures latest mutations, not a stale one.

**Edge cases:**
- `_persist` called rapidly N times → 1 task, ≤2 writes (current + 1 coalesced). No unbounded growth.
- `_persist` called from sync context (it's a sync method) — `asyncio.create_task` needs a running loop. All current callers run inside the event loop (verified: turn_end, send, interrupt, etc. all async-context). `create_task` requires running loop — same constraint as the old `run_in_executor`. OK.
- Exception inside `save_session` → caught by `gather(..., return_exceptions=True)` in drain; in the loop it would propagate and kill the task. **Guard:** wrap the executor call in try/except inside `_persist_loop` so one failed write doesn't stop future persists. Log on failure.

**Refined `_persist_loop`:**
```python
async def _persist_loop(self) -> None:
    while self._persist_dirty:
        self._persist_dirty = False
        snapshot = self._to_db_dict()
        try:
            await asyncio.get_event_loop().run_in_executor(None, save_session, snapshot)
        except Exception as e:
            logger.error(f"[{self.name}] persist failed: {e}")
```

**Codex #3 — existing tests break:** `tests/test_manager.py:618,623` inspect `orch._persist_futs` directly (`test_db_cwd_is_new_after_inflight_persist`). Must rewrite those assertions:
- line 618 `assert len(orch._persist_futs) >= 1` → `assert orch._persist_task is not None` (after the 3 `_persist()` calls).
- line 623 `assert all(f.done() for f in orch._persist_futs)` → `assert orch._persist_task.done() and not orch._persist_dirty` (after `change_orchestrator_scope` which drains).
- `test_drains_persist_before_db_write` (591) mocks `_drain_persist` — unaffected (signature unchanged).
- The test's semantics (drain-before-write, final cwd is new) are preserved.

**Test (TDD — high value, data layer / concurrency):**
- `test_persist_coalesces`: patch `save_session` with a slow recorder; call `_persist()` 5× rapidly; await `_drain_persist()`; assert `save_session` called ≤2 times and the LAST call's snapshot has the latest field values.
- `test_persist_last_wins`: set status=running, `_persist()`; immediately set status=idle, `_persist()`; drain; assert final saved snapshot status=idle.
- `test_persist_survives_db_error`: make first `save_session` raise, second succeed; assert the loop logged + still wrote the second (one error doesn't stop future persists).

---

## Fix 1 + 2 — compact() rewrite (session.py) — **Codex #1 + #2 corrected**

**Combined** — done together. `compact()` lines 591-661.

### New fields
```python
    _compact_ack_event: Optional[asyncio.Event] = field(default=None, repr=False)
    _compact_ack_gen: int = field(default=-1, repr=False)   # Codex #2: bind event to a specific turn
```

### Re-entrancy guard + atomic `_compacting` (Fix 1a)
Top of `compact()` — guard then set with NO await between (atomic in single-threaded asyncio):
```python
async def compact(self) -> dict:
    if self._compacting:
        return {"ok": False, "error": "compact already in progress"}
    self._compacting = True
    before_pct = self._last_context.get("percentage", 0)
    self._log("status", f"compact started (context {before_pct}%)")
```

### Codex #2 — cancel any scheduled flush BEFORE compact, bind ack event to turn gen
`_flush_pending()` bypasses `send()` and can start a non-ack turn that falsely sets the ack event. Two defenses:

**(a) Drain pending-flush at compact start.** `_flush_pending` is scheduled via `asyncio.create_task` in `_handle_turn_end`/`_codex_turn_loop`/heartbeat. Add a guard at the TOP of `_flush_pending`:
```python
async def _flush_pending(self) -> None:
    await asyncio.sleep(0.3)
    if self._compacting:          # Codex #2: don't start a turn during compact
        return                    # messages stay queued; compact's finally re-flushes
    if not self._pending_messages:
        return
    ...
```
Since `_compacting` is set synchronously at compact entry, any flush task that wakes from its 0.3s sleep after that sees the flag and bails. A flush already past the sleep + inside the lifecycle lock is serialized by `_lifecycle_lock` (compact's ack send also takes it) — so it finishes first, its turn_end fires while `_compact_ack_gen` is still -1 (event not yet armed) → no false set.

**(b) Bind ack event to the ack turn's generation.** In `_handle_turn_end`, only set the event if THIS turn is the ack turn:
```python
    # near end of _handle_turn_end, after status is set
    if self._compact_ack_event is not None and self._turn_gen == self._compact_ack_gen:
        self._compact_ack_event.set()
```
`_compact_ack_gen` is captured right after `_bump_turn_gen()` in the ack-send block (under the lock), so it names exactly the ack turn. A stray flush turn has a different `_turn_gen` → won't set the event.

**Also suppress auto-report/flush for the ack turn:** the ack turn sets `_did_report=False` and isn't a real worker reply — `_fire_auto_report` (447) would send a bogus report to the parent. Guard: in `_fire_auto_report`, `if self._compacting: return` (already returns early if `_pending_messages`; add `_compacting`). And `_handle_turn_end`'s end-of-function flush (449) is gated by `_flush_pending`'s own `_compacting` guard from (a), so it self-defers.

### Codex #1 — fresh ack backend WITHOUT nulling persisted session_id (Fix 1b)
The ack turn must start a fresh SDK session (no resume token) so compaction actually drops context. But we must NOT write `session_id=NULL` to the DB before the new token lands (P1-1 crash window). 

**Approach:** add a `force_fresh` path to backend construction; keep `self.session_id` pointing at the old token until the ack `turn_end` delivers the new one (which `_handle_turn_end` writes at line 397-398 as usual).

`_make_backend` gets an optional param:
```python
def _make_backend(self, force_fresh: bool = False):
    resume = None if force_fresh else self.session_id
    ... ClaudeBackend(resume_session_id=resume, ...)   # and CodexBackend(resume_thread_id=resume, ...)
```
`_ensure_backend` gets a matching param:
```python
async def _ensure_backend(self, force_fresh: bool = False):
    if self._backend is not None:
        return self._backend
    self._backend = self._make_backend(force_fresh=force_fresh)
    ...
```

In compact, after the COMPACT_PROMPT turn + `disconnect()` + `_backend=None` (existing 638-639): do **NOT** set `self.session_id = None`. Remove dead `old_session_id` (647) and the `self.session_id = None` (648). The ack-send block calls `_ensure_backend(force_fresh=True)` → fresh CLI session, old token still in memory+DB. When ack `turn_end` arrives, `_handle_turn_end` overwrites `self.session_id` with the new token and persists.

**Crash safety:** if the process dies mid-compact (before ack turn_end), DB still has the OLD token → restart resumes with old context (no loss) instead of NULL. Strictly better. **P1-1 fixed as a clean side-effect** (not by hack — by the force-fresh design Codex recommended).

**Note on COMPACT_PROMPT turn session_id (630-631):** that turn runs on the EXISTING backend (pre-disconnect) and may update `self.session_id` to the summary turn's id. That's fine — it's still a valid resume token. The ack turn then force-fresh ignores it for resume but `_handle_turn_end` replaces it with the truly-fresh ack session id. No NULL window anywhere.

### Ack-send block (replaces 641-661)
```python
    summary = "".join(summary_parts).strip()
    if not summary:
        self._log("error", "compact returned empty summary")
        self._compacting = False
        return {"ok": False, "error": "empty summary", "before_pct": before_pct}

    preamble = PREAMBLE.format(summary=summary)
    self._compact_ack_event = asyncio.Event()
    ack_event = self._compact_ack_event
    try:
        async with self._lifecycle_lock:
            self._did_report = False
            self._bump_turn_gen()
            self._compact_ack_gen = self._turn_gen      # Codex #2: name THIS turn
            self._turn_logs = []
            self._turn_start = asyncio.get_event_loop().time()
            self._last_msg_time = self._turn_start
            self.status = AgentStatus.RUNNING
            self._persist()
            backend = await self._ensure_backend(force_fresh=True)   # Codex #1: fresh session
            await backend.send(preamble + "Acknowledge briefly.")

        try:
            await asyncio.wait_for(ack_event.wait(), timeout=60)
        except asyncio.TimeoutError:
            self._log("error", "compact ack turn did not complete (60s)")
            return {"ok": False, "error": "ack turn did not complete", "before_pct": before_pct}
    finally:
        self._compact_ack_event = None
        self._compact_ack_gen = -1
        self._compacting = False
        if self._pending_messages:
            asyncio.create_task(self._flush_pending())

    after_pct = self._last_context.get("percentage", 0)
    self._log("status", f"compact done: {before_pct}% → {after_pct}%")
    return {"ok": True, "before_pct": before_pct, "after_pct": after_pct, "summary_chars": len(summary), "summary": summary}
```

**Invariants:**
- Only one `compact()` runs at a time (guard + synchronous flag set).
- `_compacting` True from entry until ack completes/times out.
- ack send bypasses `send()` queue (direct `backend.send`); ack runs on a FRESH session (force_fresh).
- Persisted `session_id` is NEVER NULL — old token held until ack turn_end writes the new one.
- ack event set ONLY by the matching turn gen → no false positive from a flush/heartbeat turn.
- timeout → `ok:False`, not fabricated success.
- `_compact_ack_event`/`_compact_ack_gen` reset in finally.

**Edge cases:**
- COMPACT_PROMPT turn fails / empty summary: clears `_compacting`, returns ok:False (existing). Keep.
- ack turn errors mid-way: `_handle_turn_end` fires on turn_end (matching gen) → event set → returns ok:True with after_pct. Acceptable.
- a `_flush_pending` already scheduled before compact: bails on `_compacting` guard (a) OR finishes first under the lock with a non-matching gen (b). Either way no false ack.
- heartbeat reconnect mid-compact sends `[system] Continue` directly: it runs only if `status==RUNNING` and listener dead; during compact the ack turn IS running. If it fires, its turn isn't the ack gen → won't set event. Low risk, covered by (b).

**Test (TDD):**
- `test_compact_reentry_guard`: `_compacting=True` → `compact()` returns the in-progress error without touching backend.
- `test_compact_ack_timeout`: mock backend so ack turn never fires turn_end (monkeypatch timeout small) → `ok:False` "ack turn did not complete".
- `test_compact_ack_bound_to_gen`: arm event with gen=5, fire `_handle_turn_end` with `_turn_gen=4` → event NOT set; with gen=5 → set. (Directly tests Codex #2 fix.)
- `test_compact_keeps_session_id`: assert `self.session_id` is non-None throughout compact until ack turn_end overwrites it (no NULL window).
- `test_flush_pending_defers_during_compact`: set `_compacting=True`, queue a message, run `_flush_pending` → returns without sending.

---

## Implementation order
1. Fix 6 (backend_claude) — isolated.
2. Fix 7 (main) — isolated.
3. Fix 4 (workspace remove_worktree lock) — isolated.
4. Fix 5 (manager except) — depends on Fix 4 being in (uses remove_worktree).
5. Fix 3 (persist single-flight) — touches session.py, isolated from compact.
6. Fix 1+2 (compact rewrite) — last, depends on stable `_handle_turn_end` and `_persist`.

## Test strategy summary
- TDD where it pays: Fix 3 (concurrency), Fix 1+2 (state machine guard/timeout), Fix 6 (cleanup contract).
- Code-review / manual: Fix 4 (git lock), Fix 5 (cleanup wiring), Fix 7 (endpoint smoke).
- Tests in `tests/` (check existing test layout before writing).
- Full suite run requires global test lock (acquire before, release after).

## Scope check
- 7 fixes, ~5 files. No new features. No refactor beyond what each fix requires.
- `_persist` refactor touches many call sites — pure internal serialization, signatures unchanged.
- **P1-1 (session_id NULL) now fixed as a clean side-effect** of the Codex #1 force-fresh design — NOT by hack, and without expanding scope (it lives inside the compact block we're already rewriting). Removing the NULL write is strictly safer.
- `_make_backend`/`_ensure_backend` gain an optional `force_fresh=False` param — additive, all existing callers unchanged.
- Dead `old_session_id` removed (P3-3) — it's in the rewritten compact block.

## Codex review resolution (docs/tasks/39/findings.md)
1. **#1 session_id** — DONE: force-fresh ack backend, never persist NULL. Better than original "accept P1-1".
2. **#2 ack false positive** — DONE: bind event to `_compact_ack_gen` + `_flush_pending` defers on `_compacting` + suppress auto-report during compact.
3. **#3 persist** — DONE: `get_running_loop().create_task`, done-callback logging, in-loop try/except, test_manager.py:618/623 rewritten.
4. **#4 create_worktree leak** — DONE: rollback inside `create_worktree` (covers post-`git worktree add` copy failure) + manager except block.
5. **#5 reconnect leak / CancelledError** — DONE: shared `_cleanup_failed_client`, `BaseException` in both connect+reconnect.
