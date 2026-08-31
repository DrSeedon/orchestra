<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

Ну да, «durable» — пока любой запрос без membership видит весь портфель 😏

Патч не одобряю: найдено 8 blocking-проблем в авторизации, целостности данных, идемпотентности, watchdog, MCP и TG-семантике. Проверял только `/tmp/418-backend-review.diff`; файлы репозитория и тесты не открывал.

## Findings (blocking/suggestion/question)

### blocking

1. `blocking: [P1] Закрыть список проектов авторизацией — app/routes/portfolio.py:92-94; app/portfolio.py:231-243`

   При отсутствии `x-orchestra-session-id` вызывается `list_projects("")`, выбирающий все активные проекты и пропускающий `authorize`. В ответ попадают owner, contributors, goals, tasks и waits любого проекта. Любой доступный API-клиент без project-session header получает чужие данные.

2. `blocking: [P1] Проверять роль при создании attention — app/portfolio.py:635-640`

   `create_attention()` проверяет только существование неархивированной сессии; для projectless attention `authorize()` вообще не вызывается. Активный worker может создать durable attention через `/api/portfolio/attention`, хотя контракт `notify_user` ограничивает вызов оркестраторами.

3. `blocking: [P1] Не блокировать удаление технических задач soft-link’ами — app/db.py:502-510; app/portfolio.py:353-355`

   `task_row_id` имеет FK на `tm_tasks(id)` без `ON DELETE`, а `unlink_task()` лишь заполняет `removed_at`, сохраняя строку. После любого portfolio-link удаление технической задачи будет отклоняться FK даже после unlink.

4. `blocking: [P1] Не принимать клиентское время для watchdog — app/routes/portfolio.py:36-55; app/portfolio.py:510-514; app/portfolio_watchdog.py:113-122`

   Публичный `GoalProgress.now` передаётся в `last_progress_at` и lease. Участник проекта может отправить будущее время, после чего watchdog считает goal не stalled и видит живой lease, фактически отключая watchdog до указанной даты.

5. `blocking: [P1] Сделать goal/wait операции retry-idempotent — app/portfolio.py:455-456, 480-484, 552-561, 604-610`

   Повтор `update_goal` всегда увеличивает revision, повтор progress — `stall_generation`; `open_wait` включает изменяемый generation в claim key и после чужого progress создаёт новый wait, а повтор `close_wait` после успешно закоммиченного resolve получает 404. Потерянный ответ приводит к дублированию blocker’ов или ложному сообщению об ошибке.

6. `blocking: [P1] Защитить outbox от устаревших delivery callbacks — app/portfolio_watchdog.py:139-148, 222-244`

   После истечения 300-секундного lease другой evaluator может заново забрать тот же `delivery_id`. Старый callback обновляет строку только по `goal_id`, generation и delivery ID, без claim token/state check, поэтому запоздалый failure может перевести уже `accepted` delivery обратно в `retryable`, вызывая повторные доставки.

7. `blocking: [P1] Не создавать portfolio link после ошибочного task update — app/mcp_stdio.py:2980-2997`

   Изменение удаляет прежнюю обработку `result["error"]`. Если PUT вернул error-payload, но вызов содержит явный `project`, код всё равно берёт его как `task_project` и выполняет POST link. В итоге неуспешное обновление задачи оставляет побочный portfolio-link; одновременно ломается прежний MCP-ответ `Error: ...`.

8. `blocking: [P1] Привязать durable marker к notify_user в текущем tool result — app/tg_bridge.py:149-164, 3313-3317`

   `_durable_attention_from_tool_result()` проверяет только наличие существующего event ID от той же сессии и вызывается для каждого tool result, без проверки имени `notify_user` или текущего tool call. Другой инструмент, вернувший ранее сохранённый `ATTENTION_DURABLE:<id>`, может самопроизвольно установить `_notify_reason` и отправить TG attention.

### suggestion

Нет: найденные проблемы блокируют merge.

### question

Нет: для воспроизведения перечисленных сценариев дополнительных предположений не требуется.

## Verdict

**❌ NOT APPROVED**

Нужно исправить 8 blocking-проблем. Вспомогательный Luna-review в этой сессии недоступен; Sol не запускался.

Пока это сторож, который сначала ставит «доставлено», а потом ищет дверь.

## Review process log

- Attempt 1: no reviewer output; timed out after 600 seconds during unrelated source-file exploration. No review round consumed.
- Attempt 2 / Round 1: completed on the backend changed-hunk bundle; verdict NOT APPROVED with 8 blocking findings.

## Author response before Round 2

1. Project list: the no-agent-header branch is the dashboard view. Added an explicit validated dashboard-cookie check whenever dashboard auth is enabled; agent requests with `X-Orchestra-Session-Id` remain membership-filtered. Auth-disabled mode intentionally has no API boundary anywhere, not only here.
2. Attention: projectless attention now rejects every active role except `orchestrator|sub-orchestrator`; regression covers worker 403.
3. Task link FK: changed to `ON DELETE CASCADE`; regression unlinks then deletes the technical task and proves the receipt disappears.
4. Time: all supplied timestamps now reject any future instant; past test clocks remain possible without allowing a contributor to postpone watchdog.
5. Retries: goal patch is no-op on identical state; progress persists a deterministic note claim and replays without a generation bump; open wait has a generation-independent partial-unique `open_key`; repeated close returns its committed result.
6. Watchdog: every lease acquisition gets a new `claim_token`; success/failure callbacks update only their current `delivering` token. Regression lets an expired second claim accept before the first failure returns and proves final state remains accepted.
7. MCP: restored the legacy error-payload return before link creation; regression proves one PUT and zero link POSTs on error.
8. TG: durable lookup now runs only when the current/result-resolved tool name is exactly `mcp__orchestra__notify_user`; a Bash result replaying a valid marker is rejected.

