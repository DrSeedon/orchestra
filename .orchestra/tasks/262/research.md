# #262 — экономика подписок: Claude, Codex, Grok и Antigravity

**Прямой ответ.** На снимке **13.08.2026 08:24 UTC** первым кончится основной Codex:
он вырос `0 → 73%` за 4.45 ч, и линейный остаток при том же утреннем темпе — **1.65 ч**.
Claude weekly был на 66% и при среднем темпе текущего окна имел **25.0 ч**; его свежий 5h-
бакет был на 3% и должен был сброситься раньше, чем дойти до 100%. В деньгах API-эквивалента
один наблюдённый weekly pool даёт: Claude **$1,836** на завершённой неделе и предварительно
**$2,802** на нынешнем mix, Codex main **$541–568**, Grok ориентировочно **$171–214**,
Antigravity **$0.589** на единственном коротком опыте неизвестного tier. После приведения к
4.348 недели/месяц это **$39.9–60.9**, **$23.5–24.7** и **$24.8–31.0 API-эквивалента на
$1 подписки** соответственно. Antigravity честно сравнить по доллару нельзя: free имеет
нулевой знаменатель, купленный за 90 ₽ Jio Pro не проходит product-region gate, а измеренный
pool принадлежит другому аккаунту неизвестного tier. Экономическая таблица **не меняет**
операционную политику «Codex жжём первым»: цена остановки Claude выше цены остановки Codex.

Дата исследования: **13.08.2026**. Все доллары ниже — виртуальный API-эквивалент, не списание
денег поверх подписки.

## 1. Вопрос, гипотезы и критерий

**Контекст.** У Orchestra четыре независимых подписочных двери с несовпадающими метриками
квоты и качеством телеметрии.

**Изменение под проверкой.** Сравнить их одной таблицей по реальной цене подписки,
API-эквиваленту хода, ёмкости quota pool и текущему времени до исчерпания.

**Baseline.** Не сравнивать по названию поля `input_tokens`, по имени агента или по числу
prompts; считать только после проверки семантики каждого runtime и физического потолка окна.

**Решающий исход.** API-$ на $ месячной подписки при текущем workload mix; отдельно — ETA первого
pool по прямому процентному счётчику.

Рассматривались две конкурирующие гипотезы:

1. **H1: более дорогая подписка даёт пропорционально больше API-эквивалента.** Фальсификатор —
   порядок API-$/$ не совпадает с ценой тарифа. **REFUTED:** Claude $200 даёт лучший измеренный
   коэффициент, но Codex $100 и Grok $30 близки друг к другу.
2. **H2: API-$/$ — стабильное свойство подписки.** Фальсификатор — один и тот же pool даёт
   существенно разный API-эквивалент на разных workload mix. **REFUTED для Claude:** завершённая
   неделя дала $1,836, а текущие 66% экстраполируются в $2,802 (+53%). Это характеристика
   нагрузки, а не печатная ёмкость тарифа.
3. **H3: все четыре runtime можно ранжировать одним числом.** Фальсификатор — неизвестный tier,
   отсутствующая median либо неизвестная цена модели. **REFUTED:** Antigravity и Spark не имеют
   достаточных данных для честного единственного числа.

## 2. Снимок, фильтры и знаменатели

Живая SQLite снята **только** через `sqlite3.Connection.backup` из URI с `mode=ro` в
`/home/kesha/orchestra-262-research.db`. Frozen snapshot:

```text
usage_snapshots  9,356  2026-07-05T05:19:58Z → 2026-08-13T08:24:08Z
turn_usage       3,160  2026-08-03T06:33:39Z → 2026-08-13T08:25:25Z
PRAGMA quick_check = ok
```

Воспроизводящий расчёт и замороженный manifest входов лежат рядом с исследованием:

```bash
python3 docs/tasks/262/measure.py /home/kesha/orchestra-262-research.db
```

[`measure.py`](measure.py) проверяет SHA256 снимка и всех локальных источников, ограничивает
таблицы frozen `max(id)` и воспроизводит знаменатели, turn economics, pool estimates, месячную
нормализацию, API-$/$ и проверки потолка. [`measurement-inputs.json`](measurement-inputs.json)
фиксирует commit, SHA256, цены и
ручные входы Grok/Antigravity. Копия rate card здесь — **manifest доказательства на 13.08**, а не
второй production-owner цен; production-owner остаётся в `app/models.py` и
`app/backend_codex.py`.

