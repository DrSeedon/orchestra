# Background Jobs — Implementation Plan

## Overview
One-shot background tasks that live in Orchestra server (not CLI), survive hibernate, and wake agents on trigger.

## DB Schema (`app/db.py`)

Add to `init_db()`:
```sql
CREATE TABLE IF NOT EXISTS bg_jobs (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL CHECK (type IN ('timer','file','command','ssh')),
    config TEXT NOT NULL DEFAULT '{}',
    message TEXT NOT NULL DEFAULT '',
    target_session_id TEXT NOT NULL,
    target_name TEXT NOT NULL,
    target_scope TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','triggered','expired','cancelled')),
    timeout_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    triggered_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_bg_jobs_session ON bg_jobs(target_session_id, status);
```

Add functions: `bg_save_job()`, `bg_get_jobs()`, `bg_update_job()`, `bg_delete_job()`.

## Core Logic (`app/bg_jobs.py` — NEW)

```
BgJobManager:
    jobs: dict[str, asyncio.Task]

    create(type, config, message, target_session_id, target_name, target_scope, timeout) -> job_id
    cancel(job_id) -> bool
    list(scope?) -> list[dict]
    restore_from_db()  # on startup, resume active jobs

_run_timer(job_id, delay, message, session_id)
_run_file_watch(job_id, path, pattern, message, session_id, timeout)
_run_command_watch(job_id, command, pattern, interval, message, session_id, timeout)
_run_ssh_watch(job_id, command, host, pattern, message, session_id, timeout)
```

Each runner:
1. Runs as asyncio task
2. On trigger: calls `_trigger(job_id)` → sends message to agent via HTTP API, updates DB
3. On timeout: marks as expired, cleans up
4. On cancel: CancelledError → cleanup

## MCP Tools (`app/mcp_stdio.py`)

3 tools, all calling HTTP API:

```python
bg_create(type: str, ...) -> str
bg_list() -> str
bg_cancel(job_id: str) -> str
```

Parameters per type:
- timer: `delay_seconds`, `message`
- file: `path`, `pattern`, `message`
- command: `command`, `pattern`, `interval_seconds=60`, `message`
- ssh: `command`, `host`, `pattern`, `message`

Optional: `target` (agent name, default = caller), `timeout_seconds` (default 3600, max 86400).

## API Endpoints (`app/main.py`)

```
POST /api/bg/jobs     — create job (JSON body)
GET  /api/bg/jobs     — list jobs (query: scope=)
DELETE /api/bg/jobs/{id} — cancel job
```

## Startup (`app/main.py` lifespan)

After `manager.auto_resume_orchestrators()`:
```python
from app.bg_jobs import bg_manager
bg_manager.set_session_manager(manager)
await bg_manager.restore_from_db()
```

## Trigger Flow

```
asyncio task (timer/file/command/ssh)
  → pattern matches or delay expires
  → bg_manager._trigger(job_id)
    → find session by target_session_id in manager
    → session.send(f"[Background job triggered]\n{message}")
    → update DB: status='triggered', triggered_at=now
    → remove asyncio task from jobs dict
```

## File Watcher Implementation

```python
async def _run_file_watch(job_id, path, pattern, message, session_id, timeout):
    proc = await asyncio.create_subprocess_exec(
        "tail", "-f", "-n", "0", path,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        async with asyncio.timeout(timeout):
            async for line in proc.stdout:
                if re.search(pattern, line.decode(errors="replace")):
                    await _trigger(job_id)
                    return
    except asyncio.TimeoutError:
        _expire(job_id)
    finally:
        proc.kill()
        await proc.wait()
```

## Command Watch Implementation

```python
async def _run_command_watch(job_id, command, pattern, interval, message, session_id, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        proc = await asyncio.create_subprocess_shell(
            command, stdout=PIPE, stderr=PIPE
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        if re.search(pattern, stdout.decode(errors="replace")):
            await _trigger(job_id)
            return
        await asyncio.sleep(interval)
    _expire(job_id)
```

## SSH Watch Implementation

