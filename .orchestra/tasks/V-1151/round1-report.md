# V-1151 — source-only ownership updates

## Причина и исправление

Сбой воспроизведён на синтетических данных. `_transition_prompt` передавал в `refresh_worker_memory` только `session.worktree_path or ""`. Для существующего воркера без записанного `worktree_path` это теряло собственный `cwd`. В `load_worker_memory` выражение `Path(repository_path or scope)` выбирало родительский routing scope, хотя там находится другой Git-проект.

Если у родителя есть managed state, но нет layout, реальный HTTP ownership route возвращал 500 `ORCHESTRA_LAYOUT_MISSING`; ошибка проходила через существующий MCP error adapter. Если layout родителя существует, операция вместо отказа подмешивала его память. Собственное повреждённое состояние при этом могло остаться незамеченным.

Исправлен только этот аргумент в `app/manager.py::SessionManager._transition_prompt`: `session.worktree_path or session.cwd`. Явный worktree сохраняет приоритет. Политика optional memory, `allow_missing_layout`, обработка `LayoutMigrationError`, миграция, модели, admission, HTTP/MCP API и атомарная запись ownership не менялись. Сам `app/prompting.py` менять не потребовалось: его существующее разрешение source-only/reports-only уже корректно при передаче собственного checkout.

Добавлена рукописная запись в `CHANGELOG.md`. Рабочий Python не перезапускался; активация остаётся за авторизованным idle watcher после принятия родителем.

## Репродукция и границы доказательства

`tests/test_source_owned_dirs_v1151.py` создаёт реальный Git parent с managed memory и вложенный независимый Git source repository. У source есть обычные исходники и корневой `skills/`, отдельно проверяются task reports. Родитель проверяется с layout и без него.

Тесты создают существующую session row с сохранённым `cwd`, проверяют loaded registry и настоящий detached hydrate, вызывают настоящий `set_worker_owned_dirs`, ownership HTTP route, manager и SQLite. HTTP использует штатный глобальный exception handler, MCP — штатный error adapter; локальный ASGI transport заменяет сеть. `AgentSession.start` заменён запрещающим sentinel. Провайдер не запускается.

44 случая проверяют:

- update и clear ownership для source-only/reports-only, loaded/detached, с явным worktree и без него;
- реальные `owned_dirs`, `system_prompt`, `prompt_overlay`, текущий prompt и флаг повторной инъекции;
- отсутствие stale/foreign parent memory и обновление собственной managed memory;
- строгий отказ на собственных workers/legacy workers, migration journal, неизвестном state, повреждённом layout entry и broken managed symlink;
- отсутствие частичной DB/prompt записи при отказе;
- сохранность остальных session columns, tasks/reservations, файлов/ссылок, refs, worktree registry и stashes; отсутствие bootstrap `.orchestra`, private и ignore metadata у source-only.

`LayoutMigrationError` для linked worker намеренно называет его основной checkout как место ремонта. Проверяется именно собственный source project, а не чужой родительский scope.

Реальный репортёр, его DB/session/log/history и чужие проекты не исследовались. Доказан конкретный путь потери repository context у существующей строки без `worktree_path`; наличие такого поля у реального репортёра не утверждается. Общее поведение layout JSON/schema в загрузчике памяти не пересматривалось: проверяются существующие отказы managed state при отсутствующем layout.

## Среда и команды

Broker uv **0.11.28**, pinned `uv.lock`, стандартная `.venv`, Python 3.12.3, настоящий локальный Git 2.43.0. Зависимости устанавливал только frozen uv. Интерпретатор не подменялся. `TMPDIR` направлен внутрь task directory; `/usr/bin` стоит перед inherited dispatcher shims, чтобы синтетический Git выполнялся локально.

Импортированный `app`: `/home/<runtime-user-redacted>/orchestra-ws/<runtime-host-redacted>/hub-a68b31929bb3436f/app/__init__.py`.

Интерпретатор: `/home/<runtime-user-redacted>/orchestra-ws/<runtime-host-redacted>/hub-a68b31929bb3436f/.venv/bin/python3`. `RLIMIT_AS` и `RLIMIT_CPU`: `(-1, -1)`. Проверки запускались четырьмя xdist workers, последовательно между наборами, с hang bound 180 секунд на тест. Это не замер производительности. Подробности — `environment.log`.

Одинаковая подготовка принятых red/green shell:

```sh
export PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:/usr/bin:$PATH"
export TMPDIR="$PWD/.orchestra/tasks/V-1151/tmp"
```

RED, исходный manager, окончательные регрессии:

```sh
uv run --frozen python -m pytest tests/test_source_owned_dirs_v1151.py -q -n 4 --tb=short --timeout=180 > .orchestra/tasks/V-1151/red-accepted.log 2>&1
```

**22 failed, 22 passed in 69.48s**, exit 1. Это реальные behavioral failures: HTTP500, чужая память и ошибочное разрешение собственной managed-state ошибки. Linked worktree controls проходят. Нет import/wording failures.

GREEN, исправленный manager, те же тесты:

```sh
uv run --frozen python -m pytest tests/test_source_owned_dirs_v1151.py -q -n 4 --tb=short --timeout=180 > .orchestra/tasks/V-1151/green.log 2>&1
```

**44 passed in 68.52s**, exit 0.

Расширенный caller/security набор:

```sh
export GIT_AUTHOR_NAME="Synthetic V1151" GIT_AUTHOR_EMAIL="v1151@example.invalid"
export GIT_COMMITTER_NAME="Synthetic V1151" GIT_COMMITTER_EMAIL="v1151@example.invalid"
uv run --frozen python -m pytest tests/test_owned_dirs_migration_473.py tests/test_prompting.py tests/test_optional_worker_memory_v1069.py tests/test_source_layout_spawn_v1130.py tests/test_worker_worktree_layout_v635.py tests/test_manager.py::TestCreateSession tests/test_manager.py::TestSendAndControl tests/test_workspace.py::TestMergeTarget tests/test_publish_guard.py tests/test_hub_workspace.py::test_upload_excludes_credentials_by_name_and_by_value tests/test_hub_workspace.py::test_upload_paths_subset_and_no_escape tests/test_hub_workspace.py::test_sync_back_cannot_escape_the_worktree tests/test_hub_workspace.py::test_sync_back_rejects_credentials_the_hub_produced -q -n 4 --tb=short --timeout=180 > .orchestra/tasks/V-1151/callers.log 2>&1
```

**6 failed, 212 passed in 122.63s**, exit 1. Лог сохранён дословно. Прошли существующие сценарии atomic cancellation/повторной отмены, ownership locks, detached narrow write и reload race, обычные source/report-only spawn/send, managed memory/worktree recovery, реальные merge controls и выбранные upload/data guards.

Пять проверок не смогли проверить своё целевое поведение из-за отсутствующих исходных зависимостей в выданной копии:

- `scripts/migrate_orchestra_layout.py`: `test_repair_ownership_cli_prints_the_plan_and_repeats_to_zero`, `test_dry_run_alone_cannot_commit_a_layout_migration`, `test_supported_explicit_repair_then_spawn_keeps_memory`, `test_the_dirty_error_command_fixes_the_worktree`;
- `scripts/secret_scan.py`: `test_pre_push_hook_blocks_listed_string`.

Во всех этих случаях вызван provisioned/frozen runner, а дочерний процесс завершился из-за отсутствующего файла (`Errno 2`/exit 2). Скрипты не заменялись заглушками и проверки не ослаблялись. Требуется повторить их на полном checkout родителя; успех repair CLI и standalone pre-push hook здесь не подтверждён.

Шестое падение — `TestCodexProjectDocPreflight::test_multibyte_overflow_reports_first_incomplete_line_and_bounded_fallback`: строка предупреждения имеет 669 символов при ожидаемых `<600`, потому что длинный абсолютный sandbox path входит в неё дважды. `app/prompting.py` и этот тест не менялись. Повторный контроль с более коротким локальным `--basetemp`:

```sh
uv run --frozen python -m pytest tests/test_prompting.py::TestCodexProjectDocPreflight::test_multibyte_overflow_reports_first_incomplete_line_and_bounded_fallback -q --tb=short --timeout=180 --basetemp="$PWD/.orchestra/tasks/V-1151/t" > .orchestra/tasks/V-1151/prompt-path-control.log 2>&1
```

**1 passed in 45.50s**, exit 0. Это подтверждает зависимость от пути; продукт и тестовый контракт не менялись. Исходный расширенный набор всё равно зарегистрирован как красный.

## Артефакты, ранние попытки и интеграция

`red-accepted.log` и `green.log` сохранены дословно, включая синтетические tracebacks. Ранние попытки также сохранены отдельно: `red.log` был прерван; `red-first.log` получил 30-секундный timeout во время Pydantic import; `red-behavior.log` получен до завершения оформления HTTP handler в новых тестах; `red-final.log` содержит неверное первоначальное ожидание repair target для linked checkout. Эти попытки не подменяют окончательный RED выше.

`change.patch` содержит единственный source hunk; `before.sha256` и `after.sha256` фиксируют происхождение и неизменный соседний контекст. Нет `.git`, поэтому Git history/commit provenance этой копии не утверждается. Корневой commit/push не выполнялся; ветку `task-V-1151/fix-source-owned-dirs` собирает платформа.

Финальные исходные checksum совпали с `after.sha256`; prompting/session/backend/HTTP/MCP совпали и с исходными checksum. Временные синтетические Git-песочницы и полные временные копии исходников удалены; остаются scoped patch, исходные/финальные hashes, отчёты и verbatim logs.

```sh
export PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:/usr/bin:$PATH"
uv run --frozen python .orchestra/tasks/V-1151/verify_artifacts.py > .orchestra/tasks/V-1151/artifact-scan.log 2>&1
```

Credential-shape scan существующими `HUB_SECRET_SHAPES`: **20 файлов, совпадений нет**, exit 0. Проверены изменённые source/test/changelog и task artifacts, включая сырые синтетические логи. Inventory настоящих credentials не читался. Этот локальный shape scan не выдаётся за отсутствующий standalone pre-push script или его непрошедший интеграционный тест.

V-1150: фактическая правка ограничена `_transition_prompt` в manager. `app/session.py`, `app/backend_codex.py`, prompting, HTTP и MCP совпадают с полученными исходными байтами; backend/session/context/UI не редактировались. Изолированный hunk позволяет родителю сопоставить его с актуальными правками коллеги. Исторический V-1130 report прочитан полностью и не изменён.

Полный host gate `uv run --frozen python scripts/run_tests.py` не запускался: эта source copy неполна, интеграционное принятие остаётся родителю. Нет live provider/messages, рестарта, deployment, реальных credentials, новых зависимостей, автоматической миграции или изменений чужих данных.

Publication note: parent normalized runtime user/host literals in this report and stdout derivatives. Verbatim originals and hashes remain private under V-1151; source/tests, numeric results and line counts of log derivatives are preserved.
