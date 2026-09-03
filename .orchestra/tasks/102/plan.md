# #102 — Implementation plan

## Approach

Keep the existing per-chat delivery ownership and change only three contracts:

1. reliable agent text always outranks fresh cosmetics; stale cosmetics are settled and
   counted instead of sent;
2. Read/diff/result previews stay on the isolated image worker but use reliable media
   retries and backpressure rather than the optional reject-new policy;
3. group pacing permits the measured 1.05-second burst while enforcing Telegram's
   documented 20-message/60-second chat-wide window and honoring the first
   `retry_after`.

The tracked delivery ceiling is shared by topic ids because it is stored under `chat_id`.
Nonimportant traffic never sleeps for a future rate slot: if no slot is immediately
available, it is dropped and its existing counter increments. Important traffic waits
under the shared lock, so text and image workers cannot reserve the same slot.

Concurrency is not increased. The primary chat keeps one text dispatcher plus one
image dispatcher; the shared rate authority staggers their starts. This is below the
measured safe probe of three simultaneous small sends and avoids the #99 failure mode
where roughly 30 concurrent topic edits produced 18 five-second timeouts.

## Files and symbols

- `app/tg_bridge.py`
  - constants and `_TgDeliveryState`;
  - cleanup/snapshot-adjacent rate history;
  - `_tg_rate_wait`, `_tg_reserve_rate_slot`, `_tg_run_attempts`;
  - `_tg_oldest_telemetry`, `_tg_next_telemetry_wait`, `_tg_pick_next`,
    `_tg_dispatch_chat`;
  - `_tg_dispatch_images`, `_tg_send_optional_photo`, `_tg_send_file_safe`,
    `_send_png_to_tg`;
  - stream-log call sites for Read images, generated previews, and the pretty
    `send_message` tool call.
- `tests/test_tg_bridge.py`
  - focused delivery classification, expiry, retry, rolling-window, and 429 tests.
- `app/routes/tg.py`
  - expected unchanged: `GET /api/tg/delivery-stats` already returns the drop counters.

## What not to touch

- `_topic_status*`, `_any_running_in_scope`, `_sync_all_topic_statuses`,
  `_update_topic_status`, or their tests: task #99 T2 owns them concurrently.
- mirror architecture, stream polling, Bot API deployment, environment/configuration,
  and unrelated Telegram handlers.
- no server restart; only the orchestrator/user decides when Python changes go live.

## Test method

Production behavior is written against deterministic event and fake-clock tests. New
tests do not assert elapsed wall time:

- construct queue items with controlled `enqueued_at`;
- call selection/rate functions with explicit fake `now`;
- monkeypatch `asyncio.sleep` to advance a fake loop for 429/retry sequencing;
- use events only to prove causal ordering (cosmetic held, text selected/completed,
  image edit held, later text completes).

Required final command:

```text
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_tg_bridge.py -q
```

## Tickets

### T1 — Enforce reliable-text priority and expire cosmetics

- Files: `app/tg_bridge.py`, `tests/test_tg_bridge.py`
- Change:
  - treat the existing 15-second telemetry age as an expiry boundary rather than a
    fairness trigger;
  - prune stale telemetry and optional entries before selection, settle their futures
    with `None`, and increment `telemetry_dropped` / `optional_dropped`;
  - remove the “one telemetry after three reliable” preemption rule while preserving
    the ordered-marker sequence barrier for fresh preceding telemetry;
  - route the specially formatted `send_message` tool event as coalesced cosmetic
    telemetry instead of `important=True`;
  - leave agent `text` and explicit attachments reliable.
- AC:
  - queued agent text is selected before every non-ordered cosmetic entry;
  - telemetry/optional entries at or beyond 15 seconds are not sent, their futures
    settle to `None`, and the matching dropped counter increments exactly once;
  - `GET /api/tg/delivery-stats` exposes the incremented existing counters without
    starting a dispatcher or mutating state;
  - a pretty `send_message` tool call cannot enter the reliable deque;
  - all new age/priority tests use controlled clocks/events, not elapsed-time asserts.
- blocked-by: none

### T2 — Make visual previews reliable without moving media onto the text worker

