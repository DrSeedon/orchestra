# #111 — Safe Codex hibernation implementation report

Date: 2026-08-01

## Outcome

Codex workers can now release their complete app-server/MCP process scope after the
existing 300-second worker or 600-second orchestrator idle timeout and resume the exact
native Codex thread on the next message. Claude hibernation remains enabled; Grok and
OpenCode remain disabled.

A targeted manual path is available at
`POST /api/sessions/{name}/hibernate` with `{"scope": "..."}`. It never cold-loads a
detached DB row. Running, waiting, pending, compacting, unsupported, and unverified
sessions return conflict instead of being disconnected.

## Tickets and commits

- T1 — stable process owner and exact resume: `5bf3570`
  (`#111: own Codex processes with verified scopes`).
- T2 — lock-linearized delivery plus manual/timer hibernate: `150c7f6`
  (`#111: add race-safe manual hibernation`).
- T3 — final capability activation only: `3a09ed7`
  (`#111: enable automatic Codex hibernation`).
- Codex P2 follow-up — require the teardown cgroup contract during preflight:
  `3764124` (`#111: validate cgroup teardown contract`).

The capability flip landed after T1 and T2 and touches only the Codex registry flag and
its exact capability-matrix test.

## Implementation

- `app/backend_codex.py`
  - probes `Linger=yes`, actual user-scope attachment, unified cgroup ownership, and a
    readable `cgroup.events` from inside a disposable scope;
  - runs eligible Codex app-servers in a unique transient user scope;
  - keeps direct launch as a logged `hibernate_safe=False` compatibility fallback;
  - interrupts an active turn, then terminates/verifies the whole owned scope with
    bounded TERM/KILL handling;
  - retains scope/backend ownership after partial teardown failure and rejects a
    substituted thread id before any turn is sent.
- `app/session.py` and `app/session_hibernate.py`
  - keep backend ownership until teardown succeeds;
  - serialize send/steer, pending dequeue, compact, wake, and hibernate decisions through
    the lifecycle lock;
  - restore failed pending delivery before hibernate can observe an empty queue;
  - expose one shared manual/timer hibernate authority with class-bearing errors.
- `app/routes/system.py`
  - adds the targeted manual endpoint without touching the concurrently owned
    `app/routes/sessions.py`.
- `app/runtime_registry.py`
  - changes only Codex `hibernate=False` to `hibernate=True`.

Production plus test diff: 11 files, `+1107/-110`.

## Verification

### Deterministic tests

- Final focused command from the approved plan: `271 passed in 46.68s`.
  Artifact: `/tmp/pytest-111-focused-final.log`.
- Final full suite under the Orchestra global test lock:
  `1309 passed, 20 skipped in 99.52s`. Artifact: `/tmp/pytest-111-final.log`.
- New race tests use controlled events/fake sleeps, not elapsed-time assertions.

### Existing live population (read-only)

The live SQLite registry contained 123 Codex rows: all 123 native `session_id` values
were non-empty and distinct; 21 were idle and 8 running at the sample. No existing
session was disconnected or mutated during validation.

### Controlled live hibernate/resume

The standalone `AgentSession` smoke used the implemented production path from the
Orchestra service cgroup:

- first process scope: 5 members; hibernate returned `state=hibernated`; survivors `[]`;
- wake: new root PID, same native thread
  `019fbc7d-40ff-7f42-b167-eca885c92bf8`;
- the resumed turn recalled the exact nonce stored before hibernate;
- cleanup scope: 6 members; survivors `[]`.

Raw artifact: `/tmp/codex-hibernate-smoke-111.json`.

## Adversarial review

`docs/tasks/111/codex-review-impl.md` preserves the first substantive review and the
required second shared-runtime round. Round 1 approved with one P2: the original
preflight proved scope attachment but did not prove the later `cgroup.events` teardown
contract. The implementation and deterministic test were corrected. Round 2 confirmed
the P2 resolved, found no P0–P2 findings, and returned **APPROVED**.

## Compatibility, rollback, and remaining risk

- No database/config migration and no native session-id reset.
- Unsupported hosts keep working through direct Codex launch, log the class-bearing
  preflight reason, and refuse manual/automatic hibernation.
- In-memory capability activation requires an ordinary Orchestra service restart. No
  restart was performed in this task.
- Rollback is a code revert; restoring only Codex `hibernate=False` immediately disables
  automatic scheduling while retaining the guarded manual/process-owner code.
