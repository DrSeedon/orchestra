# #102 — Telegram delivery priority, expiry, and measured pacing

## Question

- **Context:** outbound traffic in `app/tg_bridge.py` shares one rate authority per
  Telegram chat while reliable text, coalesced telemetry, optional previews, and the
  separate image worker compete for sends.
- **Change under test:** make agent text and visual previews reliable; discard stale
  cosmetic traffic; replace fixed three-second spacing with the fastest pacing that
  the deployed local Bot API and Telegram accept without repeated flood waits.
- **Baseline:** `_TG_GROUP_INTERVAL = 3.05`, reliable traffic always precedes optional
  traffic but overdue telemetry is deliberately inserted after every three reliable
  calls, and queued optional traffic has no age expiry.
- **Outcome:** reliable text and accepted visual previews are never discarded, cosmetic
  work cannot delay them after becoming stale, live throughput improves over the
  baseline, and the first `429 retry_after` makes the sender pause and reduce pressure.

## Hypotheses and falsifiers

### H1 — forum topics have independent send budgets

If topics have independent budgets, alternating otherwise identical `sendMessage`
requests across two topic ids should allow materially more accepted requests before a
429 than sending to one topic.

**Falsifier:** the first 429 depends on the total requests to the shared `chat_id`, not
on the per-topic count.

### H2 — the local Bot API removes or raises Telegram's group-send ceiling

If the local server owns the ceiling, the deployed `localhost:8081` endpoint should
accept sustained group traffic above Telegram's documented public Bot API limit without
returning 429.

**Falsifier:** the local endpoint returns Telegram `retry_after` flood responses at the
same chat-wide scale, or the local-server primary sources say flood limits remain
server-side.

### H3 — fixed spacing, rather than queue capacity, dominates observed latency

If fixed spacing dominates, a queue well below its capacity can still reach tens of
seconds of age, and stale telemetry/optional calls consume scarce send slots.

**Falsifier:** observed latency correlates with queue saturation or reliable admission
overflow instead.

### H4 — reliable text and previews can share retry semantics safely

If all user-defined important payloads use the reliable lane (or an equally reliable
isolated image lane), telemetry and cosmetics can expire without losing agent text or
visual evidence.

**Falsifier:** any Read image or generated diff/result preview remains on a one-attempt,
bounded-drop path, or promoting it can block text behind media I/O.

## Experiment protocol (fixed before measurement)

The live probe targets the deployed local Bot API and existing forum topics. It does not
restart or patch the running service.

- **Metric:** accepted `sendMessage` responses before the first HTTP/Bot API 429,
  request start/finish timestamps, topic id, and returned `retry_after`.
- **Safety stop:** abort before sending if the live delivery snapshot has reliable work
  or an image in flight; stop immediately on the first 429 or non-429 error.
- **Topic test:** alternate requests between two existing idle topics in the same group.
  A chat-wide 429 after the combined count falsifies independent topic budgets.
- **Cleanup:** bulk-delete every accepted probe message through `deleteMessages`.
- **Pass condition for a faster burst:** at least three consecutive requests 1.05 seconds
  apart succeed with no 429. This supports 1.05-second burst pacing only; it does not
  override a minute-scale group cap.
- **No-go condition:** any 429 below the candidate rate, or a documented/live shared
  group cap, forbids treating that candidate as a safe sustained interval.

Raw measurements and final findings will be appended after the probe.

### Protocol amendment after the first run

The first run waited 600 seconds and aborted without sending anything because the live
delivery state never remained empty and unchanged for 65 consecutive seconds. This
refutes the practical assumption that production provides a clean minute-long window.

The candidate, sample size, gaps, topic alternation, error stop, and cleanup remain
unchanged. The second run records the starting live snapshot and sends the same maximum
of three requests under actual load, stopping on the first 429/error. Its pass condition
is still all three requests accepted at 1.05-second gaps. This amendment measures the
requested production condition rather than weakening the numerical success criterion.

## Findings

### F1 — the local Bot API does not provide a higher message-send ceiling

The deployed server is `telegram-bot-api 10.0`, launched with `--local` on port
8081 (direct `systemctl show` and binary-version measurement). Telegram's local-server
documentation lists the behavior changed by local mode: file sizes and paths, webhook
addresses/ports/connections, and local `file_path`; it does not list relaxed flood
limits [2][3]. Telegram's own FAQ still defines the upstream limits as approximately
one message per second in one chat and no more than 20 messages per minute in a group
[1].

The production journal independently recorded seven 429 responses through the local
server in 45 minutes, with `retry_after` values `16, 9, 11, 12, 3, 10, 11` seconds.
Therefore localhost removes the HTTP/network hop and raises file limits, but does not
remove Telegram's upstream flood control.

