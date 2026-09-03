# Phase 2 plan — Telegram bridge reliability polish

Date: 2026-07-25
Input: approved findings in `research.md` and the explicit instruction to proceed through
Phase 2 and Phase 3 without another idle gate.

## Goal and invariants

The bridge must keep user-visible replies moving while retaining bounded, eventually visible
tool activity. The implementation will preserve these invariants:

1. One rate authority owns every Bot API send for a `chat_id`; topics in the same group never
   get independent limiters.
2. Every collection of pending work has a fixed capacity and an explicit full policy.
3. Reliable primary text is FIFO and applies producer backpressure; it is never evicted by
   telemetry or cosmetic work.
4. Tool telemetry is coalesced by `(chat_id, thread_id, agent)` and receives a bounded share of
   send slots after becoming overdue. It never uses the reliable retry path.
5. Topic metadata, topic creation, mirrors, and optional images cannot hold the source stream's
   cursor.
6. Every background task has one lifecycle owner and is cancelled by `stop_bridge()`.
7. Late media completion may resolve only the generation and reservation that created it.

## Fixed policy values

These are constants, not new configuration:

- reliable queue: at most 256 entries per chat plus at most 64 admitted producers waiting for
  capacity; admitted waiters have a hard 5-second deadline, further producers fail immediately
  with a typed overload result and an explicit final-loss counter/log;
- telemetry map: at most 128 topic/agent keys per chat; an update to an existing key coalesces,
  while a new key at capacity is dropped with a loss counter and warning;
- optional best-effort lane: at most 64 entries per chat, physically separate from reliable
  admission; images use at most 16 of those entries and mirror/image saturation can never consume
  a primary reliable slot;
- telemetry eligibility: 15 seconds; once eligible, the oldest pending key gets at least one of
  every four available slots while reliable work continues;
- telemetry Bot API attempt: one attempt, hard 2-second deadline;
- reliable Bot API attempt: hard 30-second deadline; the complete three-attempt operation,
  including retry sleeps but excluding time waiting in the bounded queue, has a 75-second
  deadline;
- topic create and topic metadata attempts: one attempt, hard 5-second deadline;
- detached mirror ingress: at most 64 entries per orchestrator; overflow drops that mirror copy
  with an explicit loss counter and warning, never the primary copy.
- optional image ingress: at most 16 entries per chat with one owned worker; overflow rejects the
  new preview and removes its temp file immediately.

The reliable queue deliberately gives a bounded number of producers short backpressure instead
of creating unlimited `Queue.put()` waiters. Once both admission bounds are exhausted, overload
fails loud rather than hiding an unbounded memory queue. `stream_logs()` retains the current log
cursor on typed admission overload so SQLite remains the durable retry source; direct callers get
an explicit delivery failure. Telegram/network exhaustion after an admitted send retains the
existing final-loss tradeoff and is counted separately.

## TDD protocol

For every ticket, tests are written and run against the pre-fix code first. The red command and
failure names are recorded in the ticket commit message or `report.md`; only then is production
code changed. A ticket is committed immediately after its focused acceptance suite is green.

The six confirmed defects map to mandatory red tests:

| Confirmed defect | Pre-fix red proof |
|---|---|
| strict-priority starvation and unbounded 1,000-tool burst | parametrized 5/20/50 ordering test plus 1,000-event bounded-state test |
| image enqueue reported as delivery success | failed photo delivery must retain textual tool evidence |
| cosmetic startup delay and skipped-window risk | configured stream starts before blocked ensure/status work |
| duplicate/untracked streams and stale debounce timers | new topic gets one owned stream; stop cancels stream/status/debounce owners |
| stale voice/video-note resolver corrupts next batch | old generation completed after timeout cannot overwrite/decrement the new generation |
| awaited mirror stalls later primary logs | blocked mirror does not prevent the source stream from processing its next primary item |

Additional red tests cover reliable call deadlines, runtime status deduplication, all queue
capacities, reset cleanup, and queue-age/counter snapshots.

## Files

