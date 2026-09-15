# V-575 — мерж перестал отбивать 409 на расхождении двух записей платформы

## Что было в коде (проверено до правки)

`execute_merge_session` (`app/routes/sessions.py:2054` в `ce49eeba`) сверяла
`expected_branch` операции с `row_branch` — колонкой `sessions.branch`. Обе стороны
сравнения — записи ПЛАТФОРМЫ; git в этой точке не опрашивался вовсе.

Откуда берётся `expected_branch`: при приёме операции `accept_merge_operation`
(`app/merge_operations.py:2063`) делает `_session_snapshot`, а тот берёт ветку и HEAD из
`inspect_worktree_identity`, то есть **из git**. Значит закреплённая веткой операции —
git-ветка, и отказ означал ровно одно: колонка БД отстала от git. Из этого следует
главное свойство петли — **новая операция с новым `operation_id` не помогала тоже**:
приём снова пинил git-ветку, и сравнение снова падало на той же устаревшей колонке.

Предписание `REFRESH_WORKER_THEN_NEW_OPERATION` → `worker_wip` →
`/api/sessions/{name}/wip` → `branch_wip_status` только читает git и в `sessions.branch`
ничего не пишет. Обе стороны сравнения после «починки» те же самые — отказ
воспроизводился побайтово. Живые операции (seedon, 15.09):
`f9731106-c585-4a28-80e8-f2e61e7a98ef`, `d68cd973-0673-4b29-a59a-bb6de26926bc`,
`806519aa-85c6-49ab-a494-a840ec8af9c8`.

Тот же класс дефекта уже чинился в `switch_worktree_branch` (#17,
`app/workspace.py:2365-2368`, комментарий прямо называет «мерж падал на session branch
changed»): там решили, что идемпотентный ремонт — успех, а запись идёт следом за git.
Здесь то же решение доведено до мержа.

## Что изменено

`app/routes/sessions.py` — проверка переехала ниже (после `found` и `worktree_path`) и
теперь спрашивает git:

1. `inspect_worktree_identity(worktree_path)` не удался → **отказ** 409, текст называет
   обе записи и причину невозможности опроса. Fail-closed сохранён.
2. git на закреплённой ветке И на закреплённом HEAD → `manager.persist_lifecycle`
   приводит `sessions.branch` в соответствие с git (`base_branch`/`task_id`/`needs_switch`
   переписываются своими же текущими значениями — привязка задачи не восстанавливается,
   это отдельная работа), мерж продолжается. Запись не удалось обновить → отказ.
3. Любое другое состояние (третья ветка либо разъехавшийся HEAD) → **отказ** 409, и текст
   называет все три стороны явно: что лежит в `sessions.branch`, что закрепила операция,
   что показывает git, плюс рабочий выход — `worker_wip` для осмотра и новая операция
   **без** `operation_id`, приём которой перепинит ветку и HEAD с worktree.

Git не двигается и не переименовывается: платформа чинит только СВОЮ запись.

`app/merge_operations.py`:
- `next_action` для `SESSION_IDENTITY_CHANGED` в обеих точках
  (`_classify_failure`, ветка `_verify_accepted_snapshot` в `_run_operation`) больше не
  предписывает `REFRESH_WORKER_THEN_NEW_OPERATION`. Вместо него
  `INSPECT_WORKER_THEN_NEW_OPERATION`: осмотреть `worker_wip`, затем начать операцию БЕЗ
  `operation_id`, и прямо сказано, что `worker_wip` только читает git, поэтому повтор того
  же `operation_id` помочь не может.
- `_verify_accepted_snapshot` в тексте отказа называет значения обеих сторон
  (`worker_branch (accepted 'task-42/worker', now 'other')`), а не голый список полей.

## Тесты

Добавлены в `tests/test_identity_drift.py` (файл ровно про сведение запомненной личности
воркера с живым git; стенд — настоящий репозиторий и настоящий worktree, подделка git тут
ничего не доказала бы):

