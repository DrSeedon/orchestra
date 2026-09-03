# Task #40 — Implementation Plan: 13 P1 fixes

Scope: 13 surgical fixes. **#5, #7 already fixed** (verify-only). **#15, #17 deferred** (orchestrator-approved).
Decision locked: `permission_denials` is informational — does NOT flip `ok`.

Order: #1 (errors) → #2 (thinking) → #3+#4 (cost/ctx cleanup, same block) → #6/#8/#9/#11/#13 (session) → #10/#14 (manager) → #12 (workspace) → #16/#19 (main+tg) → #18 (tm).

---

## GROUP A — backend_claude.py `_convert` (#1, #2, #3, #4)

These all live in `_convert`. Done together — one coherent rewrite of the `ResultMessage` block + two added branches.

### #2 — ThinkingBlock (trivial, additive)
- Import: add `ThinkingBlock` to the `from claude_agent_sdk import (...)` block (line 9-22).
- In the `AssistantMessage` content loop (line 204), add after the TextBlock branch:
```python
elif isinstance(block, ThinkingBlock) and block.thinking:
    events.append(AgentEvent("thinking", block.thinking))
```
- `_handle_event` (session.py:335) must handle `"thinking"`: log it as a dedicated type so the dashboard shows it. Add:
```python
elif event.type == "thinking":
    self._log("thinking", event.content)
```
(No `_turn_logs` append — thinking is not worker output for auto-report.)

### #1 — AssistantMessage.error + ResultMessage error states
- In the `AssistantMessage` branch (line 203), after the content loop, surface model-level error:
```python
err = getattr(msg, "error", None)
if err:
    events.append(AgentEvent("error", f"model error: {err}"))
```
- In the `ResultMessage` branch (line 243), read error fields and put real values in metadata:
```python
is_err = bool(getattr(msg, "is_error", False))
err_list = getattr(msg, "errors", None) or []
denials = getattr(msg, "permission_denials", None) or []
```
- In the `turn_end` metadata dict (line 291-306): replace `"ok": True` with `"ok": not is_err`, add `"is_error": is_err`, `"errors": err_list`. (permission_denials NOT included in ok logic — informational only; we can log count but do not surface as error.)
- `session.py _handle_turn_end` (395): after computing `ok`, if `not ok`, log loudly and DO NOT auto-report as success. Concretely:
```python
ok = meta.get("ok", True)
errors = meta.get("errors") or []
...
if not ok:
    err_txt = "; ".join(errors) if errors else sr
    self._log("error", f"turn FAILED: {err_txt}")
    self._did_report = False  # ensure we don't suppress; but also block auto-report-as-success
```
  - Auto-report gating: `_fire_auto_report` (375) currently fires whenever idle + not reported. We add: do not fire the normal "finished, last output" auto-report when `not ok`; instead the error is already logged and the orchestrator sees it via the error log / TG stream. Simplest: pass `ok` into `_fire_auto_report` and skip the success report when `not ok` (the error log already surfaces the failure). Add guard at top of `_fire_auto_report`: store `self._last_turn_ok` set in `_handle_turn_end`, and `if not self._last_turn_ok: return` after logging.
  - **Edge:** still set status IDLE/WAITING normally (the turn did end) — we just don't lie about success.

### #3 — delete dead `iterations` branch
- In `ResultMessage` usage block (262-289): remove `iters = usage.get("iterations", [])` and `last = iters[-1] if iters else usage`. Read directly from `usage`:
```python
cache_create = usage.get("cache_creation_input_tokens", 0) or 0
cache_read   = usage.get("cache_read_input_tokens", 0) or 0
input_tokens = usage.get("input_tokens", 0) or 0
output_tokens= usage.get("output_tokens", 0) or 0
```
- Cost calc: drop the `if iters:` loop (281-287), keep only the flat `else` formula (288-289).

