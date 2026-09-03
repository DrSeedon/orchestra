# Расход Codex Pro: Sol-воркеры против `codex_review`

**Срез:** 2026-07-24
**Среда:** Codex CLI `0.144.6`, ChatGPT Pro 5× (`plan_type=prolite`), `gpt-5.6-sol`

## Вывод

`codex_review` — заметный, но не главный потребитель: в текущем недельном окне
он дал **9.86% расхода Orchestra в Sol-кредитах**, а Sol-воркеры — **90.14%**.
На уровне всего аккаунта, где был ещё один внешний Codex-originator, доли
составили **9.78% / 89.46% / 0.76%**. За то же окно официальный meter вырос
с `0%` до `19%`; credit-share соответствует примерно **1.86 процентного пункта**
на review, **17.0 п.п.** на Orchestra workers и **0.14 п.п.** на внешний Codex.
Последнее — аллокация по измеренным кредитам, а не отдельный provider meter:
OpenAI публикует только общий целочисленный процент.

Типичный успешный review легче типичного завершённого worker turn:
**22.47 credits и 279 s** против **46.73 credits и 392 s**; отношение медиан
`0.481`. Но review — отдельный `codex exec` thread с `xhigh`, поэтому шесть
fresh review в выборке стоили уже **31.14 credits median**. Пять follow-up
`resume` стоили **9.59 credits median**, то есть на **69.2% меньше fresh**.

Переключить underlying CLI review на Spark технически можно через `-m
gpt-5.3-codex-spark` или `review_model`, но текущий MCP wrapper ещё не
предоставляет этот выбор caller-у. Это не доказанно «дешёвая версия Sol»:
у Spark **отдельный quota pool**, публичной credit-rate нет, а OpenAI прямо
называет модель less-capable. Живой A/B на этом отчёте подтвердил routing, но
Spark пропустил historical double-count, который нашёл Sol. Поэтому перенос
final/adversarial review на Spark quality gate **не прошёл**.

## Вопрос

- **Контекст:** Orchestra запускает workers на Sol и вызывает отдельный Sol
  через `codex_review`.
- **Изменение под проверкой:** маршрутизировать review дешевле либо в отдельный
  Spark pool.
- **Baseline:** нынешний `codex_review` на Sol `xhigh`.
- **Outcome:** доля credits/quota, tokens, model calls, wall time, cache reuse,
  failure waste и возможность сменить модель без недоказанного quality loss.

## Гипотезы и фальсификаторы

1. **H1:** `codex_review` — существенный quota drain, если он даёт хотя бы 10%
   Sol-кредитов Orchestra или его median cost не меньше 50% median worker turn.
   **Фальсификатор:** обе доли ниже порогов.
2. **H2:** review можно убрать из Sol pool через Spark. **Фальсификатор:**
   CLI не принимает model override, rollout остаётся на Sol либо отдельный
   `codex_spark` meter не меняется.
3. **H3:** Spark можно сделать default review без потери качества.
   **Фальсификатор:** официальный источник считает Spark less-capable либо
   контролируемый A/B пропускает load-bearing finding, найденный Sol.
4. **H4:** `/api/usage/daily` уже даёт нужный split. **Фальсификатор:** endpoint
   считает только `turn ended`, а bg review не создаёт такой log.

По заранее установленному критерию H1 формально **REFUTED**, но результат
пограничный: `9.86%` и `48.1%`. Практически это примерно один пункт из десяти,
а не «шум» и не главный виновник исчерпания.

## Метод измерения

1. В SQLite `/mnt/data/Projects/Python/orchestra/data/orchestra.db` взяты
   завершённые `bg_jobs` с message `Codex … done. Results in …`, timestamps review и worker
   `turn ended`, session cwd/model и `usage_snapshots`.
2. Из `~/.codex/sessions/**/rollout-*.jsonl` прочитаны только
   `session_meta`, `turn_context` и `token_count`; prompt, assistant и tool
   message bodies parser не читает.
3. События классифицированы по `originator + cwd + timestamp`:
   `codex_exec` внутри bg-job = review, `orchestra` внутри worker interval =
   worker. Активный незавершённый worker turn учтён в aggregate workers, но
   исключён из per-turn median.
4. Credits рассчитаны по официальной Sol rate-card [3]:

```text
credits = ((input - cached) × 125 + cached × 12.5 + output × 750) / 1,000,000
```

5. Primary split использует одно непрерывное текущее quota window:
   `2026-07-23 10:25:23Z → 2026-07-24 13:25:02Z` (`26.99 h`).
   Codex meter имел один reset `2026-07-30 10:25:45Z`, начал с `0%` и дошёл
   до `19%`. Наблюдался rounding jitter `1% ↔ 2%`; поэтому проценты не
   дифференцировались по отдельным concurrent jobs.
