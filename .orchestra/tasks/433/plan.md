# #433 — plan: structured message provenance (B1)

## Approved architecture receipt

User decision, relayed verbatim by `Orchestra-orchestrator` on 2026-09-02:

> «B1 — категория + структурный список отправителей, почтовый ящик умеет слить несколько агентов в одно сообщение, скаляр там врёт».

Canonical contract:

- `origin` is exactly `user | agent | background_task | platform | system | unknown`.
- `origin_detail` is structured JSON with a non-empty `senders` array and optional non-empty stable `subtype` / `ref`.
- Every new delivery constructs provenance before `SessionManager.send`; omission is a loud error. `unknown` is passed explicitly only when the source is genuinely unavailable.
- Only `origin == 'user'` renders right. Missing, malformed, invalid, and explicit `unknown` render left with a visible Unknown label.
- Runtime code never derives origin/subtype/ref from `content`. Model-facing prefixes may remain a derived presentation, but are never authoritative or parsed.
- Historical classification is one offline idempotent migration: durable receipts first, frozen prefixes second, explicit 181-class rules third, remainder `unknown`.

## Ordering and fresh-main gate

Implementation order is fixed externally: merge #436 first → implement #433 → atomically move files in #430. #438 currently owns `app/session.py` and `app/session_turns.py`.

Before T1 touches code:

1. Confirm #436 and #438 are merged into `main`; if this worktree does not contain both merged results, STOP and ask the orchestrator to refresh/switch it before any implementation.
2. Re-read from the refreshed working tree: `app/db.py`, `app/mcp_stdio.py`, `app/codex_review_artifact.py`, `app/session.py`, `app/session_turns.py`, `app/backend_claude.py`.
3. Re-run the semantic writer inventory and all five RED commands. Every command must still fail for its frozen missing behavior. Already-green, missing, collection-error, or premise drift → STOP; do not edit an oracle or implement around it.
4. Recompute the 29 ingress calls semantically. A new ingress discovered after #436/#438 must use the same required provenance boundary; the T3 AST oracle scans current `app/**/*.py` rather than pinning the historical count.

Read-only conflict files: `app/codex_review_artifact.py` and `app/backend_claude.py` are re-read because #436/#438 change adjacent contracts, but #433 does not edit them.

## Storage and API shape

- Add `logs.origin TEXT NOT NULL DEFAULT 'unknown'` with a finite-value constraint.
- Add `logs.origin_detail TEXT NOT NULL DEFAULT '{"senders":["unknown"]}'`; application validation owns JSON structure and non-empty strings.
- `MessageProvenance` in `app/events.py` validates the finite origin, de-duplicates non-empty `senders` while preserving order, and serializes/deserializes canonical JSON. `subtype` and `ref` default to absent/empty but cannot contain blank-only values when present.
- T1 introduces the value without changing send signatures. T2 atomically changes `SessionManager.send(..., *, provenance)`, `AgentSession.send(..., *, provenance, delivery=None)`, both durable manager methods, and every caller in the same ticket; there is no intermediate commit where existing delivery paths raise `TypeError`. `AgentSession._log` / `db.add_log` reject a `user_message` without provenance; non-user log types keep their current callers.
- `InjectedMessage` carries `MessageProvenance` plus `event_id`; the old free-form `origin="orchestra.bg_jobs"` / `job_id` duplication is replaced by `origin=background_task`, `subtype`, and `ref`.
- Durable receipt tables persist the structured provenance accepted with the receipt so retry/recovery cannot reclassify after sender/session state changes. Receipt provenance is included in the idempotency payload hash. Their schema version advances for B1: the offline migration reconstructs provenance only for pre-B1 receipt versions; an explicit `unknown` accepted under the B1 version is immutable and cannot be reclassified from its text/source fields.
- SQLite stores `origin_detail` as canonical JSON text. All `db.get_log/get_logs/get_logs_before/get_logs_sync` read boundaries decode it to a dict; `_SYNC_COLS` explicitly projects both new fields. Snapshot/SSE/MCP/TG/RAG therefore consume a dict and never a JSON-encoded string. Migration/raw SQL alone operate on storage text.

## Producer mapping

