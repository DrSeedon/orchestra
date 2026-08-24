# knowledge-base-architecture

## Установлено

- Canonical evidence Orchestra должно оставаться в Git (`docs/tasks` + typed topic records), а SQLite/FTS/vector/graph быть content-bound projections: это сохраняет review/offline portability и делает `target_head/indexed_head` проверяемой границей · [`docs/tasks/256/research.md`](../tasks/256/research.md) §§5–7; [Git objects](https://git-scm.com/book/en/v2/Git-Internals-Git-Objects); [SQLite FTS5 drift contract](https://www.sqlite.org/fts5.html) · 2026-08-23, #256
- Текущий prompt-only write path не обеспечивает даже source linkage: с commit создания KB-контракта exact task-path в topic-файлах получили 7 из 12 изменённых research, 5/12 не имеют ссылки, 1 из 12 topic-файлов отсутствует в README; semantic promotion recall исторически не измерим без atomic fact IDs/anchors · `python3 docs/tasks/256/eval/audit_structure.py ...` → source-link coverage 7/12, unlisted `dashboard-quota-map.md`; [`structure.raw.json`](../tasks/256/eval/structure.raw.json) · 2026-08-23, #256
- Текущий RAG не может быть current-state oracle: из 1 092 indexable Markdown только 547 имеют current sha, долг 545 = 516 missing + 29 stale; frozen 18-query holdout дал exact/current/rejected R@5 33.3%/33.3%/50.0% и stale contradiction 1/6 · [`structure.raw.json`](../tasks/256/eval/structure.raw.json), [`baseline.raw.json`](../tasks/256/eval/baseline.raw.json), holdout sha256 `9e7c737d…9e466b` · 2026-08-23, #256
- Новая находка должна входить через deterministic topic registry + stable `fact_key`: identical → idempotent no-op; same-key conflict требует explicit `supersedes` или `disputed`; TTL только `stale-needs-validation`; rejected сохраняется отдельно от correct history. Semantic similarity может предлагать candidate, но не retire fact · [Graphiti #1728](https://github.com/getzep/graphiti/issues/1728) (3 false retirements/4 audit cases), [Wikibase ranks](https://www.wikidata.org/wiki/Help%3ARanking), [deterministic freshness paper](https://arxiv.org/abs/2606.01435) · 2026-08-23, #256
- Shared read-after-write определяется merge generation: canonical Git merge establishes `target_head`; changed typed facts synchronously project into SQLite current/FTS; vector/log backfill remains async; head mismatch triggers direct canonical fallback plus visible debt, never “not found” · [`docs/tasks/256/research.md`](../tasks/256/research.md) §6.4; current absence of generation proven by `app/rag_service.py:190-201`, `app/routes/memory.py:48-52` · 2026-08-23, #256
- Cold delivery should be three-tier: compact generated topic registry hot, typed fact summaries warm in one search, full topic/task/log evidence cold on demand; one line/topic bounds prompt footprint and removes a discovery tool call without injecting a biography · [Letta MemFS](https://github.com/letta-ai/letta-docs-md/blob/main/concepts/memfs/index.md), local footprint 2 909 + 4 963 = 7 872 bytes in [`structure.raw.json`](../tasks/256/eval/structure.raw.json) · 2026-08-23, #256

## Отвергнуто

- «Достаточно усилить Markdown prompt-контракт» · после введения контракта source-link coverage только 58.3%, topic orphan 8.3%, а current index coverage 50.1%; semantic promotion recall не измерим, enforcement должен быть write API + validator/projection · 2026-08-23, #256
- «Graph-first/LLM contradiction resolver безопасно выбирает текущее знание» · Graphiti #1728 измерил 3 collateral retirement из 4 audit cases, #1275 — O(n) resolution и silent dropped episodes, MemoryAgentBench paper — Graphiti/Zep 7% FC-SH · 2026-08-23, #256
- «Нужно снова крутить embedder/reranker/RRF/weights/pool или разводить file/log corpus» · #133 не доказал superior embedder, #135 отверг pool/RRF/weights, #138 отверг corpus split при равном budget; #256 локализует seam раньше retrieval — promotion + freshness + typed current state · 2026-08-23, #256
- «TTL означает удалить/считать ложным» · время последней проверки не является valid-time; истёкший `refresh_after` только помечает validation debt, а history/rejected сохраняются · [Wikibase historical vs deprecated semantics](https://www.wikidata.org/wiki/Help%3ARanking), 2026-08-23, #256

## Пробелы

- Candidate architecture не реализована и её effect на answer utility/task success не измерен · внешняя модель для eval не разрешена; frozen mechanical holdout и 12-scenario promotion design готовы в `docs/tasks/256/metrics.md` · 2026-08-23, #256
- Stable fact-key vocabulary и exact serialization typed records в Git не выбраны · это Phase 2 schema decision с red mutation oracles, текущая задача research-only · 2026-08-23, #256
- Semantic duplicate-topic rate не измерен: exact cross-topic duplicates дают только lower bound и не ловят paraphrase · нужен blinded manual audit или отдельно авторизованный model-assisted audit · 2026-08-23, #256
- A/B latency and real tokenizer tokens для proposed typed path отсутствуют · implementation не существует; current baseline хранит 335.6/682.8 ms и chars/3 proxy, не выдавая proxy за tokens · 2026-08-23, #256

## Источники

- docs/tasks/256/research.md — полный local/external synthesis и recommended write/update/delivery seam.
- docs/tasks/256/comparison.md — exact 15-column comparison across Git, relational, hybrid retrieval, graph, typed facts and event log.
- docs/tasks/256/metrics.md — metric contracts, frozen holdout, baseline and future promotion gate.
