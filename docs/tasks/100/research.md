# #100 — Telegram image chronology

## Question

- **Context:** outbound Telegram delivery in `app/tg_bridge.py`, where one per-chat
  dispatcher owns reliable text, coalesced telemetry, and optional media.
- **Change under test:** preserve the position of a photo relative to surrounding text
  without letting the photo upload/edit occupy the reliable text worker.
- **Baseline:** the current strict lane priority (`reliable`, then `optional`) and the
  current single dispatcher for both lanes.
- **Outcome:** after the position marker is acknowledged, for
  `TEXT-1 -> PHOTO -> TEXT-2` the final Telegram history is
  `TEXT-1 -> PHOTO -> TEXT-2`; a photo operation held indefinitely does not prevent
  `TEXT-2` from completing; overflow is bounded, deterministic, counted, and exposed
  through a read-only API. Ambiguous marker delivery has an explicit degraded contract
  because Bot API sends are not exactly-once.

## Hypotheses considered

### H1 — fair or globally sequenced admission is enough

**Claim:** starting a photo request at its source position and allowing later text to use
another execution lane preserves final Telegram order without blocking text.

**Falsifier:** Telegram may process parallel requests out of order, or a deterministic
slow-photo probe lets the later text finish before the photo has obtained a stable message
position.

**Result:** **REFUTED.** A sequence number can order local starts, but it cannot order the
server's completion of concurrent Bot API requests.

### H2 — sending photos as reliable items fixes both requirements

**Claim:** putting the real `sendPhoto` in reliable FIFO preserves chronology and remains
safe because the queue is bounded.

**Falsifier:** a slow or failed `sendPhoto` holds the sole dispatcher and prevents later
reliable text from starting.

**Result:** **REFUTED.** The current single-dispatcher probe reproduced exactly that
blocking, and this reintroduces the prior lock/retry-path failure mode.

### H3 — reserve a message position, then replace it asynchronously

**Claim:** send a small text placeholder through the ordered reliable lane, then replace
that same message with the photo through a separate bounded, one-attempt media-edit worker.
The placeholder fixes the history position; the real file operation no longer owns the text
dispatcher.

**Falsifier:** the deployed Bot API cannot replace text with media; aiogram cannot upload
an `InputMediaPhoto` in `editMessageMedia`; or the later text still waits for the edit.

**Result:** **SUPPORTED for acknowledged marker delivery.** The local server reports Bot
API 10.0, the installed aiogram 3.28.2 exposes `Bot.edit_message_media`, the official API
explicitly permits replacing a text message with media, and the event-controlled prototype
completed later text while the media edit was held. Telegram does not provide exactly-once
Bot API sends, so an ambiguous marker response cannot support an absolute guarantee.

## Findings

### F1 — current lane selection deterministically moves a photo behind later text

`_tg_pick_next()` chooses `state.reliable.popleft()` before it examines
`state.optional`. `_tg_send_file_safe(..., is_photo=True, important=False)` enters the
optional queue with `best_effort=True`, while streamed agent text uses `important=True`.
The producer gets an optional future immediately, so it can enqueue the later reliable text
before the dispatcher selects its next item.

Measured against the current code with rate delay set to zero:

```text
ordering ['TEXT-1', 'TEXT-2', 'IMAGE']
```

**Confidence: CONFIRMED** — direct source inspection plus deterministic execution of the
current functions.

### F2 — a started optional photo blocks reliable text today

All three traffic classes are awaited inside `_tg_dispatch_chat()`. Once an optional photo
is selected, the dispatcher cannot select any later reliable item until the photo returns,
fails, or reaches `_TG_TELEMETRY_CALL_TIMEOUT`.

Measured with an event-held `bot.send_photo`:

```text
blocked_before_release True ['IMAGE-start']
after_release ['IMAGE-start', 'IMAGE-end', 'TEXT-AFTER']
```

No elapsed-time threshold was used; the assertion is causal: the text-start event remained
unset until the photo release event.

**Confidence: CONFIRMED** — direct source inspection plus deterministic event ordering.

### F3 — concurrent real sends cannot provide strict server-side order

Telegram's primary API documentation says parallel requests are processed in arbitrary
order and provides dependency wrappers for clients that need ordered processing [1].
The HTTP Bot API surface used here does not expose those MTProto dependency wrappers.
Therefore “start the photo first, do not await it, then send text” cannot prove the final
history order.

**Confidence: LIKELY** — primary Telegram ordering semantics and absence of an ordering
primitive in the Bot API interface; not exercised against the live production group.

