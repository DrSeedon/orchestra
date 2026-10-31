# V-1151 — уточнённый linked source-only ownership fix

## Результат и исправление предыдущего вывода

Первый раунд исправил отдельный реальный дефект: потерю `cwd` у существующего worker без `worktree_path`. Он **не воспроизводил исходный linked case**. После уточнения родителя новый раунд проверяет worker с непустым `worktree_path == cwd` и не использует fallback как объяснение reported HTTP500. Отчёт первого раунда сохранён отдельно в `round1-report.md`; его результаты не являются доказательством reported-path исправления.

На baseline второго раунда с уже имеющимся `cwd` fallback получен настоящий RED через MCP → HTTP → manager → memory loader: **8 failed, 74 passed**. После изменения классификации ordinary private directory те же окончательные тесты дают **82 passed**. В числе RED/GREEN — точная сообщённая родителем linked-форма, loaded и detached. Ошибка не подавляется: MCP adapter поднимает настоящий `ApiToolError` для HTTP500 `ORCHESTRA_LAYOUT_MISSING`.

## Точная причина

Синтетический основной source repository — самостоятельный Git под другим синтетическим managed parent scope. В source base внутри `.orchestra` есть только обычная `tasks/`. Linked checkout имеет ровно две обычные директории: `.orchestra/tasks/` и `.orchestra/private/`; private не symlink, layout отсутствует в обоих checkout. Session хранит настоящий linked Git `worktree_path == cwd`; общий Git directory указывает именно на source base, не на родительский scope.

`_transition_prompt` уже передаёт правильный worktree и `allow_absent_project=True`. `load_worker_memory` проверяет worker и его собственный base через общий `has_worker_memory_project_state`. До исправления этот predicate разрешал только ordinary `tasks/`; любой `private/` считался managed memory state. Поэтому optional memory ошибочно требовала layout для известного output artifact. Cwd fallback этого пути не меняет.

## Production diff и границы исключения

Новая правка только в `app/private_folder.py::has_worker_memory_project_state`: обычная директория с точным именем `private` допускается рядом с `tasks`. Типовые проверки `is_dir()` и запрет symlink сохранены. Классификатор смотрит на тип записи, **не читает private contents**, не перемещает, не удаляет и не заменяет private data.

Строгими остаются:

- файл или symlink на месте private, включая broken/foreign links;
- legacy workers, managed workers/KB и прочее настоящее managed state;
- неизвестные entries, layout markers и migration journal;
- файлы/ссылки на месте tasks и сама повреждённая `.orchestra` оболочка по прежнему контракту.

Произвольная `.orchestra/.gitignore` не получила исключения. Существующие root ignore rules и common Git `info/exclude` сохраняются. Ссылки **внутри** обычной private директории сохраняются побайтно как ссылки и не исследуются для классификации памяти. Исключение не расширяет поддержку private symlink как самой записи: она по-прежнему strict.

`allow_missing_layout`, ловля `LayoutMigrationError`, сам layout guard, migration policy, admission/models, HTTP/MCP API, upload/publication guards, ownership locks и атомарная DB/prompt публикация не менялись. Positive tests запрещают вызов реальной `migrate_project_layout` sentinel-ом; он не вызывался. Shared predicate также не заставляет source-only worktree setup создавать private metadata. Историческая managed worktree migration остаётся существующим поведением, новой миграции исправление не запускает.

Отдельный уже принятый `app/manager.py::_transition_prompt` fallback сохранён. В этом раунде manager, prompting, session и Codex backend не редактировались. `CHANGELOG.md` переписан вокруг окончательного результата, оба дефекта названы раздельно.

## Поведенческие доказательства

`tests/test_source_owned_dirs_v1151.py` содержит 82 offline случая. В новых tests реально создаются самостоятельный source Git и linked Git worktree; проверяется его top-level и common Git directory. Session rows и loaded/detached lookup настоящие. MCP использует свой штатный error adapter, HTTP — настоящий ownership route и штатный exception handler; только транспорт заменён локальным ASGI. Provider startup запрещён sentinel-ом.

