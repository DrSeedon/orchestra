# Background Jobs Implementation Review

## Original Findings

1. FIXED: Atomic trigger claim is implemented. `bg_claim_trigger()` uses `UPDATE ... WHERE status='active'` before delivery (`app/db.py:431`), and `_trigger()` returns if the claim fails (`app/bg_jobs.py:232`).

2. STILL BROKEN: Crash recovery for `triggering` jobs does not actually retry. `restore_from_db()` calls `_trigger()` for rows already in `triggering` (`app/bg_jobs.py:206`), but `_trigger()` immediately calls `bg_claim_trigger()`, which only claims `status='active'` (`app/db.py:434`). Result: stale `triggering` rows stay stuck forever and are never delivered.

3. FIXED: Trigger-time session lookup now uses `ensure_loaded(target_name, target_scope)` and falls back to `ensure_loaded_any(target_name)` (`app/bg_jobs.py:238`).

4. STILL BROKEN: Target deletion/scope deletion cleanup is incomplete. `manager.remove()` calls `bg_manager.cancel_by_session()` (`app/manager.py:234`), but `cancel_by_session()` only updates DB and has an empty task loop (`app/bg_jobs.py:184`). It does not cancel live tasks or kill subprocesses. `remove_scope()` also deletes DB-only sessions directly without calling bg cancellation for those rows (`app/manager.py:247`). There is still no FK from `bg_jobs.target_session_id` to `sessions.id` (`app/db.py:150`).

5. FIXED: Public cancel vs trigger semantics are mostly correct. `bg_cancel_job()` only cancels from `active` (`app/db.py:456`), while `_trigger()` must claim `active -> triggering` first. A cancel racing after trigger claim will fail instead of overwriting `triggering`/`triggered`.

6. FIXED: The schema now has `active`, `triggering`, `triggered`, `expired`, `cancelled`, `failed`, and `error TEXT` (`app/db.py:159`).

7. FIXED: Timer fire time and deadline are now separate fields: `trigger_at` and `expires_at` (`app/db.py:162`). Restore recomputes timer delay from `trigger_at` (`app/bg_jobs.py:148`).

8. STILL BROKEN: Startup recovery is not correct because stale `triggering` rows are selected but not reset or claimable (`app/db.py:534`, `app/bg_jobs.py:206`). Also, watcher tasks that exited without a match can leave DB rows `active` with no running task until a server restart.

9. FIXED: Normal subprocess cleanup uses process groups via `preexec_fn=os.setsid` and `_kill_proc()` sends SIGTERM then SIGKILL (`app/bg_jobs.py:80`, `app/bg_jobs.py:272`, `app/bg_jobs.py:300`, `app/bg_jobs.py:327`, `app/bg_jobs.py:363`).

10. FIXED: Command watch wraps each command iteration in `wait_for(proc.communicate(), timeout=30)` and kills on timeout (`app/bg_jobs.py:305`).

11. FIXED: SSH watch now uses non-interactive keepalive/connect options including `BatchMode=yes`, `ConnectTimeout`, `ServerAliveInterval`, and `StrictHostKeyChecking=accept-new` (`app/bg_jobs.py:26`).

12. FIXED: File watch uses `tail -F` and create-time regex validation (`app/bg_jobs.py:40`, `app/bg_jobs.py:272`).

13. FIXED: MCP identity now defaults target to `WORKER_NAME`, sends `target_scope=SCOPE`, and API resolves target by name+scope before creating the job (`app/mcp_stdio.py:365`, `app/main.py:896`).

14. STILL BROKEN: Creator tracking is only `created_by_name`; there is no `created_by_session_id` and no cancellation authority check. For this local MVP that may be acceptable, but it does not implement the original suggestion fully.

15. FIXED: Config validation exists for required fields and regexes (`app/bg_jobs.py:35`). It is still light validation, but enough for the plan's MVP level.