### 2.1 Грязь, исключённая до любого деления

В live `turn_usage` оказались **26 synthetic rows**: `scope='/test'`,
`session_id='test-001'` — 25 Claude и 1 Codex. Их сумма всего **$1.0041406**, но Codex-row
на 03.08 сдвигает `MIN(ts)` на пять суток раньше первой usage-bearing работы и занижает
нормированный недельный Codex burn. Поэтому предикат исключения применён **до** count, median,
границ периода и суммы:

```sql
NOT (scope = '/test' OR session_id LIKE 'test-%')
```

Отдельная задача на исправление учёта — **#263**; в #262 код не менялся.

Второй знаменатель: реальная Codex-попытка 05.08 завершилась `error` с нулём токенов и $0.
Для цены submitted turn она остаётся честным нулевым ходом; для начала периода расхода она
не годится. Нормирование по времени начинается с первой строки, где положителен хотя бы один
из `cost/input/output/cache_read`.

### 2.2 Первая настоящая работа и период

| runtime | первая usage-bearing работа UTC | последняя UTC | terminal rows | usage-bearing | активных UTC-дней | wall-span |
|---|---|---|---:|---:|---:|---:|
| Claude | **03.08 06:33:39** | 13.08 08:24:56 | 2,341 | 2,316 | 9 | 10.077 суток |
| Codex | **08.08 07:41:40** | 13.08 08:25:25 | 793 | 792 | 6 | 5.030 суток |
| Grok | **13.08 07:08:31** | 13.08 07:26:37 | 20 raw traces | 20 | 1 | 18.1 мин |
| Antigravity | **13.08, точное время не сохранено** | тот же batch | 13 results | 13 | 1 | не сохранён |

Grok-время восстановлено из UUIDv7 `sessionId` 20 raw JSONL. Antigravity сохранил агрегат,
но не timestamps отдельных results; точность нельзя дорисовывать задним числом.

Другие проверки знаменателей:

- `event_id` уникален по схеме; production rows с `cost_unaccounted=1` — **0**;
- Claude: 25 нулевых terminal rows лежат **внутри** периода и не меняют края; Codex: одна
  нулевая строка лежит до периода и потому не двигает начало burn;
- модель всегда бралась из `turn_usage.model`: Claude — 2,339 Opus + 2 Haiku; Codex — 742 Sol,
  50 Luna, 1 Terra. Имена агентов не использовались;
- нормирование — по непрерывному wall-span между первой/последней usage-bearing строкой, а не
  по числу активных дней. Это сохраняет паузы из-за quota как часть реальной пропускной способности.

**Confidence: CONFIRMED** — прямой snapshot и два независимых SQL-предиката края периода.

## 3. Семантика токенов: проверка по всем строкам

| runtime | rows | `cache_read ≤ input` | `cache_read > input` | вывод |
|---|---:|---:|---:|---|
| Claude | 2,341 | 49 | **2,292** | cache **не входит** в `input`; прибавлять отдельными тарифами |
| Codex | 793 | **793** | 0 | cache **входит** в `input`; сначала вычитать cached/write из input |
| Antigravity aggregate | 1 | да | — | `276,577 input + 3,445 output = 280,022 total`; cache 256,572 — subset input |
| Grok | 20 traces | provider ticks primary | — | стоимость берётся из `total_cost_usd_ticks`; fallback aggregate не billing truth для tool-loop |

Из-за этого одна «универсальная» формула дала бы headline с неверным знаком. Для Claude
использована текущая `TOKEN_PRICES` и формула fresh + cache-read 10% + cache-create 125% +
output. Для Codex использована `CODEX_TOKEN_PRICES` и ровно семантика `_codex_cost`: fresh =
input − cached − write. Постановка называла `TOKEN_PRICES` единственным владельцем, но текущий
код намеренно хранит Codex в `app/backend_codex.py`, Grok — в `app/backend_grok.py`, а Spark —
`None`. Воспроизводящий manifest фиксирует считанные оттуда значения и SHA владельцев: это
не исполняемый production price table и не может разойтись с dashboard молча.

