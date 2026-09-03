# #440 — формула кредитов Claude Max на нашей телеметрии

Дата замера: 2026-09-02. Фаза 1; реализации и плана нет.

## Прямой ответ

### Q1 — работает ли формула на нашей телеметрии

**Нет при принятом для расчёта потолке 11,000,000: утверждение «формула с 11M воспроизводится из
`turn_usage` по соседним округлённым снимкам» REFUTED. Поскольку сам 11M не восстановлен, это не
опровержение ни самой формулы, ни альтернативного потолка.**

Primary — соседние снимки с разрывом не более 900 с, без пересечения reset, с хотя бы одной
Claude-строкой между снимками. Совпадение означает
`abs(predicted_pp - observed_delta_pp) <= 1`.

| Контур | Cache write по цене входа | Cache write не считается |
|---|---:|---:|
| Ноутбук | **916/1494 = 61.31%** | **957/1494 = 64.06%** |
| VPS | **874/1500 = 58.27%** | **946/1500 = 63.07%** |

Обе доли недостаточны для «формула сходится». Более того, выбор варианта cache-write меняет знак
при смене информативности:

| Срез | Write | No-write |
|---|---:|---:|
| Ноутбук, наблюдаемая дельта ≥2 п.п. | **84/829 = 10.13%** | **32/829 = 3.86%** |
| VPS, наблюдаемая дельта ≥2 п.п. | **160/760 = 21.05%** | **111/760 = 14.61%** |

На primary no-write формально чаще попадает в округление; на больших дельтах write чаще. Парные
исходы показывают ту же инверсию: ноутбук primary `write-only=68`, `no-write-only=109`, а на
`>=2 п.п.` — `68` против `16`; VPS primary `118` против `190`, на `>=2 п.п.` — `118` против `69`.
**Ни один вариант cache-write не идентифицирован.** Исключение правого цензурирования при 100%
ничего не меняет: ноутбук write/no-write `902/1473=61.24%` / `940/1473=63.82%`; VPS
`862/1478=58.32%` / `932/1478=63.06%`.

Высокая доля на всех парах была бы ложным положительным результатом: ноутбук даёт
`3128/3980=78.59%`, VPS `4216/4989=84.51%` для write, но этот знаменатель включает тысячи пар без
локального трафика и без движения целого процента. Поэтому primary заранее требует хотя бы одну
строку `turn_usage`.

Прямое доказательство неучтённого относительно таблицы движения: при **нуле** строк `turn_usage`
счётчик всё равно вырос в
`624` парах на ноутбуке (суммарно `1196` п.п.) и в `505` парах на VPS (`748` п.п.). Официальная
документация независимо говорит, что Claude, Claude Code и другие поверхности делят один лимит
[4]. Наблюдение совместимо с трафиком других consumers, пропусками сбора и коррекцией snapshot;
оно доказывает недиагностичность formula-from-`turn_usage`, но не выбирает одну из этих причин.

Счётчики `sessions` до/после каждого финального прогона: ноутбук **598 → 598**, VPS
**469 → 469**. Обе БД открывались только URI `mode=ro`; `cp` и backup не использовались.

**Fact-check rating:** 🚫 FALSE для условного узкого утверждения «формула с потолком 11M
воспроизводится текущей `turn_usage`»; ❓ UNVERIFIABLE для более сильного утверждения «сама
тарифная формула или потолок неверны».

### Q2 — чем объясняется 1.93×

**Названные кандидаты не дали подтверждённого объяснения 1.93×. Три отвергнуты как причина, два
остаются непроверенными. Главное ограничение разрешения — сравнение точной формулы с коэффициентом
регрессии, сырые четыре источника которой в этой задаче недоступны.**

Чистый Opus output по таблице даёт `30.3030 п.п./МТок` при потолке 11,000,000. Коэффициент
`15.68 п.п./МТок` подразумевал бы потолок **21,258,503.40 кредита**, то есть
**1.932591× 11,000,000**. Это арифметический implied value, не измеренный потолок.

