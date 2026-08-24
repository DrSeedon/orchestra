# #333 — Telegram media delivery incident reconstruction

Date of reconstruction: 2026-08-24 (local time Asia/Krasnoyarsk, UTC+7)

Scope: Phase 1 research only. The live database and journals were read-only. No media
send, route switch, service restart, credential use, or Telegram-topic/config mutation was
performed.

## Question

### Context

The Orchestra Telegram bridge sends media through MCP HTTP → FastAPI → the per-chat reliable
queue → aiogram → local `telegram-bot-api` → proxychains → gateway `127.0.0.1:12339` →
Telegram. The incident window is 15:04:00–15:10:59 local on 2026-08-24 while eight PNGs
were being requested sequentially.

### Change under test

This is a reconstruction, not an implementation: determine whether the current three-attempt
media path can duplicate, what its HTTP 500 means, why sequential calls block, and what the
smallest truthful durable contract would need to expose.

### Baseline

Current direct important photo path: `send_file_to_tg` calls `_tg_send_file_safe(...,
important=True)`; a normal photo goes to `bot.send_photo`, not the isolated marker/edit lane.
Current `send_file` has an MCP request timeout of 180 s, while each important Telegram call is
wrapped by a 30 s bridge timeout and may be attempted three times.

### Measurable outcome

The answer is decided by (a) timestamped journal/API/SQLite evidence, (b) code-level retry and
queue semantics, and (c) explicit delivery classification for every observed event:
`PROVEN`, `UNKNOWN`, or `NOT_SENT`.

## Hypotheses considered

### H1 — three ambiguous attempts can duplicate the same Telegram message

Falsifier: every timeout is proven to occur before the outbound request was sent, or Telegram
provides and the bridge uses an idempotency key. Neither is present in the trace or current
code.

Result: **CONFIRMED as a capability; not proven to have happened in this incident.**
`_TG_IMPORTANT_ATTEMPTS=3`; important timeout and network/server exceptions continue to a new
call. The call factory creates a fresh aiogram request each time, with no event/delivery key.
The Bot API documents `sendPhoto` parameters and a returned `Message`, but no idempotency key
[10]. A timeout therefore leaves the upstream side effect unknown and a later attempt can
create a second message [3][10].

### H2 — the 500 is a known failure and a fresh retry is safe

Falsifier: the route returns 500 only when it has proof that Telegram did not receive the file,
or it exposes a durable receipt that can be reconciled. The route has neither property.

Result: **REFUTED.** `send_file_to_tg` turns `msg is None` into a generic error object; the route
maps every such error to HTTP 500. MCP classifies a non-GET 500 as `outcome_unknown=true` and
`retryable=false`, but exposes no message id or per-attempt receipt [4][5].

### H3 — eight calls block because Telegram rejected eight files

Falsifier: local queue/API logs show eight upstream rejections rather than one serialized call
holding the queue. The evidence shows one 93-second direct-photo attempt sequence, no upstream
Telegram response log, and only later successful local API responses.

Result: **REFUTED.** The per-chat dispatcher awaits one reliable item before selecting the next;
the first item consumes three 30 s budgets and retries. The first observed HTTP 500 is local
FastAPI, not an upstream Telegram 500 [1][3][4][6].

### H4 — route recovery and individual sends were absent

Falsifier: all later sends remain failed or there are no successful `message_id` receipts.

Result: **REFUTED.** Within the window, the journal records successful file deliveries with
`msg_id=162144`, `162147`, and `162148` plus HTTP 200. This is counter-evidence against a
permanent route outage, but it does not reconcile the earlier timed-out attempts to specific
messages [1].

## Findings

### F1 — exact incident timeline

The source rows and sanitized journal excerpts are preserved in `timeline.csv` and
`evidence/journal-tg-1504-1510.txt`. The key sequence is:

1. 15:04:53–15:05:33: cosmetic `send_message`/`edit_message` calls are dropped because the
   non-important lane refuses to wait for a rate slot. These are not proof that media was sent
   or rejected.
2. 15:05:35: `161177-surikov.png` begins as a direct important `send_photo` request.
3. 15:06:05 and 15:06:36: attempt 2/3 and 3/3 follow 30 s timeouts.
4. 15:07:08: the bridge logs `LOST after 3 timed out attempts`; FastAPI returns HTTP 500. The
   observed start-to-500 interval is **93.003504 s** (15:05:35.550065 → 15:07:08.553569).
   No
   `message_id` exists for this logical request, so external delivery is unknown.
