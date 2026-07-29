# #99 — Implementation plan

## Decision

Implement a new `cron_command` background-job type before changing topic status:

1. on each cron fire, run the command server-side;
2. wake the target only when the combined stdout/stderr matches `pattern`;
3. keep the job active after a match and across restarts;
4. preserve existing one-shot `command` and unconditional `cron` behavior;
5. make runtime running status immediate, but delay idle by a fixed five minutes.

Do **not** add `wake_source` to `AgentSession.send`. Once empty checks no longer
wake the LLM, a background match represents real running work and should light
the topic. Source filtering would touch shared session provenance and still
need changes to the independent `stream_logs` ignition path.

## Deployment compatibility

`app/routes/bg.py` is unchanged because it already accepts a generic config.
`app/mcp_stdio.py` reloads before `app/bg_jobs.py`, so there is a temporary
version window: the new tool can advertise `cron_command`, but the old service
will reject it as an unknown type. This is deliberately fail-closed—no legacy
cron fallback and no unconditional LLM wake.

**A service restart is required after merge before creating `cron_command`
jobs. Existing job types continue to work during the window.**

## Changes

### Background job behavior

In `app/bg_jobs.py`:

- validate `cron_command` as a five-field UTC `cron_expr`, non-empty `command`,
  and compilable non-empty regex `pattern`;
- treat `cron_command` as a recurring no-expiry-capable type;
- also honor `timeout_seconds=0` for existing watch types (`file`, `command`,
  `ssh`) by persisting `no_expiry` and passing `None` to their runners;
- reuse the existing cron scheduler and non-terminal fire guard;
- for `cron_command`, start one process per fire, register it in `_procs`, cap
  one invocation at 30 seconds, collect stdout+stderr, and update `last_output`;
- retain the local process reference until an outer `finally`, kill it there on
  cancellation, and remove `_procs[job_id]` only when it still refers to that
  exact process;
- for completed processes, treat `pattern` as the sole wake condition:
  matching output wakes even when the process exits non-zero, while
  non-matching output never wakes;
- append an exit-code marker to recorded output for non-zero exits; on timeout,
  kill the process, record an explicit 30-second timeout marker, keep the
  recurring job active, and never wake from that invocation—even if partial
  output matched before termination;
- do not load or send to the target on a no-match;
- on a match, restore report provenance, send the match output, record the
  recurring fire, and leave the row `active`;
- on cancellation/shutdown, cancel the scheduler and terminate an in-flight
  process through the existing `_procs` lifecycle;
- skip missed schedules and overlapping runs: the cron loop awaits one command
  and computes the next future fire after it completes.

In `app/mcp_stdio.py`:

- add `cron_command` to the `bg_create` documentation and icon map;
- build its config from the already-existing `cron_expr`, `command`, and
  `pattern` parameters;
- document `timeout_seconds=0` for recurring/watch jobs;
- do not silently translate `cron_command` to legacy `cron`.

### Topic-status behavior

In `app/tg_bridge.py`:

- keep delay and edit ownership in the existing per-orchestrator
  `_topic_status_tasks` registry—do not add a second handoff registry;
- make the existing status worker delay runtime idle before it edits;
- keep running updates immediate: `_schedule_topic_status(..., True)` cancels
  and replaces a delayed-idle worker, so the direct `stream_logs` running path
  cannot bypass cancellation;
- route runtime idle signals, including the `turn ended` stream path, through
  the delayed branch already reached through `_schedule_topic_status`;
- after five minutes, resolve the orchestrator's current scope from `_manager`
  and re-check `_any_running_in_scope(scope)` synchronously before editing
  idle; if the orchestrator/scope no longer exists, skip the edit;
- keep startup synchronization immediate in both directions, but remove the
  unconditional `_topic_status.pop` so a repeated startup sync is idempotent;
- rely on existing topic deletion, rename, and `stop_bridge` cancellation of
  `_topic_status_tasks`; because the delay and edit are one task, cancellation
  cannot race across an owner handoff.

The five-minute delay is an internal constant, not new configuration.

