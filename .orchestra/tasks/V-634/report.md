# V-634: ноутбучная Orchestra после синка с VPS — отчёт

Ноутбук: `/mnt/data/Projects/Python/orchestra`, БД `data/storage-recovery-local-20260908/orchestra.db`.
Исходное состояние: main `35ac1cb7` (синк `083f4871` + лишний коммит V-621), рестарт в 17:27.

## Что было и причины

1. **21 worktree в старой раскладке (`docs/tasks|kb|workers|archive`).** В журнале было 17 `ORCHESTRA_LAYOUT_MISSING`.
   Ещё четыре сессии (bizdev, infra, ent, sales) без `session_id` при старте не резюмируются
   и упали бы на первом сообщении. Одна сессия (burial-import) была `broken`, потому что каталог её worktree исчез.
   Причина: стартовая миграция (`migrate_registered_project_layouts`) переводит только
   базовый чекаут из `tm_projects.scope`, а ветки воркеров остаются старыми. `load_worker_memory`
   видит в worktree `docs/tasks` без `.orchestra/layout.json` и падает. Подсказка `repair`
   (после V-611) указывает на базовый чекаут, который уже current, поэтому ничего не чинит.
   У ent и infra старым был и сам базовый репозиторий (`orchestra-enterprise`, `seedon/infra`):
   их нет в `tm_projects`, стартовая миграция их не видит.
2. **gamedesign-researcher**: роль `researcher` удалена в `3478d558` (03.07, влита в full-cycle).
3. **Лишний коммит V-621 на каждом старте.** Если в каталоге остался хоть один пропущенный scope,
   `migrate_v621` делал бэкап, переписывал домашний файл тем же содержимым и коммитил его.
   В main ноутбука таких коммитов пять (`1525b636`, `cf862eec`, `b7ada189`, `7ae410f8`, `35ac1cb7`), бэкапов четыре.
   Каталог ноутбука хранит девять scope с путями VPS (`/home/kesha/...`, `/opt/cog-second-brain`), и на этом диске они не появятся никогда.
4. **Девять ложных `not a Git checkout`.** `sync_catalog` проецирует те же пути VPS в `tm_projects.scope`,
   миграция раскладки пыталась их обойти. `university` — одна из них.
5. **Сломанные базовые чекауты**, которых не было в постановке задачи (из того же журнала):
   - `Parsing`, `stargate-tactics`: `cannot locate the migration commit while recovering stash`.
     Это застрявшие журналы preserve-dirty (фаза `stashed`) от старого прогона. HEAD с тех пор ушёл вперёд, поэтому
     автоматическое восстановление невозможно. Незакоммиченная работа лежит ТОЛЬКО в stash:
     Parsing `c621720b`: CLAUDE.md, CREDENTIALS.md, TASKS.md, YOUGILE_ARCHIVE.md, artifacts/ и kb records.
     stargate `36cbab6c`: `.serena/project.yml`, `docs/artifacts/polus-gamedesign.html`, kb records.
   - `TradingCryptoBot`: пустой (0 байт) `.git/orchestra-layout-preserve.json` → `JSONDecodeError`.
   - `COG-second-brain` (3 файла) и `VPN-Service` (10 файлов): одновременно `docs/tasks` и `.orchestra/tasks`.
     Старые коммиты задач пришли слиянием из origin, пересечений по файлам нет.

## Что сделано

Перед каждой правкой чужого репозитория ставилась метка на текущий HEAD.
`stash drop`, `reset --hard` и force-push не использовались.

