# #382 — Phase 2 plan: canonical secret handling across persistence, streaming, and cache

Status: PLAN READY — supplemented RED frozen and independently approved
Research: `docs/tasks/382/research.md` (approved)
Security rule: only the synthetic fixture `tests/fixtures/t382_secret_canary.json` may be used.

## Objective

Eliminate the escaped/nested Codex MCP argv masking bypass from every enforceable Orchestra
persistence/display path, without reading or creating new copies of real credentials. A secret
assignment must never persist or stream the complete synthetic value or any fixture-designated
value fragment. Diagnostic output may retain the key name and value length, but never a tail.

Provider-native Codex rollout content created before Orchestra receives the tool output is outside
#382's enforceable boundary. Source prevention is owned by #31; #382 neither edits nor scans native
rollouts and makes no retroactive-protection claim.

## Fixed design decisions

### Canonical recognizer/parser owner

- `app.secret_mask` is the sole owner of named-secret recognition and replacement.
- Move/re-own bearer and PEM recognition there as needed; `runtime_history` imports the canonical
  API. Delete `_NAMED_SECRET`; do not add a third regex/parser copy.
- The parser recognizes assignment structure, not prose: a declared secret key must be followed by
  optional escaped quote layers and `:`/`=`. Words such as “token” or “password” without that
  structure remain byte-for-byte unchanged.
- Replacement contains length only, for example `[secret len=N]`. No tail, prefix, hash fragment,
  or other synthetic value substring is retained.
- Scanning is linear with bounded per-candidate state. `_MAX_SECRET_CANDIDATE_CHARS` is exactly
  65,536. A quoted candidate that does not terminate at the limit-1/limit/limit+1 boundaries fails
  closed by masking through the line/end boundary; it never grows an auxiliary buffer or leaves a
  prefix/suffix visible.
- Existing explicit non-secret controls such as `TEMPLATE_HASH` remain unchanged.

### Persistent ingress and egress policy

- Both `logs` insert seams use the canonical parser:
  `db.add_log` and `initial_deliveries.prepare_initial_delivery`.
- One `db.py` row-sanitization helper is the completed-log egress boundary. It is called by
  `get_logs`, `get_logs_before`, `get_log`, `get_logs_sync`, and `get_history_logs`. REST, SSE and
  TG remain wiring consumers and contain no redactor copies.
- `initial_deliveries.message`: reject a secret-shaped durable task before any row is inserted;
  return HTTP/domain status 422 and code `SECRET_CONTENT_REJECTED`. Benign security prose is
  accepted unchanged. This avoids silent task mutation and avoids introducing encryption/vault
  scope.
- `tool_errors.error_text`: mask before INSERT; analytics consumes the stored sanitized value.
- DB-write failure journal: log the canonical sanitized candidate, never the original content.
- `sessions.last_summary`: sanitize centrally in `save_session` before INSERT/UPDATE so every
  Claude/native summary caller inherits the rule.
- RAG `log_chunks.text` and `fts_logs.text`: sanitize before chunking/indexing. Embeddings are
  derived only from sanitized text.
- `runtime_handoffs.packet_json`: the builder and actual SQLite record must contain canonical
  sanitized content. Hash-only snapshot/reference fields remain unchanged.

### Bounded fail-closed live streaming

Per-chunk regex masking is unsound because a key/value may be split at any byte/character boundary.
#382 therefore withholds arbitrary partial **content** for these exact seven live event classes:

1. `stream`
2. `subagent_stream`
3. `thinking_stream`
4. `tool_stream`
5. `tool_patch`
6. `turn_diff`
7. `subagent_event`

`type`, ids, activity/status metadata and the exact non-sensitive marker
`[live content withheld for secret safety]` still flow. Completed authoritative events (`text`,
`thinking`, `tool`, `tool_result`, file completion)
later travel through the canonical DB corridor. For ephemeral-only subagent detail, the detailed
partial UX is intentionally lost; security outranks cosmetic fidelity.

No arbitrary partial content is accumulated. `_accum`/replay are bounded by 4,096 characters per
session. A subscriber queue stays at or below 256 records and 32,768 retained content characters,
and every retained record contains only the exact marker. Publishing 2,000 synthetic 4 KiB
partials must complete in under 2 seconds on the test host. These are deliberately generous safety
bounds, not performance optimization targets.

### Browser log-content epoch

- Keep IndexedDB database `orchestra` at schema version 1. No version bump and no primary
  `deleteDatabase()` path.
