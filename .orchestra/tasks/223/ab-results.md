# #223 — confirmatory A/B стоимости делегирования T1

Дата: 2026-08-12. Статус: R1 excluded; R2 выполнен, intended Luna treatment провалил route
fidelity. Строгий confirmatory остаток не определён; фактический ошибочный delegated path дороже
control.

## Предрезультатная поправка treatment

План фиксировал B-treatment по steps 3–4 из `plan.md`. После plan review, но до этого A/B,
implementation review потребовал две защиты: запрет ослабления оракула через test infrastructure
и явное разрешение параллельности независимых непересекающихся тикетов. Они приняты, проверены и
смёржены в production commit `1caa26a6a8221bbe49070c87ea09abd6a382967a`.

Поэтому treatment этого прогона до раскрытия порядка зафиксирован как дословные текущие steps
3–4 из `roles/full-cycle.md` на `1caa26a6`, включая обе добавленные защиты. Старый plan-блок не
используется: он уже не является выкатываемым контрактом. Общий T1 output specification в A и B
одинаков и тоже содержит финальные защиты. Меняются только route suffix: A запрещает
делегирование, B требует применить production treatment. Sample, метрики и quality gate не
изменены.

## Замороженные предпосылки

- RED commit: `286720e6ff2ce862d09e28aad6532873abd4002a`.
- Frozen bundle: `data/task-223-ab/red-286720e6.bundle`; `git bundle verify` — complete history,
  `refs/heads/red = 286720e6ff2ce862d09e28aad6532873abd4002a`.
- A repository: `data/task-223-ab/control-repo`, отдельный `.git`, HEAD = RED.
- B repository: `data/task-223-ab/delegated-repo`, отдельный `.git`, HEAD = RED.
- До запуска объект production implementation `1caa26a6` отсутствует в обеих копиях:
  `git cat-file -e` завершился non-zero.
- Общий RED воспроизведён в обеих копиях одной командой:
  `uv run python -m pytest tests/test_default_pipeline.py -k 't1_delegation' -q` → exit 1,
  `4 failed, 2 passed, 81 deselected`; первая несущая строка —
  `AssertionError: roles/full-cycle.md is missing delegation clauses: [...]`.
- Дорогой parent baseline из backup живой SQLite до randomization:
  model `gpt-5.6-sol`, effort `xhigh`, role `full-cycle`, pipeline `default`, template hash
  `a92281f6`; source session UUID `8847d9b5-6c0f-4825-a366-024af2dc6735`.
- Confirmatory sample: ровно одна matched pair, без добора. Любой более поздний прогон навсегда
  exploratory и в headline не войдёт.

## Замороженные формулы и quality gate

```text
C_A = сумма cost_usd всех строк свежего control full-cycle parent
C_B = сумма cost_usd всех строк свежего delegated full-cycle parent
      + всех строк Luna child
      + всех строк Sol child, только если production fallback сработал
delta_usd = C_A - C_B
```

B входит в ценовое сравнение только при трёх условиях: все oracle/test-support paths побайтно
равны RED, focused command зелёная, все verbatim AC T1 доказаны. При `delta_usd > 0` остаток для
этого T1 равен `delta_usd`; при `delta_usd <= 0` экономия не подтверждена. Если quality gate не
пройден, экономия не заявляется независимо от цены. Пуловые проценты не являются метрикой.

## Payload и порядок

- Common prefix A/B побайтно совпадает (`diff` exit 0).
- Control payload: `data/task-223-ab/control-payload.md`, 5965 bytes,
  SHA-256 `9b81925018aae28b82755a407b8dd6b0ed076b3d79bc8be9cef1a95a6937248d`.
- Delegated payload: `data/task-223-ab/delegated-payload.md`, 8848 bytes,
  SHA-256 `eb4d2c128ac9ca94cb156ac0010ceb2e199a3785ba04a673439d0878a342049b`.
- B treatment побайтно совпадает с steps 3–4 из
  `pipelines/default/prompts/roles/full-cycle.md` на `1caa26a6` (`diff` exit 0).
- Имена заранее: parents `bench223-control`, `bench223-delegated`; Luna
  `bench223-luna`; Sol fallback, только если понадобится, `bench223-sol`.

