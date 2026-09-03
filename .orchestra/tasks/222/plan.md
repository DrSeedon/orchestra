# Plan #222 — узкий допуск Spark

## Outcome

Фаза 3 меняет ровно одного владельца правила — `pipelines/default/prompts/modules/model-routing.md`. Существующий Spark bullet заменяется целиком; второй формулировки про Spark не появляется. Правило остаётся под общим приоритетом Luna → Sol → Opus, добавленным в `a397c34c`, и лишь сужает уже существующий optional leaf route.

Второй одобренный пункт — цена/ёмкость пула — рассчитан в этой фазе и не превращается в кодовый ticket. Сырые числа и арифметика сохранены в `docs/tasks/222/pool-capacity-measurement.txt`.

## Изменение текста

Текущий Spark bullet заменить одной строкой следующего содержания; смысловые anchors ниже — часть AC, не пример:

```markdown
- **Spark** (`gpt-5.3-codex-spark`) — optional narrow fast/overflow leaf route only when the Codex pool is the binding constraint and all hold: text-only; ≤2 named files; ≤100K total initial context (system prompt + task + supplied files); every correctness-critical decision and value is explicit; an independent pre-existing oracle mechanically covers every correctness-critical criterion. Spark silently invents missing data: any missing fact or decision forbids this route. semantic prose, prompt work without literal anchors, review, research, architecture, vision, and security are forbidden. After any failed or incomplete Spark attempt, never retry Spark; hand the ticket to Luna or Sol by task class.
```

Причина `Spark silently invents missing data` остаётся в самом owner-rule: #222 получил 2/2 тихих выдумывания при недостающей константе, тогда как Luna 2/2 остановилась и спросила. Порог 100K — консервативный pre-spawn предел: 102K прошло 2/2, около 164K громко отказало 2/2; точный cliff не заявляется.

## Доставка и мутация oracle

Красный delivery-test впервые закоммичен в `3cbbcdcd`; после Codex review его anchors усилены полными clauses с полярностью запрета в `0a9438cb`:

```text
uv run python -m pytest -q tests/test_default_pipeline.py::TestDefaultRolesResolve::test_t1_spark_admission_rule_is_delivered_without_leaking
```

Текущий результат — exit 1 по отсутствующему поведению:

```text
AssertionError: Spark admission rule lacks 'text-only; ≤2 named files'
```

Проверка закрепляет семь ручных полных clauses в единственном Spark bullet, включая `are forbidden` и общий `After any failed or incomplete Spark attempt, never retry Spark`. Поэтому инверсия запрета не сохраняет anchor. Test требует ровно одно вхождение каждого clause в собранных prompt ролей `orchestrator`, `sub-orchestrator`, `full-cycle` и отсутствие всех clauses у terminal `worker`.

Oracle проверен до реализации на временном candidate-тексте:

- candidate в owner-модуле → exit 0, `1 passed`;
- составная мутация «тот же Spark rule остаётся в модуле и копируется в общий `base.md`» → exit 1 на `out.count(anchor) == 2`;
- оба файла восстановлены через `mv` + `touch`; `grep` дал один Spark bullet в owner и ноль нового anchor в `base.md`; исходный test снова exit 1.

В Фазе 3 мутация повторяется на реализованном тексте: зелёный baseline → красная составная мутация → `mv`-откат + `touch` + marker count → снова зелёный baseline.

## Ёмкость `codex_spark`

### Что измерено напрямую

Один полный Spark-side benchmark batch содержал 10 starts: 8 usage-bearing turns, 5 строгих PASS, 2 silent failures, 1 partial и 2 громких pre-output отказа. За весь непрерывный интервал integer-индикатор отдельного бакета изменился `0% → 4%`.

Для **точно такого же mix и текущей ёмкости preview-бакета** линейная экстраполяция даёт:

- `100 / 4 = 25` batch в неделю;
- около **250 starts**;
- около **200 usage-bearing turns**;
- только **125 strict PASS**, если сохранить тот же плохой mix.

Это единственная оценка, которая напрямую стоит на наблюдаемом endpoint delta. Она подтверждает опасение оркестратора: отдельный Spark-пул не удваивает ёмкость безусловно; он добавляет примерно 25 таких batch при текущем preview limit. OpenAI предупреждает, что отдельный Spark rate limit может меняться с demand, поэтому даже эта оценка — snapshot, не контракт.[1]

### Что можно оценить для нового admissible class