#### (а) В выборке не только Opus — REFUTED как объяснение

- Ноутбук primary: `3526` Opus-строк и `17` Sonnet-строк. Пересчёт всех строк как Opus меняет
  predicted credits лишь на `20,655 / 162,862,541 = 0.01268%`.
- VPS primary: `4088` Opus и `2` Haiku. All-Opus меняет результат на
  `40,474 / 295,469,163 = 0.01370%`.

Помодельный расчёт выполнен по **колонке `turn_usage.model`**, не по имени агента. Наблюдаемая
смесь на два порядка меньше требуемого эффекта 93%.

#### (б) `output_tokens` не включают reasoning — REFUTED

Production-код сохраняет именно `ResultMessage.usage['output_tokens']`
(`app/backend_claude.py:1399-1413`) [7]. Anthropic прямо определяет thinking tokens как billed
output tokens, включая скрытое/omitted thinking [3]. Локальный контроль по сохранённым transcript:

- `581` JSONL-файл, `28,235` уникальных usage-records после дедупа по `message.id`;
- `11,647` записей содержат `output_tokens_details`;
- `660` записей имеют положительный `thinking_tokens`, сумма `405,074`;
- нарушений `thinking_tokens > output_tokens`: **0/11,647**.

То есть billing reasoning уже лежит внутри `output_tokens`; отсутствие видимого reasoning-текста не
объясняет множитель.

#### (в) Вход и cache write были приписаны output — UNCERTAIN

Разложение raw predicted credits в primary:

| Контур | Fresh input | Cache write | Output |
|---|---:|---:|---:|
| Ноутбук | 65,140 (0.040%) | 110,370,248 (67.77%) | 52,425,996.67 (32.19%) |
| VPS | 4,242,022.93 (1.44%) | 181,468,354.27 (61.42%) | 109,757,435.33 (37.15%) |

Положительный input/write увеличивает interval predicted movement на данный output. Но направление
смещения **маргинального OLS output-коэффициента** зависит от interval covariance input/write с
output; одних агрегированных totals для sign verdict недостаточно. Предоставленная
четырёхисточниковая регрессия имела отдельный write-терм `1.71` [6], однако её interval rows и
covariance отсутствуют. Поэтому кандидат не подтверждён и не опровергнут. Вопрос «считается ли
cache write сейчас» также неразрешён Q1: write/no-write меняют лидерство между primary и
информативным срезом.

#### (г) Потолок изменился за семь месяцев — UNCERTAIN

Потолок `21,258,503` математически дал бы коэффициент `15.68` для чистого Opus output. Однако
сохранённых неокруглённых долей нет, а неполная `turn_usage` не позволяет оценить потолок. Текущее
официальное описание Max подтверждает только «20× больше за session» и reset раз в пять часов,
не точное число внутренних кредитов [5]. Дополнительный +50%/+25% режим относился к недельному
окну; по предоставленной проверке первоисточников пятичасовой потолок промо не затрагивало [9].
Промо поэтому снято как объяснение 1.93×, но иное изменение потолка не доказано и не опровергнуто.

#### (д) Наш счётчик считает не то окно — REFUTED

`turn_usage.quota_five_hour_pct` заполняется из `_usage_cache.data['five_hour']`, отдельно от
`seven_day` (`app/session_turns.py:121-142`) [7]. В JSON истории найдено:

- ноутбук: `6654` Anthropic `five_hour` windows, **0** нецелых utilization,
  **0** значений `window_minutes != 300`;
- VPS: `7090`, **0**, **0** соответственно.

То есть outcome — именно округлённое 300-минутное окно. Ошибка выбора weekly/модельного bucket не
объясняет коэффициент.

#### Что остаётся

Raw data четырёхисточниковой регрессии (`15.68`, `1.71`, `R²=.751`) не лежит в task artifact:
`docs/tasks/437/report.md` дословно помечает коэффициенты как caller-supplied и невоспроизводимые
локальным worker [6]. Без interval rows, covariance/CI и полного per-request model ledger нельзя
отличить изменившийся тариф от bias регрессии на округлённом общем счётчике. Поэтому причинный
вердикт по 1.93× — **UNCERTAIN**, а не «потолок точно удвоился».