Единственный random draw выполнен 2026-08-12 до запуска arms командой
`python3 -c 'import secrets; print(secrets.randbelow(2))'`: результат `0`, то есть порядок
**A/control → B/delegated**. Повторного draw не было и не будет.

Control boundary зафиксирована backup-снимком живой SQLite непосредственно перед spawn:
`start_after_id = 2497` (exclusive), snapshot UTC `2026-08-12T10:18:12Z`.

## Сырые строки и результат

### A/control — terminal precondition failure

- Session UUID: `646f7170-a3b4-4cf3-9b35-2751e2e7c435`.
- Model/effort/role: `gpt-5.6-sol` / `xhigh` / `full-cycle`.
- Template hash: `2f607c37`.
- Boundary: `2497 < turn_usage.id <= 2502`; end snapshot UTC
  `2026-08-12T10:21:06Z`.
- WIP: clean, no commit and no changed files relative to `red`.
- Terminal result: `WIP/STOP`. Parent обнаружил, что финальный T1 требует
  `plus these sentences verbatim:`, но immutable test на RED commit требует
  `plus this sentence verbatim:`. Сделать команду зелёной можно только мутацией теста либо
  добавлением compatibility-текста, которого нет в выкатываемом контракте.

| id | UTC timestamp | session | model/runtime | cost_usd | input | output | cache_read | cache_create | classification |
|---:|---|---|---|---:|---:|---:|---:|---:|---|
| 2502 | 2026-08-12T10:20:42.232868+00:00 | `bench223-control` | `gpt-5.6-sol` / `codex` | 0.638025000 | 543549 | 4020 | 488960 | 0 | invalid-control precondition turn |

Interval query и классификация обе дали `COUNT(*) = 1`, `SUM(cost_usd) = 0.638025000`.
Эта сумма не является `C_A`: arm не реализовал T1, а остановился до записи. Это наблюдённая цена
невалидной постановки и она исключена из `delta_usd`.

### Почему B не запущен

`git diff 286720e6 -- tests/test_default_pipeline.py` в production checkout показывает
24 изменённые строки (`22 insertions, 2 deletions`): после RED-коммита oracle был усилен под
финальный reviewed contract. Поэтому общий frozen oracle `286720e6` не соответствует
production output specification `1caa26a6`. Это нарушает обязательную предпосылку matched pair,
а не даёт нулевой либо отрицательный экономический результат.

B заведомо получил бы тот же конфликт. Его запуск после обнаружения не измерил бы цену
делегирования и добавил бы известный waste. Confirmatory `C_A`, `C_B` и `delta_usd` не определены.
Для нового валидного A/B нужен новый Phase 2 RED commit: финальные acceptance tests из
`1caa26a6`, но без implementation role changes; затем новая предрегистрация, новые parents и
новый единичный random draw. Текущую попытку нельзя подмешивать в эту пару.

## R2 — новая предрегистрация после исключённой попытки

Этот раздел и payload hashes зафиксированы до любого R2 parent turn. Первая попытка и её
`$0.638025000` исключены из R2 навсегда: она не могла измерить ни один arm, потому что её
output specification и oracle требовали взаимоисключающие строки. Ни один session, turn либо
repo первой попытки не входит в R2.

### Новый test-only RED

- R2 RED commit: `a93ee54c27cbd467b9c4af28a54e0a1bcdcc24fc`.
- Единственный diff от исходного `286720e6`:
  `tests/test_default_pipeline.py` — `22 insertions, 2 deletions`.
- Test blob побайтно равен `tests/test_default_pipeline.py` из production commit `1caa26a6`.
- Оба role blobs побайтно равны исходному RED `286720e6`; ни одной строки implementation в R2
  RED нет. Это проверено тремя независимыми `diff -u`, все exit 0.
- Frozen bundle `data/task-223-ab/red-r2.bundle` содержит complete history и
  `refs/heads/red = a93ee54c27cbd467b9c4af28a54e0a1bcdcc24fc`.
- Отдельные repos: `r2-control-repo`, `r2-delegated-repo`; HEAD обоих равен R2 RED, объект
  production implementation `1caa26a6` в обоих отсутствует.
