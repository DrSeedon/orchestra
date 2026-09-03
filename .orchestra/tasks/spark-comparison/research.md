# GPT-5.3-Codex-Spark для Orchestra — исследование

Дата среза: 2026-07-18.

## Короткий вывод

GPT-5.3-Codex-Spark — не «дешёвый Sol», а отдельный latency-first режим Codex:
уменьшенная, text-only модель с окном 128k, работающая на Cerebras WSE-3 и
предназначенная для коротких интерактивных правок. OpenAI заявляет более 1000
output tokens/s, но не раскрывает число параметров, архитектуру весов,
публичную API-цену или точный размер квоты.[1][2]

Для Orchestra Spark стоит проверить в ограниченном A/B-пилоте как узкого
исполнителя уже декомпозированной задачи: точечный `impl-*`/`fix-*`,
механическая правка, маленькая UI-итерация, запуск заданного теста. Текущих
данных недостаточно для изменения default routing. Не стоит даже в пилоте
переносить на него оркестрацию, автономное исследование, финальный code review,
миграции, security-задачи и неоднозначную многофайловую отладку.

Основания:

- у Spark нет карточки Artificial Analysis (AA), Coding Agent Index и
  независимых стандартизованных TTFT/throughput-измерений — численно поставить
  его рядом с Sol и Opus без подмены Spark обычным GPT-5.3-Codex нельзя;[12][13]
- в нашем контролируемом микротесте Spark был в 2.32 раза быстрее Sol medium по
  полному времени короткой tool-задачи, но лишь в 1.17 раза быстрее Opus 4.8
  medium; все модели ответили правильно;
- OpenAI прямо настраивает Spark на минимальные правки и предупреждает, что он
  не запускает тесты автоматически, если это не попросить явно.[1]

## Вопрос и критерий решения

**Контекст.** Orchestra использует GPT-5.6 Sol medium для Codex-воркеров и
Claude Opus 4.8 для задач, где важны оркестрация, длинный контекст и качество
суждения.

**Изменение под проверкой.** Перенести часть коротких задач на
GPT-5.3-Codex-Spark, используя его отдельную квоту.

**Baseline.** Sol medium для реализации и Opus 4.8 medium/max для сложного
анализа и оркестрации.

**Измеримый исход.** Качество выполнения, end-to-end latency, расход основной
Sol-квоты, число повторов/эскалаций и способность задачи уместиться в 128k
контекста.

## Гипотезы и фальсификаторы

### H1 — Spark выгоден для узких, детерминированных правок

Spark сокращает wall time и не расходует стандартный лимит Codex, когда задача
text-only, локальна, имеет явные acceptance criteria и заданные тесты.

**Что опровергнет H1:** на реальных коротких задачах success rate окажется ниже
95% от Sol, медианное время не будет заметно меньше Sol или результат будет
регулярно требовать повторной реализации Sol.

### H2 — Spark может заменить Sol как основной coding worker

Если качество Spark близко к Sol на автономной repo-работе, отдельная квота и
скорость позволят сделать его default.

**Что опровергает H2 сейчас:** отсутствует независимый coding-agent score
Spark; OpenAI позиционирует его как менее способную модель для точечных правок,
а не как long-horizon replacement.[1][2] Поэтому H2 **не подтверждена** и не
должна определять routing без A/B-пилота.

### H3 — отдельная квота гарантированно работает после исчерпания Sol weekly

Официально расход Spark не учитывается в standard rate limits.[1][4]

**Что опровергнет H3:** Spark блокируется общим weekly gate, даже если его
собственные индикаторы показывают остаток. Такой пользовательский отчёт уже
существует в Codex issue tracker,[11] поэтому гарантия доступности после
исчерпания общей weekly-квоты сейчас **не доказана**.

## 1. Что такое GPT-5.3-Codex-Spark

