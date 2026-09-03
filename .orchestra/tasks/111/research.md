# #111 — Codex session hibernation research

Date: 2026-08-01

## Question

- **Context:** Orchestra keeps one `codex app-server` process per loaded Codex
  session. Codex currently declares `hibernate=False`, so the ordinary 5/10-minute
  idle timers never release those processes.
- **Change under test:** disconnect an idle Codex backend, retain its native thread id,
  then construct a new backend and resume that thread on the next message.
- **Baseline:** keep every Codex app-server alive indefinitely.
- **Deciding outcomes:** the old process exits, the new process has a different PID,
  `thread/resume` returns the same thread id, a post-resume turn recalls a unique value
  from the pre-disconnect turn, and no native session id is cleared or replaced.

## Hypotheses and falsifiers

### H1 — Codex can use the existing hibernate/wake lifecycle safely

Codex thread state survives the app-server process because a fresh backend can call
`thread/resume` with the persisted Orchestra `session_id`.

**Falsifier:** after an orderly disconnect, a fresh app-server rejects
`thread/resume`, returns a different thread id, or cannot recall the unique value from
the previous turn.

### H2 — `reconnect=False` forbids Codex hibernation

If `reconnect=False` describes all process replacement, the hibernate wake path cannot
restore a Codex backend.

**Falsifier:** code shows that `reconnect` gates only in-place heartbeat recovery of a
running persistent listener, while ordinary wake constructs a new backend through
`_ensure_backend()` and `thread/resume` succeeds in a new process.

### H3 — the existing `hibernate=False` records a current Codex limitation

The flag may have been deliberately retained after the persistent app-server adapter
was introduced because resume was known to lose thread context.

**Falsifier:** history shows the Claude-only guard predates persistent Codex, the
app-server migration left the inherited flag unchanged without recording such a
limitation, and a cold-resume experiment preserves context.

## Experiment protocols (criteria fixed before execution)

Run two independent trials in temporary directories with the real installed Codex
CLI and `CodexBackend`, without loading or mutating any Orchestra session:

1. Start a new backend/thread and complete a turn that stores a trial-specific nonce.
2. Record thread id and app-server PID, then call `disconnect()`.
3. Verify the original PID is no longer alive.
4. Construct a new backend with the recorded thread id and the same cwd/model.
5. Verify the new PID differs, `connect()` returns the same thread id, and a second
   turn returns the exact nonce.
6. Disconnect the second backend and verify its process exits.

**GO:** both trials satisfy all six checks. **NO-GO:** either trial loses context,
changes the thread id, cannot resume, or leaves either process alive. Latency and token
usage are recorded but are not pass/fail criteria.

After the first Codex review challenged the process boundary, a second controlled
experiment used a real long-running MCP tool call. Before running it, the criterion
was fixed as: capture the complete descendant tree while the tool is active, invoke
teardown, then require every captured PID to be absent. The baseline was the current
`disconnect()`. A candidate teardown was tested separately: snapshot descendants,
send `SIGTERM` deepest-first, then run the ordinary backend disconnect. **GO for the
candidate:** zero captured survivors after 750 ms. **NO-GO:** any survivor. This
stronger active-call probe does not authorize hibernating active turns; it tests that
the teardown primitive owns the full process tree.

The plan review then falsified PID-walk safety: `/proc` child enumeration can miss
thread-created or reparented descendants, and `(pid,starttime)` still has a
check-to-signal reuse race [5]. A third protocol therefore tested ownership by a
transient systemd user scope instead of PID enumeration. Predeclared pass criteria:
the command keeps working over inherited stdio; the scope is observable as active;
`--kill-whom=all` removes a deliberately `setsid()`-detached child and every captured
member of a real six-process Codex/MCP tree; zero survivors after 750 ms. Any survivor,
lost stdio, or unavailable user manager is NO-GO for scope-backed hibernation.
After plan review raised deployment context, the same detached-child probe was launched
as a server-side Orchestra background job. Its parent therefore came from the real
`/system.slice/orchestra.service` cgroup rather than the interactive shell. Pass
criteria stayed zero survivors plus an active user-scope cgroup. Host lifetime was
checked independently with `loginctl`; scope eligibility requires `Linger=yes`.

## Findings

### F1 — the missing capability is the direct reason idle Codex processes never hibernate

