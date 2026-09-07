# #514 — Фаза 1: аудит ссылок на старые пути после переезда `docs/` → `.orchestra/`

Вопрос: в каких ещё проектах миграция 03.09 оставила ИСПОЛНЯЕМЫЙ код со ссылками на
несуществующие пути, и что из этого реально красное, а что упоминание.

Сырьё — `.orchestra/tasks/514/raw/`. Каждая команда писалась в файл через `> ... 2>&1`;
в таблице стоит имя файла, а не пересказ вывода.

## Какие scope проверены

Список брался из живой системы двумя независимыми источниками, не из формулировки задания.

- `tm_projects.scope` (read-only копия `data/orchestra.db`, снята `sqlite3.Connection.backup`) —
  `raw/scopes-tm-projects.txt`. Владелец списка в коде: `app/orchestra_layout.py:1142-1150`
  (`_registered_project_roots`) читает именно `tm_projects.scope`.
- `distinct scope from sessions` — `raw/scopes-from-sessions.txt`.
- Физический признак переезда — `.orchestra/layout.json` в корне: `raw/layout-json-scan.txt`.

Мигрированных корней **8** (по `layout.json`), из них 6 совпадают с `tm_projects.scope`; ещё два —
`/opt/cog-second-brain` и `/opt/kesha-bot` — в `tm_projects` отсутствуют, но `layout.json` у них есть.

| scope | источник | проверен | старых путей всего | вне `.orchestra/tasks/` |
|---|---|---|---|---|
| `/home/kesha/orchestra` | tm_projects + layout.json | да | 353 | 98 |
| `/home/kesha/katya-work` | tm_projects + layout.json | да | 19 | 10 |
| `/home/kesha/projects/kesha-tg-bot` | tm_projects + layout.json | да | 22 | 14 |
| `/home/kesha/projects/seedon` | tm_projects + layout.json | да | 33 | 0 |
| `/home/kesha/projects/VPN-Service` | tm_projects + layout.json | да | 0 | 0 |
| `/home/kesha/projects/dnd-game-master` | tm_projects + layout.json | да | 0 | 0 |
| `/opt/cog-second-brain` | только layout.json | да | 13 | 0 |
| `/opt/kesha-bot` | только layout.json | да | 22 | 14 |

Числа — `raw/final-counts-and-markers.txt`, выводы команд — `raw/rg-<имя>.txt`.

**Пропущены и почему:**

- `/home/kesha/projects/University` — есть в `sessions` (1 сессия), но `layout.json` нет и `docs/`
  на месте, то есть репозиторий НЕ мигрирован; мандатный `rg` дал 0 строк (`raw/rg-University.txt`).
- `/home/kesha/projects/ai-table-mvp` — `layout.json` нет, `docs/` на месте, репозиторий не мигрирован
  (`raw/skipped-and-leftovers.txt`). В `tm_projects` и в `sessions` не значится; попал в поле зрения
  только через каталог worktree.
- `/home/kesha/projects/seedon-site` — каталога не существует, есть только worktree
  (`raw/skipped-and-leftovers.txt`).
- Строки `tm_projects` с пустым `scope` (`Orchestra`, `Seedon`, `orchestra`) — проверять нечего.
- Worktree воркеров (`/home/kesha/orchestra/worktrees/**`) как отдельные repo в таблицу не вносил:
  это ветки, а не состояние проекта. Счётчики по ним сняты — `raw/worktrees-hit-counts.txt`.

## Таблица

Одна строка на файл. `.md`, хроника и артефакты прошедших задач в `.orchestra/tasks/<id>/**`
исключены по правилу задания (сколько их — в колонке «вне `.orchestra/tasks/`» выше).
Позиция литерала (комментарий / докстринг / строковый литерал) для каждой строки —
`raw/token-position.tsv`, считана `tokenize` без импорта и запуска файла.