| Параметр | Установленный факт | Уверенность |
|---|---|---|
| Позиционирование | Research preview, «smaller version of GPT-5.3-Codex» и первая модель OpenAI, спроектированная для real-time coding.[1] | **CONFIRMED** — первичный источник OpenAI |
| Архитектура модели | Не опубликована. Нет подтверждённого parameter count, MoE/dense-топологии или сведений о distillation. | **CONFIRMED как пробел** — OpenAI раскрывает только «smaller» |
| Inference hardware | Cerebras Wafer-Scale Engine 3; это аппаратная платформа инференса, а не описание архитектуры весов.[1][10] | **CONFIRMED** — OpenAI + партнёр запуска |
| Контекст | 128k на старте.[1] | **CONFIRMED** |
| Модальности | Text-only; image input не поддерживается.[1][2] | **CONFIRMED** |
| Основной режим | Быстрые точечные изменения, refinement UI/логики и интерактивный pair-programming; не long-running autonomous agent.[1][2][8] | **CONFIRMED** |
| Availability | Codex app, CLI и IDE extension для ChatGPT Pro; ограниченный API-доступ был только у design partners.[1][4] | **CONFIRMED для research preview** |

Размер WSE-3, огромный throughput и слово «smaller» не позволяют вывести число
параметров. Любая точная оценка размера Spark без нового раскрытия OpenAI была
бы выдумкой.

## 2. Возможности и инструменты

Нужно разделять способности модели и Codex harness. Shell, file edit, MCP и
web search предоставляет среда Codex; OpenAI не опубликовала отдельную
Spark-specific матрицу инструментов.

| Возможность | Статус у Spark | Что это значит для Orchestra |
|---|---|---|
| Чтение файлов / shell | Доступно через Codex harness; подтверждено нашим живым Spark-пилотом | Можно выполнять локальные repo-задачи |
| File edit | Доступно через Codex; targeted edits — основной официальный use case.[1][8] | Подходит для маленьких патчей |
| Запуск тестов | Инструмент доступен, но Spark **не запускает тесты автоматически**, если это не указать.[1] | В prompt/AC нужно явно писать команду проверки |
| Web search | Harness-level capability; в Orchestra Codex backend принудительно задаёт `web_search="live"` (`app/backend_codex.py:222`) | Технически доступен, но качество автономного research для Spark не доказано |
| MCP tools | Подтверждено живым пилотом Orchestra | Spark может вызывать инструменты Orchestra |
| Subagents | Официальные Codex docs предлагают Spark как модель **для subagent**, когда важнее latency.[7] Способность Spark-root качественно управлять деревом subagents отдельно не опубликована | Использовать как leaf-executor; не как главный координатор |
| Interrupt / redirect | Официально рассчитан на прерывание и изменение направления в реальном времени.[1] | Удобен для интерактивной пары |
| Images / vision | Нет, text-only.[1][2] | Скриншоты, визуальный review и image reasoning оставлять Opus |
| Long-context | 128k против 1M у Opus 4.8.[1][9] | Не давать большие монорепы и длинные research-корпуса |
| Deep/long-horizon reasoning | Reasoning effort может передаваться harness, но OpenAI называет модель less-capable и противопоставляет её long-running Codex.[1][2] | `xhigh` не превращает Spark в Sol/Opus; сложность маршрутизировать выше |

В текущем коде Orchestra модель уже зарегистрирована с `runtime="codex"` и
128k: `app/models.py:35,52,82-84,102` и
`app/backend_codex.py:21`. Spark не указан в `CODEX_TOKEN_PRICES`, поэтому
виртуальная API-equivalent стоимость не вычисляется; придумывать её нельзя.

## 3. Квоты: что действительно отдельно

Официальная формулировка сильная, но не числовая:

- Spark имеет собственный rate limit, а его использование «does not count
  toward your standard rate limits»;[1]
- лимит может меняться в зависимости от спроса и доступности специального
  low-latency hardware; возможна очередь;[1][4]
- стандартные local/cloud задачи Codex делят 5-hour window, а дополнительные
  weekly limits могут применяться;[4]
- точный Spark weekly allocation, формула расчёта и гарантированный reset
  schedule публично не указаны.[4]

В текущем клиенте пользователи видят отдельные Spark 5h и weekly meters, но это
наблюдение интерфейса, а не опубликованный контракт. В GitHub issue #19868
пользователь сообщил, что при `0%` общего weekly Spark перестал запускаться,
несмотря на остаток отдельных Spark 5h/weekly meters; issue закрыт как
`not planned`.[11]

