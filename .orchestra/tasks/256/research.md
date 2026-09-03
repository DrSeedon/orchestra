# #256 — архитектура проектных знаний Orchestra

Дата: 2026-08-23. Только Phase 1: research + read-only/local measurements. Production code,
runtime state and deployment не менялись. Holdout не использовал внешние модели; единственный
разрешённый model review — Luna после mechanical completeness checks.

## Короткий ответ

Orchestra не должна выбирать между Markdown, SQLite, vector RAG, graph и event log как между
взаимоисключающими базами. У них разные обязанности:

1. **Canonical evidence остаётся в Git:** task research/report хранит полный источник и замер;
   тематический Markdown хранит компактные typed conclusions, которые человек может читать,
   ревьюить и переносить вместе с репозиторием.
2. **Write path становится типизированным:** новая находка проходит через topic registry и stable
   `fact_key`; обновление, rejected, disputed и superseded — состояния записи, а не свободные слова.
   Новый topic-файл разрешён только вместе с регистрацией и только когда существующего дома нет.
3. **SQLite становится синхронной производной current-state/control plane:** append-only
   `knowledge_events` + current fact view + FTS. Он даёт exact/current/rejected/as-of filters,
   idempotency, constraints и immediate shared search после merge, но не заменяет Git как truth.
4. **Нынешний vector+FTS RAG остаётся cold-history retriever:** embeddings и raw logs могут
   догонять асинхронно, но возвращают `target_head/indexed_head`. При долге typed facts читаются
   из синхронной проекции или прямо из canonical topic at HEAD; пустой stale index не имеет права
   отвечать «факта нет».
5. **Graph — только будущая производная для cross-topic/global вопросов.** Graphiti доказывает
   полезность valid-time/provenance, но current counter-evidence показывает ложное retirement и
   плохой conflict consolidation. Semantic similarity может предложить topic/fact candidate, но
   не может supersede знание.

Главный seam: **research evidence → deterministic topic resolution → typed fact event → canonical
topic update → merge generation → synchronous current/FTS projection → immediate search**, при этом
полный task artifact и все предыдущие версии остаются доступны. Это минимальный гибрид, который
закрывает orphan, stale contradiction и provenance, не вводя вторую независимую истину.

## 1. Вопрос и критерий решения (Step 0)

- **Context:** project-shared memory Orchestra: `docs/tasks`, `docs/kb`, `CLAUDE/AGENTS`, selected
  logs и производный hybrid RAG. Холодный исследователь/исполнитель должен найти не просто похожий
  текст, а полезное текущее или явно rejected знание с доказательством.
- **Change under test:** write/promotion seam с canonical topic resolution, fact identity,
  provenance, valid-time/status, deterministic supersession и visible projection freshness.
- **Baseline:** ручной Markdown+Git contract + async `vec.db` over Markdown/logs + текущий
  `memory-search` prompt.
- **Outcome:** exact/current/rejected recall; stale contradiction; provenance; time/tool calls/tokens
  to first useful fact; answer utility/task success; duplicate/orphan/promotion; integration lag;
  false supersession; prompt footprint. R@k/MRR — только retrieval diagnostics.

## 2. Гипотезы и фальсификаторы (Step 1)

| Гипотеза | Что доказало бы её неправильной | Результат |
|---|---|---|
| **H1. Усиленного Markdown-only контракта достаточно.** | После prompt-контракта research стабильно доходит в topic, topic всегда зарегистрирован, index догнан и current/rejected не конфликтуют. | **REFUTED как достаточное решение:** source-link coverage только 7/12, unlisted topic 1/12, current index coverage 50.1%, stale contradiction 1/6. Semantic promotion recall исторически не измерим. Git остаётся хорошим canonical evidence. |
| **H2. Relational/event typed facts должны заменить Markdown как единственный canonical store.** | DB-only сохраняет Git-review/portability, полный task evidence и не создаёт второй truth при ручных edits. | **REFUTED для единственного store:** SQLite даёт нужное enforcement, но repo knowledge обязано travel/review with Git. Подходит как projection/control plane. |
| **H3. Graph-first автоматически решит updates/contradictions.** | Current primary code/papers показывают безопасное scoped supersession, высокую consolidation accuracy и bounded ingestion. | **REFUTED:** Graphiti issue #1728 — 3 ложных retirement из 4 audit cases; issue #1275 — O(n) ingestion context и silent drops; MAB paper — 7% FC-SH. |
| **H4. Hybrid Git evidence + typed facts/events + derived retrieval даст нужные свойства без полной миграции.** | Любой named metric остаётся без owner; shared read-after-write требует full vector rebuild; false supersession остаётся LLM decision; prompt становится unbounded. | **LIKELY:** каждый owner и fallback определены, но effect не измерен до implementation holdout. |