Положительные private-artifact cases покрывают worker-only (точная reported форма), base-only, оба checkout и основной source checkout; loaded/detached; update и clear. Private fixture содержит синтетические бинарные байты и внутренний symlink. Все outcome assertions проверяют фактические DB/prompt данные, без brittle English `now owns`/`Ownership removed`.

Отрицательные controls добавляют настоящее managed/unknown/journal state по отдельности в base и linked worker при существующем private в обоих. Отдельно проверяются private file/broken link/foreign link в обоих checkout. Отказ обязан сохранить всю DB и текущий prompt.

Snapshots до/после охватывают:

- содержимое файлов, типы директорий и link targets в worker и другом managed parent/source base;
- private bytes и внутренние ссылки, root `.gitignore`, common `.git/info/exclude`;
- refs, Git status, stash list и worktree registry;
- sessions и все нетронутые колонки, task/reservation rows;
- prompt overlay, текущий prompt, `owned_dirs` и флаг повторной инъекции.

Нет layout/bootstrap, новых private links или сгенерированного `.orchestra/.gitignore`. Старые controls проверяют source/report-only без private, правильную managed memory и отдельный cwd fallback. Дополнительный существующий набор проверяет strict memory/recovery, concurrency/cancellation, обычные spawn/send/merge и private/publication guards.

## Runner, импорт и дословные команды

Broker uv **0.11.28**, pinned `uv.lock`, стандартная `.venv`, Python 3.12.3, локальный Git. Подмены интерпретатора и изменения lock не было. `TMPDIR` внутри task; `/usr/bin` добавлен после provisioned uv, перед dispatcher shims, чтобы Git оставался локальным. Тесты offline, без провайдера/сети. Четыре xdist workers; timeout 180 секунд на тест — hang bound, не performance claim. `RLIMIT_AS`/`RLIMIT_CPU` из зафиксированного `environment.log`: `(-1, -1)`.

Импорт `app`: `/home/<runtime-user-redacted>/orchestra-ws/<runtime-host-redacted>/hub-a68b31929bb3436f/app/__init__.py`. Интерпретатор того же checkout: `.venv/bin/python3`. Реальный reporter project, private contents/logs/history и live session не читались; форму дал родитель. Runtime path literals в логах относятся только к этой synthetic sandbox; оригиналы сохранены для обработки родителем перед публикацией.

Каждый test shell:

```sh
export PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:$PATH"
export PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:/usr/bin:$PATH"
export TMPDIR="$PWD/.orchestra/tasks/V-1151/round2/tmp"
```

RED на исходниках второго раунда (baseline с уже имеющимся cwd-fallback; родитель обозначает его 447de10):

```sh
uv run --frozen python -m pytest tests/test_source_owned_dirs_v1151.py -q -n 4 --tb=short --timeout=180 > .orchestra/tasks/V-1151/round2/red.log 2>&1
```

**8 failed, 74 passed in 104.75s**, exit 1. Все восемь failures — реальные HTTP500 для private-artifact positive cases. Exact linked worker loaded/detached падает при правильном непустом `worktree_path`. Imports и отрицательные controls проходят.

GREEN на окончательном source, без изменений тестов между RED и GREEN:

```sh
uv run --frozen python -m pytest tests/test_source_owned_dirs_v1151.py -q -n 4 --tb=short --timeout=180 > .orchestra/tasks/V-1151/round2/green.log 2>&1
```

**82 passed in 84.66s**, exit 0.

Caller/security набор:

```sh
export GIT_AUTHOR_NAME="Synthetic V1151" GIT_AUTHOR_EMAIL="v1151@example.invalid"
export GIT_COMMITTER_NAME="Synthetic V1151" GIT_COMMITTER_EMAIL="v1151@example.invalid"
uv run --frozen python -m pytest tests/test_owned_dirs_migration_473.py tests/test_prompting.py tests/test_optional_worker_memory_v1069.py tests/test_source_layout_spawn_v1130.py tests/test_worker_worktree_layout_v635.py tests/test_private_symlink_dirty_v1049.py tests/test_manager.py::TestCreateSession tests/test_manager.py::TestSendAndControl tests/test_workspace.py::TestMergeTarget tests/test_publish_guard.py tests/test_hub_workspace.py::test_upload_excludes_credentials_by_name_and_by_value tests/test_hub_workspace.py::test_upload_paths_subset_and_no_escape tests/test_hub_workspace.py::test_sync_back_cannot_escape_the_worktree tests/test_hub_workspace.py::test_sync_back_rejects_credentials_the_hub_produced -q -n 4 --tb=short --timeout=180 --basetemp="$PWD/.orchestra/tasks/V-1151/t2" > .orchestra/tasks/V-1151/round2/callers.log 2>&1
```

