# Готовые строки для `.orchestra/kb/data-locality.md`

Я не владею `.orchestra/kb/` (мои каталоги — `.orchestra/tasks/514/` и
`.orchestra/workers/audit-layout-fallout.md`), поэтому дописываю сюда, а не туда.
Строки готовы к вставке дословно.

## В раздел `## Established`

- `fact:layout-migration-leaves-code-references` — Миграция `docs/` → `.orchestra/`
  переименовывает файлы и НЕ переписывает ссылки внутри них: в `app/orchestra_layout.py:25-27`
  старые корни объявлены только источниками переименования, кода правки содержимого в модуле нет.
  Из 8 мигрированных корней исполняемый код со ссылками на исчезнувшие пути остался в 4
  (`orchestra` 98 строк, `kesha-tg-bot` 14, `kesha-bot` 14, `katya-work` 10), а реально красных
  файлов — 3, все в `katya-work` · искать: `docs/tasks`, `migrate_orchestra_layout`,
  `LEGACY_PATH_FIXTURE`, `generate-master-registry.py`, «старые пути после переезда»,
  «broken docs path after layout migration» · evidence:
  `.orchestra/tasks/514/raw/final-counts-and-markers.txt`,
  `.orchestra/tasks/514/raw/run-katya-generate-master-registry.txt`
  (`FileNotFoundError: ... /home/kesha/katya-work/docs/tasks/4/evidence/master-manifest.json`) ·
  2026-09-05, #514
- `fact:check-orchestra-paths-guard-is-single-repo-and-crashing` —
  `scripts/check_orchestra_paths.py` — единственный сторож старых путей, он существует только в
  репозитории Orchestra (отсутствует во всех 7 остальных мигрированных корнях) и сейчас не
  печатает ни одной цифры: `main()` (строки 244-246) вычисляет
  `{**classify_old_paths(root), **verify_historical_bindings(root)}`, второй вызов падает
  `ValueError: not enough values to unpack (expected 3, got 2)` на строке 211. Правило
  классификации `occurrence_class` (строки 93-106) безусловно относит любой путь под `tests/` к
  `negative`, а под `.orchestra/` — к `historical`, поэтому живой старый путь в этих деревьях им
  не обнаружим по построению · искать: `check_orchestra_paths.py`, `occurrence_class`,
  `verify_historical_bindings`, `LEGACY_PATH_FIXTURE`, «сторож старых путей» ·
  evidence: `.orchestra/tasks/514/raw/run-orchestra-script-check_orchestra_paths.txt`,
  `.orchestra/tasks/514/raw/run-classify_old_paths-orchestra.txt`
  (`live_old_path_occurrences=0`, `historical_old_path_occurrences=82470`) · 2026-09-05, #514
- `fact:layout430-receipt-commits-absent-from-object-store` — Три теста
  `tests/test_orchestra_layout_430.py` (`test_t3_*`, `test_t4_*`, `test_t5_*`) красные и в главном
  чекауте, и в worktree, но не из-за путей: коммиты квитанций #430 `1f80bb50…`, `e748168c…`,
  `f157420676…` отсутствуют в объектном хранилище (`git cat-file -t` → `fatal: git cat-file: could
  not get object info` на все три), падение печатает `fatal: not a tree object` ·
  искать: `test_orchestra_layout_430`, `not a tree object`, `move-receipt.json`,
  `verify_historical_bindings` · evidence:
  `.orchestra/tasks/514/raw/run-orchestra-layout430-MAIN-checkout.txt`,
  `.orchestra/tasks/514/raw/orchestra-missing-objects.txt` · 2026-09-05, #514

## В раздел `## Отвергнуто`

- «В `VPN-Service` два файла держат старые пути и блокируют мерж / молча красные с 03.09
  (`tests/test_task2_pilot.py:111`, `tests/test_task11_ops.py:565`)» · мандатный `rg` по
  репозиторию даёт 0 строк; литерала `docs/tasks/2/client-matrix.html` нет ни в одной ветке,
  починка уехала в `master` сквошем `107957b` из `9fbf4cf` «#2: align test gate with orchestra
  layout»; `docs/tasks/11/report.md` жив только на 5 отставших ветках, и там тест тоже ЗЕЛЁНЫЙ
  (`6 passed`), потому что литерал ищется подстрокой в runbook той же ветки ·
  `.orchestra/tasks/514/raw/vpn-service-premise-forensics.txt`,
  `.orchestra/tasks/514/raw/run-vpn-master-task11-task2.txt`,
  `.orchestra/tasks/514/raw/run-vpn-worktree-fix-onboarding-task11.txt` · 2026-09-05, #514

## В раздел `## Пробелы`

- Литералы `docs/archive` и `docs/artifacts` в мандатном правиле поиска #514 отсутствовали, хотя
  `check_orchestra_paths.py` считает `docs/archive` наравне с прочими (`DOC_LITERALS`, строка 18),
  а приёмочная команда задачи #463 ссылается на `docs/artifacts/` · правило поиска задал заказчик ·
  2026-09-05, #514
- 12 строк таблицы #514 остались `UNVERIFIED`: 8 файлов `/opt/kesha-bot` (`No module named pytest`),
  `scripts/verify_orchestra_move.py` (требует `--root/--before-ref/--after-ref`), три файла
  `katya-work`, запуск которых пишет в чужой репозиторий · запрет на правки в чужих репозиториях ·
  2026-09-05, #514
- Не проверено, красен ли хоть один worktree воркера: 35 из 41 живых worktree содержат совпадения,
  прогонялся только `tests/test_task11_ops.py` в `fix-onboarding-clients` ·
  `.orchestra/tasks/514/raw/worktrees-hit-counts.txt` · 2026-09-05, #514

## В раздел `## Источники`

- `.orchestra/tasks/514/research.md` — кросс-проектный аудит ссылок на старые пути после переезда
  раскладки: список scope из живой системы, таблица по файлам с классами по факту прогона,
  опровержение исходной посылки про VPN-Service.
