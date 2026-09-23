# V-621 — каталог проектов: файл на scope, а не один общий

Решение владельца 23.09.2026, дословно: «эта хуйня в каждом оркестраторе свои задачи
должны быть и свои проекты не надо мешать блять и каждый оркестратор локально в дот
оркестра может проекты вписывать свои». Повод: после V-576 во вкладке ЗАДАЧИ у каждого
оркестратора висели чипы всех 18 проектов — свои и чужие вперемешку.

Ветка `task-V-621/local-projects`. Боевую БД и боевое хранилище задач не трогал (только
временные копии/tmp_path); чужие проекты и ветки не трогал; рестарт не делал. Во время
работы получил сообщение от оркестратора, что ход оборвался на `git stash push` — работа
была цела в worktree, закоммитил как WIP (`4e77788f`) и больше стэш не трогал.

## 1. Что сделано

### 1.1 Каталог — файл на каждый scope (`app/project_catalog.py`)

Было: один файл `.orchestra/projects.yaml` в репозитории Orchestra, `catalog()` парсил
его целиком — все 18 проектов видны отовсюду.

Стало: `own_catalog(scope)` открывает РОВНО `<scope>/.orchestra/projects.yaml` — файл
проекта, которым он владеет сам. Это то, что оркестратор видит и может выставить: чужой
файл этот код не открывает физически, а не по фильтру. Отсутствующий файл — не авария
(scope, который ещё не завёл каталог), а пустой каталог; громко падает только испорченный
существующий файл.

`catalog()` (без аргумента) остался — но сузился до внутренней бухгалтерии ОДНОЙ
установки: проекция номеров при старте (`sync_catalog`), метка источника задачи
(`#161 · ноутбук`). Он собирается из домашнего файла (`.orchestra/projects.yaml` этой
установки) плюс каждого пути из его нового поля `include_scopes` — списка чужих
собственных файлов, которые эта установка подмешивает в свой слитый вид. Проекты без
scope (архив: `polus`, `sensar`, `family-tree` и т.п. — 9 штук на 23.09) живут в
домашнем файле: им больше негде быть, `own_catalog` для них не существует.

Валидация тега/namespace/scope конфликтов раньше проверялась внутри одного разбора
файла; теперь вынесена в `_aggregate()` и общая для обоих путей — `own_catalog` гоняет
её на списке из одного файла, `catalog()` — на списке из нескольких. Один и тот же код
ловит и дубликат внутри файла, и коллизию между двумя включёнными файлами (тест
`test_merged_catalog_rejects_a_tag_declared_in_two_included_files`).

Тестовая изоляция (`tests/conftest.py`): `own_catalog(scope)` в тестах никогда не читает
боевой диск — `ORCHESTRA_PROJECT_CATALOG_ROOT` уводит его в песочницу `tmp_path/scopes`;
без явной записи файла там `own_catalog` любого scope пуст. В проде эта переменная не
задана — `own_catalog(scope)` читает буквально `<scope>/.orchestra/projects.yaml`.

### 1.2 Оркестратор видит и ставит только свои теги

- `GET /api/tm/projects?scope=<путь>` — чипы фильтра (`app/routes/tm.py`): со `scope`
  отдаёт ровно `own_catalog(scope).projects`, без — прежний слитый вид (админский путь).
- `app/static/js/app.js`: `_taskProjectCatalog()` теперь запрашивает `?scope=currentScope`
  и кэш инвалидируется при смене scope (`_taskCatalogScope`); `onOrchestratorChange()`
  чистит выбранные теги-чипы при переключении оркестратора, чтобы чужой выбор не
  пережил смену. Список задач по умолчанию (`_loadTasksNow`) шлёт `scope=` ВСЕГДА, даже
  вместе с `tags=` — фильтр по тегам тоже проверяется по своему каталогу.
- `app/tm.py`: `normalize_tags`, `resolve_project_selector`, `api_list_tasks`,
  `_resolve_task_create_project` получили `catalog_scope` — с ним тег ищется ТОЛЬКО в
  `own_catalog(catalog_scope)`. Пустой `catalog_scope` (внутренние вызовы, часть старых
  тестов) — прежнее поведение через слитый `catalog()`, обратная совместимость не
  сломана.