`HibernateManager.schedule()` cancels any prior timer and returns immediately when the
runtime does not declare `capabilities.hibernate`; Codex currently declares
`hibernate=False`, whereas Claude declares `True` [2]. Turn completion does call
`schedule()` for Codex, but the capability guard prevents a timer from being created
[2]. The configured timeouts are already live at 300 seconds for workers and 600
seconds for orchestrators [2].

**CONFIRMED — current source plus live process/journal measurement (tiers 1 and 2).**

A second live snapshot at 2026-08-01 13:56 UTC+7 found:

```text
native app-server: 16 processes, 2488.8 MiB RSS
node launchers:     16 processes,  613.7 MiB RSS
code-mode helpers: 17 processes,  221.9 MiB RSS
combined:          49 processes, 3324.4 MiB RSS
swap used:         11 GiB
load average:      3.53 / 2.75 / 4.22
hibernate/wake journal events in preceding 3h: 0
```

This independently corroborates the task snapshot (62 Codex processes / 3.4 GiB RSS /
10 GiB swap), while also showing that process count and load vary as workers start and
finish.

### F2 — `hibernate=False` predates the persistent Codex process; history does not show a resume prohibition

Idle hibernation was introduced on 2026-05-15 for the persistent Claude SDK process
(commit `000ff65`). At that time the Codex backend launched `codex exec` per turn,
`connect()` was a no-op, and there was no idle Codex process to release. The
provider-neutral runtime registry preserved the existing Claude-only guard as
`codex.hibernate=False` on 2026-07-17 (commit `cd3dce1`). Codex moved to a persistent
`app-server` the next day (commit `4cc8c32`); that change enabled mid-turn steering but
left the inherited hibernate flag untouched. Its report says only “hibernate пока не
включён” and records no resume failure [3].

**CONFIRMED for chronology; UNCERTAIN for unrecorded author intent — git history is a
primary source, but cannot prove an undocumented reason.** The chronology explains why
the old value was once correct and turns the current flag into an unverified holdover,
not evidence that resume is unsafe.

### F3 — a basic Codex thread survives app-server teardown and cold resume

The installed runtime is `codex-cli 0.145.0`. The official app-server contract defines
a thread as the conversation, says `thread/resume` reopens a stored thread by id, and
returns the same thread id in the response [1]. Orchestra implements exactly that:
`CodexBackend.connect()` starts a new app-server, calls `thread/resume` when constructed
with a thread id, and rejects a response without an id [2]. `disconnect()` terminates
and waits for the app-server process, but does not clear `_thread_id` [2].

The predeclared two-trial experiment passed all checks:

```text
trial 1
  thread: 019fbc1a-7927-7433-b808-769e17f35dd8 → same id
  PID: 445506 → 446458; both dead after their disconnect
  first turn: 6.134s, STORED, ok/end_turn
  resumed turn: 6.198s, HIBERNATE-111-1-Q7M4, ok/end_turn

trial 2
  thread: 019fbc1a-ac44-7f81-9a54-059e953f3eb0 → same id
  PID: 447493 → 448517; both dead after their disconnect
  first turn: 7.749s, STORED, ok/end_turn
  resumed turn: 10.598s, HIBERNATE-111-2-Q7M4, ok/end_turn
```

All 12 boolean checks were true: new PID, same thread id, exact nonce recall, both old
and new app-server processes gone, and both turns terminal-successful in both trials.

**CONFIRMED for orderly same-runtime/same-model resume on CLI 0.145.0 — direct
measurement plus the current official protocol (tiers 1 and 2).** The trials used new,
short threads and prove the native resume primitive, not every long or compacted
production-thread shape. The protocol contract supplies the broader basis; a missing
or corrupt rollout must still fail closed.

### F4 — `reconnect=False` and `resume_across_models=False` do not forbid idle hibernation

`reconnect` is read only by the heartbeat path that tries to repair a dead listener
while a session is still `RUNNING`; it requires an in-place backend `reconnect()` [2].
Idle wake follows a different path: `send()` takes `_lifecycle_lock`, clears the
transient hibernated marker, and `_ensure_backend()` constructs a new backend [2].

`resume_across_models` is read only by `change_model()`. Codex deliberately clears the
native thread id and builds an Orchestra handoff when the model or runtime changes [2].
Hibernate changes neither. `_make_backend(force_fresh=False)` passes the existing
Orchestra `session_id` to the Codex factory as `resume_thread_id`; only explicit
force-fresh and model/runtime change clear it [2].