- `user`: authenticated dashboard/operator send, dashboard voice, TG batch, TG restart inbox replay.
- `agent`: MCP direct send, initial task delivery, explicit/automatic worker report, quota notice attributed to its worker, mailbox batch with all distinct senders in order.
- `background_task`: bg terminal results, cron/cron-command result, limit-wake result; job id/token lives in `ref`, outcome in `subtype`.
- `platform`: fan manifests, bug-report/undelivered notices, compaction input, Orchestra-owned context/notification messages.
- `system`: restart/retry/auto-continue and external CI/system notices; retry kind lives in `subtype`.
- `unknown`: only explicit compatibility/unprovable cases. It is never the default argument of a send API and never renders right.

Initial-delivery history rule: `sender` matching a session with the same scope → operational `agent`; mismatch → `unknown`. Direct-message history rule: `source_principal LIKE 'operator:%' → user`, `source_principal LIKE 'mcp:%' → agent`; malformed/empty principal falls through to later rules or `unknown`.

## Runtime consumer changes

- `chat.js`: render classes and labels from `payload.origin` + `payload.origin_detail`; never strip/inspect `[HH:MM]`, `[from:]`, background, platform, or system text for provenance.
- `tg_bridge.py`: label mirrored inputs from fields; no `[from:]` parsing.
- `rag.py`: `_classify_log` receives origin/detail; contradictory content cannot override the field.
- `session.py` text tail and `runtime_history.py`: platform exclusion uses `origin`, not content.
- `session.py` retry accounting uses `subtype`, not `[system] Retrying...`.
- `limit_wake.py` uses structured `origin/subtype/ref` for token visibility and exclusion; no content `LIKE`/`startswith` lookup.
- `mcp_stdio.get_worker_logs`: icons/labels reflect structured origin rather than treating all `user_message` rows as human.

## Migration and production safety

`scripts/migrate_message_provenance_433.py` accepts an explicit `--db` path, defaults to dry-run, and requires `--apply` to mutate. It does not import/use the process-global production `DB_PATH` as an implicit target.

Classification precedence:

1. Receipt joins: `message_deliveries.source_principal`, then `initial_deliveries.sender + same-scope session match`.
2. Frozen leading prefixes: `[from:]`, `[Background job...]`, `[Orchestra platform...]`, `[HH:MM]`, `[from TG:]`.
3. Explicit 181 rules: `[system]`, compaction summaries, `НЕДОСТАВКА:`, `BUG REPORT платформы:`, fan manifests, cron, `LIVE-USER-*`.
4. Remainder: explicit `unknown` + `senders=["unknown"]`.

The CLI prints one machine-readable JSON summary with exact keys `mode,target,rows_before,rows_after,sessions_before,sessions_after,counts,invalid,would_update,updated`; `counts` contains all six origin keys. Default invocation is dry-run. `--apply` wraps the entire update in one transaction; a mid-batch trigger failure must roll back every row. `--backup PATH` uses `sqlite3.Connection.backup` before apply and is mandatory for production apply. Re-run after success reports `updated=0,would_update=0`. It never deletes rows.

Phase 3 may run `--apply` only on a temporary DB. Any command against the production DB—including a production dry-run/apply requested for acceptance—waits for the orchestrator's separate explicit authorization. Before and after every allowed run, independently query the production `sessions` count; it must be identical.

After separately authorized production apply, an independent read-only SQLite query—not the migration's own summary—must prove for the frozen cohort `ts >= '2026-08-25' AND id <= 562928`:

- `COUNT(*) = 2738`;
- `origin='user' = 940`;
- `origin IS NULL OR origin='' OR origin NOT IN (...) = 0`;
- invalid JSON, empty/missing `senders`, or blank sender values = 0.

## Files

Production scope approved for Phase 3:

- Contract/persistence: `app/events.py`, `app/db.py`, `app/session.py`, `app/manager.py`, `app/initial_deliveries.py`, `app/message_deliveries.py`.
- Producers: `app/bg_jobs.py`, `app/notify.py`, `app/restart_inbox.py`, `app/session_turns.py`, `app/fan_barrier.py`, `app/limit_wake.py`, `app/routes/tg.py`, `app/routes/system.py`, `app/routes/sessions.py`, `app/tg_bridge.py`, `app/mcp_stdio.py`.
- Consumers: `app/rag.py`, `app/runtime_history.py`, `app/static/js/chat.js`.
- Migration: `scripts/migrate_message_provenance_433.py`.
- Immutable RED oracles: `docs/tasks/433/test_t1_provenance_contract_433.py`, `test_t2_writer_seams_433.py`, `test_t3_ingress_consumers_433.py`, `test_t4_frontend_origin_433.py`, `test_t5_offline_migration_433.py`.
- Task artifacts / personal memory if warranted: `docs/tasks/433/`, `docs/workers/feat-msg-origin.md`.