**Worktree воркеров (22 шт.).** Использовался драйвер `.orchestra/tasks/V-634/migrate_worktrees.py`. На каждое дерево:
сначала тег `preserve/v634-<имя>`. Неотслеживаемые файлы под `docs/` на время переносились в `/mnt/data/tmp/v634-park`,
чтобы они не попали в коммит. Затем вызывалась каноническая `migrate_project_layout(_allow_dirty=True)`:
`git mv` плюс коммит «Orchestra: migrate project state to .orchestra». Отложенные файлы возвращались по
новому пути, и статус до/после сравнивался с учётом переименований.
Результат по всем деревьям: `dirty_preserved=true`. Diff к тегу содержит только R100-переименования, `.gitignore`
(`!.orchestra/**`) и `layout.json`. Одно исключение: 13 файлов `codex_sessions.json` (id сессий Codex, секретов нет),
раньше скрытых через `.git/info/exclude`, стали отслеживаемыми, потому что `!.orchestra/**` сильнее exclude.
Список: dev-lead, victoria-worker, photo-regen, feat-victor-orchestra, feat-kesha-remote
(его неотслеживаемая `docs/tasks/14/` осталась неотслеживаемой уже как `.orchestra/tasks/14/`), vanilla-frontend,
mobile-os-strategy, sensar-roadmap, mobile-os-brief, audit-both-projects, sensar-client-offer,
sensar-concrete-roadmap, sensar-product-platform, upgrade-claude5, research-codex-harness,
feat-job-hunt, bizdev, infra, ent, sales, burial-import. Тем же способом, с тегом
`preserve/v634-base-*`, переведены базовые `orchestra-enterprise` (`a77372b8`) и `seedon/infra` (`06574d76`).
Для burial-import сначала заново создан worktree его существующей ветки (`bcce7bb`) через `git worktree add`.

**Роль.** `sessions.role` для gamedesign-researcher: `researcher` → `full-cycle` (одна строка, БД забэкаплена ранее).

**Базовые чекауты.** Во всех случаях сначала тег `preserve/v634-pre-repair`.
- Parsing, stargate-tactics: оба журнала (`.git/orchestra-layout-preserve.json` и
  `.orchestra/.layout-migration.json`) перенесены, не удалены, в `/mnt/data/tmp/v634/parked/<repo>/`.
  Stash закреплён ссылкой `refs/rescue/v634-layout-preserve-stash` и остался `stash@{0}`.
  **В рабочее дерево stash не применялся:** HEAD ушёл на 3 коммита, среди них чистка KB,
  а stash содержит старые kb records и секреты (CREDENTIALS.md). Это решение владельца, см. ниже.
- TradingCryptoBot: пустой журнал перенесён туда же. Грязное состояние (1 M + 3 untracked) не менялось.
- COG-second-brain (`251c1fb`), VPN-Service (`ebe1d96`): `git mv docs/tasks/* → .orchestra/tasks/*`.

**Код платформы** (ветка `task-V-634/laptop-order`, коммит `7aef93a6`; на ноутбук применён как `417610bb`
поверх тега `preserve/v634-pre-patch`):
- `app/catalog_migration_v621.py`: если `include_scopes` уже есть и ни один scope не сдвинулся, функция возвращает
  `state=pending` без бэкапа, записи и коммита.
- `app/orchestra_layout.py` `migrate_registered_projects`: scope, которого нет на диске, получает `status=absent`
  вместо `ORCHESTRA_LAYOUT_GIT_ERROR`.
- Тесты `test_a_scope_that_stays_skipped_leaves_no_trace_on_the_next_start` и
  `test_fleet_skips_a_scope_that_is_not_on_this_machine`. На старом коде оба красные (проверено откатом
  `app/`), с фиксом зелёные. В двух прежних fleet-тестах добавлен `mkdir`: раньше они передавали
  несуществующие пути, и это было случайностью, а не предметом проверки.
  Прогон: `uv run --frozen python -m pytest tests/test_catalog_migration_v621.py tests/test_orchestra_layout_fleet_430.py
  tests/test_project_catalog_v621.py tests/test_orchestra_layout_430.py tests/test_orchestra_layout_repair_base_v611.py -q`
  → 39 passed (импорт `app` из этого worktree).

