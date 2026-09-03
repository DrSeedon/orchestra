## Summary

План представляет вертикальный text-delivery slice с конкретным AC, узким scope и реально красным committed oracle. Точный запуск:

`uv run python -m pytest -q tests/test_default_pipeline.py::TestDefaultRolesResolve::test_t1_spark_admission_rule_is_delivered_without_leaking`

дал:

`AssertionError: Spark admission rule lacks '≤2 named files'`

Сборка и импорт исправны; тест падает именно из-за отсутствующего нового правила. Арифметика `25 batches / 250 starts / 200 usage-bearing / 125 strict PASS` соответствует измеренным данным. Оценка `1.5–2.2K` корректно обозначена как sensitivity proxy, а не прямое измерение. Scope не включает pricing fix, полный suite или restart.

## Findings

suggestion: Oracle проверяет наличие строк, но не их смысловую полярность. Например, мутация `semantic prose ... are forbidden` → `semantic prose ... are encouraged` сохранит anchor `semantic prose` и пройдёт тест. Аналогично фраза `never retry Spark` может остаться внутри разрешающего retry предложения. Это не блокирует узкую доставку дословно заданного candidate block, но oracle нельзя описывать как механическое покрытие семантики всех критериев.

suggestion: Требование «no retry» сформулировано уже необходимого: `never retry Spark` действует только если oracle остаётся красным или вырос scope. Timeout, crash либо громкий pre-output отказ не покрыты и формально допускают повторный Spark-запуск. Лучше запретить любой retry после первой неуспешной попытки.

suggestion: Source trace подтверждает точный дефект: цена Spark равна `None`, `_codex_cost()` поднимает `ValueError`, а `_turn_completed()` вызывает её до создания `turn_end`. Поэтому отсутствие completion/accounting event доказано. Однако доступный фрагмент не доказывает, что уже переданный текстовый результат обязательно теряется, поэтому формулировки «runtime-доставка» и «оплаченный результат должен быть доставлен» стоит сузить до подтверждённой потери `turn_end`/учёта либо подкрепить отдельной трассировкой. Вынос исправления в отдельный ticket откалиброван правильно.

## Verdict

План готов к реализации: owner заменяется без второго Spark bullet, существующий Luna→Sol→Opus приоритет не переписывается, обязательная composite mutation и `touch` после rollback предусмотрены.

VERDICT: APPROVED — no blocking findings

## Round (2026-08-12T10:07:57Z)

## Summary

Round 2: изменения устранили все три прежних замечания. RED остаётся настоящим delivery failure из-за отсутствующего поведения, а не ошибкой collection/import. Candidate соответствует scope: одна замена owner-rule, узкий pre-spawn gate, calibrated capacity estimate; без реализации, pricing fix, полного suite или restart.

Точный тест:

`uv run python -m pytest -q tests/test_default_pipeline.py::TestDefaultRolesResolve::test_t1_spark_admission_rule_is_delivered_without_leaking`

Результат:

`AssertionError: Spark admission rule lacks 'text-only; ≤2 named files'`

## Findings

- FIXED — polarity-bearing clauses теперь ловят инверсию запретов и retry-семантики.
- FIXED — `After any failed or incomplete Spark attempt, never retry Spark` охватывает crash, timeout и pre-output failure.
- FIXED — source trace больше не преувеличен: план доказывает потерю `turn_end`/completion-accounting event и прямо оговаривает: «уже streamed text мог остаться видимым, его судьба этим source trace не установлена».
- Новых blocking или suggestion findings нет.
- Capacity корректно разделяет прямую same-mix экстраполяцию `25 / 250 / 200 / 125` и непрямой sensitivity proxy `1.5–2.2K`; долларовая оценка честно не заявлена как цена Spark.
- Composite mutation, common-layer duplication, terminal-worker non-leakage и `mv + touch` rollback закреплены в AC.

## Verdict

Round 2.

VERDICT: APPROVED — no blocking findings
