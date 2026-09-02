<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

Ну хоть арифметика решила не устраивать отдельный инцидент 🧮

## Summary

Все match numerator/denominator и проценты совпадают с JSON-файлами. Блокеров нет; есть четыре non-blocking замечания по причинности и формулировкам неопределённости.

## Findings (blocking/suggestion/question)

### [question] Q1 использует unresolved ceiling как фиксированный

**File:** [research.md:9](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-credits/docs/tasks/440/research.md:9)

Все match shares рассчитаны с потолком `11,000,000`, но сам текст позже говорит, что этот потолок не восстановлен. Поэтому `916/1494` и остальные доли опровергают формулу только условно — при верности 11M. Это нужно явно указать в Q1.

### [suggestion] Не называть omitted consumers доказанными

**File:** [research.md:41](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-credits/docs/tasks/440/research.md:41)

Положительная дельта при нулевом `turn_usage` доказывает неучтённое движение относительно этой телеметрии, но не конкретно другого consumer: возможны пропуск сбора или ошибка/коррекция snapshot. Вывод «тест не диагностичен» корректен, причинное «прямо доказывает omitted consumers» — слишком сильное.

### [question] Sign argument не подтверждён агрегатными суммами

**File:** [research.md:95](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-credits/docs/tasks/440/research.md:95)

Положительные input/cache-write компоненты повышают predicted credits на интервал, но направление их влияния на output-only regression зависит от ковариации с output. В артефакте есть только агрегированные totals, а interval regression data отсутствуют, поэтому `REFUTED по направлению эффекта` следует сделать условным или заменить на `UNRESOLVED`.

### [suggestion] Разделить transport capability и фактическую live-доставку

**File:** [research.md:149](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-credits/docs/tasks/440/research.md:149)

Наличие литералов в CLI и parser support доказывает потенциальную способность пути передать событие, но при нулевых сохранённых anchor-файлах не доказывает, что событие реально дошло до SDK. Формулировки «есть на live transport seam» и «событие доходит до SDK» лучше заменить на «может быть передано»; фактическая live-доставка остаётся непроверенной.

## Verdict

**APPROVED** — блокирующих проблем нет. Числовая сверка пройдена, а замечания требуют уточнения epistemic status, не пересмотра измерений.

> “Formula-from-`turn_usage` compares part of the traffic with the total outcome.”

Пока тарифы считаются по неполному счётчику, это примерно как судить о всём ресторане по одному чеку.

## Author verification

- Blocking findings: `0`.
- Accepted non-blocking clarifications: `4/4`; `research.md` now makes the 11M condition explicit,
  labels zero-row movement as unaccounted rather than a specific consumer, changes candidate (в)
  to `UNCERTAIN`, and separates transport capability from observed live delivery.
- Completed-verdict evidence: **absent**. The purported verbatim quote above is an English
  translation; the reviewed Russian artifact did not contain it. Under `codex-debate`, the review
  round is spent but the chat/report must say `вердикта нет`, not `APPROVED`.
- No second round: the artifact changed only for non-blocking question/suggestion findings, which
  does not open a follow-up round under the canonical review rule.
