# #474 — пять дефектов пути мержа

Два по исходному заданию (потолок на один тест, привязка ревью к хешу цели), три раскрыты
расширением задачи и раундом 1 Luna: исключение на неразрешимом ref, покрытие untracked
продовых путей, молча отключённая приёмочная команда.

## Дефект 1 — у гейта не было потолка на ОДИН узел

### Что было
`app/merge_test_gate.py::pytest_argv` не передавал `--timeout`, хотя `pytest-timeout>=2.3`
объявлен в `pyproject.toml:39` и стоит в `.venv`. Бюджет существовал только общий:
`BASE_TIMEOUT_SECONDS=180`, `PER_FILE_TIMEOUT_SECONDS=150`, потолок `MAX_TIMEOUT_SECONDS=1200`,
применяется в `run_pytest`. Один зависший узел съедал бюджет всей партии и возвращал
`inconclusive` без имени.

Замер 04.09: мерж #466 простоял 9+ минут на
`test_concurrent_keys_start_exactly_one_executor_and_survive_request_return` (процесс жив,
CPU 1%, состояние `S` — ждал события, переставшего наступать); мержи всего проекта стояли
всё это время.

### Величина потолка: 120 с

Замер собственный, `--durations=0 --durations-min=1.0` по восьми самым тяжёлым файлам
(семь крупнейших по объёму + `tests/test_merge_operations.py`), каждый файл — свой процесс:

| файл | тестов | итог |
|---|---|---|
| tests/test_session.py | 244 | 6.84 с |
| tests/test_frontend.py | 107 | 90.40 с |
| tests/test_tg_bridge.py | 194 | 6.46 с |
| tests/test_manager.py | 171 | 9.38 с |
| tests/test_api.py | 131 | 21.93 с |
| tests/test_workspace.py | 116 | 7.61 с |
| tests/test_mcp_stdio.py | 118 | 5.32 с |
| tests/test_merge_operations.py | 37 | 3.32 с |

**1118 тестов из 3214 (35% сьюта), 3353 записанных фазы.** Самый долгий ОДИН узел —
**14.90 с** (`tests/test_frontend.py::test_dashboard_polling_equivalent_twelve_minutes_before_after`),
дальше 8.87 с и 8.14 с. Дольше 5 с — три узла, дольше 10 с — один.

- 120 с = **восьмикратный запас** к измеренному максимуму. Ошибаться безопаснее в эту сторону:
  ложный красный блокирует мержи всех проектов, проспавший потолок стоит одной партии.
- Пол бюджета партии = `budget_for(1)` = 330 с, то есть потолок **втрое меньше самого
  маленького бюджета**: один висяк физически не может выесть партию, а второй и третий уже
  приносят `FAILED` с именами раньше, чем истечёт общий бюджет. Соотношение закреплено тестом
  `test_per_test_ceiling_is_far_below_the_smallest_batch_budget`.
- Узел, которому законно нужно больше, ставит свой `@pytest.mark.timeout(N)` — маркер сильнее
  флага. В репозитории такие уже есть: `tests/test_native_history_import.py:199` (840 с) и
  `:268` (360 с), оба под `live_probe`, то есть гейтом не гоняются вовсе.

### Метод: `signal`, не `thread`

`thread` печатает стеки и убивает ВЕСЬ процесс через `os._exit` — уносит построчные вердикты
`-vv`, по которым `_partial_progress` вообще отличает «набор красный» от «мы не успели».
`signal` (SIGALRM) поднимает исключение в главном потоке: висящий узел получает свой `FAILED`
с именем, остаток партии продолжает считаться. Главный поток здесь и нужный: `pytest-asyncio`
крутит корутину через `run_until_complete` на нём же, синхронный Playwright ждёт драйвер на
прерываемом чтении.

**Проверено мутацией, а не рассуждением.** С `PER_TEST_TIMEOUT_METHOD = "thread"` тест падает
ровно на строке «остаток партии должен продолжаться»:

```
>       assert "test_after_the_hang PASSED" in result["output"]
E       AssertionError: the rest of the batch must keep running after one node hits the ceiling
E       assert 'test_after_the_hang PASSED' in '…+++++ Timeout +++++…'
```

