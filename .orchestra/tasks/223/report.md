# #223 — отчёт Phase 3

Дата: 2026-08-12.

## Результат

T1 смёржен в `main` как `1caa26a6`: `full-cycle` теперь делегирует закрытый тикет с
зафиксированным RED-оракулом одному worker, принимает только после своей проверки и ограничивает
маршрут одной Luna-попыткой и одним Sol fallback. `oracle: none` никогда не делегируется.
`worker` и конкретный payload запрещают менять как полученный тест, так и поддерживающую его
test infrastructure.

T2 не подтвердил экономию текущего prompt-only workflow. Валидный direct control стоил
`$0.963806000`. Делегированный путь создал green implementation за `$2.031708400`, но parent
вызвал запрещённую `gpt-5.6-terra` вместо обязательной `gpt-5.6-luna`; поэтому строгого `C_B` и
`delta_usd` для Luna нет. Фактическая, но не confirmatory, дельта Terra-path равна
`-$1.067902400`: он был дороже control в 2.108 раза.

Observed B-parent `$1.656354000` сам по себе на 71.86% дороже всего A, но это не чистая
coordination floor. В его две агрегированные строки попали две отклонённые попытки spawn и
диагностика isolated nested repo, а после успешной приёмки — отдельное расследование и
`report_bug` про squash subject. Это 9 из 19 parent tool calls. Для смены знака достаточно снять
`$0.692548000` (41.81% parent total), а `turn_usage` не разделяет стоимость внутри строки.
Поэтому вывод «даже бесплатный ребёнок проигрывает» этим прогоном не доказан.

## Изменения

- `pipelines/default/prompts/roles/full-cycle.md` (`+27/-11`, merge `1caa26a6`):
  delegability, payload, terminal reporting, immutable oracle/test infrastructure, одна попытка
  Luna → одна Sol → возврат дорогой стороне, parent acceptance, независимая параллельность.
- `pipelines/default/prompts/roles/worker.md` (`+2`): immutable test и supporting-infrastructure
  guard с `WIP/STOP`.
- `tests/test_default_pipeline.py` (`+115`): delivery/source ownership/non-leakage oracle T1.
- `docs/tasks/223/ab-results.md`: полная предрегистрация, UUID/boundaries/raw rows, excluded R1,
  test-only R2 RED, negative control, долларовый итог и route-fidelity failure.
- `docs/tasks/223/codex-review-impl.md`: финальный Round 2 `APPROVED`, новых findings нет.

`app/`, `pipeline.yaml` и `model-routing.md` не менялись.

## Tickets

### T1 — выполнен

Focused output целиком:

```text
warning: `VIRTUAL_ENV=/home/kesha/orchestra/.venv` does not match the project environment path `.venv` and will be ignored; use `--active` to target the active environment instead
......                                                                   [100%]
6 passed, 81 deselected in 6.62s
```

Neighbour output целиком:

```text
warning: `VIRTUAL_ENV=/home/kesha/orchestra/.venv` does not match the project environment path `.venv` and will be ignored; use `--active` to target the active environment instead
........................................................................ [ 31%]
........................................................................ [ 62%]
........................................................................ [ 93%]
...............                                                          [100%]
231 passed in 9.65s
```
- Составная мутация «dispatch исчез из role и якорь посажен в base» → `6 failed`; откат,
  `touch`, marker check → `6 passed`.
- Составная мутация worker/test-infrastructure guards → `3 failed`; откат → `6 passed`.
- Точечные мутации parent byte-compare и independent-ticket clause также красные; после каждого
  отката focused command зелёная.
- Сборка production prompt: immutable guard доезжает в `worker` и payload `full-cycle`;
  `orchestrator` и `sub-orchestrator` получают 0 delegation anchors.
- Codex Round 2: `APPROVED`; прежние findings про косвенное ослабление oracle и глобальную
  сериализацию исправлены.

### T2 — выполнен как `oracle: none`

Для живых будущих строк `turn_usage` независимой команды-оракула не существует; поэтому T2
остался на дорогой стороне и проверен по ручному предзарегистрированному протоколу.

Первая попытка навсегда excluded: oracle изменился после исходного RED (`22 additions,
2 deletions`) и конфликтовал с финальным contract. Parent корректно дал `WIP/STOP`; его
`$0.638025000` опубликованы отдельно как цена невалидной постановки. Compatibility-текст не был
добавлен: он зазеленил бы старый тест, но измерял бы не production contract.

R2 test-only RED `a93ee54c` содержит финальный test blob из `1caa26a6` и ни одной role-строки
реализации. Два no-op parent дали одинаковые HEAD/status/stdout и совпавшие metadata/template
hash; их overhead `$0.609090000` исключён из arms. Единственный draw дал порядок B → A.

