# #333 — Phase 2 plan: durable per-file TG outbox (C1) + compatibility wrapper (C5)

## Decision and scope

Implement only the preferred Phase-1 C1 receipt-backed per-file outbox and C5 legacy MCP
wrapper.  One logical file is accepted once by Orchestra, is submitted automatically to each
configured provider target at most once, and remains reconcilable by `event_id` after caller
timeout or process restart.

In scope:

- additive SQLite schema for one logical file receipt, primary/mirror child outcomes and a
  durable per-chat lease generation;
- a private immutable-by-contract 0600 file snapshot completed before the 202 receipt;
- canonical payload hash and same-event idempotence/conflict;
- states `QUEUED`, `SUBMITTING`, `SENT(message_id)`, `FAILED_BEFORE_SUBMIT`, `UNKNOWN`;
- exactly-once Orchestra acceptance and at-most-once automatic provider submission;
- restart recovery, per-chat FIFO, bounded backpressure, owner-scoped status, retention,
  quarantine, cleanup and rollback behavior;
- current `send_file(path, caption="", as_document=False)` compatibility, with optional
  `event_id` added at the end and truthful accepted/receipt wording.

Out of scope for v1:

- C2 marker/edit mode, orphan-marker cleanup or changes to existing isolated-preview behavior;
- C3 `sendMediaGroup`, batch ids, album ordering or group→individual fallback;
- automatic photo→document fallback after any ambiguous call;
- Telegram/provider idempotency claims, provider-side search/reconciliation, route switching,
  service restart, deployment, live Telegram probes or timeout increases;
- generalizing `app/message_deliveries.py` or the direct-agent `/send` contract from #380.

The frozen behavior tests are commit `3907df87`.  Phase 3 must compare every file under
`docs/tasks/333/acceptance/` byte-for-byte with that commit before accepting an executor result.

## Baseline and required external contract

Current production path:

```text
MCP app.mcp_stdio.send_file
  → POST /api/tg/send_file
  → app.routes.tg.tg_send_file
  → app.tg_bridge.send_file_to_tg
  → _tg_send_file_safe / _tg_call_safe
  → bot.send_photo|send_document
```

The current route waits for provider completion and returns 200/500.  Important calls can make
three ambiguous provider attempts; there is no file receipt/status id linking the HTTP call to a
Telegram message id.  The new route contract is:

- Request keeps `path`, `caption`, `scope`, `sender`, `as_document`; adds `event_id` (UUID).
- New MCP code always generates `event_id` before POST when the optional argument is blank.
- A provided valid event id with byte-identical canonical payload returns HTTP 202 and the same
  `accept_seq`/hash (`acceptance=ALREADY_ACCEPTED`); a changed canonical payload returns HTTP 409
  `IDEMPOTENCY_CONFLICT`, `outcome_unknown=false`.
- First durable acceptance returns HTTP 202:

```json
{
  "ok": true,
  "acceptance": "ACCEPTED",
  "event_id": "<uuid>",
  "payload_hash": "<sha256 hex>",
  "accept_seq": 1,
  "delivery_state": "QUEUED",
  "status_url": "/api/tg/file-deliveries/<uuid>",
  "children": {
    "primary": {"state": "QUEUED", "chat_id": -100, "thread_id": 42,
                "message_id": null, "error": null}
  },
  "next_action": {}
}
```

- `delivery_state` is always the primary child state; mirror state cannot rewrite it.  The
  `children` mapping gains `mirror` only when a mirror target was snapshotted at acceptance.
- HTTP 429 capacity rejection is pre-accept and typed as `TG_FILE_QUEUE_FULL`,
  `retryable=true`, `outcome_unknown=false`, with both JSON `retry_after_seconds` and the
  `Retry-After` header.  An already-accepted event bypasses this gate and reconciles normally.
- New-admission rollback rejection is HTTP 503 `TG_FILE_OUTBOX_DISABLED`, known not accepted and
  safe to retry after the operator reenables admission; it never falls through to the old direct
  send path.
