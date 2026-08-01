Арифметика, как назло, отказалась разоблачать NO-GO. 🔬 Основной вердикт выдерживает проверку; блокирующих ошибок не найдено.

## Summary

Независимый пересчёт подтвердил:

- 8 fixture-кластеров и 24 выхода на вариант.
- Знаменатели на вариант: critical exact — 213, recent — 72, pending — 27.
- `hot_state_ledger`: 187/213 против 169/213 у current, то есть +8.4507 pp.
- Зафиксированный bootstrap воспроизводится: 20 000 resamples, CI `[-3.8095, +20.1878] pp`. Нижняя граница хуже порога `-2 pp` на 1.81 pp, поэтому зарегистрированный exact non-inferiority gate действительно не пройден.
- Gate-таблицы, judge agreement, headline-числа и HTML арифметически согласованы с `analysis.json`.
- `hot_state_atomic_tail_v2` корректно и заметно обозначен как непроверенный.
- `70.8%` и `$23.7488` арифметически верны, но требуют более узкой формулировки из-за допущений ниже.

## Findings (blocking/suggestion/question)

### [question] Сделайте момент предрегистрации проверяемым

**Comment on:** [research.md:30](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-compact-prompt/docs/tasks/106/q4/research.md:30)

Разрешённые артефакты не подтверждают, что протокол был зафиксирован до первого вызова: manifests содержат только время завершения и хешируют текущие `protocol.md`, `fixtures.json` и `candidates.py`, но не время создания lock и не scoring/analysis scripts. Они доказывают согласованность файлов к моменту завершения прогонов, а не предрегистрацию. Пока источник lock вне области проверки, точнее писать «under the documented locked protocol» либо добавить в разрешённый audit bundle подписанный lock с timestamp и всеми исполняемыми хешами.

### [question] Не называйте корпус доказанно свежим без сравнимого provenance

**Comment on:** [research.md:50](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-compact-prompt/docs/tasks/106/q4/research.md:50)

`fixtures.json` подтверждает наличие пяти dev и восьми holdout fixtures, а manifests — стабильность их хеша между прогонами. Однако ни один разрешённый артефакт не сравнивает их с исходным #106 corpus и не подтверждает, что содержание не участвовало в выборе кандидатов. Поэтому «all new relative to original», «untouched» и «second fresh corpus» остаются утверждениями автора. Это ослабляет положительные claims об external validity, хотя консервативный NO-GO не отменяет.

### [suggestion] Не засчитывайте side-effect gate без третьего условия

**Comment on:** [research.md:146](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-compact-prompt/docs/tasks/106/q4/research.md:146)

Предрегистрация требует также отсутствия ложного file-state утверждения, принятого из неизменённого состояния, но `evaluate_gates()` проверяет только `ledger_mismatches == 0` и количество unrelated changes ([analyze_results.py:317](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-compact-prompt/docs/tasks/106/q4/analyze_results.py:317)). `judge-input-inspection.json` подтверждает корректную инструкцию судьям, а не отсутствие таких утверждений в outputs. Поэтому Pass для hot-state и итог `7/8` полностью не доказаны; возможно, это `6/8`. Сам NO-GO от этого только усиливается.

### [suggestion] Приписывайте write-sprawl результат всему bundle

**Comment on:** [research.md:195](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-compact-prompt/docs/tasks/106/q4/research.md:195)

Эксперимент не изолирует targeted promotion: `hot_state_ledger` одновременно меняет generated sections, запрещает generic writes, добавляет raw tail, tool ledger и measured diff. Поэтому данные показывают, что весь hot-state bundle дал ноль unrelated change events, но не что именно narrow promotion «eliminated write sprawl». HTML повторяет более сильную причинную формулировку в [compact-prompt-q4-106.html:248](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-compact-prompt/docs/artifacts/compact-prompt-q4-106.html:248).

### [suggestion] Ограничьте область применимости secret upper bound

**Comment on:** [research.md:118](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-compact-prompt/docs/tasks/106/q4/research.md:118)

