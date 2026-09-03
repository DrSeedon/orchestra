# #315 — synthesis of the information architecture

Дата исследования: 2026-08-24. Это Phase 1 research для открытого архитектурного решения;
код, production, конфигурация, сервисы, БД и модельные/eval/review-вызовы не изменялись.

## Вопрос

- **Context:** Orchestra хранит задачи, доказательства задач, `docs/kb` topics, session/log history,
  skills/resources и несколько поисковых индексов в Git, SQLite и `vec.db`.
- **Change under test:** один typed namespace/data plane с разными record contracts, где Git/файлы
  остаются canonical для reviewable evidence, SQLite обслуживает current-state/query projections,
  а FTS/vector и hot/warm/cold delivery являются производными.
- **Baseline:** текущий ручной Markdown+Git contract + SQLite task/session/log state + async
  FTS/vector RAG; target seams из #256 и #299; cleanup decisions #309; discussion/spec #295.
- **Outcome:** отсутствие dual truth и duplicate identity, provenance-complete promotion, exact /
  current / rejected recall, stale-head fallback, replay/rollback parity, task facade parity,
  projection read-after-write, conflict-loss and privacy evidence. Prompt/tool/time metrics remain
  acceptance measurements, not assumptions.

## Гипотезы и фальсификаторы

| Гипотеза | Что должно быть верно | Что её опровергает |
|---|---|---|
| H1: усиленного Markdown-only contract достаточно | every fact is linked, current/rejected queries are deterministic, all readers observe the same HEAD | #256 measured source-link coverage 7/12, one unlisted topic, 545 missing/stale index files, current proxy 1/6 and stale contradiction 1/6; no atomic fact identity exists |
| H2: один DB/JSON store должен стать canonical для всех domains | task state, evidence, facts, sessions and skills share compatible lifecycle and review/portability semantics | #256/#299 separate task state from evidence and facts; Git review/recovery is required for evidence and task history; one append-only JSONL is a merge hotspot |
| H3: OpenViking wholesale adoption solves the boundary | its unified filesystem can safely own operational task state, immutable evidence and typed facts | official docs make FS the source and vector derived, but also rely on async LLM compression/rerank, standalone daemon, and backup that is not atomic; those do not supply Orchestra's evidence/merge contract |
| H4: one logical namespace with strict typed contracts is sufficient | one URI/identity vocabulary, separate lifecycle/validator/projection per record type, and explicit heads preserve both unity and separation | any record can be written through another path without identity/CAS/provenance validation, or projections can answer a different canonical head |

## Findings

### 1. Current-state owner/writer/reader matrix

| Domain / canonical status | Current owner | Writers | Readers / projections | Identity and observed gap |
|---|---|---|---|---|
| Operational task state | SQLite `tm_projects`/`tm_tasks` and related tables; schema in `app/db.py:309-383`, business owner `app/tm.py` | `app/tm.py:create_task/update_task`, payment helpers, merge lifecycle `app/routes/sessions.py:1665-1795`, `/api/tm` and MCP `task_*` adapters | `app/routes/tm.py`, MCP `task_list/get`, dashboard task views, branch naming and merge links | DB integer row id, project-local `par_number`, `docs/tasks/<N>/`, `task-N/branch`; #299 says stable UUID/ULID + preserved project `#N` is needed; current Git canonical task record is not implemented |
| Task evidence (research/report/metrics/eval) | Git blobs under `docs/tasks/<N>/` | user/agent writes and Git commits; merge is `workspace.py`/session merge lifecycle | direct file reads, RAG file index, human review, `search_memory` | path and Git commit/blob are evidence identity; no typed evidence record or enforced evidence→fact promotion |
| KB topics | Markdown `docs/kb/*.md`; README is registry owner by convention | manual append by agents; no server-side promotion API | memory gate reads README + topic files; RAG file index; prompt/build consumers | topic slug/path and README membership; duplicate topics and missing source links are possible; #256 measured 7/12 source-link coverage and 1/12 unlisted topic |
| Typed facts | **Absent** in current code | none | no current-state fact query; RAG returns untyped chunks | `fact_key`, status, valid-time and supersedes are design requirements from #256, not live schema |
| Session runtime state | SQLite `sessions` plus in-memory `AgentSession` | `app/session.py`, `app/manager.py`, `app/db.py:save_session/update_session_lifecycle` | manager resume, session routes, dashboard, runtime handoff/merge recovery | durable session UUID, `(name, scope)` uniqueness, optional `task_id`; `last_summary` and logs are not curated facts |
| Session/log evidence | SQLite `logs`, `turn_usage`, delivery/handoff tables; logs are immutable rows | session turn/logger and delivery code, `app/db.py:add_log` | session history, `search_memory` log index, recovery/audit paths | log autoincrement is insertion order, not event order; #340 establishes timestamp ordering for pairing |
| Skills/resources | repo `pipelines/`, `.codex/skills/`, `.claude/skills/`, `AGENTS/CLAUDE` delivery mirrors | repository/platform sync and project authors | prompt assembly, runtime tool registry, worker worktrees | path/name and generated mirror; no unified typed resource identity; prompt delivery remains a separate contract |
| SQLite/FTS/vector indexes | `data/vec.db` is derived; SQLite `orchestra.db` is operational storage | `app/rag.py` creates `files`, `file_chunks`, `logs_indexed`, `log_chunks`, FTS5 and sqlite-vec rows; `app/rag_service.py` schedules slices | `/api/memory/search`, MCP `search_memory`, dashboard memory route | file key `(project,path,sha256)`, log key `log_id`; no canonical Git `target_head`/`indexed_head`; #256 measured 545 debt and no read-after-write |