| repo | file:line | старый путь в коде | существует сейчас | аналог в `.orchestra/` | класс | доказательство |
|---|---|---|---|---|---|---|
| katya-work | `pipeline/scripts/generate-master-registry.py:18` (также 19, 20) | `docs/tasks/4/evidence/master-manifest.json` | нет | да | RED_FROM_PATH | `raw/run-katya-generate-master-registry.txt` |
| katya-work | `artifacts/task-4/tests/validate_t1_contract.py:23` | `docs/tasks/4/evidence/master-manifest.json` | нет | да | RED_FROM_PATH | `raw/run-katya-validate_t1_contract.txt` |
| katya-work | `artifacts/task-4/tests/validate_t3_catalog.py:21` | `docs/tasks/4/evidence/analyze_pptx_overflow.py` | нет | да | RED_FROM_PATH | `raw/run-katya-validate_t3_catalog.txt` |
| katya-work | `artifacts/task-4/tests/validate_t4_lesson9.py:38` | `docs/tasks/4/evidence/analyze_pptx_overflow.py` | нет | да | UNVERIFIED | `raw/run-katya-validate_t4_lesson9.txt` |
| katya-work | `artifacts/task-6/lesson-01/validate.py:6` (также 64, 92) | `docs/tasks/6/plan.md`, `docs/tasks/6/research.md` | нет | да | UNVERIFIED | `raw/katya-task6-inspect.txt`, `raw/token-position.tsv` |
| katya-work | `artifacts/task-9-avito/avito_ads.py:176` | `docs/tasks/9/consent.md` | нет | да | UNVERIFIED | `raw/katya-remaining-inspect.txt`, `raw/token-position.tsv` |
| orchestra | `tests/test_orchestra_layout_430.py:32` (19 строк) | `docs/kb`, `docs/tasks`, `docs/workers` | нет | да | MENTION_ONLY | `raw/run-orchestra-layout-tests.txt`, `raw/run-orchestra-layout430-MAIN-checkout.txt` |
| orchestra | `tests/test_owned_dirs_migration_473.py:111` (37 строк) | `docs/tasks/88`, `docs/tasks/404`, `docs/tasks/999` | нет | да (88, 404) / нет (999) | MENTION_ONLY | `raw/run-orchestra-layout-tests.txt` |
| orchestra | `tests/test_orchestra_layout_dirty_430.py:34` (17 строк) | `docs/kb`, `docs/tasks`, `docs/workers` | нет | да | MENTION_ONLY | `raw/run-orchestra-layout-tests.txt` |
| orchestra | `tests/test_orchestra_layout_compat_430.py:27` (6 строк) | `docs/kb`, `docs/workers` | нет | да | MENTION_ONLY | `raw/run-orchestra-layout-tests.txt` |
| orchestra | `tests/test_orchestra_layout_recovery_430.py:26` (4 строки) | `docs/kb`, `docs/kb/fact.md` | нет | да (`docs/kb`) / нет (`fact.md`) | MENTION_ONLY | `raw/run-orchestra-layout-tests.txt` |
| orchestra | `app/orchestra_layout.py:25` (также 26, 27, 340, 769) | `docs/kb`, `docs/tasks`, `docs/workers` | нет | да | MENTION_ONLY | `raw/run-orchestra-layout-tests.txt`, `raw/run-classify_old_paths-orchestra.txt` |
| orchestra | `app/ia/cutover.py:33` (также 34, 35, 38) | `docs/kb/README.md`, `docs/tasks/<task-id>/research.md` | нет | да (`README.md`) / нет (шаблоны с `<id>`) | MENTION_ONLY | `raw/run-orchestra-cutover-secretscan-wfpilot-tests.txt` |
| orchestra | `scripts/secret_scan.py:18` | `docs/tasks/sol-efficiency/calls_strict.tsv` | нет | нет | MENTION_ONLY | `raw/run-orchestra-cutover-secretscan-wfpilot-tests.txt` |
| orchestra | `scripts/wf_pilot.py:23` | `docs/tasks/` | нет | да | MENTION_ONLY | `raw/run-orchestra-cutover-secretscan-wfpilot-tests.txt` |
| orchestra | `scripts/check_orchestra_paths.py:19` | `docs/kb`, `docs/tasks`, `docs/workers` | нет | да | MENTION_ONLY | `raw/run-orchestra-script-check_orchestra_paths.txt` |
| orchestra | `scripts/verify_orchestra_move.py:15` (также 16, 17) | `docs/kb/`, `docs/tasks/`, `docs/workers/` | нет | да | UNVERIFIED | `raw/run-orchestra-script-verify_orchestra_move.txt` |
| kesha-tg-bot | `runtime_protocol.py:3` | `docs/tasks/16/` | нет | да | MENTION_ONLY | `raw/run-kesha-tg-bot-tests.txt`, `raw/kesha-bot-identity-and-env.txt` |
| kesha-tg-bot | `codex_session.py:11` (также 370, 1095) | `docs/tasks/16/spikes/turn_probe_events.jsonl` | нет | да | MENTION_ONLY | `raw/run-kesha-tg-bot-tests.txt` |
| kesha-tg-bot | `compact.py:159` | `docs/tasks/21` | нет | да | MENTION_ONLY | `raw/run-kesha-tg-bot-tests.txt` |
| kesha-tg-bot | `claude_session.py:88` (также 700) | `docs/tasks/20`, `docs/tasks/20/spikes/ctxleak.py` | нет | да | MENTION_ONLY | `raw/run-kesha-tg-bot-tests.txt` |
| kesha-tg-bot | `rag.py:5` | `docs/tasks/rag-memory/plan.md` | нет | да | MENTION_ONLY | `raw/kesha-bot-identity-and-env.txt` (import-проба), `raw/token-position.tsv` |
| kesha-tg-bot | `tests/test_codex_session.py:4` (также 180, 1029) | `docs/tasks/16/spikes/*` | нет | да (2 из 3) | MENTION_ONLY | `raw/run-kesha-tg-bot-tests.txt` |
| kesha-tg-bot | `tests/test_compact_prompt.py:288` (также 331) | `docs/tasks/21` | нет | да | MENTION_ONLY | `raw/run-kesha-tg-bot-tests.txt` |
| kesha-tg-bot | `tests/test_runtime_limits.py:495` | `docs/tasks/25` | нет | да | MENTION_ONLY | `raw/run-kesha-tg-bot-tests.txt` |
| kesha-bot | `runtime_protocol.py:3` | `docs/tasks/16/` | нет | да | UNVERIFIED | `raw/kesha-bot-identity-and-env.txt` |
| kesha-bot | `codex_session.py:11` (также 370, 1095) | `docs/tasks/16/spikes/turn_probe_events.jsonl` | нет | да | UNVERIFIED | `raw/kesha-bot-identity-and-env.txt` |
| kesha-bot | `compact.py:159` | `docs/tasks/21` | нет | да | UNVERIFIED | `raw/kesha-bot-identity-and-env.txt` |
| kesha-bot | `claude_session.py:88` (также 700) | `docs/tasks/20`, `docs/tasks/20/spikes/ctxleak.py` | нет | да | UNVERIFIED | `raw/kesha-bot-identity-and-env.txt` |
| kesha-bot | `rag.py:5` | `docs/tasks/rag-memory/plan.md` | нет | да | UNVERIFIED | `raw/kesha-bot-identity-and-env.txt` |
| kesha-bot | `tests/test_codex_session.py:4` (также 180, 1029) | `docs/tasks/16/spikes/*` | нет | да (2 из 3) | UNVERIFIED | `raw/kesha-bot-identity-and-env.txt` |
| kesha-bot | `tests/test_compact_prompt.py:288` (также 331) | `docs/tasks/21` | нет | да | UNVERIFIED | `raw/kesha-bot-identity-and-env.txt` |
| kesha-bot | `tests/test_runtime_limits.py:495` | `docs/tasks/25` | нет | да | UNVERIFIED | `raw/kesha-bot-identity-and-env.txt` |