### F4 — Bot API 10.0 can reserve a position with text and later turn it into a photo

The official Bot API says `editMessageMedia` can replace a text message with media and
accepts an `InputMedia` upload for a non-inline message [2]. The installed aiogram API
exposes `Bot.edit_message_media(media, chat_id, message_id, ...)` and
`InputMediaPhoto.media` accepts an uploaded input file [3][4].

Local compatibility measurements:

```text
Bot API 10.0
aiogram 3.28.2
(self, media, ..., chat_id=None, message_id=None, ..., request_timeout=None)
```

**Confidence: CONFIRMED** — two primary API surfaces plus the deployed binary/library
versions.

### F5 — acknowledged position reservation satisfies both load-bearing requirements

Prototype sequence:

1. send `TEXT-1` through the reliable dispatcher;
2. send `IMAGE-POSITION` through the same dispatcher and keep its `message_id`;
3. start `editMessageMedia` in an isolated task and hold it on an event;
4. send `TEXT-2` through the reliable dispatcher;
5. release the edit, replacing message 2 in place.

Measured output:

```text
text_completed_while_edit_slow True
positions_before_edit ['TEXT-1', 'IMAGE-POSITION', 'TEXT-2']
positions_after_edit ['TEXT-1', 'IMAGE', 'TEXT-2']
```

The placeholder is also the failure fallback: if the photo edit fails, the ordered text
marker remains instead of silently losing all evidence of the attachment. The guarantee is
conditional on receiving the marker's successful response and `message_id`.

**Confidence: CONFIRMED for acknowledged local control flow; LIKELY for live Telegram UX**
— deterministic prototype plus the official edit contract, without sending test traffic to
the user's group.

### F6 — admission must be reserved before the placeholder is sent

The image capacity check must happen before creating the placeholder. Checking after the
placeholder would leave permanent “loading” messages for rejected images. Capacity must
include reservations waiting for placeholder delivery, queued edits, and the in-flight edit;
otherwise concurrent producers can all pass a queue-length-only check.

The predictable overflow policy is reject-new:

- increment `image_dropped`;
- do not send a placeholder;
- return an unaccepted submission so Read-image handling keeps its textual fallback;
- clean generated temp files immediately.

**Confidence: CONFIRMED** — state-machine invariant derived from the bounded admission
requirement; every transition is directly testable.

### F7 — the real file operation needs its own worker but a shared rate authority

Moving the edit into the existing optional deque is insufficient: that deque is still
awaited by `_tg_dispatch_chat()` and therefore still blocks text after it starts. The image
worker must:

- be one owned task per chat;
- have a bounded reservation count (`_TG_IMAGE_QUEUE_MAX`);
- perform one edit attempt under a dedicated timeout;
- share a short per-chat rate-slot gate and `_tg_flood_until` with text, but release that gate
  before awaiting the network operation;
- never use reliable retries or hold the main dispatcher while the edit is in flight;
- settle completion, release the reservation, and update image-specific counters on every
  success, failure, timeout, cancellation, and reset.

The current single dispatcher is itself the per-chat rate authority. Adding an image worker
requires making rate-slot acquisition atomic across both workers; otherwise they can compute
the same delay and start simultaneously. The lock covers only wait-plus-timestamp reservation,
not the Telegram call. A `retry_after` reported by either worker updates the shared flood
window. That remote throttle can delay later text, but slow/failing file I/O cannot.

The small placeholder uses the ordered FIFO but gets one attempt rather than the reliable
ambiguous-error retry policy. This prevents duplicate markers. If Telegram accepts the
marker but its response is lost, an unknown textual marker can remain and the photo edit is
counted lost; the system cannot safely edit or retry it without a `message_id`.

**Confidence: CONFIRMED** — follows from F2 and the required separation of execution
ownership.

### F8 — asynchronous Read images require an owned immutable snapshot

The current Read-image path is an agent-controlled source file. Once upload moves to a
separate worker, that file can be overwritten or removed between admission and
`FSInputFile` consumption. Every accepted Read image must therefore be copied to an owned
temporary path before marker delivery; rejection/failure/reset must remove it just like a
generated PNG.

**Confidence: CONFIRMED** — the existing path is read lazily by the eventual send operation,
and the source file has no bridge-owned lifetime.

### F9 — worker cleanup must be state-identity safe

Reset can remove a chat state and an immediate resubmission can create a replacement state
for the same `chat_id`. An old image worker or callback must mutate only its captured state
and unregister itself only when both the registered task and state identity still match.
This mirrors the existing main dispatcher's ownership check.