### Q3 — воспроизводим ли сам метод и что он открыл

**Математический метод воспроизведён; точный потолок нашего аккаунта — нет. CLI/SDK schema может
передать неокруглённое значение, но фактическая live-доставка такого события в нашем аккаунте не
наблюдалась, и ни один текущий consumer его не сохраняет.**

Контроль алгоритма по IEEE-754 bucket:

```text
python3 docs/tasks/440/reproduce_credit_formula.py --self-test
SELF_TEST_OK fraction=449/2750 lcm_control=3300000
```

Это независимо воспроизводит пример источника
`0.16327272727272726 -> 449/2750` [1]. Код открытого расширения подтверждает сам канал: оно клонирует
SSE response, разбирает `data:` и пересылает payload при `json.type === 'message_limit'` [2].

Наш production seam:

- laptop Claude CLI `2.1.258` содержит `rate_limit_event`; его schema несёт fraction
  `utilization` и `unifiedWindows`; production действительно запускает этот binary;
- VPS CLI `2.1.205` содержит `rate_limit_event`, но ещё без `unifiedWindows`;
- SDK `0.2.114` на обеих машинах способен разобрать событие в `RateLimitInfo`, сохранить `utilization` и
  полный `raw` dict (`message_parser.py:336-352`, `types.py:1243-1266`) [8];
- `ClaudeBackend` импортирует `ResultMessage`/`StreamEvent`, но не `RateLimitEvent`, и в dispatch
  ветки для него нет (`app/backend_claude.py:17-35, 1398-1444`) [7]. Если CLI emitted событие, SDK
  может его разобрать, после чего текущий backend потеряет его до БД; сам факт emission не доказан.

Инвентаризация сохранённого:

- `turn_usage`: laptop `3359` five-hour и `3349` seven-day значений, VPS `4166/4166`;
  нецелых — **0 во всех четырёх группах**;
- `usage_snapshots` columns: laptop `12459/12459`, VPS `13561/13561`; нецелых — **0**;
- рекурсивный exact-anchor поиск в `~/.claude/projects` и `~/.claude/debug` обеих машин:
  `rate_limit_event=0`, `unifiedWindows=0`, `unified_windows=0`, `message_limit=0`,
  `anthropic-ratelimit-unified=0` файлов.

Следствие: denominator/LCM нашего аккаунта сейчас вычислять не из чего. Ни один из трёх weekly
кандидатов — **83,333,300** (base), **125,000,000** (+50%), **104,166,625** (+25%) — не подтверждён
и не опровергнут. Пятичасовой кандидат **11,000,000** также не восстановлен из float samples.

**Fact-check rating:** ✅ TRUE для «метод извлечения дроби воспроизводим»; ⚠️ MOSTLY TRUE для
«schema нашего CLI способна отдать материал методу» (laptop да, VPS старый binary видит только
top-level event; actual emission не наблюдался); ❓ UNVERIFIABLE для точных потолков текущего
аккаунта.

## Возможности

Без рекомендаций; только что стало бы возможно при подтверждении Q1 и/или сохранении raw float.

| Возможность | Цена | Риск |
|---|---|---|
| Считать плановую цену задачи в credits до запуска | Полный per-request ledger всех четырёх источников и актуальная таблица ставок каждой модели | Пропущенная поверхность или новый model bucket делает прогноз систематически низким |
| Показывать credits вместо/рядом с виртуальными API-долларами | Отдельный subscription-accounting слой; cache read=0 и cache write как проверенный arm | Смешение credits и usage credits/PAYG; текущая формула не подтверждена |
| Восстановить точный 5h/7d ceiling и режим weekly promotion | Сохранить несколько уже идущих `rate_limit_event` samples, затем fraction bucket + LCM | Один упрощённый denominator — лишь divisor; LCM может недобрать потолок, окно может сменить режим |
| Сверять каждую задачу с фактическим списанием credits | Join quota event ↔ per-request usage по timestamp/model на обеих машинах | Округление времени, duplicate transcript branches, cross-device traffic |
| Отделить цену input/write/output без OLS на целых процентах | Неокруглённый outcome и модельный ledger на каждом API request | `turn_usage` сейчас агрегирует несколько model calls в одну строку и теряет per-call ceil/model detail |
| Закрыть спор о +50%/+25% weekly режиме | Exact recovered weekly LCM, который равен ровно одному из трёх кандидатов | Ни один кандидат не совпал бы при иной base или новом tier; это отдельный обнаруживаемый исход |