- Files: `app/tg_bridge.py`, `tests/test_tg_bridge.py`
- Change:
  - submit actual Read images and generated Edit/Write/Read preview PNGs as important
    image work while retaining marker + isolated `editMessageMedia`;
  - make the isolated-photo helper accept reliable versus optional semantics, and have
    `_tg_send_file_safe` select it for both nonimportant mirror photos and explicitly
    marked important previews; explicit `/api/tg/send_file` photos keep their current
    synchronous reliable contract;
  - snapshot and hand important previews to bridge-owned state before returning to
    `stream_logs`; enqueue the ordered marker without awaiting its network result, and
    let an owned continuation queue the isolated media edit after marker success;
  - keep the existing bounded reject-new capacity only for optional/mirror images;
    important preview metadata/temp files do not use the optional capacity drop path;
  - propagate `_TgDeliveryOverloaded` from important preview admission so the stream
    cursor is retained; do not convert admission failure to `False`;
  - run media edits with reliable attempts and shared 429 admission; normalize
    “message is not modified” after an ambiguous successful edit as success;
  - give the ordered marker selective retry: retry explicit `TelegramRetryAfter`, but
    do not retry timeout/network/server errors whose delivery result is ambiguous;
  - preserve immutable snapshots, cancellation shielding, state-identity cleanup, and
    text progress while an edit is held.
- AC:
  - Read image and generated diff/result call sites create image items with reliable
    retry semantics;
  - a first network error or 429 on `editMessageMedia` is followed by a rate-gated retry
    and eventual success without incrementing `image_lost`;
  - an important preview returns to `stream_logs` only after an owned snapshot, marker
    item, and completion continuation exist; marker/network completion is not awaited;
  - filling optional image capacity does not reject or block an important preview;
  - an injected reliable admission failure escapes as `_TgDeliveryOverloaded`, causing
    the stream cursor to retain the log instead of silently advancing;
  - holding media edit I/O does not prevent later agent text from completing;
  - reset/cancellation removes every owned temporary snapshot and settles waiters once;
  - marker 429 retries only after `retry_after + margin`; an ambiguous marker timeout or
    network/server error makes exactly one attempt, is counted, and does not duplicate.
- blocked-by: T1

### T3 — Replace fixed group pacing with measured burst plus rolling ceiling

- Files: `app/tg_bridge.py`, `tests/test_tg_bridge.py`
- Change:
  - lower burst spacing from 3.05 seconds to the exact live-proven 1.05 seconds;
  - add a per-chat deque of reserved request timestamps and cap group traffic at
    20 reservations in a rolling 60-second window;
  - count every attempt, including ambiguous/rejected attempts, conservatively;
  - make nonimportant attempts drop immediately when flood/spacing/window admission
    would wait; important attempts sleep and recheck under the existing per-chat lock;
  - remove the outer 75-second reliable delivery timeout so legitimate rate/flood waits
    cannot consume the network-attempt deadline; retain the existing per-attempt timeout
    and finite three-attempt policy;
  - on the first 429, extend `_tg_flood_until` by `retry_after + margin`; the next
    important attempt cannot start before that point and the sender retains its
    minute-window debt;
  - retain exactly one main dispatcher and one image dispatcher per chat; do not add
    request fan-out or a larger media worker pool;
  - clear rate history only with the owning chat state/reset.
- AC:
  - three group sends can reserve at 1.05-second spacing after an idle window, versus
    3.05 seconds before (2.90× burst throughput);
  - request 21 in the same synthetic 60-second group window waits until the oldest
    reservation expires and is not counted lost by the removed 75-second wrapper;
  - calls to two different topic ids in one group consume the same chat budget;
  - a cosmetic call facing any positive rate wait is dropped/counted without calling
    Bot API, while queued reliable text remains deliverable;
  - after a synthetic 429, no retry starts before `retry_after + margin`, and only one
    retry proceeds when the fake clock advances;
  - a 40-second rolling-window wait followed by a 30-second active-call timeout still
    receives its configured retry instead of incrementing `reliable_total_timeouts`;
  - different `chat_id` values remain independent;
  - controlled events prove at most one main call and one image call can be in flight
    for a chat; no new delivery path creates a third concurrent call;
  - no new test uses real elapsed-time thresholds.
- blocked-by: T1, T2

## Migration and rollback

No database/config migration. All delivery/rate state remains in memory and resets on
service restart.

Rollback is one code revert. The observable behavior change is intentional: stale
cosmetic futures resolve to `None`, and fresh cosmetics may be discarded immediately
when the chat has no current rate slot. Reliable text and accepted previews retain
retry/loss counters. The `reliable_total_timeouts` stats field remains for response-shape
compatibility but no longer expires calls while they wait for Telegram rate admission.