### Побочный гейт, которого не было
Интерпретатор без `pytest-timeout` отвергает флаг usage-ошибкой ДО сбора: тесты не запускались
вовсе. Общая ветка объявила бы это `exit_nonzero`, то есть «набор красный», и заблокировала
мержи всех проектов на отсутствующем плагине. Теперь это `INCONCLUSIVE / pytest_timeout_unavailable`
(`test_missing_timeout_plugin_is_inconclusive_not_red`).

## Дефект 2 — состоявшееся ревью обнулял ЛЮБОЙ посторонний коммит в main

### Что было
`production_snapshot` считал дайджест как `sha256(SNAPSHOT_VERSION + target_sha + b"\0" + raw)`,
а `coverage_decision` искал квитанцию по паре (`target_sha`, `production_snapshot_sha256`).
В личность снимка входил хеш ЦЕЛИ, хотя проверяемый предмет — продовый дифф.

Замер 04.09 на #472: ревью Luna прошло
(`review-receipt:01435214-5df0-4073-8eaa-6d074fb12240`, status=completed, rc=0, verdict ACK,
coverage_outcome=reviewed). После него в main приехал посторонний коммит `525684a4`, а воркер
дописал коммиты с тестами. Сырой продовый дифф остался БАЙТ-В-БАЙТ тем же — обе команды дают
одинаковые 167 байт:

```
git diff --raw --full-index -z 2268e0fe...2735fcf1 -- app scripts
git diff --raw --full-index -z 525684a4...598a5848 -- app scripts
```

— а дайджест сменился `67cf8c11…` → `f8f83743…`, и мерж был отбит
«production diff has no snapshot-bound review». Пришлось выписывать skip оркестратором.

### Что сделано
Отдельный дайджест ПРЕДМЕТА ревью: `production_diff_sha256 = sha256(DIFF_VERSION + raw)`, без
хеша цели. Своя версия-префикс, потому что оба дайджеста считаются от одного `raw` и не должны
совпадать между собой. Новая колонка `review_receipts.production_diff_sha256`, обычная
аддитивная миграция в `app/db.py::_migrate`; старые квитанции задним числом не переписываются.

Допуск теперь предъявляет одну и ту же гарантию двумя ветками:

```sql
AND (
  (target_sha=? AND production_snapshot_sha256=?)
  OR (production_diff_sha256<>'' AND production_diff_sha256=?)
)
```

Первая ветка — для квитанций, выписанных до этой колонки: без неё они разом перестали бы
засчитываться. Вторая снимает зависимость от постороннего движения main.

### Почему гарантия не ослаблена
`git diff --raw --full-index` несёт статус, режим, путь и blob-SHA ОБЕИХ сторон. Байт-в-байт
равный `raw` означает тождественный продовый дифф: тот же набор путей, те же исходные и те же
результирующие блобы. Любая правка в `app/**`/`scripts/**` меняет blob-SHA → меняет `raw` →
меняет дайджест → квитанция не засчитывается.

Отдельно закрыт край: **пустой `raw` не получает дайджеста вовсе** (пустая строка вместо
`sha256(DIFF_VERSION)`). Такое состояние достижимо — `changed_paths` считает и untracked-файлы,
поэтому бывает «продовый путь есть, а сырой дифф пуст». Константный дайджест здесь совпал бы
с пустой колонкой любой квитанции до #474, и чужое ревью авторизовало бы непросмотренный файл.
Отсюда же явный `<>''` в допуске. Оба края закрыты тестом
`test_empty_production_diff_never_matches_a_legacy_empty_digest`.

## Мутационные проверки — по каждому дефекту отдельно

Протокол один: `cp F F.bak` → мутация → прогон → `mv F.bak F` + `touch F` → счёт маркера.

| # | мутация | маркер ДО / ПОСЛЕ отката | что покраснело |
|---|---|---|---|
| 1 | убран `f"--timeout={ceiling:g}"` из argv | прод-маркер **1 / 1**, мутант-маркер (флаг на месте) **0** под мутацией | `test_hung_node_becomes_a_named_red_not_inconclusive[2.0]`, `test_pytest_argv_carries_the_per_test_ceiling_and_its_method` |
| 2 | `PER_TEST_TIMEOUT_METHOD` = `thread` | прод-маркер (`signal`) **1 / 1**, мутант-маркер (`thread`) **1 / 0** | те же два, причём первый — ровно на «остаток партии продолжается» |
| 3 | допуск возвращён к до-#474 (`AND target_sha=? AND production_snapshot_sha256=?`) | мутант-маркер **1 / 0**, прод-маркер (OR-ветка) **1** после отката | `test_foreign_main_commit_does_not_invalidate_the_reviewed_production_diff`: `satisfied` → `blocked` — дословный симптом #472 |
| 4 | ветка по диффу сделана всегда истинной (`AND ?=?`) | прод-маркер (OR-ветка) **1** после отката, мутант-маркер **0** | `test_one_changed_production_byte_still_revokes_the_receipt`: `blocked` → `satisfied` |