## Question framing

- **Context:** общий Claude Max 20× аккаунт, два Orchestra-контура и interactive Claude Code на
  двух машинах.
- **Change under test:** январская credit formula и точные Max ceilings.
- **Baseline:** текущий эмпирический коэффициент `15.68 five-hour п.п./MTok output` и округлённая
  telemetry.
- **Measurable outcome:** доля соседних snapshot pairs, где predicted credits попадают в допустимый
  шаг округления; наличие actual unrounded ratios и recovered LCM.

## Hypotheses considered and falsifiers

1. **H1: формула и 11M ceiling верны сейчас.** Фальсификатор: complete per-request telemetry
   систематически не попадает в rounding interval. Текущая incomplete telemetry не даёт complete
   test; узкая формулировка «работает из `turn_usage` при 11M» опровергнута условно на 11M.
2. **H2: 1.93× создаёт model mix или missing reasoning.** Фальсификатор: помодельный пересчёт
   меняется пренебрежимо, reasoning является subset billed output. Оба наблюдаются; H2 refuted.
3. **H3: cache write не считается.** Фальсификатор: write arm устойчиво чаще попадает на тех же
   парах. На primary и large-delta знак меняется; H3 unresolved.
4. **H4: five-hour ceiling изменился примерно до 21.26M.** Фальсификатор: exact live LCM=11M.
   Actual float samples отсутствуют; H4 unresolved.
5. **H5: outcome был не five-hour.** Фальсификатор: production mapping и 300-minute metadata.
   Оба подтверждены; H5 refuted.

## Counter-evidence and limitations

- Источник [1] помечен пользователем достоверным и self-test воспроизводит его математику, но это
  один неофициальный источник; автор сам пишет, что не сохранил notes процесса вывода rates [1].
- Большие непопадания не опровергают тариф: положительные дельты без единой локальной строки прямо
  доказывают omitted consumers.
- `turn_usage` хранит aggregate runtime turn, тогда как formula содержит `ceil` на request; поле
  `model_calls` есть в runtime metadata, но отсутствует в таблице `turn_usage` [7]. Ошибка ceil
  мала относительно миллионов credits, но точное равенство строкой БД не доказуемо.
- Два контура наблюдают один account counter, поэтому ноутбук и VPS — репликации поверхности, не
  статистически независимые выборки; их нельзя складывать как два разных аккаунта.
- Weekly promo facts и три exact candidates получены из сообщения оркестратора после его проверки
  первоисточников; сами первоисточники конфликтуют по 31.08/14.09 [9].

## Confidence per finding

- **CONFIRMED:** formula-from-current-`turn_usage` при принятом 11M не воспроизводится — direct
  measurement на `1494 + 1500` active pairs, два read-only DB.
- **CONFIRMED:** model mix не объясняет 1.93× — direct rate counterfactual `0.01268%/0.01370%`.
- **CONFIRMED:** thinking входит в billed output semantics — official docs + 660 local positive
  records with zero subset violations.
- **LIKELY:** outcome — корректное five-hour window — production path + 13,744 JSON windows, все
  300 минут; endpoint itself остаётся rounded.
- **CONFIRMED:** fraction recovery mathematics works — deterministic self-test on published float.
- **CONFIRMED:** stored telemetry contains no unrounded ratios — exhaustive numeric and exact-anchor
  inventory on both machines.