## 3. Что реально есть сейчас

### 3.1 Canonical и derived слои

`app/rag.py` прямо считает индекс производным: schema/model change дропает таблицы и rebuild'ит
их из файлов/logs. Markdown-файл keyed by `(project,path)` и deduped по sha256; обновление удаляет
старые chunks и атомарно вставляет новые vec/FTS rows. Лог после `log_id` только append/dedup:
позднее заключение не обновляет ранний рабочий log и оба могут попасть в выдачу [1].

Canonical topic semantics существуют только в prompt/document contract: одна тема — один файл,
вывод append, refuted line stays, new topic gets README entry. Нет parser/validator, stable fact ID,
topic alias registry, evidence FK, overlap rule или merge gate [4][5].

### 3.2 Freshness path

Успешный `merge_worker` вызывает `rag_service.schedule_backfill(scope)`. Scheduler возвращает
`accepted/coalesced` сразу, обрабатывает файлы/logs срезами под 300-секундным бюджетом и хранит
только последний `pending_files` в памяти процесса. `index_status` до первого прохода пуст; target
Git HEAD, indexed HEAD, per-projection generation и indexed timestamp отсутствуют [2][3].

`search_memory` видит долг и предупреждает, что пустой ответ не доказывает отсутствие факта. Это
честно, но не доставляет новый факт: агент остаётся с сигналом “index behind” и должен сам идти в
grep. Read-after-write shared knowledge отсутствует [3].

### 3.3 Query и delivery

Current query — free text → file/log vector + FTS → RRF → top-k. Returned file hit сохраняет path;
log hit имеет `log_id/kind/author` в route payload, но MCP header показывает только kind/author.
Ни status, ни valid-time, ни current/rejected intent не участвуют в selection [1][3].

Cold pre-work делает `pwd` → README topic scan → one semantic search. Это два knowledge tools до
полезного факта. Current memory instruction 2,909 bytes, README 4,963 bytes, вместе 7,872 bytes;
полный AGENTS — 104,695 bytes. Это уже bounded, но topic registry можно доставить hot компактным
generated list, как Letta всегда показывает file tree, и убрать отдельный README read [4][16].

## 4. Direct measurements on current base

Полная методика, определения и raw artifacts: [`metrics.md`](./metrics.md),
[`eval/`](./eval/). Holdout написан до первого прогона и frozen sha256
`9e7c737d…9e466b`.

### 4.1 Retrieval holdout

18 новых queries: 6 exact, 6 current, 6 rejected; production-shaped `k=5`.

| Metric | Result |
|---|---:|
| fact recall@5 | **7/18 = 38.9%** |
| exact / current / rejected recall@5 | **33.3% / 33.3% / 50.0%** |
| current task-success proxy | **1/6 = 16.7%** |
| stale contradiction rate on current | **1/6 = 16.7%** |
| canonical provenance accuracy when fact found | **5/7 = 71.4%** |
| MRR@5 | **0.2287** |
| latency median / p95 | **335.6 / 682.8 ms** |
| content before first fact, median | **1,209 chars; 403-token proxy** |
| cross-project hits at `cross_project=false` | **0/18** |