Мутация 3 оставила близнецов-гарантий зелёными, мутация 4 оставила зелёным близнеца-ослабления —
то есть тесты разделяют «ослабили» и «сняли гарантию», а не краснеют оба на любой правке.

Первая попытка мутации 3 была НЕГОДНОЙ (`ProgrammingError`: разошлось число параметров) и все
четыре теста покраснели одинаково — такой прогон ничего не доказывает и не засчитан; повторена
корректно с сохранением числа параметров.

## Прогоны

- `tests/test_merge_operations.py` — 37 passed.
- `tests/test_review_coverage_gate_462.py` — зелёный.
- `tests/test_review_coverage_target_drift_474.py` — 4 passed (новый).
- `tests/test_merge_test_gate.py` — 32 passed, **3 failed**, см. ниже.
- Смежное по квитанциям и схеме: `test_db.py`, `test_review_receipt_{migration,storage,start,terminal,safety,outcome_tool}_436.py`,
  `test_mcp_codex_review.py`, `test_codex_review_artifact.py`, `test_tm.py` — зелёные.
- Полный сьют одним процессом не гонялся (воспроизводимо `RC=137` около 80%).

### Отрицательный контроль на ложную красноту

Главный риск потолка — что он покраснеет на честном тесте под нагрузкой. Проверен прогоном
НАСТОЯЩЕЙ команды гейта (argv взят из `pytest_argv`, не собран руками) по смеси, где живут оба
опасных класса — синхронный браузерный Playwright и `@pytest.mark.asyncio`:

```
… -m pytest -q -vv --timeout=120 --timeout-method=signal -m not live_probe \
  tests/test_frontend.py tests/test_tg_bridge.py tests/test_session.py
RC=0  elapsed=98.7 s
544 passed, 1 skipped in 97.36s
```

Ни одного срабатывания потолка на 545 узлах.

### Краснота пути мержа — расширение задачи, ПОЧИНЕНА

Семь тестов красны и в моей ветке, и в чистом worktree `main` (`bf59a7d3`), множества node id
совпадают ровно:

```
tests/test_merge_test_gate.py::test_red_mapped_test_does_not_reach_merge_executor
tests/test_merge_test_gate.py::test_green_mapped_test_reaches_executor[gate_db0]
tests/test_merge_test_gate.py::test_docs_only_change_skips_gate_and_merges[gate_db0]
tests/test_acceptance.py::test_failing_registered_command_blocks_merge_executor
tests/test_acceptance.py::test_inconclusive_is_not_passed_or_failed
tests/test_acceptance.py::test_existing_invalid_command_blocks_merge_with_repair_guidance
tests/test_acceptance.py::test_passing_command_reaches_executor
```

Причина одна: `tests/test_acceptance.py:79` подменяет `_worker_head` синтетическим
`("task-42/worker", "b"*40)`, а пришедший с #462 `production_snapshot` зовёт этим значением git
и получает `fatal: Invalid symmetric difference expression <sha>...bbbb…`. `ValueError` летит
из `_prepare_admission_snapshot` наружу неперехваченным.

Оркестратор подтвердил красноту независимо (`7 failed, 42 passed` на чистом `main`, боевая база
не тронута: `sessions` 635 до и 635 после) и включил починку в #474. Разобрано ниже.

## Дефект 3 — неразрешимый ref ронял ВЕСЬ путь мержа исключением

`_git_bytes` поднимает `ValueError`, и он летел из `_prepare_admission_snapshot` наружу
неперехваченным. Несуществующий `worker_head` — возможное состояние прода, а не выдумка стенда:
ветку сносят, worktree переезжает, ссылку переписывают. Правильный ответ допуска — определённый
отказ с причиной.