- **UNCERTAIN:** exact current ceilings, weekly promo state, cache-write tariff, input/write
  regression-bias candidate, actual live emission of rate-limit floats, and physical cause of 1.93×
  — missing raw float/full-account interval artifact.

## Affected files, risks, edge cases

Production files were read only. Task artifacts:

- `measurement-plan.md` — frozen filter/denominator;
- `reproduce_credit_formula.py` — read-only reproduction and fraction self-test;
- `local-results.json`, `vps-results.json` — measured pair results;
- `telemetry-inventory.json` — precision/runtime/transcript inventory;
- `research.md` — synthesis.

No `app/`, `tests/`, database, credential, provider, or prompt change. No live model/provider call
was made for the experiment. Edge cases represented in the script: reset crossing, >900 s gaps,
missing/negative counters, 100% right-censor sensitivity, unknown model fail-closed, ISO parameters
generated outside SQLite.

## Review decision gate inputs

- Changed files/consumers: only `docs/tasks/440/*`; consumer is the task owner/orchestrator.
- Author: `gpt-5.6-sol`, Codex runtime (live `list_agents`, 2026-09-02).
- AC: direct Q1/Q2/Q3 answers, match fractions, named candidates, Opportunities, session counts.
- Named checks:
  - `python3 docs/tasks/440/reproduce_credit_formula.py --self-test` →
    `SELF_TEST_OK fraction=449/2750 lcm_control=3300000`;
  - laptop frozen run → `916/1494` write, `957/1494` no-write, sessions `598/598`;
  - VPS frozen run → `874/1500`, `946/1500`, sessions `469/469`;
  - `python3 -m json.tool` on all three JSON artifacts → exit 0;
  - `python3 -m py_compile docs/tasks/440/reproduce_credit_formula.py` → exit 0.
- Review route: causal/statistical research would normally route to Sol; no auxiliary Sol approval
  was given. Per `codex-debate`, one Luna completeness/falsification pass is the permitted route.

## Review outcome

Luna independently matched every stated numerator/denominator to the JSON artifacts and found
`0` blocking issues plus `4` epistemic-status clarifications, all applied. Its displayed
`APPROVED` is **not a completed verdict** under `codex-debate`: the claimed verbatim quote was an
English translation absent from the Russian artifact. Result: `Review: Luna, вердикта нет —
evidence quote not verbatim`; full evidence and author verification are in `review-research.md`.
No second round is allowed because the accepted findings were non-blocking suggestions/questions.

## Sources

1. [she-llac, “suspiciously precise floats, or, how I got Claude's real limits,” 2026-01-25](https://she-llac.com/claude-limits) — user-designated trusted; source tier 4 for tariff claims, primary description of the author's experiment.
2. [claude-counter `src/injected/bridge.js`](https://github.com/she-llac/claude-counter/blob/main/src/injected/bridge.js) — primary source code; SSE `message_limit` interception.
3. [Anthropic Platform Docs: Extended thinking](https://platform.claude.com/docs/en/docs/build-with-claude/extended-thinking) — official primary documentation; thinking billed as output tokens.
4. [Anthropic Help Center: How do usage and length limits work?](https://support.claude.com/en/articles/11647753-how-do-usage-and-length-limits-work) — official primary documentation; surfaces share usage limit.
5. [Anthropic Help Center: What is the Max plan?](https://support.claude.com/en/articles/11049741-what-is-the-max-plan) — official primary documentation; 20× session description and five-hour reset, no exact credits.
6. `docs/tasks/437/report.md:60-86` — prior task artifact; four-source coefficients explicitly caller-supplied and not independently reproduced.
7. `app/backend_claude.py:17-35,1398-1444`; `app/session_turns.py:121-142`; `app/db.py:660-772` — current production source.
8. Production SDK `claude_agent_sdk 0.2.114`: `_internal/message_parser.py:336-352`, `types.py:1243-1266`; local CLI 2.1.258 binary schema offsets recorded in session commands — primary local code/runtime evidence.
9. Orchestrator message 2026-09-02 for #440 — opened this session; primary-source check of weekly promo conflict and exact three-state predicate.