Do not touch: `app/static/js/app.js`, CSS, `app/codex_review_artifact.py`, `app/backend_claude.py`, #430 relocation code, unrelated refactors/tests, or any test/oracle/config/fixture outside the approved `_433` files.

## RED oracle record

Final frozen oracle commit: `de813880`.

Excluded oracle history:

- `f3ff31bd` T4 contained the expected origin word in its body and could satisfy the visible-label assertion without a label; `05327bf1` re-froze T4 with neutral bodies.
- `05327bf1` T1/T2/T3/T5 are excluded after Luna round 1: T1 prematurely required the send API, T2 checked representation instead of persistence/atomicity, T3 missed durable/behavioral consumers, and T5 missed CLI path/dry-run/rollback/WAL/precedence. `78bd511e` replaces those bytes. T4 is byte-identical to its valid `05327bf1` version.
- `78bd511e` T2/T3/T4/T5 are excluded after final Luna round 2: `_log` forwarding, receipt/hash/manager replay, real HTTP/SSE, malformed explicit-user detail, pre-B1 receipt versioning and full counters were still open. `de813880` closes those oracle gaps. T1 is byte-identical to its valid `78bd511e` version.

All commands collected successfully and exited 1 for missing behavior, not import/collection failure:

- T1: `env PYTHONPATH=. uv run pytest -q docs/tasks/433/test_t1_provenance_contract_433.py` → `2 failed`; first assertion: `#433 T1 missing behavior: MessageProvenance B1 value object is absent`.
- T2: `env PYTHONPATH=. uv run pytest -q docs/tasks/433/test_t2_writer_seams_433.py` → `7 failed`; distinct session/compact/db/durable assertions, first: `#433 T2 missing writer behavior at distinct seam: session.send.compacting has no B1 value`.
- T3: `env PYTHONPATH=. uv run pytest -q docs/tasks/433/test_t3_ingress_consumers_433.py` → `18 failed`; first: `#433 T3 missing producer behavior: provenance is omitted before send at ...` plus durable manager, runtime-history, retry, DB/HTTP/SSE/sync, TG/MCP, mailbox, RAG and limit-wake behavior.
- T4: `env PYTHONPATH=. uv run pytest -q docs/tasks/433/test_t4_frontend_origin_433.py` → `1 failed`; assertion: `#433 T4 unsafe fallback: agent origin rendered as the user`; the test checks actual class and `getComputedStyle` and includes missing/invalid negative controls.
- T5: `env PYTHONPATH=. uv run pytest -q docs/tasks/433/test_t5_offline_migration_433.py` → `1 failed`; assertion: `#433 T5 missing behavior: offline provenance migration script is absent`; after implementation it exercises distinct global/explicit DB paths, default dry-run, trigger rollback, WAL snapshot, backup, conflicting precedence and second-run no-op.

## Tickets

### T1 — Ship the lossless B1 envelope on the existing background injection