Сделано: `_review_snapshot_unavailable` — один владелец исхода на оба шва
(`production_snapshot` в `_review_coverage_for_snapshot` и `_target_head` в
`_revalidate_review_coverage`; вторая копия того же словаря, стоявшая инлайном, снята).
Исход **fail-closed**: `required=True`, `status="blocked"`, `reason="review_snapshot_unavailable"`,
плюс новое поле `reason_detail` с дословным текстом git — без него отказ неотличим от
«квитанции нет». Поле доехало и в `details` отказа (`_review_coverage_refusal`).

## Дефект 4 — ревью одного продового файла авторизовало ВТОРОЙ, untracked (нашла Luna)

`git diff` untracked-файлов не видит, а `changed_paths` их считает
(`git ls-files --others --exclude-standard`). Значит добавленный ПОСЛЕ ревью untracked
`app/new.py` оставляет ОБА дайджеста прежними, и при той же цели старая квитанция проходила по
target-привязанной ветке. Дефект пришёл с #462, а не с моей правкой (старый дайджест тоже не
менялся), но он снимает ровно ту гарантию, которую #474 обязан удержать.

Проверено по коду, а не по пересказу: `changed_paths` (`app/merge_test_gate.py:164-169`) →
`production_paths` → `required=True`; `production_snapshot` зовёт `git diff --raw … -- app scripts`,
untracked там нет → `raw` тот же → оба дайджеста те же → первая ветка допуска совпадает.

**Уточнение severity — PARTIAL, а не полный ACK.** Луна написала «authorizing unreviewed
production content» в main; конца-в-конец это недостижимо: `execute_merge_session` отказывает на
грязном воркерском дереве (`_clean_worktree_error`, `app/workspace.py:1386`), а
`git status --porcelain` показывает untracked как `??` по умолчанию. То есть дыра реальна в
ЛОГИКЕ допуска, но перекрыта вторым независимым гейтом — «в main не попадёт», при этом решение
допуска остаётся ложным. Закрыто всё равно: цена — одно условие.

Сделано: в допуск добавлено `AND production_paths_json=?`. Условие стоит НАД обеими
дайджест-ветками, потому что дыра была именно в target-привязанной; `production_paths_json`
лежит в квитанциях с #462, поэтому старые квитанции не переписываются.

## Дефект 5 — перепроверка покрытия МОЛЧА отключала приёмочную команду

Всплыл сразу, как только отказ перестал падать исключением и путь стал доходить дальше.
`_run_operation` делал `pinned_admission = dict(record.get("accepted_admission") or {})`,
дописывал туда `review_coverage` и переприсваивал `record`. Ниже (строка ~1880)
`legacy_unpinned = not admission`: пустой `accepted_admission` — признак операции, принятой до
пиннинга, и именно он включает исполнение зарегистрированной приёмочной команды. Дописав ключ в
пустой словарь, перепроверка объявляла такую операцию пиннингованной, и ветка приёмки уходила в
`status=passed, reason="not_required"` с пустой командой — **красная приёмка пропускалась молча**,
ровно тот исход, против которого написан #240.

Замер: `test_failing_registered_command_blocks_merge_executor` пропускал executor вперёд с
`{"acceptance": {"command": "", "reason": "not_required", "status": "passed"}}`.
Сделано: `review_coverage` дописывается только в НЕПУСТОЙ `accepted_admission`.

## Харнес: почему подмена была нечестной

Оркестратор потребовал обоснования, если харнес всё же трогать. Обоснование конкретное:

- `_accepted()` и патч `inspect_worktree_identity` возвращали `"b" * 40` — коммит, которого нет
  в репозитории, создаваемом ТОЙ ЖЕ фикстурой. В проде `inspect_worktree_identity` отдаёт
  `git rev-parse HEAD` живого worktree, то есть значение, которое в этом worktree разрешается
  всегда. До #462 его никто не резолвил, и подделка была невидима.
- `acc_db` объявлял `branch`, `base_branch` и git-идентичность, но каталог `wt` репозиторием НЕ
  был вовсе — отсюда `fatal: not a git repository` из `_target_head`.