### #4 — stop computing billing-derived ctx_pct
- Remove `ctx_pct`/`ctx_tokens` computation from billing (268, 273-274). Set `ctx_pct = 0`, `ctx_tokens = 0` in metadata (or omit and let `_handle_turn_end` keep previous `_last_context`). `cache_hit` derived from cache tokens is fine to keep (it's a ratio, not window occupancy) — keep it.
- **`_handle_turn_end` (session.py:415-425):** currently overwrites `_last_context["percentage"]` with the billing `ctx_pct` (which becomes 0). To avoid showing 0% for ~1s: only update `percentage`/`total_tokens` if the incoming value is >0; always keep `cache_*`. So:
```python
ctx_pct = meta.get("context_pct", 0)
ctx_tokens = meta.get("context_tokens", 0)
if ctx_pct:  # only trust non-zero billing estimate (now always 0 → keep prev)
    self._last_context["percentage"] = ctx_pct
    self._last_context["total_tokens"] = ctx_tokens
self._last_context["cache_hit"] = meta.get("cache_hit", 0)
self._last_context["cache_read"] = meta.get("cache_read", 0)
self._last_context["cache_create"] = meta.get("cache_create", 0)
self._last_context["max_tokens"] = meta.get("max_tokens", 200000)
```
- `_refresh_context_from_api` (729) remains the authoritative source (fires at 427). The >30% "corrected" log noise (740) disappears because we no longer write a bad estimate.
- **Auto-compact trigger** (session.py:451 `ctx_pct > 90`): now `ctx_pct` from meta is 0. Switch the check to read from `_last_context` (which holds the last API-refreshed %): `pct = self._last_context.get("percentage", 0); if pct > 90 and ...`. Keeps auto-compact working.

---

## GROUP B — session.py (#6, #8, #9, #11, #13)

### #6 — cost reset on session_id change
- `_handle_turn_end` (402-410). Capture old sid BEFORE overwriting:
```python
sid = meta.get("session_id")
if sid and sid != self.session_id:
    self._last_cost = 0.0
    self._last_cost_cached = 0.0
if sid:
    self.session_id = sid
```
(Place the reset before the `self.session_id = sid` assignment. First-ever turn: `self.session_id` is None → sid != None → reset 0→0, harmless.)

### #8 — inject flags set after successful send
- `send()` (207-235). Move the mutations out of the pre-send block. Plan:
  - Lines 207-217: compute `templates_changed`, build the prefixed `message`, but DO NOT set `self._template_hash`, `self._prompt_injected`, `self.system_prompt` yet. Stash intended values in locals (`pending_th`, `pending_prompt`, `did_inject=True`).
  - After `await backend.send(message)` (235) succeeds, commit:
```python
await backend.send(message)
if did_inject:
    self._template_hash = pending_th
    self._prompt_injected = True
    self.system_prompt = pending_prompt
```
  - The `except` at 230 (backend connect fail) now leaves flags untouched → next send retries injection. ✓
  - **Edge:** the status-log `prompt updated: X → Y` (213) — move it after success too, or keep before (it's just a log; keep before is fine, but cleaner after). Move after.

### #9 — pass stop_reason to on_idle (no live re-read)
- `_fire_auto_report` (375): compute stop_reason from the snapshot at fire time:
```python
last_texts = self._turn_logs[-5:] if self._turn_logs else []
stop_reason = ""
for log in reversed(self._turn_logs):
    if "stop_reason=" in log: stop_reason = log.strip(); break
```
  Wait — `_turn_logs` holds text/tool entries, not the `stop_reason=` status line (that's logged via `_log`, not appended to `_turn_logs`). Check: `_handle_turn_end` logs `turn ended (sr...)` via `self._log` (436), NOT appended to `_turn_logs`. So the manager's loop over `_turn_logs` for `stop_reason=` (manager.py:817-821) **never matches** today → `sr` is always "". So #9's "wrong stop_reason" is really "always empty". Fix: pass the actual `sr` from the turn_end event.
- Plan: thread `stop_reason` through. `_handle_turn_end` already has `sr` (399). Store `self._last_stop_reason = sr` before calling `_fire_auto_report`. In `_fire_auto_report`, pass it:
```python
await self.on_idle(self.name, self.scope, last_texts, self._last_stop_reason)
```
- `manager._on_worker_idle` (805): change signature to `(worker_name, worker_scope, last_texts, stop_reason="")`, drop the live `_turn_logs` loop (817-821), use `sr = f" (stop_reason={stop_reason})" if stop_reason else ""`.
- **Edge:** any other caller of `on_idle`? grep: only `_fire_auto_report`. Safe.

### #11 — _flush_pending requeue on error
- `_flush_pending` except (495-498): requeue msgs at front before setting IDLE:
```python
except Exception as e:
    logger.error(f"[{self.name}] flush pending failed: {e}")
    self._pending_messages[0:0] = msgs
    self.status = AgentStatus.IDLE
    self._persist()
```

### #13 — dedicated DB executor for _log/_persist
- Add module-level lazy executor in session.py:
```python
import concurrent.futures
_DB_EXECUTOR = None
def _db_executor():
    global _DB_EXECUTOR
    if _DB_EXECUTOR is None:
        _DB_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="db")
    return _DB_EXECUTOR
```
- `_log` (831): `run_in_executor(_db_executor(), add_log, ...)`.
- `_persist_loop` (823): `run_in_executor(_db_executor(), save_session, snapshot)`.
- Keeps git ops (`asyncio.to_thread`) on the default pool, DB writes on their own → no contention.
- **Edge:** executor never explicitly shut down — fine for a long-lived server; Python atexit handles it. Don't add shutdown complexity (MVP).

---

## GROUP C — manager.py (#10, #14)

### #10 — preserve waiting state on resume
- `auto_resume_all` (877-887):
  - Capture waiting ids: `was_waiting = {r["id"] for r in c.execute("SELECT id FROM sessions WHERE status='waiting'")}`.
  - Include waiting in resumable filter: `status IN ('running','idle','waiting')`.
  - The blanket `UPDATE ... SET status='idle' WHERE status != 'idle'` (887): keep it (so unloadable rows don't lie as running), BUT after a waiting session loads, restore its waiting status. Simplest: after `_load_from_db` for a row in `was_waiting`, re-derive from bg_jobs:
```python
if row["id"] in was_waiting:
    from app.bg_jobs import bg_manager
    if bg_manager and bg_manager.has_active_jobs(row["id"]):
        session.status = AgentStatus.WAITING
        session._persist()
```
  Place in both orch + worker resume loops (only workers wait realistically, but apply to both for safety). Do NOT inject restart notice for waiting sessions (they're parked, not interrupted) — `was_running` already excludes them.

### #14 — to_thread for git rev-parse at resume
- `_load_from_db` (728-732): the function is `async`, so wrap the blocking call:
```python
actual = await asyncio.to_thread(subprocess.run,
    ["git", "rev-parse", "--abbrev-ref", "HEAD"],
    cwd=wt_path, capture_output=True, text=True)
```

---

## GROUP D — workspace.py (#12)

### #12 — attribute stats to all task refs
- `_parse_merged_commits` (457): replace `.search` with `.finditer`, attribute the same commit dict to each distinct ref:
```python
refs = []
seen = set()
for m in _TASK_REF_RE.finditer(message):
    ref = m.group(3) if m.group(3) else f"{m.group(1)}-{m.group(2)}"
    if ref not in seen:
        seen.add(ref); refs.append(ref)
if not refs:
    continue
# ... compute stat once ...
for ref in refs:
    by_par.setdefault(ref, []).append(commit)
```
- **Edge:** stat is per-commit, computed once, appended to each ref — each ref gets the full commit (not split). This matches `_build_squash_message` listing all refs. Downstream `link_commits_to_task` (main.py:758) links per ref — each task gets the commit. No double-payment: payment logic keys on task, the commit appears once per task. Verify in tm `link_commits_to_task` it's idempotent/additive per task (out of scope to change).

---

## GROUP E — main.py + tg_bridge.py + db.py (#16, #19)

### #16 — to_thread for merge / switch-branch
- main.py:755 `merge_worktree_to_main(...)` → `await asyncio.to_thread(merge_worktree_to_main, worktree_path, scope, target_branch=target)`.
- main.py:797 `switch_worktree_branch(...)` → `await asyncio.to_thread(switch_worktree_branch, worktree_path, new_branch, from_ref=from_ref)`.
- Both already inside `get_session_lock` — serialization preserved, event loop no longer blocked by flock.

### #19 — reuse connection + adaptive backoff in poll loops
- **db.py:** add optional `conn` param to `get_logs`:
```python
def get_logs(session_id, after_id=0, limit=5000, conn=None):
    c = conn or _conn()
    try:
        ... (existing query body) ...
    finally:
        if conn is None:
            c.close()
```
  (Use explicit close instead of `with` so a passed-in conn is not closed.)
- **main.py `stream_session_logs` (483-498):** open one connection at generator start, pass to get_logs, close in finally; adaptive sleep:
```python
async def event_generator():
    from app.db import _conn
    last_id = after_id; initial = True; idle_ticks = 0
    c = _conn()
    try:
        while True:
            if await request.is_disconnected(): return
            if initial and after_id == 0:
                logs = get_logs_before(session_id, before_id=2**31-1, limit=limit); initial=False
            else:
                logs = get_logs(session_id, after_id=last_id, conn=c); initial=False
            for log in logs:
                yield ...; last_id = log["id"]
            idle_ticks = 0 if logs else idle_ticks+1
            await asyncio.sleep(0.5 if idle_ticks < 4 else 3.0)
    finally:
        c.close()
```
  (`get_logs_before` left as-is — fires once on init.)
- **tg_bridge.py `stream_logs` (871-974):** open one conn before the `while True`, pass to both `get_logs` calls, adaptive backoff, close on cancel:
```python
from app.db import _conn
c = _conn()
logs = get_logs(session_id, after_id=0, conn=c)
last_id = logs[-1]["id"] if logs else 0
idle_ticks = 0
try:
    while True:
        try:
            logs = get_logs(session_id, after_id=last_id, conn=c)
            ... existing processing ...
            idle_ticks = 0 if logs else idle_ticks+1
        except Exception as e:
            logger.error(...); idle_ticks = 0
        await asyncio.sleep(2 if idle_ticks < 3 else 5)
finally:
    c.close()
```
  - **Edge:** a long-lived SQLite connection in WAL mode is fine for reads; it sees committed writes from the write executor (WAL readers always see latest committed). No staleness.
  - **Edge:** must close on task cancel (topic deleted / shutdown) → try/finally.

---

## GROUP F — tm.py (#18)

### #18 — single DB path
- Delete `app/tm.py:16` `DB_PATH = ...` and `:22-2x` `def _conn()`.
- Add `from app.db import _conn` to tm.py imports.
- All existing `with _conn() as conn:` callers (324, 677, 690, 702, 719, 729, 736, 755, ...) work unchanged — same signature, same `Row` factory.
- **Verify:** tm.py doesn't rely on any PRAGMA difference. db.py `_conn` sets WAL + busy_timeout + foreign_keys=ON. tm.py's old `_conn` — check it set the same (it connects to the same file, schema shared). FK=ON is stricter; verify tm writes don't violate FKs (tasks/payments tables). Will check during impl.

---

## What NOT to touch
- #5, #7 (already fixed)
- #15, #17 (deferred — separate tasks)
- The flat `merge_worktree_to_main` body (don't refactor — only wrap the call site)
- `_extract_tool_result` JSON unwrap, dead-code deletions from arch review (P2/P3, out of P1 scope)
- model_usage / betas / fallback_model (P2, out of scope)
- Any prompt files, frontend, CSS

## Test strategy
- `tests/test_backend_claude.py`: add cases — ResultMessage with `is_error=True` → `ok=False`, `errors` surfaced; ThinkingBlock → "thinking" event; usage without iterations → cost from flat path; ctx_pct no longer billing-derived.
- `tests/test_session.py`: #6 cost reset on session_id change; #8 inject flags not set when send raises; #11 requeue on flush error; #9 stop_reason passed to on_idle.
- `tests/test_manager.py`: #10 waiting restored; #14 (smoke — resume doesn't block).
- `tests/test_workspace.py`: #12 multi-ref squash attributes to all refs.
- Run: `UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest -x -q`.
- Codex review on the diff (mode="review") after impl.

## Migration / compatibility
- No DB schema changes. No new tables (defer #17 means no inbox).
- `on_idle` signature change (#9) is internal — only caller is `_fire_auto_report`; add default `stop_reason=""` for safety.
- `get_logs` new param is optional/backward-compatible.
- AgentSession gets new fields: `_last_turn_ok: bool = True`, `_last_stop_reason: str = ""` (repr=False).
