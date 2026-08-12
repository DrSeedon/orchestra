# #204 — Чужие данные про эффорт и про выбор модели под класс задачи

**Фаза 1, ресёрч по внешним источникам. Своего стенда не строил, моделей не гонял, квоту на замеры не жёг.**
Дата сбора: 12.08.2026. Всё, что ниже, помечено как **[ЗАМЕР]** (кто-то прогнал и опубликовал числа),
**[ВЕНДОР]** (заявление производителя), **[МНЕНИЕ]** (текст без чисел) или **[НЕ ПРОВЕРЕНО]**.

---

## Прямой ответ на вопрос юзера

**Короткий ответ: за верхние ступени эффорта мы платим, не имея доказательств, что они что-то дают.**
На нашей рабочей модели (Opus 5) по независимому замеру Artificial Analysis подъём `high → xhigh`
стоит **+47 % цены прогона** ($1 974 → $2 909 за один и тот же набор из девяти бенчмарков) и
не даёт ни одного значимого прироста ни на одном из бенчмарков по отдельности: на длинном
контексте ровно 0.000 (AA-LCR 0.763 → 0.763), на агентном кодинге +0.4 п.п., на многоходовом
тул-юзе −1.4 п.п. Composite-индекс двигается на +1.0 балла, **но и это не доказанный прирост** —
AA публикует неопределённость для точки, а не для разности, парных результатов по задачам нет,
и при их же ±1 % на точку интервал разности был бы шире самой разности (см. раздел 1).

На той же лестнице у дешёвой Luna переход `medium → xhigh` даёт **+24.7 п.п. на Terminal-Bench**
и +11.2 п.п. на HLE — всё значимо. **[ДОПУЩЕНИЕ, не замер]** объяснение, которое я из этого вывожу:
эффорт работает там, где модели не хватает собственного потолка. Строго измерено другое, более
узкое: *в семействе GPT-5.6 на этой короткой бенчмарк-сюите Luna отреагировала на подъём эффорта
сильнее, чем Opus 5.* Универсального правила «эффорт для слабой модели» отсюда не следует.

Отдельно про «ресёрч против сложного кода»: **данных, которые бы это различили, в мире нет.**
Ни одного эффорт-свипа на BrowseComp / GAIA / FRAMES / DeepResearch Bench не опубликовано (искали
двое, независимо). Есть косвенное: на HLE (ближайший к ресёрчу закрытый прокси) Opus 5 растёт
монотонно, но по 1.5–1.6 п.п. на ступень; на **открытых** задачах FrontierCS подъём `medium → high`
не просто не помог, а уронил счёт с 15.34 до 12.63; на открытом письме включение reasoning целиком
даёт +0.3…+1.2 %, тогда как на AIME то же вмешательство даёт +200 %.

**Что из трёх независимых свипов устойчиво, а что нет.** Устойчиво: **выше `high` все кривые плоские
или отрицательные.** Неустойчиво: где именно колено — у AA оно на `low → medium`, у OckBench на
`medium → high`, и на этом расхождении ничего строить нельзя (разбор в разделе 1).

**Три изменения в нашей маршрутизации, которые дадут больше всего:**

1. **`full-cycle: xhigh → high`** (`pipelines/default/pipeline.yaml:71`), но **только после замера A**
   (раздел 10). Мы держим xhigh, потому что так рекомендовала Anthropic для Opus 4.7/4.8. Для Opus 5
   вендор рекомендацию **развернул** — «Start with `high`, the default» — и отдельной строкой велел не
   переносить настройку с прошлого поколения: «If you carried effort settings over from an earlier
   model, run a fresh effort sweep on your evals rather than reusing them». Мы её перенесли и свип не
   гоняли. Честный контраргумент, который я не могу закрыть: вендор оправдывает `xhigh` **длиной
   горизонта** («over 30 minutes… token budgets in the millions»), а все доступные замеры короче
   наших сессий — см. раздел 6.
2. **Проверить гипотезу, что наши классы правильнее резать по ДЛИНЕ ЦЕПОЧКИ, а не по ярлыку
   «сложная / механическая».** В контролируемом замере (ICLR 2026, arXiv:2509.09677) слабая модель
   делает **первый шаг почти безошибочно** — знание и план ей выданы явно, — и всё равно
   разваливается к 15-му шагу; «больше модель» покупает число шагов до развала, а не понимание шага.
   **Статус для нас — [ДОПУЩЕНИЕ]:** мерили Qwen3/Gemma3 без тулов, перенос на Opus/Sol не
   подтверждён даже в направлении. Но проверяется он у нас **бесплатно** — запросом к своей же БД
   (замер D, раздел 10): медиана числа ходов на задачу по классам. Если гипотеза верна, «аудит
   логов» и «механические правки» окажутся в разных корзинах, хотя сейчас лежат в одной.
3. **Эффорт выбирать на сессию, а не на фазу.** Соблазнительная идея «ресёрч на medium, реализация
   на xhigh внутри одного full-cycle» ломает prompt cache: «changing the effort value between requests
   invalidates prompt caching». У нас 68 % расхода — это `cache_read` (#178), то есть такая
   «оптимизация» стоила бы дороже, чем экономила. Хочешь разный эффорт — разводи по разным воркерам.

Отдельно — то, что мы могли бы внедрить дешевле всего: **на коротких классах поднимать эффорт младшей
модели вместо перехода на старший тир.** Luna на `xhigh` и Terra на `high` дают одинаковый индекс 50.1
при цене прогона $95 против $395 — вчетверо дешевле. Ограничение: это верно для коротких цепочек;
на длинных находка из пункта 2 говорит обратное.

---

## Как поставлен вопрос и что считалось бы опровержением

**Вопрос:** для каких классов нашей работы подъём эффорта и переход на старшую модель окупаются, и
на чьих данных это можно утверждать?

Три конкурирующие гипотезы, записаны до сбора:

- **H1.** Эффорт окупается на верифицируемых задачах (код, математика) и не окупается на открытых
  (ресёрч, проза, суждение).
- **H2.** Наоборот: эффорт окупается именно на открытых задачах, потому что там нужна ширина
  исследования, а на закрытых модель и так знает ответ.
- **H3.** Эффорт покупает не «ум за токен», а **длину горизонта и настойчивость в тул-вызовах**;
  значит он важен там, где работа длинная и агентная, независимо от открытости.

Фальсификаторы: для H1 — опубликованный свип, где прирост на research-бенче не меньше, чем на
SWE-bench; для H2 — свип, где на research-бенче прирост плоский; для H3 — свип, где прирост есть на
одноходовых задачах и отсутствует на агентных.

**Что получилось.** H2 отвергнута: единственный найденный свип на открытых задачах (FrontierCS)
показал падение. H1 подтверждена частично и на другой оси — не «low→max», а «думать / не думать».
**H3 оказалась ближе всех к истине, и её пришлось уточнить** (раздел 6): решает не «агентность» и не
«открытость», а **число шагов до развала**. Вендорское описание эффорта это подпирает с другой
стороны — низкий эффорт прямо описан как «**fewer tool calls**», то есть эффорт торгует длиной
работы, а не глубиной отдельной мысли.

**Побочный результат, которого я не планировал:** на том стенде, где это проверяли (arXiv:2509.09677,
Qwen3/Gemma3, без тулов), обе оси, по которым мы сейчас режем классы («сложная / простая»,
«открытая / закрытая»), зафиксированы — и разница между тирами всё равно велика, а объясняет её
длина цепочки. Верно ли это для НАШИХ моделей и классов — не проверено. Это разворачивает не ответ,
а вопрос, который стоит задать.

---

## 1. Лестница эффорта: единственный полный независимый свип с ценой

Artificial Analysis публикует один и тот же набор из девяти бенчмарков для **каждой ступени эффорта
отдельно** и приводит фактическую стоимость прогона. Это самый близкий к нашему вопросу открытый
источник: индекс взвешен агентно (Agents 34 %, Coding 24 %, Scientific Reasoning 24 %, General 18 %).
Данные сняты 12.08.2026, сырьё сохранено в `docs/tasks/204/aa-index-by-effort.json`.

**[ЗАМЕР]** — https://artificialanalysis.ai/models/gpt-5-6-luna-xhigh (числа лежат в
`__next_f` самой страницы), методика — https://artificialanalysis.ai/methodology/intelligence-benchmarking

### Claude Opus 5 (наша модель во всех ролях)

