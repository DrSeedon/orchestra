# #111 — Safe Codex hibernation plan

Date: 2026-08-01

## Decision

Use a uniquely named transient systemd user scope as the Codex process owner. The
scope/cgroup owns Node, native Codex, MCP servers, thread-created children, and
reparented descendants without PID enumeration. The measured local path preserved
stdio and removed both a `setsid()` child and a real six-process Codex/MCP tree with
zero survivors.

Automatic Codex hibernation is activated only after scope ownership, exact native
resume, delivery admission, manual hibernate, and failure tests are complete. Existing
300-second worker and 600-second orchestrator timeouts remain unchanged.
`reconnect=False` and `resume_across_models=False` remain unchanged. Grok and OpenCode
remain `hibernate=False`.

## Implementation design

### Stable process ownership

At the first Codex connect in each Orchestra process, `CodexBackend` performs a bounded
host preflight using a derived user-bus environment (`/run/user/<uid>` only when the
socket exists). Eligibility requires both:

1. `loginctl` reports `Linger=yes`, so the user manager and its scopes outlive the last
   interactive logout while system-wide Orchestra continues.
2. A disposable `systemd-run --user --scope --collect true` succeeds when launched by
   the actual Orchestra process. This proves the current source cgroup may attach a
   child to the user manager; a responsive bus alone is insufficient.

The positive/negative result is cached only for that Orchestra process lifetime, so a
service restart revalidates its possibly changed cgroup/deployment. The measured live
service case passed from `/system.slice/orchestra.service` with `Delegate=no`, and the
host has `Linger=yes`. When eligible, Codex launches through:

```text
systemd-run --user --scope --quiet --collect --unit=<unique>.scope -- <codex command>
```

Scope mode is synchronous and preserves the command's stdio/PID, so the JSON-RPC
transport stays unchanged. A cryptographically unique unit name is retained as backend
ownership. No PID walk, `killpg`, or per-PID signal is used.

If linger or the disposable scope preflight fails, Codex launches directly exactly as
it does today, logs a class-bearing warning, and marks that backend
`hibernate_safe=False`. This fallback preserves worker execution on other hosts but can
never be hibernated manually or automatically. Scope-start failure after a successful
preflight is a connect error, not a silent fallback that could hide a real launch bug.

Disconnect order for a scoped backend:

1. Preserve the current bounded `turn/interrupt` attempt when a turn is active.
2. Signal the unique unit with `systemctl --user kill --kill-whom=all --signal=TERM`.
3. Await the stdio/root child and scope inactivity with bounded waits; if members remain,
   signal the same unit with KILL and verify it becomes inactive or disappears.
4. Clear process/tasks/futures/unit ownership only after that postcondition.

Failure to signal, await, or verify retains `_scope_unit` and `_proc` as retryable
ownership, raises with the exception class, and blocks `connect()` from spawning a
replacement. `AgentSession._disconnect_backend()` similarly keeps `_backend` and its
session tasks until backend teardown succeeds. Connect-failure cleanup may clear a
candidate only when it reports no owned scope.

Direct-launched fallback keeps today's disconnect behavior for ordinary stop/recovery,
but it is never accepted by the hibernate authority. This task does not claim to repair
unscoped descendant cleanup on a host without a user manager.

### Exact cold resume

`CodexBackend.connect()` retains the requested thread id separately, compares it to the
`thread/resume` response before assignment, and raises on any mismatch. Cleanup uses
the owned scope. The requested id remains available for retry and no user turn is sent
to a substituted thread.

### Lock-linearized delivery and hibernate

All `AgentSession.send()` admission decisions move under `_lifecycle_lock`, including
the current fast `RUNNING`/mid-turn path. The lock is held through the short backend
steer request. If status becomes idle and steering fails, the message is appended while
still under the lock and an immediate flush is scheduled; hibernate then observes the
pending message and cannot disconnect it. This explicitly closes the race where the
turn finalizer made its flush decision before failed injection queued the message.

`_flush_pending()` also takes `_lifecycle_lock` before copying/clearing the queue,
rechecks compaction, and clears `_hibernated` before ensuring/sending through a backend.
On failure it restores the captured messages. Codex compaction keeps `_compacting`
visible before lock acquisition; lock order defines concurrency. A later explicit
send/compact may wake a completed hibernate, but already-admitted work is never torn
down.

