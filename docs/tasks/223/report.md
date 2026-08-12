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
