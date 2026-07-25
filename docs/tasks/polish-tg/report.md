# Phase 3 report — Telegram bridge reliability polish

Status: implementation complete. No service restart or production Telegram call.

## T1 — bounded fair telemetry scheduler

### Red evidence (before production-code changes)

```text
UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest \
  tests/test_tg_bridge.py::TestTgTelemetryFairness -q -p no:cacheprovider

6 failed, 1 passed in 2.33s
```

The three parametrized starvation cases observed tool positions `6`, `21`, and `51` after 5,
20, and 50 later reliable calls. The 1,000-event test had no bounded scheduler snapshot, the
never-returning telemetry call held the dispatcher past the test deadline, and reliable admission
had no bounded state. The update-during-send control already passed against the old FIFO because
it did not coalesce entries.

### Green evidence

```text
tests/test_tg_bridge.py::TestTgTelemetryFairness
8 passed in 1.44s

tests/test_tg_bridge.py
64 passed in 1.63s
```

Implemented in `app/tg_bridge.py`:

- one per-chat dispatcher with bounded reliable FIFO (`256`) plus bounded admission waiters
  (`64`) and typed overload;
- one coalesced telemetry entry per key, capped at `128`, with shared completion and explicit
  overflow;
- 15-second eligibility and one overdue telemetry slot after at most three reliable slots;
- version replacement when a new event arrives during an in-flight digest;
- one-attempt 2-second telemetry deadline;
- async reset which settles queued/in-flight work and awaits bounded admission owners;
- SQLite stream cursor rollback on typed reliable overload;
- fixed-size delivery snapshot counters.

### T1 review status

Plan review reached Codex `APPROVED`. The first implementation diff review was unavailable:
both Codex WebSocket and HTTPS transports returned `Connection refused`; the platform bug was
reported and no implementation verdict was claimed. The required final diff review remains
scheduled.

Self-review found and fixed before commit:

1. reset removed the chat registry before awaiting the old dispatcher, which could permit two
   owners during concurrent restart;
2. reliable overload returned ordinary `None`, so `stream_logs()` could advance its SQLite
   cursor and lose the reply instead of retrying;
3. immediately rejected telemetry keys still created wrapper tasks, allowing transient task
   growth during an overflow burst;
4. formatted-entity fallback reused the live telemetry key and could replace a newer tool event.

Not exercised against live Telegram: actual Bot API cancellation latency and real 3.05-second
wall-clock fairness. Deterministic tests replace those intervals and block calls with events.

## T3 — stream/topic/status lifecycle

### Red evidence (before production-code changes)

```text
tests/test_tg_bridge.py::TestTgLifecycleReliability
6 failed in 1.70s
```

The failures directly reproduced: configured streams starting only after blocked topic work; two
stream tasks for one newly created topic; two remote creates from concurrent sync; awaited runtime
status; unbounded topic creation; and a debounce task/buffer surviving bridge stop.

### Green evidence

```text
tests/test_tg_bridge.py::TestTgLifecycleReliability
7 passed in 1.43s

tests/test_tg_bridge.py
71 passed in 1.72s
```

Implemented:

- idempotent owned stream registry, with configured streams started before status/create work;
- serialized primary/mirror topic creation with 5-second deadlines and persisted uncertain-result
  markers which prevent blind duplicate creation;
- one coalescing background status owner per topic; runtime log polling no longer awaits topic
  metadata;
- delete/rename cancellation and await of old stream/status owners, including delete→recreate;
- stop cancellation/await for stream, status, creation, bridge, and inbound debounce owners,
  followed by buffer/registry cleanup.

Self-review checked concurrent create registration, task callback/registry ordering, status changes
arriving during a blocked edit, cancellation through `asyncio.shield()`, and delete→recreate. It
found two additional cleanup gaps and fixed them: main-topic removal now clears an uncertain
create marker, and stop clears the topic-status cache. Live ambiguous `createForumTopic` behavior
cannot be reconciled through Bot API, so an uncertain marker intentionally requires explicit
operator/config resolution.

## T4 — generation-safe voice/video-note reservations

### Red evidence (before production-code changes)

```text
tests/test_tg_bridge.py::TestMediaGenerationSafety
3 failed, 1 passed in 1.54s
```

The stale completion overwrote next-generation text, resolved/decremented the next generation's
media reservation, and repeated the same corruption after a simulated stop/restart buffer reset.
The valid in-generation ordering control passed.

### Green evidence

```text
tests/test_tg_bridge.py::TestMediaGenerationSafety
5 passed in 1.35s

tests/test_tg_bridge.py
76 passed in 1.62s
```

Media handlers now carry an opaque token containing a unique buffer-instance epoch and a unique
reservation identity. Resolution requires both identities, consumes the reservation once, and
every flush replaces the epoch. Stop/restart cannot reproduce either object identity.

Self-review added two defenses beyond the original reproduction: a late resolver after stop no
longer creates an empty buffer, and resolving the same token twice cannot overwrite its first
completion or decrement media twice.

## T2 — bounded optional images with unconditional text evidence

### Red evidence (before production-code changes)

```text
targeted image regressions
3 failed in 1.88s
```

Rendered PNG bytes were reported as success after a failed delivery, a truthy image submission
prevented `stream_logs()` from calling `_send_expandable()`, and the scheduler exposed no bounded
image lane.

### Green evidence

