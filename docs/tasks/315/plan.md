# #315 — implementation plan (PLAN READY: architecture/discussion only)

This plan implements one logical typed namespace/data plane with separate record contracts. It does
not create one shapeless JSONL/Markdown dump and does not give SQLite/FTS/vector a second canonical truth.

## Scope and ownership

### Files to add/change in a later implementation

- app/ia/namespace.py — URI parsing, stable-ID resolution, scope/private boundary.
- app/ia/schema.py — envelopes and per-record validators.
- app/ia/events.py — idempotency, CAS, supersedes/disputed/rejected/tombstone events.
- app/ia/task_store.py — Git-canonical task records, #N lease/lookup and facade parity.
- app/ia/evidence.py — immutable evidence manifest/path-anchor/blob validation.
- app/ia/knowledge.py — topic registry, fact promotion/current/rejected/as-of queries.
- app/ia/projections.py — SQLite current/event/FTS projection, head receipts and fallback.
- app/db.py — additive projection metadata/schema only; preserve existing session/log/task migrations
  until cutover proves parity.
- app/tm.py, app/routes/tm.py, app/mcp_stdio.py — route existing task facade through stable task
  identity; retain API names and project-scoped #N.
- app/rag.py, app/rag_service.py, app/routes/memory.py — consume typed projection, carry heads, keep
  vector/log backfill async and content-bound.
- app/routes/sessions.py, app/merge_operations.py, app/workspace.py — emit merge/evidence/task
  receipts and preserve partial/unknown boundaries.
- app/session.py, app/manager.py — immutable session archive/commit receipt; explicit promotion only.
- scripts/ia_migrate.py, scripts/ia_replay.py, scripts/ia_pack.py — offline snapshot, replay, shadow
  compare, restore and rollback rehearsal; no live write during migration rehearsal.
- docs/tasks/315/acceptance/test_smoke_t*.py — smoke presence probes only; behavior-specific RED oracles
  remain to be designed and frozen ticket-by-ticket.

### Files intentionally not touched

- Provider/model routing and #298 implementation/configuration.
- OpenViking as a runtime dependency or service.
- Existing embedding/reranker/RRF tuning rejected by #256.
- Live systemd service, live DB, .env, proxy owner/configuration, and external YouGile.
- Historical #256/#299/#309 research/evidence and #295 HTML.

## Migration, shadow, cutover and rollback

1. Freeze a fresh sqlite3.Connection.backup snapshot; record cutoff, Git HEAD/blob inventory,
   task/evidence hashes, stable-ID mapping and row counts. Do not reuse historical #299/#309 counts as
   invariants.
2. Import into an isolated shadow store: map current tasks to stable UUID/ULID + preserved project #N;
   map evidence paths/blobs; map topics and only source-linked typed facts; classify private fields.
   Payments/YouGile are excluded, not migrated.
3. Replay and compare task facade outputs, identity uniqueness, evidence links, current/rejected/as-of
   facts and projection heads. Re-run #256 holdout and #299 migration definitions.
4. Shadow dual-read: normalize old facade/current responses and candidate responses without changing
   production writes. Record mismatches and stale-head receipts.
5. Cut over readers behind one owner/facade only after parity and privacy gates. Keep old projection
   rebuildable and retain historical canonical records.
6. Roll back before new canonical writes by switching reader/projection generation. After new canonical
   writes, append forward restore/replay events and rebuild projections; never reset/delete Git history
   to hide a failed cutover.
7. Cleanup order: progress UI hide; legacy merge route removal after v1 oracle; duplicate refresh merge;
   proxy control experiment. YouGile/payments deletion occurs under #299 gates, not knowledge migration.
   #298 remains deferred.

## Tickets (behavioral RED is frozen for T1 and T2)

### T1 — typed namespace, envelopes and private-field boundary

- Files: future app/ia/namespace.py and app/ia/schema.py; frozen
  acceptance/test_t1_namespace_behavior.py plus acceptance/fixtures/t1_namespace_*.json. The existing
  test_smoke_t1_namespace.py remains a missing-seam diagnostic only.