- `app/tg_bridge.py` — delivery scheduler state, call wrappers, tool/image integration, topic and
  stream lifecycle, media generation ownership, mirror isolation, diagnostic snapshot.
- `tests/test_tg_bridge.py` — deterministic concurrency and state-machine tests.
- `docs/tasks/polish-tg/codex-review-plan.md` — adversarial review of this plan.
- `docs/tasks/polish-tg/codex-review-impl.md` — cumulative implementation reviews.
- `docs/tasks/polish-tg/report.md` — red/green evidence, commits, tests, remaining tradeoffs.
- `docs/tasks/polish-tg/retro.md` — signal-anchored retrospective.

No broad `tg_bridge` module split is planned. If the scheduler cannot remain understandable as
one state owner inside `tg_bridge.py`, extracting only that owner to `app/tg_delivery.py` is
allowed, but no rendering, handler, topic, or media refactor may hitchhike on the task.

## Tickets

### T1 — Bounded fair tool telemetry through the shared chat rate authority

- Files: `app/tg_bridge.py`, `tests/test_tg_bridge.py`
- Change:
  - replace the unbounded `PriorityQueue` with a bounded reliable FIFO and a capped coalesced
    telemetry map owned by the same per-chat dispatcher;
  - cap reliable admission at 256 queued plus 64 waiting producers; time out admitted waiters,
    reject further arrivals explicitly, and wake/cancel every waiter during reset;
  - give queued items enqueue timestamps and a single dispatcher wake-up mechanism;
  - update `_send_expandable()`/tool call sites to supply the
    `(chat_id, thread_id, orch_name)` coalescing key;
  - render the latest tool activity plus the number of coalesced events;
  - enforce oldest-first 1-in-4 service after the 15-second eligibility threshold;
  - version every telemetry entry; dispatch a snapshot and remove it only if no newer update
    arrived while that snapshot was in flight;
  - enforce the 2-second, one-attempt telemetry call deadline;
  - make reset settle queued, admitted, and in-flight completion futures with a typed stopped
    result before discarding delivery state.
- AC:
  - before the fix, the 5/20/50 test observes the tool after all later reliable calls; after the
    fix and with the eligibility threshold set to zero, telemetry is attempted no later than the
    fourth post-blocker slot in all three cases;
  - before the fix, 1,000 same-key tools produce 1,000 queued futures; after the fix, pending
    telemetry for that key is exactly one and its digest reports `1000` coalesced events;
  - reliable queue size never exceeds 256, admission waiters never exceed 64, the first admitted
    waiter proceeds when capacity is released, and further arrivals fail with the typed overload
    result instead of allocating more internal futures;
  - 1,000 concurrent reliable submissions keep scheduler-owned queue/waiter state within
    `256 + 64`; overflow completes explicitly and reset resolves all admitted waiters;
  - reset settles queued, admitted, and in-flight submissions; no direct caller remains awaiting
    an orphaned completion future;
  - telemetry state never exceeds 128 keys; the 129th new key is dropped and counted;
  - a never-returning telemetry call is cancelled within the configured test deadline, is not
    retried, and the next reliable call runs;
  - an update of the same telemetry key during a blocked send survives completion of the older
    version and is sent on a later eligible slot;
  - one dispatcher per chat remains the only code that updates the chat's rate timestamp;
  - focused T1 tests and all prior queue/retry tests pass.
- blocked-by: none

### T2 — Preserve textual evidence when optional image delivery fails

- Files: `app/tg_bridge.py`, `tests/test_tg_bridge.py`
- Change:
  - add a bounded image ingress inside the shared dispatcher's best-effort lane (16-image subset
    of 64 optional entries, reject-new full policy), separate from reliable admission;
  - return a submission object with `accepted` and an owned completion future so tests/metrics can
    observe actual Telegram completion without `stream_logs()` awaiting it;
  - treat diff/result images as optional previews and always retain the coalesced expandable text
    as durable tool evidence; image completion therefore never decides whether text exists;
  - ensure rejection, timeout, reset, and cancellation all settle completion and remove temp files.
