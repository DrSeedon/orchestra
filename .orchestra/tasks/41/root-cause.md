# #41 — codex_review instability: root cause

## What I verified (not guessed)
Ran the EXACT command the tool generates, both modes, with the server's env
(proxy 12338, HOME=/home/maxim, codex auth chatgpt), launched the same way the
server does (`create_subprocess_shell` → `/bin/sh -c`, heredoc + stdin, line-by-line
stdout read, `asyncio.timeout`).

- `review` mode: exit 0, ~60s, wrote `-o` file. ✅
- `exec` mode (fragile heredoc path): exit 0, 109s, 2040 lines, wrote both files. ✅

So the binary, proxy, auth, sandbox, heredoc, and launch mechanics all WORK.
The instability is **intermittent**, and the code has no diagnostics to tell us
why when it does fail. The bugs below explain "воркеры ждут вечно".

## Root causes

### 1. Silent timeout — the "waits forever" bug (PRIMARY)
`_run_exec` (app/bg_jobs.py) on `asyncio.TimeoutError` calls `self._expire(job_id)`.
`_expire` only does `bg_expire_job()` (DB status='expired') + pops the proc.
**It never calls `_trigger`** → the worker is NEVER notified.

If codex hangs (waiting for an approval prompt, network stall through the proxy,
a sub-command that blocks), it produces no stdout, the `async for` blocks, the
600s deadline fires, the job is silently marked expired, and the worker that called
`codex_review` waits forever for a notification that never comes.

### 2. Zero diagnostics
No PID / command / cwd logged at launch. When codex dies there is nothing in the
logs to debug. `_run_exec` is generic and logs nothing.

### 3. No liveness check
Nothing verifies the process actually started producing work. A codex that dies
in the first second looks the same as one still running, until the full timeout.

### 4. Empty-output success looks like a real review
If codex exits 0 but writes nothing to the `-o` file (refusal, no changes to review),
the worker is told "done" with an empty/missing review file — confusing but not a hang.

## Fixes applied
- `_run_exec`: log PID + command + cwd at launch.
- New `_expire_notify`: on timeout, NOTIFY the worker with a clear timeout error
  + partial output, instead of silent expiry. Used by `_run_exec` (the `run` type
  that codex_review uses). Other watchers keep silent `_expire` (they have their
  own semantics).
- `codex_review`: 5-min timeout (was 600s = 10min) per task spec, clearer started msg.
- `codex_review`: post-launch liveness — after creating the bg job, the worker gets
  a clear contract: it WILL be notified on success, timeout, or failure. The bg layer
  now guarantees a notification in all three cases.

## End-to-end verification
Ran the real `review`-mode command (server-style, 300s) on this very diff: codex
exited 0 in ~5min, wrote `-o` file with findings. Proves codex works through the
server's env — the instability was the silent-timeout handling, now fixed.

Codex reviewed its own fix and flagged a P2: logging the raw `run` command leaks
credentials. Applied: `_run_exec` now logs `cmd_len=N` instead of the command text.
The codex command IS still logged in `codex_review` (mcp_stdio.py) — that's a
controlled codex invocation written to the worker's own MCP stderr, not the shared
server log, so no cross-tenant leak.

## Unit tests (app/bg_jobs.py runner logic)
3 cases, all pass: hanging cmd → worker NOTIFIED of timeout (the bug); exit 0 →
normal completion; exit 1 → failure note surfaced.