Поэтому: `worker_head()` берёт настоящий HEAD, `acc_db` строит настоящий git-worktree (продовых
файлов там нет намеренно — предмет этих тестов приёмочная команда), `gate_db` дополнительно
выписывает квитанцию ревью на текущий снимок, потому что его предмет — тест-гейт, а не покрытие.
Настоящий случай неразрешимого ref не потерян, а вынесен в отдельный тест, где отказ и есть
ожидаемый исход:
`test_unresolvable_worker_head_is_a_structured_refusal_not_a_crash` и
`test_unresolvable_target_branch_in_revalidation_is_a_structured_refusal`.

Итог: `tests/test_acceptance.py` + `tests/test_merge_test_gate.py` — **53 passed**, было 7 failed.

## Мутации второго захода

| # | мутация | маркер ДО / ПОСЛЕ отката | что покраснело |
|---|---|---|---|
| 5 | убрана `"production_diff_sha256": ""` из `scripts/migrate_review_receipts.py` | 1 / 1 | `test_apply_writes_the_full_receipt_row_for_every_declared_column` — `sqlite3.IntegrityError: NOT NULL constraint failed: review_receipts.production_diff_sha256` |
| 6 | `except (ValueError, OSError): raise` вместо структурного отказа | 3 / 3 (`return _review_snapshot_unavailable`) | `test_unresolvable_worker_head_is_a_structured_refusal_not_a_crash` — наружу снова летит `ValueError: fatal: Invalid symmetric difference expression …` |
| 7 | убрано `AND production_paths_json=?` | 1 / 1 | `test_untracked_production_file_is_not_covered_by_the_old_receipt`: `blocked` → `satisfied` |
| 8 | снят guard `if pinned_admission:` | 1 / 1 | три теста `tests/test_acceptance.py` — приёмочная команда снова не исполняется |
| 9 | снята проверка кода возврата 4 | 1 / 1 | `test_real_failure_mentioning_the_timeout_flag_stays_red`: `FAILED` → `INCONCLUSIVE` |

## Мерж этой задачи проходит СВОЙ гейт

Не рассуждением, а прогоном `evaluate_test_gate('.', target_ref='main')` на ветке:

```
status=passed  reason=''  elapsed=18.5 s
mapped: tests/test_acceptance.py, tests/test_db.py, tests/test_merge_operations.py,
        tests/test_merge_test_gate.py, tests/test_review_coverage_target_drift_474.py,
        tests/test_review_receipt_migration_436.py
190 passed in 17.08s
```

### Остаётся красным и НЕ трогалось: `tests/test_merge_target_oracle_386.py`

13 падений, множества node id на ветке и на чистом `main` совпадают ровно (`diff` пуст). В
mapped-набор гейта этот файл не попадает (`select_tests` идёт по stem: `app/merge_operations.py`
→ `tests/test_merge_operations.py`), поэтому мержи он не блокирует. Отдельный тикет.

## Осталось за границами задачи

`scripts/migrate_review_receipts.py:95-118` собирает строку квитанции дословным перечнем полей и
вставляет её как `tuple(receipt.get(key) for key in _REVIEW_RECEIPT_COLUMNS)`. Новая колонка
там отсутствует → `.get` вернёт `None` → `NOT NULL` при попытке ПРИМЕНИТЬ миграцию (dry-run,
единственный покрытый тестом путь, не задет). Правка ровно одна строка —
`"production_diff_sha256": "",` рядом с `production_snapshot_sha256`. Файл принадлежит
`fix-ownership-migration`, поэтому не тронут.


## Раунд 2 ревью (Luna) — оба blocking проверены и закрыты

Раунд 1: обе находки FIXED, severity correction по untracked принята ревьюером дословно
(«untracked-файл давал неверное admission-решение, но показанный dirty-worktree guard не
позволяет ему дойти до executor»).

### blocking — STILL BROKEN: `_target_head` в НАЧАЛЬНОМ admission — PARTIAL, закрыто

Проверено по коду: наружу `ValueError` оттуда не улетал — единственный вызывающий
(`app/merge_operations.py:2248`) ловит `Exception` и отдаёт структурный 409. Но код отказа при
этом `ORACLE_METADATA_INVALID`, а действие — «почини оракул»: **отказ называл причиной оракул,
которого проблема не касается**. Это тот же класс, что #416 («обёртка имеет право добавить КОД,
но не право заменить ПРИЧИНУ»), поэтому находка принята.