Ограничения: same-author gold, n=6/class, approximate token proxy, live index (`indexing=true`)
instead of frozen DB. Это regression/mechanism diagnostic, не generalization benchmark.

### 4.2 Write/promotion and freshness

| Metric | Result | Exact counting rule |
|---|---:|---|
| topic registry coverage | **11/12 = 91.7%** | Topic file has a README link. `dashboard-quota-map.md` is unlisted. |
| source-link coverage since KB contract | **7/12 = 58.3%** | Changed research paths from contract-creation commit through HEAD; exact path occurs anywhere in a KB file, including `## Источники`. |
| unlinked research rate | **5/12 = 41.7%** | Complement; exact five paths retained in raw JSON. This does not adjudicate whether their conclusions were paraphrased elsewhere. |
| semantic promotion recall | **UNMEASURED** | Historical atomic fact IDs/anchors do not exist; a source path alone does not prove conclusion integration. 58.3% is at most a valid-promotion upper bound when source linkage is mandatory. |
| current index coverage | **547/1,092 = 50.1%** | Current file sha equals `vec.db.files.sha256`. |
| freshness debt | **545** | 516 missing + 29 stale; equals live service status. |
| orphaned index paths | **0** | Indexed path absent from disk. |

Эти числа не говорят, что vector search плох. Они говорят, что retrieval получает incomplete/stale
input, а write contract не обеспечивает promotion. Reranker/RRF/weights/pool/corpus split уже
исследованы и здесь намеренно не открываются заново: #133 не доказал superior embedder; #135
опроверг pool/RRF/weight candidates; #138 опроверг split при равном context budget [7–10].

## 5. External landscape: mechanisms, not brand choices

Полная exact table — [`comparison.md`](./comparison.md).

### 5.1 Markdown+Git and Letta MemFS

Git даёт content-addressed versions, commit parents/author/time/message и CAS update of refs [11–13].
Он идеально подходит для durable evidence and review, но ничего не знает о fact identity, current
rank, valid-time или orphan topic.

Current Letta MemFS — closest independent convergence: Git-backed Markdown, small `system/` hot tier,
always-visible file tree/descriptions, cold content on demand, worktrees for memory edits. Its reflection
prompt explicitly says inspect current memory, update an existing topic, create only if distinct, and
archive retired context [14–16]. Transferable mechanism: **compact hot registry + cold bodies + inspect
before integrate**. Counter-evidence: orphan/contradiction enforcement remains a model prompt, exactly
the layer that Orchestra's 7/12 source-link count shows can be skipped. It does not measure semantic promotion.

### 5.2 SQLite relational/FTS

SQLite supplies serializable ACID transactions, unique/check/FK constraints and snapshot reads [17–19].
FTS5 can be kept transactionally alongside content; external-content designs can drift and then require
rebuild — the official docs warn this explicitly [20]. Transferable mechanism: one local typed fact/event
transaction + deterministic current view. It fits Orchestra's existing SQLite operational model and offline
requirement. It must remain derived from Git HEAD or it creates two truths.

### 5.3 GraphRAG vs temporal graph

Microsoft GraphRAG is a batch transformation: documents→TextUnits→entities/relations/optional claims→
communities/reports→Parquet+vectors. It has strong source TextUnit links and paper evidence for global
sensemaking, but claims are off by default, indexing is expensive, repo is now maintenance-only, and
read-after-write/update semantics are not its contract [21–24]. It answers global corpus questions, not
Orchestra's exact current-state seam.

Graphiti/Zep is much closer: raw episodes remain, facts link to episodes, facts carry valid/invalid times,
groups isolate graphs, hybrid retrieval filters by type/date, and direct `add_triplet` can bypass extraction
[25–27]. Its original paper reports DMR 94.8% vs 93.4% and LongMemEval improvements up to 18.5% with 90%
lower latency vs its baselines [26].

But the falsifier matters more than the headline:

- issue #1728: 1,616/3,950 facts in one production graph were invalidated; manual four-case audit found
  **three collateral retirements**, caused by unscoped semantic candidates + LLM judgment [28];