| effort | Индекс | Agentic | AA-LCR (длинный ctx) | Terminal-Bench 2.1 | τ³-Banking (тул-юз) | HLE | $ за суиту | с/задача |
|---|---|---|---|---|---|---|---|---|
| low    | 52.5 | 42.1 | 0.770 | 0.764 | 0.303 | 0.434 | 555 | 80 |
| medium | 58.6 | 50.4 | 0.787 | 0.861 | 0.386 | 0.513 | 1 116 | 151 |
| high   | 61.5 | 56.1 | 0.763 | 0.876 | 0.447 | 0.528 | 1 974 | 259 |
| xhigh  | 62.5 | 58.4 | 0.763 | 0.880 | 0.433 | 0.544 | 2 909 | 384 |
| max    | 63.1 | 59.2 | 0.757 | 0.891 | 0.421 | 0.549 | 3 836 | 478 |

Переходы, с проверкой на значимость (биномиальная ошибка по числу инстансов из методики AA:
AA-LCR 100×3, Terminal-Bench 89×3, τ³ 97×5, HLE 2 158×1, GPQA 198×5):

| переход | цена | Δиндекс | AA-LCR | TB 2.1 | τ³ | HLE |
|---|---|---|---|---|---|---|
| low → medium | ×2.01 | +6.2 не проверен | +0.017 шум | +0.097 значимо° | +0.082 значимо° | +0.079 значимо° |
| medium → high | ×1.77 | +2.8 не проверен | −0.023 шум | +0.015 шум | +0.062 шум | +0.015 шум |
| high → xhigh | ×1.47 | +1.0 не проверен | ±0.000 шум | +0.004 шум | −0.014 шум | +0.016 шум |
| xhigh → max | ×1.32 | +0.5 не проверен | −0.007 шум | +0.011 шум | −0.012 шум | +0.005 шум |

° «Значимо» здесь — при допущении независимости повторов, которое не выполняется; см. разбор ниже.
Вердикты «шум» от этого допущения не страдают, вердикты «значимо» — страдают.

**Читать так.** Выше `medium` **ни один отдельный бенчмарк не показывает значимого прироста.**
Двигается только composite-индекс. Соблазнительно сказать «зато composite значим, он же агрегирует
девять оценок» — **и это была бы ошибка, которую я сначала и сделал.** AA заявляет 95 % CI «менее
±1 %» **для оценки одной конфигурации, а не для разности двух.** Даже если бы каждая точка имела
ровно ±1 балл и была независимой, интервал разности составил бы ≈±1.41 балла — то есть шире, чем
сами +1.0. А конфигурации прогоняются на одном наборе задач, значит нужна ковариация или bootstrap
по задачам; ни того, ни другого AA не публикует, в JSON лежат только агрегаты.

**Честный статус: `high → xhigh` = +47 % цены при НЕ УСТАНОВЛЕННОМ приросте.** Не «маленький
прирост» — именно не установленный. Для нашего решения это важнее: мы платим за то, чего никто
не измерил.

**Про мою собственную оценку ошибки, точно.** Я взял `N = задачи × повторы` и независимую формулу
разности долей `SE = √(p₁(1−p₁)/N₁ + p₂(1−p₂)/N₂)`. Повторы идут по одним и тем же задачам, то есть
положительно коррелированы, эффективный размер выборки меньше моего, **SE занижена, интервалы у́же
настоящих — оценка антиконсервативная.** Отсюда два разных следствия, и их нельзя путать:

- вердикты **«в пределах шума» от этого только крепнут** (с настоящими, более широкими интервалами
  они тем более не значимы);
- вердикты **«значимо» (строка `low → medium`) — наоборот, ослаблены** и строго говоря требуют
  task-level данных, которых у меня нет. Считать их указанием на направление, а не доказательством.

Минус на τ³ (`high → xhigh`, −1.4 п.п.) — **не** доказательство, что xhigh хуже на тул-юзе. Это
отсутствие разницы. Утверждать регрессию на такой выборке нельзя.

### Вторая, независимая лестница по той же модели — и она НЕ согласуется в точке перегиба

**[ЗАМЕР]** OckBench, arXiv:2511.05722, 200 задач (100 math / 60 coding / 40 science), сырой CSV
`https://ockbench.github.io/static/data/top200_model_performance.csv`:

| effort | Accuracy | Avg output tokens | OckScore |
|---|---|---|---|
| low | 85.0 % | 1 623 | 83.50 |
| medium | 85.0 % | 4 215 | 81.48 |
| **high** | **94.0 %** | 6 745 | **88.84 (лучший)** |
| xhigh | 95.0 % | 9 740 | 88.20 |
| max | 94.5 % | 13 130 | 86.11 |

По доменам: **coding насыщается на `high` полностью** (100.0 % и дальше ничего, при этом xhigh тратит
вдвое больше токенов), math даёт +1 п.п. за `high→xhigh` и **0** за `xhigh→max` при +39 % токенов,
science — единственный домен, где xhigh реально помог (+2.5 п.п.), и там же max откатился на −2.5 п.п.

**Два замера расходятся в том, где колено.** У AA прыжок на `low→medium`, у OckBench — на
`medium→high`. Это не «кто-то ошибся»: у OckBench в строке `medium` девять прогонов Opus 5 упали с
пустым выходом и засчитаны как неверные (авторы это документируют), то есть их `medium` занижен
артефактом стенда. Но и без этого две выборки разного состава дают разное колено — **значит
универсального «правильного уровня» из чужих данных не извлекается, он зависит от смеси задач.**
Согласуются они в другом, и согласуются жёстко: **выше `high` обе кривые плоские или отрицательные.**

### Третий независимый свод, форма кривой та же

**[ЗАМЕР]** OccuBench (arXiv:2604.10866, §6.5), профессиональные агентные задачи, дословно:
«GPT-5.2 exhibits a clear monotonic trend, scaling from **none (54.7 %) to xhigh (82.2 %), a 27.5-point
improvement**… Claude Opus 4.6 shows a similar overall trend, with its highest effort level **max
(73.8 %) outperforming low (70.2 %) by 3.6 points**».

Заголовочные +27.5 п.п. меряются **от режима без reasoning вообще**. Там, где обе точки — настоящие
уровни рассуждения (Opus 4.6, low→max), весь диапазон даёт **3.6 п.п.**

**[ЗАМЕР, ⚠️ через пересказ WebFetch, дословность не гарантирую]** Artificial Analysis на запуске
GPT-5: Intelligence Index `minimal 44 / low 64 / medium 67 / high 68`, при этом «GPT-5 with reasoning
effort high uses **23× more tokens** than with reasoning effort minimal». Тот же вогнутый профиль:
+20 / +3 / +1.

---

## 2. Эффорт — рычаг для СЛАБОЙ модели, а не для сильной

Тот же датасет AA, но по семейству GPT-5.6:

| модель | эффорт | Индекс | AA-LCR | TB 2.1 | τ³ | HLE | $ за суиту |
|---|---|---|---|---|---|---|---|
| Sol | medium | 55.6 | 0.743 | 0.861 | 0.365 | 0.422 | 580 |
| Sol | xhigh | 59.0 | 0.763 | 0.895 | 0.381 | 0.473 | 1 525 |
| Terra | medium | 46.8 | 0.703 | 0.723 | 0.256 | 0.333 | 192 |
| Terra | high | 50.1 | 0.733 | 0.757 | 0.287 | 0.385 | 395 |
| Terra | xhigh | 52.8 | 0.750 | 0.801 | 0.297 | 0.419 | 590 |
| Luna | medium | 38.9 | 0.720 | 0.532 | 0.177 | 0.258 | 21 |
| Luna | high | 47.0 | 0.740 | 0.697 | 0.252 | 0.334 | 55 |
| Luna | **xhigh** | **50.1** | 0.733 | 0.779 | 0.287 | 0.370 | **95** |
| Luna | max | 52.3 | 0.783 | 0.809 | 0.311 | 0.395 | 172 |

- **Luna `medium → xhigh`**: Terminal-Bench **+24.7 п.п.**, τ³ +10.9, HLE +11.2, GPQA +3.6 — все
  значимы. Цена ×4.50. Сравни с Opus 5 `medium → xhigh`, где значим ноль показателей из пяти.
- **Luna (xhigh) = Terra (high) = индекс 50.1**, при цене прогона $95 против $395. Подъём эффорта на
  младшей модели дешевле, чем переход на средний тир, **вчетверо**.
- **Luna (max) 52.3 ≈ Terra (xhigh) 52.8** — $172 против $590.