- Test: uv run python -m pytest docs/tasks/315/acceptance/test_t1_namespace_behavior.py -q
- RED result: two harness controls pass; the behavior suite fails at the dynamic public API call with
  `#315 T1 missing behavior: cannot import app.ia.namespace: No module named 'app.ia'`.
- AC: command is green; all six record types resolve a stable URI; cross-kind writes fail; stable IDs
  are unique; private fields are absent from hot/FTS/vector payloads; no secret-form match in fixtures.
- blocked-by: none.

### T2 — #299 task canonical record and facade parity

- Files: future app/ia/task_store.py, scripts/ia_migrate.py, app/tm.py, app/routes/tm.py and
  app/mcp_stdio.py; frozen acceptance/test_t2_task_behavior.py plus
  acceptance/fixtures/t2_task_store_*.json. The existing test_smoke_t2_task_parity.py remains a
  missing-seam diagnostic only.
- Test: uv run python -m pytest docs/tasks/315/acceptance/test_t2_task_behavior.py -q
- RED result: five harness controls pass (including exact current `app.tm` output and real ASGI→app.tm
  →MCP reachability); 15 behavior tests fail on the absent `app.ia.task_store` and
  `app.tm.ia_task_store_mode` production hook. Commit
  `529711a9feda296e361bc8a09fd8f7ec65be4a57` is superseded/excluded for Phase 3: it covered the direct
  store but could not detect a dead parallel implementation.
- AC: command is green; fresh content-bound manifest has 0 duplicate UUIDs and preserves every
  project-scoped #N; per-task JSON bodies/events/evidence refs have no shared JSONL hotspot; same-manifest
  replay is idempotent; task_create/list/get/update/status/acceptance/worker-session/commit-link outputs
  preserve the normalized facade; two-contour disjoint fields survive while same-field/global-MAX+1
  conflicts fail or dispute; a direct SQLite payload edit cannot become truth; rollback/forward replay
  reproduces exact heads; source-less evidence and payment/YouGile events fail closed. Default legacy
  mode preserves exact current output; shadow writes/compares through real app.tm and exposes mismatch;
  canonical mode makes TaskStore authoritative only inside explicit test/rollout configuration. HTTP
  and MCP must enter through the same app.tm owner, and removing app.tm→TaskStore keeps this command red.
- blocked-by: T1.

### T3 — immutable evidence manifest and typed fact promotion

- Files: new app/ia/evidence.py, app/ia/events.py, app/ia/knowledge.py; docs/kb registry adapter;
  test_smoke_t3_promotion.py only as a missing-seam diagnostic. Behavioral oracle design:
  acceptance/README.md T3 row; no RED test is frozen.
- Smoke: uv run python -m pytest docs/tasks/315/acceptance/test_smoke_t3_promotion.py -q
- Smoke result: RED only because the future path is absent; this is not behavioral acceptance.
- AC: command is green; 12 promotion scenarios pass; 0 source-less promoted facts; identical event is
  a no-op; same-key conflict requires explicit supersedes/disputed; rejected and superseded records
  remain queryable; as-of uses valid-time; TTL produces validation debt only; duplicate topic
  resolution fails closed.
- blocked-by: T1, T2.

### T4 — SQLite current projection, heads and cold index

- Files: new app/ia/projections.py; additive app/db.py; app/rag.py, app/rag_service.py,
  app/routes/memory.py; test_smoke_t4_heads.py only as a missing-seam diagnostic. Behavioral oracle design:
  acceptance/README.md T4 row; no RED test is frozen.
- Smoke: uv run python -m pytest docs/tasks/315/acceptance/test_smoke_t4_heads.py -q
- Smoke result: RED only because the future path is absent; this is not behavioral acceptance.
- AC: command is green; SQLite current/FTS projection reaches canonical head synchronously;
  canonical_head, projection_head and indexed_head are returned separately; vector/log lag is visible;
  stale SQLite falls back to canonical changed records; vector/index failure never erases current
  task/fact result; existing RAG file/log content remains rebuildable.
