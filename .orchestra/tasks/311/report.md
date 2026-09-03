# #311 Phase 3 report — durable spawn initial-task delivery

## Status

T1–T3 are implemented on the frozen RED baseline
`327242a7432ef7b325cb7c4de38244479bcc1cab`. The #311 load-bearing regression set and mandatory
Sol review are green. The branch was reconciled with current main `a497a12f` after #312 and #313
closed the two unrelated baseline test blockers; all requested post-reconciliation gates are now
green. No service restart, deployment, push, or production-state mutation was performed.

Reconciliation commit `7a823d48` merged `main` into the existing #311 branch without conflicts and
changed only the three #312/#313-owned test files. Current main is an ancestor of HEAD; reviewed
#311 production code and both frozen oracle files are unchanged.

## Implemented

- `app/db.py`
  - creates `initial_deliveries` with the frozen schema and the
    `(scope, state, created_at)` recovery index;
  - keeps the delivery row linked to the target session and its sole immutable user log.
- `app/initial_deliveries.py`
  - canonical SHA-256 payload fingerprint over the frozen schema fields;
  - `BEGIN IMMEDIATE` insert-or-read acceptance, commit before runner wake, same-payload dedupe,
    and different-payload conflict;
  - `QUEUED -> PREPARING -> DISPATCHING -> SUBMITTED` plus terminal
    `DELIVERY_UNKNOWN` quarantine;
  - restart recovery schedules only `QUEUED`/`PREPARING` and quarantines orphan
    `DISPATCHING` rows;
  - exact persisted `logs.content` is carried as the history-exclusion value, including when
    secret masking changes the text.
- `app/routes/sessions.py`
  - fast `POST /api/sessions/{name}/initial-deliveries` acceptance and scoped
    `GET /api/initial-deliveries/{delivery_id}` lookup;
  - explicit proven-precommit `503 DELIVERY_ACCEPT_REJECTED` and `409 IDEMPOTENCY_CONFLICT`.
- `app/manager.py`, `app/session.py`
  - narrow `send_initial_delivery` sibling preserves the session lock, changed-session recheck,
    auto-switch, owned-task wait, and loud result propagation;
  - one prepared user log, one current backend prompt, one backend call;
  - `DISPATCHING` is committed immediately before `backend.send`; exception or cancellation after
    that boundary records unknown and is never replayed;
  - the exact persisted masked history row is excluded from native import, DB fallback, and
    `resume_failed` handoff while the original task remains the sole current submission.
- `app/main.py`
  - recovery runs immediately after `auto_resume_all()` and before orphan sweep/background
    traffic/restart inbox drain.
- `app/mcp_stdio.py`
  - caller-provided or locally generated immutable `delivery_id`;
  - initial spawn uses the acceptance resource instead of synchronous `/send`;
  - `delivery_status` and `retry_initial_delivery` preserve the same key and payload;
  - ambiguous POST/generic 5xx performs exactly one same-id GET and never automatically POSTs
    again; conflict never reconciles/retries; proven-not-sent offers only an explicit same-key
    retry action;
  - no timeout was increased.
- `tests/route_surface_snapshot.json`
  - records the two intentional HTTP routes.
- `tests/test_initial_delivery_review_regressions.py`
  - additive regression for secret-masked immutable-history deduplication. The two frozen oracle
    files were not edited.

## Ticket evidence

- T1: `uv run python -m pytest -q tests/test_initial_deliveries.py -k 'test_t1_'`
  -> `5 passed, 10 deselected`.
- T2: `uv run python -m pytest -q tests/test_initial_deliveries.py -k 'test_t2_'`
  -> `10 passed, 5 deselected`.
- T3: `uv run python -m pytest -q tests/test_mcp_stdio.py -k 'test_t3_'`
  -> `9 passed, 93 deselected`.
- Frozen-oracle integrity:
  `git diff 327242a7432ef7b325cb7c4de38244479bcc1cab -- tests/test_initial_deliveries.py tests/test_mcp_stdio.py`
  -> empty throughout implementation and final verification.
- Platform merge gate before the reviewer fix: `601 passed in 144.99s` across DB, delivery,
  manager, MCP, route-surface, and session suites.
