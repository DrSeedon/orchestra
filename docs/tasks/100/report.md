# #100 — Implementation report

## Outcome

Telegram photos now reserve their history position with a one-attempt text marker and replace
that marker asynchronously through `editMessageMedia`. The image upload has a separate bounded
worker, so a slow or failed file request cannot retain the main text dispatcher.

The marker participates in a sequence barrier across pending admission, the reliable queue, and
the in-flight call. Telemetry admitted before the marker is drained before it; telemetry admitted
after it cannot pass through reliable fairness or coalesce across the marker. A cancelled queued
marker releases the barrier, while a cancelled in-flight marker retains it because Telegram may
already have committed the request.

## Tickets

### T1 — Preserve photo position with an isolated media edit

Completed in `app/tg_bridge.py` and `tests/test_tg_bridge.py`.

- `_TgDeliveryState` owns image reservations, a bounded edit deque, an isolated dispatcher,
  image counters, and a shared atomic rate-slot lock.
- `_tg_send_optional_photo` snapshots the source before asynchronous work, sends one ordered
  marker attempt, then queues a one-attempt `editMessageMedia`.
- The text and image workers share `_tg_flood_until`, but neither holds the rate lock during a
  Telegram network call.
- Reset, replacement-state, caller-cancellation, marker failure, edit failure, timeout, and
  temporary-file cleanup paths settle against their captured state.
- Reject-new overflow happens before a marker and increments `image_dropped`; marker/edit
  failures increment `image_lost`.

### T2 — Expose delivery queue diagnostics

Completed in `app/tg_bridge.py`, `app/routes/tg.py`, and `tests/test_tg_bridge.py`.

- `GET /api/tg/delivery-stats` returns all live per-chat snapshots in numeric `chat_id` order.
- The response includes the existing reliable/telemetry/optional metrics and the exact
  `image_*` reservation, queue, timeout, loss, age, and latency schema.
- The endpoint is read-only and uses the existing authenticated Telegram router.

## Files

- `app/tg_bridge.py`: +476/-107 lines; delivery state, sequencing barrier, rate gate, image
  worker, marker/edit submission, cleanup, and snapshots.
- `app/routes/tg.py`: +6/-0 lines; read-only delivery-stats route.
- `tests/test_tg_bridge.py`: +720/-20 lines; deterministic ordering, admission, cancellation,
  lifecycle, rate, overflow, statistics, and fallback coverage.
- `docs/tasks/100/`: research, plan, three Codex review artifacts, and this report.

Topic-status functions, `app/bg_jobs.py`, `app/mcp_stdio.py`, and `docs/tasks/99/` were not
edited by this task.

## Verification

Tests were defined before production changes:

- T1 image-lane selection: 8 failures against the old delivery implementation.
- T2 delivery-stats selection: 2 failures before the endpoint existed.

Final required command:

```text
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_tg_bridge.py -q
........................................................................ [ 63%]
.........................................                                [100%]
113 passed in 2.97s
```

The final output is retained in `/tmp/pytest-100.log`. `git diff --check` passed. The full
project suite was not run because it requires the global test lock and was explicitly excluded.

The mandatory adversarial implementation review is in `codex-review-impl.md`. Its five rounds
found and drove fixes for:

1. telemetry bypassing a marker;
2. concurrent stale-state replacement;
3. snapshot and rendered-PNG cancellation cleanup;
4. marker barriers during admission, backlog, coalescing, and consecutive markers;
5. cancelled queued markers retaining fairness unnecessarily.

Final review verdict:

```text
Approved. Ordering, cancellation lifecycle, coalescing, fairness, cleanup, counters,
and pending/queued/in-flight transitions satisfy the stated MVP acceptance criteria.
```

Codex independently ran the same target after the final change: `113 passed in 2.26s`.

## Self-review

Three weak points found during implementation were corrected before handoff:

- the shared rate reservation now rechecks a newly extended flood window after every mocked
  sleep instead of assuming the first wait remains authoritative;
- every continuation and cleanup owns its captured state, so reset followed by resubmission
  cannot mutate the replacement;
- consumer cancellation is shielded from the raw image completion, so it cannot remove a
  snapshot while `editMessageMedia` still uses it.

## Compatibility and remaining boundary

No migration or configuration change is required. Queue statistics are in-memory and reset with
the service.

The ordering guarantee starts after Telegram acknowledges the marker and returns its
`message_id`. An ambiguous marker response is deliberately not retried because Bot API does not
provide exactly-once delivery; this can leave one unknown marker, but avoids duplicate position
messages. A failed media edit leaves the acknowledged text marker as the readable fallback.

## Commits

- `ece5ad6` — research and approved plan artifacts;
- `0ae0240` — T1 ordered marker and isolated image worker;
- `86dfa35` — T2 delivery statistics endpoint;
- `8f3f4f2` — adversarial-review concurrency and lifecycle fixes.