Репозитории `seedon`, `cog-second-brain`, `VPN-Service`, `dnd-game-master` строк в таблице не дают:
у первых двух все совпадения лежат в `.orchestra/tasks/<id>/**` (0 вне), у вторых двух совпадений
нет вовсе.

### Дословные причины у каждого UNVERIFIED

- `katya-work artifacts/task-4/tests/validate_t4_lesson9.py:38` — прогон дошёл только до строки 131 и
  встал на другой причине: `AssertionError: T4 lesson JSON is not contract-valid: E_REGISTRY_DIGEST
  cannot read source master` (отсутствует `/home/kesha/orchestra/data/uploads/Мастер-макет.key`,
  `raw/katya-prereqs.txt`). Строка 210, где путь потребляется в `run([... PPTX_OVERFLOW ...])`,
  не выполнялась.
- `katya-work artifacts/task-6/lesson-01/validate.py` — не запускал: запуск пишет в чужой репозиторий,
  `script = ROOT / ".validate_node.js"` и `script.write_text(NODE, encoding="utf-8")`
  (строки 160-161), а задание запрещает в чужих репозиториях любые правки.
- `katya-work artifacts/task-9-avito/avito_ads.py` — не запускал: запуск пишет в чужой репозиторий,
  `with open(src, "w", encoding="utf-8") as f:` (строка 881).
