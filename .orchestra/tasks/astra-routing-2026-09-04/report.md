# GPT-6 Astra в Orchestra: экономика, маршрутизация и effort

Дата среза: 4 сентября 2026, 19:09 Asia/Krasnoyarsk.

## Решение

**Astra не заменяет весь парк и не должна стать новым default.** Она является кандидатом на замену
большей части **Sol-класса** задач: сложный agentic coding, computer use, SRE/security и длинные
end-to-end workflow. Luna остаётся default для закрытых задач, Opus остаётся отдельным Claude-пулом
для особой неоднозначности, визуала/прозы и cross-runtime проверки, Spark/Grok/OpenRouter сохраняют
свои отдельные ёмкости и специализации.

Главный экономический парадокс: один токен Astra расходует `2.5×` credits Sol, но в Coding Agent
Index Astra использует примерно треть токенов Sol. Поэтому на **кодовых агентных задачах** Astra
может оказаться не дороже и даже дешевле за готовый результат. На общем Intelligence Index токены
сократились лишь примерно на 10%, и Astra `max` получилась на 75% дороже Sol `max` при том же
округлённом индексе 61. Следовательно, «Astra вместо Sol» оправдано по классу задачи, а не по имени
модели.

Рекомендуемый старт после появления доступа:

| Класс Orchestra | Модель | Effort | Почему |
|---|---|---:|---|
| Закрытая правка с file+line+oracle | Luna | `high` | Наши #199/#222: дешёвая, проходит закрытые задачи и безопаснее останавливается на недостающем решении |
| Обычный сложный coding worker | Astra | `medium` | Лучшее экономическое стартовое плечо; внешний coding index ≈65 при $2.19/task |
| Неоднозначный research / orchestrator | Astra | `high` | Чуть больше judgement без скачка к верхней ступени; обязательна очная ставка с текущим Sol/Opus |
| Длинный full-cycle, computer use, defensive security/SRE | Astra | `xhigh` | Здесь подтверждены самые крупные внешние преимущества; `xhigh` почти равен `max` дешевле |
| Уникальная quality-first задача | Astra | `max` вручную | Не default: на двух AA-кривых прирост относительно `xhigh` округляется до нуля |
| Визуал, тонкая проза, независимый review Astra/Sol | Opus 5 | `high` | Другой runtime и другой quota pool; Astra не даёт независимости от Codex-семейства |

Если требуется **одно** значение Astra до появления своей статистики, выбирать `medium`, а не
`xhigh`/`max`. Нынешний Orchestra resolver умеет задавать effort отдельно по ролям, поэтому после
канарейки лучше оставить `medium` у `worker`, `high` у `orchestrator/sub-orchestrator` и `xhigh` у
`full-cycle`, вместо одной глобальной ступени.

## Доступ прямо сейчас

- Локальный Codex CLI: `0.153.2`.
- Свежий `~/.codex/models_cache.json`: `2026-09-04T12:09:37Z`, девять моделей, Astra отсутствует.
- Живой `GET http://127.0.0.1:8888/api/models`: Astra отсутствует.
- Production-конфигурация Orchestra не содержит `gpt-6-astra` ни в `ModelSpec`, ни в aliases,
  price map, context map или pipeline effort map.

Это согласуется с поэтапным rollout OpenAI. Принудительный платный/квотный вызов не выполнялся:
отрицательный каталог уже доказывает, что сейчас Astra нельзя объявлять рабочей моделью Orchestra.

## Экономика подписки

Текущая официальная таблица ChatGPT credits за 1M токенов:

| Модель | Input | Cached input | Output | Astra к модели |
|---|---:|---:|---:|---|
| Astra | 250 | 25 | 1,250 | — |
| Sol | 100 | 10 | 500 | ровно `2.5×` по всем трём типам |
| Terra | 50 | 5 | 300 | `5×` input/cache; `4.17×` output |
| Luna | 5 | 0.5 | 30 | `50×` input/cache; `41.67×` output |