6. Воспроизводимый read-only parser:
   [`measure_usage.py`](measure_usage.py).

Команда:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run python \
  docs/tasks/codex-cost/measure_usage.py \
  --db /mnt/data/Projects/Python/orchestra/data/orchestra.db \
  --review-source bg_jobs \
  --start '2026-07-23T10:25:23.385493+00:00' \
  --end '2026-07-24T13:25:02.150353+00:00'
```

## Измерения текущего quota window

| Метрика | `codex_review` | Orchestra Sol workers |
|---|---:|---:|
| Завершённые units для median | 11 jobs | 31 turns |
| Дополнительные незавершённые calls | — | 53 |
| Model calls | 107 | 995 |
| Input tokens | 7,637,233 | 121,056,258 |
| Cached input | 6,797,568 | 116,029,440 |
| Cache ratio | 89.01% | 95.85% |
| Output tokens | 99,445 | 453,408 |
| Credits total | **264.511** | **2,418.776** |
| Доля внутри Orchestra | **9.86%** | **90.14%** |
| Median credits/unit | **22.474** | **46.726** |
| Median wall time | **279.1 s** | **391.9 s** |
| Median model calls/unit | **12** | **30** |

Ещё `20.516 credits` (`0.76%` account total) пришли от внешнего originator
`dm-game-master`; они не отнесены к Orchestra workers.

### Raw review jobs

| Job | Вид | s | Calls | Credits |
|---|---|---:|---:|---:|
| pricing research | fresh exec | 324.5 | 14 | 36.785 |
| pricing re-review | resume | 117.2 | 2 | 9.593 |
| non-tech models | fresh exec | 291.7 | 15 | 42.895 |
| sales plan | fresh exec | 279.1 | 7 | 17.936 |
| restart research | fresh exec | 281.6 | 12 | 24.005 |
| sales plan re-review | resume | 90.0 | 4 | 8.624 |
| restart re-review | resume | 89.4 | 3 | 5.422 |
| sales implementation | fresh review | 316.6 | 13 | 25.489 |
| sales implementation re-review | resume | 146.7 | 12 | 22.474 |
| HTML research | fresh exec | 408.5 | 18 | 49.187 |
| HTML re-review | resume | 109.9 | 7 | 22.102 |

Fresh против resume:

| Вид | n | Median credits | Median duration | Median calls | Total credits |
|---|---:|---:|---:|---:|---:|
| Fresh | 6 | 31.137 | 304.1 s | 13.5 | 196.297 |
| Resume | 5 | 9.593 | 109.9 s | 4 | 68.214 |

**CONFIRMED — direct measurement, evidence tier 1.**

## Что именно запускает `codex_review`

`app/mcp_stdio.py:841-1018`:

- fresh implementation review:
  `codex exec review --uncommitted … --full-auto --json`;
- file/plan/research review:
  `codex exec … -s workspace-write … --full-auto --json`;
- follow-up:
  `codex exec resume <uuid> …`;
- model и effort **не передаются**.

Установленный `~/.codex/config.toml` задаёт:

```toml
model = "gpt-5.6-sol"
model_reasoning_effort = "xhigh"
```

Все 11 rollout review подтвердили `model=gpt-5.6-sol`,
`effort=xhigh`, `originator=codex_exec`, `rate_limit.limit_id=codex`.
Для сравнения 30 из 31 измеренных worker turns шли на `high`, один на `xhigh`;
workers получают effort явно через `app/backend_codex.py`, review наследует
глобальный user config.

В review output было `69,185` reasoning tokens — `69.6%` всего output.
По rate-card они дают `51.889 credits`, то есть **19.6% review cost** и
**1.93% Orchestra Sol cost**. Это только верхняя граница выигрыша от снижения
effort: `high` не удалит все reasoning tokens, а влияние на findings не
измерено.

**CONFIRMED — code + installed CLI config/help + rollout measurement,
evidence tiers 1–2.**

## Исторические ошибки и timeout waste

В `logs` за `2026-07-18…24` есть ровно **75** tool calls:

- 63 completed;
- 6 timed out на 10 минутах;
- 6 failed.

Для поднабора, который однозначно связался с сохранёнными rollout metadata,
шесть timeout содержали **136 unique model calls / 308.548 credits**.
Двадцать успешно завершённых usage-bearing review в том же matched subset:
**203 unique calls / 498.371 credits**. Timeout jobs дали **38.2%** unique
measured review credits этого поднабора, хотя их было 6 против 20 successful.
Per-job median не публикуется: некоторые historical job intervals
перекрывались, поэтому однозначно разложить общие events между двумя jobs
нельзя. Три matched quota-limit failures не успели создать `token_count`.

Эти исторические числа не смешиваются с current-window split: старый период
пересекает другие reset windows и часть worktrees уже сменила cwd. Они
показывают только failure waste. В текущем окне все 11 review завершились.

**CONFIRMED для status counts и matched timeout subset; LIKELY для полного
historical credit total — не все старые jobs можно однозначно привязать после
worktree switch.**

## Можно ли перевести review на Spark

Underlying CLI технически позволяет это, MCP wrapper сейчас — нет:

- `codex exec review --help` в CLI `0.144.6` содержит `-m, --model`;
- `codex exec resume --help` также содержит `-m, --model`;
- live `codex debug models` видит `gpt-5.3-codex-spark`, context `128k`;
- официальный config поддерживает отдельный `review_model` [6];
- live usage snapshot показывает отдельный `codex_spark` meter (`0%` на срезе).
- `app/mcp_stdio.py:841-1018` не имеет `model`/`effort` parameters и не
  передаёт `-m`, поэтому для Orchestra routing требуется code change.

Но «дешевле» здесь означает **другой pool**, а не известное число credits:
официальная rate-card помечает Spark как `research preview` без чисел [3].
OpenAI называет Spark «fast, less-capable» и подтверждает отдельный,
динамический usage limit [4][5]. Предыдущее локальное исследование имело только
`n=3` на простом symbol lookup; review-quality parity там не проверялась [8].

### Живой Spark A/B

Тот же неизменный `research.md` был проверен Spark `xhigh`:

- rollout: `model=gpt-5.3-codex-spark`, input `3,431,159`, cached
  `3,316,608`, output `30,552`, reasoning `24,124`;
- Spark weekly meter вырос `0% → 1%`, Sol meter имел другой reset;
- raw rollout при этом вернул generic `limit_id=codex`, а не
  `codex_spark`. Следовательно, имя raw bucket нельзя использовать для
  доказательства общего pool; отдельность подтверждают meter/reset.

Spark дал `PASS w/ caveat` и воспроизвёл основную арифметику, но пропустил
перекрытие historical job intervals. Sol до своего timeout показал:

```text
completed: sumrows 237, unique 203, duplicates 34
timed_out: sumrows 181, unique 136, duplicates 45
```

Проверка кода подтвердила: старый historical parser мог отнести одно событие
двум overlapping jobs. Current-window jobs не пересекались, поэтому основной
split не изменился. Parser исправлен: уже claimed event больше не попадает в
следующий job. Это реальный A/B false negative Spark на load-bearing accounting
issue, поэтому H3 **REFUTED** для default final review.

Итого:

- **CONFIRMED:** routing возможен и убирает вызовы из стандартного Sol meter;
- **REFUTED:** Spark уже доказан как quality-equivalent final reviewer;
- **UNCERTAIN:** credit efficiency внутри Spark pool — rate не опубликован.

## Почему `/api/usage/daily` не отвечает на вопрос

Endpoint доступен и на 2026-07-24 вернул `100 turns / $116.11`, но
`app/routes/system.py:799-864` агрегирует только log rows с
`content LIKE '%turn ended%'`. `codex_review` живёт в `bg_jobs` и не создаёт
session `turn ended`, поэтому его tokens, `$` и credits отсутствуют в daily
chart. В текущем окне это скрывает **264.511 credits**, или `$10.58`
API-equivalent по той же Sol rate-card.

**CONFIRMED — endpoint code + live response + rollout accounting.**

## Counter-evidence и ограничения

- Выборка current-window review мала (`n=11`) и содержит research/plan review,
  а не только code diff. Это реальные production jobs, но не стандартный
  benchmark.
- Worker median посчитан по 31 завершённому Sol turn. Ещё 53 model calls
  активного turn включены в aggregate share, но не в median.
- SQLite хранит текущую модель session; после model switch старый `turn ended`
  нельзя классифицировать по `sessions.model`. Поэтому source of truth —
  rollout `turn_context`, не mutable DB field.
- Provider meter округлён до целого процента и иногда колеблется на 1 п.п.
  Credit split точнее для относительной доли, но provider не публикует размер
  100% weekly allowance в credits.
- Spark A/B выполнен только на одном accounting report. Он уже дал false
  negative против Sol, но `n=1` не измеряет error rate на маленьких code diff.
- Снижение reasoning effort может менять tool exploration и input tokens;
  `51.889 credits` — верхняя граница direct reasoning component, не прогноз
  реальной экономии.

## Рекомендации

1. **Не менять final review на Spark по умолчанию.** Потенциальный выигрыш —
   около `1.86` quota points в текущем окне; в живом A/B Spark пропустил
   verified accounting bug.
2. **Пилотировать Spark только на малых text-only diff с известными bugs.**
   Pass gate: Spark находит все P0/P1 Sol findings, не создаёт ложный blocker,
   укладывается в 128k. До 20–30 paired reviews решение не менять.
3. **Закрепить model/effort в `codex_review` явно.** Сейчас глобальный
   `~/.codex/config.toml` незаметно делает все review `xhigh`. Сначала A/B
   `Sol high` против `Sol xhigh`; измерять findings, credits и retries.
4. **Всегда продолжать через `resume=True` и тот же output.** Реальные median:
   `9.59` против `31.14 credits`; новый output/thread выбрасывает это
   преимущество.
5. **Пропускать обязательный review на действительно тривиальных изменениях**
   по уже действующему правилу `<50 lines, 1 function`; это надёжнее, чем
   подменять final reviewer менее способной моделью.
6. **Для больших research/docs review запрещать web и задавать узкий target.**
   Шесть historical timeout дали `308.55` unique credits — главный устранимый waste.
   Глобально снижать timeout ниже 5 минут нельзя: median fresh review уже
   `304.1 s`, часть нормальных jobs будет убита.
7. **Добавить usage telemetry самому `codex_review`.** Finalizer должен
   сохранять input/cached/output/reasoning/credits/duration/status в SQLite;
   `/api/usage/daily` затем покажет worker/review split без post-hoc rollout
   correlation.

## Adversarial second opinion

Два независимых reviewer-а проверили метод и выводы:

- Spark дал `PASS w/ caveat`, воспроизвёл основной split, но не заметил
  historical double-count overlapping jobs
  ([полный review](spark-review-research.md)).
- Sol нашёл double-count и ещё три воспроизводимых дефекта parser-а:
  `None` median crash, зависимость worker sample от mutable `sessions.model`
  и незамороженное окно. Все четыре проблемы исправлены и проверены повторным
  frozen run.
- После resume Sol подтвердил точные значения `11/31 units`,
  `264.511/2,418.776 credits`, `9.86%/90.14%`, не нашёл новых замечаний и
  выдал `APPROVED` ([полный review](codex-review-research.md)).

**CONFIRMED — adversarial code review + исправления + повторный измерительный
прогон.**

## Затрагиваемые файлы, если идти в план

- `app/mcp_stdio.py` — явные `model`/`effort`, детерминированный routing.
- `app/codex_review_artifact.py` — извлечение usage из JSONL и итог review.
- `app/db.py` / migration — хранение review usage.
- `app/routes/system.py` — добавить bg review к daily/provider breakdown.
- tests для CLI args, resume model consistency, credit formula, timeout/failure
  и daily aggregation.

## Источники

1. **Tier 1 — direct local measurement:** SQLite
   `/mnt/data/Projects/Python/orchestra/data/orchestra.db`, Codex rollout
   metadata/token counts, parser [`measure_usage.py`](measure_usage.py).
2. **Tier 2 — primary local source:** `app/mcp_stdio.py:841-1018`,
   `app/backend_codex.py:30-58,195-247,1082-1120`,
   `app/routes/system.py:799-864`.
3. **Tier 2 — OpenAI official:** [Codex pricing and credits](https://learn.chatgpt.com/docs/pricing#what-are-tokens-and-credits).
4. **Tier 2 — OpenAI official:** [Codex-Spark speed/positioning](https://learn.chatgpt.com/docs/agent-configuration/speed#codex-spark).
5. **Tier 2 — OpenAI official:** [Usage limits, shared Sol window and separate Spark limit](https://learn.chatgpt.com/docs/pricing#what-are-the-usage-limits-for-my-plan).
6. **Tier 2 — OpenAI official:** [Codex configuration sample (`review_model`)](https://learn.chatgpt.com/docs/config-file/config-sample).
7. **Tier 2 — installed primary artifact:** `codex-cli 0.144.6`,
   `codex exec review --help`, `codex exec resume --help`,
   `codex debug models`.
8. **Tier 2/1 — previous official-source research + local microbench:**
   [`docs/tasks/spark-comparison/research.md`](../spark-comparison/research.md).
9. **Tier 2 — independent Spark review:**
   [`spark-review-research.md`](spark-review-research.md).
10. **Tier 2 — independent Sol review + resumed approval:**
    [`codex-review-research.md`](codex-review-research.md).