Закрыто двумя правками: шов обёрнут и отдаёт тот же `_review_snapshot_unavailable`; у отказа
появилась своя ветка `REVIEW_SNAPSHOT_UNAVAILABLE` + `FIX_WORKER_REFS_THEN_NEW_OPERATION`, и
текст git попадает в сообщение. Тест —
`test_unresolvable_target_in_initial_admission_is_a_structured_refusal`.

### blocking — NEW BUG: skip-квитанция писала `NULL` — подтверждено, закрыто

`review_receipt_record_skip` строит `values` через `receipt.get(key)` и нормализует лишь пять
колонок. Payload без нового ключа → `NOT NULL constraint failed`. Плюс вторая половина находки:
я включил `production_diff_sha256` в `stable` (identity повтора), и у квитанции, выписанной до
#474, колонка пуста — повтор ТОГО ЖЕ решения превращался в
`skip decision id conflicts with existing provenance`.

Закрыто: колонка нормализуется вместе с остальными и **убрана из `stable`** — она выводится из
того же `raw`, что и `production_snapshot_sha256`, который в identity уже есть вместе с
`target_sha`, то есть к пиннингу предмета ничего не добавляла. Тест —
`test_replayed_skip_receipt_from_before_the_new_column_is_not_a_conflict`.

### suggestion — нормализация путей: принята

`production_paths()` нормализует `\`→`/`, а `production_snapshot()` писала имя от git как есть;
после привязки к `production_paths_json` это стало бы ложным БЛОКОМ на пути с обратным слэшем в
имени. Снимок теперь строит список тем же `production_paths()` — один владелец нормализации.

### Мутации раунда 2

| # | мутация | маркер ДО / ПОСЛЕ отката | что покраснело |
|---|---|---|---|
| 10 | снят `try` вокруг `_target_head` в admission | 1 / 1 | `test_unresolvable_target_in_initial_admission_is_a_structured_refusal` — наружу снова `ValueError` |
| 11 | `production_diff_sha256` убран из нормализации skip | 1 / 1 | `test_replayed_skip_receipt_…` — `sqlite3.IntegrityError: NOT NULL constraint failed` |
| 12 | `production_diff_sha256` возвращён в `stable` | мутант **2 / 1** | тот же тест — `skip decision id conflicts with existing provenance` |

### Состояние после раунда 2

- Смежный набор (22 файла пути мержа и квитанций) — **294 passed**.
- Гейт на своей же ветке: `evaluate_test_gate('.', target_ref='main')` → **passed, 192 passed
  in 18.66s**.


## Раунд 3 ревью (Luna) — APPROVED

Вердикт: **✅ Correct, confidence 0.96**, все находки раунда 2 — FIXED, blocking не осталось.
Доказательство прочтения (требовалась дословная строка из изменённого файла, которой нет в
запросе): `USAGE_ERROR_EXIT_CODE = 4  # pytest EXIT_USAGEERROR` — проверено грепом,
`app/merge_test_gate.py:221`.

Ревьюер отдельно подтвердил рассуждение про `stable`: удаление `production_diff_sha256` из
identity повтора безопасно, потому что `production_snapshot_sha256` уже фиксирует `target_sha`
и точный `raw`, и разойтись эти дайджесты могли бы только при коллизии SHA-256.

### Единственная оставшаяся находка — suggestion, сознательно НЕ чиню

`app/review_coverage.py:65-69`: новые квитанции пишут пути через `production_paths()`, старые
хранят сырое написание от git. Репозиторий, где в имени файла под `app/` или `scripts/` стоит
буквальный обратный слэш, сравнил бы `app/foo\bar.py` с `app/foo/bar.py` и получил ложный блок.

Не чиню по четырём причинам, каждая проверяема:
1. Это suggestion, не blocking; потолок раундов для исполняемого артефакта (3) исчерпан, вердикт
   получен.
2. Направление отказа — **fail-closed**: ложный БЛОК, а не дыра. Лечится повторным ревью, в main
   ничего не проезжает.
3. Сценарий недостижим: `git ls-files | grep -c '\\'` → **0** в этом репозитории; путей с
   обратным слэшем в трекнутых именах нет.
4. Лечение стоит дороже болезни: нормализация хранимого JSON на стороне запроса убивает индекс
   `idx_review_receipts_coverage_diff` на горячем пути допуска, а нормализация данных — это
   переписывание старых квитанций задним числом, прямо запрещённое заданием.