Это уже не косвенный пересчёт по API-долларам: OpenAI публикует сами token credit rates. Однако
нельзя переводить их в «процентов недельного окна на задачу» без известного размера allowance и
наблюдаемой телеметрии. Старые исследования Orchestra правильно сравнивали относительные веса, но
точные исторические `$` и проценты нельзя механически переносить через изменения тарифов и промо.

API-эквивалент Astra: `$10/M` input, `$1/M` cached input, `$12.5/M` cache write, `$50/M` output.
Это ровно `2.5×` нынешней промо-цены Sol `$4/$0.4/$5/$20`. Fast на подписочной credit rate даёт
множитель `2.5×`; при обещании до `2×` скорости это экономически хуже Standard и годится только для
ручной latency-critical задачи.

У Astra есть дополнительная ловушка: API-запрос с input больше 272K тарифицируется целиком по
`2×` input/cache и `1.5×` output. Применение этого множителя к included subscription allowance не
опубликовано, поэтому утверждать его нельзя. Но внутренний виртуальный cost Orchestra обязан будет
учитывать этот порог, если реальный ChatGPT-auth context Astra превысит 272K.

## Effort: что реально покупает каждая ступень

### Общий Intelligence Index

| Effort | Индекс | $/task | Прирост следующей ступени |
|---|---:|---:|---|
| `low` | 57 | 0.46 | — |
| `medium` | 59 | 0.75 | +2 индекса, +63% цены к low |
| `high` | 60 | 0.96 | +1, +28% |
| `xhigh` | 61 | 1.20 | +1, +25% |
| `max` | 61 | 1.67 | +0 округлённо, +39% |

На общей работе экономическое колено — `medium/high`. `max` не оправдан как default.

### Coding Agent Index

Значения индекса и token count ниже считаны с опубликованного графика AA и потому помечены `≈`;
цены подписаны на графике явно.

| Effort | Coding index | $/task | Tokens/task | Практический смысл |
|---|---:|---:|---:|---|
| `low` | ≈63 | 1.41 | ≈0.67M | почти уровень Sol xhigh, но ещё не причина отбирать работу у Luna |
| `medium` | ≈65 | 2.19 | ≈1.1M | лучший default для обычного сложного coding worker |
| `high` | ≈65.5 | 2.89 | ≈1.4M | для неоднозначности и дополнительной проверки |
| `xhigh` | ≈67 | 3.27 | ≈1.5M | лучший quality/cost для длинного full-cycle |
| `max` | 67 | 4.72 | ≈2.1M | тот же округлённый score, +44% к xhigh |

Для сравнения, в том же Codex harness Sol: `medium 62/$2.19/5.8M`,
`high 64/$3.00/8.0M`, `xhigh 63/$3.74/9.9M`, `max 65/$5.00/13.2M`.
Внешне Astra medium уже выглядит лучше нынешнего Orchestra Sol xhigh. Но это один чужой harness,
поэтому production policy меняется только после нашей парной канарейки.

## Что говорят наши исследования Orchestra

### Luna, Terra, Sol

- #199: на трёх закрытых заданиях Luna/Terra/Sol прошли всё; Luna была в 20.5 раза дешевле Sol в
  тогдашнем API-эквиваленте. На extraction из 164K все дали 9/9, но cross-reference reasoning не
  проверялся. Terra не дала преимущества над Luna и была отключена.
- #203 закрепил правило: закрытая задача → Luna, открытая/сложная → Sol.
- #208: Luna high и Sol high дали одинаковые 5/6 на одном реальном research+implementation кейсе;
  Luna использовала больше tools/input, Sol дал полезнее telemetry. `N=1`, поэтому это не отменяет
  различие классов.

**Следствие для Astra:** она не трогает Luna-lane. Экономический порог против Luna огромный — до
`50×` credits на input/cache. Astra должна конкурировать только с Sol/Opus за задачи, где дешёвая
модель повышает риск переделки.

### Effort

- #199: Sol `medium` и `xhigh` дали одинаковый PASS на двух закрытых кейсах; один кейс стал `2.04×`
  дороже и `1.74×` медленнее на xhigh.
- #204/#208: внешний composite у Sol рос по лестнице, но данных по нашим многочасовым research и
  full-cycle не было.