- issue #1275: 300+ episodes produced an O(n) resolution prompt, max-token retries and silent dropped
  episodes [29];
- issue #1661: `reference_time` was persisted but absent from every read path [30];
- Reddy & Challaram's current paper reports Graphiti/Zep **7%** on MemoryAgentBench FC-SH and shows
  that extract-candidates + deterministic `max(version)` beats direct LLM policy execution; their own
  LongMemEval check bounds the claim because max timestamp is wrong for historical/aggregate questions
  [31].

Conclusion: borrow bitemporal/provenance fields, never the authority to invalidate by similarity.

### 5.4 Wikibase typed statements

Wikibase cleanly separates claim, qualifiers (including valid time), references and rank. Preferred is
default current/consensus; normal holds relevant/history; deprecated retains erroneous/outdated beliefs
and is normally excluded. Correct history uses start/end qualifiers rather than “deprecated” [32–35].
This exactly fits Orchestra's current/historical/rejected/disputed distinction and “do not delete the
road somebody will re-add.” It does not solve topic placement or read-after-write by itself.

### 5.5 Event log and projections

KurrentDB's primary contract is immutable per-entity streams, expected-revision writes, idempotent retry,
commit positions, and projections/checkpoints [36–39]. Transferable mechanism: append a knowledge event,
fold current state, expose projector position, rebuild deterministically. A separate event-store deployment
is disproportionate; the pattern fits two existing SQLite tables.

## 6. Recommended Orchestra architecture

### 6.1 Owners and tiers

```text
task research/report (raw evidence, Git)
        │ kb_promote: evidence ref + topic + fact key/status/time
        ▼
topic registry ──CAS/validation──► typed topic record (canonical Git)
                                       │ successful merge @ HEAD
                    ┌──────────────────┴──────────────────┐
                    ▼                                     ▼
        sync SQLite events/current/FTS           async existing vec/log backfill
                    │                                     │
                    └──── search_memory with HEAD watermark/fallback ────► agent
```

| Tier | Contains | Delivery | Budget rule |
|---|---|---|---|
| **Hot** | Compact generated topic registry: slug, aliases, one-line scope; current task state. | Inject once in system/session context or generated memory module. | One line/topic; no findings/evidence bodies. Keep total registry+procedure ≤ current 7,872-byte baseline except literal new topic lines. |
| **Warm** | Typed fact summaries selected by mode: current/rejected/as-of/disputed plus one provenance line. | One `search_memory` call. | Default ≤5 facts; claim+status/time+source, not whole chunks. |
| **Cold** | Full topic Markdown, task research/report, raw measurement artifacts and selected logs. | Explicit `get_fact_evidence`/file read or existing RAG fallback. | On demand; never always inject. |

### 6.2 Canonical record

Each promoted conclusion needs these fields, whether serialized as a strict Markdown block/frontmatter or
a nearby tracked structured record. Exact syntax is Phase 2, not decided here.

| Field | Rule |
|---|---|
| `fact_id` | Stable UUID/content-independent ID. Never reused. |
| `project_id`, `topic_id` | Server-derived project + registry-owned topic; arbitrary path is invalid. |
| `fact_key` | Stable semantic identity chosen from topic schema, e.g. `codex_review.default_model`. This, not embedding similarity, defines replacement candidates. |
| `claim` | Atomic statement, qualifiers preserved. |
| `status` | `current`, `historical`, `rejected`, `disputed`, `stale-needs-validation`. |
| `valid_from`, `valid_to` | When true in the system/world. Null is unknown, not beginning/end of time. |
| `observed_at`, `recorded_at` | Evidence time vs ingestion time; never collapse them. |
| `refresh_after` | Optional review deadline for volatile external facts. Crossing it warns; it does not delete or reject. |
| `supersedes_fact_id` | Explicit and only within same `(project,topic,fact_key)` unless an authorized migration says otherwise. |
| `evidence[]` | Required task path + anchor + Git blob/commit; measurement artifact/URL and confidence. |
| `actor/session/task`, `event_id`, `expected_topic_revision` | Audit, idempotency and CAS. |

