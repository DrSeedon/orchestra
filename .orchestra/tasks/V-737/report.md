# V-737 — force-переключение задач

После мёржа V-736 прогоны `37416223668` (коммит `6ba1141`) показали, что guard из V-736 отказывал при `force=True` и коммите вне base. Это противоречило контракту `switch_worker_branch`: force — явное разрешение отказаться от committed content, не проверенного в base. Ранний `JSONResponse(409)` срабатывал до git и до ожидаемых dict-ответов тестов; в `test_t3_switch_assignment_exception_rolls_back_branch_and_lifecycle` он также обходил ветку компенсации и оставлял asyncio subprocess transport на закрытом loop.

Теперь force не отказывает на committed-only unlanded work: switch выполняется, затем прежний run закрывается как `interrupted/task_superseded`, прежняя задача освобождается, а новая назначается через `release_previous` внутри одной SQLite-транзакции. Ошибка назначения после git switch запускает существующий rollback. Незакоммиченные файлы по-прежнему не проходят `switch_worktree_branch` даже с force, поэтому task-store не меняет binding. Тест V-620 закрепляет оба исхода.

`RuntimeError: Event loop is closed` оказался unraisable предупреждением после исключения в `tests/test_task_tracker_integration.py::test_t3_switch_assignment_exception_rolls_back_branch_and_lifecycle`: ранний force-409 возвращал response до внедрённого task-store исключения и rollback-пути; сам тест затем падал на `response["ok"]`. После восстановления force-пути тест достигает rollback, проходит отдельно и в полном union; полный прогон больше не сообщает закрытый loop.

| Проверка | Исход |
|---|---|
| `test_api.py` switch tests (восемь падений на `JSONResponse` вместо dict) | Пройдены после восстановления force-пути; существующие CAS/quarantine/rollback ответы сохранены. |
| `test_identity_drift.py::test_stale_db_is_repaired_and_merge_proceeds` | Force переключил Git, назначил новую задачу и прошёл stale identity repair. |
| `test_task_tracker_integration.py::test_t3_switch_assignment_exception_rolls_back_branch_and_lifecycle` | Исключение task-store вызывает switch назад, восстанавливает прежний lifecycle и не закрывает run. Падения больше нет; вместе с ним исчез unraisable `RuntimeError: Event loop is closed`. |
| `test_switch_after_continue_620.py::test_switch_keeps_binding_while_worker_holds_unlanded_work` | Plain и force при грязных uncommitted файлах отказывают без изменения binding; force при unmerged commit проходит, supersedes прежний run и назначает следующую задачу; `complete_previous` отказывает. |

## Приёмочная проверка

- Список построен по буквальному `rg -l "switch" tests/`: 55 путей найдено, включая `route_surface_snapshot.json`; 54 — Python. После объединения с восемью файлами V-736 и удаления дублей прогнано **59 уникальных Python-файлов**. Полный список — `test-paths.txt`.
- `/home/kesha/orchestra/.venv/bin/python -m pytest <59 paths> -q` — **1717 passed, 2 skipped, 2 warnings in 309.55s**. Оба предупреждения — `DeprecationWarning` от multiprocessing fork в двух случаях `test_merge_operations.py::test_schema_and_cross_process_arbitration_allow_one_owner`; ошибок event loop больше нет. Вывод: `all-tests.log`.
- Перед полным union: switch/T620 и `test_api.py -k switch` — 28 passed; stale identity + rollback integration — 2 passed.
- `git diff --check` — без замечаний.
- Импортированный app: `/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-dashboard/app/__init__.py`.

Orchestra не перезапускал. GitHub Actions после этого коммита не запускал; post-merge прогон на main проверит оркестратор.