- `GET /api/tg/file-deliveries/{event_id}` returns the same resource to its bound MCP principal
  (session id + MCP proof) or an authenticated dashboard operator; another valid principal and a
  token-only caller get 403.

`UNKNOWN` means only that a provider effect may exist.  It is never an instruction to resend.
No state or response promises provider exactly-once.

## Additive database schema and migration

Owner: `app/db.py:init_db` creates all three tables with `IF NOT EXISTS` before `_migrate`; a
new `_migrate_tg_file_deliveries(connection)` validates/adds only v1 nullable metadata columns
if a pre-release test database exists.  It must not rewrite/drop `sessions`, `logs`, #380
`message_deliveries`, or any TG config.  Receipt rows intentionally have no foreign key to
`sessions`: session deletion must not erase idempotency history.

### `tg_file_deliveries` — one logical accepted file

```sql
accept_seq INTEGER PRIMARY KEY AUTOINCREMENT
event_id TEXT NOT NULL UNIQUE
schema_version INTEGER NOT NULL
source_session_id TEXT
source_name TEXT NOT NULL
source_scope TEXT NOT NULL
source_path TEXT NOT NULL
original_name TEXT NOT NULL
snapshot_path TEXT NOT NULL
size_bytes INTEGER NOT NULL CHECK(size_bytes > 0 AND size_bytes <= 52428800)
content_sha256 TEXT NOT NULL CHECK(length(content_sha256) = 64)
caption TEXT NOT NULL
outbound_caption TEXT NOT NULL
as_document INTEGER NOT NULL CHECK(as_document IN (0,1))
payload_hash TEXT NOT NULL CHECK(length(payload_hash) = 64)
orch_name TEXT
created_at TEXT NOT NULL
updated_at TEXT NOT NULL
snapshot_deleted_at TEXT
quarantined_at TEXT
```

### `tg_file_delivery_targets` — independent primary/mirror outcomes

```sql
event_id TEXT NOT NULL REFERENCES tg_file_deliveries(event_id) ON DELETE CASCADE
target_kind TEXT NOT NULL CHECK(target_kind IN ('primary','mirror'))
chat_id INTEGER NOT NULL
thread_id INTEGER
state TEXT NOT NULL CHECK(state IN
  ('QUEUED','SUBMITTING','SENT','FAILED_BEFORE_SUBMIT','UNKNOWN'))
message_id INTEGER
attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count >= 0)
lease_generation INTEGER NOT NULL DEFAULT 0 CHECK(lease_generation >= 0)
error_json TEXT
submitted_at TEXT
sent_at TEXT
updated_at TEXT NOT NULL
PRIMARY KEY(event_id, target_kind)
```

Indexes:

- `idx_tg_file_targets_chat_state` on `(chat_id, state, event_id)`; ready selection joins the
  parent and orders by `tg_file_deliveries.accept_seq`.
- `idx_tg_file_deliveries_source_seq` on `(source_session_id, accept_seq)`.

### `tg_file_chat_leases` — one durable runner generation per chat

```sql
chat_id INTEGER PRIMARY KEY
generation INTEGER NOT NULL CHECK(generation > 0)
owner_token TEXT NOT NULL
lease_expires_at TEXT NOT NULL
updated_at TEXT NOT NULL
```

Migration order inside one startup is: create/validate tables and indexes → initialize the HTTP
surface → start the TG bridge → run file-delivery recovery/maintenance.  No target is selected
before `init_db()` commits and no runner starts before the bridge provider seam is ready.

Rollback has no down migration.  Old code safely ignores additive tables; dropping tables or
spool files would destroy reconciliation and is forbidden.

## Snapshot, identity and atomic acceptance

Owner: new `app/tg_file_deliveries.py`.

Constants/symbols required by the frozen oracle and implementation:

- `SCHEMA_VERSION = 1`;
- `SPOOL_ROOT = data/tg-file-outbox` by default; root and `active/`, `tmp/`, `quarantine/`
  directories are 0700;
- `MAX_PENDING_TOTAL = 256` active child outcomes;
- `MAX_PENDING_PER_CHAT = 64` active child outcomes;
- `RETRY_AFTER_SECONDS = 5`;
- `LEASE_SECONDS = 120`, greater than the one-call provider timeout;
- `ADMISSION_ENABLED`, initialized from `TG_FILE_OUTBOX_ADMISSION` and patchable by tests;
- `SENT_SNAPSHOT_RETENTION_SECONDS = 86400`,
  `FAILED_SNAPSHOT_RETENTION_SECONDS = 604800`,
  `MAINTENANCE_INTERVAL_SECONDS = 21600`.

`accept_file_delivery(...)` performs these steps:

1. Authenticate/bind the source principal in the route and resolve the primary topic plus the
   current optional mirror once.  Target kind/chat/thread are payload identity, not live config
   consulted again during dispatch.
2. If `event_id` exists, calculate/compare the canonical payload when the source is available,
   return the existing receipt on exact match, and return 409 on mismatch.  Existing ids are
   reconciled before admission-enabled and capacity gates.
3. Open the source once with no symlink following, copy while hashing into a unique 0600 temp file,
   `fsync` the file, and publish it without replacement under `active/<event-id>/` with the
   original basename.  The service never opens a published snapshot for writing.  It must retain
   original bytes even if the source is changed or deleted immediately after 202.
4. Canonical `payload_hash` is SHA-256 over sorted compact JSON containing protocol
   `tg-file/v1`, content SHA-256, size, original basename, final outbound caption, source
   scope/sender, `as_document`, and sorted primary/mirror target kind/chat/thread.  Absolute
   source and spool paths are excluded.
5. In one `BEGIN IMMEDIATE` transaction, recheck event identity, count active
   `QUEUED|SUBMITTING` children globally and for every target chat, then insert the parent and all
   child rows.  Commit is the ACCEPTED boundary.  Lost commit acknowledgement is reconciled by
   re-reading `event_id` and comparing the stored hash.
6. On conflict, capacity rejection or failed transaction, remove only this request's unpublished
   temp/candidate.  It must not remove a concurrent winner's snapshot.  After commit, runner wake
   failure is logged but cannot rewrite the 202 receipt.

For a same-event `FAILED_BEFORE_SUBMIT` retry, rebuild a missing snapshot from the source, require
the same canonical hash, atomically return only failed child outcomes to `QUEUED`, retain the
original `accept_seq`, and wake the same chats.  `SENT`, `SUBMITTING`, and `UNKNOWN` are status-only
on repeat POST and never requeued automatically.

## State machine and one-call provider boundary

New `app/tg_file_deliveries.py` owns:

- `_resource(event_id)` / owner-scoped `get_file_delivery`;
- `accept_file_delivery`;
- `ensure_chat_runner(chat_id)`;
- `run_chat_deliveries(chat_id)`;
- `recover_file_deliveries()`;
- `cleanup_file_deliveries(*, now=None)`;
- `start_file_delivery_service()` / `shutdown_file_delivery_service()`.

`run_chat_deliveries` acquires `tg_file_chat_leases` in `BEGIN IMMEDIATE`: absent or
released/expired leases get a new positive generation; an unexpired foreign owner makes the
second runner return.  It processes only that chat, ordered by parent `accept_seq`, and stamps the
same generation on each claimed target.  Every transition/result update is conditional on the
current lease owner/generation.  A stale runner cannot submit a new item or overwrite a newer
generation's result.

For each `QUEUED` child:

1. While still pre-boundary, verify the snapshot exists, is a regular private file with stored
   size/hash, that the snapshotted target is usable, and reserve the existing local per-chat rate
   slot.  A known local failure writes `FAILED_BEFORE_SUBMIT` with
   `retryable=true`, `outcome_unknown=false` and makes no provider call.