- Server owns a positive monotonic `LOG_CONTENT_EPOCH` and exposes it as
  `data-log-content-epoch` in initial HTML, `content_epoch` in sync JSON, header
  `X-Orchestra-Log-Content-Epoch` on REST history/full-row fetch, and `content_epoch` on the SSE
  handshake plus each event.
- `_storeOpen().onsuccess` assigns the raw database then runs a dedicated direct `readwrite`
  transaction over `logs+meta`. It does not call `_storeTx` through the unresolved open promise.
  Store readiness resolves only after epoch validation completes.
- One named promise/mutex boundary, `_storeApplyEpochBatch`, owns **all** sync/REST/SSE epoch
  transitions and row writes. For response epoch `R` and highest accepted epoch `H`:
  - `R < H`: discard without writing;
  - `R == H`: write rows;
  - `R > H`: in one transaction clear `logs` and stale meta, write `R`, then write only rows from R.
- Transaction abort leaves the old epoch and old rows together. It must not advance the epoch or
  render before completion.
- New-code sibling tabs receive a BroadcastChannel notification and reopen behind the same barrier.
- Pre-feature tabs cannot be erased automatically. First rollout requires **operator-confirmed
  closure** of every pre-feature dashboard tab before reset/reopen. The plan explicitly does not
  claim automatic old-code-tab erasure; without confirmation rollout remains blocked.

## Files expected in Phase 3

| File | Intended change | Tickets |
|---|---|---|
| `app/secret_mask.py` | canonical linear recognizer, no tail, false-positive/bound policy | T1 |
| `app/runtime_history.py` | consume canonical API; remove duplicate named matcher | T1, T4 |
| `app/db.py` | log ingress/egress helper, tool error, summary, handoff persistence | T1-T4, T6 |
| `app/initial_deliveries.py` | reject secret-shaped new delivery; protect legacy direct log insert | T3 |
| `app/session.py` | sanitize failure journal; completed/partial wiring | T2, T3, T5 |
| `app/usage_analytics.py` | wiring regression only if sanitized DB value needs normalization | T2 |
| `app/rag.py` | sanitize before chunk/index | T4 |
| `app/live_broker.py` | bounded metadata-only partial delivery/replay | T5 |
| `app/routes/sessions.py` | content epoch on log REST/SSE contracts | T1, T6 |
| `app/templates/dashboard.html` | initial content epoch delivery | T6 |
| `app/static/js/app.js` | same-version atomic epoch barrier and ordered writers | T6 |
| uniquely named `tests/test_t382_*.py` + fixture | frozen acceptance oracles; immutable in Phase 3 | T1-T6 |

## What Phase 3 must not touch

- real production DB, browser profile, process argv, environment files, or native rollout files;
- provider-native rollout persistence or #31's source-prevention architecture;
- enterprise vault/encryption integration;
- unrelated log formatting, dashboard redesign, schema migrations, deploy/restart/cache clearing;
- frozen #382 test files/fixture, pytest configuration, fixtures outside the uniquely named #382
  files, markers or test selection.

## Tickets

### T1 — Completed Codex event: canonical parser -> SQLite -> DB/history egress

- Vertical outcome: a production-serialized nested Codex tool event is masked by the one canonical
  owner, persists safely through `add_log`, and a deliberately raw legacy row leaves every completed
  log getter sanitized; REST/SSE/TG are proven to use that boundary without private redactors.
- Files: `app/secret_mask.py`, `app/runtime_history.py`, `app/db.py`,
  `app/routes/sessions.py`; frozen `tests/test_t382_completed_log_corridor.py` and fixture.
- Test: `/home/kesha/orchestra/.venv/bin/python -m pytest tests/test_t382_completed_log_corridor.py -q`
  — committed RED in `85c0db94`.
- RED reason: `AssertionError: the complete synthetic credential survived`.
- AC: the named command is green; raw SQL contains no complete canary/forbidden fragment/tail;
  benign prose is byte-for-byte unchanged; direct simple replacement is exactly `[secret len=N]`;
  every 4-character fixture substring is absent; 65,536 candidate-budget edges fail closed;
  `runtime_history._NAMED_SECRET` is absent; all five completed/history getters are covered; REST,
  SSE and TG getter wiring is behaviorally intercepted; 500 scans of 4 KiB complete under 2 seconds.
- blocked-by: none

### T2 — Failed tool event: telemetry table + analytics + failure journal

- Vertical outcome: a failed tool event cannot fork raw content into `tool_errors`, reliability
  analytics, or the DB-write failure journal.