Stored `turn_usage.cost_usd` и пересчёт по **текущей** цене не обязаны совпадать: старые rows
сохраняют цену своего дня. Для сравнения на 13.08 ниже везде один текущий rate card. Stored
суммы приведены только как audit: Claude $4,276.92 против current-rate $4,505.48; Codex
$1,466.31 против $1,466.11.

**Confidence: CONFIRMED** — all-row invariant + прочитанные production cost functions.

## 4. Реальная цена и форма лимитов

| runtime | реальные деньги | что включено и чем исчерпывается | confidence |
|---|---:|---|---|
| Claude Max 20× | **$200/мес** | rolling 5h + weekly all-model; оба 0–100%, блокирует первый достигший 100%; абсолютных токенов provider не раскрывает | CONFIRMED — official plan + live windows [S1][M2] |
| Codex Pro `prolite` | **$100/мес** | main 7d token-credit pool + отдельный Spark 7d pool; точное число credits тарифа не опубликовано; reset credits могут обнулить main раньше ожидаемого | CONFIRMED price / measured limits [S2][S3][M3] |
| SuperGrok | **$30/мес** | один shared weekly allowance для платных Grok products; на 100% paid features pause, если не купить extra credits; бесплатные Chat/Voice живут отдельно | LIKELY account tier, CONFIRMED public price/limit [S4][S5] |
| Antigravity Individual | **$0/мес** | meaningful weekly Gemini quota; work-based, не request count | CONFIRMED docs [S6][S7] |
| Google AI Pro retail | **$19.99/мес list** | 5h refresh до weekly cap + higher weekly; overage credits отдельно | CONFIRMED docs [S7][S8] |
| Купленный Jio AI Pro | **90 ₽ всего** за 18 мес по данным юзера; 5 ₽/мес amortized | Google называет Jio benefit AI Pro на 18 мес, но текущий Jio account получает Antigravity location error; его повышенный pool не измерен | CONFIRMED cash input / REFUTED как доступный runtime [S9][M4] |

По курсу ЦБ РФ на 13.08.2026 `1 USD = 82.9977 RUB`: 90 ₽ = **$1.084 total**,
или **$0.0602/мес** при делении на 18. Это цена приобретения промо, а не официальный retail fee.[S10]

### Нюансы окна

- Claude weekly в нашей истории сбрасывается во вторник 07:00 UTC; 5h якорится первым запросом
  после закрытия предыдущего окна.[M2]
- Codex `resets_at` не годится как стабильный календарный anchor: в текущем последнем segment
  шесть разных значений, а счётчик реально упал `92 → 0` 13.08 около 03:36. Ёмкость считается
  по наблюдаемому monotonic segment, не как `now` относительно прогнозного reset.
- Grok live telemetry показывает один `primary`, `window_minutes=10080`; официальный FAQ
  подтверждает один shared weekly allowance.[S5]
- Antigravity control показал **две** weekly groups: Gemini и Claude/GPT. Current docs при этом
  обещают third-party models явно Ultra, а pricing surface шире; registry/quota group не доказывает
  inference entitlement. Tier control-account неизвестен.[S6][S7][M4]

## 5. Цена хода и выжигание за измеренный период

Mean/median считаются по всем production terminal rows, включая честные $0 ошибки: они тоже были
запущенными ходами. Test rows исключены.

| runtime / выборка | n | mean API-$ / ход | median | API-$ всего | нормировано на 7d |
|---|---:|---:|---:|---:|---:|
| Claude production | 2,341 | **$1.9246** | **$1.0545** | **$4,505.48** | **$3,129.65** |
| Codex production | 793 | **$1.8488** | **$0.6956** | **$1,466.11** | **$2,040.16** |
| Grok known current traces (18 prereg + 2 pilot) | 20 | **$0.4282** | **$0.4038** | **$8.5644** | не нормировать 18 мин |
| Antigravity `gemini-3.6-flash-low` aggregate | 13 | **$0.00726** | **нет per-turn rows** | **$0.09433** | не нормировать один batch |

