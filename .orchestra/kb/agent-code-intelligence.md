# agent-code-intelligence

## Established

- Serena 1.7.0 на frozen Orchestra-shaped корпусе дала semantic refs TP/FP/FN = 3/0/0, тогда как `rg`+stdlib AST = 3/8/0: её сильная сторона — точная идентичность известного статического символа · `.orchestra/tasks/346/evidence/raw/static-score.json` · 2026-08-25, #346
- Для production-entry edges Serena дала 1/0/7: `{}` на FastAPI/FastMCP decorators, dynamic string dispatch и на обоих `dead_root`/decorator-rooted `live_root`; HTML `onclick` не доехал при живом TypeScript positive control · `.orchestra/tasks/346/evidence/raw/static-b1-valid.json`, `static-b2-valid.json` · 2026-08-25, #346
- Serena `rename_symbol` прошла простой `pace_text` rename (2 изменения, 8 тестов), но провалила rename с monkeypatch/patch strings: 4 старых токена, 6 failed / 8 passed · `.orchestra/tasks/346/evidence/raw/direct-serena-edit-acceptance.txt` · 2026-08-25, #346
- На двух cold Python+TypeScript прогонах first positive ref был готов через 9.931/7.197 с; cgroup peak 714,182,656/772,153,344 Б, post-query 661,700,608/723,554,304 Б · `.orchestra/tasks/346/evidence/raw/serena-index-ready-summary.json`, `serena-memory-phase-summary.json` · 2026-08-25, #346
- Serena cold isolated disk = 174,421,353 apparent / 216,883,200 allocated bytes; 23 tool schemas = 29,651 Б, lazy manual = 6,508 Б · `.orchestra/tasks/346/evidence/raw/serena-install-disk.txt`, `post-run-disk.txt`, `serena-context-size.json` · 2026-08-25, #346
- External atomic Python rename не дал stale index: старый symbol исчез, новый появился сразу в обоих прогонах; этот результат ограничен Python/TypeScript и Serena 1.7.0 · `.orchestra/tasks/346/evidence/raw/static-b1-valid.json`, `static-b2-valid.json` · 2026-08-25, #346
- Нативная Luna закрыла 8 из 8 real rename outcomes без code-intelligence MCP; одинаковые задания гуляли 413,575–758,876 input tokens и 11–48 tool calls, поэтому двухточечный token delta меньше этого шума не причинный · `.orchestra/tasks/346/evidence/raw/luna-summary.json` · 2026-08-25, #346
- Лёгкий 267-line/10,967-byte MCP повторил ровно native scores и не добавил измеренной способности; глобальный custom replacement сейчас не обоснован, оставлять stdlib AST task-local · `.orchestra/tasks/346/eval/light_codeintel_mcp.py`, `.orchestra/tasks/346/evidence/raw/static-score.json` · 2026-08-25, #346
- `codex exec` 0.149.1 распарсил session `mcp_servers.*`, но не доставил tool модели: forced Luna controls вернули `SERENA_UNAVAILABLE`, MCP calls=0; B/C agent token deltas исключены как no-treatment · `.orchestra/tasks/346/evidence/raw/luna-mcp-control-b-codemode.jsonl`, `luna-summary.json` · 2026-08-25, #346

## Rejected

- «Serena `{}` после positive control означает, что production entry нет» · decorator/registry/string/HTML ground truth дал recall 0.125 при semantic recall 1.0 · 2026-08-25, #346
- «Semantic cross-file rename атомарно закрывает реальный rename целиком» · LSP не изменил patch/monkeypatch strings и docstring, механическая приёмка дала 6 падений · 2026-08-25, #346
- «Маленький MCP поверх `rg`+AST уже оправдан» · output scores совпали побайтно по метрикам, agent treatment не был доставлен · 2026-08-25, #346
- «Выгодные token deltas B/C доказывают эффект Serena/light» · во всех treatment runs MCP calls=0, forced control показал unavailable · 2026-08-25, #346

## Gaps

- Agent-level acceptance/tool/token effect Serena в настоящем managed Orchestra Codex path не измерен · Codex CLI 0.149.1 не доставил session MCP override в `exec`; нужен отдельный frozen managed-backend A/B · 2026-08-25, #346
- Результат не покрывает type hierarchy, external dependency lookup, Java/JetBrains backend и большие статически типизированные монорепо · корпус Orchestra: 3 semantic edges, 8 production edges, 2 edits · 2026-08-25, #346
- Aggregate memory при N одновременных Serena workers и warm shared-cache startup не измерены · запрещена интеграция/сервисная конфигурация, каждый прогон был cold/ephemeral · 2026-08-25, #346
- `.orchestra/kb/README.md` ещё не содержит ссылку на новую тему · файл вне owned dirs этого воркера · 2026-08-25, #346

## Источники

- `.orchestra/tasks/346/research.md` — полный Serena/native/light вердикт, corpus, ресурсы, primary/vendor counter-evidence
- `.orchestra/tasks/346/measurements.md` — точные таблицы precision/recall, edit acceptance, tokens, memory, disk, context
- `.orchestra/tasks/332/research.md` — независимый current-repo dead-code audit и реальные Serena false zeros