- #373: замороженный A/B/A/B Sol high↔xhigh дал одинаковые `14/14` и один SHA результата во всех
  четырёх confirmatory runs; разница latency была меньше A/A-шума.
- #374: текущий resolver model-aware, но не task-aware; все роли сейчас дают Sol `xhigh`, Luna
  `high`, Opus `high`. Глобальный Sol xhigh остаётся risk policy, а не доказанным optimum.

**Следствие для Astra:** нельзя копировать Sol `xhigh` во все роли. Внешний Astra sweep прямо
показывает бесполезность `max` как общего default и отдельные экономические точки для `medium` и
`xhigh`.

### Opus/Fable и независимость пулов

- Opus 5 оставлен для особой неоднозначности, визуала, творческой/профессиональной подачи и как
  fallback после исчерпания Codex. Его `high` — измеренное колено; выше прирост мал.
- #434/#437: Fable 5.1 умеет переиспользовать cache, но скидка token-billed cache не доказала
  расширение Max allowance. Fable не введён в рабочий пул.
- #176: один и тот же Sol, который написал постановку, отревьюил её и реализовал, усилил собственную
  ошибку и породил оверинжиниринг. Сильнее модель не чинит петлю независимости.

**Следствие для Astra:** не заменять ею Opus полностью и не назначать Astra финальным судьёй работы,
которую сделала Astra/Sol. Для high-stakes review нужен другой runtime.

### Spark, Grok, OpenRouter и внешние кандидаты

- #222: Spark полезен как отдельная быстрая полоса только для полностью закрытой text-only задачи.
  Он дважды придумал отсутствующую константу, тогда как Luna дважды остановилась и спросила.
- #232/#251: Grok — отдельная ёмкость и специализированный X/search route, а не доказанная замена
  Sol по качеству.
- #236/#422: OpenRouter Harness полезен как бесплатная автономная lane с точным oracle; бесплатность
  не превращает слабую/нестабильную модель в production default.
- #469: Muse Spark 1.3 выглядит сильным и дешёвым, но authorised production canary и полный runtime
  contract не доказаны; правила `AGENTS.md` обрезались на 65,536 bytes.
- #506: Antigravity технически оборачивается, но consumer login через сторонний wrapper противоречит
  текущим условиям; runtime не вводится.

**Следствие для Astra:** она самый дешёвый путь к новой frontier-capability, потому что использует
уже существующий Codex backend и общий логин. Но она не добавляет новый quota pool — именно поэтому
Grok/Spark/Harness сохраняют ценность после её появления.

### Контекст и app-server

- #312/#375: увеличение номинального контекста само по себе не доказало улучшение работы; важнее
  фактический ChatGPT-auth budget и compaction behavior.
- #376: persistent app-server экономит примерно 2–3 секунды локального lifecycle, но общий wall time
  сильнее шумит от модели/провайдера; менять backend architecture ради Astra не нужно.
- Astra предлагает экспериментальное context management: notes между окнами плюс поиск по прошлым
  messages/tool results. Это особенно релевантно нашим длинным full-cycle и прежним compact-сбоям,
  но feature выключена по умолчанию и должна идти отдельной канарейкой. Номинальные 1.05M API нельзя
  считать фактическим лимитом Orchestra до живого `model/list`/turn measurement.

## Где Astra реально лучше Sol

Сильные кандидаты:

1. **Agentic coding и миграции.** Terminal-Bench 4.0 `57.9 vs 37.3`, internal database migration
   `63.9 vs 42.7`, AA coding index `67 vs 65` на max; токенов примерно втрое меньше.
2. **Computer use и браузерные workflow.** OSWorld `72.6 vs 65.7`, примерно 40 минут против 75;
   AutomationBench `41.4 vs 18.1`.
3. **Defensive security/SRE.** SRE-Bench `88.0 vs 55.9`, ExploitGym `42.4 vs 30.3`, свежий
   ExploitBench `39.0 vs 11.5`. Production safeguards могут остановить часть допустимых задач.
4. **Длинная агентная работа с меняющимися требованиями.** AA-Briefcase вырос примерно на 80 Elo;
   context management адресует потери от повторной компактизации.
