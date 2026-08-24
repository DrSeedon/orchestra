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
- app/routes/knowledge.py, app/mcp_stdio.py — one agent-facing typed `knowledge` API/tool for
  promotion, query and evidence import with progressive structured payloads; no separate human output.
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
- scripts/ia_document_inventory.py, scripts/ia_migrate_documents.py — classify every legacy document,
  emit path→typed-URI aliases/evidence refs, and prove byte-preserving historical migration.
- pipelines/default/prompts/modules/memory-search.md and the project skill/prompt owners selected by
  delivery inventory — switch agents to typed IDs and evidence/promotion/query APIs only at T7 cutover;
  verify final assembled prompts for every runtime rather than source snippets.
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
7. After corrected T3b and T4–T6 are green, freeze a tracked document inventory and classify every
   `docs/tasks/*.md`, `docs/kb/*.md`, TODO/instruction source and session archive as exactly one of:
   canonical structured JSON, immutable evidence/cold archive, active skill/resource source, or derived
   machine index. Preserve historical bytes and paths; import/index them once through structured refs
   and `orch://` aliases rather than rewriting or regenerating Markdown.
8. Run T7 legacy→shadow→canonical prompt/document cutover. Structured JSON task/fact/evidence-ref/event
   records and their structured registry/index are canonical; historical Markdown stays cold evidence,
   never a regenerated projection. SQLite, FTS and vector remain rebuildable machine projections.
   Do not destructively remove SQLite or legacy readers until shadow parity, rollback rehearsal, assembled
   prompt delivery and live cutover receipts all pass. Rollback switches the owner/read generation and
   replays forward; it never deletes newer canonical history.
9. Cleanup order: progress UI hide; legacy merge route removal after v1 oracle; duplicate refresh merge;
   proxy control experiment. YouGile/payments deletion occurs under #299 gates, not knowledge migration.
   #298 remains deferred.

## Tickets (behavioral RED is frozen for T1–T3)

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
- RED result: six harness controls pass (including exact current `app.tm` output, real ASGI→app.tm
  →MCP reachability); 15 behavior tests fail on the absent `app.ia.task_store` and
  `app.tm.ia_task_store_mode` production hook. Commit
  `529711a9feda296e361bc8a09fd8f7ec65be4a57` is superseded/excluded for missing production wiring;
  `f09641624d371f9914e6e3eaed0b214384d9a9f4` is superseded/excluded because it applied the
  canonical-body removed-domain ban to audit metadata that must name excluded source fields.
- AC: command is green; fresh content-bound manifest has 0 duplicate UUIDs and preserves every
  project-scoped #N; per-task JSON bodies/events/evidence refs have no shared JSONL hotspot; same-manifest
  replay is idempotent; task_create/list/get/update/status/acceptance/worker-session/commit-link outputs
  preserve the normalized facade; two-contour disjoint fields survive while same-field/global-MAX+1
  conflicts fail or dispute; a direct SQLite payload edit cannot become truth; rollback/forward replay
  reproduces exact heads; source-less evidence and payment/YouGile events fail closed. Default legacy
  mode preserves exact current output; shadow writes/compares through real app.tm and exposes mismatch;
  canonical mode makes TaskStore authoritative only inside explicit test/rollout configuration. HTTP
  and MCP must enter through the same app.tm owner, and removing app.tm→TaskStore keeps this command red.
  Audit metadata names removed sources; their field names and values are absent only from canonical
  task/evidence/event bodies.
- blocked-by: T1.

### T3 — immutable evidence manifest and typed fact promotion

- Files: future app/ia/evidence.py, app/ia/events.py and app/ia/knowledge.py plus the docs/kb registry
  adapter; frozen acceptance/test_t3_promotion_behavior.py and
  acceptance/fixtures/t3_promotion_*.json. The existing test_smoke_t3_promotion.py remains a
  missing-seam diagnostic only.
- Test: uv run python -m pytest docs/tasks/315/acceptance/test_t3_promotion_behavior.py -q
- RED result: four T1/T2/fixture/mutation controls pass; exactly 12 frozen promotion scenario nodes
  plus two wiring/compatibility nodes fail inside the dynamic public seam with
  `#315 T3 missing behavior: cannot import app.ia.evidence: No module named 'app.ia.evidence'`.
- AC: command is green; the #256 3/2/2/1/1/1/1/1 distribution passes exactly 12 scenarios; source-less,
  orphan, duplicate-topic, cross-kind evidence and undeclared-private writes produce zero facts/events;
  identical event is a content-bound no-op and changed replay conflicts; same-key overlap needs explicit
  supersede/disputed; rejected, historical/superseded and disputed rows remain labelled/queryable;
  as-of uses valid time; TTL returns validation debt without changing/deleting canonical current; valid
  alias/field order/safe metadata is accepted; public promote_fact calls KnowledgeService →
  EvidenceResolver → FactEventLog and emitted facts validate/project through T1 over T2 evidence.