Territory constraint: production edits stay inside `app/bg_jobs.py`,
`app/mcp_stdio.py`, and the topic-status globals/functions in
`app/tg_bridge.py` (`_topic_status*`, `_any_running_in_scope`,
`_sync_all_topic_statuses`, approximately lines 1734–1860). Do not edit the TG
delivery queue being changed by #100.

## Tests

All new timing tests use injected/monkeypatched delay coroutines, controlled
events, fake subprocesses, or a fake clock. They must not use real sleeps or
short `asyncio.wait_for` calls as behavior assertions.

Run after implementation:

```bash
uv run pytest tests/test_bg_jobs.py tests/test_mcp_stdio.py -q
uv run pytest tests/test_tg_bridge.py -q
```

The full suite is outside this worker's lock authority.

## What not to touch

- `app/routes/bg.py` — generic config already carries the new job type safely.
- `app/session.py`, `app/manager.py`, `app/limit_wake.py` — no wake-source
  propagation.
- `app/db.py` — job types are already unconstrained and current recurring
  helpers are sufficient.
- Existing `timer`, `run`, `file`, `ssh`, `command`, and `cron` match/fire
  semantics, except the explicit zero-timeout fix for watch lifetimes.
- Telegram message delivery queues and retry behavior.

## Tickets

### T1 — Conditional recurring command job

- Files: `app/bg_jobs.py`, `app/mcp_stdio.py`, `tests/test_bg_jobs.py`,
  `tests/test_mcp_stdio.py`, `tests/test_tg_bridge.py` (separate #99 boundary
  test class)
- AC:
  - four consecutive `cron_command` fires whose output does not match execute
    the command four times, call `session.send` zero times, and leave the job
    active;
  - a controlled boundary test wires fake `session.send` to the real topic
    running scheduler; four no-match fires then cause zero attributable
    `edit_forum_topic` calls, while a forced match proves the same wiring would
    edit;
  - a matching fire sends the configured message plus bounded output exactly
    once, records the fire, and leaves the job active for the next schedule;
  - matching output wakes even with a non-zero exit; non-matching non-zero
    output only records the exit marker; timeout kills the process, records a
    timeout marker, leaves the job active, and does not wake even when partial
    output emitted before the timeout matches;
  - legacy `cron` still wakes unconditionally and legacy `command` still
    terminates after its first match;
  - `timeout_seconds=0` persists/restores `file`, `command`, `ssh`, and
    `cron_command` without a one-second expiry;
  - invalid cron expressions and regexes fail before persistence;
  - cancellation during a command run terminates the process and leaves no
    owned task/process; the test cancels while `communicate()` is blocked;
  - MCP sends the exact `cron_command` config and never falls back to `cron`;
  - no new test relies on elapsed wall-clock time.
- blocked-by: none

### T2 — Asymmetric Telegram topic hysteresis

- Files: `app/tg_bridge.py`, `tests/test_tg_bridge.py`
- AC:
  - an interactive running signal schedules the running icon immediately;
  - an idle signal performs no edit before the controlled five-minute delay
    completes;
  - a new running signal cancels a pending idle owner, so four rapid
    running→idle cycles produce one running edit and no idle edit;
  - a direct `_schedule_topic_status(..., True)` call, matching the existing
    `stream_logs` path, cancels the same pending idle worker;
  - after the final delay completes with the scope still idle, exactly one idle
    edit occurs;
  - if the scope is running at delay completion, no idle edit occurs;
  - repeated `_sync_all_topic_statuses` with unchanged state does not erase the
    cache or repeat an edit;
  - cancellation of the existing `_topic_status_tasks` owner while delay or
    edit is blocked leaves no later edit;
  - no new test relies on elapsed wall-clock time.
- blocked-by: T1

## Verification gate

After both tickets, review the diff adversarially for:

- a no-match path that accidentally calls `ensure_loaded` or `session.send`;
- recurring jobs entering terminal `triggering/triggered` states;
- cancellation leaking a subprocess;
- stale delayed-idle tasks editing a deleted/renamed topic;
- a startup or stream-log path bypassing the new idle helper.

No implementation begins until this plan is approved.
