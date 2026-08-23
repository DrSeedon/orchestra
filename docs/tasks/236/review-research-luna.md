<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

Ну да, зелёные механические проверки сами себя читать не умеют 😏

## Summary

Все 8 блокеров закрыты:

1. **FIXED** — `research.md:164,261-268`: Ox исключён из production free-only pool; suffix-only правило сформулировано явно. Eval-guard Ox намеренно допускает для тестовой матрицы.
2. **FIXED** — `research.md:273-281`: один Contabo-брокер, единый managed ledger и явная неизвестность внешних клиентов.
3. **FIXED** — `current-free-screening.md:3-26`, `research.md:101-106,290`: 20 маршрутов перечислены; глобальный победитель не заявлен.
4. **FIXED** — `protocol-provenance.json:2-14`: SHA, размеры, timestamps и порядок guard; хэши совпадают с frozen-копиями.
5. **FIXED** — `catalog-selection-transcript-2026-08-23.json:2-5`: 422 строки, pricing для всех строк, `selected_count=20`, source SHA-256.
6. **FIXED** — `research.md:41-58`: UTC reset прямо понижен до **LIKELY**.
7. **FIXED** — `production-call-path.txt:1-37`: цепочка wiring зафиксирована, прямой POST `/chat/completions` найден один.
8. **FIXED** — `research.md:292-301`: 23:30/23:55/23:58, reserve, порядок, leases, serial concurrency и stop conditions описаны детерминированно.

Цитата из изменённого `research.md`:

> “Evidence provenance is self-contained: `protocol-provenance.json` records the full commit SHA/time, hashes the exact frozen runner/README copies, and shows the commit preceded the first guard by 43.399 seconds.”

Проверил также соответствие 20 строк screening-таблицы выбранным строкам transcript и `git diff --check`; расхождений нет.

## Findings

### Suggestion

`docs/tasks/236/research.md:279` использует формулировку **“suffix-free eligible route”**. Она двусмысленна и буквально может означать маршрут без `:free`-суффикса, что конфликтует с suffix-only правилом выше. Лучше написать **“another exact `:free`-suffixed eligible route”**.

## Verdict

**APPROVED** — все восемь блокеров закрыты, блокирующих противоречий не найдено. Осталась только неблокирующая правка терминологии: табличка «вход только по пропуску» не должна рядом говорить, что пропуск необязателен.
