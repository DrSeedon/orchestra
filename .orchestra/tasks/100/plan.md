# #100 — Plan: ordered Telegram images without text stalls

## Decision

Reserve each accepted photo's place with a small one-attempt ordered text message, then
replace that same message using `editMessageMedia` from a separate bounded image worker.
Later text waits only for the small position marker, never for the real file upload/edit.

This is not “make images reliable”: only the marker that establishes chronology uses the
ordered FIFO, and it deliberately does not retry ambiguous delivery. The file operation has
its own queue, timeout, counters, and task owner.

## Fixed behavior

- Image capacity remains a fixed per-chat limit of `_TG_IMAGE_QUEUE_MAX`.
- Admission counts reservations waiting for a marker, queued edits, and the in-flight edit.
- Overflow is reject-new before any marker is sent.
- Markers get one attempt. Acknowledged delivery provides the `message_id`; ambiguous failure
  is counted and not retried, preventing duplicate markers.
- Image edits get one attempt and a dedicated timeout; they do not use reliable retries or
  the main dispatcher.
- Text and image workers atomically reserve starts through one per-chat rate gate and share
  `_tg_flood_until`. The gate is released before the network call, so slow file I/O cannot
  hold text; Telegram-requested flood waits still apply to both.
- A failed edit leaves its ordered text marker as a readable fallback.
- Successful edit replaces the marker in place, preserving `message_id` and history position.
- Accepted Read images use bridge-owned immutable temporary copies.
- Existing reliable, telemetry, mirror, and topic-status policies remain unchanged.

## Files

- `app/tg_bridge.py`
  - add per-chat image reservation/queue/task state and image-specific metrics;
  - add isolated image worker lifecycle;
  - make optional photo submission use marker-then-edit;
  - preserve Read/tool text fallback when admission is rejected.
- `app/routes/tg.py`
  - add `GET /api/tg/delivery-stats`.
- `tests/test_tg_bridge.py`
  - add deterministic queue, failure, overflow, reset, and route tests;
  - update the two existing image-lane tests for edit-in-place semantics.

## Tickets

### T1 — Preserve photo position with an isolated media edit

- Files: `app/tg_bridge.py`, `tests/test_tg_bridge.py`
- Change:
  - extend `_TgDeliveryState` with a bounded image-edit deque, reservation count,
    dispatcher task/event, in-flight item, per-chat rate gate, and `image_*` counters;
  - make state/reset ownership settle queued and in-flight image futures and cancel/await the
    image worker;
  - reserve image capacity before sending any marker;
  - send the marker once through the existing ordered FIFO and capture its `message_id`,
    without reliable ambiguous-error retries;
  - enqueue `InputMediaPhoto(FSInputFile(...), caption=...)` as a one-attempt
    `editMessageMedia` operation owned by the separate image worker;
  - make both dispatchers atomically reserve shared rate starts while never holding the rate
    gate across a Telegram call; propagate `retry_after` to the shared flood window;
  - on marker failure/overload or stopped state, release the reservation and remove the
    generated PNG/Read snapshot immediately because no edit completion will exist;
  - on edit success/failure/timeout/cancellation, settle completion and release exactly one
    reservation;
  - copy accepted Read-image sources to an immutable owned temp path before marker delivery;
  - use the submission result in Read-image handling so rejected images retain the current
    textual fallback;
  - after an edit is queued, keep generated PNG and Read snapshot cleanup attached to its
    actual completion;
  - make every continuation after an `await` mutate only its captured state/reservation;
    worker cleanup unregisters only on matching state/task identity and never looks up a
    replacement state by `chat_id`.