- `_resolve_task_create_project`: если явный тег существует ГДЕ-ТО на платформе
  (слитый вид), но не в собственном каталоге вызывающего scope, раньше это молча
  подставило бы проект самого вызывающего scope (или просто отказало бы как
  «неизвестный»); теперь — явный отказ `'<tag>' is not registered in this scope's own
  catalog`, а не тихая подмена.
- `app/mcp_stdio.py`: `task_create`/`task_update` уже слали `scope: SCOPE` (без
  изменений); `task_list` теперь шлёт `scope` ВМЕСТЕ с `tags`, а не вместо него (было
  `elif`, стало отдельная ветка) — фильтр по тегам тоже проходит через каталог
  вызывающего. `task_get`/`task_update` с явным `project=` НЕ получили `scope` (частая
  причина — заморожен тест `test_task_get_and_update_prefer_explicit_project_over_scope`,
  который проверяет точный `params` без `scope` при явном `project`; трогать не стал).
  Значит явный `project=<чужой тег>` в этих двух путях остаётся не заблокированным на
  уровне MCP-клиента — задокументированная граница, не полное покрытие.

### 1.3 Миграция существующих 1863 задач и их тегов (`app/catalog_migration_v621.py`)

По образцу `app/startup_migration.py` (V-576), вызывается из `app/main.py` ДО
`sync_catalog`, идемпотентно:

1. **Разбор домашнего файла** — единственное, что ещё может уронить старт (см. ниже).
2. **Бэкап** старого домашнего файла рядом, с меткой времени UTC — всегда, до записи.
3. **По каждому scope из старого файла — попытка завести его собственный файл**
   (`<scope>/.orchestra/projects.yaml`): каталог создан, записан, закоммичен, если это
   git. Если scope уже владеет своим файлом (прошлый частичный прогон или ручная
   правка) — не перезаписывается, просто подхватывается в `include_scopes`.
4. **Новый домашний файл**: `include_scopes` — объединение прежних значений с тем, что
   удалось сейчас; `projects:` — сироты плюс то, что ещё НЕ удалось разобрать.
5. **Коммит домашнего файла — точечный**, `git add -- <файлы>` + `git commit` без `-a`:
   коммитятся ровно эти файлы, что бы ещё ни было не закоммичено в том же
   репозитории — чужая незакоммиченная работа в него не попадает и им не мешает.

**Деградация вместо отказа старта — решение владельца 23.09.2026, второй заход.**
Первая версия требовала чистоты КАЖДОГО затронутого scope и роняла старт всей
платформы, если хоть один из восьми чужих репозиториев в момент рестарта оказался
грязным — а починить это изнутри некому, агенты вместе с Orchestra лежат. Теперь
непригодный ЧУЖОЙ scope (грязный git, нет каталога на диске, отказ прав на запись,
любая иная ошибка записи/коммита) громко логируется и просто остаётся в домашнем
файле как был — его тег продолжает резолвиться через слитый `catalog()`, просто ещё
не через собственный `own_catalog(scope)`. Служба стартует и работает. Идемпотентность
теперь НЕ разовый флаг «мигрировано/нет»: каждый следующий запуск заново ищет внутри
`projects:` домашнего файла записи с чужим `scope` и доразбирает их — пропущенный
scope доедет сам на следующем рестарте или когда владелец руками почистит его дерево.
Падать на старте можно только если ЧИТАТЬ НЕЧЕГО — домашний файл не парсится или не
той формы; это не про чужой scope, чинить некому, значит служба честно не стартует.

От владельца по-прежнему требуется один рестарт и ни одной команды — просто теперь
это гарантия, а не надежда на чистоту восьми чужих репозиториев одновременно.
Существующие теги остаются валидными «просто через include_scopes вместо одного
файла» — проверено тестом `test_existing_tags_all_remain_resolvable_after_the_split`,
а для пропущенного scope — `test_a_dirty_external_scope_is_skipped_others_split_service_starts`
и `test_a_missing_scope_directory_is_skipped_others_split_service_starts`.

**Что НЕ было сделано мной руками**: сама миграция реальных 9 scope на VPS не
запускалась — граница задачи прямо запрещает трогать чужие проекты и боевые пути.
Она сработает при следующем рестарте Orchestra на текущем боевом
`.orchestra/projects.yaml` (18 проектов, 9 scope — см. `.orchestra/tasks/V-576/report.md`).
На 23.09 все восемь внешних scope чистые (со слов владельца) — состояние минуты, не
гарантия; если что-то изменится к моменту рестарта, деградация подхватит это без
дополнительных действий.

