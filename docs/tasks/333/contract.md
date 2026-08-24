# #333 — smallest durable media-delivery contract and Class-C options

This is a Phase 1 contract proposal, not an implementation plan. It follows the observed
boundary: the bridge can know that Orchestra accepted a file before it can know that Telegram
accepted the multipart request. It must not collapse those facts into one HTTP 500/200 result.

## Required minimum

| Field/state | Required meaning |
|---|---|
| `event_id` (or `delivery_id`) | One stable id per logical file. Reuse it for status and explicit retry; a fresh id is a new send. |
| `payload_hash` + immutable file reference/snapshot | Same-id retries must identify the same bytes/caption/target. Changed payload is a conflict. |
| `ACCEPTED` / `QUEUED` receipt | Durable Orchestra ownership committed before the first Bot API call. It is not Telegram delivery. |
| `SUBMITTING` | Provider-call boundary crossed; no automatic replay. |
| `SENT` + `message_id` | Only a provider response with a message id may prove a file send. |
| `FAILED_BEFORE_SUBMIT` | Local rejection before provider call; explicit same-id retry is permitted. |
| `UNKNOWN` | Timeout/network/server error after the provider boundary; no blind retry. |
| `GET status(event_id)` | Reconciliation path; must work after caller timeout/restart. |
| `Retry-After`/typed backpressure | Full admission is a bounded rejection, not an unbounded synchronous wait. |
| per-file outcome | A batch does not erase or overwrite another file's state; primary and mirror outcomes are separate. |

The contract promises exactly-once acceptance by Orchestra and at-most-once automatic provider
submission. It cannot promise exactly-once Telegram effect without a provider idempotency key or
a provider-side receipt query.

## Proposed Class-C options

These options are intentionally additive and have explicit rollback boundaries. “Class-C” here
means the compatibility-controlled contract choices to carry into Phase 2; no option was shipped
or activated by this research.

### C1 — receipt-backed per-file outbox (smallest durable contract; preferred candidate)

- Add a file-delivery receipt/outbox owner keyed by `event_id`, with the states above.
- Return `202`/receipt promptly after the SQLite commit; run the existing per-chat FIFO worker
  after commit.
- Preserve the existing `send_file(path, caption, as_document)` arguments. Add an optional
  `event_id` only if the caller can retain it; legacy callers get a generated id and receive an
  explicit `ACCEPTED`/`UNKNOWN` result rather than a false success.
- Keep primary topic and mirror as separate child outcomes.

Rollback: stop admitting new C1 rows and leave `UNKNOWN` rows quarantined; do not replay them as
fresh sends. A compatibility reader can continue to report legacy HTTP 500 while the new status
resource is disabled, but it must not silently treat 500 as safe to retry.

Compatibility boundary: additive table/status endpoint and additive result envelope; current
topic resolution, `as_document`, file-size checks, and MCP tool name stay unchanged. No user-topic
or route mutation is required.

### C2 — isolated marker + edit as a containment mode

- Use the existing marker/edit seam only for selected previews.
- Record marker `message_id` as a separate receipt before attempting `editMessageMedia`.
- Never retry an ambiguous marker; permit explicit same-marker-id reconciliation.

Rollback: disable the opt-in isolated flag and return to direct send. Orphan markers are a known
cleanup concern; do not delete or mutate user topics automatically.

Compatibility boundary: no changes to direct `send_photo` callers. C2 reduces the cost of a
media-edit retry after a proven marker, but is not a durable exactly-once contract by itself.

### C3 — `sendMediaGroup` for an explicitly batched album

- Accept 2–10 same-type files and store one event id for the batch plus child file ids.
- On success store the returned array of message ids.
- On timeout mark the entire group `UNKNOWN`; never automatically fall back to individual sends.

Rollback: disable batch admission and use C1 individual outbox rows. Do not split an unknown
group into new ids, because that can duplicate every item.

Compatibility boundary: new opt-in batch API only; existing single-file `send_file` remains C1 or
legacy. Captions/order/topic behavior must be specified before implementation.

### C4 — direct `send_document` fallback

- Keep `as_document=True` as an explicit caller choice, useful where Telegram photo constraints
  are the problem.
- It still uses the same receipt, queue, and unknown rules; it is not a retry escape hatch after
  an ambiguous photo call.

Rollback: callers can select photo again without schema migration. Automatic photo→document
  fallback is prohibited after an unknown provider call because it sends a second logical item.

### C5 — legacy compatibility wrapper

- Keep the current synchronous MCP tool callable during migration.
- Map a committed receipt to a short accepted result; map pre-submit rejection to typed retryable
  failure; map provider-boundary ambiguity to typed `UNKNOWN` with the same `event_id` and a status
  lookup instruction.

Rollback: route legacy callers back to the old wrapper only before they have seen/retained C1
ids. Once a caller has a C1 id, status and retry must remain same-id; never downgrade it to a
fresh POST.

## Not selected by evidence

- Raising the 30 s bridge timeout: does not create an id or receipt and still fails after a
  transport close.
- Blind retries after 500/`ReadTimeout`: directly conflicts with the measured duplicate window.
- Automatic fallback photo→document or group→individual after unknown: creates a second logical
  send without knowing whether the first reached Telegram.
- Route switching/restarting local Bot API as a delivery protocol: current controls recovered and
  individual sends worked; operational recovery does not establish per-file outcome.
