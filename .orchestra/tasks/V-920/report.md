# V-920 — cleanup осиротевших dynamic_workflow worktree

## Причина

`WorkflowEngine._run_attempt` удаляет worktree только в `finally` (`scripts/wf_run.py:1232-1243`); `_cleanup_workspace_sync` сначала архивирует изменения, сбрасывает worktree и удаляет его (`scripts/wf_run.py:547-565`). Остановка процесса до выхода из coroutine обходит этот путь.

Журнал Orchestra подтверждает остановку и новый запуск 15.10.2026: в `journalctl` — `09:59:21 Polling stopped`, `09:59:28 Finished server process [241177]`, `09:59:31 Started server process [851291]`; в `10:00:42` новый процесс записал `Restart notice injected: urok-svyaz`. В `data/workflow-runs/V-19-3e4abd6c290e/journal.jsonl:6888,6901,6912` — последние `dispatched` для call keys, встроенных в имена трёх worktree; для них нет завершающих событий. Каталоги созданы в 09:59:05–09:59:09, а `.run.lock` к проверке уже отсутствовал.

Повторная уборка на старте в `10:00:37` записала для каждого из трёх путей `stale worktree skipped (dirty)`. `git status --short` на каждом показал только `?? .wf-mcp.json`. Причина — рестарт процесса во время трёх workflow вызовов; остатки сохранились, потому что обычная уборка пропускает dirty worktree (`app/workspace.py:3142-3148`). Гипотеза о рестарте подтверждается последовательностью остановки, нового PID и restart notice; отдельного сообщения systemd о причине остановки в доступном журнале нет.

## Исправление

`cleanup_stale_worktrees` теперь отдельно обрабатывает `wf-*`: сопоставляет run-id с каталогом в `data/workflow-runs`, удерживает `.run.lock` на время удаления и оставляет активный или неопознанный workflow нетронутым (`app/workspace.py:3115-3143, 3189-3215`). Пустой roster обычных сессий по-прежнему защищает остальные worktree; workflow worktree проверяются по собственному lock. Перед удалением изменённые, untracked и ignored файлы копируются в `<run>/orphaned-workspaces/<worktree>/`, кроме приватных/сгенерированных файлов и пересобираемых директорий `.venv`, `venv`, `node_modules`, `.cache`, `.mypy_cache`, `.ruff_cache`, а также каталогов с корневым `pyvenv.cfg`. `workspace.json` перечисляет исключённые пересобираемые пути (`app/workspace.py:3218-3302`).

Суть diff: прежняя ветка проверяла `git status` и оставляла любой dirty worktree на месте; новая workflow-ветка удерживает lock, архивирует данные и вызывает существующий `remove_worktree`. Обычные worker worktree продолжают проходить прежнюю проверку dirty/roster.

Регрессионный тест `tests/test_workspace.py::TestCleanupStaleWorktrees::test_removes_dirty_orphan_workflow_but_keeps_active_workflow` создаёт сиротский workflow с обычными, ignored и пересобираемыми файлами и активный workflow с удерживаемым lock при пустом roster. Проверяет архив обычных результатов, исключение `.venv`, `venv`, `node_modules`, кэшей, окружения с `pyvenv.cfg`, `.wf-mcp.json` и сгенерированного `AGENTS.md`, полный список исключённых путей и сохранность активного worktree. `.venv/` и `node_modules/` помечены ignored, как типичные зависимости. Без фикса тест краснел: `.venv` попадал в архив (`1 failed in 6.53s`).

## Удаление трёх остатков University

Для чистого состояния до изменения: `git -C /home/kesha/projects/University worktree list`.