## 2. Порядок выката и откат

1. Мерж этой ветки в `main`.
2. Рестарт Orchestra владельцем (единственное требуемое действие). При старте
   `migrate_v621()` пытается разбить `.orchestra/projects.yaml` на домашний файл
   (`orchestra` + 9 архивных/сиротских тегов) плюс до 8 файлов
   `<scope>/.orchestra/projects.yaml` (seedon, comfy-image-pipeline, cog-second-brain,
   kesha-tg-bot, katya-work, dnd-game-master, vpn-service, university). Служба
   поднимется независимо от состояния этих восьми репозиториев.
3. Проверить лог на `V-621 catalog split:` — поля `written`/`already` (что разобралось),
   `skipped` (что осталось в домашнем файле и почему — грязный git, нет каталога,
   отказ записи) и `home_committed`. Непустой `skipped` — не авария, а список того, что
   ещё нужно почистить владельцу (или что само доедет на следующем рестарте).

**Откат.** Файлы — `git revert` коммита в каждом затронутом репозитории (домашнем и
внешних, только там, где коммит реально прошёл — см. `written`/`home_committed` в
логе) плюс возврат бэкапа `.orchestra/projects.yaml.pre-v621-<UTC>.yaml` в домашний
файл, если ревert неудобен. Код — `git revert` этого мержа в Orchestra. Оба независимы,
без БД (миграция файловая, SQLite не трогает).

## 3. Чем проверено

- `python -m pytest tests/test_project_catalog_v621.py tests/test_catalog_migration_v621.py`
  — 24 новых теста, все зелёные. Покрывают ровно акцептанс: чужой тег не виден
  (`test_own_catalog_does_not_see_a_foreign_scope_file`,
  `test_projects_endpoint_scoped_to_caller_hides_foreign_tags`) и не принимается
  (`test_task_tags_validate_against_the_callers_own_scope_only`,
  `test_api_list_tasks_rejects_a_foreign_scopes_tag`,
  `test_api_create_task_rejects_a_foreign_scopes_tag`); правка локального файла
  применяется без рестарта (`test_own_catalog_reloads_after_an_edit_without_restart`);
  задача с несколькими тегами и без тегов остаётся валидной
  (`test_task_without_tags_and_task_with_several_tags_both_stay_valid`); миграция —
  бэкап, точечный коммит, существующие теги резолвятся после разбиения
  (`test_existing_tags_all_remain_resolvable_after_the_split`), идемпотентность
  (`test_migration_is_idempotent_on_rerun`) — и деградация вместо отказа старта:
  грязный/отсутствующий внешний scope пропускается, остальные едут, служба
  стартует, тег пропущенного всё ещё резолвится
  (`test_a_dirty_external_scope_is_skipped_others_split_service_starts`,
  `test_a_missing_scope_directory_is_skipped_others_split_service_starts`), второй
  рестарт дожимает пропущенное, когда оно стало чистым
  (`test_a_skipped_scope_is_picked_up_on_the_next_start_once_clean`), точечный
  коммит домашнего файла не спотыкается о чужой незакоммиченный файл в том же
  репозитории (`test_a_dirty_home_repository_still_writes_and_commits_only_its_own_files`),
  а испорченный/непарсящийся домашний файл по-прежнему валит старт громко
  (`test_refuses_to_start_when_the_home_file_has_unexpected_shape`,
  `test_refuses_to_start_when_the_home_file_is_not_valid_yaml`).
- Прежние тесты каталога и задач: `tests/test_project_catalog_v576.py` (22),
  `tests/test_startup_migration_v576.py` (8), `tests/test_tm.py` (22) — без изменений в
  тексте тестов, все зелёные: `catalog()` без `include_scopes` в файле ведёт себя
  байт-в-байт как раньше (обратная совместимость по конструкции, не по патчу теста).
- Прямые потребители изменённого кода: `test_api.py` (127), `test_mcp_stdio.py` (125),
  `test_acceptance.py`, `test_git_task_api.py`, `test_mcp_proof.py`,
  `test_merge_target_oracle_386.py`, `test_merge_test_gate.py`,
  `test_task_tracker_integration.py`, `test_adhoc_switch.py`, `test_identity_drift.py`,
  `test_task_binding_417.py`, `test_vps_task_prefix.py` — все зелёные и до, и после
  мержа свежего `main` (см. §4).