Raw arm totals:

| Срез | Rows | Стоимость |
|---|---:|---:|
| A direct, valid | 1 | `$0.963806000` |
| B parent | 2 | `$1.656354000` |
| B child, фактически Terra | 1 | `$0.375354400` |
| B actual total | 3 | `$2.031708400` |
| `A - B_actual` | — | `-$1.067902400` |

Parent составил 81.53% B, child 18.47%. Два parent turns `$0.900241` и `$0.756113` независимо
воспроизвели механизм #219: одно terminal сообщение ребёнка будит дорогого parent примерно на
тот же порядок стоимости. При одном child barrier не может убрать единственный acceptance wake;
результат передан `feat-fan-research`.

Проверка нулевой цены ребёнка: арифметика 71.86% верна для observed totals, но не для
контрфактического чистого механизма. Terra parent не анализировал — подмена была найдена позже
вне arm. Зато raw trace содержит 9 известных non-treatment calls: два rejected spawn, git-layout
диагностику, correction message и расследование squash bug. Их точная надбавка в долларах
неидентифицируема внутри двух `turn_usage` rows; она может превышать требуемые для смены знака
`$0.692548`. Главный вывод поэтому остаётся узким: фактический путь проиграл, но знак чистого
Luna-path и coordination floor не установлены.

## Pre-mortem и проверки

- Потеря delivery/non-leakage → source anchors, четыре role assemblies и составные мутации.
- Ослабление oracle через helper/config → worker prohibition + parent rejection anchor;
  отдельная мутация обоих guards красная.
- Скрытая сериализация независимых tickets → explicit Phase 3 clause и красная point mutation.
- Загрязнение replay готовой реализацией → frozen bundles, отдельные `.git`, отрицательные
  `git cat-file -e` до каждого arm.
- Изменение oracle после RED → R1 excluded; R2 test blob сравнен с `1caa26a6`, role blobs — с
  исходным `286720e6`, затем committed отдельно.
- Асимметрия стенда → одинаковая no-op пара до draw; outputs и metadata совпали.
- Подмена модели именем worker → ground truth только `sessions.model` и raw spawn tool call;
  это поймало Terra, несмотря на имя `bench223r2-luna`.
- Пропуск/double count turns → exact UUID + exclusive/inclusive boundaries; COUNT/SUM каждой
  классификации сверены с interval query.

## Breaking и TODO

Breaking changes: нет.

Найден platform defect: `spawn_worker` принимает модель, прямо запрещённую активным
`model-routing`; вызов и admission не имеют server-side enforcement. Отправлен `report_bug`
`spawn_worker admits model explicitly forbidden by active model-routing policy`. Отдельный
platform bug про дублирование `#223:` в squash subject отправил экспериментальный parent.

Экономика именно Luna остаётся неизвестной: повтор после раскрытия route violation запрещён
предрегистрацией, а явное принуждение модели в новом payload измеряло бы уже другой treatment.
Текущий production workflow по наблюдённому фактическому пути экономию не подтвердил и не
обеспечил собственный route contract.

Memory: none — reusable freeze-oracle правило уже добавлено владельцем в project rules, а
task-specific evidence сохранено здесь и в `ab-results.md`.

## Дополнение 13.08.2026 — T3: явно порученные test-layer edits

### Результат и выбранная граница

`worker.md:18` теперь сохраняет test-layer запрет по умолчанию, но допускает ровно одно
исключение: **direct orchestrator assignment должен прямо разрешить конкретные test-layer edits**.
Worker не вправе вывести разрешение из необходимости реализации. Полученный acceptance test
всегда остаётся вне исключения и immutable.

`full-cycle` исключение намеренно не получил. **Делегирование test-layer тикетов через
`full-cycle` остаётся заблокированным:** эта роль сама выдаёт oracle и payload исполнителю, а
живой #235 требует только прямого назначения оркестратором. Это выбранная authority boundary,
не пропущенный случай; расширять её молча нельзя.

T3 реализован Luna-исполнителем `impl223-test-layer-auth`, модель проверена по фактическому
`list_agents`: `gpt-5.6-luna`. Его commit `254836d8` содержал только `worker.md` (`+1/-1`),
замороженный test blob относительно RED `5667a32f` не изменился. После parent acceptance commit
смёржен в эту ветку как `3b28f78c`.

### Файлы

- `pipelines/default/prompts/roles/worker.md` (`+1/-1`) — точное узкое исключение.
- `tests/test_default_pipeline.py` (`+48/-6` относительно базы дополнения) — source ownership,
  worker delivery, role isolation и независимый immutable-oracle guard; тесты заморожены в
  `5667a32f` до реализации.
- `docs/tasks/223/plan.md`, `codex-review-test-layer-exception-{research,plan,impl}.md` —
  предрегистрация и три внешних вердикта.