**Модели.** 18 сессий на `claude-opus-5[1m]` переведены через `POST /api/sessions/<name>/change-model`.
Все 18 ответили `200`, `history_transfer.mode=native_in_place`, `native_session_reset=false`.

## Чем проверено

- До рестарта: симуляция `load_worker_memory` по всем 70 не-архивным сессиям дала 0 ошибок.
  `require_project_layout` по всем scope из `tm_projects` дал ok или absent (absent — только пути VPS).
- Рестарт `POST /api/restart` в 17:38:24 (running не было; `cut_names=[]`). После него:
  в журнале нет ни `layout migration failed`, ни `Failed to resume`; 66 строк `Resumed`, 75 сессий `idle`,
  `broken` нет. HEAD остался `417610bb` (новых коммитов нет), бэкапов `projects-pre-v621-*` по-прежнему 4.
  Stash в Parsing и stargate на месте, нового stash стартовая миграция не создала.
- Осталось в журнале: 9 предупреждений `V-621: scope '...' пропущен … без каталога на диске`.
  Это не ошибки раскладки, а честное «не доедет». Их источник — пути VPS в каталоге ноутбука (см. развилку).

## Та же проблема на VPS?

- Старая раскладка у worktree: **сейчас нет.** Проверены 58 не-архивных worktree VPS, ни одного
  со старой раскладкой. Механизм тот же: воркер, чья ветка создана до миграции своей базы, упадёт так же.
- Лишний коммит V-621: код тот же. На VPS после старта 05:36 пропущен только `/opt/cog-second-brain`
  (тогда был грязный). Сейчас у него есть свой `projects.yaml`, поэтому следующий рестарт VPS
  подхватит его как `already` одним законным коммитом, дальше коммитов не будет даже без фикса.
  Фикс нужен на случай любого надолго пропущенного scope.
- Ошибки раскладки на VPS в журнале старта 05:36 (не чинил, VPS вне задачи):
  `dnd-game-master` — `ORCHESTRA_LAYOUT_PARTIAL` (смесь old/new: kb, tasks, workers);
  `scope:/opt/cog-second-brain` — тот же застрявший preserve-stash (`fb3d4dac…`), что Parsing/stargate на ноутбуке.

## Нужны решения владельца

1. **Развилка: как worktree переживают смену раскладки.** Варианты с ценой:
   (a) Как сейчас, чинить руками при появлении. Кода 0, но каждый старый воркер падает до ручной миграции.
   (b) При резюме или auto-switch воркера мигрировать его worktree на месте тем же `migrate_project_layout`.
   Около 30 строк и тесты. Риск: платформа сама коммитит в ветку воркера, а грязные деревья требуют
   preserve-пути, у которого история потерь (V-625, V-629).
   (c) Не мигрировать ветку, а читать память воркера из базового чекаута. Мало кода, но это read-fallback,
   который `orchestra_layout.py` прямо запрещает, а задачи в ветке останутся в `docs/`.
   Рекомендую (b), только для чистых деревьев; грязные — громкая ошибка, как сейчас.
2. **Каталог ноутбука держит пути VPS.** Ноутбук резолвит теги `orchestra/seedon/…` через scope VPS.
   Правильный путь — отдельный каталог на машину, или scope без абсолютного пути. Это решение о формате каталога, я его не трогал.
3. **Stash Parsing `c621720b` и stargate `36cbab6c`**: применить в рабочее дерево или оставить как архив.
   В V-625 они уже выгружены (`laptop-stash/*`, bundle с секретами на VPS).
4. У `research-codex-harness`, `upgrade-claude5`, `feat-job-hunt` и других в ветках теперь есть коммит
   миграции. При мерже в базу (где та же миграция уже сделана) переименования совпадут и конфликтов не дадут.
   Исключение: где в базе уже что-то лежит по тем же путям, возможен обычный content-конфликт.
