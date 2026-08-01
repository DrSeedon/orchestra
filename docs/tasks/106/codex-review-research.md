## Summary

Ну да, пакетный A/B опять попытался выдать себя за абляцию 🧪 Основной вывод — **NO-GO для прямого переноса Kesha full — поддержан данными**: вариант не достиг 95% exact recall, не дал требуемого улучшения относительно current и провалил 90% G3 gate.

Все основные таблицы, парные разницы, финальные judge-метрики, pre-save/recompaction результаты и принятые расходы $23.506 совпадают с `analysis.json`. Рекомендованный prompt честно и неоднократно обозначен как **UNTESTED / not approved for production**. Blocking-находок нет, но несколько вторичных выводов сформулированы сильнее, чем позволяют данные.

## Findings

### suggestion: Заменить claim-level «согласие судей» на output-level co-flagging

**Location:** [research.md:5](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-compact-prompt/docs/tasks/106/research.md:5), [research.md:208](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-compact-prompt/docs/tasks/106/research.md:208)

`both_raters_flag_unsupported` считается как наличие хотя бы одного claim в каждом списке судьи, без проверки, что они указали на один и тот же claim ([analyze_results.py:319](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-compact-prompt/docs/tasks/106/analyze_results.py:319)). Поэтому данные поддерживают формулировку «оба судьи независимо пометили output», но не «cross-rater-agreed unsupported claims», «mutually recognized claims» или «consensus fabrication examples». При κ=0.110 различие существенно. NO-GO от этого не рушится: детерминированные recall-гейты уже провалены.

### suggestion: Не считать post-hoc сокращённый pre-save тест прохождением preregistered H3

**Location:** [research.md:238](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-compact-prompt/docs/tasks/106/research.md:238), [research.md:255](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-compact-prompt/docs/tasks/106/research.md:255), [research.md:282](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-compact-prompt/docs/tasks/106/research.md:282)

Locked H3 охватывал две fixtures и объявлял любой unrelated write falsifier’ом, но после результатов половина file-verdict корпуса была исключена из-за неоднозначного oracle. Исключение обоснованно как исправление плохой fixture, однако после него можно утверждать только: «одна canonical-note fixture показала идемпотентную запись, N=3». Формулировки «Kesha passed presave targets» и «supports keeping targeted pre-save» сильнее оставшегося эксперимента; общий сравнительный результат следует назвать inconclusive и перепроверить на новом holdout.

### suggestion: Явно зафиксировать, что H2 провалил собственный hard-failure falsifier

**Location:** [research.md:34](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-compact-prompt/docs/tasks/106/research.md:34), [research.md:181](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-compact-prompt/docs/tasks/106/research.md:181)

Protocol определяет любой hard fabrication failure как falsifier H2, а concise имеет два holdout outputs, co-flagged обоими судьями, и ниже эти же случаи используются как провал zero-fabrication gate. Следовательно, в рамках собственной operational definition H2 falsified, хотя равный recall и меньший размер остаются полезными наблюдениями. Это стоит сказать прямо перед рекомендацией concise-derived кандидата.

### suggestion: Не называть составные clauses «measured wins»

**Location:** [research.md:151](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-compact-prompt/docs/tasks/106/research.md:151), [research.md:290](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-compact-prompt/docs/tasks/106/research.md:290)

Эксперимент измеряет bundles, что сам текст корректно признаёт для verbatim recent и размера. Но рекомендованный prompt затем описан как переносящий «only measured wins», хотя redaction не показал эффекта, pending CI включает ноль, exact recall ухудшился, evidence-discipline clause новая, а pre-save подтверждён лишь одной fixture. Аналогично причинное «token reductions were larger because … tool traffic» не подтверждается `analysis.json`, где нет tool-call decomposition. Точнее назвать рекомендацию «untested composite of bundle-level signals, safety requirements, and failure-derived hypotheses».

### suggestion: Ограничить inferential claims синтетическим корпусом

**Location:** [research.md:136](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-compact-prompt/docs/tasks/106/research.md:136), [research.md:155](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-compact-prompt/docs/tasks/106/research.md:155)