```text
/home/kesha/projects/University                                                                                                                            d84bb31 [main]
/home/kesha/orchestra/worktrees/home-kesha-projects-university/craft-3b1b                                                                                  31e8bc0 [task-V-22/craft-3b1b]
/home/kesha/orchestra/worktrees/home-kesha-projects-university/ikit-film                                                                                   2779751 [task-V-21/ikit-film]
/home/kesha/orchestra/worktrees/home-kesha-projects-university/index-video                                                                                 4388d7e [task-V-13/index-video]
/home/kesha/orchestra/worktrees/home-kesha-projects-university/kuzenkov                                                                                    045aed1 [task-V-14/kuzenkov]
/home/kesha/orchestra/worktrees/home-kesha-projects-university/neuro                                                                                       6253413 [task-V-16/neuro]
/home/kesha/orchestra/worktrees/home-kesha-projects-university/nn-video                                                                                    a413a9a [task-V-23/nn-video]
/home/kesha/orchestra/worktrees/home-kesha-projects-university/sentiment                                                                                   f678419 [adhoc-1791890662-1/sentiment]
/home/kesha/orchestra/worktrees/home-kesha-projects-university/wf-V-19-3e4abd6c290e-b7a6d0b113303fcf48d496950a49449943078a0ec428db2fdea0de617ee05d4d-0-a1  64d61b8 [feat/home-kesha-projects-university/wf-V-19-3e4abd6c290e-b7a6d0b113303fcf48d496950a49449943078a0ec428db2fdea0de617ee05d4d-0-a1]
/home/kesha/orchestra/worktrees/home-kesha-projects-university/wf-V-19-3e4abd6c290e-f108520c7766f4d55525ef0e9ad476352ff3ce6aa07fcccc918c9a015a137af6-0-a1  64d61b8 [feat/home-kesha-projects-university/wf-V-19-3e4abd6c290e-f108520c7766f4d55525ef0e9ad476352ff3ce6aa07fcccc918c9a015a137af6-0-a1]
/home/kesha/orchestra/worktrees/home-kesha-projects-university/wf-V-19-3e4abd6c290e-f862939780305bb81d74013cdc22273ea09f294e305b0836a6ed619282e2b8c6-0-a1  64d61b8 [feat/home-kesha-projects-university/wf-V-19-3e4abd6c290e-f862939780305bb81d74013cdc22273ea09f294e305b0836a6ed619282e2b8c6-0-a1]
```

Выполнено ровно три `git worktree remove --force <path>` с указанными `wf-V-19-*` путями в репозитории University, затем `git worktree prune --verbose`. Dry-run перед prune ничего не нашёл; prune после удалений также не сообщил оставшейся stale metadata. Активные University worktree не менялись. `bg-351e25d4fc` и worktree проекта Orchestra не затрагивались.

После: `git -C /home/kesha/projects/University worktree list`.

```text
/home/kesha/projects/University                                             d84bb31 [main]
/home/kesha/orchestra/worktrees/home-kesha-projects-university/craft-3b1b   31e8bc0 [task-V-22/craft-3b1b]
/home/kesha/orchestra/worktrees/home-kesha-projects-university/ikit-film    2779751 [task-V-21/ikit-film]
/home/kesha/orchestra/worktrees/home-kesha-projects-university/index-video  4388d7e [task-V-13/index-video]
/home/kesha/orchestra/worktrees/home-kesha-projects-university/kuzenkov     045aed1 [task-V-14/kuzenkov]
/home/kesha/orchestra/worktrees/home-kesha-projects-university/neuro        6253413 [task-V-16/neuro]
/home/kesha/orchestra/worktrees/home-kesha-projects-university/nn-video     a413a9a [task-V-23/nn-video]
/home/kesha/orchestra/worktrees/home-kesha-projects-university/sentiment    f678419 [adhoc-1791890662-1/sentiment]
```

University остался `main...origin/main [ahead 76]`; его статус изменений пустой. Каталогов `wf-V-19-*` в `git worktree list --porcelain` больше нет.

## Проверка

Команда: `uv run --frozen python -m pytest tests/test_workspace.py tests/test_wf_run.py -q`.

```text
........................................................................ [ 37%]
........................................................................ [ 75%]
................................................                         [100%]
192 passed in 63.30s (0:01:03)
```

`app` импортирован из `/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-wf-worktrees/app/__init__.py`.

Тест до фикса: `uv run --frozen python -m pytest tests/test_workspace.py::TestCleanupStaleWorktrees::test_removes_dirty_orphan_workflow_but_keeps_active_workflow -q` → `1 failed in 6.53s`: `.venv` и её файл оказались в архиве. После фикса, с `.venv/` и `node_modules/` в `.gitignore`, целевой тест прошёл: `1 passed in 6.34s`; `workspace.json` содержит все семь исключённых каталогов, включая `runtime-env` с `pyvenv.cfg`.

## Изменённые файлы

- `app/workspace.py` — определение inactive workflow worktree, блокировка run-id, архивирование незакоммиченных файлов, удаление сироты.
- `tests/test_workspace.py` — регрессия для грязной сироты и активного workflow.
- `CHANGELOG.md` — запись V-920.