**5 failed, 229 passed, 2 subtests passed in 133.93s**, exit 1. Пять failures относятся к исходным зависимостям, отсутствующим в этой copy:

- `scripts/migrate_orchestra_layout.py`: `test_repair_ownership_cli_prints_the_plan_and_repeats_to_zero`, `test_dry_run_alone_cannot_commit_a_layout_migration`, `test_the_dirty_error_command_fixes_the_worktree`, `test_supported_explicit_repair_then_spawn_keeps_memory`;
- `scripts/secret_scan.py`: `test_pre_push_hook_blocks_listed_string`.

Runner присутствует, frozen setup/imports успешны; дочерние CLI процессы завершаются `Errno 2`/exit 2. Ни другой интерпретатор, ни заглушки вместо скриптов не использовались. Целевое поведение этих пяти проверок остаётся непроверенным до полного checkout родителя. Это те же отсутствующие зависимости, которые были зафиксированы в первом раунде. Полный caller прогон сохранён как красный, а не представлен зелёным набором с исключёнными tests.

Все остальные выбранные controls прошли, включая strict memory/layout recovery, private symlink dirty checks и сохранность ignore metadata, обычные source/report-only spawn/send/merge, ownership concurrency и повторную cancellation между DB write и prompt publication, а также выбранные upload/data guards. Прежний path-length-sensitive Codex doc-preflight тест также прошёл при коротком локальном `--basetemp`, без изменения его кода.

## Артефакты и остаточная приёмка

`round2/red.log` и `round2/green.log` — дословные результаты на одинаковых новых тестах; `round2/callers.log` — отдельный полный caller прогон. `round2/change.patch` — только новое production изменение; прежний manager patch остаётся в `change.patch`. В `round2/before.sha256` и `round2/after.sha256` — происхождение baseline/final bytes. В этой копии нет `.git`: commit identity независимо не утверждается, hashes позволяют родителю сверить его 447de10. Root commit/push не выполнялся; результат импортирует платформа в `task-V-1151/fix-source-owned-dirs`.

Предыдущие phase-one logs и `round1-report.md` сохранены как история отдельного дефекта. Они не заменяют новый reported-path RED/GREEN. Исторический V-1130 report не изменялся. V-1150 session/backend/context/UI не менялись; их baseline checksum сохранён и проверен.

Скан changed source/test/changelog и task artifacts существующими `HUB_SECRET_SHAPES`: **29 файлов, совпадений нет**, exit 0; `round2/artifact-scan.log`. Настоящий credential inventory не читался. Команда:

```sh
export PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:$PATH"
uv run --frozen python .orchestra/tasks/V-1151/verify_artifacts.py > .orchestra/tasks/V-1151/round2/artifact-scan.log 2>&1
```

Это отдельный shape check; он не подменяет отсутствующий standalone `secret_scan.py` или его непрошедший CLI тест. Временные синтетические Git/DB/private fixtures и полная временная копия baseline source удалены. Source/test/changelog совпадают с финальными checksum; manager/prompting/session/backend совпадают также с baseline второго раунда. Protected raw репортёра не получался и не передавался.

Полный host runner `uv run --frozen python scripts/run_tests.py` в этой неполной copy не запускался. Приёмка на полном checkout и активация Python остаются родителю и существующему авторизованному idle watcher. Нет manual restart, deployment, настоящих сообщений/провайдеров, новых платных вызовов, credentials или чужих изменений.

Publication note: parent normalized runtime user/host literals in this report and stdout derivatives. Verbatim originals and hashes remain private under V-1151; source/tests, numeric results and line counts of log derivatives are preserved.
