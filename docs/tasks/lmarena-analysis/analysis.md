# LMArena: анализ fleet-моделей

Дата выгрузки: **2026-07-24**. Основной snapshot text/agent: **2026-07-21**.

## Короткий вывод

- **Fable 5 — лидер fleet по human preference:** #1 в Overall, Coding, Creative
  Writing, Math, Instruction Following, Hard Prompts и Russian; #1 в Agent
  Arena. Против Opus 4.8 преимущество большое и во многих категориях выходит за
  95% CI.
- **Sol остаётся правильным дефолтом для code/impl:** #2 Agent Arena и #3 Code
  Arena, практически вничью с Fable (#1/#2), но использует отдельный,
  недогруженный Codex-пул. В text-coding Sol только #12 — для реальной
  разработки Agent/Code Arena релевантнее обычных chat coding prompts.
- **Opus 4.6 для brand copy — разумно, но не абсолютный лидер:** thinking-вариант
  #2 Creative Writing (1499.9), Fable #1 (1508.2). Их 95% CI пересекаются, поэтому
  2× расход лимита Fable не оправдан как постоянный дефолт.
- **Opus 4.8 для research/analysis лидербордом не подтверждается.** В Expert,
  Hard Prompts и Math он уступает Fable и Opus 4.6 thinking. Но LMArena не
  измеряет citation accuracy, deep-research workflow и 1M-context synthesis —
  4.8 можно оставить только как capability-driven escalation.
- При Claude 5h=65% и Codex 7d=7%: **все новые routine worker turns отправлять в
  Sol/Spark; Claude оставить оркестраторам и явным исключениям.** Для следующего
  5h-окна разумная цель — не менее 90% новых worker turns на Codex-пуле.

## Источник и метод

Первичный источник — официальный
[LMArena leaderboard dataset](https://huggingface.co/datasets/lmarena-ai/leaderboard-dataset),
revision
[`543e0628da0a445a3c8918967c1ef7311bc2d868`](https://huggingface.co/datasets/lmarena-ai/leaderboard-dataset/tree/543e0628da0a445a3c8918967c1ef7311bc2d868),
лицензия CC-BY-4.0.

Скачаны все 20 configs, оба split (`latest`, `full`): **40 CSV,
2,004,003 строки, 304,864,579 bytes**. Полные CSV лежат в
`/tmp/lmarena_data`; в Git сохранены [скрипт загрузки](download_dataset.py),
воспроизводимый extractor, fleet-срезы и [manifest с SHA-256](dataset-manifest.csv).

Для text использован `text_style_control/latest`: с 2025-05-16 style control
является дефолтной методикой LMArena. `rating` — Arena Score по Bradley–Terry;
Agent Arena использует отдельный IPS `score`, поэтому численные шкалы text и
agent **нельзя сравнивать между собой**. Интервалы в dataset — 95% CI.

Срезы:

- [все 29 text-категорий fleet](fleet-text-all-categories.csv);
- [9 запрошенных text-категорий](fleet-requested-text-categories.csv);
- [Agent aggregate + 5 signals](fleet-agent.csv);
- [Code Arena / WebDev](fleet-webdev.csv);
- [скрипт извлечения](extract_fleet.py).

`GPT-5.3 Spark` в dataset отсутствует. `gpt-5.3-chat-latest` и
`gpt-5.3-codex (codex-harness)` приведены только как близкие по имени записи;
это **не данные Spark**. Аналогично, Agent Arena называет Fable
`Claude Fable 5 (High)`, а text — `claude-fable-5`.

## Сравнительная таблица

Формат ячейки: **score (#rank)**. Rank считается относительно всех моделей в
конкретной категории.

### Text: Overall, Code, Creative, Math, Instruction Following

| Модель | Overall | Code | Creative | Math | Instr. Follow |
|---|---:|---:|---:|---:|---:|
| Fable 5 | **1507.3 (#1)** | **1553.1 (#1)** | **1508.2 (#1)** | **1542.7 (#1)** | **1513.2 (#1)** |
| Opus 4.8 | 1473.4 (#22) | 1529.6 (#10) | 1458.6 (#18) | 1476.1 (#22) | 1477.6 (#15) |
| Opus 4.8 thinking | 1483.6 (#13) | 1533.9 (#7) | 1463.3 (#14) | 1496.7 (#9) | 1494.4 (#5) |
| Opus 4.6 | 1497.8 (#4) | 1548.0 (#5) | 1478.2 (#7) | 1502.1 (#6) | 1498.7 (#4) |
| Opus 4.6 thinking | 1504.8 (#2) | 1550.0 (#3) | 1499.9 (#2) | 1518.5 (#3) | 1513.1 (#2) |
| Sol xHigh | 1485.1 (#11) | 1527.9 (#12) | 1471.5 (#9) | 1483.4 (#17) | 1485.3 (#7) |
| Sonnet 5 high | 1461.2 (#38) | 1524.5 (#15) | 1428.8 (#53) | 1467.7 (#34) | 1460.2 (#32) |
| GPT 5.5 high | 1481.7 (#14) | 1520.0 (#21) | 1448.2 (#27) | 1490.1 (#14) | 1477.9 (#14) |
| GPT 5.5 | 1476.3 (#16) | 1507.2 (#43) | 1447.1 (#29) | 1497.1 (#8) | 1471.5 (#19) |
| GPT 5.3 chat, не Spark | 1448.8 (#57) | 1497.1 (#58) | 1405.9 (#75) | 1426.4 (#87) | 1434.1 (#64) |

### Text: Hard Prompts, Multi-Turn, Expert, Russian

| Модель | Hard Prompts | Multi-Turn | Expert | Russian |
|---|---:|---:|---:|---:|
| Fable 5 | **1533.9 (#1)** | **1517.5 (#3)** | **1545.0 (#2)** | **1521.3 (#1)** |
| Opus 4.8 | 1504.8 (#11) | 1498.9 (#9) | 1514.1 (#10) | 1487.8 (#16) |
| Opus 4.8 thinking | 1512.8 (#7) | 1505.9 (#7) | 1525.6 (#6) | 1498.5 (#9) |
| Opus 4.6 | 1526.7 (#3) | 1511.2 (#5) | 1535.6 (#4) | 1509.2 (#3) |
| Opus 4.6 thinking | 1532.9 (#2) | 1517.5 (#4) | **1546.7 (#1)** | 1504.0 (#6) |
| Sol xHigh | 1505.6 (#9) | 1480.2 (#29) | 1523.5 (#7) | 1490.1 (#14) |
| Sonnet 5 high | 1490.8 (#29) | 1467.9 (#49) | 1513.8 (#11) | 1461.5 (#39) |
| GPT 5.5 high | 1501.1 (#16) | 1489.3 (#15) | 1517.4 (#8) | 1485.7 (#18) |
| GPT 5.5 | 1494.4 (#24) | 1480.6 (#28) | 1507.9 (#19) | 1479.0 (#23) |
| GPT 5.3 chat, не Spark | 1471.8 (#56) | 1466.7 (#51) | 1469.4 (#65) | 1459.5 (#42) |

### Agent Arena

| Модель | IPS score | Rank | 95% CI |
|---|---:|---:|---:|
| Fable 5 High | **0.1272** | **#1** | 0.1072…0.1472 |
| Sol xHigh | **0.1012** | **#2** | 0.0843…0.1182 |
| Opus 4.8 thinking | 0.0975 | #3 | 0.0836…0.1114 |
| Sonnet 5 high | 0.0866 | #5 | 0.0676…0.1055 |
| GPT 5.5 high | 0.0761 | #9 | 0.0680…0.0842 |
| Opus 4.6 | 0.0642 | #11 | 0.0519…0.0766 |
| GPT 5.5 | 0.0565 | #12 | 0.0489…0.0642 |
| Opus 4.8 | 0.0356 | #15 | 0.0191…0.0522 |
| Opus 4.6 thinking | — | — | отсутствует |
| GPT 5.3 / Spark | — | — | отсутствует |

### Code Arena / WebDev

| Модель | Arena Score | Rank | 95% CI |
|---|---:|---:|---:|
| Fable 5 | **1633.7** | **#2** | 1621.5…1645.9 |
| Sol xHigh (Codex harness) | **1629.7** | **#3** | 1618.8…1640.5 |
| Opus 4.8 thinking | 1565.5 | #5 | 1557.2…1573.8 |
| Sonnet 5 high | 1543.7 | #9 | 1533.1…1554.4 |
| Opus 4.6 thinking | 1542.4 | #10 | 1536.3…1548.5 |
| Opus 4.6 | 1535.9 | #13 | 1530.0…1541.8 |
| Opus 4.8 | 1534.1 | #14 | 1525.9…1542.3 |
| GPT 5.5 high (Codex harness) | 1483.1 | #25 | 1476.2…1490.0 |
| GPT 5.5 (Codex harness) | 1451.3 | #33 | 1444.3…1458.2 |
| GPT 5.3 Codex, не Spark | 1371.0 | #62 | 1360.2…1381.8 |

## 1. Fable 5 vs Opus 4.8 vs Sol

Для Opus взят лучший 4.8-вариант — thinking. «Различимо» ниже означает
непересекающиеся 95% CI; это консервативная эвристика, а не формальный
парный тест, потому что оценки моделей коррелированы.

| Категория | Fable | Opus 4.8 thinking | Sol | Вывод |
|---|---:|---:|---:|---|
| Overall | 1507.3 #1 | 1483.6 #13 | 1485.1 #11 | Fable различимо выше обоих |
| Agent | 0.1272 #1 | 0.0975 #3 | 0.1012 #2 | Fable по point estimate; CI всех пересекаются |
| Code (text) | 1553.1 #1 | 1533.9 #7 | 1527.9 #12 | Fable различимо выше обоих |
| Code Arena | 1633.7 #2 | 1565.5 #5 | 1629.7 #3 | Fable≈Sol; оба различимо выше Opus |
| Creative | 1508.2 #1 | 1463.3 #14 | 1471.5 #9 | Fable различимо выше обоих |
| Math | 1542.7 #1 | 1496.7 #9 | 1483.4 #17 | Fable различимо выше обоих |
| Instruction Following | 1513.2 #1 | 1494.4 #5 | 1485.3 #7 | Fable различимо выше обоих |
| Hard Prompts | 1533.9 #1 | 1512.8 #7 | 1505.6 #9 | Fable различимо выше обоих |
| Multi-Turn | 1517.5 #3 | 1505.9 #7 | 1480.2 #29 | Fable≈Opus; Fable различимо выше Sol |
| Expert | 1545.0 #2 | 1525.6 #6 | 1523.5 #7 | Fable по point estimate; CI пересекаются |
| Russian | 1521.3 #1 | 1498.5 #9 | 1490.1 #14 | Fable по point estimate; CI пересекаются |

## 2. Стоит ли использовать Fable вместо Opus

**Вместо Opus 4.8 — иногда да.** Fable заметно сильнее в обычном text/chat,
creative, coding, math, instruction following и hard prompts. Если задача
требует именно Claude и не требует уникальных возможностей 4.8
(1M-context/deep-research/citation workflow), Fable выглядит лучшим выбором.

**Вместо Opus 4.6 thinking — не по умолчанию.** Они близки:

- Overall 1507.3 vs 1504.8;
- Coding 1553.1 vs 1550.0;
- Creative 1508.2 vs 1499.9;
- Hard Prompts 1533.9 vs 1532.9;
- Multi-Turn 1517.5 vs 1517.5;
- Expert даже у Opus 4.6 thinking чуть выше: 1546.7 vs 1545.0.

95% CI в этих сравнениях пересекаются. Значит, **2× расход Claude quota не
окупается доказанным общим uplift**. Практический маршрут:

1. routine work → Sol;
2. final brand/voice → Opus 4.6;
3. Fable → ручной opt-in для дорогого финального результата или A/B, когда
   качество важнее лимита;
4. agentic/code → Sol, потому что он почти равен Fable в Agent/Code Arena и не
   ест Claude quota.

Вердикт claim «Fable стоит сделать новым Claude-default»: **❌ MOSTLY FALSE** при
текущей цене лимита. Claim «Fable сильнее Opus 4.8 в большинстве text-задач»:
**✅ TRUE** для snapshot 2026-07-21.

## 3. Sol vs Claude

Sol выигрывает или практически равен:

- **Code Arena:** #3, 1629.7; Fable #2, 1633.7 — статистически ничья; все Opus
  заметно ниже.
- **Agent Arena:** #2, 0.1012; Fable #1 и Opus 4.8 thinking #3 имеют
  пересекающиеся CI.
- против **Opus 4.8 thinking**: чуть выше Overall (1485.1 vs 1483.6) и Creative
  (1471.5 vs 1463.3), но различие неубедительно.

Sol проигрывает:

- Fable во всех запрошенных text-категориях по point estimate;
- Opus 4.6 thinking почти во всех text-категориях;
- особенно Multi-Turn: #29 против Fable #3 / Opus 4.6 thinking #4.

Итог: Sol не лучший «чат-писатель», но очень сильный **исполнитель с tools/code
harness**. Это как раз профиль worker-дефолта.

## 4. Проверка текущего routing

| Claim routing policy | Verdict | Данные |
|---|---|---|
| Sol = code/impl | **✅ TRUE** | Agent #2, Code Arena #3 и отдельный quota pool |
| Opus 4.6 = brand copy | **⚠️ MOSTLY TRUE** | Creative #2 thinking / #7 base; Fable #1, но CI Fable↔4.6 thinking пересекаются |
| Opus 4.8 = research/analysis | **❓ UNVERIFIABLE по LMArena** | Expert #6, Hard #7, Math #9; dataset не тестирует citation/deep research/1M context |
| Fable = универсальная замена Opus | **❌ MOSTLY FALSE** | сильнее 4.8, но почти ничья с 4.6 thinking и 2× расход Claude quota |
| Spark = быстрые leaf tasks | **❓ UNVERIFIABLE по LMArena** | точной модели Spark в dataset нет |

Текущий routing правильный по **default=Sol** и **brand=Opus 4.6**. Правило
`research → Opus 4.8` надо формулировать уже: не роль/тип задачи автоматически,
а escalation при явной нужде в citation precision, deep synthesis, vision или
1M context. Иначе начать с Sol.

Новый Russian split также исправляет прежний data gap: Fable #1, Opus 4.6 #3,
Opus 4.6 thinking #6, Opus 4.8 thinking #9, Sol #14. Но интервалы fleet-моделей
пересекаются, поэтому это направление, а не доказательство «русский только на
Claude».

## 5. Как разгрузить Claude

Проценты 5h и 7d нельзя сравнивать как одинаковые burn rates: окна разные. Но
65% короткого Claude-окна при 7% недельного Codex явно означает срочный перекос.

На ближайшее 5h-окно:

1. **Не запускать Fable автоматически.** Только manual escalation.
2. **Все routine code/impl/fix/review, research breadth и marketing routine →
   Sol.**
3. **Spark → bounded leaf tasks** по внутренней политике (текст, ≤2 файлов,
   чёткий AC и тест); Arena не даёт оснований расширять его область вслепую.
4. **Opus 4.6 оставить оркестраторам и final voice-sensitive copy.**
5. **Opus 4.8 запускать только при явном capability trigger**, а не на любое
   слово «research».
6. Цель: **≥90% новых worker turns на Codex-пуле**, Claude worker escalations
   ≤10% до сброса 5h-окна.

После сброса окна не откатывать policy: отдельный Codex-пул — first-order
фактор, а не аварийный режим. Fable проверять через внутренний blind A/B на
реальных brand-задачах; leaderboard не доказывает, что его небольшой uplift над
Opus 4.6 thinking окупает 2× quota.

## Ограничения

- LMArena измеряет **человеческое предпочтение**, а не объективную correctness,
  latency, price или успешность production-задач.
- Rank зависит от полного состава leaderboard и меняется быстрее абсолютного
  score.
- Text, Agent и WebDev — разные методики/шкалы; сравнивать можно порядок внутри
  arena, но не значения между arenas.
- Некоторые runtime aliases/harness отличаются от моделей в подписке.
- У Sol меньше votes в text-категориях, поэтому CI шире; выводы по Russian,
  Expert и Math менее устойчивы.
- Непересечение CI — полезная эвристика, но не замена парному статистическому
  тесту.

## Дополнительный capability-контекст

LMArena — главный источник чисел в этом отчёте. Для routing учтены также
официальные описания поставщиков, но как vendor evidence, а не независимое
сравнение:

- [Anthropic: Introducing Claude Opus 4.8](https://www.anthropic.com/news/claude-opus-4-8)
  заявляет улучшения long-running analysis и более активное обнаружение проблем
  во входных данных/выводах. Это объясняет research escalation, но не отменяет
  слабые LMArena point estimates.
- [OpenAI: GPT-5.6 launch](https://openai.com/index/gpt-5-6/) позиционирует Sol
  для coding, knowledge work и long-horizon agents; это согласуется с Agent и
  Code Arena.
