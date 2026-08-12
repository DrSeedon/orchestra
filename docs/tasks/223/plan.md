# #223 — делегирование реализации закрытых тикетов из `full-cycle`

## Результат и границы

Phase 3 получает один явный маршрут: дорогой `full-cycle` сохраняет план и красный oracle,
а целиком закрытый тикет отдаёт роли `worker` на модель из существующего `model-routing`.
Приёмку делает родитель по неизменности oracle, той же команде и оставшимся AC. Тикет с
`oracle: none` никогда не делегируется.

Меняются только:

- `pipelines/default/prompts/roles/full-cycle.md` — dispatch, payload, приёмка, попытки;
- `pipelines/default/prompts/roles/worker.md` — неизменяемость полученного oracle;
- `tests/test_default_pipeline.py` — source/delivery/non-leakage oracle;
- `docs/tasks/223/ab-results.md` и `report.md` — результат предзарегистрированного A/B.

Не менять `pipeline.yaml`, `model-routing.md`, `app/`, API, БД или lifecycle. Барьер #219 не
является зависимостью: последовательный rollout #223 имеет одного ребёнка. Общего запрета на
параллельные независимые тикеты нет; этот A/B идёт последовательно только для разделения
эффектов. Второй механизм барьера не проектируется.

## Дословный production-текст

### `roles/full-cycle.md`: новые шаги 3–4 Phase 3

Вставить после существующего RED-гейта. Предложения, которые являются якорями теста, оставить
физически целыми строками.

```markdown
3. **DISPATCH a delegable ticket to one executor.**
   - Only a ticket with a reviewed, committed RED command that just failed for the missing behavior is delegable.
   - A ticket marked `oracle: none` is NEVER delegated; implement it yourself on the expensive side.
   - Otherwise use the model selected by `<model-routing>`: Luna remains the default, and the existing Sol complexity exception still applies. Spawn one `worker` for the whole ticket. Send `Files`, `Test`, `AC`, `blocked-by`, the RED commit, the exact command, its non-zero exit and failing assertion, plus this sentence verbatim:
     `The received acceptance test is immutable: NEVER edit, delete, rename, skip, xfail, or weaken it.`
   - The worker sends exactly one message: its terminal `DONE` report, or one terminal exception report instead. Normal progress stays silent. An early exception report is allowed only for leaving/cannot obey scope, finding a false premise, or being blocked.
   - The terminal report contains the executor commit, the exact test command and output, and evidence for every remaining AC.
4. **ACCEPT OR ESCALATE; never coach or retry the same executor.**
   - Inspect the executor's committed diff and clean WIP before merge. Before merge, compare every oracle path byte-for-byte with the RED commit.
   - A clarification request, a `WIP/STOP` report, or any oracle mutation is a failed executor attempt. A still-red named command or an unproven AC is the same failure.
   - Luna gets exactly one attempt. On failure, send the same unchanged ticket once to a Sol `worker`; do not answer Luna's question, rewrite its oracle, or return the ticket to Luna.
   - A Sol `worker` gets exactly one attempt. If Sol fails, whether selected first or after Luna, take the ticket back and implement it yourself on the expensive side. If the premise, scope, Test, or AC must change, take it back immediately and re-close it before any future delegation.
   - A child's green report is evidence, not acceptance. Merge only a clean committed result, then rerun the exact command and the ticket's focused regression check yourself.
```

Существующие шаги 3–8 становятся 5–10. В перенумерованном pre-mortem дословно обновить ссылки
`Cover each in step 6` и `report.md (step 9)`; остальной смысл шагов не менять.

### `roles/full-cycle.md`: уточнение `<parallelism>`

Заменить двусмысленное `Research/data gathering only — never split code implementation this
way` одним владельцем границы:

```markdown
- Never split one implementation ticket across agents. Phase 3 may delegate the whole ticket to one worker under its red-oracle contract.
```

Это не запрещает параллельность независимых тикетов и не добавляет fan-out в последовательный
A/B #223.