- AC:
  - the pre-fix regression suppresses text after render/enqueue despite a failed send; the fixed
    path always retains text, and the separately awaited image completion reports failure;
  - a failed/timed-out/cancelled/rejected image leaves an expandable textual event pending or
    delivered;
  - every temp path created by the test is absent after success, failure, replacement, and reset;
  - image ingress never exceeds 16 entries and has one worker/completion owner per chat; a
    1,000-image rejection burst creates no unbounded scheduler task/future set.
  - saturated image traffic leaves all 256 reliable slots and 64 reliable admission waiters
    available to primary text.
- blocked-by: T1

### T3 — Start and own streams before bounded cosmetic/topic work

- Files: `app/tg_bridge.py`, `tests/test_tg_bridge.py`
- Change:
  - add an idempotent stream-task registry keyed by `(orch_name, thread_id)`;
  - start every configured stream before `ensure_topics()` or status synchronization;
  - give topic creation a 5-second attempt deadline and idempotently start a stream after a new
    topic is persisted;
  - serialize creation per orchestrator with one in-flight owner; persist an `uncertain` marker
    after an ambiguous create timeout and do not auto-retry that name because Bot API provides no
    idempotency key or topic-list reconciliation;
  - replace awaited startup/runtime status edits with one coalescing background owner per topic;
  - own status tasks, stream tasks, and inbound debounce tasks through stop/start;
  - on topic/orchestrator removal, cancel, await, and remove its stream/status registry entries
    before allowing delete→recreate;
  - make stop/reset cancel and await every dispatcher/stream/status/image/mirror/debounce owner
    before clearing registries or returning;
  - clear buffered inbound state on stop rather than delivering it through a replacement manager.
- AC:
  - the pre-fix ordering test blocks `ensure_topics()`/status and sees no stream; the fixed test
    observes every configured stream first;
  - a topic created during startup or periodic sync has exactly one live stream task;
  - repeated ensure/start calls do not create a second stream for the same key;
  - concurrent `ensure_topics()` calls make at most one create call per orchestrator;
  - an ambiguous create timeout persists the uncertain marker and later sync/restart does not
    create a second remote topic until the mapping is resolved explicitly;
  - a never-returning topic create/status call ends at the configured test deadline and cannot
    delay an already-configured stream or a current log;
  - rapid running→idle→running requests have at most one status worker and apply the latest state;
  - stop cancels and clears stream/status/debounce owners and `_buffers`; restart cannot receive a
    stale inbound batch;
  - delete→recreate cancels and awaits the old owners and starts exactly one new stream;
  - immediately restarting after stop cannot leave an old task sending or mutating the new
    generation's rate/status state;
  - create/rename/delete/status still never enter the reliable message queue.
- blocked-by: T1

### T4 — Generation-safe voice and video-note reservations

- Files: `app/tg_bridge.py`, `tests/test_tg_bridge.py`
- Change:
  - give each `_BufState` a unique process-lifetime epoch object and each reservation a unique
    opaque identity object, never a reusable list index or resettable integer;
  - return an opaque `(epoch, reservation)` token from `_register_media()` and store reservation
    identity with the entry;
  - make `_resolve_media()` a no-op unless the epoch is the current buffer instance and that exact
    reservation is still active;
  - replace the buffer epoch whenever a batch is flushed, timed out, or cleared on stop.
- AC:
  - the pre-fix late-resolver test reproduces `new text -> OLD-VOICE`; after the fix the new text
    is unchanged;
  - when the next generation contains its own reserved voice/video-note, the stale old completion
    neither overwrites its slot nor decrements its `pending_media`;
  - valid voice and video-note completion still preserves original message order and can trigger
    an early flush when the last current-generation media resolves;
  - stop invalidates every outstanding token;
  - stop→restart→new reservation cannot collide with or be resolved by a surviving old token.
- blocked-by: T3

### T5 — Bound reliable delivery attempts and expose delivery health