**Вывод по квоте:**

- **CONFIRMED:** расход Spark учитывается отдельно от стандартного Sol
  5-hour usage;
- **LIKELY:** отдельный weekly meter существует в клиенте;
- **UNCERTAIN:** Spark останется доступным после полного исчерпания общего
  Codex weekly. На это нельзя опираться ни как на SLA, ни как на плановую
  резервную ёмкость Orchestra.

## 4. Цена и credits

| Модель | ChatGPT/Codex credits на 1M tokens | Публичная API-цена | Комментарий |
|---|---:|---:|---|
| GPT-5.3-Codex-Spark | Не финализированы; rate card показывает `research preview`, а не числа.[5] | Нет публичного API/цены на момент preview.[1][4] | Нельзя оценивать как «дешевле за токен» |
| GPT-5.6 Sol | 125 input / 12.5 cached input / 750 output credits.[5] | $5 input / $30 output по live AA provider data.[12] | Для Orchestra реальная оплата подписочная; это лишь внешний эквивалент |
| Claude Opus 4.8 | Не Codex credits | $5 input / $25 output.[9] | В Orchestra также используется подписка, не API billing |

Внутри Orchestra долларовые значения являются виртуальной API-equivalent
метрикой. Практическая ценность Spark здесь — отдельный лимит и latency, не
неизвестная token price. Routing следует принимать по риску, измеренному
качеству и latency, а не по несопоставимым долларовым строкам этой таблицы.

## 5. Бенчмарки: что можно и нельзя сравнивать

### Artificial Analysis

На дату среза AA не имеет карточки GPT-5.3-Codex-Spark ни в Intelligence Index,
ни в Coding Agent Index. Следовательно, честного трёхстороннего
apples-to-apples сравнения нет.

| Система | AA Intelligence Index v4.1 | AA Coding Agent Index | DeepSWE / Terminal-Bench v2 / SWE-Atlas-QnA | Active time / task | Tokens / task |
|---|---:|---:|---:|---:|---:|
| Spark | — | — | — | — | — |
| Codex + Sol medium | 54 | 75 | 64% / 78% / 82% | 5.2 min | 5.8M |
| Claude Code + Opus 4.8 max | 56 | 73 | 56% / 79% / 82% | 23.1 min | 18M |
| Claude Code + Opus 4.8 medium | отдельной Intelligence-card не найдено | 67 | 49% / 75% / 77% | 12.4 min | 7.8M |

Источники: AA model cards и coding-agent comparison.[12][13][14] Coding Agent
Index сравнивает **системы** Codex+model и Claude Code+model; различаются harness
и reasoning effort. Поэтому данные поддерживают операционный вывод «Codex + Sol
medium сейчас эффективнее на этом наборе», но не утверждение «веса Sol умнее
весов Opus».

### Официальный launch chart Spark

OpenAI показывает SWE-Bench Pro и Terminal-Bench 2.0 только графиком, без
машиночитаемой таблицы.[1] Независимые чтения графика дают около `58.4%` для
Spark на Terminal-Bench 2.0 и примерно `51.5%` в одной точке кривой
SWE-Bench Pro, но это **LOW confidence**: effort не указан, SWE-Bench Pro
является accuracy-vs-duration curve, а не одним scalar.[18][19] Эти числа
зафиксированы только как гипотезы для будущей проверки и не участвуют в
routing-рекомендации.

Дополнительно OpenAI в июле 2026 отозвала рекомендацию использовать SWE-Bench
Pro как надёжный coding benchmark: около 30% задач были сломаны, а human audit
получил 34.1% problematic tasks.[17] Поэтому launch chart Spark нельзя делать
load-bearing доказательством качества.

Terminal-Bench 2.1 показывает Claude Code + Opus 4.8 high `78.9% ± 1.3%`, но в
verified leaderboard нет Spark и Sol; версия 2.1 несопоставима с launch
Terminal-Bench 2.0 Spark.[15]