Antigravity API-equivalent:

```text
uncached input = 276,577 - 256,572 = 20,005
$ = 20,005×$1.50/M + 256,572×$0.15/M + 3,445×$7.50/M
  = $0.0943308
```

Thinking 1,546 не прибавлялся повторно: Google включает thinking в output price, а
`total=input+output` показывает, что это subset, не четвёртый токеновый поток.[S11]

Ограничение Grok: один terminal usage не кумулятивен по внутреннему X tool-loop. На 18
preregistered ходах reported $8.2302408, а условная формула с каждым completed X call дала
$8.2802408; расхождение **0.6%** в одной строке. Это известная точность этой выборки, не
доказательство универсального undercount.[M5]

## 6. Сколько подписка даёт API-эквивалента

Для сопоставления weekly pool умножается на `365.2425 / 12 / 7 = 4.348125` недели/месяц.
Это нормализация, а не обещание provider: workload mix меняет результат.

| runtime / basis | наблюдаемый full weekly pool API-$ | приблизительно ходов/pool | API-$ / месяц | API-$ на $ подписки |
|---|---:|---:|---:|---:|
| Claude, завершённая неделя 04–10.08 | **$1,836.28** | **994** | $7,984 | **$39.92** |
| Claude, текущий mix (`66%`, provisional) | **$2,802.11** | **1,458** | $12,184 | **$60.92** |
| Codex main, три последних segments | **$541–568** (current $552.96) | current **258** | $2,352–2,467 | **$23.52–24.67** |
| Grok, `8→12` immediate / `8→13` delayed | **$214 / $171** | **500 / 400 short traces** | $931 / $745 | **$31.03 / $24.83** |
| Antigravity, unknown-tier control | **$0.589** | **81 short results** | $2.563 | **не вычисляется** |

### Что означают и не означают эти числа

1. **Claude — диапазон, не константа.** Первый partial segment `38→80` эквивалентен **$1,860.30**
   на full pool и отличается от завершённой недели $1,836.28 лишь на 1.3%. Текущий `0→66`
   даёт $2,802,
   но неделя ещё не закончена. Разброс реальный и объясняет, почему API-$/$ нельзя переносить
   между workload mix.
2. **Codex main воспроизводится.** Три достаточных segment дали $541.03, $567.35, $552.96.
   Предыдущий независимый credit-calibration #190 дал около $566 на pool — тот же диапазон.[M3]
3. **Codex package недооценён на Spark.** Spark сейчас 1%, но его API price намеренно `None`;
   в `turn_usage` Spark rows нет. Подставлять ноль запрещено, поэтому $23.5–24.7 — main-only
   lower bound, не полная ценность $100 plan.
4. **Grok — условный bracket.** Ближайший snapshot с 8% записан через **0.436 с после старта**
   первого известного trace, но до его завершения; это pre-completion, не доказанный pre-start
   baseline. Сразу после batch было 12%, через 36 мин — 13%. Полная стоимость известных traces
   $8.5644. Диапазон $171–214 условно приписывает batch 4–5 п.п.; неизвестный расход в первые
   0.436 с и provider lag не отделены, поэтому точное full-pool число **UNCERTAIN**.
5. **Antigravity нельзя подписать free или Pro.** До 13 probes было 100%, после — 83.9955%; full
   pool линейно равен $0.589 и 81 такому result. Но control — бывший corporate account неизвестного
   tier, а Jio Pro заблокирован регионом. Делить $2.563 monthly-equivalent на 90 ₽ было бы
   соединением чужого числителя с чужим знаменателем.

Число ходов особенно несопоставимо: Grok и Antigravity — короткие probes, Claude/Codex — реальные
длинные agent turns. API-$ лучше нормирует модельную работу, но не качество результата.

## 7. Кто кончится первым при текущем темпе

Snapshot `2026-08-13T08:24:08Z`; ETA — простая линейная экстраполяция последнего наблюдаемого
монотонного segment, не forecast будущего расписания.