Same as file watch but command is `ssh <host> '<command>'`:
```python
proc = await asyncio.create_subprocess_exec(
    "ssh", "-o", "StrictHostKeyChecking=no", host, command,
    stdout=PIPE, stderr=PIPE
)
```

## Safety

- Max 50 active jobs per scope (prevent abuse)
- Max timeout: 24 hours
- Default timeout: 1 hour
- Kill subprocess on cancel/timeout
- DB cleanup: on startup, expire any jobs whose timeout_at is past

## Files Changed

1. `app/bg_jobs.py` — NEW (~200 lines)
2. `app/db.py` — schema + 4 functions (~40 lines)
3. `app/mcp_stdio.py` — 3 MCP tools (~60 lines)
4. `app/main.py` — 3 API endpoints + startup hook (~50 lines)

## Codex Review

blocking: `_trigger(job_id)` must be an atomic state transition, not "send then update DB". With the current sketch, two paths can deliver the same job: watcher match plus timeout/cancel edge, duplicate restored task, or concurrent API cancel while the runner is already matching. Minimal fix: one DB helper like `bg_claim_trigger(job_id) -> bool` that does `UPDATE bg_jobs SET status='triggering' ... WHERE id=? AND status='active'` and checks `rowcount`; only the winner may send. Then transition `triggering -> triggered` or `failed`.

blocking: The plan does not close the crash window between delivery and status update. If the process crashes after `session.send()` but before `status='triggered'`, startup restores the active row and sends again. If it updates first and crashes before `send()`, the wake-up is lost. For the stated correctness goal, the plan needs an explicit delivery contract. A pragmatic MVP version is `active -> triggering`, persist `triggering_at`, send, then `triggered`; on startup, retry stale `triggering` rows after a short age. That gives at-least-once after crashes, not strict exactly-once. Strict exactly-once is not available with current `session.send()` unless delivery itself becomes idempotent, for example by persisting a unique job delivery/inbox record that the agent consumes once.

blocking: Trigger lookup by `target_session_id in manager` is not enough for this codebase. `SessionManager` can have DB-only sessions; `send_message` already uses `ensure_loaded(name, scope)` and then falls back to `ensure_loaded_any`. Background jobs should do the same or add `ensure_loaded_by_id()`. Otherwise a valid job restored after restart or targeting a hibernated/unloaded session can fail even though the session row is resumable.

blocking: Target deletion and scope deletion are not covered. `manager.remove()`, `manager.remove_scope()`, `DELETE /api/sessions/{name}`, and `DELETE /api/orchestrators/{name}` can remove the target while a bg job remains active in DB and in `BgJobManager.jobs`. The implementation must cancel/terminal-mark jobs for that `target_session_id` or `target_scope` during removal. Add a FK policy (`target_session_id REFERENCES sessions(id) ON DELETE CASCADE` or explicit cleanup) and still cancel the in-memory task, because DB cascade alone will not kill a running subprocess.

blocking: Cancel vs trigger semantics need to be defined. `cancel(job_id)` cannot just `task.cancel()` and set `cancelled`, because `_trigger()` may already have claimed or sent the job. Use the same compare-and-set pattern: cancel only succeeds from `active`; if the row is `triggering` or `triggered`, return "already triggering/triggered" and do not overwrite it. This matters for exactly-once and for user trust in `bg_cancel`.

blocking: The schema has no `failed` or `triggering` state, but real trigger failures are possible: session deleted, `ensure_loaded` fails because cwd is gone, backend connect fails, regex invalid, command exits repeatedly with errors, ssh auth hangs, subprocess kill fails. Folding all of these into `expired` or leaving `active` hides reliability failures. Add at least `triggering` and `failed`, plus `error TEXT`.

blocking: `timeout_at` is overloaded. Timer jobs need a fire time; file/command/ssh jobs need a deadline. On restart, an overdue timer should usually trigger immediately, but an overdue file watch should expire. Store clear fields such as `trigger_at` for timers and `expires_at` for all jobs, or document the type-specific meaning and enforce it in restore logic.

