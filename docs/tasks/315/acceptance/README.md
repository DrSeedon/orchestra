# #315 acceptance and oracle design

PLAN READY here means architecture/discussion ready only. The three user decisions in discussion.md
were resolved on 2026-08-24. Each ticket still requires a separately designed, behavior-specific RED
acceptance test committed against the current base. T1, T2, T3 and corrective T3b are materialized by
their behavior tests plus frozen JSON fixtures under `fixtures/`; T4–T7 remain at design only, and T4
is stopped until T3b is implemented/merged.
No implementation is implied by this directory.

T2 oracle history: commits `529711a9feda296e361bc8a09fd8f7ec65be4a57` and
`f09641624d371f9914e6e3eaed0b214384d9a9f4` are superseded and excluded from Phase 3. The first
could pass with a dead parallel store that no production `app.tm`/HTTP/MCP path called. The second
fixed that wiring gap but contradicted itself by requiring audit metadata to name
`tm_tasks.yougile_task_id` while banning the same name from the whole manifest. The replacement keeps
the production-path tests and scopes removed-domain bans only to canonical task/evidence/event bodies;
audit metadata may name excluded sources.

T3b supersedes only the human-projection/output clauses of merged T3: its evidence, event, conflict,
valid-time and 12-scenario semantics remain. The old T3 layout requirement for generated `README.md`
and `topic.md` is excluded from future implementation. Exact baseline: 2 generator call sites, 3
Markdown outputs at base initialization, 4 after a new topic, 2 frozen layout paths and 2 oracle
assertions. T3b requires JSON-only canonical writes and one agent-facing typed tool.

## Smoke probes (not acceptance oracles)

The test_smoke_t*.py files are deliberately minimal missing-seam diagnostics. Each only checks that a future
path exists. They are not behavioral RED tests, do not prove an acceptance criterion, and must never be
reported as frozen oracles. They remain useful as early diagnostics.

T7 intentionally has no smoke probe: its first executable artifact must be the production-shaped
behavioral RED, because path/symbol existence cannot prove document ownership, prompt delivery or cutover.
T3b also has no smoke: its controls must prove the current T3 Markdown mutation executes before the
agent-only behavior fails.

| Ticket | Smoke command | Expected current result |
|---|---|---|
| T1 | uv run python -m pytest docs/tasks/315/acceptance/test_smoke_t1_namespace.py -q | RED: smoke: canonical typed namespace resolver is missing |
| T2 | uv run python -m pytest docs/tasks/315/acceptance/test_smoke_t2_task_parity.py -q | RED: smoke: stable task identity facade is missing |
| T3 | uv run python -m pytest docs/tasks/315/acceptance/test_smoke_t3_promotion.py -q | RED: smoke: evidence-backed promotion seam is missing |
| T4 | uv run python -m pytest docs/tasks/315/acceptance/test_smoke_t4_heads.py -q | RED: smoke: canonical/projection/indexed heads are missing |
| T5 | uv run python -m pytest docs/tasks/315/acceptance/test_smoke_t5_recovery_privacy.py -q | RED: smoke: session commit/pack/privacy boundary is missing |
| T6 | uv run python -m pytest docs/tasks/315/acceptance/test_smoke_t6_merge_cleanup.py -q | RED: smoke: task-to-evidence merge receipt is missing |

## Required behavioral oracle design before Phase 3

The following table is the design freeze target. T1–T3b commands are committed behavioral RED gates;
T4–T7 commands are still future commands. Each remaining ticket must turn its row into a real behavior
test, run it RED, commit that oracle, and only then implement. The smoke probe cannot satisfy any row.