**Бенчмарк-вывод:** Sol medium имеет актуальное независимое coding-agent
основание; Spark — нет. Пока Spark следует считать отдельным latency class, а
не quality-equivalent replacement.

## 6. Скорость и latency

### Публичные данные

| Модель | Output speed | TTFT / TTFA | Уровень доказательства |
|---|---:|---:|---|
| Spark | `>1000 tok/s` на launch; краткие burst до `4000 tok/s` описаны OpenAI.[1][3] | Абсолютное значение не опубликовано; OpenAI сообщает относительное улучшение stack TTFT на 50%.[1] | First-party vendor claim; независимого AA измерения нет |
| Sol medium | 54.7 tok/s | 4.15 s на live AA provider snapshot; в течение исследования отображалось примерно 4.05–4.83 s.[12][16] | Независимое измерение AA, но live-значение волатильно |
| Opus 4.8 max, Anthropic API | 63.3 tok/s | 34.49 s TTFA; Bedrock 63.9/30.96, Google 67.2/29.56.[16] | Независимое измерение AA; effort=max и TTFA включает reasoning |

`1000 / 55 ≈ 18x` — сравнение raw decode, а не wall-clock агентной задачи.
Tool execution, prefill, reasoning и round trips резко уменьшают преимущество.
OpenAI отдельно сообщает 40% end-to-end ускорение агентных циклов от
persistent WebSocket transport; это улучшение harness, а не только модели.[3]
AA-строка Opus относится к `max`; ниже наш отдельный microbench использует
Opus `medium`. Между этими двумя frames не вычисляется общий коэффициент.

### Контролируемый Orchestra microbench

**Гипотеза до запуска:** на одинаковом read-only symbol lookup в тёплых
persistent sessions Spark будет минимум в 2 раза быстрее Sol medium и Opus 4.8
medium по time-to-first-visible-content и total turn time, сохранив
корректность.

**Задача:** прочитать `backend_for_model` в `app/models.py` и вернуть runtime
для Spark и Opus с номерами строк. Три последовательных запуска на каждую
модель, effort=`medium`. Метрики считались из timestamp событий SQLite
Orchestra: `user_message → first text event` и
`user_message → first subsequent "turn ended"` до следующего trial.
Воспроизводимый extraction query и точные log IDs сохранены в
[`microbench.sql`](microbench.sql).

| Модель | Trial first-visible, s | Trial total, s | Median first-visible | Median total | Median tool calls | Correct |
|---|---|---|---:|---:|---:|---|
| Spark medium | 1.773 / 1.709 / 1.969 | 7.199 / 3.812 / 6.550 | **1.773 s** | **6.550 s** | 2 | 3/3 |
| Sol medium | 8.435 / 3.799 / 2.813 | 29.110 / 15.161 / 11.524 | **3.799 s** | **15.161 s** | 2 | 3/3 |
| Opus 4.8 medium | 2.496 / 4.096 / 3.087 | 13.101 / 7.660 / 6.094 | **3.087 s** | **7.660 s** | 1 | 3/3 |

Отношение медиан:

- first-visible: Spark быстрее Sol в `2.14x`, Opus — в `1.74x`;
- total: Spark быстрее Sol в `2.31x`, Opus — в `1.17x`.

Предзарегистрированный порог `≥2x` против обеих моделей **не пройден**:
преимущество над Sol подтверждено, над Opus на этой крошечной задаче — нет.

Ограничения измерения: `n=3`, разные harness (Codex/Claude), тёплые сессии, одна
простая repo-задача. Первый Sol trial содержал отложенный текст предыдущего
turn и мог завысить его latency; медиана ограничивает, но не устраняет этот
эффект: `first_content` для log ID `268702` — старый digest, не `START`.
Это microbench интерактивности static lookup, не coding benchmark и не
основание переносить `impl-*`/`fix-*` без отдельного edit-пилота.

## 7. Что Spark не может или делает хуже

