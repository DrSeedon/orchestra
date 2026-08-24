# #315 acceptance and oracle design

PLAN READY here means architecture/discussion ready only. The three user decisions in discussion.md
were resolved on 2026-08-24. Each ticket still requires a separately designed, behavior-specific RED
acceptance test committed against the current base. T1, T2, T3, corrective T3b, T4 and T5 are
materialized by their behavior tests plus frozen JSON fixtures under `fixtures/`; T6–T7 remain at
design only.
No implementation is implied by this directory.

T2 oracle history: commits `529711a9feda296e361bc8a09fd8f7ec65be4a57` and
`f09641624d371f9914e6e3eaed0b214384d9a9f4` are superseded and excluded from Phase 3. The first
could pass with a dead parallel store that no production `app.tm`/HTTP/MCP path called. The second
fixed that wiring gap but contradicted itself by requiring audit metadata to name
`tm_tasks.yougile_task_id` while banning the same name from the whole manifest. The replacement keeps
the production-path tests and scopes removed-domain bans only to canonical task/evidence/event bodies;
audit metadata may name excluded sources.

T3b supersedes only the human-projection/output clauses of merged T3: its evidence, event, conflict
and valid-time semantics remain. The first T3b oracle frozen in worker commit
`21e1b0718f8e8c3d30a06c2762b9d8257c815df4` (main equivalent `b693f302`) is permanently superseded
and excluded: its executable controls pin the pre-change `app/ia/knowledge.py` SHA and require the
old 3→4 generated-Markdown behavior, so they cannot pass after a correct implementation. The old test
and fixtures remain unchanged; their measurements are evidence text only in
`t3b-prechange-red-evidence.md`.

The corrected contract is `fixtures/t3b_agent_only_contract_v2.json`. Original T3 scenario S11 is
also explicitly excluded because it combines valid atomic new-topic registry/fact/event behavior with
superseded `README.md` and `topic.md` assertions. Corrected T3b replaces that structured part in
`test_t3b_v2_new_topic_is_atomic_structured_json_without_generated_human_output`; every other original
T3 node remains selected. T3b requires JSON-only canonical writes and one agent-facing typed tool.

Corrected pre-implementation execution on 2026-08-25:

- the exact three-control command returned `3 passed in 0.14s`;
- the exact full command in the T3b table returned
  `6 failed, 20 passed, 1 deselected in 0.34s` (exit 1);
- the replacement S11 node first fails on `{'.json', '.md'} <= {'.json'}`, proving the current
  generated-Markdown behavior is still present;
- the remaining five behavior nodes first fail on
  `#315 T3b missing behavior: app.ia.knowledge.knowledge_api is not callable`;
- all 17 selected original T3 nodes plus all 3 invariant controls are green. The only deselection is
  the explicitly superseded original S11 node.

T4 oracle history: worker commit `863c7bd9e152f9dc8da948038d007d02c020eab7` (main equivalent
`020f32f1`) is permanently superseded and excluded. Its alternate-backend behavior entered the T3
helper with `tmp_path/alternate-mode`, but that helper writes `registry-input.json` before creating
the directory. The intended implementation therefore reached 10/11 and then failed with an unrelated
`FileNotFoundError`. V2 keeps every head/fallback/wiring assertion, creates that root explicitly and
adds an invariant control that independently executes the complete alternate fixture setup.

## Smoke probes (not acceptance oracles)

The test_smoke_t*.py files are deliberately minimal missing-seam diagnostics. Each only checks that a future
path exists. They are not behavioral RED tests, do not prove an acceptance criterion, and must never be
reported as frozen oracles. They remain useful as early diagnostics.

T7 intentionally has no smoke probe: its first executable artifact must be the production-shaped
behavioral RED, because path/symbol existence cannot prove document ownership, prompt delivery or cutover.
T3b also has no smoke: its corrected controls are invariant fixture/count, byte-preserving reference
import and real T1–T3 structured-behavior checks. Agent API reachability and zero generated Markdown
are behavior nodes, so they are RED before implementation and green after it.

| Ticket | Smoke command | Expected current result |
|---|---|---|
| T1 | uv run python -m pytest docs/tasks/315/acceptance/test_smoke_t1_namespace.py -q | RED: smoke: canonical typed namespace resolver is missing |
| T2 | uv run python -m pytest docs/tasks/315/acceptance/test_smoke_t2_task_parity.py -q | RED: smoke: stable task identity facade is missing |
| T3 | uv run python -m pytest docs/tasks/315/acceptance/test_smoke_t3_promotion.py -q | RED: smoke: evidence-backed promotion seam is missing |
| T4 | uv run python -m pytest docs/tasks/315/acceptance/test_smoke_t4_heads.py -q | RED: smoke: canonical/projection/indexed heads are missing |
| T5 | uv run python -m pytest docs/tasks/315/acceptance/test_smoke_t5_recovery_privacy.py -q | RED: smoke: session commit/pack/privacy boundary is missing |
| T6 | uv run python -m pytest docs/tasks/315/acceptance/test_smoke_t6_merge_cleanup.py -q | RED: smoke: task-to-evidence merge receipt is missing |