- blocked-by: T1, T2.

### T3b — agent-only structured knowledge correction

- Files: future correction to app/ia/knowledge.py; new app/routes/knowledge.py; app/mcp_stdio.py single
  `knowledge` tool; structured archive/evidence index. Existing app/ia/evidence.py/events.py fact semantics
  remain. The oracle at worker commit `21e1b0718f8e8c3d30a06c2762b9d8257c815df4`
  (main `b693f302`) is permanently superseded/excluded and unchanged; its old implementation SHA and
  3→4 Markdown counts are retained only in acceptance/t3b-prechange-red-evidence.md. Replacement frozen
  files are acceptance/test_t3b_agent_only_knowledge_behavior_v2.py and
  acceptance/fixtures/t3b_agent_only_*_v2.json.
- Test: `uv run python -m pytest docs/tasks/315/acceptance/test_t3_promotion_behavior.py docs/tasks/315/acceptance/test_t3b_agent_only_knowledge_behavior_v2.py --deselect 'docs/tasks/315/acceptance/test_t3_promotion_behavior.py::test_t3_exact_promotion_scenario[S11]' -q`
- Selection: original T3 S11 is excluded because it mixes structured new-topic behavior with removed
  README/topic assertions; corrected T3b replaces its registry/fact/event/query coverage. All other
  original T3 nodes remain selected. The three corrected controls are invariant before/after.
- RED result: exact three-control command → `3 passed in 0.14s`; exact full command → exit 1,
  `6 failed, 20 passed, 1 deselected in 0.34s`. Replacement S11 fails on
  `{'.json', '.md'} <= {'.json'}`; the other five behavior nodes fail on
  `#315 T3b missing behavior: app.ia.knowledge.knowledge_api is not callable`. All selected original
  T3 nodes and invariant controls pass; only mixed original S11 is deselected.
- AC: command is green; the only agent entry is one typed `knowledge` MCP/API supporting promote/query/
  import_evidence and summary/record/evidence payload levels; new canonical writes are JSON records/index
  only; no README/topic Markdown, HTML/text summary or hidden human-projection key is generated; existing
  Markdown corpus bytes/paths remain cold evidence and import idempotently through structured refs; missing
  canonical truth fails closed and cannot read caller-supplied file, SQLite payload or vector hits; MCP →
  HTTP route → knowledge_api → KnowledgeService wiring is observable. Original T3 12-scenario semantics
  remain, but its Markdown layout clauses are superseded by T3b.
- blocked-by: T3.

### T4 — SQLite current projection, heads and cold index

- Files: new app/ia/projections.py; additive app/db.py; app/rag.py, app/rag_service.py,
  app/ia/knowledge.py, app/routes/knowledge.py and app/routes/memory.py. Worker commit
  `863c7bd9e152f9dc8da948038d007d02c020eab7` (main `020f32f1`) is permanently
  superseded/excluded: its alternate T3 fixture root was absent before the registry writer ran.
  The corrected frozen oracle is acceptance/test_t4_projection_heads_behavior_v2.py plus
  fixtures/t4_projection_contract_v2.json and the unchanged fixtures/t4_projection_records.json;
  test_smoke_t4_heads.py remains only a missing-seam diagnostic.
- Smoke: uv run python -m pytest docs/tasks/315/acceptance/test_smoke_t4_heads.py -q
- Smoke result: RED only because the future path is absent; this is not behavioral acceptance.
- Test: `uv run python -m pytest docs/tasks/315/acceptance/test_t4_projection_heads_behavior_v2.py -q`
- RED result: invariant controls → `5 passed in 0.69s`; full command → exit 1,
  `7 failed, 5 passed in 0.70s`, first failure
  `#315 T4 missing behavior: cannot import app.ia.projections: No module named 'app.ia.projections'`.
  Collection succeeds; current T3b MCP→HTTP→knowledge_api query and the independent alternate-mode
  fixture setup remain green.
- AC: command is green; SQLite current/FTS projection reaches canonical head synchronously;
  canonical_head, projection_head and indexed_head are returned separately; vector/log lag is visible;
  stale SQLite falls back to canonical changed records; vector/index failure never erases current
  task/fact result; existing RAG file/log content imports/rebuilds as JSON structured refs without
  direct file/legacy SQLite/vector fallback or generated Markdown. The only agent query stays
  `knowledge(operation="query")`; `/api/memory/search|reindex` are compatibility consumers of the same
  projection owner. Forged equal-head stale payload, deleted canonical with stale SQLite/vector hits,
  index failure, projection-write failure after canonical commit and route/query bypass all fail.