| Ограничение | Практическое последствие |
|---|---|
| Нет image input | Не отдавать screenshot review, визуальную диагностику и multimodal research |
| Только 128k | Полный prompt Orchestra + код + tool results быстрее упираются в compaction |
| Less-capable / lightweight | Не использовать как default для неоднозначной архитектуры и long-horizon debugging |
| Тесты не запускаются автоматически | Каждая impl/fix задача обязана содержать явную test command |
| Нет публичного API и token price | Нельзя строить экономику per-token или внешний production integration |
| Неизвестная/эластичная квота | Нельзя обещать фиксированную weekly capacity |
| Нет независимого AA score | Нельзя заявлять parity с Sol/Opus |
| Minimal edits by default | Полезно для хирургических изменений, рискованно для задач, требующих полного dependency sweep |

В живом исследовательском turn полный Orchestra prompt и серия tool calls
привели Spark к compaction в рамках одной сессии. Это не доказывает дефект
модели, но подтверждает, что существующий тяжёлый full-cycle prompt плохо
соответствует 128k latency-first worker.

## 8. Routing для Orchestra

### Кандидаты для ограниченного A/B-пилота

Default routing на текущих данных **не меняется**. Задачу можно включить в
Spark-пилот, только если одновременно выполняются условия:

1. text-only;
2. затронуто обычно не более 1–2 файлов;
3. функция/место изменения заранее указаны;
4. acceptance criteria детерминированы;
5. test command задана явно;
6. ожидаемый working context заметно меньше 128k;
7. нет security, migration, concurrency или data-loss риска.

Кандидаты для проверки, а не уже доказанные production use cases:

- быстрый одноразовый `impl-*`: добавить простой validation branch, небольшой
  endpoint/helper по готовому паттерну, узкую UI/CSS-правку;
- `fix-*` с уже установленной причиной и воспроизводящим тестом;
- механический rename/замена/адаптация сигнатуры в малом scope;
- создание простого boilerplate по существующему соседнему примеру;
- leaf-worker: применить подготовленный Sol/Opus patch plan, запустить
  конкретный тест и вернуть diff/result;
- быстрый вопрос по локальному символу или файлу.

### Только пилот, не default

- **Лёгкие system workers.** Допустимы лишь stateless/deterministic jobs с
  коротким prompt и фиксированным output schema. Длинноживущий system worker
  будет терять преимущество из-за 128k и compaction.
- **Code review.** Spark можно использовать для дешёвого первого scan
  (очевидные syntax/contract mismatches), но не как финальный gate. Финальное
  correctness/security review оставлять Sol/Opus.
- **Research.** Только leaf extraction из уже предоставленных текстов:
  извлечь таблицу, нормализовать факты, найти строку. Автономный web research,
  оценку источников и synthesis оставлять Opus/Sol.

### Оставить Sol medium

- неоднозначный `impl-*`/`fix-*`, где root cause ещё не найден;
- многофайловая repo-работа и terminal-heavy agent loops;
- тестирование, которое требует самостоятельного поиска нужного набора;
- миграции, persistence, concurrency, security, auth;
- финальный code review и исправление найденных дефектов;
- задачи, где Spark уже сделал более одного неудачного повтора.

### Оставить Opus 4.8

- оркестрация и декомпозиция;
- исследование, архитектура, сложная сравнительная оценка;
- 1M-context corpus/repo synthesis;
- image/vision;
- решения с неоднозначными trade-offs и высокий риск неверного суждения.

### Детерминированное дерево

```text
Text-only + ≤2 files + explicit AC + explicit test + low risk + short context?
├── yes → Spark leaf-worker
│   ├── test passes and AC satisfied → normal review/merge gate
│   └── test fails, scope expands, or >1 retry → escalate to Sol
└── no
    ├── implementation/debug/review → Sol medium
    └── research/architecture/orchestration/vision/long context → Opus 4.8
```

## 9. Предлагаемый A/B-пилот

Это рекомендации, а не внешние факты. Сначала провести не менее 20 парных
разведочных задач в каждой выбранной категории: механический edit,
known-root-cause fix и маленький impl. Один и тот же task spec случайно
назначать Spark или Sol; собирать:

- acceptance success без повторной реализации;
- wall time;
- tool calls и число retry;
- compaction;
- долю результатов, отклонённых Sol-review;
- дефекты после merge.