2. Commit CAS `QUEUED → SUBMITTING`, increment `attempt_count`, store `lease_generation` and
   `submitted_at`.  A crash after this commit but before the call is conservatively ambiguous.
3. Call `app.tg_bridge._submit_file_snapshot_once(chat_id, snapshot_path, caption, thread_id,
   *, is_photo)` exactly once.  It performs a direct `bot.send_photo` or `bot.send_document`
   inside one 30-second timeout and never enters `_tg_run_attempts`, marker/edit, mirror outbox,
   retry or photo→document fallback.
4. A returned Telegram object with integer `message_id` commits `SENT`; timeout, cancellation,
   network/server exception, missing/invalid receipt, or any post-CAS exception commits `UNKNOWN`
   with `retryable=false`, `outcome_unknown=true`.  Then continue to the next FIFO item.

Primary and mirror are ordinary independent target rows and may run concurrently because their
chat ids differ.  Top-level state/message id derives only from `target_kind=primary`.  A mirror
error is visible on its child and never rewrites primary `SENT`.

On startup `recover_file_deliveries` atomically changes every orphaned `SUBMITTING` child to
`UNKNOWN`, leaves `FAILED_BEFORE_SUBMIT|UNKNOWN|SENT` terminal, and starts each chat containing a
`QUEUED` child.  It is idempotent.  On shutdown, cancel/join file runners before closing the TG
bot: cancellation before CAS leaves QUEUED; after CAS writes UNKNOWN.  No blind replay is allowed.

## HTTP/MCP compatibility and status

`app/routes/tg.py` changes only the two file-receipt routes:

- `tg_send_file(req: dict, request: Request)` authenticates MCP proof or dashboard operator,
  preserves safe-path/size/topic/as-document checks through the new service, and returns the
  explicit 202/409/429/503 envelopes above;
- new `tg_file_delivery_status(event_id, request)` returns an owner-scoped stored resource.

`app/mcp_stdio.py`:

- keeps `send_file(path, caption="", as_document=False)` valid and adds only trailing optional
  `event_id=""`;
- generates one UUID before POST when blank, always includes it in JSON, and returns a string
  containing `accepted`, the durable id, current state, and `file_delivery_status` instruction;
  it must not say “sent” for QUEUED/SUBMITTING/UNKNOWN;
- on ambiguous HTTP transport/5xx, performs one GET for the same generated id before returning;
  a found receipt is returned, a missing/unavailable receipt raises typed `ApiToolError` that
  still carries the id and forbids a fresh-id retry;
- adds read-only `file_delivery_status(event_id)` and its path helper, and includes the tool in
  `READ_ONLY_MCP_TOOLS`; it performs GET only and accepts extra status fields.

Known internal consumers remain compatible: `send_chart` concatenates the returned string and
does not parse its old wording; `publish_artifact` only names `send_file` as explicit fallback.
Existing non-C1 calls to `_tg_send_file_safe`, isolated previews, text delivery and log mirrors
remain unchanged.

## Retention, quarantine and cleanup

Receipt and child rows are never automatically deleted: removing them would permit a retired
`event_id` to be accepted and submitted again.  Only bulky snapshots are cleaned.

- `QUEUED` and `SUBMITTING`: never cleanup.
- Any terminal file with at least one `UNKNOWN` child: after all children are terminal, atomically
  move the shared snapshot within the same private filesystem to `quarantine/`, update
  `snapshot_path`/`quarantined_at`, keep mode 0600 and retain indefinitely.
- All children `SENT`: after 24 hours, unlink the snapshot and set `snapshot_path=''` plus
  `snapshot_deleted_at`; keep hashes/receipt/message ids.
- At least one `FAILED_BEFORE_SUBMIT` and no UNKNOWN: retain seven days for same-id retry, then
  unlink the snapshot and retain the receipt/failure.  A later same-id request may recreate only
  from a still-matching source.
