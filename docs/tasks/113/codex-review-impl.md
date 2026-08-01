The new cleanup path can be interrupted before escalation and can signal an unrelated recycled process group. These defects undermine the intended guarantee that completed background jobs cannot leave descendants behind safely.

Full review comments:

- [P1] Avoid signaling groups through a recycled leader PID — /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-memory/app/bg_jobs.py:160-165
  After the shell is reaped, `proc.pid` is only a stale integer. On a long-running, high-process-churn host, if that PID is recycled for another `setsid` subprocess before this check, `_process_group_exists()` validates the unrelated group and the following TERM/KILL terminates that other job. POSIX prevents reuse only while an original descendant still holds the group, so group ownership must remain kernel-backed or otherwise be proven before signaling.

- [P2] Complete group cleanup after timeout or cancellation — /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-memory/app/bg_jobs.py:735-735
  If the leader exits near the job deadline, or the job is canceled while descendants are in the TERM grace period, this unshielded await is interrupted by the outer timeout/cancellation. The handlers then call `_kill_proc(proc)`, which returns immediately because `returncode` is already set, leaving TERM-ignoring descendants alive. Cleanup needs a bounded non-cancelable path, or the timeout/cancel handlers must signal the saved group themselves.

## Round (2026-08-01T09:15:55Z)

🙃 The reaper no longer shoots recycled PIDs, but cancellation still leaves a pipe hanging open.

## Re-review status

- Prior P1 — **FIXED.** Post-exit `killpg(proc.pid, ...)` is gone; the stale PID is now observation-only.
- Prior P2 — **STILL BROKEN.** Cancellation during the two-second reader wait bypasses `transport.close()`. Since the leader has exited, `_kill_proc()` returns immediately. A focused probe confirmed both transports remained open.

## New findings

### [P2] Close the subprocess transport from a cancellation-safe path

**File:** [app/bg_jobs.py:722](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-memory/app/bg_jobs.py:722) | **Confidence:** 0.99

If `_run_exec` is canceled after leader exit but before line 726, `finally` cancels the reader but never closes the transport. A long-lived descendant can therefore retain the pipe and buffer data indefinitely.

### [P2] Move the `/proc` scan off the event loop

**File:** [app/bg_jobs.py:153](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-memory/app/bg_jobs.py:153) | **Confidence:** 0.94

The synchronous full-process-table scan performs an open/read per PID inside the FastAPI event loop. Large process tables or simultaneous job completions can stall unrelated requests, and `asyncio.timeout` cannot interrupt this synchronous section.

### [P3] Do not decode process names as strict ASCII

**File:** [app/bg_jobs.py:157](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-memory/app/bg_jobs.py:157) | **Confidence:** 0.90

Linux task names may contain non-ASCII bytes. `encoding="ascii"` then raises `UnicodeDecodeError`, which is silently caught as `ValueError`, causing matching orphan processes to disappear from the statistics.

## Verdict

**CHANGES REQUESTED.** No new explicit process-group signals were introduced, and the `/proc/stat` session/starttime field indexes are correct. Tests passed: `25 passed`, plus five repeated orphan-test runs—but the cancellation leak is independently reproducible.

The scythe is gone; stdout still has its sleeve caught in the door. 🙃

## Round 3 — infrastructure timeout, no verdict

The same session was resumed after applying all Round 2 fixes:

- subprocess transport is closed from `finally` after the process has a known return code;
- `/proc` observation runs through `asyncio.to_thread`;
- `/proc/<pid>/stat` uses UTF-8 with replacement for non-UTF-8 task names;
- integration tests cover cancellation after leader exit and prove the scan runs outside
  the event-loop thread.

Codex timed out after 10 minutes without producing a review message. Its partial sandbox
trace first hit `OperationalError: no such table: bg_jobs`, then showed an isolated
`asyncio.to_thread(threading.get_ident)` probe hanging during `asyncio.run()` shutdown.
That hang did not reproduce in the task worktree: the same `.venv` probe completed and
closed in 1.1 ms; the two focused lifecycle tests passed in 2.59 s, the complete
`tests/test_bg_jobs.py` file passed 27/27, and the final suite passed 1323/1323 with 7
skips. Therefore Round 3 has **no Codex verdict**; it must not be represented as APPROVED.
The previous concrete findings were fixed and independently verified, and the configured
three-round debate ceiling was reached.
