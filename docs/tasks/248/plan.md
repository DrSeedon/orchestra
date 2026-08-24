# #248 — План: сделать трекер частью исполнения, а не отдельным журналом

> **Owner resolution after the final review round:** the remaining first-post-Git-checkpoint
> window is closed below with a pre-Git `PREPARED` record and an exact Git operation trailer.
> Per Orchestra-orchestrator direction, no third review call is made; this revision is the Phase 2
> handoff candidate.

## Цель и граница

Цель — не заставить агентов чаще вспоминать `task_list`, а сделать так, чтобы штатная
работа через `spawn_worker` / `send_message` / `merge_worker` сама:

1. получала канонический номер из `tm_tasks`;
2. не могла провести в `main` несуществующий номер;
3. двигала `new → in_progress → done` по фактам платформы;
4. возвращала свежий task-state в уже обязательных ответах, без нового MCP-вызова.

Не входит в #248:

- исправление scope-реестра — это уже #246;
- ретроспективное переименование 132 коммитов или создание под них фиктивных задач;
- эвристическое закрытие старых задач по наличию файла/символа;
- новый универсальный workflow/новый таск-менеджер;
- рестарт или деплой живого сервиса. Смешанное окно старых MCP и нового route закрывается
  capability-протоколом ниже; принудительный реконнект не является условием безопасного мержа.

## Почему не инжектировать все открытые задачи в статический system prompt

Идея проверена по текущему пути переинжекта и отвергнута в полном виде.

- `ROLE_SYSTEM_PROMPT()` собирает строку при spawn/load. На первом сообщении после resume/compact
  `AgentSession.send()` пересобирает роль только когда `_prompt_injected == False`; следующие ходы
  получают cached prompt. Личная память — специальный блок: `refresh_worker_memory()` перечитывает
  только `docs/workers/<name>.md` и только в момент такого переинжекта
  (`app/session.py:1050-1100`, `app/prompting.py:84-99`).
- Следовательно, список задач, добавленный рядом с памятью, свеж только в момент resume/compact и
  начинает устаревать на следующем изменении трекера. Это та же уверенно устаревшая копия, против
  которой направлена задача.
- На замороженном snapshot [E1] было 97 `new|in_progress`, из них 92 в канонических scope.
  Формат `#N [status] title` занял 9 400 символов целиком: Orchestra — 5 708, Seedon — 3 439,
  kesha-tg-bot — 254. Оценка `chars/4` даёт около 2 350 токенов постоянного входного налога на
  полный список, либо около 1 427 только для Orchestra. Это оценка, не токенайзерный замер.

Вместо snapshot в промпте task-state читается в момент уже совершаемого действия:

- spawn/send/merge возвращают затронутую задачу;
- `list_agents` тем же одним MCP round-trip показывает задачи видимых воркеров, orphaned
  `in_progress` и не более пяти верхних `new`; ответ ограничен 2 000 символами и сообщает число
  скрытых строк.

Это ноль новых model→tool round-trip. Напротив, два ручных `task_update` из старого workflow
исчезают; при измеренной цене ≈$0.13 за round-trip это до $0.26 устранённого ритуала на задачу.

## Где обязателен код, а где допустима инструкция

Критерий применён отдельно к каждому отказу: что будет, если правило забыли, и что будет, если
его применили слишком широко.