Разведочные 20 задач не дают достаточной статистической мощности сами по себе.
Перед изменением default накопить минимум 30 пар в конкретной категории и
посчитать paired bootstrap 90% CI для отношения median wall time, а также
Wilson 90% CI для success rate каждой модели. Политические пороги ниже —
guardrails небольшого MVP, не универсальные свойства моделей:

- success rate не ниже 95% от Sol;
- верхняя граница 90% CI для median wall-time ratio не выше 0.8;
- retries не выше 1.2x Sol;
- Sol-review rejection ниже 15%;
- ни одного security/data-loss regression;
- compaction менее чем в 10% коротких задач.

Остановить категорию досрочно после любого security/data-loss regression,
трёх acceptance failures или двух последовательных Sol-review rejections.
Если пороги не выполнены, оставить Spark только для mechanical/UI edits и
локальных lookup-задач.

## 10. Counter-evidence и неопределённости

- OpenAI заявляет «strong performance», но не публикует точные Spark scores в
  текстовой таблице; доступные числа являются чтением графика.[1][18][19]
- Raw decode Spark огромен, но наш microbench показал лишь 17% median
  end-to-end выигрыш против Opus на простой tool-задаче.
- Отдельная квота официальна, но один воспроизводимый пользовательский report
  показывает возможную зависимость от общего weekly gate.[11]
- AA слегка ставит Opus max выше Sol medium по Intelligence Index (56 vs 54),
  тогда как coding-agent system ставит Sol medium выше Opus max (75 vs 73).
  Разные effort и harness не позволяют превратить это в общий рейтинг моделей.
- Независимый RuleLedger v3 experiment с шестью Spark leaves улучшил medium
  root на одном benchmark, но потребовал больше токенов; solo high root был
  лучше, а Spark не улучшил лучший xhigh result.[20] Spark solo там не
  тестировался, поэтому это counter-evidence против «fan-out всегда выгоден»,
  а не прямой benchmark Spark.
- Spark — research preview: availability, rate limits, API и capabilities
  могут измениться после этого среза.

## 11. Уверенность по ключевым выводам

| Вывод | Уверенность | Причина |
|---|---|---|
| Spark = smaller, text-only, 128k, latency-first model на WSE-3 | **CONFIRMED** | Два первичных источника |
| Parameter count/архитектура весов не раскрыты | **CONFIRMED** | Официальный пробел; точных данных нет |
| Standard Codex file/shell tools работают | **CONFIRMED** | Официальный use case + прямой пилот |
| Spark расходуется отдельно от standard rate limit | **CONFIRMED** | Прямая формулировка OpenAI |
| Доступность после исчерпания global weekly | **UNCERTAIN** | Официальной гарантии нет; есть counter-report |
| Spark >1000 tok/s raw decode | **LIKELY** | OpenAI + Cerebras, но нет независимого AA |
| Spark быстрее Sol на коротком tool loop | **LIKELY** | Наш `n=3` microbench, ограниченная внешняя валидность |
| Spark сопоставим с Sol по coding quality | **UNCERTAIN** | Нет независимого apples-to-apples benchmark |
| Spark годится как default coding worker | **UNCERTAIN → default не менять** | Нет независимого quality evidence или edit-пилота |
| Spark годится как узкий leaf-executor | **LIKELY как кандидат пилота** | Официальный use case + lookup-пилот; coding A/B ещё нужен |

## 12. Затрагиваемые файлы, риски и edge cases

Research не меняет runtime. Если A/B-пилот будет одобрен, вероятно затронутся:

- `pipelines/default/pipeline.yaml` — routing/role assignment;
- prompt-модули worker/full-cycle — явные AC, test command и escalation;
- тесты routing/model selection;
- возможно `app/backend_codex.py` — только если появится официальная цена или
  model-specific compatibility, без выдуманной стоимости.

Не нужно повторно добавлять модель: она уже зарегистрирована в
`app/models.py` и `app/backend_codex.py`.

Риски пилота:

- незаметная деградация correctness на «маленькой», но связанной с глобальным
  контрактом правке;