**Confidence: CONFIRMED** — two primary Telegram sources plus direct deployed-version
and live-429 measurements.

### F2 — the current delay is not queue-capacity pressure

The complaint-time live snapshot measured:

```text
reliable_queued=2
reliable_lost=0
optional_dropped=0
reliable_max_latency=57.828s
telemetry_max_latency=61.063s
telemetry_coalesced=37
```

A second read during research measured one reliable item, three telemetry items, no
optional items, two image reservations, and one image in flight; counters still showed
zero reliable loss/overflow. These depths are far below the configured reliable
capacity of 256 and optional capacity of 64 [4]. The delay therefore occurs before
capacity pressure: fixed rate admission and Telegram flood waits serialize a small
backlog into tens of seconds.

**Confidence: CONFIRMED** — two live snapshots plus direct configured capacities.

### F3 — the current priority classification contradicts the requested one

Direct call-site inspection found:

| Payload | Current path | Requested path |
|---|---|---|
| agent `text` log | reliable, `important=True` | reliable; unchanged |
| explicit `/api/tg/send_file` attachment | reliable, retries | reliable; unchanged |
| actual image returned by `Read` | isolated image lane, `important=False` | isolated but reliable/retried |
| generated Edit/Write/Read diff/result PNG | isolated image lane, `important=False` | isolated but reliable/retried |
| ordinary tool/tool-result expandable | coalesced telemetry | expiring cosmetic; unchanged class |
| pretty `send_message` tool call | reliable, `important=True` | expiring cosmetic |
| status/subagent cosmetics | coalesced telemetry | expiring cosmetic |
| mirror copies | bounded best-effort outbox | optional/expiring; unchanged |

The isolated image lane created in #100 is the correct network execution owner for
previews because a slow `editMessageMedia` there does not retain the text dispatcher.
Its producer handoff is not isolated yet: `stream_logs` awaits marker admission inline,
preview helpers swallow generic failure, items use one attempt, and new previews are
rejected after 16 reservations [4][5]. Waiting for capacity would block later log/text
processing; returning `False` advances the stream cursor and loses the preview.

Important previews therefore need a nonblocking owned handoff before the helper returns:
snapshot the file, enqueue the ordered marker and its continuation into bridge-owned
state, then return without awaiting marker/network completion. The existing capacity
limit remains for optional/mirror images; admitted important preview metadata and
bridge-owned temp files must queue without the optional reject-new path. If reliable
marker admission itself cannot be owned, raise `_TgDeliveryOverloaded` unswallowed so
`stream_logs` retains its cursor. Merely changing previews to the main reliable network
dispatcher would restore retries but regress text latency by awaiting media I/O there.

**Confidence: CONFIRMED** — direct source and call-site inspection, corroborated by the
deterministic #100 image-lane tests.

### F4 — `_TG_TELEMETRY_MAX_AGE` is currently a send delay, not an expiry

`_tg_oldest_telemetry()` selects telemetry only after its age reaches 15 seconds.
`_tg_pick_next()` then deliberately inserts that aged telemetry after every three
reliable calls. No branch drops it for age. Optional deque items likewise have no age
check [4]. This exactly permits the observed 61-second telemetry latency: an obsolete
item eventually consumes a scarce send slot instead of being discarded.

Expiry can use the existing measured/configured 15-second boundary without inventing a
new tuned duration: settle stale cosmetic futures with `None`, increment the existing
`telemetry_dropped` or `optional_dropped`, and let the already deployed stats endpoint
expose those counters. Fresh telemetry may run only when no reliable item is ready;
the current “one telemetry after three reliable” fairness rule conflicts with the new
priority contract and must go.

**Confidence: CONFIRMED** — direct control-flow inspection plus the live age/counter
measurements.

### F5 — a faster fixed sustained interval would make flood waits worse

`3.05s` corresponds to 19.67 sends/minute, already just under Telegram's documented
20/minute group ceiling [1][4]. Changing it to 1.05 seconds without a minute-scale guard
would attempt 57.14/minute and necessarily turn normal load into repeated 429 pauses.

The safe shape is two-dimensional:

1. exactly 1.05-second minimum spacing permits the measured short-chat burst and reduces
   latency for text after idle time;
2. a shared 20-reservation/60-second rolling window preserves the tracked delivery
   ceiling across all topics because state is keyed by `chat_id`, not
   `message_thread_id`;
3. cosmetic traffic that cannot reserve immediately is dropped instead of sleeping in
   the dispatcher;
4. important traffic waits; the first 429 extends the existing shared
   `_tg_flood_until`, and the rejected reservation remains counted conservatively.