После нового gate из benchmark однозначно admissible только два code-run: text-case не имел per-criterion mechanical coverage, ambiguous-case имел недостающее решение, а measured `ctx100` фактически использовал 102,060 input tokens и уже выше нового `≤100K` порога.

Integer counter и задержка refresh не выделяют code-run в собственную дельту, поэтому прямой tasks/week для admissible code **не идентифицируется**. Два sensitivity proxy распределяют общие 4 п.п. по всем Spark turns:

- пропорционально raw input tokens → **2,181.9 code tasks/week**;
- пропорционально Luna-weighted fresh/cached/output mix → **1,530.1 code tasks/week**.

Рабочая оценка для capacity planning — **порядок 1.5–2.2K таких малых code tasks/week**, не confidence interval и не гарантия. Нижняя граница выбрана не из отдельного измерения Spark, а из более output-sensitive proxy. Пока неизвестны Spark credit weights, обещать эту ёмкость нельзя; для обязательств использовать только measured same-mix оценку 250 starts/week.

Для близкого к границе extraction proxy sensitivity ещё хуже: 573.9–1,866.5 tasks/week. Эта ячейка не проходит новый 100K gate и в правило ёмкости не входит.

### Доллары и отдельный дефект учёта

Долларовую цену Spark посчитать нельзя. Официальная token rate card помечает все три Spark ставки как `research preview` и отдельно говорит, что они не final.[2] Текущий source намеренно содержит:

```python
"gpt-5.3-codex-spark": None
```

Поэтому 10 строк benchmark имеют `virtual_cost: null`. Число `$0.44730484` в measurement — лишь стоимость тех же токенов **по Luna weights**, то есть sensitivity proxy; это не цена Spark. Оно соответствует `$0.11182621 Luna-equivalent / observed Spark pp` и не должно попадать в dashboard как Spark dollars.

Это отдельный дефект completion/accounting: `app/backend_codex.py::_codex_cost()` поднимает `ValueError("No published token price...")`, а `_turn_completed()` вызывает его до создания `turn_end`. Имеющийся тест `tests/test_backend_codex.py::test_spark_cost_fails_loud_without_a_published_price` подтверждён зелёным; в живой `turn_usage` нет ни одной строки `gpt-5.3-codex-spark`/`codex_spark`. Прямой benchmark обходил Orchestra backend, поэтому дефект не проявился в прогонах. Доказана потеря completion/accounting event; уже streamed text мог остаться видимым, его судьба этим source trace не установлена.

Исправление pricing/completion **не входит в #222** и не должно подменяться выдуманной ставкой. Новое правило сужает существующий Spark route, но production-spawn Spark остаётся небезопасным до отдельного тикета, который разведёт «цена неизвестна» и обязательный `turn_end`/учёт результата.

## Tickets

### T1 — Заменить Spark leaf rule без второго owner

- Files: `pipelines/default/prompts/modules/model-routing.md`; test уже в `tests/test_default_pipeline.py`
- Test: `tests/test_default_pipeline.py::TestDefaultRolesResolve::test_t1_spark_admission_rule_is_delivered_without_leaking` — committed RED in `0a9438cb` (initial oracle `3cbbcdcd`)
- RED: `AssertionError: Spark admission rule lacks 'text-only; ≤2 named files'`
- AC: `uv run python -m pytest -q tests/test_default_pipeline.py::TestDefaultRolesResolve::test_t1_spark_admission_rule_is_delivered_without_leaking` is green; Spark bullet содержит дословно все семь anchors из теста; candidate block выше заменяет текущий bullet, а не добавляется рядом; составная мутация в `base.md` красная, после `mv`-отката + `touch` и marker count тот же command снова зелёный
- blocked-by: none

## Не трогать

- `app/backend_codex.py`, `app/models.py`, `app/runtime_router.py`, quota thresholds и dashboard accounting — найденный pricing/runtime defect требует отдельной постановки.
- Общий приоритет Luna → Sol → Opus из `a397c34c`.
- Другие bullets и соседнюю формулировку про consequence asymmetry.
- Полный test suite и рестарт сервиса.

Миграции и обратная совместимость отсутствуют: это одна prompt-строка с уже закоммиченным delivery oracle.

## Источники

1. OpenAI, “Introducing GPT-5.3-Codex-Spark”: https://openai.com/index/introducing-gpt-5-3-codex-spark/ — separate preview limit may adjust with demand.
2. OpenAI, “Codex rate card”: https://help.openai.com/en/articles/20001106-codex-rate-card — usage token-based; Spark credit rates are research preview/not final.