`HibernateManager` exposes one lock-owning immediate operation. Under the lock it
requires exact `IDLE`, no pending/in-flight delivery, no compaction, and either no
backend or `backend.hibernate_safe=True`. `_hibernated=True` is assigned only after
verified scoped teardown. The timer and HTTP route call the same operation; the timer
additionally remains gated by the registry capability. Timer wiring and fake-timer
tests land with this helper while Codex capability is still false; activation cannot
temporarily expose the legacy timer path.

### Manual API and final activation

Add `POST /api/sessions/{name}/hibernate` with the existing `ScopeRequest` body:

- missing session → 404;
- `manager.get_by_name()` returns `loaded=False` → idempotent already-process-free
  success, without `ensure_loaded()` or registry insertion;
- loaded eligible session → verified immediate hibernate;
- running/waiting, pending/in-flight, compacting, unscoped Codex fallback, or unsupported
  runtime → 409 without state change;
- teardown exception → 500 with exception class, retained owner, and no success claim.

Only after the endpoint, timer wiring, and all prerequisite tests pass does the final
ticket set Codex
`hibernate=True`. Claude remains true; Grok/OpenCode remain false. On an unsupported
host, the timer may be scheduled by the runtime capability but the backend-level safety
predicate refuses teardown, so Codex execution remains compatible and visible warning
explains why resources were not released.

## Files

- `app/backend_codex.py` — user-scope launch/kill/verification, retained unit ownership,
  direct fallback safety marker, exact resume-id validation.
- `app/session.py` — atomic backend ownership, lock-linearized send/flush admission,
  wake marker, compact interaction, public immediate-hibernate delegation.
- `app/session_hibernate.py` — shared automatic/manual hibernate authority/result.
- `app/routes/sessions.py` — manual route without cold loading.
- `app/runtime_registry.py` — final Codex capability activation only.
- `tests/test_backend_codex.py` — scope/resume ownership success and failures.
- `tests/test_session.py` — ownership plus send/flush/compact/hibernate races.
- `tests/test_session_hibernate.py` — eligibility and fake-timer behavior.
- `tests/test_api.py` — endpoint outcomes/no-load guarantee.
- `tests/test_runtime_registry.py` — final exact capability matrix.
- `tests/route_surface_snapshot.json` — intentional POST surface.

## Out of scope

- No changes to `app/manager.py`; the route avoids its unserialized cold-load path.
- No service-unit/deployment config change and no assumption that a user manager exists
  on every host.
- No Codex→Claude/model-change changes and no clearing of `session_id`.
- No Grok/OpenCode hibernation, database/config migration, dashboard button,
  load-based policy, or timeout setting.
- No service restart or mutation of any existing live worker during implementation.

## Tickets

### T1 — Give Codex a stable process owner and exact resume

- Files: `app/backend_codex.py`, `app/session.py`, `tests/test_backend_codex.py`,
  `tests/test_session.py`.
- Work:
  - preflight and launch under a unique transient user scope when available;
  - preserve direct launch as explicitly hibernate-unsafe fallback;
  - keep bounded active interrupt before unit-wide TERM/KILL and inactive verification;
  - retain scope/backend ownership through every partial failure and prohibit duplicate
    spawn;
  - require exact requested/returned thread id before assignment.
- AC:
  - scoped launch preserves stdin/stdout JSON-RPC command construction and records a
    unique unit owner;
  - preflight requires `Linger=yes` and a disposable scope spawned from the current
    Orchestra process; responsive bus with linger disabled and cross-cgroup attach
    failure both choose direct fallback without breaking Codex;
  - a service-context fixture starts outside the user-manager cgroup and proves the
    disposable probe—not a bus/socket check—is the deciding signal;
  - scope teardown signals all members, verifies inactive/absent state, and clears
    ownership only afterward;
  - fixtures representing `setsid`, a non-leader-thread child, and an intermediate
    parent exit require no enumeration and remain unit-owned;
  - injected preflight absence chooses direct execution plus `hibernate_safe=False`;
    a post-preflight scope-start error fails connect instead of falling back silently;
  - TERM failure, KILL failure, root/scope timeout, and status-query failure retain the
    same unit/backend owner; retry can finish cleanup, while connect/send cannot spawn a
    second process;
  - active turn interrupt is attempted before unit termination;
  - resume returning a different non-empty id tears down the owned unit, preserves the
    requested id, and sends no turn;
  - tests mock subprocess/status transitions and use events/fake waits, never elapsed
    time assertions.