This is a burst-speed increase, not a claim that Telegram permits more than 20 sustained
group messages per minute.

The current `_TG_RELIABLE_TOTAL_TIMEOUT=75s` wraps rate admission, flood wait, active
network calls, and retry delays. A full burst can legitimately make request 21 wait
about 40 seconds; one 30-second call timeout can then consume the remaining total
deadline and falsely count an important message lost. Rate/flood admission must not
consume an active-call deadline. The simplest bounded contract is to remove the outer
75-second delivery deadline, keep each active attempt under its existing call timeout,
and keep the finite three-attempt policy. Important rate waits remain lossless rather
than expiring inside the queue.

The corrected live probe then started three requests at offsets
`0.0531, 1.1043, 2.1546s`, i.e. gaps of `1.0513s` and `1.0503s`. All three returned
HTTP 200 through `localhost:8081`; they alternated topic slots `1, 2, 1`, and bulk
cleanup returned HTTP 200. This proves a three-message 1.05-second burst for the deployed
bot under real load. It does not supersede the 20/minute sustained ceiling.

**Confidence: CONFIRMED for a three-message 1.05-second burst; CONFIRMED for the
20/minute documented sustained ceiling** — direct live measurement plus primary
Telegram documentation.

### F6 — a literal “never lose a photo” guarantee is impossible after an ambiguous response

The #100 implementation intentionally gives the ordered marker one attempt. If Telegram
accepts it but a timeout/network/server response is lost, retrying may create a duplicate
marker; without the returned `message_id`, the bridge cannot know which message to turn
into a photo [5]. An explicit `TelegramRetryAfter`, however, is an unambiguous rejection:
the marker was not accepted and is safe to retry after the shared flood wait.

The marker therefore needs selective semantics: `important=True` for admission and
explicit 429 retry, but `retry_ambiguous=False` for timeout/network/server failures.
Media edits retry timeout/network/429, and “message is not modified” after an ambiguous
successful edit is treated as success. The Bot API still has no idempotency key for the
marker.

The implementable contract is: accepted previews are handed to owned state before the
stream cursor advances, are never deliberately expired or rejected by the cosmetic
lane, marker 429s retry, media edits retry timeout/network/429, all terminal failures
are counted, and the ambiguous-marker boundary remains explicit.

**Confidence: CONFIRMED** — direct state-machine analysis already adversarially reviewed
in #100; no exactly-once primitive exists in the used call path.

### F7 — low delivery concurrency is safe; startup-scale concurrency is not

#99 measured the old startup path scheduling about 30 `editForumTopic` mutations
concurrently. Seventeen timed out at `+4.989…+4.992s` and one more at `+9.991s` under
the five-second outer timeout; the empty log text was `TimeoutError()` [7]. This proves
the deployed local Bot API/proxy channel can be saturated by high fan-out.

The bounded #102 probe started three `sendMessage` requests within `6.3ms`. All returned
HTTP 200 in `0.2961s`, `0.5403s`, and `0.3099s`; bulk cleanup succeeded, and total wall
duration was `0.9244s` [8]. The current primary delivery architecture has at most one
main dispatcher and one image dispatcher awaiting network work for the chat. Keeping
that two-worker structure while staggering starts through the shared rate authority is
within the measured low-concurrency envelope; adding an image pool is not justified.

**Confidence: CONFIRMED for three concurrent small sends and REFUTED for roughly 30
concurrent topic mutations; UNCERTAIN for concurrent uploads** — two direct live
measurements with different request kinds.

## Counter-evidence and limits

- Telegram says short bursts above one message/second “may” be allowed, not that a
  particular burst size is guaranteed [1]. The implementation must use the measured
  1.05-second candidate, not an unmeasured 1.00-second or zero-delay burst.
- The primary docs express the limit for a group, while `message_thread_id` identifies a
  topic inside the same supergroup [3]. This strongly argues against per-topic budgets,
  but the safe three-message probe cannot force a 429 merely to prove the boundary.
- Topic-icon operations execute outside the delivery rate authority. #99 now serializes
  their startup fan-out, but their exact relationship to the documented 20-message
  budget is unmeasured. Another worker owns those functions; #102 must not edit them.
  The 20/60 window is therefore a tracked-delivery ceiling, not a system-wide Bot API
  guarantee. Reserving an arbitrary 18/20 or 19/20 headroom would violate the task's
  measure-don't-guess rule; a delivery 429 still extends the shared flood pause.
- A rolling window improves burst latency but cannot increase sustained upstream capacity.
  The user-visible gain must be reported as burst throughput and reliable latency, not as
  a fictional sustained messages/minute increase.

