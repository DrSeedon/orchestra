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

Рекомендуемая политика после появления доступа:

| Класс Orchestra | Модель | Effort | Почему |
|---|---|---:|---|
| Закрытая правка с file+line+oracle | Luna | `high` | Наши #199/#222: дешёвая, проходит закрытые задачи и безопаснее останавливается на недостающем решении |
| Любая задача, которую маршрутизация отдала Astra | Astra | **`medium`** | Один уровень без эскалаций: внешний coding index ≈65 при $2.19/task; high почти не добавляет качества |
| Визуал, тонкая проза, независимый review Astra/Sol | Opus 5 | `high` | Другой runtime и другой quota pool; Astra не даёт независимости от Codex-семейства |

Для Astra выбирается **одно значение `medium` во всех ролях**. Никакого автоматического или
task-specific повышения до high/xhigh/max. Модель берётся только для тех задач, которым уже нужна
её capability; effort не становится второй скрытой маршрутизацией.

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

## Effort: почему одно значение — medium

### Общий Intelligence Index

| Effort | Индекс | $/task | Прирост следующей ступени |
|---|---:|---:|---|
| `low` | 57 | 0.46 | — |
| `medium` | 59 | 0.75 | +2 индекса, +63% цены к low |
| `high` | 60 | 0.96 | +1, +28% |
| `xhigh` | 61 | 1.20 | +1, +25% |
| `max` | 61 | 1.67 | +0 округлённо, +39% |

На общей работе экономическое колено — `medium`: переход `low → medium` ещё даёт два пункта, а
`medium → high` оставляет только один пункт за +28% цены. `xhigh` и `max` для единой настройки уже
покупают верхний хвост кривой.

### Coding Agent Index

Значения индекса и token count ниже считаны с опубликованного графика AA и потому помечены `≈`;
цены подписаны на графике явно.

| Effort | Coding index | $/task | Tokens/task | Практический смысл |
|---|---:|---:|---:|---|
| `low` | ≈63 | 1.41 | ≈0.67M | почти уровень Sol xhigh, но ещё не причина отбирать работу у Luna |
| `medium` | ≈65 | 2.19 | ≈1.1M | **выбранный единый уровень** |
| `high` | ≈65.5 | 2.89 | ≈1.4M | около +0.5 пункта за +32% цены — слабая сделка |
| `xhigh` | ≈67 | 3.27 | ≈1.5M | выше качество, но +49% к medium; не единый optimum |
| `max` | 67 | 4.72 | ≈2.1M | тот же округлённый score, +116% к medium |

Для сравнения, в том же Codex harness Sol: `medium 62/$2.19/5.8M`,
`high 64/$3.00/8.0M`, `xhigh 63/$3.74/9.9M`, `max 65/$5.00/13.2M`.
Внешне Astra medium уже выглядит лучше нынешнего Orchestra Sol xhigh. Но это один чужой harness,
поэтому production policy меняется только после нашей парной канарейки.

### Почему Sol, Luna и Opus получили другие уровни

| Модель | Наш уровень | Как выбирали | Что это означает для Astra |
|---|---:|---|---|
| Luna | `high` | `medium → high` был крупнейшим полезным шагом: общий индекс `38.9 → 47.0`; на tool-heavy задачах рост был ещё заметнее. Выше кривая резко замедлялась | У Astra такого скачка на high нет |
| Opus 5 | `high` | `medium → high` давал около +2.9 индекса; `high → xhigh` только +1.0 при +47% цены, а независимый OckBench показывал насыщение coding на high | Та же логика колена у Astra останавливает нас раньше — на medium |
| Sol | сейчас `xhigh`; рекомендован `high` | На старом внешнем composite после medium каждый шаг давал примерно +1.7/+1.7/+1.9, явного перегиба не было. Позднее локальный #373 не нашёл разницы high/xhigh, а свежий coding-agent срез поставил high выше при меньших ресурсах | Это решение нельзя наследовать: Astra имеет другую кривую |
| Astra | **`medium`** | Coding: high даёт лишь ≈+0.5 за +32%; общий index: +1 за +28%. Medium уже ≈65 — уровень Sol max и выше Sol xhigh в том же harness | Один фиксированный effort без повышения |