**Confidence: CONFIRMED** — direct lifecycle invariant from the current dispatcher cleanup
pattern.

### F10 — current diagnostics exist only as a private per-chat function

`_tg_delivery_snapshot(chat_id)` already reports reliable, telemetry, and optional queue
depths, drops, losses, ages, and latency, but no route calls it. `app/routes/tg.py` has the
existing Telegram API router and is the smallest place for a read-only
`GET /api/tg/delivery-stats` endpoint.

**Confidence: CONFIRMED** — repository-wide reference search found only tests and the
definition.

## Alternatives and decision

| Approach | Chronology | Slow file does not block text | Bounded/drop-visible | Decision |
|---|---:|---:|---:|---|
| Promote `sendPhoto` to reliable | yes | no | reliable counters only | reject |
| Fairly interleave the existing optional lane | approximate | no once selected | yes | reject |
| Start photo concurrently by global sequence | not guaranteed | yes | yes | reject |
| Separate worker plus caption/reply metadata | no physical order | yes | yes | reject |
| Ordered text placeholder + isolated media edit | yes after marker acknowledgement | yes, except shared remote flood waits | yes | **choose** |

The chosen design is the only evaluated option that satisfies both hard ACs without relying
on undocumented concurrent request ordering.

## Counter-evidence and residual uncertainty

- A placeholder consumes one normal Telegram message/rate slot. This is the minimum cost of
  reserving a history position; it does not upload the real file or retry media in the text
  lane.
- Bot API sends have ambiguous outcomes. The marker uses one attempt to avoid duplicates,
  but a response lost after server acceptance can leave an uneditable textual marker with an
  unknown `message_id`. Absolute final history is impossible in that failure mode.
- Until the edit succeeds, the user sees an attachment marker rather than the final image.
  That is preferable to the current end-of-turn batch and preserves readable chronology.
- The official arbitrary-order statement is for Telegram's primary API rather than a
  Bot-API-specific ordering guarantee. This weakens F3 from CONFIRMED to LIKELY, but there is
  no documented Bot API primitive that makes concurrent `sendPhoto`/`sendMessage` strict.
- A live production-group probe was intentionally not run in research because it would send
  unsolicited messages. Final confidence requires post-restart observation after approval
  and deployment.
- If `editMessageMedia` fails after placeholder success, chronology is preserved but the
  marker remains textual. The failure and loss must be visible in both logs and stats.
- An image edit's `retry_after` must update the shared per-chat flood window. This can delay
  later text because Telegram itself requested a pause; it is distinct from waiting for a
  slow upload.

## Affected files

- `app/tg_bridge.py`
  - `_TgDeliveryState`, reset/snapshot helpers;
  - `_tg_call_safe`, `_tg_dispatch_chat`, and new isolated image-edit ownership;
  - `_tg_send_file_safe`, `_send_png_to_tg`, and Read-image fallback integration.
- `app/routes/tg.py`
  - read-only delivery-stats endpoint.
- `tests/test_tg_bridge.py`
  - deterministic event/state tests and endpoint coverage.

The topic-icon functions (`_update_topic_status`, `_schedule_topic_status`,
`_topic_status*`, `_any_running_in_scope`, `_sync_all_topic_statuses`) and `app/bg_jobs.py`
are explicitly out of scope.

## Risks and edge cases

- reset while a placeholder, queued edit, or in-flight edit exists;
- placeholder reliable admission overload after an image reservation was taken;
- edit timeout/network error/429 must release exactly one reservation and settle exactly one
  completion;
- generated temp file cleanup after rejection, failure, timeout, cancellation, and reset;
- immutable temporary snapshot cleanup for accepted Read images;
- Read-image rejection must retain the existing text/tool fallback;
- multiple chats must have independent image workers;
- reset followed immediately by resubmission must not let an old worker mutate new state;
- stats iteration must use a snapshot of live chat ids to avoid mutation races.

## Sources

1. [Telegram API — Sequential Requests](https://core.telegram.org/api/invoking#sequential-requests)
   — primary source: parallel requests are arbitrary without explicit dependencies.
2. [Telegram Bot API — editMessageMedia](https://core.telegram.org/bots/api#editmessagemedia)
   — primary source: a text message can be replaced with media.
3. [aiogram — editMessageMedia](https://docs.aiogram.dev/en/latest/api/methods/edit_message_media.html)
   — primary library API documentation.
4. [aiogram — InputMediaPhoto](https://docs.aiogram.dev/en/v3.16.0/api/types/input_media_photo.html)
   — primary library API documentation for uploaded photo input.