- Gate: behavior oracle frozen; implementation has not started.
- blocked-by: T3b.

### T5 — session commit, pack/restore rehearsal and privacy/retention

- Files: app/session.py, app/manager.py, new app/ia/recovery.py, scripts/ia_replay.py and
  scripts/ia_pack.py. The frozen oracle is acceptance/test_t5_recovery_privacy_behavior.py plus
  fixtures/t5_recovery_*.json; test_smoke_t5_recovery_privacy.py remains only a missing-seam
  diagnostic.
- Smoke: uv run python -m pytest docs/tasks/315/acceptance/test_smoke_t5_recovery_privacy.py -q
- Smoke result: RED only because the future path is absent; this is not behavioral acceptance.
- Test: `uv run python -m pytest docs/tasks/315/acceptance/test_t5_recovery_privacy_behavior.py -q`
- RED result: invariant controls → `4 passed in 0.37s`; full command → exit 1,
  `7 failed, 4 passed in 0.34s`, first failure
  `#315 T5 missing behavior: cannot import app.ia.recovery: No module named 'app.ia.recovery'`.
  Collection succeeds; the real current AgentSession/SessionManager fixture and nonempty reference
  archive/restore control pass without a live DB or service.
- AC: command is green; immutable session archive survives background extraction failure; explicit
  promotion is source-linked; pack manifest/checksum/scope/schema validation occurs before writes;
  restore/rebuild parity holds; tombstone/retention states are preserved; privacy secret scan has
  0 matches in canonical JSON, agent payloads/prompts, SQLite/FTS/vector and logs. Retrying the same
  archive is an idempotent no-op with one archive/event; rollback refuses the wrong current head and
  then reproduces the selected pack head/projection exactly. OpenViking OVPack is accepted only as an
  input package format and carries `atomicity_claim=false`; Orchestra validates/stages fully before
  writes. No generated Markdown or direct-file alternate truth is created.
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

### T7 — prompt + existing-document migration + final cutover

- Files: future scripts/ia_document_inventory.py, scripts/ia_migrate_documents.py; prompt/skill owners
  selected by the tracked delivery inventory; structured registry/archive indexes, migration manifests
  and alias maps. Historical evidence/report bodies are read-only inputs, never regeneration targets.
- Test: future `uv run python -m pytest docs/tasks/315/acceptance/test_t7_prompt_document_cutover_behavior.py -q`;
  behavioral oracle design is frozen in acceptance/README.md T7 row, but no RED is committed yet. No
  existence smoke may substitute for it.
- AC: command is green; every in-scope legacy path is classified exactly once; canonical task
  state/events/evidence refs/facts are structured Git JSON; historical evidence/report/session archive
  bytes and Git lineage are unchanged; old path/#N references resolve through typed `orch://` aliases;
  no README/topic/human summary is generated; all assembled runtime prompts instruct the single typed
  knowledge tool and typed task IDs, and deny direct file/SQLite/vector access as alternate authority;
  legacy and shadow keep current readers recoverable, canonical cutover occurs only after parity/privacy/
  rollback/live-delivery receipts, and rollback restores the previous owner without erasing canonical
  events. Compound dual-truth, prompt-source-only, fake-parity deletion and rewritten-evidence mutants fail.
- blocked-by: T3b, T4, T5, T6.

## Phase 3 entry gate and quantitative gate

The user approved project-scoped #N with stable UUID, private/secret fields outside ordinary
Git/prompt/FTS/vector, and deterministic evidence-backed supersedes/disputed with a human gate for
conflicts and sensitive classes. Each ticket must still receive the exact
fixture/path/mutation/positive-control oracle design in acceptance/README.md, then a separate
behavioral RED test must be committed and independently verified before implementation. T1–T5
have reached that oracle gate; T6–T7 have not. T7 runs only after the
corrected T3b plus T4–T6 core and has no existence-smoke
shortcut. Smoke probes never satisfy this gate.

The implementation report must include command output and frozen manifest for replay parity and 0
duplicate identity; 0 source-less promoted facts; exact/current/rejected recall and stale contradiction
on the #256 holdout; projection read-after-write and head debt; task facade parity and conflict-loss
count; prompt footprint/tool calls/time measured A/B/A/B; privacy secret scan; rollback replay parity.
T7 additionally reports exact document-classification coverage, unchanged historical evidence hashes,
typed-reference resolution, zero newly generated human-readable files/summaries, single-tool assembled-
prompt delivery for every runtime, shadow mismatch count, cutover
receipt and rehearsed rollback with legacy SQLite still recoverable.

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