```text
tests/test_tg_bridge.py
80 passed in 1.71s
```

The shared chat dispatcher now owns a separate best-effort FIFO capped at 64 entries, with images
limited to 16 of those entries and reject-new overflow. It never consumes reliable queue or
admission capacity. `_ImageSubmission` exposes acceptance and actual completion without making
the stream wait; temp files are removed on completion, rejection, failure, cancellation, or
reset.

Diff/result images are supplemental only. Tool start/result text is always queued even when an
image is rendered and accepted, so delayed or failed photo delivery cannot remove both
representations. A real failed completion (mocked `TelegramNetworkError`) returns `None` and still
cleans its file.

## T5 — reliable delivery deadlines and operational metrics

### Red evidence (before production-code changes)

```text
tests/test_tg_bridge.py::TestTgReliableDeadlines
3 failed in 1.93s
```

Both never-returning reliable calls held the shared dispatcher until the outer test timeout, so a
later reply could not run. The delivery snapshot also had no queue-age, latency, retry, timeout,
or final-loss fields.

### Green evidence

```text
tests/test_tg_bridge.py::TestTgReliableDeadlines
tests/test_tg_bridge.py::TestTgSendSafe
11 passed in 1.46s

tests/test_tg_bridge.py
83 passed in 2.08s
```

Each reliable Bot API attempt now has a 30-second deadline and the whole retry/rate-limit sequence
has a 75-second deadline. Attempt timeouts retry within the existing three-attempt policy; either
an exhausted attempt budget or the total deadline records one final loss and releases the next
queued reply.

The fixed-size per-chat snapshot now exposes pending age and last/max end-to-end latency for
reliable, telemetry, and optional classes, plus reliable retry/attempt-timeout/total-timeout/loss
counts and best-effort timeout/loss counts. No per-message history or unbounded metric labels are
retained.

Self-review verified that the total deadline includes rate waits and retry sleeps, outer
cancellation is not mistaken for an attempt timeout, and final flood/network/exception paths
increment loss exactly once. Live HTTP cancellation remains unexercised; aiogram's awaited
network operation must honor asyncio cancellation for the deadline to release the dispatcher.

## T6 — bounded mirror isolation

### Red evidence (before production-code changes)

```text
tests/test_tg_bridge.py::TestTgMirrorIsolation
2 failed in 1.65s
```

A blocked mirror send prevented the second primary log from being processed, and a burst of 1,000
mirror copies created 1,000 blocked producer tasks because no outbox or overflow contract existed.

### Green evidence

```text
tests/test_tg_bridge.py::TestTgMirrorIsolation
5 passed in 1.40s

tests/test_tg_bridge.py
88 passed in 1.73s
```

Each orchestrator now owns one 64-entry `asyncio.Queue` and one worker. `stream_logs()` only
performs non-blocking admission; reject-new overflow drops and counts the mirror copy without
moving the primary cursor. The worker submits through the destination chat's shared optional
lane, so mirrors never consume reliable admission capacity and two orchestrators targeting one
chat still share its rate timestamp. Mirrored text, photos, and documents all use this path.

Tests additionally prove that optional saturation cannot reject primary reliable delivery, two
mirror workers preserve the shared per-chat interval, and bridge stop cancels the blocked owner
and clears its outbox.

Self-review found a lifecycle race in the initial implementation: removing an outbox before its
owner had acknowledged cancellation allowed a concurrent producer to create a second owner.
Lifecycle cancellation now marks that orchestrator as stopping, rejects new admission, awaits the
old owner, and only then clears the registry.

## T7 — integration verification and final review

The final adversarial self-review used the repository review checklist across the complete
`dbab279..HEAD` change, not only the last uncommitted slice. It found nine additional edge cases;
all received red-before-fix tests:

- latest coalesced payload preservation through entity fallback;
- safe handling when optional plain-fallback admission is rejected;
- uncertain-state persistence for topic-create network/server errors and cancellation;
- rejection of the first mirror submission racing bridge stop;
- unconditional global cleanup when Bot session close fails;
- final-loss accounting for non-important flood drops;
- uncertain-marker migration and in-flight create serialization during rename.

Focused result after those fixes:

```text
tests/test_tg_bridge.py
97 passed in 1.87s
```

Repository integration result:

```text
UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest -x -q
888 passed, 20 skipped in 65.38s
```

Static/artifact checks:

```text
UV_CACHE_DIR=/tmp/uv-cache uv run python -m py_compile app/tg_bridge.py
git diff --check dbab279
git diff --check
all passed
```

Codex produced no implementation verdict. The first diff review failed with connection refusal on
both transports. The required final retry inspected the code and ran the focused suite, but timed
out after 10 minutes while starting the full suite and wrote no findings/verdict. The exact status,
attempt evidence, and self-review disposition are in `codex-review-impl.md`; no Codex approval is
claimed.

## Compatibility and remaining risk

Public bridge entry-point signatures remain compatible; runtime queue state and diagnostics are
in-memory only. Existing topic/mirror config remains valid, with an additive
`topic_create_uncertain` map used to prevent blind retries of non-idempotent creates.

Tests use deterministic short intervals and cancellation-aware fake Bot calls. Live Telegram was
not contacted, so actual Bot API cancellation latency and the real 3.05-second group-rate cadence
remain the only delivery behavior not exercised end-to-end. The service was not restarted.