- переполнение 128k из-за тяжёлого system prompt и verbose tool results;
- ложное ощущение резервной мощности, если общий weekly gate блокирует Spark;
- сэкономленная Sol-квота будет потрачена обратно на rework/review;
- text-only worker не сможет проверить визуальный результат UI-правки.

Guardrails: узкий scope, явный тест, automatic escalation после одного
расширения scope/повтора, Sol-review на пилоте и отдельные метрики по типу задач.

## Источники

Уровни: **T1** — прямое измерение; **T2** — первичный источник; **T3** —
независимый агрегатор/исследование; **T4** — единичное обсуждение или
непроверенное чтение графика.

1. **T2** OpenAI, “Introducing GPT-5.3-Codex-Spark” (2026-02-12): https://openai.com/index/introducing-gpt-5-3-codex-spark/
2. **T2** OpenAI Codex docs, “Speed / Codex Spark”: https://learn.chatgpt.com/docs/agent-configuration/speed#codex-spark
3. **T2** OpenAI, “Speeding up agentic workflows with WebSockets”: https://openai.com/index/speeding-up-agentic-workflows-with-websockets/
4. **T2** OpenAI Codex docs, “Pricing / usage limits”: https://learn.chatgpt.com/docs/pricing#what-are-the-usage-limits-for-my-plan
5. **T2** OpenAI Codex docs, “Tokens and credits”: https://learn.chatgpt.com/docs/pricing#what-are-tokens-and-credits
6. **T2** OpenAI Codex docs, “Models”: https://learn.chatgpt.com/docs/models
7. **T2** OpenAI Codex docs, “Subagents / model choice”: https://learn.chatgpt.com/docs/agent-configuration/subagents#model-choice
8. **T2** OpenAI Codex use case, “Make granular UI changes”: https://learn.chatgpt.com/use-cases/make-granular-ui-changes#pick-your-model
9. **T2** Anthropic, Claude Opus 4.8 docs and model overview: https://platform.claude.com/docs/en/about-claude/models/whats-new-claude-4-8 and https://platform.claude.com/docs/en/about-claude/models/overview
10. **T2** Cerebras, “OpenAI Codex-Spark on Cerebras”: https://www.cerebras.ai/blog/openai-codexspark
11. **T4** OpenAI Codex GitHub issue #19868, separate Spark limit blocked by global weekly: https://github.com/openai/codex/issues/19868
12. **T3** Artificial Analysis, GPT-5.6 Sol medium: https://artificialanalysis.ai/models/gpt-5-6-sol-medium
13. **T3** Artificial Analysis, Claude Opus 4.8: https://artificialanalysis.ai/models/claude-opus-4-8
14. **T3** Artificial Analysis, Codex vs Claude Code coding-agent comparison: https://artificialanalysis.ai/agents/coding-agents/comparisons/claude-code-vs-codex
15. **T3** Terminal-Bench 2.1 verified leaderboard: https://www.tbench.ai/leaderboard/terminal-bench/2.1
16. **T3** Artificial Analysis provider performance: https://artificialanalysis.ai/models/gpt-5-6-sol-medium/providers and https://artificialanalysis.ai/models/claude-opus-4-8/providers
17. **T2** OpenAI, “Separating signal from noise in coding evaluations”: https://openai.com/index/separating-signal-from-noise-coding-evaluations/
18. **T4** Reddit discussion reading Terminal-Bench 2.0 launch chart: https://www.reddit.com/r/codex/comments/1r30ti0/meet_gpt53codexspark/
19. **T4** Reddit discussion reading SWE-Bench Pro launch curve: https://www.reddit.com/r/codex/comments/1r30pvl/new_model_gpt53_codexspark_dropped/
20. **T3** Adam Owada, RuleLedger v3 Spark-mode efficiency whitepaper (2026-06-25): https://www.adamowada.com/whitepapers/spark-mode-efficiency-white-paper.pdf
21. **T1** Controlled Orchestra microbench, raw event timestamps from `/mnt/data/Projects/Python/orchestra/data/orchestra.db`, sessions `spark-pilot`, `spark-bench`, `spark-official`, reproducible query: [`microbench.sql`](microbench.sql), 2026-07-18.