### 6.3 Topic resolution and orphan control

`kb_promote` follows one deterministic state machine:

1. Derive project scope server-side. Read the **current topic registry** and adjacent topic summaries.
2. Resolve exact slug/alias first; lexical/semantic search may return candidates, never create/retire.
3. One candidate → load that canonical topic. Multiple → fail with candidates; do not guess. None → require
   explicit `new_topic=true`, distinct-scope reason and registry entry in the same change.
4. Require task evidence that exists in the same commit/branch. A source-less conclusion fails.
5. Match `fact_key` inside topic:
   - identical value+evidence/idempotency key → no-op;
   - different key → additive fact;
   - same key, non-overlapping valid time → historical/current sequence;
   - same key, overlapping different value → require explicit supersedes or `disputed`; otherwise fail;
   - rejected finding → retain it with reason/evidence, exclude from current mode, include in rejected mode.
6. Validator proves: topic registered; README generated/current; no unreferenced new topic; all fact refs resolve;
   no overlapping current same-key facts without dispute; source blob exists.
7. Branch-local read sees its file immediately. Shared project visibility begins only after successful merge,
   so unapproved worker findings do not leak globally.

This converts “remember to append the topic” from a prompt into one write API and one validator.

### 6.4 Merge, projection and read-after-write

Git+SQLite cannot form one physical transaction. The safe boundary is therefore content-bound:

1. Git topic/task change merges and establishes `target_head` — canonical success.
2. Under the same repo lock, projector parses only changed typed records and transactionally appends
   `knowledge_events`, folds `knowledge_facts_current` and updates FTS with `projection_head=target_head`.
3. Merge response performs a delivery check: exact `fact_id` is queryable from current projection.
4. If projector fails, **do not undo or hide the successful Git result**. Search compares heads, reports
   `projection_stale`, directly parses changed canonical topic(s) at HEAD for typed facts, and queues retry.
5. Existing embeddings/logs backfill asynchronously. Its own `indexed_head` may lag; this affects semantic
   recall, not exact/read-after-write current facts.
6. Startup/reconnect reconciles projection to repository HEAD, making out-of-band pulls/manual commits
   visible and repairable.

### 6.5 Retrieval and query construction

Keep current hybrid engine; add a typed stage before it:

1. Determine explicit mode: `current` default; `rejected` for “already tried/why not”; `as_of` for historical;
   `all/disputed` only by request. The memory pre-work can query current + rejected as two labelled facets.
2. Resolve topic aliases and exact symbols against registry/typed FTS. Apply `project_id`, status and valid-time
   filters deterministically.
3. Return claim + status/time + canonical evidence. Do not mix current and rejected as unlabeled prose.
4. Use existing file/log vector+FTS search for fuzzy history and raw evidence. No #135/#138 retuning.
5. If projection or vector index is behind HEAD, say which generation and use canonical direct fallback.
6. `cross_project` requires server-side caller permission and explicit target scopes. A model Boolean cannot
   widen the trust boundary.

## 7. Why each architecture class is not enough alone

| Class | Keep | Reject as sole design |
|---|---|---|
| Markdown+Git | Reviewability, offline operation, task evidence, history, portability. | No typed identity/current selection/freshness/orphan enforcement. |
| SQLite relational | Constraints, transactions, current/as-of query, synchronous FTS. | DB-only truth does not travel/review with repo and risks dual truth. |
| Existing FTS/vector hybrid | Fuzzy cold recall across docs/logs, local model, bounded top-k. | Derived incomplete index cannot decide current truth or promotion. |
| Graph | Optional cross-topic/global relationship projection; bitemporal vocabulary. | LLM extraction/invalidation too risky and expensive for canonical supersession. |
| Event log | Immutable audit, replay, generation/checkpoint, idempotency. | Separate event DB/infrastructure is unnecessary; an event stream alone is not a useful read model. |
| Typed statements | Status/rank, references, qualifiers and valid time. | Needs a topic registry, Git evidence and delivery/index lifecycle. |