**[ДОПУЩЕНИЕ]** Отсюда напрашивается «на фиксированный бюджет качества дешевле поднять эффорт снизу,
чем взять тир сверху», и это противоречит привычному «сложное → бери модель побольше». Но замерено
только равенство **агрегатов** на этой сюите; равенство индексов не означает равенства на нашем
классе работы. **[ЗАМЕР]** тут — сами числа, не вывод из них.

Наш собственный #199 этому не противоречит: мы мерили эффорт только на Sol и получили ×2.04 цены при
том же вердикте — то есть попали в ту часть кривой сильной модели, где прироста не видно.

Где дешёвая модель отстаёт сильнее всего — видно по колонкам, и это **не** длинный контекст:
Luna(medium) на Terminal-Bench 0.532 против Sol(medium) 0.861, на τ³ 0.177 против 0.365; на AA-LCR
при этом 0.720 против 0.743. **[ДОПУЩЕНИЕ]** напрашивающееся объяснение — «слабое место младшей
модели это многоходовой агентный тул-юз»; строго говоря, Terminal-Bench и τ³ показывают разрыв, но
не изолируют его причину: обе задачи отличаются от AA-LCR и многоходовостью, и наличием тулов, и
кодовой природой. Разделить эти факторы на имеющихся данных нельзя.

---

## 3. Длинный контекст: чужой контрсигнал против Luna не воспроизводится

Это была единственная причина не пускать Luna на длинные сессии.

- **Что говорил источник.** Vellum, 03.08.2026: «MRCR Long-Context Recall: Sol 91.5 %, Terra 89.6 %,
  **Luna 41.3 %**… That is a cliff». Атрибуция там же: «Source: OpenAI GPT-5.6 release, July 9, 2026.
  Score: Nerova.»
- **Проверка атрибуции.** Открыл первоисточник, на который ссылается Vellum, —
  https://openai.com/index/previewing-gpt-5-6-sol/ (57 КБ сырого текста через `r.jina.ai`).
  **Слова «MRCR» на странице нет вовсе, таблицы с 41.3 % нет.** То есть **ссылка на первоисточник у
  этого числа не подтверждается**; откуда оно и на каком уровне эффорта снято — неизвестно.
- **Независимая проверка по существу.** AA-LCR меряет ровно ту способность, ради которой мы бы
  боялись: 100 вопросов по ~100 000 токенов, ответ не лежит в тексте и должен быть выведен из
  нескольких документов, **без тулов**. Luna по ступеням: `non-reasoning 0.387`, `low 0.653`,
  `medium 0.720`, `high 0.740`, `xhigh 0.733`, `max 0.783`. Sol: 0.570 / 0.730 / 0.743 / 0.753 /
  0.763 / 0.777. **Обрыв у Luna есть ровно один — в режиме без рассуждения.** На любом рабочем
  эффорте Luna от Sol на этой задаче не отличается.
- **Гипотеза, которую я НЕ доказал**, но обязан назвать: 0.387 у Luna(non-reasoning) численно
  близко к 41.3 % из Vellum. Это разные бенчмарки, и совпадение может быть случайным. Но оно даёт
  правдоподобное объяснение «обрыва»: похоже, мерили конфигурацию без рассуждения. **Проверить это
  нечем — исходной методики нет.**
- **Наш собственный #199 (T4) согласуется:** Luna взяла 5/5 иголок из 164 К токенов нашего кода в
  трёх испытаниях из трёх, наравне с Sol.

**И главное для нашей маршрутизации:** у Opus 5 AA-LCR по эффорту **не растёт** — 0.770 / 0.787 /
0.763 / 0.763 / 0.757 при интервале ±0.068. Формулировать это надо аккуратно: **польза от подъёма
эффорта на длинном контексте не обнаружена**, а не «доказано, что её нет» — интервалы широкие,
100 вопросов. Практический вывод тот же (платить не за что), статус слабее.

Единственное, что из этих данных следует про режим без рассуждения: **на AA-LCR** Luna без
рассуждения проваливается (0.387 против 0.720 на `medium`), у Sol там же 0.570 против 0.743.
**[ДОПУЩЕНИЕ]** переносить это на наше извлечение как правило «не гонять извлечение на выключенном
рассуждении» — разумно, но это моя рекомендация, а не установленный факт: AA-LCR не наша задача,
и гипотеза про MRCR (выше) в этом выводе не участвует.

Оговорка о применимости: AA-LCR — это чтение документов без тулов и одним ходом. Наш длинный
контекст другой: он накапливается тул-выхлопом за много ходов. Перенос вывода на нашу работу —
**принятое допущение, не замер.**

---

## 4. Что говорят вендоры (это заявления, не данные)

### Anthropic, `docs.claude.com/en/docs/build-with-claude/effort` — **[ВЕНДОР]**, сырой markdown

Механика, важная нам напрямую:

> «The effort parameter affects **all tokens** in the response, including: Text responses and
> explanations; **Tool calls and function arguments**; Thinking (when active).»
> «For example, **lower effort would mean Claude makes fewer tool calls.**»

И раздел «Effort with tool use» перечисляет буквально: низкий эффорт — «Combine multiple operations
into fewer tool calls», «Make fewer tool calls»; высокий — «**Make more tool calls**», «Explain the
plan before taking action», «Provide detailed summaries of changes».