## Round (2026-08-31T08:47:51Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

Раунд 2 закрыл все восемь прежних blockers, но добавил один новый: обычный `project_goal(action="progress")` теперь ломается на пустом note 😏 Проверял только supplied diff; заявленные 124 теста самостоятельно не запускал.

## Findings (blocking/suggestion/question)

### Prior findings

1. **FIXED — authorization leak**  
   `app/routes/portfolio.py:74-84, 160-163` теперь проверяет dashboard cookie при отсутствии agent header, а agent session передаёт membership-фильтр.

2. **FIXED — attention role bypass**  
   `app/portfolio.py:710-714`: добавлена проверка `actor["role"] not in {"orchestrator", "sub-orchestrator"}`.

3. **FIXED — restrictive task FK**  
   `app/db.py:505-508`: `task_row_id` теперь использует `ON DELETE CASCADE`.

4. **FIXED — future timestamp abuse**  
   `app/portfolio.py:34-35`: будущее время отклоняется через `future timestamps are not accepted`.

5. **FIXED — goal/wait idempotency**  
   `app/portfolio.py:470-483`, `525-554`, `616-626`, `659-683`: no-op goal patch, persisted progress claim, generation-independent open key и повторное закрытие возвращают committed state.

6. **FIXED — stale watchdog callback**  
   `app/portfolio_watchdog.py:228-253`: оба callback-перехода теперь требуют совпадения `claim_token` и `state='delivering'`.

7. **FIXED — linking after task error**  
   `app/mcp_stdio.py:2984-3005`: `result["error"]` обрабатывается до portfolio-link.

8. **FIXED — false TG durable markers**  
   `app/tg_bridge.py:170-178, 3327-3332`: durable lookup выполняется только при точном совпадении текущего или resolved tool name с `mcp__orchestra__notify_user`.

### New bugs

- `blocking: [P1] Preserve the MCP default progress call — app/mcp_stdio.py:2771-2808; app/routes/portfolio.py:47-49; app/portfolio.py:525-535`

  MCP и HTTP-контракты по-прежнему задают `note: str = ""`, а `project_goal(action="progress")` отправляет `json={"note": note.strip()}`. Backend теперь безусловно отклоняет пустой note через `progress note is required`, поэтому вызов progress с дефолтными аргументами возвращает 422 вместо обновления goal.

## Verdict

**❌ NOT APPROVED**

Все прежние находки имеют статус **FIXED**. Остался один новый blocking-регресс в MCP progress compatibility. Luna-review недоступен в этой сессии; Sol не запускался.

Старые замки починили, но сторож теперь требует объяснительную даже за обычное «двигаемся дальше».

## Author response before Round 3

- Empty progress note is normalized server-side to `Progress recorded`, so the unchanged MCP/HTTP default remains valid.
- Retry detection now compares the latest same-note receipt generation with the current goal generation: the first default call advances, its immediate replay does not advance twice, and the same note becomes valid again after other progress changes the generation.
- Focused command covering frozen oracles, default progress, retry receipts, watchdog, attention and #241 fallback: `32 passed`.

## Round (2026-08-31T08:52:59Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

Раунд 3 закрыл прежний blocker, но replay lookup оставил маленькую мину под ковром 😏 Bare progress теперь работает; идемпотентность при несортированных timestamps — нет.

## Findings (blocking/suggestion/question)

### Prior blocker

- **FIXED** — `app/portfolio.py:533-553`, `app/mcp_stdio.py:2777, 2803-2808` нормализуют пустой note в `Progress recorded`, а immediate retry проверяет receipt текущего generation.

### New findings

- `blocking: [P1] Order progress receipts by generation, not client timestamp — app/portfolio.py:34-35, 544-552`

  Replay выбирает latest receipt через `ORDER BY created_at DESC`, хотя `created_at` берётся из разрешённого client-supplied `now` и может быть в прошлом или одинаковым у нескольких записей. После intervening progress новый receipt может сортироваться раньше старого; retry выберет старый generation, не сработает как replay и снова увеличит generation.

## Verdict

**❌ NOT APPROVED**

Прежний blocker **FIXED**, но найден новый blocking-дефект в том же progress/idempotency seam. Заявленные 32 теста не запускались самостоятельно; Luna недоступна, Sol не запускался.

Сторож научился принимать пустую записку, но всё ещё путает свежесть записи с датой на самой записке.

## Post-ceiling fix — not externally reviewed

**Эта правка сделана ПОСЛЕ потолка ревью и внешним ревьюером не смотрена. Она не получает
и не наследует verdict APPROVED.** Оркестратор независимо подтвердил Round-3 P1 и явно разрешил
канонический фикс без четвёртого review round.

- `app/portfolio.py`: progress receipt теперь выбирается по
  `ORDER BY stall_generation DESC,id DESC`, то есть по тому же полю, которое затем сравнивается.
- Два новых regression cases до фикса: out-of-order timestamps + equal timestamps → `2 failed`.
- Mutation обратно на `ORDER BY created_at DESC,id DESC`: `2 failed`, `MUTANT_TEST_RC=1`;
  после restore: `2 passed`, `RESTORED_TEST_RC=0`.
- Маркеры: `FIX_MARKER_BEFORE=1`, `MUTANT_MARKER_DURING=1`,
  `FIX_MARKER_AFTER=1`, `MUTANT_MARKER_AFTER=0`.
- Остальные `ORDER BY ... created_at` в `app/portfolio.py` законны: task cards, contributors и
  projects сортируются для показа человеку; решение по generation/status из этих выборок не
  принимается.