Отдано оркестратору как отдельная строка, а не закрыто молча.

### Расход раундов

Предмет исполняемый → потолок 3. Использовано 3 (все с вердиктом и доказательством).
Находок: blocking 3 (все закрыты), suggestion 2 (1 принята и починена, 1 отклонена с
основанием выше).


## Диспозиция находок ревью (author outcome = partial)

Находок ШЕСТЬ, не пять: `grep -c '^- \*\*' .orchestra/tasks/474/codex-review-impl.md` → 6.
Blocking 3 — все приняты и закрыты правкой. Suggestion 3 — две приняты и закрыты, одна
отклонена с доказательством. Две из принятых приняты С ПОПРАВКОЙ по механизму или severity,
и обе поправки ревьюер подтвердил в следующем раунде — поэтому исход `partial`, а не `accepted`.

| # | находка | исход | чем закрыто | оракул | мутация |
|---|---|---|---|---|---|
| R1-1 | blocking: untracked-продовые пути наследуют покрытие | принята, **severity снижена** | `AND production_paths_json=?` над обеими ветками допуска, `app/review_coverage.py::coverage_decision` | `test_untracked_production_file_is_not_covered_by_the_old_receipt` | 7 |
| R1-2 | suggestion: распознавание отсутствующего плагина по тексту | принята | `proc.returncode == USAGE_ERROR_EXIT_CODE`, `app/merge_test_gate.py::run_pytest` | `test_real_failure_mentioning_the_timeout_flag_stays_red` | 9 |
| R2-1 | blocking: `_target_head` в начальном admission | принята, **механизм поправлен** | `try` вокруг шва + своя ветка отказа `REVIEW_SNAPSHOT_UNAVAILABLE`, `app/merge_operations.py` | `test_unresolvable_target_in_initial_admission_is_a_structured_refusal` | 10 |
| R2-2 | blocking: skip-квитанция пишет `NULL` и конфликтует на повторе | принята целиком | нормализация колонки + удаление её из `stable`, `app/db.py::review_receipt_record_skip` | `test_replayed_skip_receipt_from_before_the_new_column_is_not_a_conflict` | 11, 12 |
| R2-3 | suggestion: разная нормализация путей у снимка и допуска | принята | `production_snapshot` строит список через `production_paths()` — один владелец | покрыт близнецами через `production_paths_json` | — |
| R3-1 | suggestion: старые квитанции хранят сырое написание git | **ОТКЛОНЕНА** | — | — | — |

### Поправки, с которыми находки приняты (обе подтверждены ревьюером)

- **R1-1, severity.** Луна написала «authorizing unreviewed production content» в main. Конца-в-конец
  недостижимо: `execute_merge_session` отказывает на грязном воркерском дереве
  (`_clean_worktree_error`, `app/workspace.py:1386`), а `git status --porcelain` показывает
  untracked как `??` по умолчанию. Неверным было РЕШЕНИЕ допуска, не исход мержа. Раунд 2
  дословно: «severity correction согласен: untracked-файл давал неверное admission-решение, но
  показанный dirty-worktree guard не позволяет ему дойти до executor».
- **R2-1, механизм.** «Всё ещё выбрасывает ValueError вместо structured refusal» — неточно:
  единственный вызывающий (`app/merge_operations.py`, accept path) ловит `Exception` и отдаёт
  структурный 409, наружу исключение не улетало. Настоящий дефект другой и он реален: отказ
  приходил с кодом `ORACLE_METADATA_INVALID` и действием «почини оракул», то есть называл
  причиной оракул, которого проблема не касается. Находка принята по этому основанию.

### Основание отклонения R3-1

1. Это suggestion, не blocking; потолок раундов исполняемого артефакта (3) исчерпан, вердикт
   раунда 3 получен: **APPROVED / Correct / confidence 0.96**.
2. Направление отказа — **fail-closed**: ложный БЛОК мержа, а не дыра в покрытии. В `main`
   ничего не проезжает; лечится повторным ревью.
3. Сценарий недостижим в наших репозиториях: трекнутых путей с буквальным обратным слэшем нет —
   `git ls-files` с фильтром по обратному слэшу даёт **0**.