**CONFIRMED — exhaustive current-code use sites (tier 2) and the cold-resume experiment
(tier 1).** A Codex thread id remains runtime-specific; the result does not authorize
carrying it across Codex→Claude or model changes.

### F5 — the lifecycle lock is the right authority, but the current predicate is incomplete

Automatic hibernate and idle `send()` use the same `_lifecycle_lock`, so backend
replacement can be serialized [2]. However, two pre-lock state transitions make the
existing predicate insufficient:

- `_flush_pending()` copies and clears `_pending_messages` before taking the lifecycle
  lock. A manual hibernate can then see an empty queue, disconnect, and return before
  flush acquires the lock and immediately recreates the backend. Flush also does not
  clear `_hibernated`, so that race can leave a running process marked hibernated.
- Codex compact sets `_compacting=True` before taking the lock, but automatic hibernate
  does not test it. The timer can disconnect first and compact can then recreate the
  backend, defeating the requested resource release.

**CONFIRMED — current control flow and adversarial review (tier 2).** The fix must move
pending dequeue under the lifecycle lock, clear `_hibernated` on the flush wake path,
and make automatic/manual hibernate share checks for capability, exact idle status,
pending work, and `_compacting`. Deterministic event-controlled race tests are required;
the existing hibernate tests cover zombie detection only.

### F6 — a manual route needs a guarded lifecycle operation, not the existing restart route

There is no `/api/sessions/{name}/hibernate` route. The nearby `restart-cli` route is
not a safe alias: it calls `_disconnect_backend()` without checking `RUNNING`, pending
messages, compaction, runtime capability, or taking `_lifecycle_lock`, then forces the
status to `IDLE` [2]. Reusing it could interrupt an active turn and misreport delivery.

The manual operation must share the automatic hibernate predicate and lock, be
idempotent for an already process-less session, preserve `session_id`, and fail closed
for `RUNNING`, `WAITING`, compacting, or pending-message states. It must not call
`ensure_loaded()`: that method is not serialized across concurrent callers, and two
loaders can construct distinct `AgentSession` objects before either enters the
registry. `manager.get_by_name()` already returns either the registered live object or
a detached `loaded=False` DB hydrate without starting a backend [2]. A detached object
is already process-free, so the route can return idempotent success without loading it.

**CONFIRMED — current route and manager source (tier 2).** A new DB/config field is not
needed; `_hibernated` is intentionally transient process state.

### F7 — enable only Codex, not every process-backed runtime

No equivalent cold-resume experiment was run for Grok or OpenCode. Their capability
flags remain negative, and changing them would expand the risk beyond the measured
case [2].

**CONFIRMED scope decision — lack of measurement is itself the boundary.**

### F8 — current `disconnect()` does not own the full Codex/MCP process tree; a systemd scope does

The stronger MCP probe ran a real `hibernate_probe.ping` call that slept for 60
seconds. Before teardown the captured tree had six processes: Node launcher, native
Codex, the probe, `kwin-mcp`, Serena, and Orchestra MCP. Current `disconnect()` removed
the launcher/native/probe, but after 750 ms Serena PID `585835` and Orchestra MCP PID
`585836` were still alive. Starting Codex in a new process group and killing that group
still left Serena PID `588449`, so process-group isolation alone is insufficient.

A separate PID-walk candidate signalled captured descendants and produced zero
survivors, but plan review correctly refuted it as a production ownership mechanism:
`/proc/.../children` can miss non-leader-thread children/reparenting, and checking
starttime before `kill(pid)` does not close PID reuse between check and signal [5].

The replacement experiment used `systemd-run --user --scope --collect` (systemd
257.9). The local user manager placed the command in
`/user.slice/user-1000.slice/user@1000.service/app.slice/<unit>.scope`. Scope commands
kept inherited stdio and the launched process retained the `Popen` PID, matching the
systemd contract [5]. Three probes passed:

```text
detached-child probe
  root: 745475; setsid child: 745476; both survivors after scope kill: []

real Codex/MCP probe (active 60-second MCP call)
  scope: orchestra-codex-probe-05945d0e32a6440b8e48b3ef6c377a3c.scope
  root/native/Serena/kwin/probe/Orchestra MCP: 6 captured processes
  survivors 750ms after systemctl --user kill --kill-whom=all: []
  stdio initialize + turn + MCP call succeeded before teardown

live Orchestra service-context probe
  measured /proc/self/cgroup: 0::/system.slice/orchestra.service
  measured loginctl Linger: yes; service Delegate=no; User=maxim
  scope: /user.slice/user-1000.slice/user@1000.service/app.slice/orchestra-probe-111.scope
  root: 812677; setsid child: 812678; both survivors after scope kill: []
```

