# V-705 — задачи и канон

Исходные пункты сверены с `git show 71a008fe:TODO.md` и текущим кодом. `TODO.md` не менялся. Боевые `data/` и живые хранилища не открывались на запись.

| Пункт | Исход | Доказательство |
|---|---|---|
| T069 | Исправлено | `app/manager.py:705-710` теперь разрешает явный `task_id` без исключения ролей `is_orch`; `db.publish_ready_session` атомарно связывает сессию, задачу и task_run (`app/db.py:376-425`). Регрессия `tests/test_manager.py::TestCreateSession::test_explicit_task_binding_is_role_independent`: зелёная в прогоне ниже; мутация исходного условия обратно на `task_id and not is_orch` дала `1 failed` — резолвер задачи вызван 0 раз. |
| T080 | Исправлено | При явном переключении на другую задачу `_release_previous_binding` завершает прежний task_run со статусом `interrupted` и кодом `task_superseded` до освобождения привязки (`app/tm.py:1645-1665`). `tests/test_task_runtime.py::test_switching_tasks_closes_the_bound_run_as_superseded` проверяет закрытие прежнего прогона и открытие нового; мутация кода причины обратно на `binding_released` дала `1 failed` на зафиксированном ожидаемом исходе. |
| T154 | Исправлено | При выдаче новой задачи `_finish_superseded_task_runs` закрывает открытые legacy-прогоны этой сессии, даже если квитанция ссылается на задачу, отличную от текущей строки привязки; операция входит в ту же SQL-транзакцию, до открытия нового прогона (`app/tm.py:828-850, 1757-1770`). `tests/test_task_runtime.py::test_new_assignment_supersedes_a_stale_legacy_task_run` зелёный; мутация с удалением вызова очистки дала `ValueError: open task run conflicts with current assignment provenance` (`1 failed`). |
| T111 | Дефекта уже нет | В текущем приложении нет реализации `_fire_sync` или пути, который пишет pending в `tm_sync_log`; таблица перечислена среди выведенных из эксплуатации в `app/task_migration.py:143-144`. `app/error_watch.py:233` и `tests/test_error_watch.py` содержат только имя `_fire_sync` для обнаружения повторов исторической ошибки. Нет события, которое могло бы оставить заявленную pending-запись. |
| T138 | Дефекта уже нет в текущем каноническом писателе | Текущий `TaskStore` не содержит `_ensure_expected`, `ConcurrentTaskUpdateError` или строки `canonical head changed`. Все чтения/записи сериализуются межпроцессным `flock(LOCK_EX)` в `app/task_store.py:115-131`; `update` перечитывает запись после захвата блокировки и отвергает только реально устаревший revision (`:262-277`). `TaskRuntime.operation` удерживает тот же lock, сверяет `HEAD` и обновляет проекцию (`app/task_runtime.py:25-45`). Старый описанный механизм в текущем пути отсутствует. |
| T153 | Дефекта уже нет в текущем каноническом писателе | Финализация мержа обновляет каждую задачу через API, который входит в `TaskRuntime.operation`; новая операция освежает проекцию при изменившемся `HEAD` до публикации (`app/tm.py:1080-1178`, `app/task_runtime.py:25-45`). Поэтому два task ref из одного мержа обрабатываются последовательно на актуальной ревизии канона, а не повторно используют старый expected head. В `app/` нет заявленного `ConcurrentTaskUpdateError: canonical head changed`. |
| T182 | Частично устранено; остаток требует решения владельца | Неверное разрешение тега `orchestra` уже устранено: `resolve_project_selector` проверяет тег закрытого каталога раньше локального id (`app/tm.py:320-347`), поэтому выбирает namespace каталожного проекта, а не одноимённую legacy-строку. Неизвестный scope больше не создаёт `scope:<path>` автоматически; `api_create_task` отказывает, если scope не зарегистрирован (`app/tm.py:1875-1910`). Упомянутый мёртвый `get_project_by_prefix` в текущем коде отсутствует. Но схлопнуть оставшиеся локальные строки и независимые namespaces безопасно нельзя без решений по четырём открытым вопросам в `.orchestra/tasks/V-576/namespace-map.md`: копия `/mnt/data/.../python/orchestra`, идентичность двух University namespaces, точное написание VPN-Service и добавление University scope. Там же измерено 424 конфликтующих номера на 857 из 1755 задач. Вариант сохранить namespace-разделение оставляет пересекающиеся `#N`; схлопывание требует выбрать эквивалентность namespaces и миграцию задач с коллидирующими ссылками/неизменяемой identity; выделение отдельных тегов сохраняет данные, но меняет пользовательскую модель выбора проектов. Live data/schema migration и архитектурный выбор не входят в эту работу. |

## Проверки

`/home/kesha/orchestra/.venv/bin/python -m pytest tests/test_manager.py::TestCreateSession::test_explicit_task_binding_is_role_independent tests/test_task_runtime.py::test_new_assignment_supersedes_a_stale_legacy_task_run tests/test_task_runtime.py::test_switching_tasks_closes_the_bound_run_as_superseded tests/test_task_tracker_integration.py::test_t3_continue_merge_keeps_task_bound_on_fresh_branch tests/test_project_catalog_v576.py -q` → `26 passed in 98.47s`.

Мутационные контроли выполнены после коммита регрессионных тестов: T069 `1 failed` при возврате ролевого исключения; T154 `1 failed` при пропуске legacy-run cleanup; T080 `1 failed` при замене `task_superseded` на `binding_released`. Мутации возвращены к закоммиченному коду.

Проверка тестовой изоляции: `tests/conftest.py:36-44` удаляет `ORCHESTRA_DB_PATH` и `ORCHESTRA_TASK_REPOSITORY` при импорте conftest, до импортов `app`; autouse-фикстура позже ставит tmp-пути и SQL guard (`:90-108`). Боевое значение не используется тестами.

Коммит: `27b98654` (`#V-705: bind orchestrator tasks and supersede stale runs`). Отчёт включён в отдельный коммит; после него рабочее дерево чистое.

Изменения Python требуют рестарта владельцем; рестарт не выполнялся.

## Повтор T705 merge gate: отмена при blocked Git

Повторён `tests/test_manager.py::TestAtomicSpawnLifecycle::test_cancelled_blocked_git_waits_then_removes_worktree_and_branch` трижды на каждой ревизии. Ветка V-705: `eb2e5a0ad5a6afb98c62235c778bfb102db77fec`; `main`: `5775cb11f27a615f6d0a9378a334e7724318f127`.

| Ревизия | Прогоны | Итог |
|---|---|---|
| V-705 | 1, 2, 3 | 2 passed; run 1 failed at `cleanup_entered.wait(2)`, teardown then showed `blocked_discard` timeout (`cleanup_release` remained unset). |
| main | 1, 2, 3 | 3 passed. |

Регрессия от изменения `if task_id and not is_orch` в `app/manager.py` исключается по коду пути: тест вызывает `mgr.create_session` без `task_id`, а изменение находится только в разрешении явной задачи, когда `task_id` truthy. Наблюдение согласуется с узкой timing flake веточного запуска; за три прогона на `main` она не повторилась, поэтому наличие flake на `main` этим замером не подтверждено. Сырые выводы всех шести прогонов сохранены рядом в `retest/*.log`.