### `roles/worker.md`: обязательный immutable-oracle guard

Сразу после существующего `Never author the acceptance test...` добавить:

```markdown
- **The received acceptance test is immutable: NEVER edit, delete, rename, skip, xfail, or weaken it.** If the command cannot be made green without changing that test, report `WIP/STOP`; do not replace it or create a different check.
```

Та же первая фраза уходит исполнителю дословно в payload. Дублирование намеренное: `worker.md`
защищает все задачи роли, payload доказывает, что конкретный родитель передал ограничение.

## Delivery oracle и мутации

Команда T1 уже закоммичена красной в `286720e6`:

```bash
uv run python -m pytest tests/test_default_pipeline.py -k 't1_delegation' -q
```

Наблюдённый RED: exit 1, `4 failed, 2 passed, 81 deselected`. Первая несущая строка:

```text
AssertionError: roles/full-cycle.md is missing delegation clauses: [...]
```

`TestTicketDelegationGate` проверяет:

1. все hand-written parent anchors принадлежат `roles/full-cycle.md`;
2. точная immutable-фраза принадлежит обоим role-файлам;
3. `build_system_prompt` доставляет полный контракт в `full-cycle`, immutable guard — в
   `worker`;
4. parent policy не протекает в `worker`, никакая клауза не протекает в `orchestrator` или
   `sub-orchestrator`;
5. dispatch gate расположен между началом Phase 3 и pre-mortem, то есть до реализации.

После зелёной реализации обязательны две составные и одна точечная мутация, каждая со свежим
backup:

- удалить dispatch/accept block из `roles/full-cycle.md` и посадить его якоря в `base.md`;
- удалить immutable-фразу из `roles/worker.md` и посадить её в `base.md`.
- отдельно удалить `Before merge, compare every oracle path byte-for-byte with the RED commit.`,
  не трогая immutable-фразу.

Каждая мутация выполняется одной shell-командой вида `cp → mutate → pytest → mv backup → touch
restored files → grep -c anchors → green pytest`; `git checkout`/`stash` для отката запрещены.
Ожидание: mutant-команда красная по source ownership и/или non-leakage, после отката focused
command снова `6 passed`, а `git diff 286720e6 -- tests/test_default_pipeline.py` пуст.

Соседняя проверка без полного suite:

```bash
uv run python -m pytest tests/test_default_pipeline.py tests/test_pipeline.py \
  tests/test_prompting.py tests/test_legacy_pipeline_skills.py -q
```

## Предрегистрация A/B в Phase 3

### Вопрос и единица сравнения

Один и тот же T1 выполняется двумя путями от одного RED-коммита `286720e6`:

- **A / control:** свежая сессия роли `full-cycle` реализует T1 сама;
- **B / delegated:** другая свежая сессия той же роли, модели и effort отдаёт тот же T1
  Luna-`worker` и принимает результат. Стоимость B включает все ходы этого parent и ребёнка.
  При failure включается ровно один Sol fallback по production-контракту; повторной Luna нет.

Общие и потому исключённые статьи: Phase 1, написание плана/oracle, этот Codex review и финальный
implementation review. Oracle один раз написал текущий дорогой `full-cycle` до разделения arms;
оба экспериментальных parent получают его как общий pre-treatment artifact и не могут менять.
Это две контрфактические ветки одной границы после Phase 2, а не новые авторы oracle.
В обеих ветках исходная спецификация, RED-коммит, test command, AC и baseline role/system prompt
побайтно одинаковы. Различается только заранее замороженный route suffix: A велит выполнить T1
самостоятельно, B велит применить дословный production block steps 3–4 из этого плана прямо
сейчас и делегировать T1. Этот B suffix — проверяемое treatment, а не импровизация parent.

### Изоляция и порядок