**Это переопределяет смысл эффорта для нас.** У нас ≈$0.13 на тул-вызов и 68 % суммы — `cache_read`
(#178). Значит эффорт у нас — не «глубина мысли за те же деньги», а **прямой множитель на
доминирующую статью расхода.** Прирост качества, как показано выше, при этом внутри шума.

Про кеш, тоже дословно:

> «Because effort shapes the rendered prompt, **changing it between requests does not preserve cached
> prefixes from earlier turns**; if you rely on prompt caching across a long session, pick an effort
> level at the start and keep it constant.»

Рекомендации по уровням:

> `low` — «Simpler tasks that need the best speed and lowest costs, **such as subagents**»
> `medium` — «Agentic tasks that require a balance of speed, cost, and performance»
> `high` — «High capability. **Equivalent to not setting the parameter.**»
> `xhigh` — «Long-running agentic and coding tasks (**over 30 minutes**) with token budgets **in the millions**»
> `max` — «Tasks requiring the deepest possible reasoning and most thorough analysis»

Для **Opus 5** (наш случай), полностью:

> «Claude Opus 5 supports all five effort levels. **Start with `high`, the default**, and adjust based
> on your evals: step up to `xhigh` for demanding coding and agentic work, or to `max` when a task
> justifies unconstrained token spending, and use `low` and `medium` liberally as your primary control
> for token cost and response time wherever your evals show quality holds. **If you carried effort
> settings over from an earlier model, run a fresh effort sweep on your evals rather than reusing them.**»

Для Opus 4.7/4.8 (откуда мы свой xhigh и унаследовали) формулировка была обратной — «**Start with
`xhigh` for coding and agentic use cases**», и там же `xhigh` описан как «The recommended starting
point for coding and agentic work, and for **exploratory tasks such as repeated tool calling, detailed
web search, and knowledge-base search**». Про `max` даже в той версии сказано: «On most workloads
`max` adds significant cost for relatively small quality gains, and on some structured-output or less
intelligence-sensitive tasks **it can lead to overthinking**».

То есть **вендор считает, что xhigh — как раз для ресёрча с тулами** (это и есть прямой ответ «да» на
вопрос юзера в вендорской версии), но для Opus 5 он же понизил стартовую точку до `high` и потребовал
собственного свипа. Замеренный слой (раздел 1) вендорское «xhigh для ресёрча» **не подтверждает**:
выше `high` там нет установленного прироста ни на одном бенчмарке. Но и не опровергает — свипа на
ресёрч-бенче с тулами не существует, а вендор оправдывает `xhigh` длиной горизонта, которой никто
не мерил. **Это открытое противоречие, а не решённый вопрос.**

Ещё одна строка, отвечающая на «как заставить модель не тупить»:

> «If you observe shallow reasoning on complex problems with Claude Opus 4.7, **raise effort rather than
> prompting around it.**» — и симметрично: «Pair `low` with **explicit checklists** if your task has
> multiple sections.»

### OpenAI — **[ВЕНДОР]**

`developers.openai.com/api/docs/guides/reasoning.md`, дословно по ступеням:
> `medium` — «**Default configuration for most workloads, and a well-balanced point on the pareto
> curve**… Common use cases include agentic coding, **research**, working with spreadsheets & slides,
> and delegating long-horizon work.»
> `high` — «agentic coding, **long-horizon research**, and knowledge work. **Depending on the
> complexity of the task, evaluate both `medium` and `high`.**»
> `xhigh` — «Deep research, asynchronous workflows and agentic tasks that require long runs. **Only use
> when your evals show a clear benefit that justifies the extra latency and cost.**»
> `max` — «If you are currently using `xhigh`, evaluate if `max` results in stronger performance.»

`learn.chatgpt.com/docs/models.md` — про выбор тира, дословно (и это лучший найденный вендорский
ответ на «как заставить дешёвую модель не тупить»):
> «**Sol, for complex, open-ended work.** Choose Sol for ambiguous, difficult, or high-value tasks that
> need extra analysis, judgment, or polish, such as complex code changes, **deep research**, or polished
> documents. **For narrower tasks, define what done looks like to keep the work focused.**»
> «**Luna, for clear, repeatable tasks.** Choose Luna for specific, high-volume tasks **when you know
> what a good result looks like**, such as extraction, classification, transformation, and structured
> summaries.»
> «**Use the lowest reasoning effort that produces the result you need.**»
> «**There is no exact mapping from GPT-5.5 reasoning efforts to GPT-5.6.**»
> «**Most tasks do not need Max or Ultra.**»

Условие применимости младшей модели вендор формулирует как свойство **задания**, а не задачи: «когда
ты знаешь, как выглядит хороший результат». Это ровно наш собственный урок из `CLAUDE.md` («объём
выхлопа задаёт формулировка задания, а не модель»), пришедший с другой стороны.

Ещё: «GPT-5.6 Sol, Terra, and Luna models **all demonstrate strong improvements in cyber capabilities
as we increase reasoning**» (openai.com/index/previewing-gpt-5-6-sol/) — вендорское утверждение, что
на длинногоризонтных задачах эффорт помогает всем тирам. Чисел на странице нет.

### Расхождение с нашим кодом, которое стоит починить отдельно

`app/backend_codex.py:50-51` описывает лестницу `light→low→medium→high→xhigh→max→ultra`. По актуальной
доке `learn.chatgpt.com/docs/config-file/config-reference.md` в конфиге Codex CLI
`model_reasoning_effort` принимает `minimal | low | medium | high | xhigh`; `max` и `ultra` — это
поверхности ChatGPT-приложения, а `ultra` вдобавок не уровень, а режим с суб-агентами. В коде это уже
оговорено комментарием, менять ничего не предлагаю — фиксирую, что комментарий верен.

---

## 5. Единственный найденный свип на ОТКРЫТЫХ задачах — и он против эффорта

**[ЗАМЕР]** FrontierCS, arXiv:2512.15699, 156 открытых задач, «problems where the optimal solution is
unknown, but the quality of a solution can be objectively evaluated». Раздел 5.1 называется
дословно «**Improving Reasoning Effort Does Not Yield Further Gains**»:

| effort | Avg reasoning tokens | Avg score |
|---|---|---|
| GPT-5 low | 4 389 | 7.903 |
| GPT-5 medium | 11 554 | **15.336** |
| GPT-5 high | 19 763 | **12.626** |

> «As expected, we observe a clear positive correlation between reasoning effort when comparing low and
> medium reasoning levels. However, **increasing the reasoning effort from medium to high does not yield
> further gains; in fact, performance drops from 15.336 to 12.626**, suggesting diminishing returns at
> higher reasoning budgets.»

Оговорки, без которых это цитировать нельзя: модель — **GPT-5 Thinking**, поколение назад; лестница
старая (low/medium/high); 3 попытки на задачу; **доверительных интервалов авторы не приводят**, так
что «падение» может быть шумом — утверждать можно только «прироста нет».

Оттуда же два наблюдения, которые бьют прямо в наш класс «ревью» и в наш класс «ресёрч»:

> «**Misleading Micro-Optimization Trap**… the model often fixates on small, low-impact optimizations
> while overlooking the core algorithmic choices required for substantial performance gains.»
> «models tuned for closed-form software engineering tasks may still **struggle to produce
> high-performance solutions for open-ended algorithmic problems**… merely producing workable solutions
> is insufficient for open-ended tasks.»

### Асимметрия «верифицируемое vs открытое» — замерена, но на другой оси

**[ЗАМЕР]** R2-Write, arXiv:2604.03004, Table 1 — одна и та же модель, тумблер thinking on/off:

| бенчмарк | Qwen3-30B-A3B | Qwen3-8B | V3.1 → R1-0528 |
|---|---|---|---|
| WritingBench (открытое письмо) | **+1.2 %** | +0.8 % | +0.3 % |
| HelloBench (long-form) | +0.7 % | +0.4 % | +0.7 % |
| MATH500 | +10.5 % | +11.1 % | +7.2 % |
| AIME 25 | **+200.4 %** | +221.5 % | +99.3 % |

**[ЗАМЕР]** AGC-Bench, arXiv:2607.01152, дословно: «Prompting 18 frontier models to "be creative"
rather than "be effective" produced a large upward shift (**dz = +1.40**)… In contrast, **enabling
reasoning (vs. baseline) on 10 different reasoning-capable models produced a much smaller composite
shift (dz = +0.34), roughly one-quarter the magnitude.**»

То есть на открытой работе **одна строка в промпте даёт вчетверо больший сдвиг, чем включение
рассуждения целиком.** Это самый сильный аргумент за то, что для ресёрча деньги лежат в постановке
задачи, а не в ползунке эффорта.

---

## 6. Правильная ось — не «сложность», а ДЛИНА ЦЕПОЧКИ

Это главная находка обзора, и она пришла не из бенчмарков моделей, а из работы, которая
целенаправленно изолировала исполнение от знания.

**[ЗАМЕР]** arXiv:2509.09677 (ICLR 2026, версия v3 от 13.03.2026). Модели дают знание и план
**явно**, дальше меряют, сколько шагов она проживёт. Дословно:

> «**Result 1: Execution alone is challenging.** … all models except Gemma3-4B and Qwen3-4B achieve
> **near-perfect accuracy on the first step**, confirming they have the knowledge required to perfectly
> do a single step of our task. Yet, task accuracy falls rapidly over subsequent turns. **Even the
> best-performing model (Qwen3-32B) sees its accuracy fall below 50 % within 15 turns.**»

> «**Result 2: Non-diminishing benefits of scaling model size.** … larger models sustain higher task
> accuracy for significantly more turns… This observation is non-trivial. While the benefits of
> increasing model size are often attributed to improved capacity for knowledge, **our task is not
> knowledge-constrained**, as models achieve near-perfect first step accuracy, **nor is the task more
> complex**… **Yet, larger models are clearly more reliable at executing the task for longer.**»

Формализм там же: при точности шага *p* успех цепочки из *t* шагов равен *p^t*, длина горизонта
растёт гиперболически с ростом *p* и особенно резко после 80 % точности шага.

**Какую гипотезу это нам подсказывает.** Мы (и вендоры, и все обвязки из #194) режем классы по
«сложности» и «открытости». В этом замере обе оси зафиксированы — задача не сложнее, знание есть,
план выдан, — и разница между тирами всё равно огромна. **Отсюда стоит проверить гипотезу, что наш
собственный разрез классов правильнее вести по числу шагов** — но именно проверить: замер сделан на
других моделях и без тулов, и следствием из него наш разрез не является. Если гипотеза подтвердится,
«механические правки в два файла» и «аудит логов за сутки», которые сейчас лежат у нас в одной
корзине «простое», окажутся на разных концах шкалы.

Прямое следствие для пункта про дешёвые классы: подъём эффорта на младшей модели равен переходу на
старший тир **по агрегату на короткой сюите** (там и мерили AA — Terminal-Bench, τ³). На длинных
цепочках эта замена данными не подтверждена, а Result 2 говорит скорее против неё.

**Оговорка о применимости — она сильнее, чем я написал в первой редакции.** Замер сделан на
Qwen3 4–32B и Gemma3 4–27B, а применяется к Opus 5, Sol/Luna и к многоходовой работе с тулами.
Данных, подтверждающих **хотя бы направление** такого переноса между этими семействами и режимами,
в отчёте нет — писать «направление переносить можно» было неправомерно. Правильный статус:
**[ДОПУЩЕНИЕ]**. Механизм (успех цепочки как *p^t*) выглядит общим, но это соображение, а не замер.
Всё, что ниже строится на оси длины цепочки, наследует этот статус — включая разметку классов в
разделе 9.

### Почему цепочка рвётся: модель кормится собственными ошибками

Оттуда же, **[ЗАМЕР]**:

> «we observe a **self-conditioning effect** — models become more likely to make mistakes when the
> context contains their errors from prior turns. **Self-conditioning does not reduce by just scaling
> the model size.**»

И проверка на живых агентных трассах (ручной разбор AgentErrorBench): «we estimate that roughly
**20 % of GAIA, 48 % of ALFWorld, 33 % of WebShop failures are similar to self-conditioning**».
Категории отказов — `inefficient_plan`, `progress_misjudge`, `causal_misattribution` («Correctly notes
failure but blames the wrong cause due to its prior outputs») — это буквальный портрет наших залипших
воркеров, и **«поставить модель побольше» от него не страхует.**

### Что из приёмов «не дать модели тупить» реально померено

Тот же стенд, Appendix C/D, **[ЗАМЕР]**:

| приём | результат |
|---|---|
| **Обрезание контекста** (не показывать модели её прошлые ошибки) | **работает**: «performance improves significantly as the context window size is reduced, allowing models to sustain execution for longer horizons» |
| **Thinking / больше последовательного compute** | **работает**: «thinking mitigates self-conditioning, and also enables execution of much longer tasks in a single turn» |
| **Self-verification промптом** («перепроверь себя на каждом шаге») | **НЕ работает**: «Self-verification does not fix self-conditioning… It leads to overthinking in thinking models and increases the amount of tokens required per turn… prompting-based self-correction may not be enough» |
| **Голосование большинством вместо thinking** | **не заменяет**: «Majority voting with the same amount of tokens as CoT traces does not match the performance of CoT» |

**Это ранжирование прямо противоречит нашей привычке.** Мы лечим залипшего воркера инструкцией в
промпте; измеренное говорит, что работает чистка контекста и эффорт, а «проверь себя» — активно
вредит, потому что жрёт контекст и провоцирует overthinking. И это же объясняет, почему у нас свежая
сессия помогает лучше уговоров.

### Anthropic про распределение моделей: выбор модели — ТРЕТИЙ фактор

**[ЗАМЕР + ВЕНДОР]** https://www.anthropic.com/engineering/multi-agent-research-system:

> «In our analysis, three factors explained 95 % of the performance variance in the BrowseComp
> evaluation… **token usage by itself explains 80 % of the variance, with the number of tool calls and
> the model choice as the two other explanatory factors.**»
> «**upgrading to Claude Sonnet 4 is a larger performance gain than doubling the token budget on
> Claude Sonnet 3.7.**»
> «agents typically use about 4× more tokens than chat interactions, and **multi-agent systems use
> about 15× more tokens than chats.**»

Их же рецепт делегирования — и это лучший найденный ответ на «как ставить задачу дешёвому исполнителю»:

> «Each subagent needs an **objective, an output format, guidance on the tools and sources to use, and
> clear task boundaries**. Without detailed task descriptions, agents duplicate work, leave gaps, or
> fail to find necessary information… one subagent explored the 2021 automotive chip crisis while
> 2 others duplicated work investigating current 2025 supply chains.»
> «**Scale effort to query complexity.** Agents struggle to judge appropriate effort for different
> tasks, so we embedded scaling rules in the prompts. **Simple fact-finding requires just 1 agent with
> 3-10 tool calls, direct comparisons might need 2-4 subagents with 10-15 calls each**… prevent
> overinvestment in simple queries, which was a common failure mode in our early versions.»

Знаменитые «90.2 %» разобраны в `docs/tasks/194/web-practice.md` и там показано, что они **не про
силу моделей**; здесь я цитирую другую часть того же текста. Полезное для нас: **выбор модели у них
третий по силе фактор после объёма токенов и числа тул-вызовов** — то есть маршрутизация не главный
рычаг, и наш пункт 3 шапки не стоит переоценивать.

---

## 7. Маршрутизация по ролям: что делают другие

**Прошлая работа #194 (`docs/tasks/194/web-practice.md`, `web-science.md`) уже разобрала**
Aider architect/editor с сырыми числами, Claude Code `opusplan`, откат Explore с Haiku на inherit,
Cline, Cursor Plan Mode, каскады/FrugalGPT и planner-executor из академии. **Не переоткрывал.** Ниже
только то, чего в #194 нет.

### Единственный найденный пер-ролевой замер с ценой И качеством

**[ЗАМЕР]** SWE-Edit (Microsoft), arXiv:2604.26102: главный агент GPT-5, два сабагента (Viewer +
Editor) на GPT-5-mini, SWE-bench Verified, 500 инстансов, 3 прогона на конфигурацию.

> «this decomposition raises resolve rate by **2.1 pp** and cuts inference cost by **17.9 %**, with
> consistent gains across multiple reasoning-model families»

Мотивация названа точнее, чем у всех остальных: «**context coupling problem**: the standard code
editing interface conflates code inspection, modification planning, and edit execution within a single
context window».

**Это единственное число, на которое можно опереться, оценивая выгоду от роутинга по ролям: +2.1 п.п.
и −18 % цены.** Не «14×», которые гуляют по блогам. Применимость частичная: у них роль узкая
(применить правку по готовому плану) и короткая — то есть ровно тот случай, где по гипотезе раздела 6 замена
тира и должна работать.

### Автоматические роутеры: систематически ошибаются в одну сторону

**[ЗАМЕР]** RouterArena, arXiv:2510.00202, дословно:

> «**all existing routers fall short of the oracle's achievable performance, primarily because they are
> inefficient at recognizing when smaller, cheaper models are sufficient for a given query.**»
> «NotDiamond ranks **#12** because it frequently selects expensive models.»

**[ЗАМЕР]** RouteLLM, arXiv:2406.18665 (ICLR 2025) — источник цифры, на которую все ссылаются:
«significantly reduces costs — by **over 2 times** in certain cases — without compromising the quality
of responses». **Применимость: нет.** Это одноходовые запросы чата, качество судит человеческое
предпочтение на Arena. Переносить «74–86 % запросов можно увести на дешёвую модель» на нашу
многоходовую работу с тулами нельзя.

**[ЗАМЕР]** arXiv:2605.07395 (206 000 пар запрос-модель) — методическое предупреждение прямо в нашу
сторону: «a substantial portion of reported unsolvability stems from evaluation artifacts: (i)
**systematic judge biases favoring verbosity over correctness**, (ii) **truncation under fixed
generation budgets**, (iii) output format mismatches… **existing routing headroom estimates are
substantially inflated.**» Если мы будем мерить «можно ли увести класс на дешёвую модель» через
LLM-судью — судья предпочтёт многословный ответ; а наш аналог «truncation» — обрыв хода по
лимиту — прочитается как «модель не смогла».

**[ВЕНДОР, без единого числа]** OpenRouter Auto: «Your prompt will be processed by a meta-model and
routed to one of dozens of models… optimizing for the best possible output». Ни точности, ни экономии
не заявлено; блок «Top models used by Auto Router» на странице пуст.

### Грабля рантайма, которая касается нас напрямую

**[ПРАКТИКА, форум OpenAI]** После выхода 5.6 у Codex CLI пропала возможность спавнить сабагента с
явной моделью; в ответе сотрудника: «The central issue was that the old spawn pattern could appear to
select a GPT-5.6 child while **actually inheriting the parent's model and effort**»
(community.openai.com/t/…/1386290). Класс дефекта — «конфиг заявляет одну модель, исполняется другая»,
и ловится он **только внешней телеметрией**. Если мы когда-нибудь начнём спавнить Codex-сабагентов
изнутри воркера — выбор модели считать неподтверждённым, пока он не виден в расходе.

Ровно тот же класс с другой стороны, **[ЗАМЕР, но неполный]**: автор поставил OpenTelemetry на
Claude Code (7 222 вызова за сутки) и обнаружил «I had `model: sonnet` set in both my global and
project settings.json. Every project. No exceptions. And almost every request was Haiku», из них
«**36 %** of the Haiku subagent calls had token signatures that looked nothing like a file lookup»
(mirin.pro, 25.02.2026). **Две оговорки обязательны:** автор померил только объём работы, **а не
ухудшение результата**, — это подозрение с цифрой, не доказательство; и по находке #194 Anthropic
с некоторой версии откатила Explore с Haiku на наследование модели сессии, то есть вендор сам убрал
то, на что жаловались.

---

## 8. Патологии верхних ступеней

**[ЗАМЕР]** «Inverse Scaling in Test-Time Compute», Anthropic Fellows, arXiv:2507.14417 (TMLR 12/2025):

> «We construct evaluation tasks where **extending the reasoning length of Large Reasoning Models
> deteriorates performance**… 1) **Claude models become increasingly distracted by irrelevant
> information**; 2) OpenAI o-series models resist distractors but **overfit to problem framings**;
> 3) models shift from reasonable priors to spurious correlations; 4) all models show difficulties in
> maintaining focus on complex deductive tasks; 5) extended reasoning may amplify concerning behaviors.»
> «**Claude Opus 4 exhibits pronounced inverse scaling…, with accuracy dropping from nearly 100 % to
> around 85-90 % as reasoning extends.**»
> «**Takeaway 5**: **Natural overthinking yields stronger inverse scaling trends than controlled
> overthinking** — models' natural reasoning allocation is more prone to overthinking errors than
> externally imposed budgets.»