Scope membership survives `setsid`, thread creation, intermediate-parent exit, and
ordinary reparenting because systemd manages the cgroup as a process set rather than a
PID family-tree snapshot [5]. Unit-scoped signalling also removes the check-then-kill
PID race: the implementation addresses a unique transient unit, not individually
revalidated PIDs.

**CONFIRMED for this host — six controlled teardown measurements plus local systemd
primary documentation (tiers 1 and 2).** The additional service-context measurement
directly confirms that this deployed `Delegate=no` system service can attach its child
to the user scope; kernel delegation rules mean a responsive bus alone would not prove
that on another host [6]. Codex hibernation is therefore safe only after both
host-lifetime (`Linger=yes`) and a disposable scope launched from the actual Orchestra
process succeed. The positive result is cached only for that Orchestra process/cgroup
lifetime. On failure, Codex retains its current direct launch so worker execution does
not break, but that backend is explicitly ineligible for automatic/manual teardown and
the reason is logged with its exception class. Because `disconnect()` also serves
active stop/recovery paths, it retains the existing bounded `turn/interrupt` handshake
before unit-wide termination.

### F9 — Codex resume currently accepts a substituted thread id

`CodexBackend.connect()` calls `thread/resume` with the persisted id but validates only
that the response id is non-empty, then overwrites `_thread_id` [2]. The official
contract says resume returns the recorded thread [1]. A different non-empty id therefore
means the requested native session was not resumed and must fail closed before any user
message is submitted.

**CONFIRMED — source/contract comparison (tier 2).** The wake path must compare the
requested and returned ids exactly, disconnect on mismatch, preserve the persisted
Orchestra id, and surface the error. A silent fresh-thread fallback would be context
loss disguised as success.

### F10 — teardown failure currently loses the only backend owner

`AgentSession._disconnect_backend()` assigns `_backend=None` before awaiting
`backend.disconnect()` [2]. A new descendant enumerator, signal, or verification step
can fail after finding a live process. In that case hibernate correctly avoids setting
`_hibernated`, but the session has already discarded the object that knows which root
and descendants still need cleanup. A later manual call can misreport idempotent
success, or a send can construct a second backend.

**CONFIRMED — current ownership order plus failure-path analysis (tier 2).** The
contract must be atomic from `AgentSession`'s perspective: keep `_backend` until its
disconnect confirms the unique scope is inactive/absent. The Codex backend retains the
scope unit as retryable ownership across partial `systemctl`/timeout failure and refuses
to connect/spawn while it remains. Connect-failure cleanup follows the same rule; the
session may clear a failed candidate only after it reports no owned scope. Deterministic
failure-injection covers scope creation, TERM/KILL, inactive verification, and timeout;
no failure may produce a second backend.

## Counter-evidence and residual uncertainty

- The persistent app-server migration left `hibernate=False`, and its
  report did not claim parity. This is the strongest counter-signal, but no failing
  resume case or incompatible contract is recorded. Two real cold resumes falsified
  the concrete context-loss hypothesis.
- `thread/resume` is only as durable as Codex's stored rollout. If the rollout is
  deleted/corrupt, Orchestra's Codex path fails loud; unlike Claude, it does not build a
  DB-log fallback. Hibernation must preserve the id and propagate that failure rather
  than silently start a new thread. The experiment covered orderly disconnect, not
  disk loss or `SIGKILL` during a write.
- Current disconnect leaking two controlled MCP descendants is direct counter-evidence
  to the original capability-only proposal. The GO decision is now conditional on
  landing and testing descendant teardown first. The candidate succeeded once; the
  implementation test and a post-implementation real idle-worker smoke must verify it
  again.
- The zero-survivor PID-walk candidate was insufficient despite passing: enumeration
  and signal identity were racy. It is retained as counter-evidence against trusting a
  green happy-path process test. The accepted design uses cgroup/scope ownership and
  tests `setsid` plus a real MCP tree instead.
- Two earlier inline custom-MCP attempts were unsuitable: one failed TOML parsing and
  one never started its lazy server. They are not positive evidence. The F8 result is
  from a separate file-backed MCP server whose `tools/call` was observed active in the
  captured descendant tree.
