# Report #222 — Spark admission rule

## Итог

Единственный Spark owner-bullet в `pipelines/default/prompts/modules/model-routing.md` заменён узким fast/overflow gate. Общий приоритет Luna → Sol → Opus и остальные model bullets не менялись.

Правило теперь сообщает не только условия, но и цену их нарушения:

- Spark — отдельный, но маленький quota wallet, не бесплатная ёмкость; при текущем preview limit прямой замер даёт 25 идентичных benchmark batch/week = 250 starts = 200 usage-bearing turns = 125 strict PASS.
- Долларовая цена Spark неизвестна (`research preview`, локально `price=None`); любая money summary со Spark неполна.
- Допуск: text-only, ≤2 named files, ≤100K всего initial context, все correctness-critical решения и значения заданы, независимый pre-existing oracle механически покрывает каждый criterion.
- Причина: при недостающих данных Spark молча выдумал ответ 2/2 и оба раза промахнулся (19/42 и 18/42); Luna 2/2 остановилась и спросила.
- На ~164K Spark 2/2 отказал громко до ответа, поэтому 100K — запас, а измеренный context failure не был тихой порчей.
- Semantic prose/prompt без literal anchors, review, research, architecture, vision и security запрещены; после любого failed/incomplete Spark attempt ретрая на Spark нет.

## Файлы

- `pipelines/default/prompts/modules/model-routing.md:13` — единственный owner-rule Spark, +1/-1 line.
- `tests/test_default_pipeline.py:179` — delivery/non-leakage oracle; в Phase 3 добавлено +5/-1 anchor lines под обязательные wallet/price/failure facts.
- `CHANGELOG.md:7` — ручная запись v2.38.2, +8 lines.
- `docs/tasks/222/report.md` — этот отчёт.

## Ticket

### T1 — Заменить Spark leaf rule без второго owner

DONE. Named test проверяет eleven polarity-bearing clauses в самом Spark bullet, ровно одну доставку в prompts `orchestrator`, `sub-orchestrator`, `full-cycle` и непротекание в terminal `worker`.

## Проверки

Перед production-edit accepted oracle был красным:

```text
uv run python -m pytest -q tests/test_default_pipeline.py::TestDefaultRolesResolve::test_t1_spark_admission_rule_is_delivered_without_leaking
AssertionError: Spark admission rule lacks 'text-only; ≤2 named files'
1 failed
```

После усиления новыми AC и до production-edit он оставался красным:

```text
AssertionError: Spark admission rule lacks 'separate but small quota wallet, not free capacity'
1 failed
```

После реализации named command:

```text
uv run python -m pytest -q tests/test_default_pipeline.py::TestDefaultRolesResolve::test_t1_spark_admission_rule_is_delivered_without_leaking
.                                                                        [100%]
1 passed in 4.96s
```

Смежные routing checks:

```text
uv run python -m pytest -q \
  tests/test_default_pipeline.py::TestDefaultRolesResolve::test_t1_spark_admission_rule_is_delivered_without_leaking \
  tests/test_default_pipeline.py::TestDefaultRolesResolve::test_model_routing_reaches_only_spawn_capable_roles \
  tests/test_default_pipeline.py::test_pool_priority_rule_reaches_roles_that_receive_model_routing \
  tests/test_default_pipeline.py::test_obsolete_priority_formulation_is_gone_everywhere
....                                                                     [100%]
4 passed in 4.86s
```

Одиночная мутация `Spark silently invents missing data → Spark safely requests missing data`:

```text
single_mutation_rc=1
AssertionError: Spark admission rule lacks 'Spark silently invents missing data: ...'
restored_green_rc=0
restored_marker_count=1
```

Обязательная составная мутация «rule удалён из owner и целиком посажен в общий `base.md`»:

```text
composite_remove_owner_copy_base_rc=1
AssertionError: Spark admission must have exactly one owner rule
restored_green_rc=0
route_spark_count=1
base_anchor_count=0
```

Оба отката завершались `touch` восстановленных файлов; после каждого named test снова был зелёным. Полный suite не запускался по прямому ограничению задачи. `uv.lock` не менялся. Рестарт не выполнялся.

## Pre-mortem и проверки потребителя

1. **Правило скопируют в общий слой, terminal worker получит routing.** Проверка: составная мутация owner→`base.md`; test красный, после restore worker снова не содержит ни одного clause.
2. **Причину допуска инвертируют, оставив короткое слово-якорь.** Проверка: одиночная polarity mutation; полный clause исчезает и test краснеет.
3. **Новый bullet затронет приоритет Luna → Sol → Opus либо вернёт obsolete wording.** Проверка: два существующих priority tests входят в финальные 4/4.
4. **128K прочитают как безопасный рабочий бюджет.** Проверка: owner и test фиксируют полный initial context ≤100K и отдельно объясняют громкий ~164K отказ.
5. **Отсутствующую цену прочитают как $0.** Проверка: owner и Changelog требуют `UNKNOWN`/incomplete; runtime/accounting fix вынесен в #301 без выдуманной ставки.

## Найденный дефект → #301

Создана отдельная tracker task **#301 “Spark: unknown price drops turn_end and understates Codex dollars”**, priority high. `CODEX_TOKEN_PRICES["gpt-5.3-codex-spark"] = None`; `_codex_cost()` бросает до создания `turn_end`. Доказана потеря completion/accounting event; уже streamed text мог остаться видимым, его судьба не установлена.

До исправления #301 **любые долларовые числа по Codex runtime занижены неизвестно на сколько**, если в рассматриваемом периоде мог работать Spark. Это относится и к денежным сравнениям трёх сегодняшних задач: отсутствие/null Spark cost не равно `$0` и делает totals неполными.

## Сохранённая граница доказательства Phase 1

**Строгая физическая недостижимость ответа не доказана.** Общий Git object store и известные корни были закрыты, обращений к сети не наблюдалось, но сеть и остальной `$HOME` физически оставались доступны. Эта оговорка не ослаблена и не заменена утверждением о полной изоляции.

## Breaking / TODO

- Breaking: none; меняется только решение будущих orchestrator/full-cycle спавнов.
- TODO: #301 должен сохранить `turn_end` и явно маркировать unknown/incomplete dollars; не входит в #222.
- Codex implementation review skipped: production diff — одна owner prompt-line и пять новых test anchors, вне shared runtime; exact candidate уже прошёл двухраундовый plan review, а реализация проверена delivery + single/composite mutations.