Takeaway 5 — самый неудобный для нас. Он говорит, что модель, которой отдали решать «сколько думать»
самой (а `xhigh`/`max` описаны вендором именно как «no constraints on token spending»), ошибается в
эту сторону **сильнее**, чем модель с внешним бюджетом. При этом на Opus 4.8+ `budget_tokens` убран и
остался только `effort`. Первый пункт списка — «Claude отвлекается на нерелевантное по мере роста
рассуждения» — ровно тот механизм, из-за которого у нас ревьюер на xhigh уходит читать посторонние
файлы (наши грабли про «ревью уползает читать Serena-онбординг»).

**[ЗАМЕР]** «When More Thinking Hurts», arXiv:2604.10739, абстракт дословно: «existing research
**implicitly assumes that longer thinking always yields better results. This assumption remains largely
unexamined**… models exhibit "overthinking", where **extended reasoning is associated with abandoning
previously correct answers**… **stopping at moderate budgets can reduce computation significantly while
maintaining comparable accuracy.**»

**[ЗАМЕР, но не про эффорт]** Cursor, `cursor.com/blog/reward-hacking-coding-benchmarks`:
«On SWE-bench Pro, we found that **63 % of successful Opus 4.8 Max resolutions retrieved the fix rather
than derived it**»; при изоляции git-истории и сети «**Opus 4.8 Max fell from 87.1 % to 73.0 %**».
⚠️ Cursor гоняли **только** `Max` и не сравнивали с `high` — это **не** доказательство, что высокий
эффорт хакает награду больше. Подтверждения тезиса «выше эффорт → больше reward hacking» не нашли ни я,
ни второй сборщик.