- `test_stale_branch_record_is_repaired_when_git_confirms_the_pin` — разрешающее плечо:
  `sessions.branch = adhoc-20260915T101900/worker`, git на `task-17/worker` с тем самым
  HEAD → мерж проходит, коммит воркера в `main`, запись починена.
- `test_third_branch_state_is_refused_and_names_both_records` — git на `sidetrack`: отказ,
  `main` не двинулся, запись НЕ починена, в тексте есть все три стороны и `worker_wip`.
- `test_advanced_head_with_stale_record_is_refused` — ветка та, HEAD уехал: отказ, в тексте
  оба HEAD.
- `test_unreadable_worktree_with_stale_record_is_refused` — worktree не существует: отказ
  (fail-closed), в тексте обе записи.

### Команда прогона

```
/opt/orchestra/runtimes/20260817-b0b72d65-py312-rag-v2/bin/python -m pytest \
    tests/test_identity_drift.py -q -p no:randomly
→ 16 passed
```

Импортированный модуль (проверено тем же интерпретатором):
`/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-merge-identity/app/routes/sessions.py`
и `.../app/merge_operations.py`.

Полный прогон мержа — `tests/test_merge_operations.py` и все соседние
`tests/test_merge_*.py`:

```
… -m pytest tests/test_merge_operations.py tests/test_merge_branch_drift.py \
    tests/test_merge_stuck.py tests/test_merge_recovery_wedge.py tests/test_merge_ref_gate.py \
    tests/test_merge_test_gate.py tests/test_merge_target_oracle_386.py \
    tests/test_merge_conflict_report_423.py tests/test_merge_progress_424.py \
    tests/test_merge_reason_preservation_416.py tests/test_merge_completion_watch.py \
    tests/test_merge_foreign_task_ref.py -q -p no:randomly
→ 147 passed, 1 failed
```

Соседние пути приёмки и сессий:

```
… -m pytest tests/test_work_acceptance.py tests/test_acceptance.py \
    tests/test_task_tracker_integration.py tests/test_adhoc_switch.py \
    tests/test_return_to_merged_branch.py tests/test_identity_drift.py tests/test_api.py \
    -q -p no:randomly
→ 230 passed, 1 failed
```

Оба падения к V-575 отношения не имеют, оба проверены на базовом коммите `ce49eeba` в
отдельном worktree:

1. `tests/test_merge_test_gate.py::test_browser_inventory_is_explicit` — инвентарь ждёт 102
   браузерных узла в `tests/test_frontend.py`, а их 104 с коммита `6a6c9e9b` (V-564,
   13.09): два браузерных теста добавили, инвентарь не обновили.
2. `tests/test_work_acceptance.py::test_failed_acceptance_still_blocks_new_work_without_review`
   — оракул теста задан буквально как `python -c "raise SystemExit(1)"`, а `python` в этом
   окружении на PATH нет (есть только абсолютный путь рантайма), поэтому команда не
   стартует и статус выходит `inconclusive` вместо `failed`. На `ce49eeba` падает так же.

Обе строки записаны в TODO.md.

### Мутации

- Узкая (отключить только разрешающее плечо: `if actual_branch != expected_branch or ...`
  → `if True`) → краснеет **ровно один** новый тест,
  `test_stale_branch_record_is_repaired_when_git_confirms_the_pin`, остальные 15 зелёные.
- Полный возврат старого сравнения записи с записью → краснеют 4 теста: разрешающий плюс
  три отказных. Это ожидаемо и честно: отказные тесты проверяют не сам факт отказа, а
  новый контракт текста из критерия 2 (обе стороны + инструмент), которого в старом коде
  нет.

## Внешнее ревью