4. Лечение дороже болезни и упирается в прямой запрет задания: нормализация на стороне запроса
   убивает индекс `idx_review_receipts_coverage_diff` на горячем пути допуска, а нормализация
   данных — это переписывание старых квитанций задним числом, которое задание запрещает явно.

Записано в `.orchestra/kb/review-design-defects.md` §Пробелы, чтобы находка не потерялась.


## Дефект 6 — мой собственный тест зависел от окружения, а не от кода

Гейт отбил мерж на `test_unresolvable_target_branch_in_revalidation_is_a_structured_refusal`:
`1 failed, 191 passed`, тогда как у меня руками тот же набор давал `192 passed`. Тот же
интерпретатор, тот же список файлов, разный исход — значит тест мерил не то, что утверждал.

### Причина — воспроизведена, а не угадана

Тест брал пустой каталог `tmp_path / "plain"` и рассчитывал, что он лежит ВНЕ любого
git-репозитория. Это свойство машины, а не теста. `tempfile.gettempdir()` слушает `TMPDIR`;
у меня база временных каталогов была `/tmp` (отдельный `tmpfs`-mount, обход вверх упирается в
границу файловой системы), у гейта — внутри чекаута.

Воспроизведение одной командой, сигнатура совпала с гейтовой дословно:

```
TMPDIR=$PWD/.tmpprobe pytest -q tests/test_review_coverage_target_drift_474.py -k revalidation
>       assert "not a git repository" in decision["reason_detail"]
E       AssertionError: assert 'not a git repository' in 'ValueError: fatal: Invalid symmetric
E         difference expression 8f40e2b3f2b812528832a01bcb3ebbfdc658619c...bbbb…'
```

Механика: `main` разрешился обходом вверх → `_target_head` отработал → отказ пришёл из ДРУГОГО
шва, `production_snapshot`. Первые два утверждения при этом прошли (`status=blocked`,
`reason=review_snapshot_unavailable`) — то есть тест был зелёным ровно до тех пор, пока
окружение случайно совпадало, и краснел на третьей строке, когда переставало. **Он не отличал
шов ЦЕЛИ от шва СНИМКА и молчал об этом.**

### Две правки, обе про причину

1. **Предусловие устанавливается тестом.** Свой репозиторий (`_repo(tmp_path)`) ограничивает
   обход вверх детерминированно, `git branch -D main` делает цель неразрешимой, и это
   проверяется ПОЛОЖИТЕЛЬНО перед вызовом кода: `git rev-parse --verify main^{commit}` обязан
   вернуть ненулевой код. Сломается предусловие — покраснеет оно, а не ассерт ниже.
2. **Утверждение опирается на текст, которым владеет НАШ код** — `cannot resolve merge target
   main` вместо формулировки git, зависящей от версии и точки запуска. Это заодно различитель
   швов: сработай вместо цели снимок, в `reason_detail` стояло бы `Invalid symmetric
   difference`, и тест обязан покраснеть. Та же замена сделана в
   `test_unresolvable_target_in_initial_admission_is_a_structured_refusal`, где стояло слишком
   слабое `"main" in reason_detail`.

### Проверка независимости от окружения

| прогон | `/tmp` (обычный) | `TMPDIR` внутри чекаута (условие гейта) |
|---|---|---|
| файл целиком, 3 раза подряд | 9 passed ×3 | 9 passed ×3 |
| набор гейта, 192 узла, один процесс | 192 passed | 192 passed |
| мутация 13 (снят `try` вокруг `_target_head` в `_revalidate_review_coverage`) | FAILED | FAILED |

Мутация красная в ОБОИХ окружениях — тест ловит сломанную реализацию, а не сломанное окружение.
Прежняя версия в обычном окружении мутацию тоже ловила, но в гейтовом краснела всегда, независимо
от кода.

### Что осталось невыясненным

Почему у merge-гейта база временных каталогов оказалась внутри чекаута — не установлено:
`TMPDIR`/`TMP`/`TEMP` нет ни в окружении сервиса (`/proc/<MainPID>/environ`), ни в `.env`,
`PrivateTmp` в юните не выставлен, `/tmp` — отдельный `tmpfs`. Дальше не копал сознательно:
тест не должен зависеть от ответа на этот вопрос, и теперь не зависит. Для протокола — любой
тест этого репозитория, берущий `tmp_path` и трогающий git, обязан создавать свой репозиторий.