| pool | now | наблюдаемый segment | pace | ETA 100% | до reported reset | вывод |
|---|---:|---|---:|---:|---:|---|
| **Codex main** | 73% | `0→73` за 4.45 ч | 16.40 pp/h | **1.65 ч** | 163.5 ч | **первый** |
| Grok primary | 13% | `8→13` за 1.18 ч | 4.25 pp/h | **20.5 ч** | 83.5 ч | второй только если benchmark burst продолжится |
| Claude weekly | 66% | `0→66` за 48.56 ч | 1.36 pp/h | **25.0 ч** | 118.6 ч | structural deficit сохраняется |
| Claude 5h | 3% | `0→3` за 0.34 ч | 8.92 pp/h | 10.9 ч | **4.60 ч** | reset раньше упора |
| Codex Spark | 1% | цена и стабильный segment неизвестны | — | — | 165.4 ч | не binding |
| Antigravity | route не запущен | один experiment | — | — | — | current pace отсутствует |

Codex ETA отражает утренний всплеск и может замедлиться, но ordering устойчив: чтобы Claude
обогнал его, Codex pace должен упасть более чем в 15 раз немедленно. Grok ETA слабая — после
08:03 counter уже стоял; без новых Grok tasks фактический pace равен нулю.

## 8. Проверка физического потолка

Legacy denormalized нули не использовались: weekly series извлечены только из непустого
`provider_usage.<bucket>.windows`. Последний monotonic segment переякоряется на minimum; reset =
падение от segment maximum (`5 pp` Anthropic, `10 pp` Codex/Grok).

Потолок ниже задан **независимо** от найденных reset-сегментов; иначе проверка была бы
тавтологией (`100 × число сегментов`, определённых тем же рядом).

| counter | независимая граница периода | наблюдаемый расход | независимый потолок | результат |
|---|---|---:|---:|---|
| Claude weekly | три календарных окна вторник→вторник | **208 pp** | 300 pp | **PASS** |
| Codex main | reset credits не сохраняются | **278 pp** | неизвестен | **UNAVAILABLE** |
| Grok primary | один неизменный `reset_at`/weekly id | **5 pp** | 100 pp | **PASS** |
| Antigravity Gemini | один before/after weekly batch | **16.0045 pp** | 100 pp | **PASS** |

У Codex нельзя честно получить независимое число доступных pool: provider умеет расходовать
reset credits, но их consumption в snapshot не сохраняется. Пять сегментов из самого ряда
нельзя превращать в потолок 500 pp. Более слабая проверка качества всё же проходит: сумма raw
positive increments равна сумме segment ranges (**278 pp**), то есть внутри выделенных сегментов
нет ложного нуля с последующим повторным подъёмом. У Claude weekly то же равенство даёт 208 pp.
У 5h Claude raw positive 1,539 против range 1,519 на 28 окнах — 20 pp мелкого jitter; этот ряд
в расчёт weekly capacity не входил.

**CONFIRMED** для Claude/Grok/Antigravity; **UNAVAILABLE** как независимый physical-ceiling test
для Codex. Проверка отвергает класс #162 там, где календарная/внешняя граница наблюдаема, и не
выдаёт производную от данных границу за независимое доказательство.

## 9. Confidence и контр-доказательства

| finding | confidence | основание |
|---|---|---|
| Claude/Codex mean, median, period burn | **CONFIRMED** | frozen live backup; all-row price/cache calculation |
| Claude full-pool API-$ | **CONFIRMED completed / LIKELY current** | одна завершённая неделя + independent partial; current only 66% |
| Codex main $541–568/pool | **CONFIRMED** | three segments + independent #190 calibration |
| Grok $171–214/pool | **UNCERTAIN** | one rounded 4–5 pp delta; missing exact billing/tool-loop truth |
| Antigravity $0.589 unknown-tier pool | **LIKELY** | exact before/after and official prices; one workload/tier only |
| Jio Pro work/$ | **UNAVAILABLE** | owned account fails eligibility; no quota observation |
| Codex exhausts first at snapshot pace | **CONFIRMED as linear ordering** | direct current segments; not a schedule forecast |

Counter-evidence, kept rather than averaged away:

- Claude completed and current mix differ by 53% in API-$ per pool → no intrinsic dollar capacity.
- Codex delivered multiple early resets/credits; multiplying one ordinary weekly pool understates
  actual short-period throughput, but treating those resets as recurring monthly capacity would overstate it.