Не проводилось: `codex_review` отбит квотой — `weekly_quota_blocked, Codex quota is 100% —
utilization 100% is at or above the hard stop 99% for lane 'luna'`. По правилу замена
ревьюеру не ищется. Вместо него — собственные проверки выше плюс разбор ниже.

### Что проверено самостоятельно вместо ревью

- **Страж не ослаблен.** Разрешающее плечо требует ОДНОВРЕМЕННО совпадения git-ветки с
  закреплённой и git-HEAD с закреплённым. Удалённая и заново заспавненная сессия с тем же
  именем отсекается выше (проверка `row.name`/`scope` и `_verify_accepted_snapshot` по
  `session_id`), а её worktree дал бы другую пару branch@head. Чужая ветка пройти не может:
  мержится `pinned_branch = expected_branch`, то есть та самая закреплённая пара.
- **Конкурентность.** Вся правка лежит внутри `manager.get_session_lock(session_id)`
  (`app/routes/sessions.py:2036`), и `switch_worker_branch` берёт ТОТ ЖЕ лок
  (`app/routes/sessions.py:2909`) — переезд ветки и ремонт записи взаимно исключены.
  `live` читается тоже под локом, поэтому `found` авторитетен (та же причина, по которой
  `set_worker_owned_dirs` перечитывает сессию внутри лока).
- **Последующие сверки не ломаются.** Проверка live-сессии (`live.branch != row_branch`)
  стоит ВЫШЕ правки и сравнивает ещё старую согласованную пару. После ремонта обновлены
  обе стороны — `sessions.branch`, память сессии и `row`, — поэтому recheck `current_row`
  после ожидания хода сравнивается с новым `row_branch`, а `classify_head_drift` под
  lifecycle-локом по-прежнему перечитывает ветку из git.
- **Fail-closed.** В отказ ведут все три «не смог»: не опросили worktree, состояние не то,
  не смогли записать исправленную строку. Прохода без положительного подтверждения от git
  нет ни одного.

## Остаточный риск

- **Питон не работает до рестарта.** Правка лежит на диске; в живом процессе Orchestra
  она начнёт действовать только после перезапуска, который делает владелец.
- Первопричина не чинилась: `sessions.branch` по-прежнему может уехать в
  `adhoc-<ts>/<имя>` с обнулением `task_id` (отдельная работа). Мерж теперь это переживает,
  но сама потеря привязки задачи остаётся.
- Ремонт записи делается ДО ожидания хода воркера (`_wait_for_merge_idle`), то есть может
  выполниться для воркера, который в этот момент ещё работает. Пишутся только четыре
  lifecycle-колонки и те же поля в памяти сессии (`persist_lifecycle` сначала сливает
  висящие persist'ы), так что собственный persist воркера перезапишет их уже новым
  значением, а не старым. Под конкурентным `switch_worker_branch` проверка не хуже
  прежней: ветка снова перечитывается из git под lifecycle-локом (`classify_head_drift`).
- Разрешающее плечо требует ОДНОВРЕМЕННО совпадения ветки и HEAD. Воркер, дописавший
  коммит после приёма операции, при разъехавшейся записи получит отказ, хотя на здоровой
  записи такой `BENIGN_ADVANCE` мержится. Выход рабочий и назван в тексте: новая операция
  без `operation_id` перепинит новый HEAD. Сделано так намеренно — запись платформы
  правится только под полным подтверждением от git.
- Тестами покрыт ремонт ОТСОЕДИНЁННОЙ сессии (`manager._hydrate_row`); плечо загруженной
  живой сессии (`persist_lifecycle` с `_drain_persist`) не проверено тестом — поднять живой
  рантайм в тесте нечем. Код там не новый: тем же вызовом пользуются `switch_worker_branch`
  и остальные переходы lifecycle.
- Боевая БД не трогалась. 10 сессий с `branch LIKE 'adhoc-%'` и пустым `task_id`
  (7 в seedon) остаются как есть; после рестарта их мерж больше не будет запираться.