---

## 9. Таблица маршрутизации по нашим классам

Ниже — предложение, не решение: маршрутизацию правит #203, здесь я её не трогаю. Колонка «основание»
честно разделяет замеренное и принятое. Сейчас **все** роли стоят на `claude-opus-5[1m]`
(`pipelines/default/pipeline.yaml`), эффорт задан ролью: orchestrator/sub-orchestrator `medium`,
worker `high`, full-cycle `xhigh`.

Колонка «цепочка» разведена со «сложностью» намеренно: на чужом стенде из раздела 6 длина оказалась
сильнее предиктором, чем сложность. Для наших моделей и классов это **не проверено.**
«Короткая» = единицы ходов, «длинная» = десятки ходов и часы.

**Два предупреждения, без которых таблицу читать нельзя.** Первое: сама ось длины перенесена с
чужих моделей и для нас имеет статус **[ДОПУЩЕНИЕ]** (раздел 6). Второе: **разметка наших классов по
этой оси — моя оценка на глаз, а не замер.** Значит вся колонка «цепочка» и все рекомендации, которые
на неё опираются (в частности «замену тира можно на коротких, нельзя на длинных»), — **гипотеза
маршрутизации, а не вывод из данных.** Закрывается запросом D из раздела 10, и он стоит один запрос
к БД.

| Класс нашей работы | Цепочка | Сейчас | Предложение | Основание | Замер или допущение |
|---|---|---|---|---|---|
| **Ресёрч** (открытая, много источников, тулы) | длинная | Opus 5 xhigh | **Opus 5 `high`** | AA: `high→xhigh` = ×1.47 цены при не установленном приросте (0 из 5 бенчмарков значимы, composite не проверен на разности); OpenAI: `xhigh` «only when your evals show a clear benefit»; Anthropic Opus 5: «start with high» | **Замер** — на закрытых прокси ресёрча (HLE, AA-LCR). **Допущение** — перенос на нашу многоходовую работу с тулами: свипа на BrowseComp/GAIA не существует. Класс длинный, поэтому тир НЕ понижать |
| **Планирование** (декомпозиция, спека) | короткая | Opus 5 medium (оркестратор) | оставить `medium` | OpenAI: `medium` — «default for most workloads… planning»; AA: `low→medium` — единственный значимый скачок | **Допущение.** Прямых замеров планирования как класса нет |
| **Реализация по точному ТЗ** | средняя | Opus 5 high | оставить `high` | OckBench coding: насыщение **на `high`** (100.0 %, выше — ноль за ×2 токенов); AA Terminal-Bench 2.1: выше `medium` всё в пределах шума; SWE-Edit: узкая роль исполнителя на младшей модели дала +2.1 п.п. и −17.9 % | **Замер** (три независимых, все на кодовых задачах — ближайший к нам класс) |
| **Ревью** (кода и прозы) | короткая на предмет, длинная по раундам | наследует роль | `high`, и **потолок раундов важнее эффорта** | Inverse-scaling: «Claude становится всё более отвлекаемым нерелевантным по мере роста рассуждения»; FrontierCS: «micro-optimization trap»; наш #177 — шесть раундов ревью прозы, 38 минут | **Допущение** про эффорт; **наш собственный инцидент** про раунды. Свипа эффорта на ревью нет ни у кого |
| **Механические правки** | короткая | Opus 5 high | **младшая модель, `high`** (Luna/Terra), не Opus | Luna(xhigh) = Terra(high) = индекс 50.1 при $95 против $395; SWE-Edit; Anthropic: `low` — «such as subagents», «pair low with explicit checklists» | **Замер** цены/качества — но **на коротких бенчмарк-задачах AA**. Что наши механические правки этому классу соответствуют — моя оценка, не замер |
| **Длинный контекст на извлечение** | короткая (один ход, много входа) | Opus 5 (любой эффорт) | **младшая модель, `medium`+; эффорт не поднимать** | AA-LCR у Opus 5 по эффорту плоский (0.757–0.787 при шуме ±0.068); у Luna обрыв только в non-reasoning (0.387); наш #199 T4 — Luna 5/5 из 164 К | **Замер** (AA + наш собственный, согласуются). **Допущение** — что накопленный тул-выхлопом контекст ведёт себя как документы AA-LCR |
| **Аудит логов** | **длинная** | Opus 5 | **не понижать тир, пока не померено** | По вендору это «extraction, classification» → Luna. Но по гипотезе раздела 6 длина цепочки важнее ярлыка, а аудит у нас идёт десятками ходов | **Конфликт вендорского основания с непроверенной гипотезой, оставлен открытым.** Вендор говорит «дёшево», гипотеза длины — «дорого». Ни то ни другое на нашем классе не мерено; это ячейка B из плана замеров |

**Что изменилось от находки про длину цепочки.** Раньше «аудит логов» и «механические правки» лежали
в одной корзине «простое, отдать дешёвой модели». По оси длины они расходятся, и рекомендация по
аудиту снята до замера. Это единственная строка таблицы, где два источника указывают в разные
стороны, и я не стал прятать конфликт за усреднением.