`70.8%` правильно вычислено как two-sided Clopper–Pearson upper bound для 0/3, но три наблюдения являются генерациями одного secret fixture, а не тремя независимыми secret-кластерами. Это граница условной per-generation leak rate на конкретном transcript при IID-допущении, не общая «failure-rate» или «risk» для секретов. Research содержит общий caveat, но HTML формулирует показатель шире как «границу риска».

### [suggestion] Не называйте стоимость полной actual workload после resume

**Comment on:** [research.md:240](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-compact-prompt/docs/tasks/106/q4/research.md:240)

Компоненты действительно суммируются в `$23.7488`, но `cost_mode()` сначала оставляет только последнюю запись каждого `job_id` ([analyze_results.py:101](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-compact-prompt/docs/tasks/106/q4/analyze_results.py:101)). При любом failed/partial запуске с последующим `--resume` ранее потраченная моделью стоимость исчезает, а `failures_this_invocation: 0` в manifests не исключает прошлые попытки. Корректное название текущего числа — стоимость latest retained attempts; для actual workload нужно суммировать usage всех попыток.

## Verdict

**NO-GO upheld; no blocking findings. Confidence: 0.92.**

Главный результат — провал заранее описанного two-sided 95% non-inferiority gate — воспроизводится точно. Открытые вопросы касаются доказуемости предрегистрации и freshness, а также нескольких слишком широких вспомогательных формулировок; ни одна из них не превращает `hot_state_ledger` в GO.

Итого: ворота закрыты правильно, просто часть сопроводительной бумаги надела лабораторный халат без допуска.

## Round (2026-08-01T10:54:47Z)

Five fixes landed cleanly; one “fresh” label is still doing more work than the evidence. 🧾

## Re-review status

1. **Preregistration provenance — FIXED.** Source → lock → pilot ordering is verified, and every locked source hash matches its committed blob.
2. **Corpus freshness — STILL BROKEN.** [research.md:55](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-compact-prompt/docs/tasks/106/q4/research.md:55) correctly narrows the evidence to exact ID/transcript non-overlap, but `fresh holdout` remains in prominent research and HTML claims, including [compact-prompt-q4-106.html:124](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-compact-prompt/docs/artifacts/compact-prompt-q4-106.html:124) and line 293. The audit explicitly cannot prove semantic/design independence. Use “exactly non-overlapping corpus” consistently.
3. **Omitted side-effect sub-gate — FIXED.** Conservatively failed for every candidate; hot-state is consistently reported as 6/8.
4. **Write-sprawl causality — FIXED.** Attribution now applies to the whole bundle.
5. **Secret upper-bound scope — FIXED.** Correctly limited to one transcript’s conditional per-generation rate under IID.
6. **Cost accounting — FIXED.** Raw records contain 3/96/12/8/8 unique job records with no duplicates; component costs reproduce `$23.7488251`.

## New findings

No new bugs. Python syntax and `git diff --check` passed.

## Verdict

**CHANGES REQUESTED — one wording correction remains.** The NO-GO and all numerical conclusions remain supported, but this is not yet PASS/APPROVED because the residual “fresh holdout” wording exceeds the provenance audit.

Five seals are real now; the sixth is still a sticker pretending to be chain of custody.

## Round (2026-08-01T10:56:30Z)

Да, слово `fresh` наконец перестало изображать сертификат происхождения. ✅

## Re-review status

1. Preregistration provenance — **FIXED**
2. Corpus freshness wording — **FIXED**. Research and HTML now claim only exact ID/transcript non-overlap, explicitly disclaim semantic independence, and require a verifiable boundary for v2.
3. Side-effect sub-gate — **FIXED**
4. Write-sprawl causality — **FIXED**
5. Secret upper-bound scope — **FIXED**
6. Cost accounting — **FIXED**

## New findings

None. `git diff --check` passed; no new contradiction found.

## Verdict

**PASS / APPROVED.**

The corpus claim now carries exactly the evidence it paid for—an unusual outbreak of responsible labeling.