- `_hibernated` is not persisted. After an Orchestra restart an idle loaded session
  reports ordinary `IDLE`, but `_load_from_db()` also leaves `_backend=None`; it is
  already process-free and the next send still resumes by persisted `session_id`.
- The measured turn durations exclude backend `connect()` time, so this research does
  not claim a wake-latency number. First-message wake latency should be observed in the
  implementation smoke, but it is not a session-safety criterion.

## Affected files and implementation risks

- `app/runtime_registry.py`: change only Codex `hibernate` capability, and do it last
  after descendant ownership, exact resume-id validation, lifecycle predicate,
  pending-dequeue serialization, and `_hibernated` reset all land; keep Grok and
  OpenCode disabled.
- `app/backend_codex.py`: fail closed if `thread/resume` returns a different id; launch
  under a unique transient user scope when available; terminate/verify that scope as a
  unit; retain retryable scope ownership across partial failure and refuse a new spawn
  until cleanup succeeds. Direct-launch fallback remains execution-compatible but
  hibernate-ineligible. Do not change turn or storage semantics.
- `app/session_hibernate.py`: expose one guarded/idempotent immediate operation and use
  it from the timer so manual and automatic semantics cannot drift.
- `app/session.py`: retain `_backend` until teardown succeeds (including failed-connect
  cleanup), move pending dequeue under the lifecycle lock, clear the transient
  hibernate marker on queued wake, and expose a public session-level delegation for the
  route; do not change session-id migration.
- `app/routes/sessions.py`: add the exact requested POST route with 404/409 outcomes;
  do not reuse unsafe `restart-cli` behavior.
- `tests/test_session_hibernate.py`, `tests/test_runtime_registry.py`,
  `tests/test_session.py`: deterministic capability, idle teardown, wake/resume-id,
  pending/running/compact/mid-turn admission, scope teardown, direct fallback,
  resume-id mismatch, connect-failure, and send/flush-vs-hibernate race coverage. No
  real-time thresholds.
- `tests/test_api.py`, `tests/test_routes_surface.py`,
  `tests/route_surface_snapshot.json`: manual route behavior and API surface.

Risks to guard:

1. Disconnecting while a turn, compact, background wait, or queued message is active.
2. Clearing/replacing a Codex thread id on hibernate or resume failure.
3. Reporting `hibernated` before process teardown has completed.
4. A second manual request racing a wake and killing the newly created backend.
5. Accidentally enabling unmeasured Grok/OpenCode hibernation.
6. Silently falling back to a new Codex thread when the native rollout is missing.
7. Leaving detached MCP descendants after reporting a successful hibernate.
8. Cold-loading the same DB-only session twice through a manual route.
9. Clearing the only backend owner after partial teardown and spawning a duplicate.
10. Treating an unavailable/transiently failing user scope as permission to hibernate a
    direct-launched backend.

## Sources

1. [OpenAI Codex App Server documentation](https://learn.chatgpt.com/docs/app-server),
   fetched 2026-08-01 — primary source: lifecycle overview and `thread/resume`
   contract.
2. Current Orchestra source at `d1fcdbd`: `app/runtime_registry.py`,
   `app/session_hibernate.py`, `app/session.py`, `app/session_turns.py`,
   `app/backend_codex.py`, `app/manager.py`, `app/routes/sessions.py` — primary source.
3. Orchestra git history: `000ff65` (Claude idle hibernate, 2026-05-15), `cd3dce1`
   (runtime capabilities, 2026-07-17), `4cc8c32` and
   `docs/tasks/codex-worker-parity/report.md` (persistent Codex app-server,
   2026-07-18) — primary source.
4. Direct measurements in this research session on 2026-08-01: live process/RSS/swap/
   journal snapshot; two independent native cold-resume trials; controlled process-tree
   teardown — highest-tier evidence.
5. Local systemd 257.9 primary manuals opened 2026-08-01: `systemd-run(1)` (`--scope`
   executes synchronously with inherited environment and service-manager ownership),
   `systemd.scope(5)` (scope lifecycle tracks the process set, not one main PID), and
   `systemctl(1)` (`kill --kill-whom=all`). Linux primary manuals
   `proc_tid_children(5)` and `pidfd_send_signal(2)` were used to reject the PID-walk
   design.
6. [Linux kernel cgroup v2 documentation](https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html),
   opened 2026-08-01 — primary source: child cgroup inheritance, process migration,
   populated-state semantics, and cross-delegation containment requirements.