5. 15:07:08: `161177-pozdeev.png` begins. A separate matrix request for
   `161177-surikov.png` begins at 15:08:28; a later `161181-surikov.png` request begins at
   15:10:08. The journal has no request id linking these starts to a completed upstream
   Telegram operation.
6. 15:10:41, 15:10:46, and 15:10:53: three file sends complete with message ids and HTTP 200.

**Confidence: CONFIRMED** for the timestamps and local outcomes (tier 1 journal + tier 1
SQLite/API rows). Attribution of each 15:10 success to a particular earlier timed-out request
is **UNCERTAIN** because neither `/api/tg/send_file` nor the bridge log carries the MCP
`X-Request-ID`/logical file id.

### F2 — the direct important photo path retries ambiguously

`_tg_run_attempts` sets three attempts for important traffic and defaults `retry_ambiguous` to
`important` [3, lines 1303–1306]. `TimeoutError` continues to the next attempt [3, lines
1326–1341]. `TelegramNetworkError` and `TelegramServerError` also continue [3, lines
1378–1386]. `_tg_send_file_safe` uses direct `bot.send_photo` for an important photo unless
`isolated_preview=True` [3, lines 2347–2382].

**Confidence: CONFIRMED** — tier 2 current source plus the three timeout log lines [1].

The three ambiguous POST/Telegram-call retries **can duplicate**. Whether this incident did
duplicate is **UNKNOWN**: the same timeout is compatible with “request never left local API”,
“Telegram accepted it but the response was lost”, and intermediate proxy failure.

### F3 — the 500 loses the information needed for a truthful retry

The route awaits `send_file_to_tg`; any returned `{"error": ...}` becomes HTTP 500 [4, lines
141–157]. The bridge returns that error after `msg is None` and only logs the generic delivery
failure [3, lines 2679–2707]. `_api` assigns `http_5xx`, sets `outcome_unknown=True` for a
non-GET 500, and suppresses retryability [5, lines 394–474].

The 500 therefore loses: the logical file/event identity, attempt number, whether the local Bot
API received the multipart body, whether Telegram accepted it, any upstream `message_id`, and
the distinction between “not sent” and “sent but acknowledgement lost”. It also provides no
status/reconciliation endpoint. The caller-visible string in the incident was exactly
`http_5xx: TG file delivery failed; see tg-bridge logs` [9].

**Confidence: CONFIRMED** — tier 2 source and tier 1 incident tool result.

### F4 — eight sequential calls block on a serialized per-chat queue

The reliable dispatcher selects one item and awaits `_tg_run_call` before clearing
`state.in_flight` and selecting another [3, lines 1623–1699]. Important calls wait for a rate
slot; non-important calls may drop when no slot is immediately available [3, lines 1258–1276,
1306–1318]. Queue admission itself can wait up to 5 s and the reliable queue has 256 slots with
64 admission waiters [3, lines 1816–1869 and constants 929–932].

The first direct photo held the per-chat reliable worker for three 30 s attempts and 1 s
backoff, ending at 15:07:08 after starting at 15:05:35. A sequential MCP caller cannot obtain
the next tool result while its current HTTP POST is awaiting that item. The incident reporter
observed the batched `functions.exec` blocked for about 53 s and did not know how many of eight
requests had delivered [9]. The code does not prove that all eight had even become server-side
requests before the batch stopped.

**Confidence: CONFIRMED** for serialization and budgets (tier 2 source + tier 1 timing);
**LIKELY** for the exact count of requests admitted before the batch stopped (tier 1 report
explicitly says that count was unknown).

### F5 — isolated marker/edit is a different failure shape, not exactly-once delivery

The isolated lane snapshots the file, sends a text marker as an ordered call with a 2 s
telemetry timeout and `retry_ambiguous=False`, then queues `edit_message_media` with a 30 s
timeout and `retry_ambiguous=important` [3, lines 2156–2344]. The important path returns a
Future and lets the marker continuation/edit proceed asynchronously; it does not wait for both
operations [3, lines 2213–2227 and 2314–2344]. Current tests confirm both behaviours: important
handoff does not wait for marker/edit, and an ambiguous marker is not retried [8, lines 632–692,
778–806].

