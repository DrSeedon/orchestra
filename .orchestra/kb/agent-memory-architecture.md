# Память агентов: поиск, связи и версии

## Established

- Общая память Orchestra должна быть единым protocol поверх project-local `.orchestra/kb/`, а не центральным corpus: Git Markdown остаётся canonical, FTS/vector/adjacency — только rebuildable projections · `.orchestra/tasks/417/research.md` §§5,10; решение locality `.orchestra/tasks/412/research.md` · 2026-08-30, #417 — УТОЧНЕНО 2026-08-30 #419: vector projection для памяти этого корпуса отклонена и удалена; в #417 остаются только files/`rg`/approved links
- Top-level topic-body adjacency lower bound почти пуст: 22 topic-файла / 283 573 Б имеют 2 cross-topic Markdown-link occurrences, обе из `token-efficiency.md` в `prompt-delivery.md`; README/navigation и nested Markdown намеренно исключены · read-only Python command и raw output в `.orchestra/tasks/417/research.md` §3.2 · 2026-08-30, #417
- Ручное `RETRACTED` сохраняет human audit, но не даёт stable fact identity, valid-time, disputed state или deterministic `as_of`; machine-versioning требует explicit `fact_key/status/supersedes/evidence`, начиная forward-only · `.orchestra/tasks/417/research.md` §6; `app/ia/knowledge.py:499-680` · 2026-08-30, #417
- A-MEM-style automatic evolution не имеет safety proof для canonical mutation: official code меняет `tags/context` старых notes на месте, не пополняя объявленное `evolution_history`; Graphiti #1728 показывает другой causal mechanism с тем же опасным outcome — collateral retirement 3/4 hand-audited cases · [A-MEM source](https://raw.githubusercontent.com/agiresearch/A-mem/main/agentic_memory/memory_system.py); [Graphiti #1728](https://github.com/getzep/graphiti/issues/1728) · 2026-08-30, #417
- Agentic keyword search — обязательный control, а не доказанный победитель: Amazon author results дают 94.52% RAG attainment по faithfulness, 88.05% context recall и 91.48% answer correctness на их PDF corpus; marginal value на Orchestra проверяется frozen A/B · [AAAI 2026 paper](https://cdn.amazon.science/df/78/e81873f9478d80b642d113acd05e/keyword-search-is-all-you-need-2.pdf); `.orchestra/tasks/417/research.md` §§4,9,11 · 2026-08-30, #417
- Текущие 808 МБ не являются памятью выводов: 19 773/20 502 records — raw resources, promoted facts = 0; оставить/урезать/удалить решает пользователь после 30-row A/B с exact thresholds, а при vector wins rebuild разрешён только для curated project-local corpus · вход пользователя #417 + `.orchestra/tasks/417/research.md` §9 · 2026-08-30, #417 — ЗАКРЫТО 2026-08-30 #419: frozen 18+N01 A/B дал vector unique 0, принято DELETE, `current.db` удалён
- Generic agent-facing `knowledge(operation,payload)` не доказал usability: mutation payload opaque и role-mismatched, но projection query не эквивалентен raw `rg` и остаётся отдельным control arm; typed promotion оправдывает узкий interface, потому что без него нужны schema/CAS/evidence/event checks · `app/mcp_stdio.py:2988-3045`; `.orchestra/tasks/417/research.md` §§8–9 · 2026-08-30, #417 — ЗАКРЫТО ДЛЯ FILE-FIRST BRANCH 2026-08-30 #419/#417: query unique wins 0 против 6 у `rg`, typed/as-of branch отложена; Phase 2 снимает generic tool с agent surface, internal `app/ia/*` не удаляет
- Frozen #419 A/B закрыл vector gap отрицательно: на 18 holdout-вопросах vector/`knowledge(query)` имел 0 unique source-backed wins, ordinary `rg` — 6 (E04, C01, C02, C04, C06, R02), ties 0; N01 пуст на обоих arms. Решение DELETE исполнено: `current.db` 808 МБ удалён, `RAG_ENABLED=false`, а `search_memory` сохранён с actionable grep fallback · `main:.orchestra/tasks/419/report.md`; commits `3abb2fa3`, `e19b4263` · 2026-08-30, #419
- `fact:file-first-memory-protocol-live` — Общий protocol Claude/Codex/Grok теперь ищет project memory двумя literal-проходами по `.orchestra/kb`, generic `knowledge` снят только с agent-facing MCP surface, а `search_memory` сохранён как необязательный compatibility fallback · search: `memory-search.md`, `search_memory`, `knowledge`, `build_system_prompt`, «файловая память агентов» · evidence: `.orchestra/tasks/417/acceptance/test_t1_file_first_read_protocol.py` → `T1 PASS`; commits `7b035c91`, `807f879d` · 2026-08-30, #417
- `fact:forward-only-kb-validator-live` — Новые и изменённые structured facts проходят repository CLI с stable key, 1–6 literal anchors, непустым evidence и same-key replacement; canonical one-hop link дополнительно требует exact receipt из `.orchestra/tasks/<numeric-id>/plan.md`, существующий target и разрешённый relation · search: `check_kb_contract.py`, `fact:`, `search:`, `approved:`, `links:`, «одобренные связи тем» · evidence: `.orchestra/tasks/417/acceptance/test_t2_lexical_fact_contract.py` + `test_t3_approved_one_hop_links.py` → PASS; `tests/test_kb_markdown_contract.py` → `30 passed`; `.orchestra/tasks/417/review-implementation-luna.md` Round 3 → APPROVED · 2026-08-30, #417
- `fact:worker-memory-read-from-repository-checkout` — Личная память воркера читается из ГЛАВНОГО чекаута репозитория (`<repository>/.orchestra/workers/<имя>.md`), а не из его worktree: `load_worker_memory` получает `base = repository_path or scope`, и менеджер передаёт туда `repo_path`, а не ветку воркера. Отсюда следствие, невидимое по коду ветки: удаление файла из main молча обезоруживает ЖИВОГО воркера, даже если его копия цела на его же ветке · search: `load_worker_memory`, `memory_repository`, `.orchestra/workers`, `<worker-memory>`, «личная память воркера не инжектится» · evidence: `app/prompting.py:59-105`; `app/manager.py:762-772`; на диске `/mnt/data/Projects/Python/orchestra/.orchestra/workers/` 186 файлов, `memory-research.md` отсутствовал при `sessions.status='idle'` для этого воркера · 2026-09-05, #513
- `fact:agent-liveness-check-before-memory-deletion` — Проверка «агента нет в живой БД» перед удалением его памяти обязана опираться на строку `sessions` по точному имени, иначе она ошибается в опасную сторону: аудит #188 T4 (коммит `46a40bc0`, 2026-08-11) снёс 17 файлов памяти как принадлежащие несуществующим агентам, и ровно один из 17 (`memory-research`) был жив тогда и жив сейчас — 25 дней воркер работал без своей памяти · search: `46a40bc0`, `#188 T4`, `sessions.status`, `archived`, «память агентов которых нет в живой БД» · evidence: read-only `SELECT name, status, created_at FROM sessions` → `memory-research` = `idle`/`2026-08-04`, остальные 10 из того же удаления = `archived`; восстановление в `.orchestra/tasks/513/result.md` · 2026-09-05, #513
- `fact:md-chunker-crumb-and-fence-defects-dormant` — В `_chunk_markdown` два подтверждённых дефекта, оба СПЯТ за `RAG_ENABLED=false`: хлебная крошка считается и выбрасывается перевязкой имени в цикле, а `_HEADING_RE` не знает про код-фенсы и делает заголовком любой `#` внутри ```` ``` ```` · search: `_chunk_markdown`, `_HEADING_RE`, `crumb`, `RAG_ENABLED`, «хлебная крошка чанка» · evidence: `app/rag.py:181,193,202` и цикл `:183-194`; `app/rag_service.py:19`; замер по корпусу 459 файлов — 626 ложных заголовков из 8053 (7.8 %), 81 файл, у 56 ломаются границы секций, в `.orchestra/tasks/513/salvaged-145/research.md` §2 · 2026-09-05, #513

## Rejected

- «A-MEM можно перенести целиком, включая auto-rewrite старых notes» · paper/code не дают immutable evolution history, а production Graphiti incident показывает тот же опасный outcome ложного retirement через другой causal mechanism · `.orchestra/tasks/417/research.md` §§4,6 · 2026-08-30, #417
- «94.5% Amazon означает 94.5% общего качества RAG» · 94.52% относится только к relative faithfulness; context recall 88.05%, answer correctness 91.48%, corpus — шесть PDF datasets · [paper Table 1 / Results](https://cdn.amazon.science/df/78/e81873f9478d80b642d113acd05e/keyword-search-is-all-you-need-2.pdf) · 2026-08-30, #417
- «Низкий usage 808-МБ projection сам доказывает, что vector бесполезен» · usage измеряет adoption, не unique correct answers; удаление допускает только path/head-deduped 30-row local A/B с 0 vector rescues и без task wins · `.orchestra/tasks/417/research.md` §9 · 2026-08-30, #417
- «20 502 existing records надо мигрировать в новую память» · 96.44% — raw resources, а новая fact/link form ещё не победила на ≥10 Orchestra questions · вход пользователя #417; `.orchestra/tasks/417/research.md` §§5,11 · 2026-08-30, #417

## Gaps

- Даёт ли vector unique task-success после canonical path/HEAD dedup · нет frozen comparison с agentic `rg`, FTS, vector и links на current corpus · 2026-08-30, #417 — ЗАКРЫТО 2026-08-30 #419: vector unique wins 0, ordinary `rg` unique wins 6; semantic path удалён и в #417 не переоткрывается
- Окупает ли machine `as_of` schema/authoring cost · фактов в live projection нет, 39 вызовов generic `knowledge` не измеряют спрос на version query · 2026-08-30, #417
- Улучшают ли explicit one-hop links ≥10 cross-topic вопросов без context dilution · current literal graph почти пуст, multi-hop gold не создан · 2026-08-30, #417
- Сколько ещё живых воркеров остались без личной памяти после #188 T4 · 2026-09-05, #513 — ЗАКРЫТО 2026-09-05 #513: сверены все 17 имён из `46a40bc0` со строками `sessions`, живым оказался ровно один (`memory-research`, `idle`), остальные 16 — `archived`; в main сегодня нет ни одного из 17
- Какой единый protocol одинаково выполняют Claude, Codex и Grok · внешние paper results не проверяют Orchestra runtimes · 2026-08-30, #417 — ЗАКРЫТО 2026-08-30 #417: frozen T1 проверяет один assembled file-first prompt в Claude/Codex/Grok factories и resumed `SessionManager.assemble_prompt`

## Источники

- .orchestra/tasks/417/research.md — сравнение A-MEM/Zep/GraphRAG/keyword/Mem0/LangMem, tool gate, versioning, links, vector fate и priced branches.

## Toast 1 (Mixedbread), оценка 01.09.2026 — сам сервис нам не подходит, открытый harness может пригодиться

**Established (из первоисточника mixedbread.com/blog/toast-1 и репозитория mixedbread-ai/toast-harness):**
- Toast 1 — **API-only**, весов нет. Цена: $0.30/1M входных, $0.036/1M кэшированных входных
  (записи в кэш бесплатны), $0.72/1M выходных; заявленная цена запроса $0.016–0.023 при
  медианной задержке 8 с, «максимальное качество» — до $0.07.
- **Harness открыт (Apache-2.0)** и от их модели не зависит: agent loop, учёт токенов и набор
  инструментов `search_corpus`, `grep`, `get_chunks`, `read_document`, `filter_chunks`,
  `prune_context`, `submit_ranking`. Работает поверх «any OpenAI-compatible served model»;
  `MXBAI_API_KEY` нужен только их хостингу, свой клиент подставляется через
  `agent_harness.RetrievalClient`.
- Заявленный выигрыш **чисто по токенам, не по качеству**. Их же таблица Harvey LAB:
  80.6M токенов / score 55 / 21.7 ходов → 47.0M / **55** / 14.6 (только их поиск, без Toast)
  → 23.0M / **55** / 11.2 (с Toast-субагентом). Оценка качества не двигается ни в одном
  варианте, а половину экономии даёт сам поисковый бэкенд.
- Корпуса бенчмарков **не раскрыты** — воспроизвести на своих данных нельзя.

**Почему нам это скорее не нужно:**
- Наш измеренный профиль поиска: 12 722 вызова инструментов за 7 дней, из них Grep/Read/
  WebSearch — 426 (3.3%), а 8 019 — `Bash` (внутри него `rg`). Мы ищем по git-репозиторию,
  а не по корпусу документов с индексом.
- Замер #419 на нашей базе: **0 уникальных побед вектора против 6 у обычного `rg`**;
  семантический поиск выключен по решению юзера. Toast — другой механизм (агентный цикл),
  но корпус тот же, и выигрывать ему у `rg` предстоит на тех же данных.
- Их хостинг означает отправку наших внутренних задач и переписок наружу.

**Что из этого стоит внимания:** не сервис, а форма — субагент, который отдаёт основной модели
уже отобранный контекст. У нас 69% цены вызова уходит на перечитывание диалога (#345), а
разведка — 26.8% денег. Проверяемо своими руками: harness открыт, модель берётся наша (Luna),
ретривер — наш `rg`. Не сделано, не мерено, решения нет.
