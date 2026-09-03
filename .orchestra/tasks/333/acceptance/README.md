# #333 frozen acceptance oracles — C1 + C5

These files are Phase-2 acceptance artifacts.  After the RED commit, every file under this
directory is immutable for Phase 3: do not edit, rename, skip, xfail, or weaken a test, fixture,
helper, selector, marker, or command.  All provider behavior is fake-only and all SQLite writes
use pytest `tmp_path`; the suite must not start Orchestra, call Telegram, restart a service, or
read/write the live database.

## Commands

Positive harness controls:

```bash
uv run python -m pytest -q docs/tasks/333/acceptance/test_tg_file_delivery_333.py -k 't333_control'
```

Ticket RED commands:

```bash
uv run python -m pytest -q docs/tasks/333/acceptance/test_tg_file_delivery_333.py -k 't333_t1'
uv run python -m pytest -q docs/tasks/333/acceptance/test_tg_file_delivery_333.py -k 't333_t2'
uv run python -m pytest -q docs/tasks/333/acceptance/test_tg_file_delivery_333.py -k 't333_t3'
```

Combined command:

```bash
uv run python -m pytest -q docs/tasks/333/acceptance/test_tg_file_delivery_333.py
```

## Oracle inventory

### T1-A — durable 202 and private immutable snapshot

- Test: `test_t333_t1_accepts_0600_snapshot_before_provider_and_source_can_disappear`.
- Production path: `app.routes.tg.tg_send_file` → `app.tg_file_deliveries.accept_file_delivery`
  → per-chat runner → `app.tg_bridge._submit_file_snapshot_once`.
- RED regression: the current route calls legacy `send_file_to_tg` synchronously and returns 200;
  the test requires a committed 202 receipt, an opaque distinct 0600 snapshot that survives source
  deletion, observable `SUBMITTING`, and final `SENT(message_id)` after exactly one fake call.
- Positive control: `test_t333_control_provider_double_reads_only_the_supplied_snapshot` proves the
  fake returns a message receipt and reads only its supplied path.
- Valid alternate: snapshot directory/name and extra receipt/status fields are unrestricted; a
  different internal scheduling implementation is valid if the same route behavior holds.
- Compound/fallback mutation: remove snapshot copy **and** route accepted work through legacy
  `send_file_to_tg`; the 200/legacy-call assertions fail before provider success can mask it.
- Command: T1 RED command above.

### T1-B — concurrent idempotence and payload conflict

- Test: `test_t333_t1_same_event_hash_is_one_acceptance_and_changed_hash_conflicts`.
- Production path: two concurrent POSTs through `tg_send_file` and the SQLite acceptance
  transaction, followed by the real status resource.
- RED regression: current POSTs are two unrelated 200 sends; required behavior is one `accept_seq`,
  one payload hash, one row, one provider call, `ACCEPTED` + `ALREADY_ACCEPTED`, then 409
  `IDEMPOTENCY_CONFLICT` when the source bytes change under the same event id.
- Positive control: the byte-identical concurrent arm must be accepted twice as one logical event.
- Valid alternate: either concurrent request may be the `ACCEPTED` one; response ordering and extra
  metadata are not fixed.
- Compound/fallback mutation: keep the unique event constraint but omit canonical payload compare,
  or compare caption/path while omitting bytes; the changed-byte 409 arm fails while the identical
  arm proves the request was otherwise acceptable.
- Command: T1 RED command above.

### T1-C — provider-boundary timeout is UNKNOWN, never replayed

- Test: `test_t333_t1_timeout_after_boundary_calls_provider_once_and_stays_unknown`.
- Production path: durable runner state transition `QUEUED → SUBMITTING`, one fake provider call,
  timeout classification, GET status, and same-id POST reconciliation.
- RED regression: current route has no receipt/state and its important lane may retry ambiguous
  failures; required behavior records `UNKNOWN`, non-retryable/outcome-unknown diagnostics and one
  call total even after the same event is posted again.