The recommended hybrid is selected by required properties, not taste: only it has an owner for human evidence,
write enforcement, current-state semantics, immediate exact retrieval, fuzzy cold history, audit and bounded prompt.

## 8. Evaluation design and pre-registered gate

`metrics.md` defines every requested metric. The existing 18-row retrieval holdout remains immutable.
Before implementation, add a 12-scenario local fixture for update-existing, supersede, rejected, additive
near-duplicate, disputed, refresh-after, true new topic and orphan trap. No production mutation.

Safety is per-case, not only aggregate:

- retrieval 18/18; current queries have zero stale anchors;
- promotion 12/12; orphan 0/12; false supersession 0/12;
- provenance fields present and resolve to Git objects in every result;
- typed shared read-after-write reaches target HEAD in the merge operation;
- unauthorized cross-project search rejected;
- hot footprint not above current 7,872 bytes except one-line new topics;
- A/B/A/B latency/tool/token measurements reported, never used to waive correctness.

True answer utility/task success requires blank agents executing frozen tasks. No external model run was authorized
for this phase, so it is **UNMEASURED**, not approximated by R@k. Current anchor proxy is only a mechanical diagnostic.

## 9. Counter-evidence, risks and edge cases

- **The baseline is small and same-author.** 38.9% is not a population retrieval estimate. The 545-file debt,
  hashes and orphan counts are direct full-corpus counts and stronger evidence.
- **Typed `fact_key` can be wrong.** Wrong separation retains two current facts; wrong merging makes a replacement
  candidate. Direction of safe failure is retention/dispute, never silent retirement.
- **Not every contradiction is supersession.** Additive roles, multiple supported values, historical truth and
  disputed sources must coexist. Graphiti issue #1728 is the concrete counterexample.
- **TTL is not truth.** `refresh_after` only marks verification debt. Auto-expiry would turn “not recently checked”
  into “false.” Secrets/forget requests remain a separate destructive policy.
- **Git and SQLite can diverge.** HEAD watermark + direct canonical fallback + replay make it visible/recoverable;
  claiming atomic dual-write would be false.
- **Manual edits remain possible.** Merge/startup validator must parse them. A tool-only happy path without
  out-of-band reconciliation would leave a second orphan channel.