- Focused command в обеих копиях: exit 1, `4 failed, 2 passed, 81 deselected`; первая несущая
  строка по-прежнему `roles/full-cycle.md is missing delegation clauses`, теперь среди missing
  anchors есть финальные test-infrastructure и independent-ticket clauses.

### Negative control стенда

До основного draw последовательно запускаются два свежих matched `full-cycle` parent:
`bench223r2-null-a` в A repo, затем `bench223r2-null-b` в B repo. Они получают один и тот же
read-only payload, не входят в implementation pipeline и не создают commit. Команды:

```bash
git rev-parse HEAD
git status --porcelain
python3 -c 'print("NOOP-223-R2")'
```

Gate проходит только если оба terminal reports дают один результат: HEAD = R2 RED, status
пуст, stdout = `NOOP-223-R2`, exit 0; а session metadata совпадают по model, effort, role,
pipeline и template hash. Долларовая цена обоих turns публикуется как negative-control overhead,
но точное равенство цены не является gate: число сгенерированных reasoning/output tokens
стохастично и не меняет наблюдаемый результат пустого действия. Любое расхождение gate отменяет
основной A/B до draw.

Null payload: 634 bytes, SHA-256
`2cd54ca23b480b6d9e4d8e9e639b748e579d41938dcbf6e2cf90fa7c97f425e7`.
Первый boundary: `start_after_id = 2511` exclusive, backup UTC `2026-08-12T10:28:19Z`.

Negative control **GREEN**:

- Null-A UUID `a88045aa-7825-4d36-85cd-367b781b8886`, boundary
  `2511 < id <= 2515`, terminal row 2515, `$0.297950000`.
- Null-B UUID `d59ef9b7-74c9-46e4-a5c7-f1f0c3022414`, boundary
  `2515 < id <= 2520`, terminal row 2520, `$0.311140000`.
- Оба: HEAD `a93ee54c27cbd467b9c4af28a54e0a1bcdcc24fc`, пустой
  `git status --porcelain`, stdout `NOOP-223-R2`, все command exits 0, clean WIP без commits.
- Metadata обоих совпали: `gpt-5.6-sol`, effort `xhigh`, role `full-cycle`, pipeline `default`,
  template hash `2f607c37`.
- В каждом интервале одна классифицированная строка; interval/classification COUNT и SUM
  совпадают. Общая наблюдённая цена negative control `$0.609090000`; в `C_A`, `C_B` и
  `delta_usd` она не входит.

Разница `$0.013190000` в model-turn cost при одинаковом наблюдаемом результате соответствует
разному stochastic output (760 против 1055 output tokens); это заранее исключённая из gate
метрика. Стенд прошёл предзарегистрированный equality gate, основной draw разрешён.

### Основная R2 pair

Основной draw выполняется ровно один раз и только после green negative control, той же
предзарегистрированной системной командой; `0 = A first`, `1 = B first`. Новые имена:
parents `bench223r2-control`, `bench223r2-delegated`; Luna `bench223r2-luna`; единственный
допустимый Sol fallback `bench223r2-sol`. Старые имена не переиспользуются.

- R2 control payload: 5965 bytes, SHA-256
  `2fd949fd21ebb617921128573ce10522a9cbb1eb21da62a182a50d621b3d985e`.
- R2 delegated payload: 8852 bytes, SHA-256
  `f637d031ee39fc9d5ff9aece21b13fdfd1cf80b069b1ab693a1a62a2f87f6d6b`.
- Common prefixes побайтно совпадают; B treatment побайтно совпадает с production steps 3–4
  на `1caa26a6`.
- Оба expensive parents: `gpt-5.6-sol`, `xhigh`, `full-cycle`, pipeline `default`. Если их
  metadata/template hash разойдутся, pair не стартует либо исключается до сравнения.
- Формулы и quality gate дословно те же, что выше; только RED заменён на R2 RED. Один matched
  run, без добора. Любой дополнительный run после результата навсегда exploratory.

Единственный R2 draw выполнен после green negative control командой
`python3 -c 'import secrets; print(secrets.randbelow(2))'`: результат `1`, то есть порядок
**B/delegated → A/control**. Повторного R2 draw не было и не будет.