До любого arm создать на реальном диске под `data/task-223-ab/` frozen `git bundle` текущей
ветки на `286720e6` и из него две отдельные копии A/B через
`git clone --no-local --single-branch`. Этот симметричный harness заканчивается отдельным
preflight-turn. Этот ход смешивает создание стенда с другой работой текущего parent, поэтому его
стоимость публикуется описательно как mixed experimental overhead, не входит в `C_A`, `C_B` и
не получает псевдоточную формулу. В обеих копиях до запуска доказать:

- `git rev-parse HEAD` = `286720e6`;
- focused command даёт тот же исходный `4 failed, 2 passed`.

Arms запускаются **последовательно**, но порядок один раз выбирается до результата системным
random source командой `python3 -c 'import secrets; print(secrets.randbelow(2))'` и записывается
в `ab-results.md` (`0 = A first`, `1 = B first`); повторного выбора нет. У обоих fresh parent нет
предыдущих turns, поэтому поздний arm не наследует выросший conversation context первого.
После первого arm и до второго дополнительно доказать, что `git cat-file -e` возвращает
non-zero для каждого implementation commit первого arm во второй копии.

Обычный Orchestra worktree от основного repo запрещён: общий object store раскрывает A через
`git log --all`/`git show` и обнуляет слепоту. В каждой копии создаётся ровно один свежий
`full-cycle` parent с одинаковыми model/effort, system prompt и task context. Для него Phase 1/2
уже закрыты: task payload содержит T1, общий RED-output и указание исполнять только одобренную
Phase 3 до commit + test evidence, затем STOP до общего внешнего Codex review/report. B-parent
сам спавнит Luna и принимает её через `merge_worker` в своей disposable copy.
Ни один результат не передаётся второму arm. После обоих прогонов control-коммит A переносится
в рабочую ветку как production-реализация; B остаётся измерительным артефактом.

Свежие parent sessions заранее называются `bench223-control` и `bench223-delegated`; B заранее
называет детей `bench223-luna` и, только при fallback, `bench223-sol`. Сразу перед каждым spawn
из backup-снимка БД записывается `start_after_id = max(turn_usage.id)`, сразу после terminal
report — `end_id`. В arm входят все и только строки соответствующих session UUID с
`start_after_id < id <= end_id`. Каждая строка классифицируется ровно один раз, а `COUNT(*)` и
`SUM(cost_usd)` классификации обязаны совпасть с тем же interval query.

Model id и effort дорогого parent один раз читаются из текущей `full-cycle` session перед
randomization и дословно передаются обоим arms; если один из них нельзя зафиксировать одинаково,
confirmatory run не начинается. До randomization сохранить два полных task payload и их SHA-256
в `ab-results.md`. Общая часть обоих файлов — T1 и RED evidence. Suffix A дословно:

```text
Execute T1 yourself. Do not delegate it. Stop after the implementation commit and test evidence.
```

Suffix B дословно начинается с `Execute T1 through the following Phase 3 treatment now`, затем
содержит **без изменений весь markdown block steps 3–4 из раздела «Дословный production-текст»**,
и заканчивается:

```text
The frozen system prompt predates this treatment; the block above is the authoritative Phase 3 rule for this run. Stop after the accepted implementation commit and test evidence.
```

Перед spawn извлечь block из committed `plan.md`, сравнить его с B payload побайтно и записать
SHA-256 обоих: несовпадение отменяет confirmatory run. Таким образом B проверяет именно будущий
production-контракт, хотя frozen baseline commit ещё не содержит его в role-файле.

### Число прогонов и запрет добора

Confirmatory sample: **1 matched run = 1 control + 1 delegated run** на T1. Повтор после первого
результата навсегда exploratory и в headline не суммируется. Причина N=1: это первый live
rollout и единственная пара независимых реализаций данного тикета; вывод относится только к T1,
не к популяции тикетов.

### Метрика, сырые данные и вердикт

Срез живой SQLite снимается только через `sqlite3.Connection.backup`, не `cp` WAL-файла.
В `docs/tasks/223/ab-results.md` записать UUID четырёх заранее названных сессий (необязательный
Sol отдельно), их start-exclusive/end-inclusive boundaries и для каждой включённой строки
`turn_usage`: `id`, UTC timestamp, session, model/runtime, `cost_usd`, input/output/cache-read
tokens и роль строки в arm.
Цены берутся как записаны действующим `TOKEN_PRICES`; никаких процентов пула и ручной перецены.

