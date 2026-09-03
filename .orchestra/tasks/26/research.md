# #26 — Cron agents — RESEARCH

## Goal
Add `bg_create(type="cron", cron_expr=...)` — a periodic background job that wakes a target agent on a cron schedule. Must survive server restart.

## Current architecture (bg_jobs)

### Job types today
`timer | file | command | ssh | run` — all **one-shot** (trigger once → terminal status). Defined in:
- DB schema `bg_jobs` table (`app/db.py:171`) — `CHECK (type IN ('timer','file','command','ssh','run'))`. **Adding `cron` requires a CHECK constraint change** → migration needed (SQLite can't ALTER a CHECK; must recreate table OR drop the CHECK).
- `_validate_config` (`app/bg_jobs.py:36`).
- `BgJobManager._start_task` (`app/bg_jobs.py:148`) — dispatches to a `_run_*` coroutine.
- `bg_create` MCP tool (`app/mcp_stdio.py:458`).
- `bg_list` MCP tool (`app/mcp_stdio.py:494`) — icons map.

### Lifecycle
- `create()` (`app/bg_jobs.py:115`): validate → cap timeout → count limit → save to DB → `_start_task` (spawns asyncio task).
- `restore_from_db()` (`app/bg_jobs.py:203`): on startup, cleans old, expires overdue, resets stale, re-`_start_task`s every `active` job. **This is where cron survives restart.**
- `_trigger()` (`app/bg_jobs.py:249`): claims (`status='triggering'`), loads target session, sends message, marks `triggered`. **For one-shot jobs this is terminal.**
- Status flow: `active → triggering → triggered/failed/expired/cancelled`.

### The fundamental difference: cron is RECURRING
Every existing type ends after first trigger. Cron must fire **repeatedly** until expiry/cancel. This breaks the `triggering/triggered` terminal model. Key design decisions:

1. **Status**: cron stays `active` across firings (never goes `triggered`). It only leaves `active` on cancel/expire/fail. So `_trigger`'s claim-based dedup (`bg_claim_trigger` sets `triggering`) does NOT fit — need a separate "fire without finishing" path that keeps status `active`.
2. **Scheduling loop**: a `_run_cron` coroutine that loops: compute next fire time from cron_expr → sleep until then → send message to target → repeat, until `timeout`/cancel. The task spec mentions "asyncio loop, проверка каждую минуту" — i.e. a per-minute tick checking whether the cron matches the current minute.
3. **Restart survival**: `restore_from_db` already re-starts `active` jobs. Cron is `active`, so it gets restarted → `_run_cron` recomputes next fire from `cron_expr` (stored in `config`). Works as long as cron_expr is in config. No `trigger_at` needed (or set to next fire for visibility).
4. **expires_at / timeout**: cron still respects `timeout_seconds` (max lifetime). Default 1h is too short for a recurring job — consider larger default for cron OR document. MAX_TIMEOUT = 86400 (24h). For a long-lived cron, the user sets a big timeout. This is a real limitation worth flagging: a cron capped at 24h max is not truly "permanent". **Decision needed in PLAN** — keep MAX_TIMEOUT, or exempt cron.

## Cron expression parsing
Need a cron parser. Options:
- **`croniter`** (PyPI) — standard, mature, computes next fire time from a cron expr + base time. Clean: `croniter(expr, base).get_next(datetime)`. **Recommend** — avoids hand-rolling cron matching. Check if already a dep.
- **Hand-rolled minute-tick matcher** — parse 5 fields, match against `datetime.now()` each minute. More code, more bugs (ranges, steps, `*/5`). Avoid.

Need to verify croniter is available / add to deps (`pyproject.toml`).

## Files affected
- `pyproject.toml` — add `croniter` dependency (if not present).
- `app/db.py`:
  - `bg_jobs` CHECK constraint → add `'cron'`. Migration: recreate table or relax CHECK. Need a `_migrate`-style step.
  - Possibly store `cron_expr` inside `config` JSON (no new column needed — config is already free-form JSON). **Prefer config JSON** — no schema change beyond the CHECK.
- `app/bg_jobs.py`:
  - `_validate_config`: `cron` branch — require `cron_expr`, validate via `croniter.is_valid` / `croniter(expr)`.
  - `_start_task`: dispatch `cron` → `_run_cron`.
  - New `_run_cron(job_id, cron_expr, message, target_name, target_scope, timeout)`: loop computing next fire, sleep, fire (send to session WITHOUT marking terminal), repeat until deadline/cancel.
  - New trigger variant `_fire_recurring` (or param on `_trigger`) that sends message but keeps status `active`, updates `last_output`/a `last_fired_at`.
- `app/mcp_stdio.py`:
  - `bg_create`: add `cron_expr: str = ""` param; `type=="cron"` → `config = {"cron_expr": cron_expr}`.
  - `bg_list`: add cron icon (⏱️/🔁).
- Tests: `tests/test_db.py` (migration / type), new tests for cron validation + next-fire computation. Time-based firing is hard to unit-test directly → test the schedule computation and validation; mock/patch sleep for the loop.

## Risks / edge cases
- **CHECK constraint migration** on existing DBs — must recreate `bg_jobs` preserving rows, OR drop the CHECK. SQLite ALTER limitations. Safest: in `_migrate`, detect old CHECK and rebuild table. **This is the riskiest part.** Alternatively: remove the CHECK entirely (validation already done in `_validate_config`) — simpler, defensible (app-level validation is the real guard).
- **DST / timezone**: croniter with naive vs aware datetimes. We use UTC everywhere (`datetime.now(timezone.utc)`). Use UTC base for croniter to stay consistent. Document that cron fires in UTC.
- **Missed fires after downtime**: if server was down across a scheduled time, on restart `_run_cron` computes *next* fire (forward only) — past fires are skipped, not backfilled. Acceptable; document.
- **Recurring trigger vs claim model**: must NOT reuse `bg_claim_trigger` (it's one-shot). Need a non-terminal send path.
- **timeout vs forever**: MAX_TIMEOUT 24h caps cron. Flag in plan; likely raise/exempt for cron.
- **Tight schedules** (`* * * * *` = every minute) → spam. Maybe a min-interval guard. Low priority; note it.
- **Target session missing at fire time** — current `_trigger` fails the job. For cron, a transient missing session shouldn't kill the whole schedule. Decide: skip-and-continue vs fail. Recommend skip-and-log, keep cron alive.

## External references
- `croniter` docs: `croniter(expr, base_dt).get_next(datetime)`; `croniter.is_valid(expr)`.
- Existing restart-survival pattern: `restore_from_db` (`app/bg_jobs.py:203`).

## Recommendation
- Use **croniter** (add dep).
- Store `cron_expr` in `config` JSON (no new column).
- For the CHECK constraint: **drop it** (rely on `_validate_config`) via a `_migrate` table rebuild — simplest robust path; OR rebuild with `'cron'` added. Decide in PLAN.
- New `_run_cron` loop + non-terminal fire path that keeps status `active`.
- Re-evaluate MAX_TIMEOUT for cron in PLAN.