- Cleanup runs once after recovery and every six hours; it refuses to touch a file outside the
  resolved `SPOOL_ROOT`, skips active/temp files it cannot attribute to one receipt, and logs the
  exception class/path without failing delivery.

## Rollout and rollback order

Rollout:

1. Deploy additive schema/module/provider seam while admission defaults enabled in the same code
   generation; `init_db` runs before any file service.
2. Expose 202/status route and C5 wrapper together, so no new caller sees a receipt without a
   lookup tool.
3. After the TG bridge is ready, recover queued rows, quarantine orphaned submitting rows as
   UNKNOWN, then start maintenance.
4. No live route switch/restart is part of this task; deployment remains an explicit user action.

Rollback:

1. Set `TG_FILE_OUTBOX_ADMISSION=0`: existing ids/status remain readable, fresh ids receive known
   503, and there is no legacy-direct fallback.
2. Let committed QUEUED rows drain or keep them for the next compatible generation; stop joins
   current runners and leaves any provider-boundary cancellation UNKNOWN.
3. Preserve the status reader/tool and additive tables/spool while any UNKNOWN receipt exists.
   `recover_file_deliveries` never selects UNKNOWN, whether admission is enabled or disabled.
4. A full old-code downgrade is allowed only after C1 callers are disabled and receipt/status
   access is separately retained/exported.  Do not drop tables, delete quarantine, convert UNKNOWN
   to QUEUED, mint replacement ids, or route an UNKNOWN item through old `send_file_to_tg`.

## File/function ownership

| File | Phase-3 owner/change | Consumers protected |
|---|---|---|
| `app/db.py` | `init_db`, `_migrate`, new `_migrate_tg_file_deliveries`; additive tables/indexes only | all DB startup, #380 message receipts, existing live DB |
| `app/tg_file_deliveries.py` (new) | snapshot/hash/accept/status/state/CAS/FIFO lease/recovery/cleanup/lifecycle single owner | TG route, main lifecycle, MCP status through HTTP |
| `app/routes/tg.py` | replace only `/api/tg/send_file`; add `/api/tg/file-deliveries/{event_id}` | current MCP `send_file`, internal auth middleware, safe paths |
| `app/tg_bridge.py` | add `_submit_file_snapshot_once`; do not alter old retry/isolated/text/mirror lanes | current TG bridge callers and existing bridge tests |
| `app/mcp_stdio.py` | C5 `send_file` wrapper, reconciliation helper, `file_delivery_status`, read-only registry | agents, `send_chart`, artifact fallback |
| `app/main.py` | start file service after bridge readiness; stop it before bridge bot close | HTTP startup latency, restart/shutdown lifecycle |
| `docs/tasks/333/acceptance/*` | immutable oracle; no Phase-3 edits | executor and orchestrator acceptance |

Do not touch deployment units, `.env`, `uv.lock`, current tests under `tests/`, Telegram config,
`app/message_deliveries.py`, `app/initial_deliveries.py`, C2/C3 code or the live DB/service.

## Tickets

### T1 — Durable primary receipt, snapshot, state and recovery

- Files: `app/db.py`, new `app/tg_file_deliveries.py`, `app/routes/tg.py`,
  `app/tg_bridge.py`, `app/main.py`.
- Test: `docs/tasks/333/acceptance/test_tg_file_delivery_333.py` tests named
  `test_t333_t1_*` — committed RED in `3907df87`.
- RED command: `uv run python -m pytest -q docs/tasks/333/acceptance/test_tg_file_delivery_333.py -k 't333_t1'`.
- Observed RED: exit 1, `AssertionError: #333 RED: /api/tg/send_file still reports synchronous provider success` (`assert 200 == 202`); five behavior tests failed, no collection/import error.
- AC: the RED command is green; exact schema/snapshot/hash/state/recovery/provider-boundary
  contract above holds; `uv run python -m pytest -q tests/test_tg_bridge.py::TestSendFileRouting`
  is green; no live provider/service path is reached.