- Files: `app/db.py`, `app/session.py`, optionally wiring-only `app/usage_analytics.py`; frozen
  `tests/test_t382_error_telemetry_corridor.py` and fixture.
- Test: `/home/kesha/orchestra/.venv/bin/python -m pytest tests/test_t382_error_telemetry_corridor.py -q`
  — committed RED in `85c0db94`.
- RED reason: `assert CANARY not in text` for raw `tool_errors.error_text` and the failure journal.
- AC: the named command is green; direct `tool_errors.error_text`, analytics JSON and captured
  failure log contain no canary/forbidden fragment/tail; benign prose remains unchanged.
- blocked-by: T1

### T3 — Durable initial delivery and session summary policy

- Vertical outcome: secret-shaped new initial delivery is rejected before persistence, a legacy
  queued delivery still produces a sanitized `logs` row, and every `last_summary` save is safe.
- Files: `app/initial_deliveries.py`, `app/db.py`, `app/session.py`; frozen
  `tests/test_t382_durable_delivery_summary.py` and fixture.
- Test: `/home/kesha/orchestra/.venv/bin/python -m pytest tests/test_t382_durable_delivery_summary.py -q`
  — committed RED in `85c0db94`.
- RED reason: `secret-shaped durable task must fail closed ... got status=202, rows=1`.
- AC: the named command is green; secret-shaped accept returns 422/
  `SECRET_CONTENT_REJECTED` with zero `initial_deliveries` rows; benign prose returns 202 and is
  stored exactly; legacy direct log insert and `sessions.last_summary` raw SQL contain no
  canary/fragment/tail.
- blocked-by: T1

### T4 — History-derived stores: native imports + handoff packet + RAG plaintext

- Vertical outcome: a raw synthetic legacy row cannot reappear in Claude/Codex import objects,
  event export, persisted `runtime_handoffs.packet_json`, `log_chunks`, or `fts_logs`.
- Files: `app/runtime_history.py`, `app/db.py`, `app/rag.py`; frozen
  `tests/test_t382_history_derived_stores.py` and fixture.
- Test: `/home/kesha/orchestra/.venv/bin/python -m pytest tests/test_t382_history_derived_stores.py -q`
  — committed RED in `85c0db94`.
- RED reason: `assert CANARY not in text` for native history, persisted handoff packet, and RAG
  plaintext chunks.
- AC: the named command is green; recursive import/export output and raw SQL for each named store
  contain no canary/fragment/tail; RAG benign prose is unchanged; no provider-native rollout is
  opened or modified.
- blocked-by: T1

### T5 — Bounded fail-closed content withholding for all seven live branches

- Vertical outcome: no subscriber or replay can reconstruct a secret split at any boundary, while
  metadata remains delivered with fixed memory and latency bounds.
- Files: `app/live_broker.py`, `app/session.py`; frozen
  `tests/test_t382_bounded_live_stream.py` and fixture.
- Test: `/home/kesha/orchestra/.venv/bin/python -m pytest tests/test_t382_bounded_live_stream.py -q`
  — committed RED in `85c0db94`.
- RED reason: `assert CANARY not in text` across all seven event classes/splits; current replay also
  retains `557056` characters above the `4096` bound.
- AC: the named command is green for all seven classes and every split boundary; combined
  subscriber output and stream replay contain no canary/fragment/tail; replay state is <=4096
  characters after 256 ordinary chunks; subscriber queue <=256 records/32768 content chars after
  2000 events; 2000 x 4 KiB publishes complete under 2 seconds; every content is the exact withheld
  marker and ids/type/activity metadata remain intact.
- blocked-by: T1

### T6 — Ordered same-version browser content epoch with two tabs

- Vertical outcome: old IndexedDB rows are cleared before first read without versionchange, abort
  is atomic, and a delayed lower-epoch sync/REST/SSE result cannot repopulate after a higher epoch.
- Files: `app/db.py`, `app/routes/sessions.py`, `app/templates/dashboard.html`,
  `app/static/js/app.js`; frozen `tests/test_t382_browser_content_epoch.py` and fixture.
- Test: `/home/kesha/orchestra/.venv/bin/python -m pytest tests/test_t382_browser_content_epoch.py -q`
  — committed RED in `85c0db94`.
- RED reason: `logs/sync does not expose the #382 content epoch`; a second version-1 tab reads the
  synthetic stale row and `_storeApplyEpochBatch` is absent.