blocking: Startup recovery only says "resume active jobs" and "expire any jobs whose timeout_at is past". It must also reconcile `triggering` rows, missing targets, invalid config, and jobs whose watcher subprocess was alive before shutdown. For timers, recompute remaining delay from persisted time; for polling command jobs, restart from scratch; for tail/ssh watchers, document that output emitted while the server was down is not observed. That is probably acceptable for MVP, but it must be explicit.

blocking: Subprocess cleanup in the sketches can leave children. `proc.kill(); await proc.wait()` kills only the shell or ssh/tail process, not necessarily the command's child process tree. `create_subprocess_shell(command)` is especially risky: a cancelled command can leave grandchildren running. For command and ssh watchers, start a process group/session and terminate the group on cancel/timeout; always handle `ProcessLookupError`, add a short graceful terminate, then kill.

blocking: `asyncio.wait_for(proc.communicate(), timeout=30)` in command watch times out without killing/waiting for the subprocess in the shown code. That is a direct zombie/leak path. The loop needs `try/except TimeoutError/finally` around every spawned command, and it must drain/wait after termination.

blocking: SSH watch feasibility is weaker than stated. A long-lived `ssh host command` can hang forever on auth, host key prompts, network partitions, or remote command silence. `StrictHostKeyChecking=no` does not prevent password prompts and is a security regression. Use non-interactive options (`BatchMode=yes`, `ConnectTimeout=...`, `ServerAliveInterval=...`, `ServerAliveCountMax=...`, probably `StrictHostKeyChecking=accept-new`), and wrap the whole ssh process in the same deadline and process-group cleanup. Treat ssh watch as best-effort, not a durable remote subscription.

blocking: The file watcher uses `tail -f -n 0 path`, which fails if the file does not exist yet and does not handle rotation/truncation reliably. If "wait until a log file contains pattern" is the intended behavior, either require the path to exist at creation time or use `tail -F` and surface stderr failures as `failed`. Also validate regex at create time so bad patterns fail fast instead of leaving an active job that can never trigger.

blocking: MCP `bg_create` needs a clear caller identity and scope contract. Current `mcp_stdio.py` has `SCOPE`, `ROLE`, and `WORKER_NAME`, and current send tools call HTTP by name+scope. The plan says optional `target` default caller, but the API schema stores `target_session_id`. Creation must resolve target name+scope to a session id at creation time, reject ambiguous names, and use the caller's scope by default. Otherwise cross-scope jobs can target the wrong same-name agent.

suggestion: Store `created_by_session_id` / `created_by_name` separately from `target_*`. Listing and limits are currently "per scope", but cancellation authority is unspecified. For a 1-developer MVP this can be simple, yet it should prevent one stale or cross-scope agent from cancelling unrelated jobs by id if ids leak in logs.

suggestion: Keep `config TEXT` as JSON for MVP, but add create-time validation per type and store normalized values: absolute path for file watch, interval clamped to sane minimum, compiled-regex validation, timeout clamped, command/ssh strings non-empty. Do not let runners discover malformed config minutes later.

suggestion: The active job limit should count only `active` and `triggering`, not historical `triggered`/`expired`/`cancelled`. Add an index on `(target_scope, status)` because the plan wants max active jobs per scope and `bg_list(scope?)`.

suggestion: Add a small shutdown hook for `bg_manager.shutdown()` in FastAPI lifespan before `manager.shutdown_all()`. It should cancel all watcher tasks and wait for their cleanup. Relying on event-loop teardown is how subprocess cleanup gets skipped.

question: What should happen if the target is currently running a turn? `AgentSession.send()` queues for Codex but sends directly for Claude through the current backend path. Is delayed delivery acceptable, or should bg jobs require the wake-up to be queued after the current turn for all backends?

question: Is missing file/command/ssh output during server downtime acceptable? If yes, write that into the plan. If no, file watch needs persisted offsets/inodes and command watch needs persisted last-check times, which is a bigger design than this MVP plan.

verdict: needs revision. The plan is workable as an MVP after adding atomic job state transitions, target/session cleanup integration, explicit startup reconciliation, and real subprocess process-group cleanup. Without those changes it will mostly work in happy paths, but it does not satisfy "jobs must not be lost" or "trigger exactly once".