## Affected files, risks, and edge cases

- `app/tg_bridge.py`
  - delivery constants/state and cleanup;
- `_tg_rate_wait`, `_tg_reserve_rate_slot`, `_tg_run_attempts`;
  - `_tg_pick_next`, `_tg_dispatch_chat`, `_tg_dispatch_images`;
  - preview submission and stream-log classification call sites.
- `app/routes/tg.py`
  - no route behavior is expected to change; the existing endpoint already exposes the
    counters. Touch only if the final snapshot schema needs an observed-rate field.
- `tests/test_tg_bridge.py`
  - deterministic fake-clock rate/window/backoff tests;
  - stale cosmetic drop/counter tests;
  - image retry and classification tests.

Risks:

- counting too few request kinds permits 429; counting rejected/ambiguous reservations is
  conservative and safer;
- retrying media edits after an ambiguous success can return “message is not modified,”
  which must be normalized as success;
- important preview admission must complete an owned nonblocking handoff before the
  stream cursor advances; optional images remain bounded/reject-new;
- rate/flood waits must remain outside active call deadlines;
- ordered markers retry explicit 429 but never ambiguous timeout/network/server errors;
- reset/replacement-state cleanup must clear new history without mutating a replacement
  state;
- no #102 edit may touch `_topic_status*`, `_any_running_in_scope`,
  `_sync_all_topic_statuses`, or `_update_topic_status`.

## Sources

1. [Telegram Bots FAQ — flood limits](https://core.telegram.org/bots/faq) —
   **primary source**, opened 2026-07-29.
2. [TDLib local Telegram Bot API README](https://github.com/tdlib/telegram-bot-api) —
   **primary source**, opened 2026-07-29.
3. [Telegram Bot API — local server and forum-topic parameters](https://core.telegram.org/bots/api) —
   **primary source**, opened 2026-07-29.
4. `app/tg_bridge.py` at `7e0b4af` — **primary source code**, inspected 2026-07-29.
5. `docs/tasks/100/research.md` and `docs/tasks/100/report.md` —
   **direct prior measurements and implementation evidence**, inspected 2026-07-29.
6. `GET /api/tg/delivery-stats` and `journalctl -u orchestra` on the deployed service —
   **direct live measurements**, 2026-07-29.
7. `docs/tasks/99/report.md` — **direct live timeout/concurrency measurements**,
   inspected after merge `7e0b4af`.
8. `docs/tasks/102/concurrency-experiment.md` and
   `/tmp/tg-probe-102-concurrency.json` — **direct live measurement**, 2026-07-29.

## Raw experiment results

### Run 0 — quiet-window prerequisite

```json
{
  "waited_seconds": 600,
  "requests_sent": 0,
  "result": "aborted: no 65-second stable empty delivery window"
}
```

### Run 1 — script-timing validation

All three requests succeeded and were deleted, but starts were separated by
`1.4108s` and `1.5694s` because the script slept after each response. This run is
retained as evidence but does not validate a 1.05-second start interval.

### Run 2 — corrected fixed-start schedule

Starting snapshot:

```json
{
  "reliable_queued": 0,
  "telemetry_pending": 0,
  "optional_queued": 0,
  "image_reserved": 0,
  "image_in_flight": 0
}
```

Requests:

| # | Topic slot | Start offset | Duration | Result |
|---|---:|---:|---:|---|
| 1 | 1 | 0.0531s | 0.1753s | HTTP 200 |
| 2 | 2 | 1.1043s | 0.1682s | HTTP 200 |
| 3 | 1 | 2.1546s | 0.1689s | HTTP 200 |

Measured start gaps: `1.0513s`, `1.0503s`. Cleanup: three message ids,
`deleteMessages` HTTP 200.

Raw outputs are retained in `/tmp/tg-probe-102.json`,
`/tmp/tg-probe-102-live.json`, and `/tmp/tg-probe-102-live-corrected.json`.

## Hypothesis outcomes

- **H1 (per-topic budgets): UNCERTAIN / not used for design.** Alternating topics accepted
  the measured short burst, but the safe probe did not force a boundary. Primary docs
  specify a group/chat limit, so implementation remains chat-wide.
- **H2 (local server raises send ceiling): REFUTED.** The local server returned seven
  upstream 429s in the measured 45-minute window, and local-mode primary docs list no
  flood-limit change.
- **H3 (pacing dominates capacity): CONFIRMED.** Tens-of-seconds latency occurred with
  queues far below capacity and no reliable overflow/loss.
- **H4 (current reliable classification matches the request): REFUTED.** Read/diff/result
  previews are currently one-attempt/drop-bounded, while a cosmetic `send_message` tool
  event is reliable.