| Дыра | Забыли | Применили слишком широко | Где живёт |
|---|---|---|---|
| Номер написан в сообщении без `task_create` | Работа получает выдуманный `#N`, затем коммит нельзя связать — запрещённое состояние | Автосоздание лишней строки даёт шум, но не теряет работу и откатывается cancel/delete | **Код T1**: taskless assignment сам создаёт номер; заявленный несуществующий номер не доставляется как идентичность |
| `spawn_worker(task_id=...)` указывает отсутствующую/чужую задачу | Ворк и task расходятся — запрещённое состояние | Слишком строгий scope-check отказывает до работы, то есть деградирует в безопасный отказ | **Код T1**: scoped resolve + атомарная публикация session/task |
| Коммит содержит `#N`, которого нет в трекере | Несвязанный номер навсегда попадает в `main` — запрещённое действие | Валидация всех refs может отказать валидному merge, но target остаётся неизменным | **Код T2**: preflight до commit point и повторная сверка под Git lock |
| У коммита нет номера при валидной binding | Появляется tracker row без ссылки в Git | Автопрефикс связывает commit с уже закреплённой задачей; неверная binding блокируется раньше | **Код T2**: primary task добавляется в squash subject платформой |
| Старт оставил задачу `new` | `new` с живой работой — ложное состояние | Ранний `in_progress` без опубликованного worker тоже ложь | **Код T1**: session publish + task assignment в одной SQLite-транзакции после подготовки worktree |
| Merge завершён, а task осталась `in_progress` | Готовая работа остаётся открытой | Безусловный `done` закроет research/plan gate или задачу с другими живыми воркерами — запрещённое действие | **Код T3**: schema-v2 merge несёт обязательный `continue|complete`; `complete` сериализуется task-reservation и запрещён при других live bindings. Старый v1 без outcome умеет только безопасный `continue` |
| Воркера архивировали, а task осталась активной | `in_progress` без живой работы | Сброс после удаления одного из нескольких воркеров преждевременно вернёт task в `new` | **Код T3**: archive пересчитывает остальные живые bindings; `new` только у последнего |
| Агент вручную вызывает `task_update(in_progress|done)` | Возвращается прежняя забывчивость | Массовый `done` закрывает живые задачи — запрещённое действие | **Код T3**: agent-facing task tools отвергают lifecycle status; human/YouGile override остаётся отдельным контуром |
| Трекер не читается (679 writes против 45 reads) | Агент может не заметить очередь, но кодовые инварианты не ломаются | Дополнительное чтение read-only state не меняет данные | **Код T4** доставляет свежий bounded state в существующих ответах; **инструкция T4** только объясняет, где он уже виден. Оба отказа инструкции деградируют в сегодняшнюю осведомлённость, поэтому prompt здесь допустим |
| Восемь задач в scope-less проектах | Неверная authority допускает cross-project запись | Слишком строгая нормализация отказывает до мутации | **Код #246**, не дублировать в #248 |
| Старые 20/28 фактически выполненных задач открыты | Если аудит не применить, остаётся сегодняшний stale backlog | Эвристика «есть файл → done» закроет частично сделанные задачи (#219) — запрещённое действие | Одноразовое **решение человека по content-аудиту**, уже применено Orchestra; профилактика будущих строк — T1–T3. Не prompt и не автоэвристика |

Семантический бит `continue|complete` не является вторым status-update: это часть единственной
durable merge-команды. Платформа знает commit point, refs, bindings и живых воркеров; вызывающий
сообщает только то, чего из этих фактов вывести нельзя — завершает ли этот merge весь scope задачи.
Пропущенный бит у нового schema-v2 вызова не получает default и останавливает merge до Git.
У пережившего обновление schema-v1 процесса отсутствие поля распознаётся по версии, а не
угадывается: такой вызов может только продолжить текущую задачу и не имеет пути к `done`.

## Контракт решения

### Назначение и номер

- Новый planned worker без `task_id` получает задачу из текста initial task; `_next_par()` остаётся
  единственным генератором номера.
- `task_id` в spawn — только ссылка на уже существующую scoped задачу, не способ зарезервировать
  произвольный номер.
- Parent→taskless-worker `send_message` создаёт задачу и привязывает worker до доставки. Leading
  `#999:` у отсутствующей задачи используется только как текст заголовка: server выделяет свой
  номер, удаляет ложный prefix и доставляет `[Task #<canonical>]`.
- У уже bound worker leading `#N`, отличный от binding, даёт HTTP 409 до доставки.
- Сбой после создания task, но до worker publish/switch оставляет честную `new` task и не доставляет
  работу; он не публикует taskless work как успешно начатую.
- Назначение разрешено только durable `sessions.parent_name` получателя. Проверка parent,
  отсутствие completion-reservation, запись `sessions.task_id` и `tm_tasks.worker_session_id`
  выполняются одной `BEGIN IMMEDIATE` транзакцией; произвольный sender не создаёт даже `new` row.

### Merge и refs

- Durable request включает `task_outcome=continue|complete`; значение участвует в request hash и
  replay identity.
- Route читает primary binding и candidate commit headers на pinned worker HEAD. Каждый ref
  разрешается только в project текущего scope.
- `merge_worktree_to_main()` под repo lock повторно извлекает refs из того же pinned HEAD и
  сравнивает их с preflight-набором, а после сборки проверяет и фактический squash subject.
  Неизвестный/изменившийся/подменённый ref возвращает `NOT_REACHED`; target HEAD не меняется.
- Если candidate commits не называют task, squash subject получает primary `#N` платформой.
  Несколько существующих refs в одном commit допустимы и линкуются; ни один ref не берётся «на
  веру» из текста сообщения.
- Platform-owned squash body заканчивается единственным trailer
  `Orchestra-Operation: <operation_uuid>`. Worker subjects с таким reserved key отвергаются до
  Git. Trailer добавляется отдельным message paragraph после canonical `#N:` subject и одинаково
  применяется в squash и unrelated-history fallback.

### Status ownership

- Publish/bind: task `in_progress`, `worker_session_id` и durable session identity записываются в
  одной SQLite-транзакции; прежний warning-after-publish удаляется. Любой bind проверяет
  отсутствие task reservation в этой же транзакции.
- `continue`: после merge/link worker переключается на свежую task-branch, остаётся bound, task
  остаётся `in_progress`.
- `complete`: до Git одна транзакция проверяет все неархивные `sessions.task_id`, затем вставляет
  `tm_task_reservations(task_id, operation_id, kind='complete', session_id)`. Уникальный `task_id`
  сериализует completion против spawn/send; оба binding path обязаны отказать на reservation.
  Если Git не достиг commit point, reservation снимается. После Git finalizer проверяет ту же
  reservation и одной транзакцией делает link commits + `done/completed_at` + prepayment deduction
  + release binding + session quarantine. При другом live session reservation не создаётся.
- `next_task_id` допустим только вместе с `complete`: current закрывается, next назначается
  `in_progress` одной DB-стадией после успешного Git switch. Та же preflight-транзакция резервирует
  next как `kind='assign'`, поэтому его нельзя увести во время Git.
- Архивация последнего bound worker возвращает незавершённую task в `new`; при наличии другого
  живого worker task остаётся `in_progress`, а primary binding пересчитывается.
- Post-commit DB failure делает durable operation `PARTIAL`; replay того же `operation_id`
  повторяет только незавершённую DB-стадию, никогда Git merge. Точная state machine описана ниже.

### Durable finalization state machine

`merge_operations` получает `finalization_stage NOT_REQUIRED|PREPARED|PENDING|APPLYING|APPLIED`
и `finalization_json`. После всех task/ref/reservation checks, но **до первой Git-мутации**, runner
под repo lock сохраняет `PREPARED`. Payload не выводится заново из уже изменившейся session:

```json
{
  "stage": "PREPARED",
  "outcome": "complete",
  "task": {"project_id": "project", "task_id": "<uuid>", "par_number": 42},
  "candidate_refs": ["42"],
  "operation_id": "<uuid>",
  "target_branch": "main",
  "target_before": "<sha>",
  "worker_head": "<sha>",
  "expected_tree": "<tree-sha>",
  "terminal_session": {"task_id": "", "needs_switch": true},
  "next_task": null
}
```

Для `continue` terminal state содержит прежний task id и новую task-branch; для `next_task`
payload содержит заранее валидированную immutable identity и желаемый branch. Переходы:

1. Repo-lock preparation вычисляет `target_before` и ожидаемый result tree без изменения refs,
   сохраняет `PREPARED`, затем ещё раз сверяет pinned HEAD/ref set. Для обычного squash tree даёт
   `git merge-tree --write-tree`; unrelated fallback вычисляет его через отдельный temporary index.
   Если tree нельзя получить без мутации, merge отказывает `NOT_REACHED`.
2. Git создаёт ровно один squash commit: canonical `#N:` subject остаётся первой строкой, exact
   trailer `Orchestra-Operation: <uuid>` — последним paragraph. [E2]
3. **Первая SQLite-мутация после Git** переводит durable row в
   `commit_point=REACHED + finalization_stage=PENDING` и дополняет payload `target_after` и
   `commits`. До этого checkpoint запрещены task links, payment, session lifecycle и YouGile.
4. Если именно checkpoint из шага 3 падает или процесс умирает, `PREPARED` уже содержит всё для
   reconciliation. Recovery ищет exact trailer только в first-parent диапазоне
   `target_before..target_branch`, требует ровно один commit, parent=`target_before` и
   tree=`expected_tree`. Совпадение восстанавливает `target_after/commits`, пишет
   `PARTIAL + PENDING`, `retryable=true`; этот сбой больше не становится `UNKNOWN`.
5. Нет trailer и target всё ещё `target_before` → Git не достиг commit point, reservation снимается.
   Target изменился без единственного parent/tree/trailer match → остаётся честный `UNKNOWN`:
   это внешняя/повреждённая история, не потерянный checkpoint.
6. `PARTIAL + PENDING → APPLYING` — CAS по `operation_id`, request hash и owner token. Idempotent
   finalizer проверяет task/next reservations, применяет все SQLite-изменения и пишет `APPLIED`
   в той же транзакции; `operation_id` — ключ идемпотентности.
7. После commit `APPLIED → SUCCEEDED`, затем YouGile sync планируется ровно один раз. Тот же
   operation id в `PREPARED|PENDING|APPLYING|APPLIED` **никогда** не вызывает Git повторно;
   repository trailer reconciliation выполняется раньше любого merge call.
8. Restart переводит orphan `APPLYING` с `commit_point=REACHED` обратно в `PARTIAL + PENDING`.
   Orphan `PREPARED` проходит trailer reconciliation шага 4, а не безусловный `UNKNOWN`.

### Свежий read path

- `list_agents()` делает один дополнительный server-side GET `/api/tm/tasks` внутри того же MCP
  вызова. В модель приходит: task каждого показанного worker, orphaned `in_progress`, top-5 `new`,
  truncation count; максимум 2 000 chars.
- Spawn/send/merge result содержит bounded `task`/`current_task` DTO
  (`par_number,status,title,worker_session_id`, максимум 512 chars).
- Static prompt не содержит task snapshot. `task-management.md` удаляет ручные start/done
  `task_update` и сообщает, что lifecycle автоматический, а свежие значения уже возвращаются
  spawn/send/merge/list_agents.

## Миграция и совместимость

- Идемпотентная SQLite-миграция добавляет `tm_task_reservations` с unique `task_id` и
  `operation_id`, плюс `merge_operations.finalization_stage/finalization_json`. Старые rows имеют
  `NOT_REQUIRED/{}` и читаются прежним recovery path.
- Существующие taskless ветки не получают guessed status. Перед следующим merge они должны быть
  bound через тот же server assignment path; до binding merge fail closed и не меняет target.
- Capability поднимается с `operation-v1/schema_version=1` до `task-lifecycle-v2/schema_version=2`.
  Новый MCP перед POST читает `/api/merge-operations/capabilities`, рекламирует
  `merge_schema_version=2`, включает `task_outcome` в request hash и отказывается **до POST**, если
  live server ещё v1. Новый route принимает старый request без version/outcome только как явно
  помеченный `LEGACY_MERGE_CONTINUE`: `next_task_id` запрещён, current остаётся `in_progress` и
  bound. Поэтому новая сторона против старой fail-closed, старая против новой деградирует ровно в
  сегодняшнее «не закрыл статус», но не может ложно закрыть задачу. После штатного реконнекта все
  callers получают v2; удаление legacy-ветки — отдельная telemetry-backed задача, не #248.
- Human dashboard и YouGile сохраняют явный override для исправления/cancel/payment. Запрет
  lifecycle mutation относится к agent-facing `task_create/task_update`, а не к человеку.

## Риски и предохранители

- **Ошибочное `complete`.** Другие live bindings и concurrent bind закрыты одной task-reservation;
  отсутствие/неизвестное значение v2 блокируется. Неизвлекаемый смысл «это последняя фаза»
  остаётся явным intent merge.
- **TOCTOU между preflight и Git.** Worker session/lifecycle locks + pinned HEAD; repo-lock повторно
  сравнивает refs с validated set.
- **Git committed, первый checkpoint недоступен.** Pre-Git `PREPARED` + exact trailer +
  parent/tree check восстанавливают `PENDING`; same-id replay завершает DB stage без повторного Git.
- **Автосоздание шумной task на короткое сообщение.** Оно ограничено parent→его taskless worker.
  Лишняя task — видимый и обратимый шум; незатреканная persistent work — необратимая потеря связи.
- **Большой read payload.** Проектный scope, top-5 `new`, обязательный truncation count и 2 000-char
  hard cap; полный список остаётся в explicit `task_list`.
- **Оплата/YouGile.** Platform completion вызывает те же `auto_deduct_prepayment()` и sync callback,
  что ручной `api_update_task(status="done")`; нельзя получить два разных status path.

## Tickets

### T1 — Канонический номер и binding в spawn/send
- Files: `app/tm.py` (`create/bind` transaction helper + reservation check), `app/db.py`
  (`tm_task_reservations` migration; publish ready session with binding),
  `app/manager.py` (`_create_session_locked`),
  `app/routes/sessions.py` (`CreateSessionRequest`, `SendRequest`, assignment before delivery),
  `app/mcp_stdio.py` (`spawn_worker` task DTO).
- Test: `uv run python -m pytest -q tests/test_task_tracker_integration.py -k 'test_t1_'`
  — committed RED in `b7ad6c76`.
- RED: `AssertionError: planned work must receive an auto-allocated task number`;
  `assert task_state.get("auto_created") is True`; non-parent and conflicting leading number
  return success instead of HTTP 403/409.
- AC: named command is green; `_next_par()` is the only number allocator; initial task is not
  delivered before durable binding; spawn CAS failure leaves no published worker; taskless
  parent assignment atomically writes both `sessions.task_id` and `tm_tasks.worker_session_id`,
  returns canonical DTO and never delivers the made-up prefix; non-parent creates no row; switch
  failure leaves exactly an unbound `new` task and no delivery; active task reservation rejects
  bind; bound mismatch returns 409; no additional MCP round-trip.
- blocked-by: none

### T2 — Pre-commit task-ref gate and canonical squash header
- Files: `app/workspace.py` (candidate ref inspection + repo-lock revalidation + canonical subject),
  `app/routes/sessions.py` (`execute_merge_session` preflight), `app/tm.py` (bulk scoped identity
  resolution), `app/merge_operations.py`, `app/routes/merge_operations.py`, `app/mcp_stdio.py`
  (`task_outcome` carried in request/capability hash).
- Test: `uv run python -m pytest -q tests/test_task_tracker_integration.py -k 'test_t2_'`
  — committed RED in `b7ad6c76`.
- RED: `a missing bound task must stop before the Git commit point` but Git is called;
  real repo assertion gets `target_committed` instead of `not_reached` for `#999`.
- AC: named command is green; missing binding/task/outcome and any unresolved candidate ref return
  typed `NOT_REACHED`; real target HEAD is byte-identical after refusal; empty ref set receives the
  bound primary `#N`; all existing additional refs link within the scoped project; candidate refs
  and emitted squash subject are rechecked under repo lock against the exact pinned HEAD; a
  task that exists only in another project is unresolved; worker-provided
  `Orchestra-Operation:` is rejected as a reserved trailer key.
- blocked-by: T1

### T3 — Platform-owned lifecycle on durable merge and archive
- Files: `app/tm.py` (transactional merge finalizer + live-binding recomputation + prepayment/sync),
  `app/db.py` (finalization columns + reservation/session/task transaction),
  `app/routes/sessions.py` (continue/complete/next/archive),
  `app/manager.py` (`remove`), `app/workspace.py` (operation trailer + expected tree),
  `app/merge_operations.py` (`PREPARED`, trailer reconciliation, PARTIAL finalize replay),
  `app/routes/merge_operations.py` (capability v2), `app/mcp_stdio.py` (capability preflight,
  required v2 outcome; reject manual lifecycle).
- Test: `uv run python -m pytest -q tests/test_task_tracker_integration.py -k 'test_t3_'`
  — committed RED in `b7ad6c76`.
- RED: completed task remains `in_progress`; continue loses `sessions.task_id`; removing the last
  worker leaves `in_progress`; agent `task_update(...done)` does not raise
  `lifecycle_platform_owned`; the injected first post-Git mutation hits `UPDATE TM_TASKS` instead
  of the durable merge checkpoint.
- AC: named command is green; `complete` reservation blocks an existing and a concurrent second
  binding; `continue` preserves binding on a fresh task branch and rejects `next_task_id`;
  current-complete/next-in-progress commits as one DB stage; archive requeues only the last worker
  and otherwise elects the remaining binding; manual agent lifecycle mutations are rejected before
  HTTP; failed post-commit finalizer exposes the exact `PENDING` payload above, same-id replay makes
  it `APPLIED` with one Git call; new MCP refuses v1 server before POST, old MCP on v2 can only
  `LEGACY_MERGE_CONTINUE`; `uv run python -m pytest -q tests/test_tm.py::test_status_prepayment_uses_resolved_task_db_id tests/test_tm_sync_loop.py`
  stays green, and the platform finalizer calls the same deduction/sync owner exactly once. The
  checkpoint-loss RED proves: first post-Git DML is an `UPDATE merge_operations` containing
  `commit_point` and `finalization_stage`; its injected failure yields `PARTIAL/PENDING`; exact
  trailer + parent + expected tree recover the same operation; second and third same-id calls keep
  one Git call and one target commit.
- blocked-by: T2

### T4 — Свежий bounded task-state в существующих ответах
- Files: `app/tm.py`, `app/routes/tm.py` (open project slice), `app/mcp_stdio.py`
  (`list_agents` + bounded DTO formatting), `pipelines/default/prompts/modules/task-management.md`
  (remove manual ritual; describe automatic state). The frozen tests and shared test helpers are
  not implementation files.
- Test: `uv run python -m pytest -q tests/test_task_tracker_integration.py -k 'test_t4_'`
  — committed RED in `b7ad6c76`.
- RED: `#7 [in_progress] First title` is absent from `list_agents`; assembled orchestrator/full-cycle
  prompts still contain `Starting work → task_update` and `Successful merge → task_update`.
- AC: named command is green; consecutive `list_agents` calls reflect changed DB title without
  cached prompt state; worker-bound + orphaned active tasks are present, `new` is capped at five,
  total output ≤2 000 chars with omitted count; orchestrator/full-cycle receive the automatic
  lifecycle anchor and worker role does not; no static task snapshot and no new model→tool call.
- blocked-by: T1, T3

## Frozen RED proof

`b7ad6c76` is the immutable oracle commit for all four tickets.

`d8cf99f8` (`22 failed in 16.67s`) and `b4558c64` (`23 failed in 32.64s`) are **superseded and
exploratory forever**. They must not be used as acceptance baselines or folded into a future
comparison: the first lacked checkpoint-loss coverage; the second overconstrained the public
finalization projection to an exact dictionary and could not carry the new recovery identity.

```text
$ uv run python -m pytest -q tests/test_task_tracker_integration.py
FFFFFFFFFFFFFFFFFFFFFFF                                                  [100%]
E       AssertionError: planned work must receive an auto-allocated task number
23 failed in 27.49s
```

## Evidence

- [E1] `docs/tasks/248/evidence/snapshot-aggregates.txt` — backed-up live SQLite snapshot and
  canonical/open status aggregates used for the prompt-size calculation.
- [E2] `docs/tasks/248/trailer-experiment.txt` — fresh Git probe: canonical task subject and one
  exact `Orchestra-Operation` trailer coexist; `git interpret-trailers --parse` returns the trailer.