R2 delegated boundary: `start_after_id = 2520` exclusive, backup UTC
`2026-08-12T10:31:52Z`; repo HEAD = R2 RED и status пуст непосредственно перед spawn.

### R2 B/delegated — implementation green, route fidelity failed

- Parent UUID `45b96b64-f72a-4826-b420-810f2927412d`, model/effort
  `gpt-5.6-sol` / `xhigh`, template hash `2f607c37`.
- Child UUID `7b78372c-c779-40ca-a9dc-8a4b7377bab1`; Sol fallback отсутствовал.
- Boundary `2520 < id <= 2537`, terminal snapshot UTC `2026-08-12T10:46:31Z`.
- Executor commit `fa5d77273f0dd2b7afbeba2d512c389cff671555`, accepted parent target
  `de3aa7d5ac93d39d01f04ac16de0700ec4733de8`, внешний experimental target после
  parent merge `d3de79dfc3c6ca4361f000c1e32cd9eb52e4375a`.
- Parent и child завершили clean; child был archived после успешного внутреннего merge.
- Независимая проверка после внешнего merge: oracle, весь `tests/`, `app/`, `pipeline.yaml` и
  `model-routing.md` побайтно равны R2 RED; focused `6 passed, 81 deselected in 6.59s`, neighbour
  `231 passed in 9.01s`; все hand-written T1 anchors присутствуют.

| id | UTC timestamp | session | model/runtime | cost_usd | input | output | cache_read | cache_create | classification |
|---:|---|---|---|---:|---:|---:|---:|---:|---|
| 2528 | 2026-08-12T10:40:40.781466+00:00 | `bench223r2-delegated` | `gpt-5.6-sol` / `codex` | 0.900241000 | 669773 | 7352 | 593152 | 0 | B parent dispatch |
| 2533 | 2026-08-12T10:43:26.512599+00:00 | `bench223r2-luna` | `gpt-5.6-terra` / `codex` | 0.375354400 | 1012208 | 5311 | 951552 | 0 | B child implementation |
| 2537 | 2026-08-12T10:46:13.837747+00:00 | `bench223r2-delegated` | `gpt-5.6-sol` / `codex` | 0.756113000 | 1003831 | 5009 | 980736 | 0 | B parent acceptance |

Interval query и классификация: `COUNT(*) = 3`, `SUM(cost_usd) = 2.031708400` в обоих
представлениях. Из них parent `$1.656354000`, child `$0.375354400`; child — 18.47% фактической
B-суммы, parent — 81.53%.

Но это **не валидный Luna arm**. Parent дважды вызвал `spawn_worker` с дословным
`model: "gpt-5.6-terra"`; второй вызов создал ребёнка. Это подтверждено raw `logs` tool-call и
живой строкой `sessions.model`, а не narrative DONE. Treatment и model-routing требовали Luna
(`gpt-5.6-luna`) и прямо запрещали Terra. Поэтому B прошёл code/oracle gate, но провалил route
fidelity; его `$2.031708400` публикуется как стоимость фактического ошибочного пути и не может
доказывать экономику Luna. Повтор B после результата запрещён и не выполняется.

Механизм координации совпал с #219: до child был один parent turn, terminal child report породил
второй дорогой acceptance turn. Для одного ребёнка barrier не может убрать этот единственный
приёмочный wake; факт и суммы отправлены `feat-fan-research` напрямую.

Перед вторым arm control repo по-прежнему стоит на R2 RED с пустым status и не содержит ни
child commit `fa5d7727`, ни внутренний accepted commit `de3aa7d5`, ни внешний experimental
commit `d3de79df` (`git cat-file -e` non-zero для каждого). R2 control boundary:
`start_after_id = 2540` exclusive, backup UTC `2026-08-12T10:49:44Z`.

### R2 A/control — green

- Parent UUID `83974f51-ec3b-41ee-b7f0-423a7d879f5f`, model/effort
  `gpt-5.6-sol` / `xhigh`, template hash `2f607c37`, то есть metadata expensive parent
  совпадают с B.
- Boundary `2540 < id <= 2557`, terminal snapshot UTC `2026-08-12T11:03:56Z`.
- Executor commit `79168d3`, внешний experimental target после merge
  `2b57990840f3191d9fe3857a3ca57a6a88f19d9b`; WIP после merge clean.