| Ticket | Fixture/data source | Production path | Red regression | Positive control | Valid future alternate | Compound/fallback mutation | Deterministic command | Remains unmeasured |
|---|---|---|---|---|---|---|---|---|
| T1 namespace/schema | in-memory records for task, evidence, fact, session, resource, skill; secret-form fixture | namespace resolver → schema validator → private-field projection filter | missing resolver or cross-kind write must fail with typed validation error | valid URI round-trips and private fields are excluded from all derived payloads | equivalent URI parser/validator implementation with same normalized output | remove resolver check while adding a namespace-looking path in a shared fallback; test must still fail | uv run python -m pytest docs/tasks/315/acceptance/test_t1_namespace_behavior.py -q | production-scale URI cardinality, multi-tenant policy, real secret inventory |
| T2 task migration/facade | immutable #299 SQLite backup + Git task/evidence manifest; project #N fixtures and two contour events | task facade → stable-ID store → Git event/SQLite projection → task_list/task_get adapters | duplicate stable ID, changed #N, or facade response drift must fail | unchanged task list/get and exact project #N replay | alternative UUID/ULID encoding with identical manifest mapping | omit Git event but retain SQLite row, or omit projection row but retain facade cache; both must be detected | uv run python -m pytest docs/tasks/315/acceptance/test_t2_task_behavior.py -q | live two-contour race rate, 10k-record performance, user choice on contiguous global #N |
| T3 evidence/promotion | #256 18-query holdout plus 12 synthetic promotion cases: identical, conflict, supersedes, disputed, rejected, as-of, TTL, missing anchor | promotion API → evidence resolver → topic registry → fact event/CAS → current query | source-less promotion, silent same-key overwrite, lost rejected fact, or wrong as-of must fail | valid evidence-linked current fact and idempotent replay | human-approved supersession workflow producing the same explicit event shape | remove provenance validation while adding a fallback topic parser; remove status filter while keeping current row; both mutations must fail | uv run python -m pytest docs/tasks/315/acceptance/test_t3_promotion_behavior.py -q | semantic duplicate-topic rate, answer utility, reviewer burden, real authoring ergonomics |
| T3b agent-only correction | merged T3 contract/implementation hashes, measured 3→4 Markdown mutation, synthetic historical docs/tasks/docs/kb/TODO/session corpus and direct-file/SQLite/vector fallback sentinels | single MCP `knowledge` tool → POST `/api/knowledge` → `knowledge_api` → KnowledgeService structured JSON/event/evidence owners | any generated Markdown/human summary, multiple agent tools, rewritten historical source, missing progressive level or fallback storage winning over absent canonical truth must fail | merged T3 structured promotion remains green; current Markdown generator demonstrably runs; historical bytes/hashes remain stable; JSON-only structured import/promotion/query succeeds through one tool | extra JSON fields/index backend and different compact agent payload shapes are allowed if summary < record < evidence and ownership/heads stay identical | hide `.markdown` below a generated directory plus `human_projection` in JSON; delete canonical then offer direct path, SQLite payload and vector hit together — all must fail | uv run python -m pytest docs/tasks/315/acceptance/test_t3b_agent_only_knowledge_behavior.py -q | agent task success, corpus import duration and payload/tool-call effect until separately measured |
| T4 heads/projections | STOPPED until T3b merges; frozen Git head + changed structured task/fact records; SQLite projection copy with deliberately stale FTS/vector heads | merge generation → synchronous SQLite fold → async FTS/vector queue → single typed knowledge query/fallback | stale projection returning “not found”, missing head receipt, vector failure erasing current result or direct file fallback must fail | equal-head typed projection returns current result; stale vector still returns typed result with debt | alternate projection backend with identical head/fallback contract | delete canonical fallback and leave stale SQLite row; forge equal head with stale payload; let vector/direct-file fallback hide canonical failure — each must fail | uv run python -m pytest docs/tasks/315/acceptance/test_t4_projection_heads_behavior.py -q | real embedder latency, index size growth, production restart timing |
| T5 session/pack/privacy | synthetic session archive with extraction failure; OVPack-like manifest/checksum/scope fixtures; secret-form corpus | session commit → immutable archive → background extraction; pack validate/restore; redacted projections | archive loss, write-before-manifest-validation, scope bypass, or secret in index/prompt must fail | successful archive and valid restore/rebuild with zero secret matches | alternate pack format with same validated manifest and restore semantics | skip archive then return extraction success; validate checksum only after write; restore redacted body through fallback; all must fail | uv run python -m pytest docs/tasks/315/acceptance/test_t5_recovery_behavior.py -q | legal purge semantics, key-management operations, real backup duration/size |
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