Формулы, зафиксированные до запуска:

```text
C_A = сумма cost_usd всех строк свежего control full-cycle parent
C_B = сумма cost_usd всех строк свежего delegated full-cycle parent
      + всех строк Luna child
      + всех строк Sol child, только если production fallback сработал
delta_usd = C_A - C_B
```

B допускается к ценовому сравнению только если oracle побайтно равен `286720e6`, focused command
зелёная и все verbatim AC T1 доказаны. Если это выполнено и `delta_usd > 0`, для этого тикета
после координации осталось `delta_usd` долларов. При `delta_usd <= 0` экономия на T1 не
подтверждена. Если качество B не прошло, экономия не заявляется независимо от цены; фактическая
стоимость неуспешного пути всё равно публикуется. `C_harness` публикуется отдельно, чтобы не
выдать цену стенда за production coordination и не спрятать цену эксперимента. Поскольку этот
mixed turn нельзя причинно разделить, в отчёте он называется наблюдённым mixed experimental
overhead без сложения с arms. Исторические 6–10 % не пересчитываются по одной паре.

## Tickets

### T1 — доставить закрытый тикет исполнителю и принять по oracle
- **Files:** `pipelines/default/prompts/roles/full-cycle.md`,
  `pipelines/default/prompts/roles/worker.md`, `tests/test_default_pipeline.py`
- **Test:** `tests/test_default_pipeline.py::TestTicketDelegationGate` — committed RED in
  `286720e6`
- **AC:** `uv run python -m pytest tests/test_default_pipeline.py -k 't1_delegation' -q` is
  green; все предложения из раздела «Дословный production-текст» присутствуют дословно;
  внутренние ссылки после перенумерации равны `step 6` и `step 9`; `pipeline.yaml`,
  `model-routing.md` и `app/` не меняются; две составные и точечная мутации красные, после каждого отката
  выполнен `touch`, проверка якорей и повторный green run. Дословно для этой задачи:
  `Do not run the full suite; the focused and neighbouring commands named in this ticket replace Phase 3 step 6.`
- **blocked-by:** none

### T2 — измерить остаток в долларах на том же T1
- **Files:** `docs/tasks/223/ab-results.md`, `docs/tasks/223/report.md`
- **Test:** `oracle: none — результатом является стоимость живых model turns и ручная
  классификация их границ; behavioural или delivery check не может породить либо независимо
  подтвердить будущие строки turn_usage`
- **AC:** один control и один delegated run выполнены свежими matched `full-cycle` parents от
  `286720e6` по предрегистрации выше; обе копии изолированы frozen bundle, вторая — ещё и
  отрицательным `git cat-file` после первого arm; все session UUID/boundaries/raw rows и три
  формулы записаны в долларах; hashes обоих payload и точное совпадение B treatment с committed
  steps 3–4 записаны; classified COUNT/SUM совпали с interval query; verdict следует
  заранее заданному quality gate и знаку `delta_usd`; повторы не подмешаны; `oracle: none`
  оставляет T2 на дорогой стороне и T2 никогда не передаётся дешёвому исполнителю.
- **blocked-by:** T1

## Риски и откат

- Prompt-only контракт не гарантирует terminal token после manual kill/stop; это известная
  runtime-дыра #219, но не основание писать второй barrier в #223.
- Новый текст попадёт только в новые backend connections, как остальные role prompts; runtime
  контракт MCP не меняется.
- Один matched run отвечает только про T1. Положительный `delta_usd` не превращается в новый
  процент по всем `full-cycle` задачам.
- Откат production-изменения — удалить шаги 3–4, вернуть старую строку `<parallelism>` и удалить
  immutable guard; red oracle затем закономерно снова даёт exit 1.
