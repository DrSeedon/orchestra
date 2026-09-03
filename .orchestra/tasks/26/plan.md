# #26 — Cron agents — PLAN

## Decision recap (from orchestrator)
- Add `croniter` to deps.
- **DROP the CHECK constraint** on `bg_jobs.type` (rely on `_validate_config`).
- **MAX_TIMEOUT EXEMPT for cron**: `timeout_seconds=0` = no expiry (run forever until cancelled). `>0` = respected.
- Target session missing at fire time → skip-and-log, keep cron alive.
- Missed fires after downtime → skip, compute next. No backfill. Document.
- Store `cron_expr`, `last_fired_at`, `fire_count` in `config` JSON (update in place).

## Cron model
- A `cron` job is **recurring**: stays `status='active'` across firings. It only leaves `active` on cancel / expire (if timeout set) / fatal validation error.
- Firing must NOT use the one-shot `bg_claim_trigger` → `triggered` path (that's terminal). New non-terminal fire path.
- `config = {"cron_expr": "...", "no_expiry": bool, "last_fired_at": "<iso>", "fire_count": N}`.
- **`no_expiry`** stored in config (Codex #26-3): when `timeout_seconds<=0` for cron, set `config["no_expiry"]=True`. On restart, `_run_cron` reads `no_expiry` from config → `timeout=None` (truly infinite), instead of relying on a far-future `expires_at` sentinel. We still set `expires_at` to far-future so `bg_expire_overdue` never expires it, but the runner's infinite-ness comes from `no_expiry`, not from sentinel arithmetic.

## Changes

### 1. `pyproject.toml` — dependency
Add `"croniter>=2.0,<7.0"` to `[project].dependencies`. Run `uv sync`.

### 2. `app/db.py` — drop CHECK on bg_jobs.type
- **Fresh DBs** (`init_db` CREATE TABLE bg_jobs): remove `CHECK (type IN ('timer','file','command','ssh','run'))` → just `type TEXT NOT NULL`. Keep the `status` CHECK as-is (cron uses only existing statuses: active/triggering? — see below).
- **Existing DBs** (`_migrate`): SQLite can't drop a CHECK via ALTER. Rebuild `bg_jobs` if the old CHECK is present.
  - **Codex #26-1 (ACK) — atomicity:** `c.executescript()` issues an **implicit COMMIT before** running the script, so a multi-statement rebuild via executescript is NOT atomic — a failure mid-script can leave `bg_jobs_old` / a partial new table / missing indexes. Confirmed: `with _conn() as c` commits on exit, and Python sqlite3 `executescript` force-commits first. **Fix:** do the rebuild as **discrete `c.execute()` calls** within the single `_migrate` `with _conn()` transaction (no executescript), so all statements share one transaction and roll back together on error.
  - **Codex #26-2 (ACK) — no `SELECT *`:** copy with an **explicit column list** matching the full schema, in the exact column order, so a future column addition can't silently misalign:
  ```python
  ddl = c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='bg_jobs'").fetchone()
  if ddl and "type IN ('timer'" in ddl[0]:
      _BG_COLS = ("id","type","config","message","target_session_id","target_name",
                  "target_scope","created_by_name","status","error","expires_at",
                  "trigger_at","created_at","triggered_at","last_output")
      cols = ", ".join(_BG_COLS)
      c.execute("ALTER TABLE bg_jobs RENAME TO bg_jobs_old")
      c.execute("""
          CREATE TABLE bg_jobs (
              id TEXT PRIMARY KEY,
              type TEXT NOT NULL,
              config TEXT NOT NULL DEFAULT '{}',
              message TEXT NOT NULL DEFAULT '',
              target_session_id TEXT NOT NULL,
              target_name TEXT NOT NULL,
              target_scope TEXT NOT NULL,
              created_by_name TEXT NOT NULL DEFAULT '',
              status TEXT NOT NULL DEFAULT 'active'
                  CHECK (status IN ('active','triggering','triggered','expired','cancelled','failed')),
              error TEXT,
              expires_at TEXT NOT NULL,
              trigger_at TEXT,
              created_at TEXT NOT NULL,
              triggered_at TEXT,
              last_output TEXT NOT NULL DEFAULT ''
          )
      """)
      c.execute(f"INSERT INTO bg_jobs ({cols}) SELECT {cols} FROM bg_jobs_old")
      c.execute("DROP TABLE bg_jobs_old")
      c.execute("CREATE INDEX IF NOT EXISTS idx_bg_jobs_session ON bg_jobs(target_session_id, status)")
      c.execute("CREATE INDEX IF NOT EXISTS idx_bg_jobs_scope ON bg_jobs(target_scope, status)")
  ```
  The new DDL keeps the **status** CHECK (unchanged) and drops only the **type** CHECK. Must exactly mirror the fresh-DB `init_db` DDL (minus the type CHECK) — keep both in sync.
- **status CHECK**: cron stays `active` and uses the existing terminal statuses on cancel/expire/fail. No new status value needed → status CHECK unchanged. (We deliberately avoid a `triggered` terminal status for cron; it never goes there.)
- **Test for atomicity (Codex #26-1):** a test that monkeypatches to raise an exception between RENAME and DROP, then asserts `bg_jobs_old` was rolled back / original data intact.

### 3. `app/bg_jobs.py` — validation
- Add `import` for croniter at top.
- `_validate_config`, new branch:
  ```python
  elif job_type == "cron":
      expr = config.get("cron_expr", "")
      if not expr:
          return "cron_expr is required"
      if not croniter.is_valid(expr):
          return f"invalid cron expression: {expr!r}"
  ```

### 4. `app/bg_jobs.py` — timeout exemption
- In `create()`: currently `timeout_seconds = max(1, min(timeout_seconds, MAX_TIMEOUT))`. For cron, `timeout_seconds<=0` must mean "no expiry".
  ```python
  no_expiry = (job_type == "cron" and timeout_seconds <= 0)
  if no_expiry:
      config = {**config, "no_expiry": True}            # persisted in config JSON
      expires_at = (now + timedelta(days=36500)).isoformat()  # far-future, never overdue
  else:
      timeout_seconds = max(1, min(timeout_seconds, MAX_TIMEOUT))
      expires_at = (now + timedelta(seconds=timeout_seconds)).isoformat()
  ```
  `no_expiry` lives in **config** (durable) — NOT inferred from the far-future `expires_at`. The far-future `expires_at` only serves to make `bg_expire_overdue` (`expires_at < now`) never match. The runner's infinite-ness comes from reading `config["no_expiry"]`.
- `_start_task` cron branch: `timeout = None if config.get("no_expiry") else <remaining-seconds>`. The `_run_cron` loop treats `None` as infinite.
- **Restart (Codex #26-3):** `restore_from_db` computes `remaining = expires_at - now`. For a no_expiry cron that's ~100 years → harmless, BUT `_start_task` must still pass `timeout=None` for cron when `config["no_expiry"]` is set (re-read from config), so the runner is genuinely infinite rather than bounded by the sentinel. Add cron handling in `_start_task` that checks `config.get("no_expiry")`.

### 5. `app/bg_jobs.py` — dispatch + runner
- `_start_task`, add:
  ```python
  elif job_type == "cron":
      coro = self._run_cron(job_id, config["cron_expr"], message,
                            target_name, target_scope, timeout)  # timeout may be None
  ```
- New runner (Codex #26-4 fix: if a finite timeout would expire before the next fire, **sleep until the deadline** then expire — don't expire immediately):
  ```python
  async def _run_cron(self, job_id, cron_expr, message, target_name, target_scope, timeout):
      from croniter import croniter
      deadline = (time.time() + timeout) if timeout else None
      try:
          while True:
              now = datetime.now(timezone.utc)
              nxt = croniter(cron_expr, now).get_next(datetime)  # aware UTC
              sleep_s = max(0, (nxt - now).total_seconds())
              if deadline is not None and time.time() + sleep_s > deadline:
                  # next fire is past expiry: wait out the remaining time, then expire
                  await asyncio.sleep(max(0, deadline - time.time()))
                  break
              await asyncio.sleep(sleep_s)
              await self._fire_cron(job_id, message, target_name, target_scope)
          self._expire(job_id)
      except asyncio.CancelledError:
          pass
      except Exception as e:
          bg_fail_job(job_id, str(e)[:500])
  ```
- New non-terminal fire path (Codex #26-5 fix: **atomic DB-guard** that the job is still `active` and not expired BEFORE sending, to avoid a stray fire of a job cancelled/expired between wake-up and send):
  ```python
  async def _fire_cron(self, job_id, message, target_name, target_scope):
      if not bg_cron_should_fire(job_id):   # atomic: status='active' AND expires_at>=now
          return
      try:
          session = await self._session_manager.ensure_loaded(target_name, target_scope) \
                    or await self._session_manager.ensure_loaded_any(target_name)
          if not session:
              logger.warning(f"cron {job_id}: target {target_name} not found, skipping fire")
              return  # skip-and-log, keep schedule alive
          await session.send(f"[Cron job fired] {message}")
          bg_cron_record_fire(job_id)  # updates config (last_fired_at, fire_count) WHERE status='active'
          logger.info(f"cron {job_id}: fired → {target_name}")
      except Exception as e:
          logger.error(f"cron {job_id}: fire failed (continuing schedule): {e}")
  ```
  Note: `cancel()` cancels the asyncio task (`_run_cron`), which raises `CancelledError` and stops the loop — Codex #26-(cancel) verified: `bg_manager.cancel` and `cancel_by_session` already `task.cancel()` any task in `self._tasks`, and the cron task is registered there by `_start_task`. So cancellation stops the schedule. The `bg_cron_should_fire` guard covers the narrow window where cancel lands mid-sleep just before a fire.

### 6. `app/db.py` — `import json`, should-fire guard, record fire
- **Codex #26-6 (ACK):** `db.py` does NOT currently import `json` (verified — imports are `os, sqlite3, datetime, Path`). **Add `import json`** at the top, else the first cron fire crashes.
- **`bg_cron_should_fire`** (Codex #26-5) — atomic check just before send:
  ```python
  def bg_cron_should_fire(job_id: str) -> bool:
      now = datetime.now(timezone.utc).isoformat()
      with _conn() as c:
          row = c.execute(
              "SELECT 1 FROM bg_jobs WHERE id=? AND status='active' AND expires_at >= ?",
              (job_id, now),
          ).fetchone()
          return row is not None
  ```
- **`bg_cron_record_fire`** (Codex #26-7 — harden against lost-update with `BEGIN IMMEDIATE`, re-read inside the txn, only write if still active):
  ```python
  def bg_cron_record_fire(job_id: str) -> None:
      with _conn() as c:
          c.execute("BEGIN IMMEDIATE")
          row = c.execute("SELECT config, status FROM bg_jobs WHERE id=?", (job_id,)).fetchone()
          if not row or row["status"] != "active":
              c.execute("ROLLBACK")
              return
          try:
              cfg = json.loads(row["config"])
          except (json.JSONDecodeError, TypeError):
              cfg = {}
          now_iso = datetime.now(timezone.utc).isoformat()
          cfg["last_fired_at"] = now_iso
          cfg["fire_count"] = cfg.get("fire_count", 0) + 1
          c.execute(
              "UPDATE bg_jobs SET config=?, last_output=? WHERE id=? AND status='active'",
              (json.dumps(cfg), f"fired #{cfg['fire_count']} at {now_iso}", job_id),
          )
          c.execute("COMMIT")
  ```
  In a single-process asyncio server with one `_run_cron` task per job (enforced by `self._tasks`), concurrent writes can't happen — but `BEGIN IMMEDIATE` + re-read makes the helper correct regardless, cheaply.

### 7. `restore_from_db` survival
- Cron jobs are `active` → already restored by the existing loop (`app/bg_jobs.py:215-232`). `_run_cron` recomputes next fire from `cron_expr` in config → forward-only, no backfill. 
- **Fix needed**: the remaining-time calc `remaining = expires_at - now` is passed as `timeout` to `_start_task`. For no-expiry cron (far-future expires_at), remaining is huge → fine (treated as effectively infinite). For finite-timeout cron, remaining is correct. Ensure `_start_task` cron branch handles a large/という finite remaining as the deadline. Acceptable as-is.

### 8. `app/mcp_stdio.py` — bg_create
- Add `cron_expr: str = ""` param.
- Branch: `elif type == "cron": config = {"cron_expr": cron_expr}`.
- Update docstring: add cron type, note `timeout_seconds=0` = forever, UTC schedule, no backfill.

### 9. `app/mcp_stdio.py` — bg_list
- Add cron icon to `icons` map: `"cron": "🔁"`.

## What NOT to touch
- Existing one-shot runners (`_run_timer/_run_file_watch/_run_command_watch/_run_ssh_watch/_run_exec`) — unchanged.
- `_trigger` (one-shot terminal path) — unchanged; cron uses `_fire_cron`.
- `status` CHECK constraint — unchanged.
- `bg_cancel` / `cancel_by_session` — already handle `active` jobs, cron included. No change.

## Tests
`tests/test_bg_jobs.py` (new file or extend):
1. `test_validate_cron_requires_expr` — missing cron_expr → error.
2. `test_validate_cron_rejects_bad_expr` — `"not a cron"` → error.
3. `test_validate_cron_accepts_valid` — `"*/5 * * * *"` → None.
4. `test_cron_create_no_timeout_means_forever` — create with timeout_seconds=0 → expires_at far future, status active.
5. `test_cron_fire_keeps_active` — mock session_manager; call `_fire_cron`; status stays 'active', config fire_count incremented.
6. `test_cron_fire_missing_target_skips` — session not found → no raise, status still active.
7. `test_run_cron_computes_next` — patch `asyncio.sleep` to capture sleep duration / fire once then cancel; assert it fired. (Use a near-future expr or monkeypatch croniter.get_next.)

`tests/test_db.py`:
8. `test_bg_jobs_accepts_cron_type` — save a job with type='cron' (after migration / new schema) → no CHECK error.
9. `test_migrate_drops_type_check` — create old-style table with the type CHECK + seed rows, run migrate, insert cron → succeeds AND original rows preserved (verify count + a column value).
10. `test_migrate_rebuild_atomic` (Codex #26-1) — force an error mid-rebuild (monkeypatch to raise between RENAME and DROP); assert the transaction rolled back and original `bg_jobs` data is intact (no `bg_jobs_old` leftover, rows preserved).
11. `test_bg_cron_record_fire` — increments fire_count, sets last_fired_at; no-op (no write) when status != active.
12. `test_bg_cron_should_fire` — True when active & not expired; False when cancelled; False when expires_at < now.

`tests/test_mcp_stdio.py`:
11. `test_bg_create_cron_builds_config` (if mockable) — cron_expr → config.

## Risks / edge cases
- **Migration table rebuild** — riskiest. Use explicit column list in INSERT...SELECT (not `*`) to survive column-order drift. Wrap in the existing `_migrate` transaction. Test against an old-schema DB.
- **croniter timezone** — pass aware UTC datetime as base; `get_next(datetime)` returns aware UTC. Consistent with codebase.
- **Far-future expires_at sentinel** — must not break `bg_expire_overdue` (it only expires `expires_at < now` → far future never matches). Good.
- **Every-minute cron** (`* * * * *`) spam — allowed; user's choice. No min-interval guard (out of scope).
- **Server restart mid-sleep** — pending fire lost; next fire computed forward. Documented (no backfill).
- **fire_count/last_fired_at race** — single-process asyncio, no concurrent writes to same job. Safe.
- **import json in db.py** — verify present; add if missing.