- blocked-by: T3.

### T5 — session commit, pack/restore rehearsal and privacy/retention

- Files: app/session.py, app/manager.py, new scripts/ia_replay.py, scripts/ia_pack.py; test_smoke_t5_recovery_privacy.py
  test_smoke_t5_recovery_privacy.py only as a missing-seam diagnostic. Behavioral oracle design: acceptance/README.md T5 row; no RED test
  is frozen.
- Smoke: uv run python -m pytest docs/tasks/315/acceptance/test_smoke_t5_recovery_privacy.py -q
- Smoke result: RED only because the future path is absent; this is not behavioral acceptance.
- AC: command is green; immutable session archive survives background extraction failure; explicit
  promotion is source-linked; pack manifest/checksum/scope/schema validation occurs before writes;
  restore/rebuild parity holds; tombstone/retention states are preserved; privacy secret scan has
  0 matches in canonical, prompt, FTS/vector and logs. OpenViking OVPack is an input contract, not an
  atomic recovery claim.
- blocked-by: T3, T4.

### T6 — merge receipt and approved cleanup sequencing

- Files: app/routes/sessions.py, app/merge_operations.py, app/workspace.py, #309 oracle references;
  test_smoke_t6_merge_cleanup.py only as a missing-seam diagnostic. Behavioral oracle design:
  acceptance/README.md T6 row; no RED test is frozen.
- Smoke: uv run python -m pytest docs/tasks/315/acceptance/test_smoke_t6_merge_cleanup.py -q
- Smoke result: RED only because the future path is absent; this is not behavioral acceptance.
- AC: command is green; merge target commit, task link, evidence manifest, projection receipt and
  partial/unknown state are distinguishable; rag_backfill remains secondary/async; legacy merge route
  removal is gated by v1 recovery/OpenAPI oracle; duplicate model refresh is not a second write path;
  progress UI hide preserves active worker API/session fields; proxy controls remain under external
  owner; #298 files/config remain untouched.
- blocked-by: T2, T4, T5.

## Phase 3 entry gate and quantitative gate

The user approved project-scoped #N with stable UUID, private/secret fields outside ordinary
Git/prompt/FTS/vector, and deterministic evidence-backed supersedes/disputed with a human gate for
conflicts and sensitive classes. Each ticket must still receive the exact
fixture/path/mutation/positive-control oracle design in acceptance/README.md, then a separate
behavioral RED test must be committed and independently verified before implementation. T1 and T2 have
reached that oracle gate; T3–T6 have not. Smoke probes never satisfy this gate.

The implementation report must include command output and frozen manifest for replay parity and 0
duplicate identity; 0 source-less promoted facts; exact/current/rejected recall and stale contradiction
on the #256 holdout; projection read-after-write and head debt; task facade parity and conflict-loss
count; prompt footprint/tool calls/time measured A/B/A/B; privacy secret scan; rollback replay parity.

No absolute future quality/latency/token constant is invented here. The acceptance test must report its
denominator, frozen fixture hash, machine/load context where relevant, and exact historical baseline.

## Superseded standalone plans

- #299 independent implementation plan is superseded by T2 and the joined migration/cutover sequence;
  docs/tasks/299/research.md and its KB evidence remain historical sources.
- Any unstarted #256 implementation is superseded by T1/T3/T4; #256 research/comparison/metrics and
  frozen eval artifacts remain canonical historical evidence.
- #309 cleanup candidates are not deleted by #315; their decisions are dependencies/gates in T6.
- #298 model routing is explicitly deferred and not part of this plan.

## Review constraint

The user explicitly prohibited model/provider/eval/review calls. No model review is requested or run.
This plan is for user discussion; its acceptance requires the listed artifacts and future commands, not
a reviewer verdict.