- Files: `app/tg_bridge.py`, `tests/test_tg_bridge.py`
- Change:
  - wrap each reliable Bot API attempt and the complete retry operation in hard deadlines while
    preserving the documented ambiguous at-least-once retry tradeoff;
  - add a cheap per-chat diagnostic snapshot and structured logs for reliable queue size, oldest
    age, telemetry keys/coalesced/dropped counts, class latency, timeout, and final loss;
  - clear diagnostic live state on reset while retaining no unbounded history.
- AC:
  - a never-returning reliable call releases the dispatcher by the configured total deadline;
  - retries never exceed three attempts or the total deadline, and the following queued reply is
    processed;
  - RetryAfter/network/entity fallback tests still preserve topic ID and rate slots;
  - snapshot values exactly match deterministic queue age/size/coalesce/drop/loss scenarios;
  - diagnostic state has fixed-size scalar fields only, with no per-event history.
- blocked-by: T1

### T6 — Isolate mirror failures without creating unbounded background work

- Files: `app/tg_bridge.py`, `tests/test_tg_bridge.py`
- Change:
  - enqueue streamed mirror copies into one bounded outbox/worker per orchestrator;
  - let the mirror worker use the mirror chat's existing shared rate authority through its
    separate bounded best-effort lane, never through primary reliable admission;
  - never await mirror delivery from `stream_logs()`;
  - cancel and clear mirror workers/outboxes on stop/reset.
- AC:
  - the pre-fix regression blocks mirror delivery and prevents a second primary item; the fixed
    test observes both primary items before releasing the mirror;
  - each outbox has at most 64 entries and one worker; overflow drops only the mirror copy and
    emits/counts an explicit loss;
  - saturated mirror/image best-effort state cannot occupy or reject a primary reliable slot;
  - two orchestrators mirrored to the same chat still share one chat dispatcher/rate timestamp;
  - mirror retry/failure cannot delay primary polling, and stop leaves no mirror task or waiter.
- blocked-by: T1, T5

### T7 — Integration verification and documentation

- Files: `tests/test_tg_bridge.py`, `docs/tasks/polish-tg/codex-review-impl.md`,
  `docs/tasks/polish-tg/report.md`, `docs/tasks/polish-tg/retro.md`
- Change:
  - run the focused bridge suite after every ticket and the repository suite at the end;
  - run cumulative Codex review after each implementation slice, fixing or debating every
    blocking finding before the slice is considered complete;
  - record exact red/green commands, test counts, commits, policy tradeoffs, and review verdicts.
- AC:
  - every confirmed defect is represented by a regression test proven red before its fix;
  - `UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest tests/test_tg_bridge.py -q
    -p no:cacheprovider` passes;
  - `UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest -x -q` passes;
  - final Codex verdict is APPROVED/no blockers;
  - `git diff --check` passes, `git status --short` is empty, and no service restart occurred.
- blocked-by: T2, T3, T4, T5, T6

## Dependency order

`T1 -> T2`
`T1 -> T3 -> T4`
`T1 -> T5 -> T6`
`T2 + T3 + T4 + T5 + T6 -> T7`

The graph is acyclic. T3/T4 and T5/T6 are independent after T1, but implementation remains
sequential in this worktree so every ready slice can be reviewed and committed without overlap.

## What not to touch

- no broad `tg_bridge` four-module refactor;
- no changes to Markdown/UTF-16 splitting, voice transcription vendor logic, TG commands,
  dashboard, database schema, proxy settings, deployment, or VPS;
- no new configuration knobs for fixed safety limits;
- no separate sender for the same `chat_id`;
- no "important" cosmetic/status/image call;
- no service restart.

## Migration and compatibility

There is no persistent-data migration. Existing topic/mirror config remains valid. Runtime
delivery state is intentionally reset when the process eventually restarts under explicit user
control. The optional `topic_create_uncertain` config map is additive and empty by default; it
prevents an ambiguous timed-out `createForumTopic` from being blindly repeated when Telegram
offers no idempotency/reconciliation API. Public bridge entry points remain callable with their
current signatures; only private helpers and their internal result contracts may change.