- Positive control: `test_t333_control_timeout_double_crosses_boundary_exactly_once` proves the
  timeout is raised only after the fake boundary is entered once.
- Valid alternate: the diagnostic may contain extra fields/text; state, booleans, next-action tool,
  stable event id and call count are fixed.
- Compound/fallback mutation: mark timeout UNKNOWN but leave the old important retry loop reachable,
  or requeue UNKNOWN on same-id POST; the final provider count catches both.
- Command: T1 RED command above.

### T1-D — crash recovery distinguishes QUEUED from SUBMITTING

- Test: `test_t333_t1_restart_replays_queued_but_converts_submitting_to_unknown`.
- Production path: additive SQLite rows → `app.tg_file_deliveries.recover_file_deliveries` → the
  production per-chat runner and status route.
- RED regression: no current durable state exists; after implementation a queued row must send once,
  an orphaned submitting row must become UNKNOWN without a provider call, and a second recovery must
  be idempotent.
- Positive control: the queued sibling reaches `SENT` through the fake provider after recovery.
- Valid alternate: recovery may group/schedule chats in any order; the two final states and exact
  per-payload call set are fixed.
- Compound/fallback mutation: blindly rewrite every nonterminal state to QUEUED, or correctly mark
  SUBMITTING unknown but let a generic fallback runner select it; the call count and second recovery
  catch both.
- Command: T1 RED command above.

### T1-E — known pre-submit failure is safe only under the same id

- Test: `test_t333_t1_pre_submit_snapshot_failure_is_retryable_with_same_event_only`.
- Production path: accepted row → `run_chat_deliveries` pre-boundary snapshot verification → status
  → same-event POST and runner.
- RED regression: a removed accepted snapshot must yield `FAILED_BEFORE_SUBMIT` without a provider
  call; restoring it from the still-matching source under the same event reuses `accept_seq` and
  sends once.
- Positive control: same-id explicit retry reaches `SENT` after the missing snapshot is recreated.
- Valid alternate: the failure message and snapshot filename are free; the state, safe-retry flags,
  unchanged sequence and zero/one call counts are fixed.
- Compound/fallback mutation: send before verifying the snapshot **or** mint a replacement event for
  retry; provider count or `accept_seq` catches the unsafe fallback.
- Command: T1 RED command above.

### T2-A — per-chat FIFO plus durable lease generation

- Test: `test_t333_t2_two_runners_keep_per_chat_fifo_and_one_lease_generation`.
- Production path: two accepted events → two concurrent calls to production
  `run_chat_deliveries(chat_id)` → `tg_file_chat_leases` generation/CAS → provider seam.
- RED regression: current queue is in-memory only; two durable runners must still produce first bytes
  then second bytes, one call each, with one positive stored lease generation on both target rows.
- Positive control: after releasing the first fake call both rows reach SENT in acceptance order.
- Valid alternate: task return values, owner tokens and generation numeric value are unrestricted;
  only positive/common generation, FIFO and call cardinality are fixed.
- Compound/fallback mutation: retain an in-process singleton but remove DB lease/generation, then
  invoke the second runner concurrently; the table/generation assertions prevent a green result
  based only on the singleton fallback.
- Command: T2 RED command above.

### T2-B — bounded backpressure is a known pre-accept rejection

- Test: `test_t333_t2_queue_full_returns_retry_after_without_snapshot_or_submit`.
- Production path: route → atomic admission capacity check with injected per-chat limit 1.
- RED regression: current request waits for/synchronously executes delivery; the full second event
  must return 429 `TG_FILE_QUEUE_FULL`, `Retry-After`, retryable=true, outcome_unknown=false, no row,
  no second snapshot and no provider call.
- Positive control: the already-accepted first event still reconciles with 202 while capacity is full.
- Valid alternate: production default capacity and exact positive Retry-After are not pinned; the test
  injects capacity 1 and accepts any integer Retry-After ≥1.
