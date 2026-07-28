# Task #97 — implementation plan

## Goal

Keep a Codex per-turn listener bound to the exact turn id returned by its
`turn/start` RPC, and explicitly consume native compact lifecycle events before
the compact operation releases the session lifecycle lock.

The implementation must fix the measured sequence:

```text
native compact → stale turn/started → stale turn/completed
→ false AgentSession IDLE → real turn output buffered until next send
```

## Assumptions and constraints

- The `turn/start` RPC result is the authoritative current turn identity. The
  rollout in `research.md` proves it differs from the delayed compact turn id.
- `AgentSession._lifecycle_lock` serializes supported session compact/send
  calls, so no ordinary turn should begin while native compact lifecycle is
  being drained.
- The fix is Codex-local. Do not change Claude handoff compaction, Grok prompt
  queuing, runtime capabilities, or shared backend interfaces.
- Do not mutate the live database and do not restart the server.
- Production is running pre-fix, pre-#91 application code. The fix must not
  depend on #91; only current-main tests may assert the lifecycle completion
  signal added there. Battle verification starts after the eventual restart.

## Design

### One ownership invariant

Add one `CodexBackend` helper through which every `turn/started` and
`turn/completed` notification passes before `_convert_notification()`:

- extract the notification turn id;
- compare it with the immutable `expected_turn_id` captured by `events()` from
  the preceding `turn/start` result;
- accept matching lifecycle events and all non-lifecycle events;
- reject mismatched lifecycle events before they can mutate
  `_active_turn_id`, emit `turn_end`, or terminate the iterator;
- emit a debug log containing method, received turn id, and expected turn id
  for every rejection.

There will not be separate ownership checks in the started and completed
conversion branches.

### Explicit compact drain

Give each `compact_context()` call its own temporary notification queue. Attach
that queue **before** sending `thread/compact/start`, establishing that even an
immediate compact `turn/started` cannot reach the ordinary turn queue. While
native compact is active, `_read_stdout()` routes its notifications to that
queue.

One absolute compaction deadline covers the start RPC, completion notification,
and the explicit `_drain_compact_lifecycle()` step through the matching compact
terminal. A missing terminal raises timeout instead of retaining the session
lifecycle lock forever. The temporary queue is detached in `finally`, including
start-RPC failure, missing-terminal timeout, and cancellation paths.

The current-turn ownership invariant remains necessary as a defensive boundary
if compact routing or cleanup regresses.

## Files

- `app/backend_codex.py`
  - immutable expected turn id in `events()`;
  - single lifecycle ownership helper with mismatch telemetry;
  - temporary compact notification queue;
  - explicit compact lifecycle drain.
- `tests/test_backend_codex.py`
  - ownership, mismatch logging, steering identity, and compact-drain tests.
- `tests/test_session.py`
  - exact session-level false-`IDLE` regression using real
    `CodexBackend`/`AgentSession` functions.
- `docs/tasks/97/codex-review-plan.md`
  - adversarial plan review.
- `docs/tasks/97/codex-review-impl.md`
  - adversarial implementation review.
- `docs/tasks/97/report.md`
  - red/green, mutation, cross-runtime, full-suite, and deployment evidence.

## Not in scope

- Changing `_pending_messages` or `_flush_pending`.
- Changing Claude/Grok compaction or mid-turn injection behavior.
- Clearing the ordinary notification queue wholesale.
- Restarting/deploying the service.
- Refactoring unrelated Codex event conversion.

## Tickets

### T1 — Bind the listener to the RPC-returned Codex turn

- Files: `app/backend_codex.py`, `tests/test_backend_codex.py`,
  `tests/test_session.py`
- AC:
  - A regression injects mismatched compact `turn/started` and
    `turn/completed` before current-turn output and fails on the unmodified
    code with false `IDLE` / lost listener.
  - Both lifecycle methods pass through one ownership helper.
  - A mismatched start cannot overwrite `_active_turn_id`; a mismatched
    terminal cannot clear it, emit `turn_end`, or stop `events()`.
  - Each rejected lifecycle event logs method, received id, and expected id at
    debug level.
  - Matching current output is delivered without a second send, and only its
    matching terminal returns the session to `IDLE`.
  - Steering after stale lifecycle input uses the id returned by the current
    `turn/start`.
  - Listener-only mutation check: temporarily bypassing the ownership helper
    while directly injecting leaked compact lifecycle makes this regression
    fail; restoring it makes the test pass.
- blocked-by: none

### T2 — Drain native compact lifecycle explicitly and preserve other runtimes

- Files: `app/backend_codex.py`, `tests/test_backend_codex.py`,
  `tests/test_session.py`, `docs/tasks/97/report.md`
- AC:
  - `compact_context()` invokes an explicit `_drain_compact_lifecycle()` step
    and does not return while its terminal lifecycle notification remains
    available to the next ordinary listener.
  - The temporary compact queue is attached before
    `thread/compact/start`; a test emits `turn/started` synchronously with that
    request and proves it cannot reach the ordinary queue.
  - One deadline bounds the start RPC, completion wait, and terminal drain. A
    missing terminal times out and detaches the temporary queue.
  - The integrated real-function sequence
    `compact → stale start → stale terminal → next turn` fails before the fix
    and passes after it.
  - Routing/drain mutation check: bypassing compact routing or the explicit
    drain makes the integrated compact regression fail independently of the
    listener ownership-helper test.
  - Compact timeout/error paths detach their temporary queue without mutating
    the ordinary turn's active id.
  - Focused Claude and Grok backend/session tests pass unchanged; no Claude or
    Grok production file is modified.
  - Full pytest passes.
  - Codex implementation review reaches no blocking findings; all accepted
    findings are fixed and re-reviewed.
- blocked-by: T1

## Verification commands

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest \
  tests/test_backend_codex.py tests/test_session.py -x -q

UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest \
  tests/test_backend_claude.py tests/test_backend_grok.py \
  tests/test_runtime_registry.py tests/test_session_hibernate.py -x -q

UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest -x -q \
  > /tmp/pytest-97.log 2>&1
```