- blocked-by: none.

### T2 — Durable chat FIFO/backpressure and primary/mirror child truth

- Files: `app/tg_file_deliveries.py`, `app/db.py` only if an index/constraint from the schema above
  was not completed by T1; no legacy mirror worker changes.
- Test: same frozen file, tests named `test_t333_t2_*` — committed RED in `3907df87`.
- RED command: `uv run python -m pytest -q docs/tasks/333/acceptance/test_tg_file_delivery_333.py -k 't333_t2'`.
- Observed RED: exit 1, first failure `assert [200, 200] == [202, 202]`; three behavior tests
  failed, positive fake controls are outside this selector and already green.
- AC: the RED command is green; two concurrent production runners produce one FIFO provider call
  per event under one persisted positive generation; injected full capacity returns typed 429
  without row/snapshot/call; mirror UNKNOWN leaves primary/top SENT; `uv run python -m pytest -q
  tests/test_tg_bridge.py::TestTgMirrorIsolation` is green.
- blocked-by: T1.

### T3 — C5 MCP/status compatibility, retention and rollback

- Files: `app/mcp_stdio.py`, `app/tg_file_deliveries.py`, `app/routes/tg.py`, `app/main.py`.
- Test: same frozen file, tests named `test_t333_t3_*` — committed RED in `3907df87`.
- RED command: `uv run python -m pytest -q docs/tasks/333/acceptance/test_tg_file_delivery_333.py -k 't333_t3'`.
- Observed RED: exit 1; route cases fail `assert 200 == 202`, and the isolated wrapper case fails
  `AssertionError: #333 RED: legacy send_file did not mint one durable id before POST`; three
  behavior tests failed.
- AC: the RED command is green; legacy three-argument calls still return `str` but carry accepted
  semantics/durable id; ambiguous POST reconciles with one same-id GET; status is owner-scoped and
  read-only; SENT cleanup/UNKNOWN quarantine/disabled-admission rollback obey the contract; `uv run
  python -m pytest -q tests/test_charts.py -k 'send_chart' tests/test_message_delivery_receipts_380.py`
  is green.
- blocked-by: T1, T2.

## Final Phase-3 verification (after all tickets, not authorized yet)

1. Before each ticket, rerun its exact selector and confirm the missing behavior remains RED.
2. After each ticket, rerun its exact selector plus the named existing regression command.
3. Verify oracle bytes against `3907df87`.
4. Run the combined fake-only acceptance file; it must report `13 passed`.
5. Run the repository full suite using the required command and inspect its saved log once:
   `uv run python -m pytest -x -q > /tmp/pytest-333.log 2>&1`.
6. Confirm `uv.lock` is unmodified and `git status` contains only the ticket's allowed files.
7. No live Telegram/media/provider call, restart, route switch or live DB mutation is an
   acceptance step.

## Review decision inputs

- Phase-2 changed consumers: documentation/oracle only; Phase-3 planned consumers are shared
  message delivery, queue/concurrency, persistence migration, auth and external HTTP/MCP contract.
- Author metadata from `/api/sessions` on 2026-08-24: model `gpt-5.6-sol`, runtime `codex`, role
  `full-cycle`, session `511fe481-a766-4e2b-843c-7c3462e2b70b`.
- Risk floor: high by persistence migration + shared delivery/concurrency + auth/external protocol.
- Exact AC and named commands: ticket sections above; positive harness command observed `2 passed`;
  combined command observed `11 failed, 2 passed`, exit 1, all failures are missing behavior.
- Canonical route would be a Sol plan review.  The task explicitly forbids auxiliary model/review
  calls in Phase 2; the separately approved Sol run is the future implementation executor, not a
  reviewer.  Therefore no model review was run and no approval verdict is claimed.  Mechanical
  adversarial evidence is recorded in `review-self.md`; orchestrator verification is the Phase-3
  gate.

