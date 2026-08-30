# #419 — A/B vector projection vs ordinary search

## Критерий решения (зафиксирован до чтения результатов)

- Векторный/FTS путь не дал ни одной уникальной победы (вопрос решён им и не решён обычным поиском) → **DELETE**.
- Дал уникальные победы → **KEEP-TRIM**: оставить, но перестраивать только на curated фактах `docs/kb/`, а не на 20 502 сырых записях.
- Прогон не получился или данных мало → **INCONCLUSIVE**.

Критерий не изменяется по результатам прогона.

## Методика

Использован frozen holdout #256: 18 вопросов (E01–E06, C01–C06, R01–R06) и отрицательный контроль N01. Порядок строго чередовался V→G для каждого вопроса. V — один живой вызов `knowledge(operation="query", detail="summary")`, G — один `/usr/bin/rg -n -i -F` по естественным словам вопроса в Markdown-файлах `docs/kb/` и `docs/tasks/`. Поиск идёт по текущей файловой системе без commit-снимков; попадание проверялось по одному `gold_path`, а несколько строк одного файла считаются одним текущим путём (все возвращённые строки входят в счётчик символов).

`V anchor-only` — frozen `must_contain` встретился в выдаче V, но результат не содержит рабочий `source_path` из holdout; это не победа. `V source-backed` — найден frozen anchor в результате с соответствующим рабочим `source_path`. Для G «да» означает frozen anchor в строке из соответствующего `gold_path`. Каждый arm потратил 1 вызов на вопрос; N01 также 1+1.

Сырые чередуемые ответы и команды: [`raw/final_lexical.jsonl`](./raw/final_lexical.jsonl). В JSONL сохранены request/command, полный ответ и exit code; G-команды возвращали stdout/stderr вместе с результатом запуска.

## Результаты

| ID | Вопрос | V source-backed | V anchor-only | rg | Кто уникален | Символов V | Символов rg |
|---|---|---:|---:|---:|---|---:|---:|
| E01 | Как программно проверить итоговый системный промпт конкретной роли Orchestra? | нет | да | нет | — (anchor-only не победа) | 1 500 | 5 414 |
| E02 | Какой безопасной командой искать литерал с байтовыми смещениями вместо regex с широким контекстом? | нет | нет | нет | — | 0 | 0 |
| E03 | Какое исключение поднимает `_api` и почему обработчик ошибок `search_memory` обязан ловить его явно? | нет | нет | нет | — | 900 | 0 |
| E04 | Почему `worker_wip` у отставшей ветки показывал 155 изменённых файлов и фантомные удаления? | нет | нет | да | rg | 1 500 | 1 377 |
| E05 | Где лежит канонический source pipeline skills, а где только runtime-проекция Codex skills? | нет | нет | нет | — | 1 500 | 84 |
| E06 | Сколько браузерных проверок `test_frontend` раньше молча пропускалось при включённом auth? | нет | нет | нет | — | 600 | 20 012 |
| C01 | Какая модель сейчас используется, если в `codex_review` не передать `model`? | нет | нет | да | rg | 0 | 101 604 |
| C02 | Что сейчас делает `spawn_worker` при пустом или отсутствующем `model`: берёт default роли или отказывает? | нет | нет | да | rg | 1 500 | 63 417 |
| C03 | Есть ли сейчас исполняемый quota router, который сам выбирает Luna Sol Opus при spawn? | нет | нет | нет | — | 1 500 | 553 |
| C04 | Каков подтверждённый текущий механизм browser-only `TimeoutError` при quota refresh? | нет | нет | да | rg | 0 | 455 |
| C05 | Какой суточный лимит OpenRouter free моделей действует для нашего аккаунта с lifetime purchases выше 10 долларов? | нет | нет | нет | — | 0 | 1 114 |
| C06 | Что реально исполняется как grep в сессии Claude Code на этой машине? | нет | нет | да | rg | 1 500 | 49 067 |
| R01 | Почему уже отказались переносить Orchestra embeddings с локальной bge-m3 на API? | нет | нет | нет | — | 1 500 | 9 378 |
| R02 | Почему увеличение `POOL_MULT` и глубины candidate pool уже отвергнуто для `search_memory`? | нет | нет | да | rg | 1 500 | 835 |
| R03 | Почему раздельные списки логов и файлов уже отвергнуты при равном бюджете выдачи? | нет | нет | нет | — | 1 500 | 1 002 |
| R04 | Почему runtime memory directory нельзя считать рабочим хранилищем знаний Orchestra? | нет | нет | нет | — | 1 500 | 224 |
| R05 | Почему гипотеза что memory blowup является багом самого ugrep была отвергнута? | нет | нет | нет | — | 1 500 | 0 |
| R06 | Какое устаревшее утверждение про default `codex_review` Sol уже явно отвергнуто? | нет | нет | нет | — | 1 500 | 0 |
| N01 | Какой retention policy для `quantum-ocean` архивов установлен в Orchestra? | нет | нет | нет | — | 0 | 0 |

## Счётчики

- Уникальных побед V (только source-backed): **0**.
- Уникальных побед rg: **6** (E04, C01, C02, C04, C06, R02).
- Ничьих: **0**.
- Отрицательный контроль: V = нет, rg = нет.

Результаты переданы оркестратору; этот отчёт не назначает вердикт и не содержит рекомендации.

## Review

Route: one fresh Luna pass (`gpt5.6luna`), docs/fact-extraction route. Changed files and consumers: this report plus raw evidence; consumed by the orchestrator and user. Named check: the Python consistency command used before commit (38 alternating records, source-backed/anchor-only/rg counts, N01 negative control) returned `alternation_ok=1 rows=38 V_unique=0 G_unique=6 ties=0`. AC: preserve the pre-registered criterion; keep V source-backed distinct from anchor-only; match table numbers to raw; do not issue the final verdict.

Reviewer artifact: [`codex-review-report.md`](./codex-review-report.md). One round, `approve with suggestion`; suggestion accepted by correcting C03, C06 and R06 symbol counts to match raw. Evidence quote: “Raw evidence подтверждает структуру прогона: 38 записей, пары V/G чередуются, unique counts — V: 0, rg: 6, negative control: оба `нет`.”

## Граница замера

Замер проверяет только frozen literal-anchor retrieval на 18 вопросах при одном bounded lexical `rg`-протоколе и `limit=5` для V. Он не измеряет end-to-end task success, качество формулировки ответа, latency/load, разные модели/рантаймы, multi-hop reasoning, curated-only corpus, rebuild cost или долгосрочную свежесть projection.
