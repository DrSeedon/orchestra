# #333 Phase-2 adversarial self-review

## Review route

The planned Phase-3 surface is high risk: shared delivery/concurrency, a persistence migration,
authentication and an externally consumed HTTP/MCP contract.  The canonical review route would
therefore be Sol.  The current assignment explicitly prohibits auxiliary model/review calls; the
separately approved Sol run is the future implementation executor, not an auxiliary reviewer.
No model review was run, no substitute reviewer was sought, and this artifact does not claim an
approval verdict.  The orchestrator's verification of the frozen plan/oracle is the Phase-3 gate.

## Decision-gate inputs

- Phase-2 changed files: `docs/tasks/333/acceptance/README.md`,
  `docs/tasks/333/acceptance/test_tg_file_delivery_333.py`, `docs/tasks/333/plan.md`, this file.
- Planned consumers: `app/db.py`, new `app/tg_file_deliveries.py`, `app/routes/tg.py`,
  `app/tg_bridge.py`, `app/mcp_stdio.py`, `app/main.py`; agents using `send_file`, `send_chart`,
  the TG bridge lifecycle and an existing SQLite database consume them.
- Author metadata: `gpt-5.6-sol`, Codex runtime, full-cycle role, live session
  `511fe481-a766-4e2b-843c-7c3462e2b70b` (read-only `/api/sessions`, 2026-08-24).
- Frozen RED commit: `3907df87`.
- Positive command: `uv run python -m pytest -q
  docs/tasks/333/acceptance/test_tg_file_delivery_333.py -k 't333_control'` → exit 0,
  `2 passed, 11 deselected`.
- Combined command: `uv run python -m pytest -q
  docs/tasks/333/acceptance/test_tg_file_delivery_333.py` → exit 1,
  `11 failed, 2 passed`; first failure is the behavioral mismatch `assert 200 == 202`, not an
  import/collection error.
- Syntax/delivery checks: `python -m py_compile
  docs/tasks/333/acceptance/test_tg_file_delivery_333.py` → exit 0; explicit pytest path collects
  the file despite the repository's `norecurseddirs=["docs"]` default.

## Mechanical completeness

| Required behavior | Frozen oracle |
|---|---|
| 0600 immutable snapshot before ACCEPTED; source disappears | T1-A |
| same event/hash idempotence under concurrency | T1-B |
| same id/different hash conflict | T1-B |
| timeout after provider boundary → one call + UNKNOWN | T1-C |
| QUEUED restart replay; SUBMITTING restart quarantine | T1-D |
| FAILED_BEFORE_SUBMIT and safe same-id retry | T1-E |
| per-chat FIFO lease/generation | T2-A |
| bounded queue + Retry-After + no orphan snapshot | T2-B |
| mirror failure cannot rewrite primary SENT | T2-C |
| owner-scoped status endpoint and read-only tool | T3-A |
| legacy caller returns string with a durable id | T3-A |
| wrapper transport timeout reconciles same id | T3-B |
| retention/quarantine/cleanup | T3-C |
| rollback refuses fresh admission and never replays UNKNOWN | T3-C |
| no live provider/media call | exploding bot + injected provider in every route fixture; controls |

Every oracle's production path, red regression, positive control, valid alternate,
compound/fallback mutation and deterministic command are recorded in
`docs/tasks/333/acceptance/README.md`.

## Adversarial findings resolved in the plan

1. **A shared snapshot cannot move to quarantine on the first UNKNOWN child.** A mirror or primary
   sibling may still be QUEUED/SUBMITTING and need the path.  The plan now moves the file only after
   every child is terminal; any UNKNOWN then forces indefinite quarantine.
2. **Deleting terminal receipt rows would silently re-enable an old event id.** Cleanup now deletes
   only bulky snapshots; parent/child hash and result rows remain as idempotency tombstones.
3. **Capacity checked after snapshot publication can leak a private orphan.** Acceptance now removes
   only its own unpublished candidate on 429/conflict/rollback; T2-B asserts the spool contains only
   the accepted event's file.
4. **Recovery before the bot/provider seam is ready can turn a local startup race into
   FAILED_BEFORE_SUBMIT.** Lifecycle order is DB → HTTP → bridge ready → file recovery; shutdown is
   file runners → bridge close.
5. **A rollback gate checked before existing-id lookup hides receipts exactly when they matter.**
   Existing ids reconcile before `ADMISSION_ENABLED` and capacity gates; only fresh ids get 503.
6. **Reusing `_tg_call_safe(important=True)` would retain three ambiguous calls.** C1 has a new
   direct one-call seam that never enters the old attempt loop, marker/edit, mirror outbox or
   photo→document fallback.
7. **An in-memory per-chat task singleton is not a restart/concurrent-runner lease.** The plan adds
   a persisted lease generation and conditional result updates; T2-A invokes two production runners
   and also requires target rows to carry the common positive generation.
8. **A mirror exception cannot be represented by one parent state.** Child rows are independent;
   aggregate/top-level state always derives from primary.
9. **Generating an id after MCP transport timeout is too late.** C5 generates before POST and the
   only automatic follow-up is GET for that same id; T3-B freezes the exact POST→GET trace.
10. **A 202 response without source binding exposes receipts across workers sharing the internal
    bearer.** Route acceptance/status bind MCP session id + proof (dashboard operator remains the
    explicit alternate); T3-A exercises a second valid principal and requires 403.

## Remaining uncertainty for the orchestrator

- Default capacities 256 total / 64 per chat, 5-second Retry-After and snapshot retention windows
  24 hours / 7 days are explicit operational defaults, not measured optimal thresholds.  The
  behavioral tests inject capacity 1 and do not pretend to validate production sizing.
- Telegram offers no provider idempotency key/receipt lookup for this request path.  UNKNOWN can be
  preserved and never replayed automatically, but cannot be resolved to SENT/not-sent by v1.
- A full rollback cannot preserve a new status endpoint if the entire new code generation is
  removed.  The plan therefore requires a partial compatibility reader while UNKNOWN rows exist;
  additive tables/spool alone preserve evidence, not API availability.

