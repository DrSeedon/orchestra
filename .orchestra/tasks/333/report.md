# #333 — Phase 3 report: durable Telegram file receipts

## Final result

**Status: COMPLETE.** C1 receipt-backed per-file delivery and the C5 compatibility wrapper are
merged in current `main` as implementation commit `2fa66628`.  C2 marker/edit and C3 media-group
remain out of scope.  No live Telegram/provider call, service restart, route switch or live DB
mutation was used for final verification.

Current-main verification point: `2fcc0e2fa468222059d87ac1643acf01a9a869cd` (2026-08-24).
`git merge-base --is-ancestor 2fa66628 main` returned 0.  The later main commit `2fcc0e2f`
removed the unrelated obsolete blob feature: the #337 core files remain byte-identical, while
`app/db.py` lost only `remove_session_blobs` cleanup and the route snapshot lost only the blob
route.  All TG file-delivery schema/route markers remain present.

## Implemented surface

- `app/db.py` (+109): additive `tg_file_deliveries`, `tg_file_delivery_targets`, and
  `tg_file_chat_leases` schema, indexes, and migration validation.
- `app/tg_file_deliveries.py` (+1174, new): 0600 file snapshot, canonical payload hash,
  receipt/idempotence/conflict, child states, bounded admission, persistent chat lease generation,
  FIFO runner, recovery, retention/quarantine, cleanup, and service lifecycle.
- `app/routes/tg.py` (+106/-11): receipt-returning `POST /api/tg/send_file` and owner-scoped
  `GET /api/tg/file-deliveries/{event_id}`.
- `app/tg_bridge.py` (+40): `_submit_file_snapshot_once` crosses the Bot API boundary once under
  the existing 30-second timeout; `_reserve_file_snapshot_slot` preserves per-chat rate authority.
- `app/mcp_stdio.py` (+145/-23): legacy-compatible `send_file` arguments plus optional stable
  `event_id`, truthful accepted receipt text, same-id timeout reconciliation, and read-only
  `file_delivery_status`.
- `app/main.py` (+11/-2): starts the durable file service only after the TG bridge is ready and
  shuts file runners down before bridge close.
- `tests/route_surface_snapshot.json` (+6): the status route is in the generated route surface.

Implementation commit total: `+1600/-36` across eight files, including executor memory and the
route snapshot.  `uv.lock` was unchanged.

## Verified production markers in current main

Read-only `git grep`/`git show` against `main` found:

- `accept_file_delivery` at `app/tg_file_deliveries.py:515`;
- `run_chat_deliveries` at line 897 and `ensure_chat_runner` at line 981;
- `recover_file_deliveries` at line 996, `cleanup_file_deliveries` at line 1144,
  `start_file_delivery_service` at line 1155, and `shutdown_file_delivery_service` at line 1163;
- the one-call provider seam `_submit_file_snapshot_once` at `app/tg_bridge.py:2385`;
- `POST /api/tg/send_file` at `app/routes/tg.py:141` and
  `GET /api/tg/file-deliveries/{event_id}` at line 213;
- `file_delivery_status` in `READ_ONLY_MCP_TOOLS`, its GET helper, and `send_file(...,
  event_id="")` in `app/mcp_stdio.py`;
- all three additive table definitions and `_migrate_tg_file_deliveries` in `app/db.py`;
- lifecycle calls in `app/main.py:55-56,311-315`.

The frozen acceptance artifacts remain unchanged from RED commit `3907df87`:

```text
test_tg_file_delivery_333.py sha256
117fa5e5fcdf78ce5c640c57624b7d53f84a70a9b9d399fd3325e1ed5e1588ae

acceptance/README.md sha256
b2de3edaac757434126fecfbfb5c7437c4dd826f27744de342ffde4c94c8ef53
```

Both current-main blobs match those frozen hashes.

## Acceptance evidence

- Final frozen merge gate on current main:
  `uv run python -m pytest -q docs/tasks/333/acceptance/test_tg_file_delivery_333.py`
  → `13 passed` (all 13/13 fake-only #333 nodes).
- Final focused TG/MCP regression gate on current main: `298 passed`.
- Earlier ticket gates recorded by the executor: T1 `5 passed`, T2 `3 passed`, T3 `3 passed`;
  `TestSendFileRouting` `3 passed`; `TestTgMirrorIsolation` `6 passed`.
- Current main matches the executor task branch byte-for-byte for `app/main.py`,
  `app/mcp_stdio.py`, `app/routes/tg.py`, `app/tg_bridge.py`, and
  `app/tg_file_deliveries.py` (`git diff --quiet` exit 0).  The only later differences in
  `app/db.py` and `tests/route_surface_snapshot.json` delete obsolete blob code/route; targeted
  diff contains no `tg_file` or `/api/tg/` deletion.

The final 13/13 and 298 results were supplied by the orchestrator after its current-main merge
gate.  This closing turn did not rerun provider-capable or live-service checks.

## Ticket completion

- T1 complete: durable primary snapshot/receipt, idempotence/conflict, one-call UNKNOWN semantics,
  pre-submit failure and restart recovery.
- T2 complete: persistent per-chat FIFO lease/generation, bounded Retry-After admission, and
  independent primary/mirror child outcomes.
- T3 complete: owner-scoped status, stable-id C5 wrapper/reconciliation, retention/quarantine,
  cleanup and rollback that never replays UNKNOWN.

## Consumer pre-mortem coverage

- Caller timeout after provider boundary → frozen T1 requires one provider call and durable
  UNKNOWN; same-id reconciliation cannot enqueue a fresh send.
- Process restart with queued/in-flight rows → frozen T1 requires QUEUED replay and SUBMITTING →
  UNKNOWN.
- Two runners for one chat → frozen T2 requires FIFO under one positive persisted lease generation.
- Mirror timeout after primary success → frozen T2 requires top-level/primary SENT and mirror
  UNKNOWN.
- Old MCP caller and `send_chart` consumer → frozen T3 preserves a string return carrying the
  durable id; focused MCP/TG gate is green.
- Cleanup/rollback → frozen T3 preserves receipt rows and UNKNOWN quarantine, refuses fresh
  admission when disabled, and never replays UNKNOWN.

## Breaking changes and remaining limits

No intentional caller-signature break: the original three `send_file` arguments remain valid and
`event_id` is trailing/optional.  The returned text now truthfully says `File accepted` instead of
claiming provider delivery before a receipt exists.

Telegram still exposes no idempotency key or receipt lookup for this path.  Therefore UNKNOWN is a
durable, non-replayable outcome, not proof of delivery or non-delivery.  Quarantined UNKNOWN rows
require operator/provider-side reconciliation outside v1.

## Review

Review-gate inputs: changed files/consumers are enumerated under “Implemented surface”; the
archived executor row in the live DB identifies session `2695f51a-14b5-4cb4-8c3c-60291aeaf7d4`,
model `gpt-5.6-sol`, role `worker`, branch `task-337/impl333-outbox-sol` (Codex implementation
run); exact AC is the frozen 13-node command above plus the focused TG/MCP regression gate.

Review: none — the high-risk route would require an additional Sol reviewer, but the authorized
Sol session was the implementation executor and this final instruction allowed only read-only
verification with no new provider/model calls.  Acceptance instead rests on the immutable
pre-implementation oracle, current-main 13/13 merge gate, focused 298-pass regression gate, and
orchestrator verification.  No reviewer approval is claimed.

## Memory check

Memory: none — final reconciliation added no reusable lesson beyond the existing
`docs/workers/research-tg-media-delivery.md` delivery-UNKNOWN rules.
