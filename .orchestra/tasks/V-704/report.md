# V-704 — layout, bg_jobs, worktree

| Пункт | Исход | Доказательство |
|---|---|---|
| T004 | Исправлено. Исключения во всём участке после `stash push` запускают recovery по журналу до возврата ошибки; если stash OID ещё не записан, он ищется по уникальному сообщению. | `tests/test_orchestra_layout_dirty_430.py::test_t004_migration_error_after_stash_restores_dirty_files_immediately`: инъекция ошибки после stash, байты tracked и untracked файлов восстановлены в новой раскладке сразу, stash и журнал очищены. На временном git-репозитории. |
| T014 / T169 | Исправлено. Локальный `run` получает `cwd` вызывающей сессии (`worktree_path`, иначе `cwd`, иначе `scope`); удалённый host-run не менялся. | `tests/test_layout_batch_v704.py::test_t014_run_job_uses_callers_worktree_for_local_relative_paths` проверяет выбор worktree инициатора, `tests/test_bg_jobs.py::TestRunExecOutcome::test_local_run_executes_relative_paths_in_supplied_cwd` проверяет фактическое разрешение относительного пути процесса. |
| T146 | Исправлено сообщением для безопасного ручного восстановления. При сосуществовании старых и новых путей `--repair` сообщает, что автоматическое слияние небезопасно, и даёт действия вместо повторной команды `--repair`. | `tests/test_orchestra_layout_430.py::test_t146_mixed_state_repair_gives_manual_resolution_instead_of_loop`: CLI на временном репозитории завершает отказ с ручным порядком действий; содержимое обеих сторон остаётся нетронутым. |
| T147 | Дефекта уже нет. Историческая blob-сверка удалена вместе с хранилищем `.orchestra/kb/records` в коммите `fed532b2`; текущий `scripts/check_orchestra_paths.py` считает только классификацию путей и не вызывает `git cat-file`. Проверка чужих/отсутствующих исторических объектов больше не входит в контракт скрипта. | `tests/test_layout_batch_v704.py::test_t147_path_check_runs_without_historical_blob_inventory`: текущая CLI-классификация успешно проходит на отдельном Git-репозитории без архива исторических привязок. |
| T052 | Исправлено правилом для воркеров: в репозиториях с linked worktrees незавершённую работу хранить в task branch или task-local patch, не в общем stash. | `tests/test_default_pipeline.py::TestDefaultRolesResolve::test_git_workflow_module_reaches_agents_that_edit_repositories` проверяет доставку git-workflow модуля всем ролям, меняющим репозитории. |
| T075 | Исправлено `.gitignore`: добавлено исключение `.orchestra/**/__pycache__/` после повторного включения `.orchestra/**`. | `tests/test_layout_batch_v704.py::test_t075_pycache_under_orchestra_is_ignored_after_unignore_rules`: `git check-ignore -v` подтверждает правило в отдельном временном репозитории. |
| T108 | Дефекта уже нет. Скиллы Claude обновляются через `AgentSession._refresh_skills()` перед подключением backend; injector перезаписывает устаревшую незатреканную копию атомарной заменой. | `tests/test_manager.py::TestRefreshSkills::test_stale_copy_is_refreshed` проверяет замену старой копии содержимым текущего источника. |

## Проверки

Через `/home/kesha/orchestra/.venv/bin/python -m pytest` (с `nice -n 15`): focused suite по новым путям дала 7 passed; после исправления fixture отдельно `test_t147_path_check_runs_without_historical_blob_inventory` дал 1 passed. Не запускал полный набор. `git diff --check` чистый.

Мутации на закоммиченных тестах дали ожидаемый красный результат: отключение recovery сделало T004 красным (нет восстановленного файла); возврат cwd к каталогу target-session сделал T014 красным (`/target` вместо worktree); возврат self-repair команды сделал T146 красным; удаление git-workflow из modules воркера сделало тест доставки правил красным; удаление `.orchestra/**/__pycache__/` сделало T075 красным; отключение `cwd` в `_run_exec` сделало проверку фактического относительного пути красной. После каждой мутации исходный закоммиченный файл восстановлен.

## Повтор V-704: cwd fallback и flaky pidfd test

Ветка `22c7afe9` против `main` `5775cb11`; каждый прогон запускал только `tests/test_bg_jobs.py::TestPidfdProcessLifecycle::test_live_leader_and_child_are_terminated_but_unrelated_survives`:

| Исходник | Прогоны | Результат |
|---|---|---|
| V-704 | 1, 2, 3 | PASS (12.51 s), FAIL (8.34 s), PASS (15.96 s) |
| main | 1, 2, 3 | PASS (7.92 s), PASS (17.85 s), PASS (22.88 s) |

Raw выводы сохранены в `test-runs/branch-{1,2,3}.log` и `test-runs/main-{1,2,3}.log`. Единственный сбой — строка 1172: дочерний PID ещё присутствовал в `/proc` после `_kill_proc`. В этом тесте вызывается `_spawn_bg_process` напрямую; `git diff main...22c7afe9 -- app/bg_jobs.py` показывает, что изменение cwd находится только в `_run_exec` и не затрагивает тестовый путь. Три измерения не доказывают частоту сбоя на main; в данной выборке он возник только на V-704 и не связан с новой передачей cwd по проверяемому call path.

Дополнительно закрыт удалённый worktree: локальный run выбирает первый существующий каталог из `worktree_path`, `cwd`, `scope`; если ни один не существует, API возвращает 400 вместо запуска в cwd сервиса. Параметризованный тест покрывает каждого кандидата, включая отсутствующий worktree → существующий cwd. Проверка: четыре focused теста (три кандидата + фактический cwd процесса) прошли.

Мутация fallback (снята проверка существования каталога) дала ожидаемо `1 passed, 2 failed`: оба сценария с отсутствующим worktree ошибочно выбрали его вместо следующего пути. Закоммиченный код восстановлен; мутационный вывод не изменил ни source, ни frozen tests.

Миграционные и ignore-сценарии создают собственные временные Git-репозитории. Живые репозитории, их stash и `data/` не затрагивались. TODO.md не менялся.

Изменённый Python требует рестарта Orchestra владельцем.