- blocked-by: none

### T2 — Ship race-safe manual hibernate end to end

- Files: `app/session_hibernate.py`, `app/session.py`, `app/routes/sessions.py`,
  `tests/test_session_hibernate.py`, `tests/test_session.py`, `tests/test_api.py`,
  `tests/route_surface_snapshot.json`.
- Work:
  - add shared immediate hibernate operation and session delegation;
  - move every send/steer admission and pending dequeue under lifecycle ownership;
  - preserve pending delivery and wake-marker semantics across inject/flush/compact
    races;
  - expose the manual route without loading detached DB rows;
  - route the existing idle timer through the shared operation and cover it with fake
    time while the production Codex capability remains false.
- AC:
  - eligible loaded idle scoped Codex returns success only after verified teardown and
    keeps its persisted `session_id`;
  - repeat hibernate and detached `loaded=False` sessions return idempotent
    already-process-free success; neither calls `ensure_loaded()` nor constructs a
    backend;
  - running/waiting, pending/in-flight, compacting, direct fallback, and unsupported
    runtime return 409 without disconnecting;
  - teardown exception returns class-bearing 500, retains the owner, and never sets
    `_hibernated`;
  - deterministic race pauses mid-turn send after its initial RUNNING observation,
    transitions the turn to IDLE, fails steering, and proves the queued message is
    immediately flushed or remains visible to hibernate—never stuck with
    `_hibernated=True`;
  - flush cannot expose an empty-queue window; content is sent once or restored on
    failure;
  - send/steer/flush/compact-vs-hibernate tests have one lock-defined winner and no
    message loss or duplicate backend;
  - route snapshot adds exactly the requested POST path; no wall-clock assertions;
  - direct invocation of the rewired timer with a test-enabled Codex capability uses
    the same `hibernate_safe` checks and refuses an unscoped fallback.
  - fake 300-second worker and 600-second orchestrator timers disconnect an eligible
    scoped backend exactly once, set `_hibernated=True` only after verified teardown,
    preserve `session_id`, and the next send wakes with that exact id.
- blocked-by: T1

### T3 — Flip the Codex capability last

- Files: `app/runtime_registry.py`, `tests/test_runtime_registry.py`.
- Work:
  - set only Codex `hibernate=True` after the complete T1/T2 suite passes;
  - assert the final static capability matrix; make no lifecycle or route changes.
- AC:
  - capability matrix is exactly Claude=true, Codex=true, Grok=false, OpenCode=false;
  - the already-green T2 fake-timer tests prove eligible scoped disconnect/wake and
    refusal of running/pending/compacting/failed/unscoped cases;
  - the T1/T2 focused suite remains green after the one-line activation;
  - T3 contains no timer, route, backend, or lifecycle redesign and is the final
    implementation ticket.
- blocked-by: T1, T2

## Verification

Focused deterministic suite:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest \
  tests/test_backend_codex.py \
  tests/test_session_hibernate.py \
  tests/test_session.py \
  tests/test_runtime_registry.py \
  tests/test_api.py \
  tests/test_routes_surface.py -q
```

No test reads live quota state or requires systemd/Codex; unit/subprocess state is
faked. After the suite, repeat the temporary real smoke already proven in research:
launch scoped Codex with the file-backed active MCP probe, verify the unit owns the full
tree, hibernate it to zero survivors, reconnect with the same thread id, and recall the
nonce. This touches none of the existing 109 sessions and does not restart the service.

## Migration and rollback

No database/config migration. `_hibernated` and scope ownership are in-memory state;
the persisted Codex `session_id` contract is unchanged.

Rollback is one code revert. The immediate safe mitigation is to restore only Codex
`hibernate=False`; manual hibernate remains guarded by actual scope ownership. Live
activation requires the ordinary Python service restart, outside implementation unless
explicitly authorized.