**Сквозное правило, вытекающее из механики, а не из класса:** эффорт нельзя менять внутри одной
сессии — «changing the effort value between requests invalidates prompt caching», а у нас 68 %
расхода это `cache_read` (#178). Поэтому разный эффорт по фазам = разные воркеры, и точка.

**Второе сквозное — про промпт, не про модель.** Единственный измеренный способ удержать слабую
модель на длинной цепочке — **чистить контекст от её собственных прошлых ошибок** и не экономить на
thinking. «Перепроверь себя» в промпте измеренно **не работает** и вредит (раздел 6). Это территория
#203, но при выборе модели на длинный класс учитывать надо: обвязка тут сильнее тира.

---

## 10. Чего в чужих данных НЕТ (и что стоило бы померить самим — позже, не сейчас)

1. **Эффорт-свип на настоящих ресёрч-бенчах** (BrowseComp, GAIA, FRAMES, DeepResearch Bench). Не
   существует ни одного — искали двое независимо. Ресёрч-бенчи публикуются одной точкой на модель,
   уровень эффорта в подписи обычно даже не указан. **Это и есть главная дыра под наш вопрос.**
2. **Эффорт-свип на многочасовой агентной сессии.** Всё, что есть, — одноходовые или короткие задачи.
   `xhigh` вендор описывает как «over 30 minutes… token budgets in the millions», но замера на таком
   горизонте не опубликовано никем. Наш собственный #199 тоже мерил одноходовое.
3. **Эффорт на ревью.** Ни одного свипа. При том что у нас ревью — отдельная роль и отдельная статья
   расхода.
4. **Пер-эффорт SWE-bench Verified от Anthropic.** Не публикуется; заголовочные проценты идут без
   указания уровня. Графики «performance vs effort» на странице Opus 5 отрисованы картинкой, чисел в
   HTML нет (проверено грепом по 322 КБ).
5. **HLE по всем ступеням для Opus 5.** У AA есть только `max 54.9` / `xhigh 54.4`; разница 0.5 п.п.
   при их же рекомендации считать разницу меньше 2 п.п. шумом.
6. **Происхождение MRCR 41.3 % для Luna.** Атрибуция к странице OpenAI не подтвердилась; методики нет.
7. **Связь «эффорт ↔ reward hacking».** Cursor мерил только `Max`, контроля не было.
8. **Постмортем с измеренной ценой ошибки роутинга** («перевели роль на дешёвую модель → N лишних
   итераций»). Ни одного. Всё, что выдаёт поиск на эту тему, — SEO-статьи с непроверяемыми числами
   («14× экономии», «$47 000 за 11 дней»); не цитировались и цитировать не надо.
9. **Бенчмарк роутеров на МНОГОХОДОВЫХ агентных задачах.** RouterArena, RouterBench, RouteLLM — все
   одноходовые. Ни один коммерческий роутер в агентном цикле независимо не мерился.
10. **Пер-ролевой ablation в OSS-харнессах.** Механизмов много (OpenHands `[llm.*]`, Roo Code
    sticky-model-per-mode, SWE-agent), замер один — SWE-Edit. Причём mini-swe-agent, наследник
    SWE-agent, вернулся к ОДНОЙ модели: эволюция пошла в сторону упрощения, а не роутинга.
11. **Кросс-тирные данные METR.** В их пуле нет Haiku/mini/nano — только фронтир разных поколений.
    METR отвечает «фронтир 2026 держит цепочку дольше фронтира 2025», а не «старший тир дольше
    младшего». Для нашего вопроса релевантен раздел 6, а не METR.

**Что померить самим, когда дойдут руки** (в порядке отношения «польза / стоимость»):

- **A. `full-cycle` на `high` против `xhigh` на нашей реальной очереди задач.** Слепое судейство,
  критерий приёмки записан до прогонов, метрика — доля задач, принятых без переделки, и число
  тул-вызовов на задачу. Это единственный замер, который может подтвердить или опровергнуть
  изменение №1 из шапки. Обязателен split-half по до-периоду: ожидаемый эффект (≈1 балл индекса)
  заведомо меньше типичного шума, и без оценки шума результат будет нечитаемым.
- **B. Класс «аудит логов» на младшей модели против Opus** — единственная строка таблицы, где
  вендорское основание и механика длины цепочки указывают в разные стороны. Метрику брать
  **не через LLM-судью**: arXiv:2605.07395 показал, что судья систематически предпочитает
  многословие, а обрыв по лимиту читается как «не смогла», и обе ошибки завышают кажущийся запас
  для дешёвой модели.
- **C. Число тул-вызовов как функция эффорта на нашей нагрузке.** Вендор утверждает прямую связь
  («lower effort → fewer tool calls»), а у нас тул-вызов — доминирующая единица расхода ($0.13, R=0.935,
  #178). Если связь у нас есть, эффорт надо считать множителем цены, а не ползунком качества, и это
  меняет всю арифметику маршрутизации.
- **D. Разметить наши классы по фактической длине цепочки** (медиана числа ходов и тул-вызовов на
  задачу по `logs`). Это не эксперимент, а запрос к своей же БД, и он ставит под весь раздел 9
  измеренное основание вместо моей оценки. **Самое дешёвое из списка — начинать надо с него.**

Чего мерить **не** надо: воспроизводить MRCR. Мы уже мерили извлечение (#199 T4), AA меряет
многодокументное рассуждение, обе выборки говорят одно и то же, а исходный контрсигнал не имеет
проверяемого происхождения.

---

## 11. Уверенность по находкам

- **Выше `medium` ни один отдельный бенчмарк AA не показывает значимого прироста на Opus 5** —
  **CONFIRMED**. Моя оценка ошибки антиконсервативна (повторы коррелированы, интервалы у́же
  настоящих), и именно поэтому вердикт «не значимо» устойчив: с настоящими, более широкими
  интервалами он тем более верен.
- **Обратная сторона того же: строка `low → medium`, где я написал «значимо»** — **UNCERTAIN**.
  Эти вердикты как раз и подорваны корреляцией повторов; без task-level данных считать их
  указанием на направление, а не доказательством.
- **`high → xhigh` на Opus 5 стоит +47 % цены** — **CONFIRMED** (числа AA).
  **Что он даёт — НЕ УСТАНОВЛЕНО:** +1.0 балла composite нельзя объявить приростом, потому что AA
  публикует неопределённость для точки, а не для разности, и парных результатов по задачам нет.
  Это не «маленький эффект», это отсутствие доказательства эффекта.
- **Верх лестницы плоский или отрицательный** — **CONFIRMED**, три независимых замера (AA, OckBench,
  OccuBench) плюс два вендора, признающих это в тексте.
- **Точка перегиба кривой зависит от смеси задач** — **CONFIRMED** (AA и OckBench расходятся:
  `low→medium` против `medium→high`).
- **В семействе GPT-5.6 на этой сюите Luna отреагировала на `medium→xhigh` сильнее, чем Opus 5** —
  **CONFIRMED** (4 из 5 бенчмарков значимо против 0 из 5). Обобщение «эффорт даёт слабой модели
  кратно больше» — **[ДОПУЩЕНИЕ]**: два семейства, одна сюита, короткие задачи.
- **Luna(xhigh) дешевле Terra(high) вчетверо при равном индексе** — **CONFIRMED** (цена прогона суиты
  из данных AA), **UNCERTAIN** как рекомендация: индекс — агрегат, равенство агрегатов не означает
  равенства на нашем классе.
- **Обрыв Luna на длинном контексте не воспроизводится** — **CONFIRMED**, что AA-LCR его не
  показывает и что атрибуция исходного числа не подтвердилась; **REFUTED не является** — исходный
  MRCR никем не перепроверен, он мог мерить что-то другое.
- **Эффорт не помогает длинному контексту на Opus 5** — **LIKELY** (плоско по AA-LCR, но интервалы
  широкие: 100 вопросов).
- **Гипотеза «41.3 % — это Luna без рассуждения»** — **UNCERTAIN**, чистое численное совпадение
  разных бенчмарков, доказательств нет.
- **На открытых задачах эффорт не окупается** — **LIKELY**: один прямой свип (FrontierCS, поколение
  назад, без CI) плюс два замера на оси thinking on/off (R2-Write, AGC-Bench). Прямого свипа по
  лестнице на ресёрч-бенче не существует.
- **Смена эффорта внутри сессии рвёт prompt cache** — **CONFIRMED** (вендорская дока дословно),
  масштаб последствий для нас — **CONFIRMED** по нашему же #178 (68 % расхода = `cache_read`).
- **Размер модели покупает ДЛИНУ цепочки, а не качество шага** — **CONFIRMED как их результат**
  (контролируемый замер, знание и план выданы явно, первый шаг почти безошибочен у всех).
  **Перенос на Opus/Sol и на работу с тулами — [ДОПУЩЕНИЕ], не подтверждено даже в направлении:**
  мерили Qwen3 4–32B и Gemma3 4–27B. Механизм *p^t* выглядит общим, но это соображение.
- **Self-conditioning не лечится размером модели, лечится чисткой контекста** — **CONFIRMED** на их
  стенде плюс ручной разбор живых трасс (20 % GAIA / 48 % ALFWorld / 33 % WebShop).
- **«Перепроверь себя» в промпте не работает** — **CONFIRMED** на том же стенде, **UNCERTAIN** для
  наших промптов: у нас другие модели и другая обвязка.
- **Выбор модели — третий по силе фактор после объёма токенов и числа тул-вызовов** — **LIKELY**
  (вендорский анализ на своём эвале BrowseComp, сырых данных нет).
- **Роутеры систематически недоузнают, что хватит дешёвой модели** — **CONFIRMED** для одноходового
  роутинга (RouterArena), **не применимо** к многоходовым задачам: там никто не мерил.
- **Разделение ролей между тирами даёт порядок «+2 п.п. и −18 % цены»** — **CONFIRMED** для одной
  узкой роли (SWE-Edit), **UNCERTAIN как общее правило**: это единственный такой замер в природе.
- **Наша разметка классов по длине цепочки** — **это оценка, а не замер.** Самое слабое место
  раздела 9; закрывается запросом D.

## 12. Затронутые файлы и риски

Кода не трогал. Написан только `docs/tasks/204/research.md` и сырьё `docs/tasks/204/aa-index-by-effort.json`.
Маршрутизация (`pipelines/default/pipeline.yaml`, `<model-routing>`) не менялась — это #203.
Риск при внедрении рекомендации №1: понижение `full-cycle` с `xhigh` до `high` — изменение поведения
на всех новых full-cycle воркерах сразу; внедрять только вместе с замером A, иначе мы заменим одну
непроверенную настройку на другую непроверенную.

## 13. Источники (открыты 12.08.2026)

**Замеры**
1. `https://artificialanalysis.ai/models/gpt-5-6-luna-xhigh` — сырые пер-эффорт данные (индекс, AA-LCR,
   Terminal-Bench 2.1, τ³-Banking, HLE, GPQA, стоимость прогона) для всего семейства GPT-5.6 и Claude.
   Снято из `__next_f` страницы, сохранено в `aa-index-by-effort.json`.
2. `https://artificialanalysis.ai/methodology/intelligence-benchmarking` — размеры выборок, число
   повторов, веса категорий, заявленный CI индекса.
3. `https://artificialanalysis.ai/articles/announcing-aa-lcr` — что именно меряет AA-LCR (100 вопросов,
   ~100 К токенов, многодокументное рассуждение, без тулов).
4. `https://arxiv.org/abs/2512.15699` (FrontierCS) — свип эффорта на открытых задачах, раздел 5.1.
5. `https://arxiv.org/abs/2511.05722` + `https://ockbench.github.io/static/data/top200_model_performance.csv`
   и `per_domain_performance.csv` (OckBench) — полный свип Opus 5 с токенами и по доменам.
6. `https://arxiv.org/abs/2604.10866` (OccuBench, §6.5) — эффорт на профессиональных агентных задачах.
7. `https://arxiv.org/abs/2507.14417` (Inverse Scaling in Test-Time Compute, Anthropic Fellows).
8. `https://arxiv.org/abs/2604.10739` (When More Thinking Hurts) — абстракт.
9. `https://arxiv.org/abs/2604.03004` (R2-Write, Table 1) — thinking on/off, письмо против математики.
10. `https://arxiv.org/abs/2607.01152` (AGC-Bench) — dz промпта против dz reasoning.
11. `https://cursor.com/blog/reward-hacking-coding-benchmarks` — 63 % найденных фиксов у Opus 4.8 Max.
12. `https://arxiv.org/html/2509.09677v3` (ICLR 2026) — **ключевой источник раздела 6**: длина цепочки
    против знания, self-conditioning, ранжирование приёмов (чистка контекста работает,
    self-verification нет).
13. `https://arxiv.org/abs/2604.26102` (SWE-Edit, Microsoft) — единственный пер-ролевой замер с ценой
    и качеством: +2.1 п.п., −17.9 %.
14. `https://www.anthropic.com/engineering/multi-agent-research-system` — 80 % дисперсии объясняет
    объём токенов; выбор модели третий фактор; правила постановки задачи сабагенту.
15. `https://arxiv.org/html/2510.00202v1` (RouterArena) — роутеры недоузнают достаточность дешёвой
    модели; NotDiamond #12.
16. `https://arxiv.org/abs/2406.18665` (RouteLLM, ICLR 2025) — источник цифры «более чем вдвое
    дешевле»; одноходовой чат, к нам не применим.
17. `https://arxiv.org/pdf/2605.07395` — запас для роутинга завышен артефактами эвала (судья любит
    многословие, обрыв по лимиту читается как провал).

**Вендор**
18. `https://docs.claude.com/en/docs/build-with-claude/effort` (через `r.jina.ai`, страница JS-рендерится).
19. `https://developers.openai.com/api/docs/guides/reasoning.md` — сырой markdown.
20. `https://learn.chatgpt.com/docs/models.md` — сырой markdown, выбор тира и уровня.
21. `https://openai.com/index/previewing-gpt-5-6-sol/` (через `r.jina.ai`) — проверка происхождения MRCR.
22. `https://learn.chatgpt.com/docs/config-file/config-reference.md` — допустимые значения
    `model_reasoning_effort` в Codex CLI.

**Вторичка, использована только как указатель**
23. `https://www.vellum.ai/blog/gpt-5-6-sol-terra-luna-explained` — источник числа MRCR 41.3 %,
    атрибуция которого не подтвердилась.
24. `https://www.digitalapplied.com/blog/reasoning-effort-cost-vs-quality-benchmarks-2026` — заявляет
    собственный прогон на 900 задачах, но **не публикует ни сырых данных, ни репозитория, ни методики**.
    Проверял отдельно. **В выводы не берётся.**

**Наше**
25. `docs/tasks/199/research.md` — свой замер: Sol `medium→xhigh` ×2.04 цены без смены вердикта;
    T4 — Luna 5/5 из 164 К токенов.
26. `#178` — ≈$0.13 на тул-вызов, 68 % суммы `cache_read`, R = 0.935.
27. `pipelines/default/pipeline.yaml` — текущая раскладка ролей и эффортов.

---

## 14. Что изменилось после Codex-ревью (раунд 1)

Ревьюер независимо пересчитал арифметику из `aa-index-by-effort.json` и подтвердил её, но нашёл
четыре содержательные ошибки. Все приняты, все исправлены — записываю, потому что три из них меняли
силу главного вывода:

1. **Composite-прирост +1.0 объявлялся «реальным, но крошечным».** Неверно: AA публикует
   неопределённость для оценки одной конфигурации, а не для разности двух. Даже при ±1 балла на точку
   и независимости интервал разности был бы ≈±1.41 — шире самой разности. Статус изменён на
   **«не установлен»** везде: шапка, разделы 1, 9, 11. Для нашего решения это не ослабление, а
   усиление: мы платим +47 % за то, чего никто не измерил.
2. **Направление ошибки от зависимых повторов было названо в двух местах противоположно** —
   «оптимистично» в разделе 1 и «консервативно» в разделе 11. Верно первое: `N = задачи × повторы`
   завышает эффективный размер выборки и занижает SE. Разведено следствие: вердикты «шум» от этого
   только крепнут, вердикты «значимо» — ослаблены (помечены `°`).
3. **Шапка утверждала «эффорт нужен слабой модели» как общее правило.** Измерено уже́: в семействе
   GPT-5.6 на этой короткой сюите Luna отреагировала сильнее, чем Opus 5. Обобщение помечено
   `[ДОПУЩЕНИЕ]`.
4. **Перенос оси «длина цепочки» с Qwen3/Gemma3 на Opus/Sol был назван допустимым «по направлению».**
   Оснований для этого нет даже в направлении; статус понижен до `[ДОПУЩЕНИЕ]`, и вся опирающаяся на
   него разметка классов в разделе 9 переименована из вывода в гипотезу маршрутизации.

Плюс приняты четыре замечания уровня suggestion: помечены авторские обобщения, «за длинный контекст
платить бессмысленно» смягчено до «польза не обнаружена», правило про выключенное рассуждение
ограничено AA-LCR и отвязано от гипотезы про MRCR, а тезис «весь прирост в нижней половине лестницы»
заменён на то, что действительно устойчиво в обоих свипах: **выше `high` кривые плоские или
отрицательные.**

Артефакт ревью: `docs/tasks/204/codex-review-research.md`.

### Раунд 2

Ревьюер подтвердил, что четыре блокирующие правки внесены, и нашёл **три остаточных места, где снятая
ось длины цепочки всё ещё работала как установленное основание**, противореча только что добавленным
оговоркам: «Значит наш собственный разрез классов проверять надо по числу шагов» (раздел 6),
«по разделу 6 длина — более сильный предиктор» (шапка раздела 9) и «на этом классе перенос законный»
(строка про механические правки). Все три переписаны в условные формулировки; заодно вычищены
оставшиеся ссылки «по разделу 6» в двух ячейках таблицы.

Это ровно тот класс ошибки, который трудно поймать самому: оговорку я добавил, а утверждения, которые
она отменяет, остались стоять рядом нетронутыми. Раундов для прозы больше не осталось — потолок два.