16. FIXED: Active job counting uses `active` and `triggering`, and there is a `(target_scope, status)` index (`app/db.py:168`, `app/db.py:541`).

17. FIXED: FastAPI lifespan now calls `bg_manager.shutdown()` before session shutdown (`app/main.py:41`).

18. STILL OPEN: Running-target delivery semantics are not defined. Background jobs call `session.send()` directly (`app/bg_jobs.py:248`); Codex queues while running, but Claude behavior depends on the existing backend/session path. The plan still does not say whether delayed delivery is acceptable for all backends.

19. STILL OPEN: Missing file/command/ssh output during server downtime is still not documented. The implementation restarts watchers from "now"; it does not persist file offsets or command check windows.

## New Bugs

blocking: `app/bg_jobs.py:184` - `cancel_by_session()` does not cancel tasks or kill subprocesses. It marks active rows cancelled in DB, then iterates over `_tasks` with `pass`. A long-running `run`, `ssh`, `tail`, or command watcher can continue after its target session was deleted. Fix by making cancellation by session return job ids, then cancel those tasks and kill their `_procs`; `remove()` should await that async cleanup.

blocking: `app/db.py:534` + `app/bg_jobs.py:206` - stale `triggering` recovery is dead code. `bg_expire_overdue()` returns stale triggering ids but leaves their status as `triggering`; `_trigger()` can only claim `active`. Fix with a DB helper that either resets stale `triggering -> active` before restore, or sends from a separate `bg_claim_stale_triggering()` transition.

blocking: `app/bg_jobs.py:333` - if the SSH process exits before matching a line, `_run_ssh_watch()` falls out of the `async for` without calling `_expire()` or `bg_fail_job()`. The task ends, `_tasks` removes it, and the DB row remains `active` forever. This is easy to hit on auth failure, bad host, or remote command exit.

blocking: `app/bg_jobs.py:278` - file watch has the same early-exit shape. If `tail` exits unexpectedly without a timeout or match, the DB row remains `active` with no task. Mark early EOF as `failed` with stderr context, or restart intentionally.

blocking: `app/db.py:448` - `bg_fail_job()` overwrites any status, including `cancelled` and `triggered`. Combined with the incomplete `cancel_by_session()` cleanup, an old live task can turn a cancelled job into failed. Make terminal updates conditional, e.g. fail only from `active`/`triggering`.

blocking: `app/bg_jobs.py:379` - `_run_exec()` reads stdout under `asyncio.timeout(timeout)`, but `await proc.wait()` is outside the timeout. If stdout closes while the process remains alive, the job can hang past its deadline. Use `communicate()` or wait with the remaining deadline.

suggestion: `app/bg_jobs.py:156` - `interval_seconds` is not type-validated. An API caller can create a command job with `"interval_seconds": "x"`; creation succeeds, then `_start_task()` raises `TypeError` before a task is registered, leaving an `active` DB row with no runner.

suggestion: `app/main.py:892` - `target_scope` is stored exactly as received, while `manager.get_by_name()` normalizes by `rstrip("/")`. A trailing slash can create jobs counted/listed under a different scope string than the session uses. Normalize before storing and counting.

suggestion: `app/bg_jobs.py:224` - `has_active_jobs(session_id)` ignores `session_id` and returns whether any task is active. It is currently unused, but if used later it will block or allow the wrong session behavior.

suggestion: `app/mcp_stdio.py:377` - `bg_list()` says "List active background jobs", but `/api/bg/jobs` returns all recent jobs because `active_only` is not exposed by the API (`app/main.py:910`). Either list all jobs honestly or add an active-only filter.

## Verification

Ran `python -m py_compile app/bg_jobs.py app/db.py app/main.py app/mcp_stdio.py app/manager.py`; syntax compilation passed.

Verdict: still needs revision before relying on it for "jobs must not be lost". The main happy paths are now implemented, but stale `triggering` recovery and session-removal cleanup are still reliability blockers.