- `orchestra scripts/verify_orchestra_move.py` — прогон без аргументов прекращается на разборе
  аргументов: `verify_orchestra_move.py: error: the following arguments are required: --root,
  --before-ref, --after-ref`, RC=2. Строки 15-17 при этом не читались.
- `kesha-bot` (все 8 файлов) — `/opt/kesha-bot/.venv/bin/python: No module named pytest` и
  `ModuleNotFoundError: No module named 'pytest_timeout'`; доустанавливать по заданию нельзя.

## Факты, не поместившиеся в колонки

1. **Оба названных в задании случая в `/home/kesha/projects/VPN-Service` в рабочем дереве не
   воспроизводятся.** Мандатный `rg` по репозиторию даёт 0 строк (`raw/rg-VPN-Service.txt`).
   - `tests/test_task2_pilot.py` на `master` содержит `.orchestra/tasks/2/client-matrix.html`
     (строка 115). Литерала `docs/tasks/2/client-matrix.html` нет НИ В ОДНОЙ ветке репозитория:
     `git grep` по всем `refs/heads` не находит его (`raw/vpn-service-worktrees-and-history.txt`).
     Починка сделана коммитом `9fbf4cf` «#2: align test gate with orchestra layout» на ветке
     `task-2/fix-tspu-ingress` и уехала в `master` сквошем `107957b`
     (`raw/vpn-service-premise-forensics.txt`).
   - `tests/test_task11_ops.py:565` на `master` содержит `.orchestra/tasks/11/report.md`.
     Старый литерал жив на пяти ветках и в одном живом worktree
     (`worktrees/home-kesha-projects-vpn-service/fix-onboarding-clients`, ветка
     `task-5/fix-onboarding-clients`, HEAD `371b833`).
   - Красным при прогоне не оказался ни один из двух, ни в `master`, ни в отставшем worktree:
     `8 passed, 1 xfailed` (`raw/run-vpn-master-task11-task2.txt`) и `6 passed`
     (`raw/run-vpn-worktree-fix-onboarding-task11.txt`). В отставшем worktree тест зелёный потому,
     что старый литерал ищется как подстрока в runbook-документе той же ветки, где он тоже старый
     (`raw/vpn-task11-test-body.txt`). Рабочие деревья обоих репозиториев после прогонов чистые.
2. **`tests/test_orchestra_layout_430.py` красный, но не от пути.** Три теста падают
   (`test_t3_repository_move_has_content_receipt_and_no_old_roots`,
   `test_t4_all_fleet_receipts_precede_global_prompt_activation`,
   `test_t5_classified_path_audit_is_clean_and_historical_evidence_resolves`) — одинаково и в моём
   worktree, и в главном чекауте `/home/kesha/orchestra`
   (`raw/run-orchestra-layout430-MAIN-checkout.txt`). В тексте падения ни одного `docs/`-пути нет:
   `fatal: not a tree object`, `fatal: Not a valid commit name
   e748168c6eea8924999e575d9c09a88a33168d2e`. Коммиты, на которые ссылаются квитанции #430
   (`1f80bb50…`, `e748168c…`, `f157420676…`), в объектном хранилище репозитория ОТСУТСТВУЮТ —
   `git cat-file -t` отвечает `fatal: git cat-file: could not get object info` на все три
   (`raw/orchestra-missing-objects.txt`). `move-receipt.json` и `release-receipt.json` в моём
   worktree байт-в-байт совпадают с главным чекаутом.