- Grok имел 8% до первого известного завершения, но snapshot на 0.436 с позже старта trace;
  поэтому привлекательный расчёт `$8.23 / 8%` отвергнут, а `8→12/13` оставлен условным bracket.
- Antigravity retail docs, current plan docs and live corporate control do not identify one common tier;
  the missing join is the main result, not a footnote.
- API-equivalent rewards expensive list pricing and says nothing about correctness. Routing must still
  incorporate task fitness and cost of exhausting each pool.

## 10. Что нужно измерять дальше

1. **Grok:** persist every `turn_completed` into `turn_usage`, sample exact weekly percent before/after
   each batch, and retain provider billing/credit delta when xAI exposes it. Median then becomes fleet,
   not benchmark-only.
2. **Antigravity:** obtain an owned eligible account; record per-result token rows plus before/after quota
   for both Gemini and third-party groups; separately repeat on known Free and known AI Pro accounts.
3. **Spark:** no money summary until the published API price ceases to be `None`; never treat unknown as zero.
4. **Claude:** close the current weekly window and retain its final mix; one more full Max20 week decides
   whether $2.8k is a regime shift or partial-window selection.

## Sources

Measurements are evidence tier 1; official pages/code are tier 2.

- **[M1] Direct measurement:** `/home/kesha/orchestra-262-research.db`, created by
  `sqlite3.Connection.backup`, SHA256
  `d6e34b41dc031162feb95040c50dc6d258363ca357baa378a02eeddff4d7e3b0`;
  [`measure.py`](measure.py) + [`measurement-inputs.json`](measurement-inputs.json), 13.08.2026.
- **[M2] Direct measurement:** [`docs/tasks/186/research.md`](../186/research.md) — Claude reset/window
  semantics and dirty-zero classifier.
- **[M3] Direct measurement:** [`docs/tasks/190/research.md`](../190/research.md) and
  [`docs/tasks/190/web-pricing.md`](../190/web-pricing.md) — Codex credit calibration and `prolite` mapping.
- **[M4] Direct measurement:** [`docs/tasks/249/research.md`](../249/research.md) — Antigravity account,
  quota groups, 13-result before/after experiment.
- **[M5] Direct measurement:** [`docs/tasks/251/research.md`](../251/research.md),
  [`docs/tasks/251/score.json`](../251/score.json), `docs/tasks/251/raw/*.jsonl` — Grok 20 traces and
  tool-loop reconciliation.
- **[S1] Anthropic:** [Choosing a Claude Plan](https://support.anthropic.com/en/articles/11049762-choosing-a-claude-ai-plan),
  [Using Claude Code with Pro or Max](https://support.anthropic.com/en/articles/11145838-using-claude-code-with-your-pro-or-max-plan).
- **[S2] OpenAI:** [About ChatGPT Pro tiers](https://help.openai.com/en/articles/9793128-about-chatgpt-pro-plans).
- **[S3] OpenAI:** [Codex rate card](https://help.openai.com/en/articles/20001106).
- **[S4] xAI:** [Grok plans and pricing](https://x.ai/pricing).
- **[S5] xAI:** [Grok usage and weekly limits FAQ](https://docs.x.ai/grok/faq).
- **[S6] Google:** [Antigravity pricing](https://antigravity.google/pricing).
- **[S7] Google:** [Antigravity plans and quotas](https://antigravity.google/docs/plans).
- **[S8] Google:** [Google One plans](https://one.google.com/about/plans).
- **[S9] Google:** [Jio Google AI Pro offer](https://blog.google/intl/en-in/company-news/partnering-with-reliance-to-bring-the-best-of-google-ai-to-more-people-across-india/).
- **[S10] ЦБ РФ:** [Курс валют на 13.08.2026](https://www.cbr.ru/scripts/XML_daily.asp?date_req=13/08/2026).
- **[S11] Google:** [Gemini Developer API pricing](https://ai.google.dev/gemini-api/docs/pricing) —
  Gemini 3.6 Flash standard $1.50 input / $0.15 cached / $7.50 output, thinking included in output.