- **Registry hot footprint grows.** One line/topic and hierarchical aliases bound it; topic facts never enter hot tier.
- **Logs remain valuable.** Nine of 28 old gold items lived in logs (#138). Do not delete/split the corpus; label
  promoted conclusions and treat raw logs as evidence/history.
- **Graph may later help global questions.** Current result rejects graph as canonical update engine, not every graph
  projection. Measure global task utility before introducing it.
- **Indexing state changed during baseline.** The raw file records `pending_files=545,indexing=true` on every query.
  Phase 2 comparisons need a frozen DB snapshot or generation pin.

## 10. Confidence per finding

| Finding | Confidence | Evidence tier and reason |
|---|---|---|
| Current source-link/registry/freshness gap is real | **CONFIRMED** | Direct full-corpus counts + code path; 7/12 source-linked, 1/12 unlisted, 545 debt. Semantic promotion recall remains unmeasured. |
| Current retrieval does not reliably separate current/rejected | **CONFIRMED on holdout; scope-limited** | Direct n=18 run, stale 1/6 and current proxy 1/6; same-author/small. |
| Markdown+Git should remain canonical evidence | **LIKELY** | Current working audit/portability + Git primary docs; alternative DB-only operational risk not experimentally compared. |
| Typed SQLite events/current view is the minimum enforcement layer | **LIKELY** | SQLite guarantees + current local architecture; candidate not implemented. |
| Automatic semantic supersession is unsafe | **CONFIRMED as failure class** | Graphiti production report 3/4 false retirements + deterministic-conflict paper; exact Orchestra rate unmeasured. |
| Graph-first is wrong for Orchestra's main seam | **LIKELY** | Multiple primary counterexamples and disproportionate batch/LLM path; Orchestra graph candidate not run. |
| Recommended hybrid will improve task success | **UNCERTAIN** | Mechanism covers observed gaps, but no external-model/cold-agent candidate eval authorized. |

## 11. Affected files if a later plan is approved

No implementation is authorized. Likely surfaces for a later phase:

- canonical schema/registry under `docs/kb/` and its validator/generator;
- `app/rag.py`, `app/rag_service.py`, `app/routes/memory.py` for typed projection/generations;
- `app/mcp_stdio.py` for typed search/promote result and server-side cross-project authorization;
- merge lifecycle in `app/routes/sessions.py` for synchronous projection/delivery check;
- `pipelines/default/prompts/modules/memory-search.md` and research method for hot registry + one write path;
- focused tests plus frozen `docs/tasks/256/eval/` fixtures.

Risks: persistence migration, Git↔DB reconciliation, merge latency, manual-edit compatibility, schema/version
evolution, and wrong supersession identity. These make Phase 2 high-risk and require red behavioral oracles;
they do not authorize it now.

## 12. Sources

Evidence tiers: **T1** direct local measurement, **T2** current primary code/docs/paper. Every external URL
below was opened on 2026-08-23.

### Local T1/T2

1. [`app/rag.py`](../../../app/rag.py) — current canonical/derived schema, indexing and retrieval path (T2 code).
2. [`app/rag_service.py`](../../../app/rag_service.py) — scheduler, debt and freshness behavior (T2 code).
3. [`app/routes/memory.py`](../../../app/routes/memory.py) and [`app/mcp_stdio.py`](../../../app/mcp_stdio.py) — route/tool contract (T2 code).
4. [`pipelines/default/prompts/modules/memory-search.md`](../../../pipelines/default/prompts/modules/memory-search.md) — current cold-entry gate (T2 code/prompt).
5. [`docs/kb/README.md`](../../kb/README.md) — current knowledge contract (T2 project contract).
6. [`eval/baseline.raw.json`](./eval/baseline.raw.json) and [`eval/structure.raw.json`](./eval/structure.raw.json) — #256 direct measurements (T1).
7. [`docs/tasks/106/external-landscape.md`](../106/external-landscape.md) — prior external memory/compaction landscape (T1/T2 synthesis).
8. [`docs/tasks/110/research.md`](../110/research.md) — Ouroboros mechanics and freshness watermark (T1/T2 synthesis).
9. [`docs/tasks/133/research.md`](../133/research.md) — embedder/API comparison (T1).
10. [`docs/tasks/135/research.md`](../135/research.md), [`docs/tasks/138/research.md`](../138/research.md), [`docs/tasks/145/report.md`](../145/report.md) — rejected retrieval paths and oracle-execution evidence (T1).

### External T2 — Git/Markdown and relational

11. [Git objects](https://git-scm.com/book/en/v2/Git-Internals-Git-Objects).
12. [`git update-ref`](https://git-scm.com/docs/git-update-ref.html).
13. [`git log`](https://git-scm.com/docs/git-log.html).
14. [Letta MemFS](https://github.com/letta-ai/letta-docs-md/blob/main/concepts/memfs/index.md).
15. [Letta memory defragmentation prompt](https://github.com/letta-ai/letta-code/blob/main/src/agent/subagents/builtin/memory.md).
16. [Letta reflection/promotion prompt](https://github.com/letta-ai/letta-code/blob/main/src/agent/subagents/builtin/reflection.md).
17. [SQLite transactions](https://www.sqlite.org/lang_transaction.html).
18. [SQLite ACID](https://www.sqlite.org/transactional.html).
19. [SQLite constraints](https://www.sqlite.org/lang_createtable.html).
20. [SQLite FTS5](https://www.sqlite.org/fts5.html).

### External T2 — graph, typed facts, event log

21. [Microsoft GraphRAG repo](https://github.com/microsoft/graphrag).
22. [GraphRAG indexing overview](https://github.com/microsoft/graphrag/blob/main/docs/index/overview.md).
23. [GraphRAG dataflow](https://github.com/microsoft/graphrag/blob/main/docs/index/default_dataflow.md).
24. [GraphRAG paper](https://arxiv.org/abs/2404.16130).
25. [Graphiti MCP primary source](https://github.com/getzep/graphiti/blob/main/mcp_server/src/graphiti_mcp_server.py).
26. [Zep/Graphiti paper](https://arxiv.org/abs/2501.13956).
27. [Graphiti LongMemEval eval source](https://github.com/getzep/graphiti/blob/main/tests/evals/eval_e2e_graph_building.py).
28. [Graphiti issue #1728: collateral invalidation](https://github.com/getzep/graphiti/issues/1728).
29. [Graphiti issue #1275: O(n) resolution](https://github.com/getzep/graphiti/issues/1275).
30. [Graphiti issue #1661: lost read provenance](https://github.com/getzep/graphiti/issues/1661).
31. [Reddy & Challaram, 2026: deterministic freshness assembly](https://arxiv.org/abs/2606.01435).
32. [Wikibase data model](https://www.mediawiki.org/wiki/Wikibase/DataModel).
33. [Wikibase primer](https://www.mediawiki.org/wiki/Wikibase/DataModel/Primer).
34. [Wikidata ranking](https://www.wikidata.org/wiki/Help%3ARanking).
35. [Wikibase RDF full/truthy statements](https://www.mediawiki.org/wiki/Wikibase/Indexing/RDF_Dump_Format).
36. [KurrentDB concepts](https://docs.kurrent.io/getting-started/concepts).
37. [KurrentDB append/expected revision/idempotency](https://docs.kurrent.io/clients/python/v1.3/appending-events).
38. [KurrentDB projections](https://docs.kurrent.io/server/v26.1/features/projections/intro).
39. [KurrentDB persistent subscriptions/checkpoints](https://docs.kurrent.io/server/v25.1/features/persistent-subscriptions).

## 13. Review route inputs

- **Changed artifacts/consumers:** research/comparison/metrics/eval raw; new KB topic and README registry.
  Consumers are cold-entry agents and future planner; no runtime/code consumer changed.
- **Author model/runtime:** assigned primary Sol worker, Codex runtime (task authorization); no auxiliary Sol call.
- **AC:** exact comparison columns; all requested metrics; fresh local holdout/baseline; canonical update seam;
  current primary external sources; no reopened #133/#135/#138 solutions; research-only stop.
- **Mechanical checks:** `eval` parsers/runners, source/link/column/metric anchors, secret-form scan and Git diff/status.
- **Model route:** prose/architecture without independent correctness oracle normally wants Sol, but auxiliary Sol is
  explicitly forbidden. Per `codex-debate`, one targeted Luna completeness/falsification pass is the allowed route.

## 14. Adversarial Luna review

The only allowed Luna pass read the bounded artifacts and mechanically confirmed all 15 comparison columns
and the raw retrieval arithmetic (7/18 fact hits, 5/7 canonical matches, 1/6 stale hit). It then timed out
after substantive analysis but before delivering its formatted verdict. Per `codex-debate`, the round is spent;
no second reviewer was started. Recovered evidence is preserved in [`review-luna.md`](./review-luna.md).

Two findings were accepted and changed the report:

1. `7/12` was only exact source-path coverage, including `## Источники`; it did not prove integration of an
   atomic conclusion. All artifacts now call it source-link coverage, and semantic promotion recall is
   **UNMEASURED** until fact IDs/anchors exist.
2. `baseline.raw.json` stored source IDs, hashes and computed flags rather than self-contained retrieved bodies.
   `verify_receipts.py` independently resolved all 90 hashes in the live read-only index and recomputed all
   flags equal; `receipts.raw.json` records this. The limitation remains explicit: without committing the 610 MiB
   DB snapshot, the baseline is not permanently self-contained.

**Review status:** one Luna pass, no completed verdict because of transport timeout; 2 substantive findings
accepted and resolved. This is not reported as “approved.”
