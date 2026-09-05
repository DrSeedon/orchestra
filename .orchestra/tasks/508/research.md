# #508 — предмет квитанции и три сообщения об отказах

Фаза 1, исследование без реализации. Код прочитан на `11695d7bb76cf2321ce0b1049bc3cc795072f196`, 05.09.2026. Исполнитель: `fix-review-receipt`, metadata `sessions.model=gpt-6-astra`, `backend_type=codex`. Изменения app/, tests/, политики и сервисов отсутствуют.

## Вопрос и критерий ответа

Контекст: `codex_review` → `review_receipts` → `coverage_decision` → merge admission; рядом используется та же таблица для `task_run`.
Изменение под проверкой: заменить связь с исполнителем связью с проверенным предметом. Baseline: текущая связь scope/session/task + снимок и признаки исхода. Исход: объяснить каждый из трёх симптомов, измерить заполненность квитанций и отказы, проверить ложные допуски кандидата на отрицательном контроле. Смена политики ревью (#506) и хендофф (#507) исключены.

Гипотезы до измерения:

- H1: три отказа вызывает неверная идентичность предмета, потому что receipt связывает проверку с вызывающим агентом. Опровержение: отказ происходит до создания receipt либо в ином `subject_kind`, или совпадение личности не устраняет причину.
- H2: симптомы принадлежат разным автоматам — получение снимка, покрытие, жизненный цикл. Опровержение: один и тот же predicate/переход с единым исправлением непосредственно воспроизводит все три.
- H3: известная выполненная проверка скрыта сессионным ключом. Опровержение для конкретного случая: до отказа не было ревью нужного снимка; совпадают только название задачи, текст отчёта или пустые поля.

## Выборка и воспроизводимость

Живая БД: `/mnt/data/Projects/Python/orchestra/data/orchestra.db`, SQLite URI `mode=ro`, дополнительно `PRAGMA query_only=ON`; без `init_db()`, backup, миграций и записи в живые таблицы. В worktree `data/orchestra.db` отсутствует. Один read transaction для census; логи прочитаны отдельным read transaction с теми же временными границами. Между транзакциями БД продолжала работать; terminal поля receipts — состояние на момент чтения, не восстановленная история переходов.

Последние 7 суток: **[2026-08-29T11:51:37.617350+00:00, 2026-09-05T11:51:37.617350+00:00)**. Receipts отобраны по `requested_at`, операции по `created_at`, события по `logs.ts`. Все scopes этой БД, не только Orchestra. Классификация оркестратора: `review_receipts.session_id = sessions.id`, `sessions.is_orchestrator=1`, не имя агента. Неразрешённых session joins — 0. «Пустые пути» — JSON пустой массив (в срезе все 147 имеют буквально `[]`, не SQL NULL/пустую строку). `task_id` пустой — NULL/пустая строка.

Команды (точный SQL печатается скриптами):

```sh
/mnt/data/Projects/Python/orchestra/.venv/bin/python .orchestra/tasks/508/measure.py > .orchestra/tasks/508/measurement.txt 2>&1
/mnt/data/Projects/Python/orchestra/.venv/bin/python .orchestra/tasks/508/log_measure.py > .orchestra/tasks/508/log-measurement.txt 2>&1
/mnt/data/Projects/Python/orchestra/.venv/bin/python .orchestra/tasks/508/negative_control.py > .orchestra/tasks/508/negative-control.txt 2>&1
/mnt/data/Projects/Python/orchestra/.venv/bin/python .orchestra/tasks/508/subject_probe.py > .orchestra/tasks/508/subject-probe.txt 2>&1
```

`measure.py` создаёт новый текущий срез при повторном запуске. Зафиксированный срез — `sample.json`: разрешённые поля receipts и краткая проекция admission операций, без prompts, test stdout, credentials и полных job configs. Повтор negative control использует именно зафиксированный срез.

Дословный вывод census:

```text
COUNTS_ALL {"n": 227, "empty_task": 17, "empty_paths": 147, "orchestrator": 2, "unresolved_session": 0, "all_three": 2}
COUNTS_KIND implementation {"n": 91, "empty_task": 9, "empty_paths": 11, "orchestrator": 0, "unresolved_session": 0, "all_three": 0}
COUNTS_KIND task_run {"n": 54, "empty_task": 0, "empty_paths": 54, "orchestrator": 0, "unresolved_session": 0, "all_three": 0}
COUNTS_KIND unknown {"n": 82, "empty_task": 8, "empty_paths": 82, "orchestrator": 2, "unresolved_session": 0, "all_three": 2}
STATUS {"completed": 166, "failed": 1, "interrupted": 36, "requested": 24}
OPERATIONS 196 RECORD_REVIEW_THEN_NEW_OPERATION 0
```

CONFIRMED — прямое измерение [1]. 147 пустых массивов не означают 147 сломанных ревью: 54 принадлежат task-run, 82 — неприкреплённым к implementation `exec/review`, 11 — implementation без app/scripts-диффа. Пустой task_id встречается и у воркеров; это не специфический признак оркестратора.

## Кто владеет полями и кто их заполняет

| Поле/связь | Владелец и writer при ревью | Consumer при merge |
|---|---|---|
| `scope` | MCP environment `SCOPE`; запись `codex_review`, `app/mcp_stdio.py:4401` | `request.scope` / snapshot worker; нормализация trailing slash, `app/merge_operations.py:1006` |
| `session_id` | `GET /api/sessions/{WORKER_NAME}` → `info.id`, инициатор review, не отдельная CLI-сессия reviewer; `mcp_stdio.py:4218` | `accepted.session_id` = session **мержимого worker**, `_session_snapshot:907` |
| `worker_name` | `WORKER_NAME` инициатора review | аудит; в SQL matching не участвует |
| `task_id`, `task_source` | `info.task_id or ''`; literal `session_lookup`; путь output не используется для вывода task_id | `accepted.task_id` из текущего назначения worker |
| `subject_kind`, `mode` | `implementation` только для mode implementation; иначе subject `unknown`; отдельный task-run writer | coverage требует implementation |
| `base_branch` | session metadata; MCP берёт `info.base_branch or 'main'`, не аргумент API review | merge берёт request target / base_branch; `_target_head:927` резолвит commit |
| `target_sha`, `worker_head` | `resolve_implementation_subject:123`: чистое committed дерево caller; `rev-parse target_ref^{commit}` и `HEAD^{commit}` | повторный снимок worktree worker; head хранится как evidence и для attestation, не отдельное равенство в основном SQL |
| `production_snapshot_sha256` | `production_snapshot:82`: sha256(version + target_sha + NUL + raw) | первая ветка SQL: target_sha И snapshot digest |
| `production_diff_sha256` | там же: sha256(отдельная version + raw); пустой raw → `''` | вторая ветка: **непустой** равный digest; разрешает дрейф target при тождественном raw |
| `production_paths_json` | там же: нормализованные sorted пути app/scripts из git diff | отдельное равенство JSON поверх ОБЕИХ веток; admission paths приходят из `changed_paths`, включая untracked |
| `requested_at`, `round`, `receipt_id` | MCP timestamp + UUID; `db.review_receipt_reserve:3284` атомарно выделяет round по artifact_path | проверка requested/completed ≤ boundary, порядок по времени |
| `status`, `completed_at`, `return_code`, artifact/JSONL/verdict поля, `coverage_outcome` | `codex_review_artifact._record_terminal_receipt:53` читает вывод и JSONL; `review_receipt_finish:3339` допускает только terminal поля; ошибки/недоступность также закрывает MCP | `_reviewed_receipt:263`, `coverage_decision:450`; skip/unavailable отдельные ветки, не выполненное ревью |
| `author_outcome`, `outcome_evidence_ref`, `outcome_source` | `record_review_outcome:4117` → `_receipt_author_session:4012` сверяет caller с receipt.session_id → `db.review_receipt_set_outcome:3365` | reviewed требует accepted/disputed/partial; без подписи отдельный отказ |
| `policy_ref`, `decision_actor` | MCP snapshot `current_policy_ref()`; skip writer указывает actor | current policy проверяется для skip/unavailable, не используется как равенство для reviewed |
| `artifact_path`, `artifact_sha256`, `job_id`, `usage_event_id`, reviewer model/runtime | MCP резервирует путь/IDs/model; finalizer пишет content hash и terminal evidence | основной gate доверяет terminal метаданным, не перечитывает artifact; attestation дополнительно сверяет hash |
| `task_stable_id`, `task_snapshot_ref`, `prompt_template_start/end`, `terminal_operation_id` | task lifecycle `tm._open_task_run_for_task`/`_finish_task_run_for_task` → db task-run writers; для обычной review reserve значения по умолчанию пустые | НЕ ключ основного coverage SQL; task-run compare защищает provenance назначения |

Хранилище и разрешённые writers: `app/db.py:3284–3390`. `_require_bound_task_run_for_review:3133` проверяет наличие одного открытого task-run для bound implementation review, но не превращает task-run в evidence ревью. CONFIRMED — первичный код [3–8].

Полный путь: `codex_review:4182` выбирает **worktree вызывающего**, затем пинит refs ДО резервирования receipt; параметры `target_worker`/`base_branch` отсутствуют. `target` в implementation запрещён. Prompt `mcp_stdio.py:4500–4530` требует читать полный committed diff между pinned SHA и запрещает подменять HEAD/task file. Финализатор записывает execution facts; инициатор отдельно подписывает свой исход. `coverage_decision:433–445` выбирает scope+session+task+paths+(snapshot ИЛИ непустой diff digest)+time, затем проверяет признаки review/skip/unavailable. При изменившейся production-дельте отдельный `_attested_decision:517` использует последнее review и подписанную аттестацию, а не произвольный старый receipt. Merge сначала проверяет admission, затем перед исполнением `_revalidate_review_coverage:1128` повторяет проверку. CONFIRMED [3–6].

**Предмет сегодня:** строка implementation описывает запуск проверки committed diff в worktree инициатора, а для допуска хранит только его **проекцию путей `app/**` и `scripts/**`**, связанную с caller session/task. Строка task_run описывает назначение задачи. Таблица — контейнер нескольких предметов. «Квитанция описывает только КТО» неверно: ЧТО уже хранится. Проблема узкого случая — сессия одновременно означает инициатора/подписанта и владельца merge subject, без отдельного explicit subject owner.

## Три симптома: разные причины, не три доказательства одной

| Наблюдение | Установленная механика | Статус исторического случая |
|---|---|---|
| Ревью вызывается оркестратором для работы worker | MCP пинит caller worktree; merge требует worker session/task/production snapshot. Снять session predicate недостаточно, если сам дифф другой/пустой | Свидетельство kesha-tg-bot в TODO.md:154; локальных receipts этого scope **0**. Случай не подтверждён этим срезом |
| `main` в master-only репозитории | `info.base_branch or 'main'` может упасть в resolve до reserve и до запуска reviewer. Явный session base_branch=master работает | В изолированном Git воспроизведено; исторический VPN-вызов локально не найден. **Не** безусловный hardcode main при любом base_branch |
| legacy continue → conflict task-run → complete без коммитов | legacy merge сохраняет привязку и quarantine; task-run остаётся requested; сравнение expected provenance может конфликтовать; complete зависит от Git commits | Код подтверждает разные переходы; seedon task-run в локальной БД **0**, первичный эпизод пока чужое свидетельство |

`task_run_receipt_open`, `db.py:2920–2953`, сравнивает не только task_id, но stable ID, snapshot ref, task_source, prompt_template_start. Поэтому «прогон открыт» само по себе **не ошибка**: continue намеренно продолжает ту же задачу. `tm.py:1450–1461` закрывает прогон при complete. Legacy-ветка `routes/sessions.py:2327–2340` сохраняет bound task, предупреждает `LEGACY_MERGE_CONTINUE`; strict v2 запрещает continue+next_task. Безусловно закрывать любой run при continue — смена семантики, а не очевидная починка. `workspace.py:1813` и `routes/sessions.py:2267` отвергают no-new-commit merge. CONFIRMED по коду [7–9]; точная историческая цепь seedon UNCERTAIN до выгрузки.

Репозиторий уже имеет `workspace.resolve_base_branch:329`: explicit requested → проверка; иначе symbolic remote HEAD → локальная ветка; затем well-known candidates. Его существование — аргумент проверить единый resolver, а не добавить ещё один порядок угадывания. Это предложение, не разрешение реализации.

Изолированный `subject_probe.py`, дословно:

```text
RESOLVE main ValueError fatal: Needed a single revision
RESOLVE master OK ['app/x.py']
UNREVIEWED_TEST_CHANGE {"production_identity_equal": true, "complete_raw_diff_equal": false}
UNREVIEWED_PRODUCTION_CHANGE_IDENTITY_EQUAL False
```

## Отказы есть в логах, но отсутствуют в реестре операций

Первичный blocked return `merge_operations.py:2384–2400` выполняется ДО `accept_operation_snapshot:2402`. SQL INSERT находится в `accept_operation_snapshot:716`. Поэтому наличие operation UUID в ответе не означает существование durable operation row. Это отдельный пробел **структурного** аудита, не доказательство исчезновения всех следов.

Дословный результат `log_measure.py`:

```text
MERGE_TOOL_RESULT_ROWS 242 COVERAGE_REFUSAL_ROWS 17
DISTINCT_OPERATION_IDS 17 PERSISTED 0
PROJECT_SESSIONS kesha-tg-bot 16
PROJECT_RECEIPTS kesha-tg-bot 0
PROJECT_SESSIONS VPN-Service 7
PROJECT_RECEIPTS VPN-Service 1
PROJECT_SESSIONS seedon 89
PROJECT_RECEIPTS seedon 0
```

Counting rule: tool_result, tool_name=`merge_worker` или суффикс `__merge_worker`, окно по ts; literal `Record review coverage for this exact snapshot, then start a new operation.` либо machine code. UUID извлечены из `Merge operation <uuid>`; все 17 уникальны и все отсутствуют в merge_operations. 242 — число ответов инструмента, не уникальных successful merges. Все 17 принадлежат локальному Orchestra scope. Это нижняя наблюдаемая граница отказов системы: вызовы через другие interfaces, другой контур, утраченные/неимпортированные логи не включены. HTTP отказы без сохранённого tool_result этим методом не восстановить.

CONFIRMED [1,2,6]: **17** таких отказов наблюдаются в logs против **0/196** в реестре merge_operations. Прямой поиск одного machine code в logs дал бы ложный результат: отображаемый текст содержит human message, не этот code. Исходные ответы с log IDs сохранены дословно в `log-measurement.txt`. После потери контекста агента текст остаётся в SQLite logs; отсутствуют структурная строка операции и полный rejected admission snapshot, что ограничивает историческую оценку правоты каждого отказа.

## Три конкретных примера и разделение болезней

1. **#507: гейт прав на момент вызова.** Log **607073**, `2026-09-05T11:40:17.042571+00:00`: `Merge operation 3048b283-ce72-460b-8fe1-defc63ca776d: FAILED — production diff has no snapshot-bound review, authorized skip, or machine-unavailable receipt. Record review coverage for this exact snapshot, then start a new operation.` Первый локальный implementation receipt worker `fix-handoff-packet` — `review-receipt:6415fed3-d0f8-4fe3-8146-bae4362f2592`, request **11:45:16.785673**, complete **11:46:59.034951**, то есть ПОСЛЕ отказа. На срезе author_outcome ещё unknown. Оркестратор письменно исправил исходную карточку: review от своего имени он не запускал. Это не потерянное выполненное review. Сам отказ не записан в merge_operations, но есть в logs. CONFIRMED [1,2,10].
2. **COG: пустые поля не доказывают ошибку покрытия.** Оркестраторские receipts `8c19ba20-384f-4762-b8f7-ee1c207a05fe` (mode review, 05:30) и `85d32f99-1937-4f30-9b7e-136a8e91e8db` (mode exec, 05:33) completed; у обеих пуст task_id/paths и subject_kind unknown. У первой verdict_present=0, у второй 1. Ни одна не является pinned implementation review; перенос на worker на основании completed/APPROVED был бы выдуманной привязкой. CONFIRMED по metadata [1]. Содержательное качество их артефактов не оценивалось.
3. **Исторический #472: выполненное ревью действительно не видел старый gate, но причиной был target drift.** Прежний отчёт #474 называет receipt `01435214-5df0-4073-8eaa-6d074fb12240` и одинаковый raw diff при разных target/head. В текущем коде уже есть отдельный production_diff digest. В этой сессии независимые готовые тесты прежнего кейса и отрицательных плеч дали **4 passed**, включая one changed production byte и untracked. Это контрдоказательство универсальности session-гипотезы, а не доказательство современного kesha-случая. Исторические числа из #474 не выдаются за наш новый замер. Исторический эпизод — tier 2 из открытого артефакта [11]; современное поведение — tier 1 [12].

Итого различать три диагноза: (а) проверка нужного предмета ещё не состоялась — не ослаблять gate; (б) проверка состоялась, но metadata не доказывает связь — нужна проверяемая identity, не косметический перенос; (в) отказ состоялся, но **не зарегистрирован как операция**, хотя текстовый лог существует. Последний диагноз ортогонален первым двум.

## Отрицательный контроль: предмет необходим, но недостаточен

Кандидат **S** «receipt описывает этот production snapshot»: одинаковый scope, **непустой** равный production_diff_sha256, одинаковый production_paths_json. Это проекция app/scripts, не claim о полном repository snapshot. Для признания выполненным ревью кандидат **R** дополнительно сохраняет `_reviewed_receipt` (implementation, reviewed, completed, RC=0, artifact exists/bytes>0, JSONL response, verdict) + допустимый author_outcome + completed до верхней границы. Это offline эксперимент; в production ничего не включено. Legacy receipts без diff digest не мигрированы и не переатрибутированы; отдельная target-bound ветка baseline остаётся за пределами этого кандидата.

Заранее заданные controls в `negative_control.py`: все **54 task_run** и **27 explicit skipped** — в ЭТИХ квитанциях model review заведомо не исполнялось; labels получены из вида операции, не из ответа кандидата. Прогнать каждую против всех **49** implementation subjects с непустым diff digest. AC: ноль признаний reviewed для этих 81 receipts; одновременно разрешить собственные eligible review как positive sanity check. Interrupted/failed не объявляются «заведомо не читали»: reviewer мог начать работу, такие записи исключены из natural-negative labels.

Дословный вывод:

```text
SUBJECTS 49 NEGATIVE_RECEIPTS 81 PAIRS 3969
NEGATIVE_CLASSES {('implementation', 'skipped'): 27, ('task_run', 'unknown'): 54}
IDENTITY_ONLY_FALSE_REVIEW_ADMISSIONS 20
CANDIDATE_FALSE_REVIEW_ADMISSIONS 0
POSITIVE_SELF 12 ADMITTED 12
CROSS_SESSION_TASK_MATCHES 0
SYNTHETIC_UNREVIEWED_SUBJECTS 36 FALSE_ADMISSIONS 0
IDENTITY_ONLY_COUNTEREXAMPLE review-skip:93ef174a7e360731a231c0a3827711d7629368e21180307bdadbfaca2b21bdd0  skipped 53babac7addfb97547778419704fc118d72e5f36f0e8c464e0c028b8e9edf298
```

CONFIRMED [13]: identity-only даёт **20 ложных признаний выполненного review**. Это НЕ утверждение, что explicit skip незаконно пропускает merge: разрешённый skip — отдельный законный исход baseline. Ошибка — выдать skip за review при переиспользовании квитанции. Сохранённый control является исполняемым oracle этой узкой ошибки.

R: **0/3969**, positive self **12/12**. Синтетические 36 candidate snapshots меняют по одному scope/digest/paths, дают 0 допусков; это metadata mutations, не 36 настоящих Git reviews. **Межсессионных положительных совпадений нет**, поэтому улучшение recall/разблокировка нужной работы не доказаны. Эти пары зависимы; 3969 не независимых испытаний и не основание статистической оценки вероятности обхода. Ни R, ни исходные flags сами по себе не доказывают, что модель действительно прочла правильные bytes.

Дополнительное контрдоказательство слишком широкой интерпретации S: реальный изолированный Git-прогон `subject_probe.py` добавил непросмотренный `tests/test_x.py` с `assert False`; production identity сохранилась при изменившемся complete diff. Это ожидаемая текущая проекция гейта, не регрессия кандидата. Назвать S доказательством «проверен полный снимок» было бы неверно; правила полноты ревью здесь не меняем.

## Предложенные заявителями починки: оценка, не проект

- `codex_review(target_worker=...)`: направляет reviewer на правильный предмет **до запуска**. Нужно сервером разрешить target worker/scope/task/base, пинить snapshot, сохранить отдельно requester/signing identity и subject identity, проверять drift. Уже проведённое неприкреплённое review не восстанавливает задним числом. Наиболее ограниченная перспективная развилка, но требует явного решения владельца об API/полях.
- `record_review_outcome(target_worker=...)` как перенос: сейчас target_worker работает для skipped, а обычный outcome проверяет **автора** и не меняет immutable start fields (`review_receipt_finish` запрещает такие updates). Перенос по отчёту/пути unsafe: правильный reviewer мог проверять другое. Допустимость новой отдельной association требует машинного доказательства того же предмета и сохранения signer, а не правки старой receipt. Для exec/unpinned review такого доказательства в нынешних полях нет. Контроль S не заменяет R.
- Обход quota для хода «только выписать квитанцию»: не чинит неверный subject/base/task_run и не превращает состоявшийся текст в pinned review. Увеличивает доступность workflow, но это другая задача/политика; здесь не рекомендуем как исправление identity.
- «Закрывать run на continue»: отбрасывается как безусловное правило; continue намеренно не завершает задачу. Нужен отдельный разбор legacy assignment/provenance и безопасного завершения без новых коммитов, со своими правами и атомарностью.

## Вывод и архитектурная развилка

H1 как общий корень трёх отказов **REFUTED кодом**: base resolution происходит раньше receipt; task_run имеет другой предмет и writer. H2 **CONFIRMED по коду**, историческое проявление двух внешних контуров ещё UNCERTAIN. Узкая H3 остаётся **возможным дефектом API**: caller одновременно используется как subject owner; конкретное состоявшееся review kesha ещё не подтверждено доступными данными. На #507 H3 опровергнута timestamp и исправлением заявителя. Ошибка структурной наблюдаемости подтверждена независимо.

| Ветка решения владельца | Что даст | Цена/ограничение |
|---|---|---|
| A. Сохранить owner-bound gate; отдельные ограниченные исправления resolver, legacy lifecycle и регистрации rejected admission | Не расширяет доверие к старым receipts; устраняет независимые seams после их конкретизации | Оркестратор не сможет заказывать pinned review другого worker штатно; может остаться дополнительный ход worker. Нужны отдельные AC для lifecycle и аудита; число трудозатрат не измерено |
| B. Explicit review subject при запуске; requester/signer отдельно от worker/task snapshot | Позволит запускать review нужной работы от оркестратора, сохраняя доказательство предмета и авторство | Меняется API и модель start provenance; нужны авторизация target, migration/read compatibility, drift/recovery и positive cross-session oracle. Не спасает старые unpinned reviews. Предпочтительная ограниченная гипотеза для следующей фазы, если владелец выбирает этот workflow |
| C. Глобальное переиспользование review по content identity без worker/task bound | Может переиспользовать один production diff между задачами/исполнителями | Самая широкая граница доверия: разные требования задач, repo context и full diff не покрыты digest; полезность не измерена (0 cross-session positives). Требуется определить полный контракт предмета и отдельные positive/negative controls; по этому ресёрчу включать нельзя |

Resolver, legacy lifecycle и структурный аудит нужны независимо от выбора A/B/C; объединение их одной миграцией receipt не обосновано. Денежных/часовых оценок без реализации не делали. Никакая ветка не разрешает называть непроверенное проверенным.

## Проверки, ограничения и следующий checkpoint

Проверен только узкий существующий набор, без полного сьюта и настоящих reviewer CLI:

```sh
systemd-run --user --scope -p MemoryMax=2G nice -n 15 env -u NOTIFY_SOCKET /mnt/data/Projects/Python/orchestra/.venv/bin/python -m pytest tests/test_review_coverage_target_drift_474.py::test_foreign_main_commit_does_not_invalidate_the_reviewed_production_diff tests/test_review_coverage_target_drift_474.py::test_one_changed_production_byte_still_revokes_the_receipt tests/test_review_coverage_target_drift_474.py::test_empty_production_diff_never_matches_a_legacy_empty_digest tests/test_review_coverage_target_drift_474.py::test_untracked_production_file_is_not_covered_by_the_old_receipt -q > .orchestra/tasks/508/focused-tests.txt 2>&1
```

Результат: `4 passed in 3.11s`. Импортированный app: `/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-review-receipt/app/__init__.py`. Первая попытка limiter отказалась **до тестов**: `Unknown assignment: Nice=15`; исправлена командой nice внутри scope, без снятия MemoryMax. Git-проба и отрицательный контроль — отдельные research scripts, не изменения acceptance tests.

Применён skill `.codex/skills/codex-debate/SKILL.md`, decision gate: менялись только исследовательские артефакты/KB, consumers runtime не менялись; AC — вопрос/полный путь/живой census/negative control/развилка, checks выше. Вывод затрагивает admission identity, полного независимого oracle для architecture нет. **Review: none — Sol not authorized**; дополнительная модель не запускалась, модельного APPROVED нет.

Открыто: первичные receipts/artifacts/logs внешних случаев и контур их БД (запрошены через своего оркестратора); успешный cross-session positive case; восстановление полного rejected subject для остальных 16 отказов; безопасность контекстного reuse. Не все failed/interrupted receipts классифицированы как действительно несостоявшееся review. Код на диске не объявляется исполняемым кодом каждого внешнего сервиса.

**Фаза 1 завершена в границах доступного среза; реализация не начата. Архитектурное решение — за владельцем.** Внешняя выгрузка может дополнить исторические случаи, но не меняет доказанную локальную статистику замороженного окна.

## Источники и уровни доказательств

1. Tier 1: `measure.py`, `measurement.txt`, `sample.json` — read-only census и metadata.
2. Tier 1: `log_measure.py`, `log-measurement.txt` — SQL, 17 дословных отказов с log IDs, отсутствие operation rows.
3. Tier 2: `app/mcp_stdio.py:4218–4530`, `:4014–4180` — создание предмета, prompt, signer.
4. Tier 2: `app/db.py:3133–3390` — reserve/finish/outcome, immutable start и bound task-run guard.
5. Tier 2: `app/review_coverage.py:82–134`, `:263–278`, `:389–588` — snapshot, SQL и evidence/attestation predicates.
6. Tier 2: `app/merge_operations.py:907–943`, `:985–1170`, `:2338–2407` — merge subject, admission/revalidation, ранний отказ.
7. Tier 2: `app/db.py:2902–3094` — task-run subject/provenance/terminal lifecycle.
8. Tier 2: `app/codex_review_artifact.py:53–116`; `app/tm.py:940–1025`, `:1438–1469` — terminal facts, task-run ownership.
9. Tier 2: `app/routes/sessions.py:1724–1740`, `:2011–2034`, `:2267`, `:2327–2340`; `app/workspace.py:329–375`, `:1813` — legacy и resolver.
10. Первичное свидетельство заявителя: `task_get("508")` и поправки Orchestra-orchestrator от 05.09 в этой сессии; исходные внешние эпизоды из `TODO.md:154`, `:164` не приравниваются к измерению.
11. Tier 2 исторический артефакт: `.orchestra/tasks/474/report.md:78–112` — прежний target drift, не наша повторная оценка чисел.
12. Tier 1: `focused-tests.txt`, `subject_probe.py`, `subject-probe.txt` — 4 tests и изолированные Git controls.
13. Tier 1: `negative_control.py`, `negative-control.txt` — frozen metadata comparison и границы labels.

Внешних URL не использовано: все исследуемые механизмы находятся в собственном коде и данных; веб-поиск не требовался.

Финальная механическая проверка: `scripts/check_kb_contract.py --root .orchestra/kb --diff .orchestra/tasks/508/kb.patch` → `KB contract OK`; `git diff --check` → exit 0. Frozen sample assertions → `Frozen counts and metadata projection: OK`; ограниченный credential-pattern scan артефактов → 0 совпавших файлов. KB получила три новых структурных вывода и вопрос в Gaps; старые факты не удалялись. Personal memory: рабочая форма nice внутри systemd scope, поскольку `Nice=` не свойство scope.