This lane can make a marker receipt available before the upload edit and can retry an ambiguous
media edit against a known `message_id`, but a marker timeout can leave either an orphan marker
or no marker. It does not establish exactly-once media effect.

**Confidence: CONFIRMED** — tier 2 source plus focused tests; no live marker/edit was issued.

### F6 — route/proxy recovered; the incident is not proof of permanent upstream outage

The current production service is active, the proxychains configuration points to the gateway
on `127.0.0.1:12339`, and the selected gateway route is `contabo`. The read-only Telegram
preflight (`getMe` with an intentionally invalid token, not a media send) returned the required
JSON marker and exit 0. No route switch was made [6].

The bridge delivery stats GET returned one chat with `reliable_retries=8`,
`reliable_timeouts=9`, `reliable_lost=3`, `telemetry_dropped=400`, and no currently queued or
in-flight work. These are aggregate counters, not per-file receipts. The journal then recorded
three successful `send_file`/HTTP 200 pairs in the incident window [7].

**Confidence: CONFIRMED** for current positive controls and later local receipts; **UNKNOWN**
for the upstream Telegram state of each timed-out attempt because local telegram-bot-api
emitted no usable method-level success/failure record in the window.

## Comparison of candidate delivery shapes

| Candidate | Evidence in current system / protocol | What it improves | What remains ambiguous or costly | Rollback / compatibility boundary |
|---|---|---|---|---|
| Direct important `send_photo` | Current default path; 3 ambiguous attempts, 30 s each; incident hit this path [1][3] | Smallest code path; one Telegram message and a returned `Message` on success; later individual sends worked | Timeout can duplicate; 500 has no receipt; per-chat serialization blocks | Keep current `send_file` signature and route; any change must preserve `as_document` and topic resolution |
| Isolated marker + edit | Existing `isolated_preview` path; marker 2 s no ambiguous retry, media edit 30 s with retry [3][8] | A known marker id can anchor later edit; media work can continue after caller returns | Two side effects, orphan marker risk, marker itself can be ambiguous; not exactly-once | Additive opt-in only; rollback by disabling isolated flag; do not alter topic/config state |
| Direct `send_document` | Existing `as_document=True` branch uses same `_tg_call_safe` retry/queue [3, lines 2362–2382] | 50 MB Bot API class versus 10 MB photo class; current 0.4–4.1 MB PNGs do not need it [10] | Same ambiguous retries and 500; Telegram still sees a new send per retry | Preserve `as_document`; safe fallback only at caller choice, never automatic after ambiguity |
| `sendMediaGroup` | Telegram supports 2–10 same-kind media and returns an array of `Message` objects on success [10] | Fewer logical HTTP operations for a batch; album presentation | One ambiguous request may duplicate an entire album; partial per-file status is not returned on failure; current captions/order/topic semantics need a new contract | New opt-in batch API; rollback to individual sends; no automatic fallback after unknown group submission |
| Server-side durable outbox | Local #380 receipt research shows the project already has a proven acceptance/unknown/reconciliation pattern for direct messages, but no file outbox is present [11] | Commit `event_id` + payload/hash before network; per-file status/receipt; bounded worker/backpressure; restart recovery without fresh ids | Schema/runner work, file snapshot/retention, status API, and provider ambiguity still remain; cannot promise Telegram exactly-once without provider idempotency | Add new table/status API and keep legacy wrapper; rollout behind an opt-in protocol/revision; rollback stops new runner and drains/quarantines rows, never replays UNKNOWN |

Telegram's official Bot API states that `sendPhoto`, `sendDocument`, and `sendMediaGroup` return
message objects on success, and that `sendMediaGroup` accepts 2–10 items [10]. It does not expose
an idempotency argument for these sends; the duplicate-risk conclusion is therefore an inference
from the documented request surface plus the current retry code, not a claim that every provider
timeout duplicates.

## Smallest durable contract (evidence-led, not implementation)

The minimum truthful contract is per logical file, not per batch:

1. **`event_id` / `delivery_id`** — caller creates one id per logical file and reuses it for
   status/retry. A fresh id is a new send, never a retry of an unknown one.