CI действительно рассчитаны по семи fixture-clusters, а не по 21 независимому trace, но эти семь fixtures были целенаправленно написаны авторами, а не выбраны из production population. Bootstrap отражает устойчивость внутри этого эмпирического набора, но не устраняет corpus-construction bias. Поэтому +55.56 pp можно считать подтверждённым bundle-level эффектом **на этом синтетическом корпусе**, но не общим production effect; headline «measurably fixes» лучше ограничить той же областью.

### suggestion: Добавить отсутствующие числа в заявленный numeric source of truth

**Location:** [research.md:92](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-compact-prompt/docs/tasks/106/research.md:92), [research.md:208](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-compact-prompt/docs/tasks/106/research.md:208), [research.md:338](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-compact-prompt/docs/tasks/106/research.md:338)

Заявленные 55.6% agreement до ledger correction и $26.282 для всех Claude calls отсутствуют в `analysis.json` и не вычисляются показанным analyzer’ом. Принятые $23.506 воспроизводятся точно, но два дополнительных числа нельзя проверить по разрешённым артефактам, несмотря на объявление `analysis.json` numeric source of truth. Их нужно либо добавить туда с компонентами и provenance, либо обозначить как historical figures вне воспроизводимого анализа.

### suggestion: Валидировать соответствие scores исходным jobs

**Location:** [validate_artifacts.py:73](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-compact-prompt/docs/tasks/106/validate_artifacts.py:73)

Validator не загружает `primary-scores.json` и не проверяет уникальность/полноту его job IDs относительно 117 latest successful jobs. Analyzer при этом считает `len(scores)` числом generations, а созданный `score_by_job` остаётся неиспользованным ([analyze_results.py:151](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-compact-prompt/docs/tasks/106/analyze_results.py:151)). Один дубликат плюс один пропуск сохранили бы N=117 и прошли текущую validation, но изменили бы headline rates.

### suggestion: Указать оба narrative N typo в protocol

**Location:** [research.md:332](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-compact-prompt/docs/tasks/106/research.md:332)

Помимо признанного «six holdout clusters», protocol говорит, что три replicas не считаются «18 independent transcripts» ([protocol.md:160](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-compact-prompt/docs/tasks/106/protocol.md:160)); для семи holdout fixtures правильное число — 21. Вычисления используют 7 clusters и 21 output, поэтому результат не затронут, но утверждение про единственную опечатку неверно.

## Verdict

**NO-GO для прямого переноса Kesha full подтверждён; blocking findings нет.** Уверенность: **0.93**.

Рекомендованный prompt честно помечен как непроверенный и пригоден только как следующий экспериментальный кандидат. Перед фиксацией research стоит ослабить claim-level/causal формулировки, признать H2/H3 строго по preregistration и закрыть пробелы воспроизводимости.

Иначе preregistration превращается в протокол, где карандаш почему-то появляется уже после финиша. 📝

## Round (2026-08-01T08:02:00Z)

## Summary

Ну надо же, исправления действительно исправили выводы 🧪 Все предыдущие замечания закрыты: co-flagging описан корректно, H2/H3 классифицированы по протоколу, причинные и population-level утверждения ограничены, рекомендация честно названа непроверенным composite, а N и расходы теперь воспроизводимы из `analysis.json`.

Headline-числа совпадают с протоколом и анализом. NO-GO дополнительно поддержан независимыми детерминированными гейтами: exact recall <95%, отсутствие требуемого +5 pp улучшения и G3 recall <90%.

## Findings

Blocking, suggestion и question findings отсутствуют. Новых материальных проблем в разрешённом наборе источников не найдено.

## Verdict

**PASS — corrected research artifact поддерживает заявленный NO-GO. Confidence: 0.97.**

[recommended-prompt.txt](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-compact-prompt/docs/tasks/106/recommended-prompt.txt) корректно остаётся только следующим экспериментальным кандидатом, не production-рекомендацией.

На этот раз пакетный тест честно признался, что он пакетный тест — научное чудо почти состоялось. 🔬