3. **У Orchestra уже есть собственный классификатор этих путей, и сейчас он не работает как сторож.**
   `scripts/check_orchestra_paths.py` считает `live/historical/negative/deferred` и возвращает 0/1,
   но `main()` собирает словарь как `{**classify_old_paths(root), **verify_historical_bindings(root)}`
   (строки 244-246), и второй вызов падает `ValueError: not enough values to unpack (expected 3,
   got 2)` в `verify_historical_bindings` (строка 211) — на тех же отсутствующих объектах. Поэтому
   ни одна цифра классификации не печатается вовсе (`raw/run-orchestra-script-check_orchestra_paths.txt`).
   Вызванная напрямую, классификация даёт `live_old_path_occurrences=0`,
   `unclassified_old_path_occurrences=0`, `historical_old_path_occurrences=82470`,
   `negative_guard_occurrences=131` (`raw/run-classify_old_paths-orchestra.txt`).
4. **Правило классификации этого сторожа устроено так, что живой старый путь внутри `tests/` или
   внутри `.orchestra/` не может быть им обнаружен по построению.** `occurrence_class`
   (`scripts/check_orchestra_paths.py:93-106`): `relative.startswith(".orchestra/")` → `historical`,
   `relative.startswith("tests/")` → `negative`, безусловно, без маркера в файле. Маркеры
   `LEGACY_PATH_FIXTURE`/`LEGACY_PATH_HISTORY` физически стоят в 8 файлах из 11 живых
   (`raw/final-counts-and-markers.txt`, `raw/run-luna-finding-verification.txt`); три теста
   `*_dirty_430`, `*_compat_430`, `*_recovery_430` маркера не имеют и классифицируются `negative`
   только по префиксу `tests/`.
5. **Сторож существует ровно в одном репозитории.** `scripts/check_orchestra_paths.py` отсутствует
   во всех остальных семи проверенных корнях (`raw/skipped-and-leftovers.txt`).
6. **Три зарегистрированные приёмочные команды ссылаются на старые пути**
   (`raw/acceptance-commands-old-paths.txt`), все три у задач в статусе `done`:
   `#383 test -s docs/tasks/288/research.md`, `#384 test -s docs/tasks/289/research.md`,
   `#463 python3 -c "... Path('docs/artifacts/quota-runway-controller.html') ..."`.
   Всего задач с непустым `acceptance_command` — 22.
7. **Каталог `docs/` после переезда остался во всех восьми мигрированных корнях**
   (`raw/skipped-and-leftovers.txt`): пустой в `katya-work` (0 записей), непустой в остальных
   (orchestra 5, kesha-tg-bot 5, seedon 20, cog-second-brain 4, kesha-bot 5, VPN-Service 3,
   dnd-game-master 11).
8. **Миграция переносит файлы и не переписывает ссылки внутри них.** В `app/orchestra_layout.py`
   старые корни объявлены только как источники переименования
   (`app/orchestra_layout.py:25-27`), кода, правящего содержимое файлов, в модуле нет.
9. **Совпадений в исполняемом коде за пределами `.orchestra/tasks/` в `seedon` и `cog-second-brain`
   ноль**, при 33 и 13 совпадениях внутри артефактов задач соответственно
   (`raw/final-counts-and-markers.txt`).
10. **Файлы `/opt/kesha-bot` и `/home/kesha/projects/kesha-tg-bot` байт-в-байт одинаковы** по всем
    восьми файлам таблицы (`raw/kesha-bot-identity-and-env.txt`).