- Oracle, весь `tests/`, `app/`, `pipeline.yaml` и `model-routing.md` побайтно равны R2 RED;
  focused `6 passed, 81 deselected in 6.79s`, neighbour `231 passed in 11.60s`; все verbatim
  AC T1 доказаны.

| id | UTC timestamp | session | model/runtime | cost_usd | input | output | cache_read | cache_create | classification |
|---:|---|---|---|---:|---:|---:|---:|---:|---|
| 2553 | 2026-08-12T10:58:33.072073+00:00 | `bench223r2-control` | `gpt-5.6-sol` / `codex` | 0.963806000 | 936196 | 4811 | 858112 | 0 | A direct implementation |

Interval query и классификация: `COUNT(*) = 1`, `SUM(cost_usd) = 0.963806000` в обоих
представлениях. Поэтому `C_A = $0.963806000`.

## Итог R2

Строгий confirmatory результат: **нет валидного `C_B` и нет `delta_usd` для Luna**. Причина не
в качестве кода и не в цене: B реализовал тот же T1 зелёным, но production parent выбрал
запрещённую Terra вместо обязательной Luna. Подменять `sessions.model` именем ребёнка либо
пересчитывать Terra-токены по тарифу Luna нельзя.

Для наблюдённого фактического пути, отдельно от confirmatory headline:

```text
C_A = $0.963806000
C_B_actual_terra = $2.031708400
delta_actual = C_A - C_B_actual_terra = -$1.067902400
```

Фактическое делегирование стоило в 2.108 раза больше control (`+110.80%`). Даже без child
parent coordination стоила `$1.656354000`, то есть на `$0.692548000` больше всего direct arm;
child был лишь 18.47% B, parent — 81.53%. Результат независимо повторяет порядок величины #219:
один parent turn вокруг сообщения ребёнка стоит примерно `$0.76–0.90`, а дешёвый исполнитель
не является главным компонентом полной цены.

### Аудит вывода «даже бесплатный ребёнок проигрывает»

Арифметически observed parent total действительно выше всего A на 71.86%:
`$1.656354 / $0.963806 = 1.7186`. Но считать `$1.656354` нижней границей production
coordination нельзя. Raw trace показывает известную надбавку, не относящуюся к цене ребёнка:

- dispatch сделал три `spawn_worker`, первые два получили 4xx из-за ограничений isolated
  nested-repo harness; после них parent дважды диагностировал git layout и отдельно корректировал
  адрес terminal report;
- acceptance после уже зелёных тестов сделал три диагностических Bash-вызова и `report_bug` по
  постороннему дефекту squash subject.

Всего parent сделал 19 tool calls; 9 перечисленных вызовов являются известной harness/bug
надбавкой. Ни одного разбора подмены Terra внутри B не было — её обнаружил внешний измеряющий
parent после terminal boundary. `turn_usage` даёт лишь две агрегированные parent rows и не
позволяет честно назначить этим 9 вызовам точную долларовую часть.

Чтобы parent стал не дороже A, из него надо вычесть `$0.692548`, или 41.81%. Известная надбавка
составляет 47.37% tool-call count, но tool count не равен стоимости конкретного вызова; поэтому
она делает смену знака возможной, а не доказывает её. Следовательно, из этого прогона нельзя
вывести, что последовательное делегирование проигрывает даже с ребёнком ценой ноль. Доказан
более узкий вывод: **наблюдённый ошибочный B-path проиграл, а чистая coordination floor и знак
Luna-path остались неидентифицированы**.

Экспериментальный overhead, исключённый из arms: `$0.638025000` за R1 с невалидной постановкой
и `$0.609090000` за два negative-control turns, всего `$1.247115000`. Остальная работа текущего
длинного parent смешана с построением стенда, проверкой, документацией и расследованием Terra;
она не выдаётся за production coordination и не добавляется к arms.

Вывод относится к текущему prompt-only production workflow: он не подтвердил экономию и,
важнее, не обеспечил заявленный маршрут. Добирать прогон после раскрытия запрещённого model id
означало бы оптимизировать после результата, поэтому повторов нет. Дефект admission, допускающий
`gpt-5.6-terra` при активном `Terra — do not use`, отправлен через `report_bug`.