OpenAI при миграции советует сохранять текущий effective effort. Механически это перенесло бы наш
Sol `xhigh` в Astra, но наш `xhigh` был выбран по кривой Sol и позднее не подтвердился локальным A/B.
Переносить его в модель с другим effort sweep означало бы повторить ровно ту ошибку, которую мы уже
разбирали для Opus: унаследовать настройку предыдущей модели вместо выбора её собственного колена.

### Перепроверка Sol: xhigh стал устаревшей глобальной настройкой

Sol `xhigh` появился 12.08.2026 в #214. Основанием был #208: на тогдашнем общем AA composite
`medium 55.6 → high 57.3 → xhigh 59.0 → max 60.9`, поэтому после medium не наблюдалось явного
перегиба. Это было рациональное решение по доступным на тот день внешним данным, а не случайный
default.

После него накопились данные против глобального xhigh:

- #199: два закрытых Sol-кейса дали одинаковый PASS на medium и xhigh; xhigh стоил `1.13–2.04×`,
  один кейс шёл `1.74×` дольше.
- #373: Sol high/xhigh на замороженном механическом research-кейсе дали одинаковые `14/14` и
  идентичный SHA во всех confirmatory runs; различие времени было меньше A/A-шума.
- Свежий AA Coding Agent Index: high `64 / $3.00 / 6.2 min / 8M tokens`, xhigh
  `63 / $3.74 / 7.3 min / 9.9M`. На этом workload high строго лучше aggregate; xhigh выше только
  на DeepSWE (`67% vs 65%`), а high лучше на Terminal-Bench (`82% vs 80%`) и SWE-Atlas-QnA
  (`45% vs 43%`).
- Общий Intelligence Index сохраняет контрсигнал в пользу xhigh: `57/$0.43` против `59/$0.63`.
  Это +2 индекса примерно за +47% цены, поэтому xhigh не «сломанный», а узкая quality-first ставка.

Официальная документация называет medium сбалансированным default для большинства агентов, high —
уровнем для сложной логики, проверки предположений и edge cases, а xhigh/max — для особенно тяжёлого
reasoning. Orchestra уже отсекает рутину в Luna и отправляет Sol только сложные задачи, поэтому
**одна фиксированная ступень Sol должна быть `high`**. Официальный Codex Security использует Sol
xhigh по умолчанию для bulk scan, но это специальный security workload и не основание распространять
xhigh на каждый research, worker и orchestrator.

Итог перепроверки: текущий глобальный `gpt-5.6-sol: xhigh` — **устаревшее policy-решение и вероятная
ошибка эффективности**. Рекомендуемое значение — `high` во всех role maps. Production pipeline в
рамках этого research не менялся.

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

**Следствие для Astra:** нельзя копировать Sol `xhigh`. Единая ступень — `medium`: high слишком мало
прибавляет, а xhigh/max превращают fixed effort в постоянный налог за редкие крайние случаи.

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
4. Во всех role maps задать один exact-model ключ `gpt-6-astra: medium`. Не добавлять override и
   автоматическую эскалацию effort.
5. Обновить model-routing: Luna остаётся default; Astra становится верхней веткой Sol-класса только
   после прохождения канарейки; Sol сохраняется как rollback/fallback.
6. Отдельно проверить >272K virtual pricing и экспериментальное context management. Не смешивать
   их с первым model-quality A/B, иначе неизвестно, что дало эффект.

Минимальная канарейка — не синтетический smoke, а три наших класса с уже существующими oracles:

| Пара | Задачи | Outcome |
|---|---|---|
| Astra medium vs Sol xhigh | 3 сложных coding tickets | pass rate, steps-to-green, tool rounds, credits, wall |
| Astra medium vs Sol xhigh | 2 research/architecture tickets | полнота evidence, число переделок, независимая оценка |
| Astra medium vs Sol xhigh | 1 длинный full-cycle | final acceptance, compact/resume, потерянные требования |

Порядок A/B/A/B, fresh thread на ячейку, одинаковый frozen prompt/commit/oracle. Если Astra medium
не хуже Sol xhigh и использует не больше credits/task, она становится единственной настройкой Astra
для Sol-класса. Если выигрыша нет, остаётся Sol; effort Astra под задачу не двигается.

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