- AC:
  - an event-controlled test records final positions
    `TEXT-1, PHOTO, TEXT-2` after an acknowledged marker when the photo was submitted between
    the two texts;
  - while `editMessageMedia` is held on an unset event, `TEXT-2` completes and the marker
    remains in the middle; no elapsed-time comparison is used;
  - edit failure leaves the marker in the middle, settles completion as failure, increments
    `image_lost`, and does not delay `TEXT-2`;
  - with capacity `2`, the third concurrent image is rejected before a third marker, returns
    unaccepted, and increments `image_dropped` exactly once;
  - placeholder admission failure returns `_ImageSubmission(accepted=False)`, releases its
    reservation, creates no image edit, and increments `image_lost` exactly once; it does not
    increment `image_dropped`, which is reserved for capacity rejection before marker work;
  - an ambiguous marker network error gets one attempt, creates no retry duplicate, releases
    the reservation, and increments image loss;
  - a mocked image `retry_after` updates the shared flood window, while a slow image call does
    not hold the short rate gate;
  - with mocked loop time/sleep, simultaneous text and image contenders reserve distinct rate
    slots: only one obtains the first slot and the other cannot start until the fake clock is
    advanced; no elapsed-time assertion is used;
  - mutating/deleting a Read source after acceptance does not change the bytes owned by the
    queued edit, and cleanup removes the snapshot;
  - reset settles/cancels every image waiter, clears reservations/tasks, and removes generated
    temp files;
  - reset followed immediately by resubmission leaves the replacement state/task/counters
    untouched by the old worker's `finally` path, marker continuation, edit continuation, and
    cleanup callback;
  - existing reliable and telemetry fairness tests remain green;
  - tests use events and mocked failures/timeouts; any `wait_for` is only a hang guard, never a
    performance assertion.
- blocked-by: none

### T2 — Expose delivery queue diagnostics

- Files: `app/tg_bridge.py`, `app/routes/tg.py`, `tests/test_tg_bridge.py`
- Change:
  - include image queue depth/reservations/drops/timeouts/loss/age/latency in
    `_tg_delivery_snapshot`;
  - add a read-only helper returning snapshots for every live chat, sorted for deterministic
    output;
  - expose it as `GET /api/tg/delivery-stats` through the existing authenticated Telegram
    router.
- AC:
  - no live delivery state returns `{"chats": []}`;
  - seeded states for chat ids `-100` and `-200` are returned numerically sorted as
    `[-200, -100]`, regardless of insertion order;
  - each chat includes `optional_dropped`, `reliable_lost`, `optional_oldest_age`, plus the
    exact image schema: `image_reserved`, `image_queued`, `image_in_flight`,
    `image_dropped`, `image_timeouts`, `image_lost`, `image_oldest_age`,
    `image_last_latency`, and `image_max_latency`;
  - endpoint reads state only and does not start dispatchers or mutate counters;
  - overflow from T1 is observable through the endpoint as `image_dropped`;
  - route and bridge tests live in `tests/test_tg_bridge.py`.
- blocked-by: T1

## Verification after implementation

1. Run focused red tests before production changes and record the failing names.
2. Implement T1 and run its focused tests plus the existing queue/image classes.
3. Implement T2 and run its focused route/snapshot tests.
4. Run:

   ```bash
   uv run pytest tests/test_tg_bridge.py -q
   ```

5. Run `git diff --check`.
6. Run mandatory Codex review of the implementation diff; resolve every blocking finding.

No full-suite test lock will be acquired without explicit approval.

## Not in scope

- no changes to topic-icon functions or `app/bg_jobs.py`;
- no changes to reliable/telemetry fairness ratios;
- no retry of real photo edits;
- no new persistent configuration or database schema;
- no dashboard UI;
- no service restart or live Telegram probe;
- no refactor of unrelated `tg_bridge.py` rendering, mirrors, or topic lifecycle.

## Compatibility and rollout

No data migration is required. Runtime queue state resets on the eventual explicit service
restart. The implementation depends on the already deployed Bot API 10.0 and installed
aiogram 3.28.2. If a live edit is rejected despite the documented contract, the ordered
marker remains visible and `image_lost`/logs make the failure diagnosable. If marker delivery
is ambiguous, the system does not retry: this avoids duplicates but may leave one unknown
text marker, an unavoidable Bot API exactly-once limitation.