2. **Acceptance receipt** — Orchestra durably commits id, target chat/topic, source/sender,
   payload hash and an immutable file snapshot/reference before starting the Bot API call. The
   response may be `QUEUED`/`ACCEPTED`; it must not claim Telegram delivery.
3. **Per-file status** — at minimum `QUEUED`, `SUBMITTING`, `SENT(message_id)`,
   `FAILED_BEFORE_SUBMIT(retryable)`, and `UNKNOWN(after provider boundary, no automatic retry)`.
   A failed batch must not erase statuses for other files.
4. **Explicit reconciliation** — `GET status(event_id)` returns the stored state and last
   diagnostic. A same-id request with a different payload hash is a conflict. Unknown is resolved
   only by a provider-side receipt/search or by an explicit operator decision; blind retry is
   prohibited.
5. **Bounded queue/backpressure** — admission has a typed rejection/`Retry-After` when full;
   per-chat FIFO is preserved, but one slow unknown item must not make callers wait for an
   unbounded synchronous POST. Cosmetic traffic remains separate and may be coalesced/dropped.
6. **Separate fan-out outcomes** — primary topic and mirror are separate per-file records or
   child outcomes. A primary success must not be rewritten as failure because a mirror failed.

This is the smallest contract that answers the incident's missing questions without promising
provider exactly-once. It is smaller than a universal enterprise ingress and stronger than merely
raising the HTTP timeout.

## Counter-evidence and open gaps

- Current gateway route was healthy at reconstruction time; the Telegram proxy preflight passed
  with `EXIT=0` and did not send media [6].
- Individual media sends recovered and produced message ids 162144, 162147, and 162148 with
  HTTP 200 in the same window [1]. Therefore “Telegram was down for the whole interval” is not
  supported.
- The local `telegram-bot-api` journal in the incident window contained repeated proxychains
  backtraces but no usable method-level receipt. We cannot prove whether any timed-out upload
  reached upstream Telegram.
- There is no per-request id linking the MCP tool row, `/api/tg/send_file` access line, queue item,
  aiogram call, local Bot API request, and final Telegram `message_id`. The exact eight-admitted
  count and duplicate count remain open.
- No live media probe was run by this research; all protocol comparison beyond current code uses
  the official Bot API documentation [10].

## Review/verification route

The user explicitly forbade model/provider/review calls. No external reviewer was invoked.
Mechanical checks used instead: exact source-line inspection, read-only SQLite query, journal
extraction, sanitized current-control probes, and consistency checks between journal and DB rows.
This is recorded as a deliberate constraint, not as a reviewer approval.

## Sources

1. `journalctl -u orchestra.service --since '2026-08-24 15:04:00' --until '2026-08-24 15:13:00'` — sanitized TG bridge and `/api/tg/send_file` lines in `evidence/journal-tg-1504-1510.txt`.
2. Read-only SQLite query against `/mnt/data/Projects/Python/orchestra/data/orchestra.db` — MCP `send_file` tool/result rows in `evidence/db-send-file.tsv`.
3. `app/tg_bridge.py:922–940, 1258–1434, 1623–1737, 1816–1869, 2156–2382` — budgets, queue, retry, direct and isolated media paths.
4. `app/routes/tg.py:135–157` — delivery-stats and `send_file` route/error mapping.
5. `app/mcp_stdio.py:394–552, 1511–1540` — HTTP error classification and MCP `send_file` contract.
6. `systemctl status/cat telegram-bot-api`, `/etc/proxychains4.conf`, gateway state/config, and read-only `check-telegram-proxy.sh` preflight — sanitized in `evidence/current-controls.txt`.
7. Read-only `GET http://127.0.0.1:8888/api/tg/delivery-stats` — sanitized response in `evidence/current-controls.txt`.
8. `tests/test_tg_bridge.py:632–840, 894–922` — isolated handoff, ambiguous marker, and retry behavior.
9. `/home/maxim/.local/state/orchestra/bug-inbox/records/20260824T080805.472060Z-f49cf488dde54ede865a5fb711f0184c.md` — sanitized incident report.
10. [Telegram Bot API](https://core.telegram.org/bots/api) — official `sendPhoto`, `sendDocument`, `sendMediaGroup`, `editMessageMedia`, and file limits.
11. `docs/tasks/380/research.md` — prior local durable acceptance/unknown-reconciliation research; no file outbox implementation was inferred from it.