5. **Задачи, где опасна уверенная выдумка.** AA сообщает снижение hallucination rate `92% → 51%`
   при одновременном росте accuracy на четыре пункта.

Не доказанные замены:

- общий research/knowledge: Intelligence Index `61.2 vs 60.9`, но задача Astra max на 75% дороже;
- long-context reasoning: AA-LCR у Astra регрессировал на 2–3 пункта;
- scientific Python и banking tool use: SciCode/τ³-Banking регрессировали на 2–3 пункта;
- professional presentation: AA наблюдает снижение Presentation Quality Elo, Sol остаётся лидером;
- весь Sol-парк до нашей канарейки: чужой harness не воспроизводит Orchestra prompts, MCP, compact,
  quotas и критерии готовности.

## Как интегрировать без гадания

Production менять только после появления Astra в нашем свежем model catalog.

1. Добавить один `ModelSpec(gpt-6-astra)` и alias `astra`; backend остаётся `codex`.
2. Добавить API-equivalent prices и реальный measured ChatGPT-auth context, а не автоматически
   копировать API `1,050,000`.
3. Astra должна попадать в общий `codex` quota bucket, не в Spark и не в новый выдуманный пул.
4. Задать role-specific effort: worker `medium`, orchestrator/sub-orchestrator `high`, full-cycle
   `xhigh`. Reducer Astra не использует.
5. Обновить model-routing: Luna остаётся default; Astra становится верхней веткой Sol-класса только
   после прохождения канарейки; Sol сохраняется как rollback/fallback.
6. Отдельно проверить >272K virtual pricing и экспериментальное context management. Не смешивать
   их с первым model-quality A/B, иначе неизвестно, что дало эффект.

Минимальная канарейка — не синтетический smoke, а три наших класса с уже существующими oracles:

| Пара | Задачи | Outcome |
|---|---|---|
| Astra medium vs Sol xhigh | 3 закрытых сложных coding tickets | pass rate, steps-to-green, tool rounds, credits, wall |
| Astra high vs Sol xhigh | 2 research/architecture tickets | полнота evidence, число переделок, независимая оценка |
| Astra xhigh vs Astra max | 1 длинный full-cycle | final acceptance; max проходит только если реально повышает качество |

Порядок A/B/A/B, fresh thread на ячейку, одинаковый frozen prompt/commit/oracle. Если Astra medium
не хуже Sol xhigh и использует не больше credits/task, она становится default для Sol-класса. Если
выигрыш есть только на coding/computer/security — маршрутизация остаётся предметной. `max` допускается
только при наблюдаемом улучшении над `xhigh`; иначе закрывается.

## Источники

Внешние:

- [OpenAI — GPT-6 Astra launch](https://openai.com/index/gpt-6-astra/)
- [OpenAI — GPT-6 Astra model card and pricing](https://developers.openai.com/api/docs/models/gpt-6-astra)
- [OpenAI — Codex model selection and context management](https://developers.openai.com/codex/models)
- [OpenAI — Codex credit rates](https://developers.openai.com/codex/pricing)
- [Artificial Analysis — GPT-6 Astra benchmark analysis](https://artificialanalysis.ai/articles/benchmarking-gpt-6-astra)
- [Artificial Analysis — Astra low](https://artificialanalysis.ai/models/gpt-6-astra-low),
  [medium](https://artificialanalysis.ai/models/gpt-6-astra-medium),
  [high](https://artificialanalysis.ai/models/gpt-6-astra-high),
  [xhigh](https://artificialanalysis.ai/models/gpt-6-astra-xhigh),
  [max](https://artificialanalysis.ai/models/gpt-6-astra)
- [ARC Prize — standard vs provider-adapter Astra](https://arcprize.org/blog/astra)

Локальные исследования: `.orchestra/tasks/199`, `203`, `204`, `208`, `222`, `232`, `236`, `251`,
`262`, `285`, `289`, `298`, `310`, `312`, `334`, `354`, `373`, `374`, `375`, `376`, `434`, `437`,
`469`, `506`, а также `opus5-routing`, `sol-model-comparison`, `subscription-strategy` и
`.orchestra/kb/model-routing-selection.md`.

Числовой снимок отчёта: `data.json`.