- Ships: validated finite origin, order-preserving/deduplicated sender list, canonical JSON round-trip, subtype/ref validation, and `InjectedMessage.provenance`; the sole current `InjectedMessage` producer is updated without changing send signatures yet.
- Files: `app/events.py`, `app/bg_jobs.py` (`_terminal_message` constructor only).
- Test: `docs/tasks/433/test_t1_provenance_contract_433.py` — committed RED in `de813880`; `env PYTHONPATH=. uv run pytest -q docs/tasks/433/test_t1_provenance_contract_433.py` exits 1 at `#433 T1 missing behavior: MessageProvenance B1 value object is absent`.
- AC: the named command is green; JSON is byte-canonical; duplicate senders preserve first-seen order; invalid origin, empty/blank senders, blank subtype/ref are rejected; `InjectedMessage` has no legacy `origin`/`job_id` duplicate. Existing bg-job tests stay green.
- blocked-by: none (plus external fresh-main gate #436/#438).

### T2 — Switch every producer and persist provenance atomically through all six writer seams

- Ships: one atomic cut: schema + required send boundary + all ordinary/durable producers + round-trip persistence for queued/running/new-turn logs, compaction, initial-delivery and direct-message transactions. There is no intermediate commit with required arguments and unconverted callers. Durable retries reuse immutable receipt provenance.
- Files: `app/db.py`, `app/session.py`, `app/manager.py`, `app/initial_deliveries.py`, `app/message_deliveries.py`, `app/events.py`, `app/bg_jobs.py`, `app/notify.py`, `app/restart_inbox.py`, `app/session_turns.py`, `app/fan_barrier.py`, `app/limit_wake.py`, `app/routes/tg.py`, `app/routes/system.py`, `app/routes/sessions.py`, `app/tg_bridge.py`, `app/mcp_stdio.py`.
- Test: `docs/tasks/433/test_t2_writer_seams_433.py` — committed RED in `de813880`; `env PYTHONPATH=. uv run pytest -q docs/tasks/433/test_t2_writer_seams_433.py` exits 1 with seven behavior failures; first is `#433 T2 missing writer behavior at distinct seam: session.send.compacting has no B1 value`.
- AC: the named command and `env PYTHONPATH=. uv run pytest -q docs/tasks/433/test_t3_ingress_consumers_433.py::test_t3_every_ingress_constructs_provenance_before_send` are green; trigger-forced durable failures leave `state=QUEUED` and zero user logs; successful rows round-trip exact provenance in the same transaction; focused durable suites are green.
- blocked-by: T1.

### T3 — Convert every server consumer and API boundary to structured fields

- Ships: mailbox keeps every sender; DB/API/sync returns detail objects; TG/RAG/history/retry/wake/MCP-log consumers use fields; seven provenance/subtype content parsers are removed. Producer wiring is already shippable from T2 and remains guarded by this suite.
- Files: `app/events.py`, `app/bg_jobs.py`, `app/notify.py`, `app/restart_inbox.py`, `app/session_turns.py`, `app/fan_barrier.py`, `app/limit_wake.py`, `app/routes/tg.py`, `app/routes/system.py`, `app/routes/sessions.py`, `app/manager.py`, `app/session.py`, `app/tg_bridge.py`, `app/mcp_stdio.py`, `app/rag.py`, `app/runtime_history.py`.
- Test: `docs/tasks/433/test_t3_ingress_consumers_433.py` — committed RED in `de813880`; `env PYTHONPATH=. uv run pytest -q docs/tasks/433/test_t3_ingress_consumers_433.py` exits 1 with 18 distinct failures; first is `#433 T3 missing producer behavior: provenance is omitted before send at ...`.
- AC: the named command is green; contradictory content cannot override RAG/history/retry/wake fields; mailbox preserves `agent-a,agent-b`; DB snapshot/before/single/sync boundaries return detail dicts and `_SYNC_COLS` projects both fields; TG/MCP labels are field-driven; no forbidden parser anchor remains; named focused regressions are green.
- blocked-by: T2.

### T4 — Render only explicit users on the right

- Ships: one field-driven dashboard renderer for snapshot and SSE rows. Agent/background/platform/system/unknown/missing/invalid entries are visible left bubbles with exact/stable labels; only explicit user is right.
- Files: `app/static/js/chat.js`.
- Test: `docs/tasks/433/test_t4_frontend_origin_433.py` — committed RED in `de813880`; `env PYTHONPATH=. uv run pytest -q docs/tasks/433/test_t4_frontend_origin_433.py` exits 1 at `#433 T4 unsafe fallback: agent origin rendered as the user`.
- AC: the named browser command is green; its class and `getComputedStyle` negative controls pass; `fromMatch`, platform-prefix hiding, and timestamp-prefix provenance parsing are absent; focused existing chat/frontend tests remain green.
- blocked-by: T2, T3.

### T5 — Backfill history offline and prove idempotency

- Ships: explicit-path dry-run-by-default migration; receipt-first/prefix-second/181-third classification; temp-DB apply and second-run no-op; machine-readable counters for the later production gate.
- Files: `scripts/migrate_message_provenance_433.py`.
- Test: `docs/tasks/433/test_t5_offline_migration_433.py` — committed RED in `de813880`; `env PYTHONPATH=. uv run pytest -q docs/tasks/433/test_t5_offline_migration_433.py` exits 1 at `#433 T5 missing behavior: offline provenance migration script is absent`.
- AC: the named command is green; explicit target differs from global DB; default dry-run mutates neither; trigger failure rolls back all rows; WAL reader retains its snapshot; `Connection.backup` image is pre-apply; receipt-vs-prefix conflicts prove precedence; JSON counters are complete; second apply reports `updated=0`; production invocation remains separately gated.
- blocked-by: T2, T3, T4.

## Verification and regression accounting

- Before implementation: run each named command and observe its frozen RED failure.
- After each ticket: its exact command green, then its named focused regressions; do not edit any file under `docs/tasks/433/test_t*_433.py`.
- Final full-suite comparison uses the same command and commit on base and branch, without `-x`; compare failed/error node-id sets, not counts. Preserve both raw logs. The task input says the current suite already has 47 failures and terminated near 82%; that number is context, not a waiver or baseline set.
- Tests/migrations use only explicit temporary DB paths. Record production `sessions` row count before/after every allowed DB probe; any difference is a stop condition.
- Before production migration: create a consistent SQLite backup with `sqlite3.Connection.backup`, never `cp` under WAL.

## Review decision inputs

### Luna round 1 resolution

- Premature required API: accepted → T1 no longer changes send signatures; T2 switches the boundary and every caller atomically.
- Representation-only T2: accepted → AST writer checks were replaced by branch execution, canonical DB round-trip, actual durable prepare transactions, trigger-forced rollback and successful state/log assertions.
- Incomplete T1 value object: accepted → canonical JSON, de-duplication/order, subtype/ref validation and `InjectedMessage` legacy-field removal are frozen.
- Missed durable ingress: accepted → T3 scanner includes `send_initial_delivery` and `send_message_delivery`; T2 behavior tests their receipt persistence.
- Consumer behavior gap: accepted → runtime-history, retry, DB/API/sync, TG/MCP, mailbox, RAG and limit-wake behavioral controls supplement parser-removal checks.
- Type mismatch: accepted → storage is JSON text; every DB read/API boundary returns a dict; T3 tests single/history/before/sync projections.
- CLI/dry-run gap: accepted → T5 invokes the real CLI with explicit target different from `ORCHESTRA_DB_PATH`, proves default dry-run and explicit apply.
- Atomicity/WAL gap: accepted → trigger failure proves rollback, live reader proves a stable WAL snapshot, and `--backup` proves a pre-apply `Connection.backup` image.
- Precedence suggestion: accepted → receipt rows deliberately contradict their text prefixes; the fixture covers every declared 181 class and JSON counters.
- PYTHONPATH question: reviewer environment differed from the root-shell measurement; all frozen commands now state `env PYTHONPATH=.` and were replayed exactly.

Round 2 is the final plan-review round by the prose ceiling. Any remaining findings after it are recorded and escalated; no third review is permitted.

### Post-ceiling resolution of final round blockers

No third model review is permitted. The final `Changes requested` findings were checked and closed mechanically in `de813880`:

- Real `_log` path: session/compact tests no longer replace `_log`; they execute it and capture the actual `add_log` call, while the separate DB test proves serialization.
- Receipt immutability: both receipt rows are asserted before prepare; changed provenance with the same delivery id must return `IDEMPOTENCY_CONFLICT`; trigger rollback and successful retry are both exercised.
- Durable manager forwarding: T3 executes `SessionManager.send_initial_delivery` and `send_message_delivery` against a recording session and requires exact provenance identity.
- Ingress scanner: `provenance=object()` is rejected; only an inline `MessageProvenance`, a variable literally named `provenance`, or `.provenance` from the durable envelope is accepted.
- HTTP/SSE: T3 invokes the actual snapshot and stream route functions and asserts `origin_detail` is an object in both payloads.
- Frontend fail-safe: explicit `origin='user'` with missing, string, or empty-senders detail is included and must render Unknown on the left.
- Historical vs new receipt: only `schema_version=1` fixture receipts may be reconstructed; a new-version explicit-unknown receipt with contradictory `[from:]` text must remain unknown.
- CLI summary: exact required keys, six category keys, target path, row/session totals, invalid count and update counters are asserted for dry-run, apply and no-op replay.

Review evidence remains honestly `Luna round 2: Changes requested`; these post-ceiling fixes have command evidence but no third reviewer verdict.

- Author metadata: `gpt-5.6-sol`, Codex runtime, xhigh, full-cycle (live `sessions` row from Phase 1).
- Changed artifacts for Phase 2: five immutable `_433` oracle files and this plan; production code is not written.
- Consumers: shared session/message delivery, SQLite schema and durable receipts, TG/RAG/runtime history, dashboard snapshot/SSE renderer, offline production migration.
- Exact AC/oracles: five commands and observed outputs in `## RED oracle record`; high-risk floor is schema/migration + shared delivery/API.
- Review route: Sol is the technically indicated high-risk route but no auxiliary Sol authorization was granted. One Luna plan/test pass is allowed; no substitute reviewer.
