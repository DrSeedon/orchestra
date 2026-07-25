Core period and task-cost metrics can be materially inaccurate, while synchronous telemetry persistence can disrupt active turns. The capacity and frontend request handling also produce misleading snapshots under common failure or interaction scenarios.

Full review comments:

- [P1] Move telemetry writes out of the turn loop — /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-usage-analytics/app/session.py:745-745
  When SQLite is locked or a write fails, this synchronous `tool_error_add()` call blocks the event loop for up to the configured 5-second timeout and then lets the exception escape `_handle_event`, terminating an otherwise healthy model turn. The direct `turn_usage_add()` call in `TurnManager.handle_turn_end` has the same problem and can skip terminal logging, retries, and auto-reporting; both collectors should use the existing DB executor and isolate telemetry failures.

- [P1] Exclude the extra boundary day from analytics windows — /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-usage-analytics/app/usage_analytics.py:40-40
  With `days=1`, `date(l.ts) >= date('now', '-1 days')` includes both yesterday and today, while `days=7` includes eight calendar dates. Whenever the boundary date has activity, every cost, turn, task, and reliability KPI is overstated, including the UI period labelled “Сегодня”; calculate the cutoff according to the intended number of calendar days.

- [P2] Do not assign cumulative session cost to the current task — /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-usage-analytics/app/usage_analytics.py:274-279
  When a persistent system worker is switched from task A to task B, `sessions.task_id` changes but `sessions.cost_usd` remains cumulative for the session. This join therefore drops A's linkage and attributes all of A's historical cost to B, making both `linked_completed_tasks` and `cost_per_linked_task` incorrect for the documented reusable-worker workflow.

- [P2] Preserve per-provider capacity when one fetch fails — /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-usage-analytics/app/routes/system.py:818-821
  If Anthropic credentials are absent or its fetch fails without a cache, `get_usage()` returns a `JSONResponse` before attempting the independent Codex fetch, and this endpoint consequently replaces all capacity with `{}`. In that scenario valid Codex limits disappear even though the control room promises provider-level fail-soft behavior; fetch or recover each provider independently.

- [P2] Report tool-error coverage before claiming zero failures — /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-usage-analytics/app/usage_analytics.py:386-388
  Immediately after deploying the collector, or for an all-time window containing pre-collector history, this unconditional `collector_ready=True` causes an empty result to be rendered as “Ошибок в собранном окне нет.” Historical failures were never observed, so zero is not supported; persist the collector start and expose partial coverage, or keep readiness false for windows that predate it.

- [P2] Ignore stale analytics responses after period changes — /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-usage-analytics/app/static/js/analytics.js:94-96
  When a user changes periods while the previous snapshot request is still pending, both requests may complete out of order and the older response unconditionally overwrites `_analyticsPayload`. The active control can then show “30 дней” while rendering the earlier 7-day data; use an abort controller or request generation check before applying the response.

## Round 2 re-review

Reviewed the full branch diff from merge-base `8526dc1`; the uncommitted diff was empty before this review entry.

### Re-review status

- **FIXED** — telemetry writes run on the dedicated DB executor and failures do not escape turn handling.
- **FIXED** — calendar windows use `days - 1`, so `days=1` includes today only.
- **FIXED** — task attribution uses event-time `turn_usage.scope/task_id`, not cumulative session cost.
- **FIXED** — Claude and Codex capacity fetch/fallback paths are independent.
- **FIXED** — collector start and partial coverage are durable and the UI does not claim zero historical failures prematurely.
- **FIXED** — stale and post-close analytics responses are ignored by request version.
- **FIXED** — provider/model rollups prefer event-time structured turns over mutable session state.
- **FIXED** — structured-only `max_turns` auto-continue segments are included without double-counting matching logs.

### New finding

- **[P2] Do not publish partial task cost as a fully linked KPI** — `app/usage_analytics.py:321-328`
  When a task starts before the `turn_usage` collector and completes after it, one post-collector turn makes the task count as linked while `SUM(u.cost_usd)` omits all earlier work. The overview can therefore show a numeric “Цена задачи” with `1 / 1` linkage even though the price is only partial; gate exact task cost on task-lifecycle collector coverage or expose the KPI as partial/null.

### Verdict

**NOT APPROVED** — all eight previously identified defects are fixed, but the new P2 can materially understate the core cost-per-task KPI during collector rollout and for tasks spanning the collector start.

## Round 3 re-review

### Re-review status

- **FIXED** — partial task cost is no longer published as exact. Linked tasks created before `turn_usage_collector_started_at` make `task_cost_coverage_complete=false`; both cost fields become `null`, and the overview renders “частичные данные” with `точно измерено X / Y`.

### New findings

None.

### Verdict

**APPROVED** — the Round 2 P2 is closed, and the conservative `task.created_at` coverage bound introduces no material correctness regression.

## Round (2026-07-25T11:08:48Z)

Ну почти — одна цифра всё ещё слишком уверенно врёт 😏

### Re-review status

- **FIXED** — асинхронная запись telemetry.
- **FIXED** — календарные окна `days - 1`.
- **FIXED** — event-time привязка стоимости к задаче.
- **FIXED** — независимый fail-soft Claude/Codex.
- **FIXED** — честное покрытие collector.
- **FIXED** — защита от stale frontend responses.
- **FIXED** — provider/model после runtime switch.
- **FIXED** — учёт `max_turns` без двойного подсчёта.

### New finding

- **[P2] Частичная стоимость задачи публикуется как полная** — [app/usage_analytics.py:321](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-usage-analytics/app/usage_analytics.py:321)

  Если задача началась до запуска `turn_usage`, один новый turn делает её полностью `linked`, хотя ранняя стоимость отсутствует. Overview показывает числовую «Цену задачи» и покрытие `1 / 1`, материально занижая KPI.

### Verdict

**NOT APPROVED** — прежние восемь дефектов закрыты, но новый P2 оставляет core cost-per-task недостоверным при rollout collector.

Round 2 добавлен в [codex-review-impl.md:23](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-usage-analytics/docs/tasks/usage-analytics/codex-review-impl.md:23). Получился полный ценник из половины чека — арифметика смелая, но бухгалтер бы не оценил.

## Round (2026-07-25T11:16:09Z)

Ну вот, KPI наконец перестал продавать половину данных как целое 😏

### Re-review status

- **FIXED** — Round 2 P2. Если любой linked task создан до запуска collector, task-cost поля возвращаются как `null`; UI показывает «частичные данные» и покрытие `X / Y`.

### New findings

Нет.

### Verdict

**APPROVED** — напрямую вызванных P1/P2 или блокирующих регрессий не найдено. Round 3 добавлен в [codex-review-impl.md](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-usage-analytics/docs/tasks/usage-analytics/codex-review-impl.md).

Теперь неполный чек хотя бы честно называется неполным — революционная бухгалтерия.
