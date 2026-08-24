# #315 acceptance and oracle design

PLAN READY here means architecture/discussion ready only. Phase 3 is blocked until the three user
decisions in discussion.md are resolved and each ticket has a separately designed, behavior-specific
RED acceptance test committed against the current base. No implementation is implied by this directory.

## Smoke probes (not acceptance oracles)

The test_smoke_t*.py files are deliberately minimal missing-seam diagnostics. Each only checks that a future
path exists. They are not behavioral RED tests, do not prove an acceptance criterion, and must never be
reported as frozen oracles. They remain useful as early diagnostics.

| Ticket | Smoke command | Expected current result |
|---|---|---|
| T1 | uv run python -m pytest docs/tasks/315/acceptance/test_smoke_t1_namespace.py -q | RED: smoke: canonical typed namespace resolver is missing |
| T2 | uv run python -m pytest docs/tasks/315/acceptance/test_smoke_t2_task_parity.py -q | RED: smoke: stable task identity facade is missing |
| T3 | uv run python -m pytest docs/tasks/315/acceptance/test_smoke_t3_promotion.py -q | RED: smoke: evidence-backed promotion seam is missing |
| T4 | uv run python -m pytest docs/tasks/315/acceptance/test_smoke_t4_heads.py -q | RED: smoke: canonical/projection/indexed heads are missing |
| T5 | uv run python -m pytest docs/tasks/315/acceptance/test_smoke_t5_recovery_privacy.py -q | RED: smoke: session commit/pack/privacy boundary is missing |
| T6 | uv run python -m pytest docs/tasks/315/acceptance/test_smoke_t6_merge_cleanup.py -q | RED: smoke: task-to-evidence merge receipt is missing |

## Required behavioral oracle design before Phase 3

The following table is the design freeze target. The commands are exact future commands, not currently
committed RED tests. Each ticket must turn its row into a real behavior test, run it RED, commit that
oracle, and only then implement. The smoke probe cannot satisfy any row.

| Ticket | Fixture/data source | Production path | Red regression | Positive control | Valid future alternate | Compound/fallback mutation | Deterministic command | Remains unmeasured |
|---|---|---|---|---|---|---|---|---|
| T1 namespace/schema | in-memory records for task, evidence, fact, session, resource, skill; secret-form fixture | namespace resolver → schema validator → private-field projection filter | missing resolver or cross-kind write must fail with typed validation error | valid URI round-trips and private fields are excluded from all derived payloads | equivalent URI parser/validator implementation with same normalized output | remove resolver check while adding a namespace-looking path in a shared fallback; test must still fail | uv run python -m pytest docs/tasks/315/acceptance/test_t1_namespace_behavior.py -q | production-scale URI cardinality, multi-tenant policy, real secret inventory |
| T2 task migration/facade | immutable #299 SQLite backup + Git task/evidence manifest; project #N fixtures and two contour events | task facade → stable-ID store → Git event/SQLite projection → task_list/task_get adapters | duplicate stable ID, changed #N, or facade response drift must fail | unchanged task list/get and exact project #N replay | alternative UUID/ULID encoding with identical manifest mapping | omit Git event but retain SQLite row, or omit projection row but retain facade cache; both must be detected | uv run python -m pytest docs/tasks/315/acceptance/test_t2_task_behavior.py -q | live two-contour race rate, 10k-record performance, user choice on contiguous global #N |
| T3 evidence/promotion | #256 18-query holdout plus 12 synthetic promotion cases: identical, conflict, supersedes, disputed, rejected, as-of, TTL, missing anchor | promotion API → evidence resolver → topic registry → fact event/CAS → current query | source-less promotion, silent same-key overwrite, lost rejected fact, or wrong as-of must fail | valid evidence-linked current fact and idempotent replay | human-approved supersession workflow producing the same explicit event shape | remove provenance validation while adding a fallback topic parser; remove status filter while keeping current row; both mutations must fail | uv run python -m pytest docs/tasks/315/acceptance/test_t3_promotion_behavior.py -q | semantic duplicate-topic rate, answer utility, reviewer burden, real authoring ergonomics |
| T4 heads/projections | frozen Git head + changed topic/task records; SQLite projection copy with deliberately stale FTS/vector heads | merge generation → synchronous SQLite fold → async FTS/vector queue → memory search/fallback | stale projection returning “not found”, missing head receipt, or vector failure erasing current result must fail | equal-head projection returns typed current result; stale vector still returns SQLite result with debt | alternate projection backend with identical head/fallback contract | delete canonical fallback and leave stale SQLite row; remove head comparison and rely on pending count; both must fail | uv run python -m pytest docs/tasks/315/acceptance/test_t4_heads_behavior.py -q | real embedder latency, index size growth, production restart timing |
| T5 session/pack/privacy | synthetic session archive with extraction failure; OVPack-like manifest/checksum/scope fixtures; secret-form corpus | session commit → immutable archive → background extraction; pack validate/restore; redacted projections | archive loss, write-before-manifest-validation, scope bypass, or secret in index/prompt must fail | successful archive and valid restore/rebuild with zero secret matches | alternate pack format with same validated manifest and restore semantics | skip archive then return extraction success; validate checksum only after write; restore redacted body through fallback; all must fail | uv run python -m pytest docs/tasks/315/acceptance/test_t5_recovery_behavior.py -q | legal purge semantics, key-management operations, real backup duration/size |
| T6 merge/cleanup | merge-operation fixtures covering target commit success + task-link/RAG/next-task partials; #309 route/duplicate inventories | pinned session merge → Git target commit → task/evidence receipt → projection queue → cleanup gates | treating secondary failure as no merge, losing link receipt, or deleting compatibility path before oracle must fail | target commit and partial states are distinct; existing v1 recovery path remains callable | alternate merge runner preserving same operation-state/receipt contract | remove partial-state branch while retaining success branch; route cleanup with stale legacy caller; both must fail | uv run python -m pytest docs/tasks/315/acceptance/test_t6_merge_behavior.py -q | live route/click telemetry, user-visible progress behavior, proxy-manager deployment behavior |

## Quantitative gate (future implementation evidence)

Report against a fresh immutable manifest, not hard-coded historical counts:

replay_parity, duplicate_identity_count == 0, source_less_promoted_fact_count == 0,
exact/current/rejected recall, stale contradictions, projection read-after-write, task facade parity,
conflict loss, A/B/A/B prompt footprint/tool calls/time, privacy secret scan, and rollback replay parity.
