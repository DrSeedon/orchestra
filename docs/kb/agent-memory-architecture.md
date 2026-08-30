# Память агентов: поиск, связи и версии

## Установлено

- Общая память Orchestra должна быть единым protocol поверх project-local `docs/kb/`, а не центральным corpus: Git Markdown остаётся canonical, FTS/vector/adjacency — только rebuildable projections · `docs/tasks/417/research.md` §§5,10; решение locality `docs/tasks/412/research.md` · 2026-08-30, #417
- Top-level topic-body adjacency lower bound почти пуст: 22 topic-файла / 283 573 Б имеют 2 cross-topic Markdown-link occurrences, обе из `token-efficiency.md` в `prompt-delivery.md`; README/navigation и nested Markdown намеренно исключены · read-only Python command и raw output в `docs/tasks/417/research.md` §3.2 · 2026-08-30, #417
- Ручное `ОТОЗВАНО` сохраняет human audit, но не даёт stable fact identity, valid-time, disputed state или deterministic `as_of`; machine-versioning требует explicit `fact_key/status/supersedes/evidence`, начиная forward-only · `docs/tasks/417/research.md` §6; `app/ia/knowledge.py:499-680` · 2026-08-30, #417
- A-MEM-style automatic evolution не имеет safety proof для canonical mutation: official code меняет `tags/context` старых notes на месте, не пополняя объявленное `evolution_history`; Graphiti #1728 показывает другой causal mechanism с тем же опасным outcome — collateral retirement 3/4 hand-audited cases · [A-MEM source](https://raw.githubusercontent.com/agiresearch/A-mem/main/agentic_memory/memory_system.py); [Graphiti #1728](https://github.com/getzep/graphiti/issues/1728) · 2026-08-30, #417
- Agentic keyword search — обязательный control, а не доказанный победитель: Amazon author results дают 94.52% RAG attainment по faithfulness, 88.05% context recall и 91.48% answer correctness на их PDF corpus; marginal value на Orchestra проверяется frozen A/B · [AAAI 2026 paper](https://cdn.amazon.science/df/78/e81873f9478d80b642d113acd05e/keyword-search-is-all-you-need-2.pdf); `docs/tasks/417/research.md` §§4,9,11 · 2026-08-30, #417
- Текущие 808 МБ не являются памятью выводов: 19 773/20 502 records — raw resources, promoted facts = 0; оставить/урезать/удалить решает пользователь после 30-row A/B с exact thresholds, а при vector wins rebuild разрешён только для curated project-local corpus · вход пользователя #417 + `docs/tasks/417/research.md` §9 · 2026-08-30, #417
- Generic agent-facing `knowledge(operation,payload)` не доказал usability: mutation payload opaque и role-mismatched, но projection query не эквивалентен raw `rg` и остаётся отдельным control arm; typed promotion оправдывает узкий interface, потому что без него нужны schema/CAS/evidence/event checks · `app/mcp_stdio.py:2988-3045`; `docs/tasks/417/research.md` §§8–9 · 2026-08-30, #417

## Отвергнуто

- «A-MEM можно перенести целиком, включая auto-rewrite старых notes» · paper/code не дают immutable evolution history, а production Graphiti incident показывает тот же опасный outcome ложного retirement через другой causal mechanism · `docs/tasks/417/research.md` §§4,6 · 2026-08-30, #417
- «94.5% Amazon означает 94.5% общего качества RAG» · 94.52% относится только к relative faithfulness; context recall 88.05%, answer correctness 91.48%, corpus — шесть PDF datasets · [paper Table 1 / Results](https://cdn.amazon.science/df/78/e81873f9478d80b642d113acd05e/keyword-search-is-all-you-need-2.pdf) · 2026-08-30, #417
- «Низкий usage 808-МБ projection сам доказывает, что vector бесполезен» · usage измеряет adoption, не unique correct answers; удаление допускает только path/head-deduped 30-row local A/B с 0 vector rescues и без task wins · `docs/tasks/417/research.md` §9 · 2026-08-30, #417
- «20 502 existing records надо мигрировать в новую память» · 96.44% — raw resources, а новая fact/link form ещё не победила на ≥10 Orchestra questions · вход пользователя #417; `docs/tasks/417/research.md` §§5,11 · 2026-08-30, #417

## Пробелы

- Даёт ли vector unique task-success после canonical path/HEAD dedup · нет frozen comparison с agentic `rg`, FTS, vector и links на current corpus · 2026-08-30, #417
- Окупает ли machine `as_of` schema/authoring cost · фактов в live projection нет, 39 вызовов generic `knowledge` не измеряют спрос на version query · 2026-08-30, #417
- Улучшают ли explicit one-hop links ≥10 cross-topic вопросов без context dilution · current literal graph почти пуст, multi-hop gold не создан · 2026-08-30, #417
- Какой единый protocol одинаково выполняют Claude, Codex и Grok · внешние paper results не проверяют Orchestra runtimes · 2026-08-30, #417

## Источники

- docs/tasks/417/research.md — сравнение A-MEM/Zep/GraphRAG/keyword/Mem0/LangMem, tool gate, versioning, links, vector fate и priced branches.
