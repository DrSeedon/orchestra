<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

Даже исследование про durable replay умудряется оставить durability на потом 😏 Документ охватывает заявленные вопросы, корректно маркирует третий прогон как незавершённый, proposals как proposals, а refutation H1 логична именно для текущего short-lived `agent()`. Нашёл 2 блокирующих пробела и 6 неблокирующих замечаний.

## Findings (blocking/suggestion/question)

### blocking: Specify a safe credential path for I1

**File:** [docs/tasks/427/research.md:239](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-dynwf/docs/tasks/427/research.md:239)

`I1` одновременно требует CLI внутри `bwrap`, empty `HOME` и отсутствия `~/.claude`, но не описывает, как subscription CLI аутентифицируется. Прямой bind credentials при shared network создаёт риск эксфильтрации; без broker или ограниченного credential handoff I1 не является исполнимым online-вариантом.

### blocking: Make accounting fail closed on parser or ledger failure

**File:** [docs/tasks/427/research.md:318](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-dynwf/docs/tasks/427/research.md:318)

Текст требует `turn_usage` для каждой попытки, но обрабатывает только процесс, умерший до terminal usage. Сам документ отдельно признаёт риск dropped ledger при parser failure. Нужно явно связать pre-dispatch WAL с `cost_unaccounted`/`OUTCOME_UNKNOWN` и запрещать следующий dispatch до reconciliation; иначе обязательный учёт остаётся намерением.

### suggestion: Reconcile the virtual-cost ceiling with the measured baseline

**File:** [docs/tasks/427/research.md:356](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-dynwf/docs/tasks/427/research.md:356)

Если `$5/$10` — потолок на workflow, он не пропускает даже полезный 9-agent run: таблица показывает `$42.73` unique API-equivalent cost при `21.56M` unique tokens, тогда как token cap этот run допускает. Уточните, что cap per-leaf, либо измените число или явно зафиксируйте, что default намеренно обрывает baseline.

### suggestion: Identify the scope and rate behind `$548`

**File:** [docs/tasks/427/research.md:152](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-dynwf/docs/tasks/427/research.md:152)

Разрешённый analyzer воспроизводит raw costs `$94.18`, `$385.34` и `$230.69`; ни один run и их сумма не дают `$548`. Если это историческое значение из карточки, нужны его run scope и price revision. Иначе `$548` следует убрать из `CONFIRMED` и из обоснования cap, а `$`-колонки переименовать в API-equivalent estimates.

### question: Prove that schema errors were recovered per agent

**File:** [docs/tasks/427/research.md:137](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-dynwf/docs/tasks/427/research.md:137)

Analyzer считает aggregate `53 calls / 43 successes / 10 errors`, но не проверяет, что каждый agent с ошибкой затем получил успешный retry. Эти числа совместимы и с 10 unrecovered agents. Нужен per-agent/order assertion; иначе формулировку следует ограничить «43 accepted results, 10 schema errors».

### suggestion: Label the 4 ms figure as a microbenchmark

**File:** [docs/tasks/427/research.md:239](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-dynwf/docs/tasks/427/research.md:239)

Измерялся пустой `true` с `--ro-bind / / --unshare-net`, а не I1 с минимальными binds, CLI, env setup и output directory. Строка I1 сейчас выглядит как end-to-end runtime estimate; её лучше обозначить как namespace-only measurement, оставив integration cost отдельной estimate.

### suggestion: Correct the median terminology

**File:** [docs/tasks/427/research.md:229](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-dynwf/docs/tasks/427/research.md:229)

`4.963 − 0.789 = 4.174 ms` — это разность медиан, не медиана пяти pairwise overheads. Медиана разностей равна `4.220 ms`; либо переименуйте показатель, либо считайте его по каждой паре.

### suggestion: Downgrade “cache stampede” to an inference

**File:** [docs/tasks/427/research.md:173](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-dynwf/docs/tasks/427/research.md:173)

Низкий first-request cache-read share доказывает слабый cross-leaf reuse, но сам по себе не доказывает concurrency stampede: это также объясняется различиями prompt/phase cache keys. `H2` refuted корректно; причинную формулировку лучше заменить на «consistent with per-call prefix creation».

## Verdict

**Verdict:** ❌ Needs revision before Phase 1 is decision-ready.

Два блокирующих пробела касаются именно обязательных свойств задачи: безопасного запуска subscription CLI и fail-closed spend accounting. Остальные проблемы не меняют основной вывод, но мешают воспроизводимости и точности формулировок.

Пока потолок `$5` выглядит как охранник, который не пускает полезный девятиагентный прогон, потому что уже увидел счёт на пятёрку.

## Round (2026-09-01T15:40:47Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Re-review status

Ну да, второй раунд починил даже арифметику — осталось только убедиться, что Git вообще видит эти файлы 😏

`git diff -- docs/tasks/427/...` пуст: оба файла имеют статус `??`, поэтому tracked patch отсутствует. Проверил текущее содержимое обоих разрешённых файлов, без чтения логов и истории.

- **FIXED — I1 credentials:** dedicated runtime home, явный риск credential exfiltration и граница I1 как accidental-write isolation; I2 вынес auth наружу ([research.md:239](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-dynwf/docs/tasks/427/research.md:239)).
- **FIXED — accounting:** `OUTCOME_UNKNOWN`, `cost_unaccounted`, quarantine, dispatch block и idempotent reconciliation описаны явно ([research.md:327](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-dynwf/docs/tasks/427/research.md:327)).
- **FIXED — $5 cap:** теперь явно обозначен Luna-first guard; Fable/Sol comparison counterfactual, Luna usage marked unknown ([research.md:360](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-dynwf/docs/tasks/427/research.md:360)).
- **FIXED — historical $548:** помечен как более ранний unreproduced snapshot и inference, а API-equivalent columns названы корректно ([research.md:152](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-dynwf/docs/tasks/427/research.md:152)).
- **FIXED — schema retry:** analyzer теперь отслеживает error→later success per agent ([analyze_workflow_logs.py:105](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-dynwf/docs/tasks/427/analyze_workflow_logs.py:105)).
- **FIXED — bwrap extrapolation:** measurement explicitly namespace-only; CLI/auth/full binds не выдаются за измеренные ([research.md:229](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-dynwf/docs/tasks/427/research.md:229)).
- **FIXED — median:** указана именно pairwise median `4.220 ms` ([research.md:229](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-dynwf/docs/tasks/427/research.md:229)).
- **FIXED — cache cause:** stampede оставлен только как совместимая гипотеза, не как доказанный механизм ([research.md:173](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-dynwf/docs/tasks/427/research.md:173)).

H1 refutation остаётся логически достаточной: warm reuse и code/task/worktree/merge cases перечислены, а hybrid DSL отдельно признан возможным, но не заменяющим underlying worker machinery. Partial third run и proposals также корректно маркированы.

## New findings

Нет новых blocking factual или logic contradictions.

## Verdict

**CLEAN — все предыдущие findings FIXED; новых блокирующих проблем нет.**

Проверяемая цитата из артефакта: “Без disjoint ownership два agents могут перезаписать друг друга до owner commit.”

Ирония судьбы: durable replay пережил раунд, а обычный `git diff` — нет.