`roles/full-cycle.md`, `base.md`, orchestrator-роли, modules, `pipeline.yaml` и `app/` в финальном
diff не менялись. `base.md` изменялся только внутри откатанной составной мутации.

### RED → GREEN

Перед правкой exact command дал `1 failed, 2 passed, 92 deselected`; несущая строка:

```text
AssertionError: roles/worker.md must own the exception: 'Sole exception: test-layer edits are permitted only when a direct orchestrator assignment explicitly authorizes those specific edits.'
```

После parent merge focused output целиком:

```text
warning: `VIRTUAL_ENV=/home/kesha/orchestra/.venv` does not match the project environment path `.venv` and will be ignored; use `--active` to target the active environment instead
...                                                                      [100%]
3 passed, 92 deselected in 4.66s
```

Соседний #223 delegation oracle:

```text
warning: `VIRTUAL_ENV=/home/kesha/orchestra/.venv` does not match the project environment path `.venv` and will be ignored; use `--active` to target the active environment instead
......                                                                   [100%]
6 passed, 89 deselected in 4.93s
```

Полный suite не запускался по явному ограничению задачи.

### Побайтная неизменность соседних guards

Hashes до и после реализации совпали:

| Guard | До | После |
|---|---|---|
| `sed -n '13,16p' ...` — `Never author` paragraph | `8818fafeadd08c4eb11e37d189dc0af25dadd6ea91b48a1a5922070778368a0e` | `8818fafeadd08c4eb11e37d189dc0af25dadd6ea91b48a1a5922070778368a0e` |
| `sed -n '17p' ...` — received oracle immutable | `9f7396eab9b8f48b86fe51e727fa902dfab4bd428bca9d5a7021ca66eb631d4b` | `9f7396eab9b8f48b86fe51e727fa902dfab4bd428bca9d5a7021ca66eb631d4b` |

### Delivery, isolation и мутации

Сборка после всех откатов дала число вхождений каждого из четырёх exception anchors:

```text
worker [1, 1, 1, 1]
full-cycle [0, 0, 0, 0]
orchestrator [0, 0, 0, 0]
sub-orchestrator [0, 0, 0, 0]
```

Каждая мутация начиналась со свежего backup и завершалась restore + `touch` + marker count +
green rerun:

1. Exception удалён из `worker.md` →
   `test_t3_worker_test_layer_authorization_is_worker_owned_and_delivered`: `1 failed`;
   после отката `3 passed, 92 deselected`.
2. Старый безусловный immutable anchor удалён отдельно →
   `test_t3_worker_test_layer_authorization_keeps_oracle_unconditionally_immutable`:
   `1 failed`; после отката `3 passed, 92 deselected`.
3. Exception удалён из `worker.md` и целиком посажен в общий `base.md` → focused command:
   `2 failed, 1 passed, 92 deselected`; покраснели и source ownership, и non-leakage. После
   отката обоих файлов assembly снова дал worker=1 и остальные роли=0, focused — `3 passed`.

### Pre-mortem

- **Worker сам выводит разрешение из задачи** → отдельный literal anchor `never infer it from
  what the implementation requires` и source/delivery oracle.
- **Широкое разрешение поглощает received oracle** → прежний guard имеет отдельный hash, тест и
  независимую красную мутацию; новое правило также явно исключает received acceptance test.
- **Exception протекает через общий слой** → source ownership + assembled zero для трёх ролей;
  составная `worker → base` мутация дала два независимых падения.
- **Соседний контракт #223 ломается** → `-k 't1_delegation'`: 6 passed.
- **Следующий автор «дочиняет» full-cycle path** → намеренная блокировка и её authority-причина
  записаны в плане и этом отчёте.

### Codex review и platform note

Codex просмотрел фактический diff и выполнил объединённую команду: `9 passed, 86 deselected`.
Дословный вердикт: **`APPROVED`**. Findings: `No blocking issues, suggestions, or questions.`
Артефакт содержит дословную строку diff, поэтому review состоялся:

```diff
+        "Without that explicit authorization, report `WIP/STOP`.",
```

Побочный usage insert после сохранения review упал:
`OperationalError: table turn_usage has no column named cost_unaccounted`. Артефакт и вердикт
не потеряны; platform bug отправлен отдельно. Это рассинхрон текущей live-схемы до restart с уже
смёрженным on-disk `turn_usage_add`, не дефект T3.

### Breaking и память

Breaking: прямое задание оркестратора теперь может явно разрешить конкретные test-layer edits;
без явного текста прежний `WIP/STOP` остаётся. `full-cycle` path не расширен.

Memory: none — reusable workflow уже принадлежит project rules; authority boundary и evidence
этой правки сохранены в task artifacts.