- Импортированный `app` при прогоне —
  `/home/kesha/orchestra/worktrees/home-kesha-orchestra/local-projects/app/__init__.py`
  (`uv run python -m pytest`, не системный `pytest`).
- Остальные ~232 файла тестов прогнаны батчами (частично через
  `ssh -o BatchMode=yes kesha@localhost` — совместный прогон на этом VPS сейчас
  ОБЩЕИЗВЕСТНО падает по OOM/зависает у ~85% независимо от задачи, см. TODO.md
  «повис на ~85%... с V-610 не связано» и мой собственный `EXIT=137` дважды на полном
  прогоне что локально, что по ssh). Реальных регрессий не найдено: 12 упавших тестов
  из разных прогонов проверены поштучно и КАЖДЫЙ воспроизведён на голом `main`
  (628ac205, без моей ветки, через одноразовый `git worktree add --detach`) или в
  изоляции показал флап из-за параллельной нагрузки на VPS от других воркеров —
  `test_backend_codex.py::test_installed_codex_history_version_matches_pin`,
  `test_backend_routing.py::test_opus5_registry_and_aliases`,
  `test_pipeline.py::TestEffortByModel::test_alias_key_normalized_to_model_id`
  (дрейф каталога моделей после «opus → 5.5», не мой коммит),
  `test_check_pipeline_manifest.py::test_check_passes_on_current_default`
  (`model-routing.md` без inline-маркера источника, не мой коммит),
  `test_mcp_codex_review.py` × 5 и
  `test_mcp_stdio.py::test_codex_review_default_is_server_owned_luna_fast`
  (V-620 переименовал `_CODEX_REVIEW_DEFAULT_MODEL` в `gpt-6-luna`, но параметр
  `model` по умолчанию в `codex_review()` остался `gpt-5.6-luna` — воспроизведено на
  main без моей ветки), `test_logs_sync.py::test_chat_snapshot_is_never_served_from_http_cache`
  (воспроизведено на main), `test_send_file_open_button.py` (жёсткая проверка русской
  строки в JS, дрейф локализации) и `test_tailwind_css.py::test_committed_css_matches_current_sources`
  (уже в TODO.md как известный красный), `test_codex_writer_conflict_536.py` (403
  вместо 409 при совместном прогоне — прошёл 7/7 в изоляции).

## 4. Мерж свежего main во время работы

Оркестратор попросил подтянуть `main` — за время работы туда легли V-620
(`switch_worker_branch` освобождает привязку воркера) и смена маршрута моделей
(`luna`/`sol` → GPT-6). Пересечение файлов: `app/tm.py`, `app/mcp_stdio.py`,
`CHANGELOG.md`. `git merge main --no-edit` прошёл БЕЗ конфликтов (`4c327220`) —
V-620 трогал `_finish_task_run_for_task`/`release_session_task_binding`/
`api_update_task_if_current` (строки ~820–1690 в старой нумерации), я — `normalize_tags`/
`resolve_project_selector`/`api_list_tasks`/`_resolve_task_create_project` (другие
участки файла); в `mcp_stdio.py` V-620 правил `switch_worker_branch` и одну строку
дефолтной модели ревью, я — `task_list`/`task_update` докстринги и параметры. После
мержа весь прямо relevant набор тестов перепрогнан заново (см. §3) — зелёный.

## 5. Оставшийся риск / известные границы

- Реальная миграция боевого каталога (9 scope на VPS) не выполнялась мной и не
  проверялась на боевых путях — только на временных git-репозиториях в `tmp_path`.
  Сработает при следующем рестарте; лог `V-621 catalog split complete` — первое, что
  стоит проверить после него.
- `task_get`/`task_update` с явным `project=` в MCP-клиенте не получают `scope` (граница
  §1.2) — чужой тег там всё ещё резолвится через слитый `catalog()`, если вызывающий его
  явно знает и передаёт. `task_list`, `task_create`, чипы `/api/tm/projects` и `tags=` на
  update — закрыты.
- Не-git внешние scope (если такие есть среди 9) получат файл каталога без
  автоматического коммита — не авария (каталог работает сразу), но требует ручного
  коммита при следующей правке того проекта.