- AC: the named command is green; positive epoch is delivered; two version-1 tabs complete without
  `blocked` within 2 seconds; the injected abort positively fires and leaves old epoch+row together;
  N after N+1 is discarded across one `_storeApplyEpochBatch` barrier; actual sync/REST/SSE paths
  are intercepted through that barrier; HTML/sync/REST/full-row/SSE contracts all carry epoch;
  BroadcastChannel closes/reopens a sibling connection; only the higher-epoch row remains; the
  isolated server uses a minimal allowlisted/blank environment and cannot load `.env`; plan retains
  the explicit operator-confirmed closure gate and no automatic old-code-tab claim.
- blocked-by: T1

## Dependency order and overlap

```text
T1
├── T2  (overlaps app/db.py + app/session.py with T3/T5; serialize implementation)
├── T3
├── T4  (overlaps runtime_history.py with T1; starts after T1)
├── T5
└── T6  (overlaps app/db.py/routes with T1; starts after T1)
```

Although T2-T6 are logically independent after T1, their implementation files overlap. Phase 3
must serialize overlapping changes; do not split a ticket or run two executors against the same
file.

## Frozen-oracle rules

- The six named files and the fixture are immutable after the RED commit. Phase 3 must not edit,
  delete, rename, skip, xfail, weaken, or replace them.
- Every ticket begins by rerunning its exact command and observing the registered missing-behavior
  assertion. Green/missing/broken collection stops implementation.
- Mutation validation occurs only after implementation turns the oracle green. Each mutation is
  one-at-a-time with pre/post marker counts, restore, `touch`, and a green rerun.
- No test depends on provider availability, production state, live browser profile, or any real
  credential.

## Review decision gate

- Changed artifacts: `plan.md`, six uniquely named #382 test files, one synthetic fixture;
  consumers are every Phase 3 ticket listed above.
- Author runtime: Codex; exact model identifier is not exposed in worker-visible metadata and is
  not used to lower risk.
- Exact AC: each ticket's named command plus its verbatim non-test constraints.
- Oracle state: pending RED registration below; no existing strong oracle covers the new behavior.
- Route: direct Sol because this is a high-risk secrets/persistence/shared-stream/cache plan.

## RED registration

To be filled from the exact commands before review:

| Ticket | Exit | First missing-behavior line |
|---|---:|---|
| T1 | 1 | `5 failed, 4 passed` — serializer, exact no-tail form, fixed budget, SQL/getters |
| T2 | 1 | `2 failed, 1 passed` — raw tool error and journal contain the canary |
| T3 | 1 | `3 failed, 1 passed` — accepted 202/row plus raw legacy log and summary |
| T4 | 1 | `3 failed, 1 passed` — native history, packet SQL and RAG SQL retain canary |
| T5 | 1 | `24 failed, 1 passed` — branches/splits/replay/accum/queue bounds and exact marker |
| T6 | 1 | `9 failed, 1 passed` — all epoch surfaces, abort, two-tab, writers, ordering, broadcast |

Superseded oracle audit: commit `55499ded` is **excluded** from Phase 3 replay because independent
review found missing history-getter, candidate-budget, abort-positive-control, writer/surface,
subprocess-isolation, queue-byte, metadata and behavioral-wiring coverage. No implementation was
run against it. The supplemented files are frozen in `85c0db94`; only that commit is valid for
Phase 3, and `git diff 85c0db94 -- tests/fixtures/t382_secret_canary.json
tests/test_t382_*.py` must then remain empty.

## Rollout note (not Phase 2/3 authorization)

No deploy, restart, live cache clear or production scan is authorized. When implementation is
eventually approved and merged, the first browser rollout remains blocked until the operator
confirms every pre-feature dashboard tab is closed. This is an operational precondition, not an
automatic guarantee of the new client code.

## Independent review outcome

Review route: direct Sol, two rounds, artifact `docs/tasks/382/review-plan.md`.

- Round 1 confirmed all six commands were honest RED with no import/collection/provider failure,
  then found seven blocking oracle gaps and two suggestions.
- Each finding was verified and accepted. The first freeze `55499ded` is excluded; the supplemented
  immutable oracle is `85c0db94`.
- Round 2 reproduced the registered counts exactly (T1 5/4, T2 2/1, T3 3/1, T4 3/1, T5 24/1,
  T6 9/1), marked every prior item fixed, found no new blockers/suggestions, and returned
  `APPROVED`.
- Review evidence criterion: the reviewer quoted the plan line “Although T2-T6 are logically
  independent after T1, their implementation files overlap.” The exact line is present above.