The matrix distinguishes *one data plane* from *one contract*. A shared namespace is safe only if
the owner/validator and identity remain domain-specific. `db.py` currently owns schema and low-level
transactions; `tm.py` owns task business rules; `session.py`/`manager.py` own live session state;
`rag.py` owns derived indexes; no module owns typed fact promotion.

### 2. Duplicate identity and write paths

| Identity/state | Duplicate paths | Dependency / resolution |
|---|---|---|
| Task number | `tm_tasks.id`, `(project_id,par_number)`, `docs/tasks/<N>`, `#N`/`PREFIX-N`, branch `task-N/name` | #299 stable UUID/ULID becomes canonical; preserve project-scoped #N as display/lease identity; all adapters resolve through one facade |
| Task lifecycle | `tm_tasks.status`, session `task_id`, branch/worker lifecycle, linked `git_commits`, merge response `task_status` | merge must emit one task event and projection receipt; payment/YouGile paths are removed per #309/#299, not migrated |
| Evidence | research/report Markdown, commit messages, SQLite logs, RAG chunks | evidence remains immutable Git source; logs/RAG are references/projections and must not promote source-less chunks |
| Topic | topic Markdown path, README registry line, generated prompt/hot registry | deterministic topic registry is the one resolver; missing/ambiguous topic is a write error |
| Fact | currently only prose repetitions; future `fact_key` + `fact_id` | same `(project,topic,fact_key)` requires identical event, explicit supersedes, or disputed state; similarity can suggest only |
| Freshness | Git HEAD, file mtime/sha, RAG per-file rows, `index_status.pending_files` | add `canonical_head`, `projection_head`, `indexed_head`; direct canonical fallback on mismatch |
| Session memory | `last_summary`, compact artifacts, logs, task evidence, KB facts | session history is cold evidence; promotion is explicit and source-linked, never an automatic overwrite |
| Skills/resources | repository files, prompt mirrors, tool registry | keep prompt/runtime delivery owner separate; namespace reference may point to them but does not duplicate body |

### 3. What the existing measurements establish

