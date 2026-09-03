## Summary
The report is mostly directionally sound and conservative, but one load-bearing area is under-supported for decision use: the controlled latency evidence that drives routing defaults is not currently reproducible from the cited T1 artifacts. Treat the core routing recommendation as **provisional** until microbench reproducibility is closed.

## Findings (blocking/suggestion/question)

1. [blocking] The routing conclusion that still hangs on the “Spark is 2.32x faster than Sol and 1.17x faster than Opus” is not independently reproducible from the cited source bundle as presented.
   - In [research.md](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-spark/docs/tasks/spark-comparison/research.md:212-233), the table is presented as T1-controlled with exact medians, but the same file’s sources only point to session names and raw timestamps. The repo’s evidence trail does not include the extraction script/query logic (first-visible metric definition, turn pairing, pruning of stale turns), so the numeric claim is not self-evident.
   - Impact: this is a blocking gap because the speed edge case is the main rationale for Spark routing.

2. [blocking] The microbench task definition is a narrow static-lookup workload, yet it is used to justify worker-class routing for coding tasks (`impl-*`, `fix-*`).
   - The benchmark task is explicitly “read `backend_for_model` in `app/models.py`” ([research.md](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-spark/docs/tasks/spark-comparison/research.md:219-221)), which is not representative of coding edit risk, dependency context, or regression behavior.
   - Impact: risk of over-generalizing a very low-complexity latency result into production routing policy.

3. [question] The Opus baseline is conflated across at least two comparability frames: AA/token-speed line references a “max” profile, while the Spark/Opus microbench is effort-labeled `medium`.
   - See [research.md](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-spark/docs/tasks/spark-comparison/research.md:204-205,228-233).
   - If Opus figures are mixed between model-tier/effort settings, a hard threshold against Spark may be optimistic or pessimistic depending on which variant is actually used in-flight.

4. [suggestion] The claim “separate Spark weekly metering exists” is only “likely” but presented operationally as a planning assumption.
   - [research.md](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-spark/docs/tasks/spark-comparison/research.md:129-133,137-141) cites client UI observation + single GitHub issue; that is useful as warning-signals but not a contract.
   - Mark this as operational risk only (`not guaranteed`) in routing docs and do not encode it into SLA-like assumptions.

5. [suggestion] The “Spark for short text-only leaf tasks / Sol for repo work / Opus for orchestration/research” taxonomy is sensible, but the report does not separate “evidence threshold” from “policy threshold.”
   - The tree is explicit ([research.md](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-spark/docs/tasks/spark-comparison/research.md:315-325), proposed KPIs in [research.md](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-spark/docs/tasks/spark-comparison/research.md:329-349)), but success/fail criteria are not justified by a pre-power analysis or confidence interval for a 10-user MVP.
   - Recommend adding minimum sample size + CI or stopping rules before changing defaults.

6. [question] Several chart-derived external values are presented as “low confidence,” which is good, but they still influence the narrative near the recommendation boundary.
   - The `58.4%` / `51.5%` values come from T4 graph reads ([research.md](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-spark/docs/tasks/spark-comparison/research.md:176-183, 355-357)).
   - Without independent source snapshots, these should remain as hypothesis inputs only, not load-bearing.

7. [question] Pricing comparisons mix planes even with caveats, and that should be explicitly normalized before any routing economics decision.
   - Section 4 mixes internal virtual API-equivalent, AA provider snapshots, and Codex subscription model in one table ([research.md](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-spark/docs/tasks/spark-comparison/research.md:143-153)).
   - This is already caveated, but if used for model selection, specify in one line: “route by risk/latency, not by these dollar figures.”

## Verdict
Verdict: **Needs a blocking follow-up before default-routing changes** — the report is methodologically careful in prose, but the currently strongest decision-driving evidence (microbench latency deltas) is not yet reproducibly documented. Run a narrowly scoped, logged benchmark harness (fixed task set, fixed effort, script in-repo) and re-check the same thresholds before rollout.

## Round (2026-07-18T11:02:48Z)

## Re-review status (Round 2)
`git diff`/проверку изменений просмотрел через `git diff --no-index -- /dev/null ...` и повторный запуск `microbench.sql` против `/mnt/data/Projects/Python/orchestra/data/orchestra.db`.

| Prior finding | Status |
|---|---|
| 1) Load-bearing microbench claim had weak reproducibility basis | **FIXED** |
| 2) Benchmark task representativeness was overgeneralized as coding benchmark | **FIXED** |
| 3) Spark/Opus metric-frame conflation (AA max vs local microbench) | **FIXED** |
| 4) Quota wording treated as guaranteed post-global-weekly reserve | **FIXED** |
| 5) Chart-derived percentages treated as official tabular data | **FIXED** |
| 6) Pricing/credit/throughput claims mixed across incomparable planes | **FIXED** |
| 7) Routing thresholds/usage not clearly anchored to evidence/CI | **FIXED** |

## New findings
- **FIXED**: Никаких новых блокирующих ложных decision-grade claims не обнаружил.
- **SUGGESTION**: `microbench.sql` теперь воспроизводим и подтверждает 9 строк выборки, но для повторного запуска в других сессиях скрипт жёстко привязан к фразе `Контрольный микробенч A` и конкретным именам сессий (`spark-pilot`, `spark-bench`, `spark-official`). Это снижает portability шаблона и лучше вынести параметры в CTE-фильтры/переменные.
- **INFO**: Проверенный факт: `microbench.sql` действительно подтверждает загрязнение Sol A1 (`first_content` старый digest), и это корректно отражено в отчёте.

## Verdict
**APPROVED (Round 2).**
Нет оставшихся blocking false decision-grade claim. Смена по умолчанию в роутинге не вводится; изменения остаются в research phase, как указано.