- Final load-bearing regression after the reviewer fix:
  `uv run python -m pytest -q tests/test_db.py tests/test_initial_deliveries.py tests/test_initial_delivery_review_regressions.py tests/test_manager.py tests/test_mcp_stdio.py tests/test_routes_surface.py tests/test_session.py`
  -> `602 passed in 173.18s` after current-main reconciliation.
- Crash/restart/timeout probe selection: queued/preparing recovery, atomic preparation,
  both possible orphan-`DISPATCHING` provider realities, terminal submitted, cancellation after
  dispatch, timeout reconciliation, unresolved timeout, and committed-then-500 ->
  `10 passed in 7.59s`. The probes use events/fakes and no wall sleep.
- Full API regression after #313: `uv run python -m pytest -q tests/test_api.py`
  -> `128 passed in 59.54s`; the prior 18 stale direct-call failures are gone.
- Frontend collection/runtime seam after #312:
  `uv run python -m pytest -q tests/test_system_chat_entry.py`
  -> `1 passed in 18.23s`; the missing helper import is gone.
- Full-suite collection: `uv run python -m pytest --collect-only -q`
  -> `3098 tests collected in 9.67s`, exit `0`. This directly proves both prior collection/API
  blockers are absent from the reconciled source branch.

## Mutation evidence

Each valid mutation started from a green oracle, printed a unique marker count before and after,
restored with `mv` plus `touch`, and finished with a green repeat.

1. Disabled the payload-hash conflict guard -> conflict returned `202` instead of `409`; T1 failed,
   then passed after restore.
2. Kept orphan recovery in `DISPATCHING` -> both provider-reality cases failed on expected
   `DELIVERY_UNKNOWN`; both passed after restore.
3. Removed the latest immutable message from history exclusion -> T2 failed on the exclusion tuple;
   passed after restore.
4. Forced reconciliation for every error -> the 409 oracle observed an extra GET and failed; passed
   after restore.
5. Reviewer-fix mutation replaced persisted masked history with the original plaintext -> the
   additive regression observed the wrong exclusion and failed; passed after restore.

One first recovery mutation attempt is explicitly excluded: its marker count was `2`, it changed
the wrong same-shaped SQL seam, and the test remained green. The unique-indentation anchor rerun is
mutation 2 above and failed for the intended reason.

## Review

Mandatory final technical review: `gpt-5.6-sol`, artifact `review-impl.md`.

- Round 1: `NEEDS WORK` with two blockers.
- The spawn-level blocker was challenged with the approved contract: #311 begins with the initial
  task *after session creation*, explicitly forbids create-session changes, and retries via
  `retry_initial_delivery` rather than a second spawn. The reviewer verified this and withdrew the
  finding.
- The masked-history blocker was accepted and fixed. The reviewer ran the additive plus frozen
  delivery suites (`16 passed in 10.23s`) and verified all three history paths.
- Final verdict: **APPROVED**; no blocking findings or suggestions remain.

The attempted fresh `claude-opus-5[1m]` cross-family review during T2 was rejected before worker
creation by the 100% Claude weekly quota. Cross-family verdict is therefore unavailable and is not
claimed.

## #305 overlap and reconciliation

The Phase 3 base main was `ddd8a4ec12abbfde34dc48c58397fc40f00b62b3`. It contained no landed
#305 hunk or behavior. #311 adds only the reviewed sibling beside `SessionManager.send`; the
ordinary method body, `_auto_switch_before_delivery`, and manager recovery were not changed.
No pending #305 branch was fetched, read, imported, copied, or cherry-picked. The only observed
unmerged metadata was a commit title from `git log --all`; no code from it was inspected.

## Breaking changes and TODOs

- Breaking behavior: none intended. The original provider submission cannot be made strictly
  exactly-once across an ambiguous external acceptance window; the protocol exposes that boundary
  as `DELIVERY_UNKNOWN` and refuses automatic replay.
- #311 TODOs: none.
- The former external test debt was resolved by #312/#313 and reconciled without changing #311
  production behavior or frozen assertions.