- #256 direct corpus baseline: 1,092 indexable Markdown files; 547 have current SHA; freshness debt
  545 (=516 missing +29 stale); frozen 18-query holdout exact/current/rejected R@5 = 33.3%/33.3%/50.0%;
  stale contradiction 1/6; source-link coverage 7/12; promotion recall unmeasured; current task proxy
  1/6; prompt registry/procedure footprint 7,872 bytes. These are historical baselines, not future
  constants ([#256 structure](../256/eval/structure.raw.json), [baseline](../256/eval/baseline.raw.json)).
- #299 safe SQLite backup baseline on 2026-08-23: 19 projects, 601 tasks, 2 payments, 3 allocations,
  488 sync rows, 486 linked hashes; later recheck saw 489 linked hashes while one write continued.
  Migration therefore needs a fresh immutable backup, cutoff/head and manifest, not hard-coded counts.
- #309 frozen backup cutoff 2026-08-24T06:12:06.860886+00:00: 611 tasks, 158,775 logs, 196 merge
  operations, 128 background jobs, 12,066 usage snapshots; payments 2, allocations 3, sync_log 488.
  Route/UI request and click telemetry is explicitly unmeasured. `update_progress` had 5 paired
  successful worker calls, so UI hiding is reversible and API deletion is not justified.

### 4. Architecture conclusion

**Recommended:** one logical typed namespace/data plane, separate record contracts and projections:

1. Git-backed operational task records and immutable/reviewable evidence remain canonical and mergeable.
2. Curated topic/fact records share the namespace but have `fact_key`, status/valid-time, provenance,
   supersedes/disputed rules and a deterministic promotion API.
3. Session history and skills/resources are distinct record types with separate privacy and retention;
   their URIs can be resolved through the same namespace without sharing task/fact schema.
4. SQLite current/event/FTS is a content-bound projection with explicit heads; vector/log remains cold
   and rebuildable. `canonical_head != projection_head` is visible, and canonical fallback is mandatory.
5. No shapeless JSONL/Markdown dump and no independent task+KB truth. One canonical source per record,
   one logical identity, named projections.

This is **LIKELY**, not measured as an outcome: #256 has mechanism-level evidence and direct baseline,
but answer utility, promotion recall and A/B latency of the candidate path are explicitly unmeasured.

### 5. Cleanup and sequencing reconciliation

- #309 progress UI: hide selected-agent progress renderers behind a reversible migration/flag first;
  retain worker API, fields and session compatibility until active-session negative controls pass.
- #309 legacy merge route: remove only after merge-operation-v1 OpenAPI negative oracle and recovery
  replay. The merge lifecycle itself is retained and becomes the task→evidence→projection handoff.
- #309 duplicate model refresh registration: merge duplicate handler before any route inventory is used
  as an oracle. This is separate from #315 and does not authorize deferred #298 model routing.
- #309 duplicate refresh/proxy controls: proxy-manager remains the external owner; retain status/link
  surface while hiding mutation controls only under its own approved experiment.
- **YouGile and payments:** DELETE, pre-decided by #299/#309. They are not migrated into the new task
  or knowledge namespace. Before deleting fields/tables, export a fresh manifest and verify no live
  reader/import path remains; technical tombstones are not legal erasure.
- #298 model routing: intentionally deferred; keep current route/config contracts and do not fold them
  into the information-architecture migration.
- #299 independent implementation plan and any unstarted #256 implementation are superseded as
  standalone plans by this joined plan, while their research, metrics, evidence and historical
  baselines remain immutable and linked.

### 6. Risks and open gaps

- stable fact-key vocabulary and exact serialization are design decisions, not existing APIs;
- private-field policy and legal purge/remote-retention procedure remain open (#299);
- two-contour/offline lease gaps versus contiguous global #N remains a user decision;
- semantic duplicate-topic rate and candidate answer utility remain unmeasured;
- vector/rerank/LLM compression claims are product claims, not measured Orchestra benefits;
- OpenViking's current backup docs state backups are online/non-atomic and official repo issue #3875
  reports a restore-overwrite failure, so its pack flow is a mechanism to adapt, not a recovery oracle;
- existing app processes load Python code in memory until restart; this research does not restart or
  mutate services.

## Counter-evidence

- **Markdown-only:** strongest reviewability/offline portability; retained as canonical evidence, rejected
  only as complete typed-fact/current-state system due #256 measured gaps.
- **DB-only:** strongest constraints/querying; rejected as sole canonical evidence because Git review,
  clone recovery and task/evidence portability are required by #299/#256.
- **Graph-first:** useful optional relationship projection, but #256 recorded Graphiti false retirements
  and silent/drop complexity; rejected as canonical supersession engine.
- **One JSONL:** easy append/replay, but #299 identifies one merge-hotspot path and no typed conflict
  boundary; reject as the primary shared store.
- **OpenViking wholesale:** compelling typed namespace, FS/index split, progressive loading and packs;
  reject wholesale adoption until its daemon, async LLM decisions, privacy/tenant model, backup failure
  modes and AGPL boundary are acceptable and its semantics are mapped to Git/CAS/task rules.
- **Separate independent task and KB systems:** allows domain-specific contracts but creates duplicate
  identity/head/provenance paths; reject independence, retain separate contracts within one data plane.

## Confidence

| Finding | Confidence | Evidence reason |
|---|---|---|
| Current task/KB/RAG owners and missing typed-fact owner | CONFIRMED | Current source code and #256/#299/#309 artifacts |
| One namespace + separate contracts is the best fit | LIKELY | Multi-source architecture synthesis; candidate outcome not implemented |
| OpenViking mechanisms are transferable selectively | LIKELY | Official current docs/repo, but product claims not measured locally |
| Automatic compression/dedup/supersession should be canonical | REFUTED | #256 counter-evidence plus OpenViking docs explicitly assign LLM decisions to compressor |
| Proposed quantitative gate will pass | UNCERTAIN | No implementation/eval authorized; only metric definitions and historical baselines exist |

## Sources

Local primary/evidence sources opened this session:

1. `docs/tasks/256/research.md`, `comparison.md`, `metrics.md`, `eval/structure.raw.json`, `eval/baseline.raw.json` — baseline and candidate typed-fact seam.
2. `docs/tasks/299/research.md`, `docs/kb/task-storage-architecture.md` — task identity, Git/SQLite projection and migration baseline.
3. `docs/artifacts/knowledge-base-architecture-256.html` — #295 approved discussion/spec and five decision board.
4. `docs/tasks/309/research.md`, `metrics.md`, `evidence/decision-matrix.csv`, `evidence/db-footprint.csv` — cleanup decisions and cutoff measurements.
5. `app/db.py`, `app/tm.py`, `app/routes/tm.py`, `app/rag.py`, `app/rag_service.py`, `app/routes/memory.py`, `app/session.py`, `app/manager.py`, `app/routes/sessions.py`, `app/merge_operations.py`, `app/workspace.py`, `app/mcp_stdio.py` — current owners and call paths.

Official OpenViking sources fetched 2026-08-24 (current docs/repo; exact URLs retained):

6. https://docs.openviking.ai/en/concepts/01-architecture — architecture, types, storage, retrieval, session and service boundaries.
7. https://docs.openviking.ai/en/concepts/02-context-types — Resource/Memory/Skill lifecycle and namespaces.
8. https://docs.openviking.ai/en/concepts/03-context-layers — L0/L1/L2 limits and sidecar semantics.
9. https://docs.openviking.ai/en/concepts/04-viking-uri — URI format/scopes/privacy boundary.
10. https://docs.openviking.ai/en/concepts/05-storage — AGFS/vector separation and URI operations.
11. https://docs.openviking.ai/en/concepts/06-extraction — parser/tree/async semantic queue.
12. https://docs.openviking.ai/en/concepts/07-retrieval — intent/hierarchical retrieval/rerank and fallback.
13. https://docs.openviking.ai/en/concepts/08-session — session commit/archive/background extraction.
14. https://docs.openviking.ai/en/concepts/09-transaction — path locks and crash recovery.
15. https://github.com/volcengine/OpenViking/blob/main/docs/en/guides/09-ovpack.md — OVPack v3, validation, conflict policy and non-atomic backup.
16. https://docs.openviking.ai/en/concepts/11-multi-tenant — account/user/role isolation.
17. https://docs.openviking.ai/en/concepts/12-metrics — Prometheus/observer/stats boundary.
18. https://docs.openviking.ai/en/concepts/10-encryption — at-rest encryption/key isolation.
19. https://docs.openviking.ai/en/concepts/13-privacy — placeholder extraction/restore and versioned private config.
20. https://docs.openviking.ai/en/concepts/14-multi-write-storage — primary/backup replication and consistency.
21. https://github.com/volcengine/OpenViking — official repository, current activity, license and v0.4.16 context.
22. https://github.com/volcengine/OpenViking/releases — v0.4.16 latest release (2026-08-21), active release stream.
23. https://github.com/volcengine/OpenViking/issues/3875 — official counter-evidence on restore-overwrite failure.

OpenViking metadata as observed: latest GitHub release **v0.4.16**, released 2026-08-21; repository
shows 2,071 commits, 169 issues, 332 pull requests at fetch time; main project **AGPLv3**, `crates/ov_cli`
and examples Apache-2.0. Documentation pages were current as crawled 2026-08-24; version-sensitive
claims are therefore marked as such and must be rechecked before implementation.

## Review constraint

The user explicitly prohibited model/provider/eval/review calls. No model review was made. This is
intentional; the evidence trail, counter-evidence and confidence labels are the review substitute for
this research-only phase and must not be reported as a reviewer verdict.
