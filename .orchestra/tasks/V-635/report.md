# V-635: автомиграция worktree воркера в старой раскладке

Выбран вариант (b) из `.orchestra/tasks/V-634/report.md`, раздел «Нужны решения»: только чистые деревья.

## Что сделано

`app/orchestra_layout.py` `migrate_worker_worktree(worktree)` выполняет миграцию только при
одновременном выполнении условий:
- путь является top-level linked worktree, то есть `_base_checkout` отличается от самого пути;
- у worktree раскладка `old` (не `partial` и не `missing`);
- у базового чекаута раскладка `current`. Если база старая, ничего не делается и остаётся
  ошибка V-611 на базу: миграция одной ветки над старой базой бесполезна, это и был цикл V-611;
- `git status --porcelain` пуст. Иначе `LayoutMigrationError("ORCHESTRA_LAYOUT_DIRTY")` с
  `repository=<worktree>` и `repair_command` = `git -C <wt> add -A && git -C <wt> commit -m
  'WIP before layout migration' && <python> scripts/migrate_orchestra_layout.py <wt>`.
  Подсказка `--repair` здесь не годится: на грязном дереве без preserve-журнала она падает
  с той же DIRTY.

Сама миграция делается вызовом `migrate_project_layout(worktree)` без `_allow_dirty` и без
`repair`. Внутри `repo_mutation_lock` грязь проверяется повторно, а stash на этом пути
не используется. Результат тот же, что у драйвера V-634 для чистого дерева: `git mv` и
коммит «Orchestra: migrate project state to .orchestra» в текущей ветке воркера.

Вызов находится в `app/prompting.py` `load_worker_memory`: срабатывает, когда
`layout.json` нет и передан `repository_path`. Через эту функцию (`refresh_worker_memory`)
проходят все три точки подъёма воркера: `_load_from_db` → `assemble_prompt` (resume после
старта), `_transition_prompt` (смена задачи) и инъекция промпта на первом сообщении в
`session.py`, в том числе после auto-switch. `LayoutMigrationError` получил необязательный
параметр `repair_command`.

## Проверка

`tests/test_worker_worktree_layout_v635.py`: настоящие git-репозитории в `tmp_path`
(база, мигрированная в current, и worktree на ветке, созданной до миграции).
Вызов идёт через `refresh_worker_memory`.
- чистое дерево: раскладка current, `HEAD~1` равен прежнему HEAD, сообщение коммита
  миграции совпадает, ветка та же, статус чистый, память воркера из `.orchestra/workers` в промпте;
- грязное дерево (изменённый tracked-файл и один untracked): DIRTY, в ошибке и команде путь
  worktree, HEAD, статус, stash list и файл не изменились, `.orchestra/` не создан;
- команда из ошибки, выполненная как есть, приводит дерево к current с сохранением правки;
- дерево в current: число коммитов не изменилось;
- база старая: `ORCHESTRA_LAYOUT_MISSING` на базу (V-611), коммитов в worktree нет.

Мутация: без вызова в `load_worker_memory` три теста падают (чистое, грязное, команда).
Тесты current и старой базы остаются зелёными, так и должно быть.

Прогон: `/home/kesha/orchestra/.venv/bin/python -m pytest` по новому файлу и файлам
`test_orchestra_layout_430`, `_repair_base_v611`, `_compat_430`, `_fleet_430`,
`test_prompting`, `test_prompt_parent_selection`, `test_owned_dirs_migration_473`,
`test_manager`: 277 passed. Импортирован
`/home/kesha/orchestra/worktrees/home-kesha-orchestra/worktree-layout/app/orchestra_layout.py`.

## Остаточный риск

- Миграция идёт синхронно в event loop. `repo_mutation_lock` общий на git common dir,
  поэтому если в этот момент идёт мерж того же репозитория, сборка промпта ждёт его окончания.
  Это случается один раз на старое дерево.
- `migrate_project_layout` также запускает перенос ownership по строкам `sessions`, у которых
  scope равен пути worktree. У обычных воркеров scope другой, поэтому на живом пути
  это не проверялось.
- Живые репозитории и боевая БД не трогались. Для работы нужен рестарт Orchestra, это Python-правка.