11. **В worktree воркеров старые пути живут отдельно от состояния проектов**: 35 живых worktree из 41
    содержат хотя бы одно совпадение, максимум 163 файла (`raw/worktrees-hit-counts.txt`).
    Хук миграции worktree не трогает — это заявлено в `CLAUDE.md` и подтверждается тем, что старый
    литерал `docs/tasks/11/report.md` жив в worktree `fix-onboarding-clients` при отсутствии его
    в `master`.

## Что осталось непроверенным

- Классы `UNVERIFIED` выше — 12 строк таблицы (8 файлов `kesha-bot` + `verify_orchestra_move.py` +
  3 файла `katya-work`; причины дословно приведены).
- Worktree воркеров как таковые: счётчики сняты, ни один файл в них не прогонялся, кроме
  `tests/test_task11_ops.py` в `fix-onboarding-clients`.
- Литералы `docs/archive` и `docs/artifacts` мандатным `rg` не искались — в правиле поиска их нет,
  хотя `check_orchestra_paths.py` считает `docs/archive` наравне с остальными
  (`DOC_LITERALS`, строка 18), а приёмочная команда #463 ссылается на `docs/artifacts/`.
- Репозитории `ai-table-mvp` и `University` не мигрированы, поэтому их `docs/`-ссылки к данному
  вопросу не относятся; отдельно они не разбирались.

## Ревью

Маршрут по канону: предмет — проза/извлечение фактов → сперва механическая проверка полноты,
затем один Luna-проход. Артефакт ревьюера — `review-research-luna.md`, раунд один.

Вердикт засчитан: ревьюер привёл дословную строку из отчёта, которой не было в запросе —
«У Orchestra уже есть собственный классификатор этих путей, и сейчас он не работает как сторож.»
(`raw/run-luna-finding-verification.txt`, `reviewer_quote_hits=1`). Вердикт `NEEDS_REVISION`,
блокирующих находок нет, две `suggestion` — обе про числа, обе проверены по сырью и приняты:

- «маркеры стоят в 7 файлах из 11» → в сырье 8 различных файлов
  (`distinct_marker_files=8`). Исправлено на 8.
- «12 строк `UNVERIFIED` = 6 файлов `kesha-bot` + …» → строк `kesha-bot` в таблице 8
  (`kesha_bot_table_rows=8`), 8+1+3=12. Исправлено на 8.

Отклонённых находок нет. Второй раунд не открывался: правки прозаические и не оспаривают ни одной
находки ревьюера.

## Как воспроизвести

```
rg -n -F --glob '*.py' --glob '*.sh' --glob '*.js' \
  -e 'docs/tasks' -e 'docs/kb' -e 'docs/workers' -e 'docs/pipelines' <repo>
```

Существование старого пути и его аналога в `.orchestra/` пересчитывается
`python3 .orchestra/tasks/514/path_status.py` (вход — `raw/rg-*.txt`, выход —
`raw/path-status.tsv`). Позиция литерала в исходнике — `python3 .orchestra/tasks/514/token_position.py`
(выход — `raw/token-position.tsv`); оба скрипта только читают.

Копия `data/orchestra.db` снималась `sqlite3.Connection.backup` в файл `orchestra-ro.db` внутри
`raw/` и УДАЛЕНА после снятия выборок (1 019 297 792 Б); имя внесено в `raw/.gitignore`, чтобы
гигабайтный блоб не попадал в историю. Выборки из неё сохранены отдельными файлами
(`raw/scopes-tm-projects.txt`, `raw/scopes-from-sessions.txt`, `raw/db-tables.txt`,
`raw/acceptance-commands-old-paths.txt`), сама копия воспроизводится одной командой.

Полнота отчёта проверяется механически: `python3 .orchestra/tasks/514/completeness_check.py`
(каждый упомянутый артефакт существует; каждая строка таблицы подтверждена соответствующим
`raw/rg-*.txt`; числа в таблице scope совпадают с `raw/final-counts-and-markers.txt`).
Вывод — `raw/run-completeness-check.txt`.