## Required behavioral oracle design before Phase 3

The following table is the design freeze target. T1–T5 commands are committed behavioral RED gates;
T6–T7 commands are still future commands. Each remaining ticket must turn its row into a real behavior
test, run it RED, commit that oracle, and only then implement. The smoke probe cannot satisfy any row.

| Ticket | Fixture/data source | Production path | Red regression | Positive control | Valid future alternate | Compound/fallback mutation | Deterministic command | Remains unmeasured |
|---|---|---|---|---|---|---|---|---|
| T1 namespace/schema | in-memory records for task, evidence, fact, session, resource, skill; secret-form fixture | namespace resolver → schema validator → private-field projection filter | missing resolver or cross-kind write must fail with typed validation error | valid URI round-trips and private fields are excluded from all derived payloads | equivalent URI parser/validator implementation with same normalized output | remove resolver check while adding a namespace-looking path in a shared fallback; test must still fail | uv run python -m pytest docs/tasks/315/acceptance/test_t1_namespace_behavior.py -q | production-scale URI cardinality, multi-tenant policy, real secret inventory |
| T2 task migration/facade | immutable #299 SQLite backup + Git task/evidence manifest; project #N fixtures and two contour events | task facade → stable-ID store → Git event/SQLite projection → task_list/task_get adapters | duplicate stable ID, changed #N, or facade response drift must fail | unchanged task list/get and exact project #N replay | alternative UUID/ULID encoding with identical manifest mapping | omit Git event but retain SQLite row, or omit projection row but retain facade cache; both must be detected | uv run python -m pytest docs/tasks/315/acceptance/test_t2_task_behavior.py -q | live two-contour race rate, 10k-record performance, user choice on contiguous global #N |
| T3 evidence/promotion | #256 18-query holdout plus 12 synthetic promotion cases: identical, conflict, supersedes, disputed, rejected, as-of, TTL, missing anchor | promotion API → evidence resolver → topic registry → fact event/CAS → current query | source-less promotion, silent same-key overwrite, lost rejected fact, or wrong as-of must fail | valid evidence-linked current fact and idempotent replay | human-approved supersession workflow producing the same explicit event shape | remove provenance validation while adding a fallback topic parser; remove status filter while keeping current row; both mutations must fail | uv run python -m pytest docs/tasks/315/acceptance/test_t3_promotion_behavior.py -q | semantic duplicate-topic rate, answer utility, reviewer burden, real authoring ergonomics |
| T3b agent-only correction v2 | immutable fixture/count contract, synthetic historical docs/tasks/docs/kb/TODO/session corpus, all original T3 nodes except mixed S11, and direct-file/SQLite/vector/wiring sentinels; old SHA and 3→4 measurement live only in excluded pre-change evidence | single MCP `knowledge` tool → POST `/api/knowledge` → `knowledge_api` → KnowledgeService structured JSON/event/evidence owners | generated Markdown/human metadata, missing agent API, rewritten historical source, missing progressive level, production wiring bypass or fallback storage winning over absent canonical truth must fail | fixture/count and mutant detector execute; reference import preserves exact paths/bytes; real T1–T3 fact/event/evidence behavior stays green; corrected agent API/import/new-topic behavior becomes green | extra JSON fields/index backend and different compact agent payload shapes are allowed if summary < record < evidence and ownership/heads stay identical | hide `.markdown` plus `human_projection`; delete canonical then offer direct path, SQLite payload and vector hit together; bypass MCP→HTTP or HTTP→owner — all must fail | `uv run python -m pytest docs/tasks/315/acceptance/test_t3_promotion_behavior.py docs/tasks/315/acceptance/test_t3b_agent_only_knowledge_behavior_v2.py --deselect 'docs/tasks/315/acceptance/test_t3_promotion_behavior.py::test_t3_exact_promotion_scenario[S11]' -q` | agent task success, corpus import duration and payload/tool-call effect until separately measured |
| T4 heads/projections v2 | frozen T1–T3b contract/record hashes; real TaskStore/fact changes; nonempty one-file/one-log legacy corpus; five mutation bundles; self-contained alternate fixture root | MCP `knowledge(query)` → POST `/api/knowledge` → `knowledge_api` → shared projection owner → SQLite current/FTS; `/api/memory/search|reindex` are compatibility consumers of the same owner | stale/forged SQLite or vector content winning, absent heads/debt, projection/index failure erasing current canonical results, direct source fallback or route bypass must fail | five invariant controls keep T1–T3b agent query and real task/fact/corpus fixtures green and execute alternate-mode setup before any projection import; synchronous current/FTS returns two current records with separate heads and visible vector/log debt | injected backend implementing `replace_current`/`search_current` may reorder items and add safe metadata without changing normalized records/heads | forge equal head with stale payload; delete canonical while leaving SQLite/vector/file inputs; vector failure plus fallback hit; projection write failure after commit; bypass shared owner through legacy route — all must fail | `uv run python -m pytest docs/tasks/315/acceptance/test_t4_projection_heads_behavior_v2.py -q` | real embedder latency, index size growth, production restart timing |
| T5 session/pack/privacy | real AgentSession/SessionManager fixture with 3 messages; 5 valid canonical task/evidence/fact/session objects; 3 secret sentinels; OVPack input manifest; 7 compound mutants | SessionManager → AgentSession → sync JSON archive/event → background extraction; scripts.ia_pack validate/build/restore → scripts.ia_replay replay/rollback → SQLite/FTS/vector rebuild | extraction deleting archive, target mutation before full validation, auto/source-less promotion, state loss, secret leak, wrong-head rollback or duplicate retry must fail | four invariant controls pin T1–T4, reach real manager/session, validate statuses/privacy and perform nonempty order-independent reference pack/restore; valid production restore/replay reproduces exact head | OVPack object order and additive safe manifest metadata may vary while normalized objects/checksums/head remain identical; `atomicity_claim` stays false | extraction failure; checksum corruption with target sentinel; source-less post-restore promotion; one nested secret across canonical/payload/prompt/SQLite/FTS/vector/log; dropped tombstone; wrong rollback head; duplicate archive/event retry | `uv run python -m pytest docs/tasks/315/acceptance/test_t5_recovery_privacy_behavior.py -q` | legal purge semantics, key-management operations, real backup duration/size |
| T6 merge/cleanup | merge-operation fixtures covering target commit success + task-link/RAG/next-task partials; #309 route/duplicate inventories | pinned session merge → Git target commit → task/evidence receipt → projection queue → cleanup gates | treating secondary failure as no merge, losing link receipt, or deleting compatibility path before oracle must fail | target commit and partial states are distinct; existing v1 recovery path remains callable | alternate merge runner preserving same operation-state/receipt contract | remove partial-state branch while retaining success branch; route cleanup with stale legacy caller; both must fail | uv run python -m pytest docs/tasks/315/acceptance/test_t6_merge_behavior.py -q | live route/click telemetry, user-visible progress behavior, proxy-manager deployment behavior |
| T7 prompt/document migration/cutover | frozen tracked inventory of every `docs/tasks/*.md`, `docs/kb/*.md`, TODO/instruction source and session archive plus legacy reference corpus and assembled-prompt matrix for every runtime | inventory classifier → byte-preserving structured evidence/archive index → single typed `knowledge` tool + typed task IDs → project prompt/skill assembly → legacy/shadow/canonical cutover gate | arbitrary Markdown becoming canonical/regenerated, rewritten historical evidence, multiple/direct storage tools, projection-as-truth or destructive SQLite removal before gates must fail | every path classified exactly once; historical hashes unchanged; all legacy refs resolve; zero generated human files/summaries; every assembled runtime prompt contains the single tool/typed-ID anchors; rollback restores legacy-compatible reads | additional archive classes/JSON metadata and runtime prompt layouts are allowed when they preserve normalized ownership and delivery | retain editable Markdown co-master beside JSON; patch only source prompt while one assembled runtime stays stale; forge parity then delete SQLite; rewrite evidence while updating alias; let file/vector fallback hide canonical failure — each must fail | uv run python -m pytest docs/tasks/315/acceptance/test_t7_prompt_document_cutover_behavior.py -q | real authoring ergonomics, total corpus migration duration, live rollback duration and task success until separately measured |

## Quantitative gate (future implementation evidence)

Report against a fresh immutable manifest, not hard-coded historical counts:

replay_parity, duplicate_identity_count == 0, source_less_promoted_fact_count == 0,
exact/current/rejected recall, stale contradictions, projection read-after-write, task facade parity,
conflict loss, A/B/A/B prompt footprint/tool calls/time, privacy secret scan, and rollback replay parity.
T7 adds: classified_path_count equals frozen inventory count with no overlap/unclassified path; historical
evidence byte hashes and Git refs unchanged; legacy reference resolution 100%; all assembled runtime
prompts carry one `knowledge` tool + typed task anchors; generated human-readable output count 0;
shadow/canonical owner parity; no destructive
SQLite removal before a live cutover receipt; reversible rollback reproduces the pre-cutover facade.