- Compound/fallback mutation: check only a global limit while per-chat admission is full, or reject
  after leaving an orphan snapshot; the second row/snapshot/call assertions catch both.
- Command: T2 RED command above.

### T2-C — mirror outcome cannot rewrite primary truth

- Test: `test_t333_t2_mirror_failure_never_rewrites_primary_sent`.
- Production path: one accepted file creates primary and mirror child rows, each using its own chat
  runner and the same one-call provider seam; GET returns both child receipts.
- RED regression: the current mirror is a best-effort in-memory side effect without a receipt;
  required behavior keeps top-level/primary SENT(message_id) while the timed-out mirror is UNKNOWN.
- Positive control: the primary fake branch returns a real message id and remains SENT.
- Valid alternate: the two chats may run in either order and status may include extra aggregate fields.
- Compound/fallback mutation: collapse child state into one parent state **or** catch mirror failure in
  the old best-effort fallback without persisting it; the required `children` mapping catches both.
- Command: T2 RED command above.

### T3-A — owner-scoped status and legacy string compatibility

- Test: `test_t333_t3_status_is_owner_scoped_and_legacy_tool_returns_durable_id`.
- Production path: authenticated status GET plus `app.mcp_stdio.send_file` POST and the new read-only
  `file_delivery_status` MCP tool.
- RED regression: the current wrapper returns a string claiming “sent” without a durable id; required
  behavior keeps a string return, mints/sends one event id, says accepted + state, exposes owner status,
  rejects a different valid MCP principal, and provides the read-only status tool.
- Positive control: owner GET and fake MCP receipt/status response both succeed.
- Valid alternate: exact human wording is free if it includes “accepted”, event id and state; extra
  tool/status fields are allowed.
- Compound/fallback mutation: implement 202 in the route but retain the legacy wrapper response/id-free
  POST, or expose an unauthenticated status route; the MCP payload/string and other-owner arms fail.
- Command: T3 RED command above.

### T3-B — legacy transport timeout reconciles before returning

- Test: `test_t333_t3_legacy_timeout_reconciles_same_generated_id_before_return`.
- Production path: `mcp_stdio.send_file` generates id → POST → `ApiToolError(outcome_unknown)` → GET
  `file_delivery_status` → compatible string result.
- RED regression: current wrapper has no pre-POST id and propagates the timeout; required behavior makes
  exactly POST then GET with the same id and returns the stored UNKNOWN receipt without a fresh POST.
- Positive control: fake GET returns an `ALREADY_ACCEPTED` receipt and the wrapper returns it.
- Valid alternate: reconciliation helper names and string punctuation are unrestricted.
- Compound/fallback mutation: generate a new id only after timeout, or retry POST before GET; the exact
  two-call trace and captured POST id catch both.
- Command: T3 RED command above.

### T3-C — retention, UNKNOWN quarantine and rollback

- Test: `test_t333_t3_cleanup_keeps_unknown_quarantine_and_rollback_never_replays`.
- Production path: terminal runners → `cleanup_file_deliveries(now=...)` → additive receipt tables;
  then `ADMISSION_ENABLED=False`, route/status and `recover_file_deliveries`.
- RED regression: required cleanup removes an old SENT snapshot but never its idempotency receipt,
  retains an UNKNOWN snapshot as 0600 under quarantine, rejects fresh admission with a known 503,
  keeps existing UNKNOWN status/reconciliation, and never submits it during recovery.
- Positive control: the SENT sibling is delivered and its bulky snapshot is actually cleaned; existing
  UNKNOWN remains readable after admission is disabled.
- Valid alternate: quarantine may add directory levels and diagnostics; receipt rows/unknown bytes,
  state, disabled-admission error and no-replay call count are fixed.
- Compound/fallback mutation: bulk-delete all terminal snapshots/rows **and** route disabled admission
  through legacy direct send; UNKNOWN file/row/status and new-event 503/provider count catch both.
- Command: T3 RED command above.

