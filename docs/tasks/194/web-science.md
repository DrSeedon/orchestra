# Разделение фаз агентной работы между моделями разной силы

## Вопрос

Есть ли измеренные данные, что сильную модель выгодно ставить на планирование/декомпозицию, а слабую или дешёвую — на исполнение? Где эта схема ломается? Отдельный практический вопрос для Orchestra: как переносить результаты на Claude Opus 5 с окном 1M и GPT-5.6 Sol с эффективным окном 258K при ChatGPT-auth в фазах `research / plan / implement / review`.

## Короткий ответ

**Да, у гетерогенных пайплайнов есть измеренный cost/latency-quality Pareto-выигрыш, но данные не подтверждают универсальное правило «самая сильная модель планирует, дешёвая исполняет».** Наиболее близкие к вопросу эксперименты дают три разных результата:

1. на PEAR качество planner действительно важнее executor, а сильный planner со слабым executor иногда не хуже пары strong/strong;
2. на deep-research AgentCollab всё наоборот: выделение большой модели только executor дало `27.3` accuracy против `24.6` при большой модели только planner;
3. адаптивная эскалация по ходу траектории заметно ближе к большой модели по качеству, чем статическое закрепление ролей, при сохранении ускорения.

Следовательно, выгоден не сам разрез по названиям фаз, а **размещение сильной модели в точках необратимых решений и эскалация при наблюдаемом отсутствии прогресса**. Опубликованные бенчмарки — гипотеза о нашей системе, не приговор: ни одна открытая работа ниже не сравнивает именно Opus 5 и GPT-5.6 Sol в нашем harness и на наших задачах.

## Находки

### 1. Сильный planner + более слабый executor может сохранить качество, но эффект не монотонен

**[ЗАМЕР] [ПЕРВОИСТОЧНИК]** PEAR, Findings of EACL 2026, 84 интерактивные задачи AgentDojo в banking/Slack/travel/workspace, пять повторов на конфигурацию. В таблице 7:

- `GPT-5 / GPT-5`: `68.06 ± 2.28` utility;
- `GPT-5 / GPT-5-mini`: `69.44 ± 3.81`;
- `GPT-5 / GPT-5-nano`: `72.28 ± 1.80`;
- `GPT-5-nano / GPT-5-nano`: `57.70 ± 2.98`;
- `GPT-5-nano / GPT-5-mini`: `48.68 ± 2.83`.

Это прямой замер того, что сильный planner допускает дешёвый executor без видимой потери на этом наборе, а слабый planner не спасается чуть более сильным executor. Но внутри Claude результат не монотонен по «силе planner»: `Claude-opus-4.1 / Claude-sonnet-4 = 80.55 ± 1.21`, тогда как `Claude-sonnet-4 / Claude-sonnet-4 = 84.90 ± 0.65`. То есть брендовая/общая сила модели не заменяет измерение совместимости конкретной пары и prompt/harness.

Источник: [PEAR, Table 7](https://arxiv.org/html/2510.07505).

### 2. Контекст между фазами — не мелочь: память planner дала 10–30 п.п., память executor почти ничего

**[ЗАМЕР] [ПЕРВОИСТОЧНИК]** В PEAR сравнили shared, separate, no-memory и planner-only memory. Таблица 2 содержит, например:

- `GPT-5 / GPT-5-mini`: no memory `69.54 ± 5.37`, planner-only `86.62 ± 2.50`;
- `GPT-5 / GPT-5-nano`: no memory `75.14 ± 1.54`, planner-only `85.81 ± 2.61`;
- `Deepseek-R1 / Deepseek-V3`: no memory `71.81 ± 2.72`, planner-only `85.18 ± 1.17`;
- `Deepseek-V3 / Deepseek-V3`: no memory `73.07 ± 3.14`, planner-only `84.27 ± 3.23`.

Авторы резюмируют прирост planner memory примерно как 10–30%, а separate/shared memory сопоставимы с planner-only. Для фазового пайплайна это сильнее поддерживает **полноценную передачу состояния планировщику/репланировщику**, чем дорогой полный контекст каждому leaf-executor. Ограничение: PEAR использует синтетические tools и короткий набор офисных сценариев, а не кодовую базу.

Источник: [PEAR, Table 2](https://arxiv.org/html/2510.07505).

### 3. На deep research адаптивная small→large эскалация почти догнала large-only и ускорилась

**[ЗАМЕР] [ПЕРВОИСТОЧНИК]** AgentCollab (arXiv, 2026) начинает с large-model warm-up/плана, затем отдаёт routine reasoning/tool calls малой модели и временно возвращает большую при stagnation. Таблица 1, DDV2:

- BrowseComp_zh: large-only `34.6`, `1.00×`; small-only `18.3`, `1.54×`; AgentCollab `33.9`, `1.36×`;
- HLE-math: large-only `23.3`, `1.00×`; small-only `8.0`, `3.38×`; AgentCollab `21.1`, `2.31×`;
- WritingBench: large-only `5.1`, `1.00×`; small-only `4.4`, `3.20×`; AgentCollab `5.0`, `2.43×`.

На втором agent harness, WebSailor, BrowseComp_zh: large-only `25.5`, small-only `14.2`, AgentCollab `22.5` при `1.50×`; HLE-math: `14.0`, `11.3`, `13.3` при `1.29×`. Это наиболее близкий найденный замер к нашим длинным research-задачам: 289 BrowseComp_zh, 866 HLE-math, 1000 WritingBench, максимум 40 итераций. Метрика speedup — end-to-end latency, не долларовая цена.

Источник: [AgentCollab, Table 1](https://arxiv.org/html/2603.26034).

### 4. Static role split хуже динамического и может выбрать не ту фазу для сильной модели

**[ЗАМЕР] [ПЕРВОИСТОЧНИК]** В ablation AgentCollab на DDV2/BrowseComp_zh (таблица 2):

- large-model only: `34.6`, `1.00×`;
- small-model only: `18.3`, `1.54×`;
- large planner: `24.6`, `1.39×`;
- large executor (information seeker): `27.3`, `1.24×`;
- static adaptive escalation: `32.5`, `1.32×`;
- dynamic escalation: `33.9`, `1.36×`.

Именно здесь привычная схема ломается: **сильная execution/information-seeking роль полезнее сильной planning роли** (`27.3` против `24.6`). Авторы связывают это с тем, что executor непосредственно выбирает и добывает доказательства, а его ошибка отравляет следующие состояния. Dynamic routing также снизил switching ratio с `49.64` до `45.07`; частые переключения мешают reuse prefill cache. Для нас это аргумент не делать жёсткое `research=cheap executor`: поиск, чтение источника и проверка числа могут быть наиболее error-sensitive частью.

Источник: [AgentCollab, Table 2](https://arxiv.org/html/2603.26034).

### 5. Гетерогенная декомпозиция даёт большой cost Pareto-выигрыш даже с малой моделью в декомпозиции

**[ЗАМЕР] [ПЕРВОИСТОЧНИК]** Division-of-Thoughts (WWW 2025) использует локальную Llama-3-8B для декомпозиции и оценки сложности, а GPT-4o — лишь для трудных подзадач. По 200 тестовых вопросов на каждом из семи бенчмарков среднее сокращение времени относительно лучшего по accuracy baseline — `66.12%`, API cost — `83.57%`. Дословные строки таблицы 1:

- P3: GPT-4o CoT `42% / 35.8 s / 4.45¢`; DoT `41% / 23.5 s / 1.58¢`;
- SCAN: `68% / 9.21 s / 2.75¢`; DoT `63% / 5.5 s / 1.20¢`;
- MATH: лучший ToT `63% / 60.5 s / 9.97¢`; DoT `59% / 22.6 s / 1.02¢`;
- DROP: лучший ToT `80.5% / 40.2 s / 5.41¢`; DoT `85% / 4.9 s / 0.32¢`;
- CSQA: лучший ToT `82% / 98.8 s / 20.50¢`; DoT `82% / 9.9 s / 0.49¢`.

Контр-интуитивная часть: тут **не сильная модель планирует**. Малой модели достаточно для decomposition/allocation на формализуемых задачах, а дорогая включается локально. Значит, «план всегда требует Opus» тоже нужно проверять, а не принимать как аксиому.

Источник: [Division-of-Thoughts, Table 1](https://arxiv.org/html/2502.04392).

### 6. План, дистиллированный большой моделью, улучшает малого агента, но длинные задачи требуют возврата большой модели

**[ЗАМЕР] [ПЕРВОИСТОЧНИК]** Sub-goal Distillation, CoLLAs 2024: ChatGPT один раз размечает sub-goals на expert trajectories; на inference работают обученные FLAN-T5 policies. ScienceWorld, таблица 1:

- small-agent Swift-only overall `46.25`, proposed distilled agent `65.43`;
- полностью решённые типы задач: `4/30` против `11/30`;
- short trajectories: `79.68` против `91.61`;
- medium: `35.80` против `62.83`;
- long: distilled agent `45.35`, но SwiftSage с правилом эскалации на ChatGPT `57.99`.

То есть одноразовое дорогое планирование/дистилляция хорошо амортизируется на повторяемом workload, но фиксированный distilled executor проигрывает схеме с large-model fallback на длинных траекториях. Есть и яркие провалы передачи плана: task 3-3 — `5.6` у proposed против `66.9` SwiftSage; авторы показывают неверный sub-goal `FocusOn(fountain)`.

Источник: [Sub-goal Distillation, Table 1](https://arxiv.org/html/2405.02749).

### 7. Каскады доказанно экономят на single-turn, но перенос на агентные траектории ограничен

**[ЗАМЕР] [ПЕРВОИСТОЧНИК]** RouteLLM (2024) маршрутизирует между GPT-4 и Mixtral-8x7B. Таблица 6 даёт cost-saving ratio относительно GPT-4:

- MT-Bench: `3.66` при `95% GPT-4 quality`;
- MMLU: `1.41` при `92% GPT-4 quality`;
- GSM8K: `1.49` при `87% GPT-4 quality`.

Но это короткие запросы: сами авторы при расчёте стоимости фиксируют средний prompt `95` tokens и output `264` tokens. В AgentCollab перенос RouteLLM «решение на каждом reasoning step» уступил trajectory-aware routing: на DDV2/BrowseComp_zh RouteLLM `28.2` accuracy, `1.09×`, AgentCollab `33.9`, `1.36×`; на HLE-math `15.2`, `1.62×` против `21.1`, `2.31×`. Следовательно, FrugalGPT/RouteLLM доказывают существование Pareto-фронта, но не доказывают правильность фазового разреза в длинном агенте.

Источники: [RouteLLM, Tables 1 and 6](https://arxiv.org/html/2406.18665), [AgentCollab, Table 1](https://arxiv.org/html/2603.26034).

### 8. Практический coding benchmark показывает крупную экономию, но это vendor-owned measurement

**[ЗАМЕР] [ПРАКТИКА]** Morph (июнь 2026), 40 end-to-end app builds, success только если приложение запускается и проходит acceptance checks:

- Claude Fable 5 solo: `92.4%`, `$185.00/build`, `48 tok/s`;
- Claude Fable 5 planner + GLM-5.2 executor: `92.6%`, `$66.20/build`, `72 tok/s`;
- Fable 5 + Kimi K2.7 Code: `91.6%`, `$64.60/build`, `44 tok/s`;
- Kimi K2.7 solo: `84.2%`, `$16.90/build`, `43 tok/s`.

У mixed loop planner работает на первом ходе и после compaction; заявленный профиль — planner `4M in / 250K out`, executor `10M in / 650K out` на build. Это сильный прикладной сигнал в пользу схемы при дорогом длинном middle, но не рецензируемая работа: benchmark публикует поставщик executor-инфраструктуры, нет показанных доверительных интервалов, raw outputs и независимого воспроизведения.

Источник: [Morph Multi-Agent Benchmarks](https://www.morphllm.com/benchmarks/multiagent).

## Контр-свидетельства

### A. На связной coding-задаче solo frontier оказался дешевле и качественнее mixed pairs

**[ЗАМЕР] [ПРАКТИКА]** Независимый практический benchmark AkitaOnRails (одна greenfield Rails-задача, поэтому внешняя валидность узкая) принудительно запрещал planner писать код. Финальная таблица:

- Opus 4.7 solo: `97`, `18m`, `$4.04`;
- Opus + Kimi manual: `97`, `30–40m`, `~$5–7`;
- Opus + Sonnet 4.6: `92`, `25m`, `$5.77`;
- Opus + Haiku 4.5: `90`, `19m`, `$3.49`;
- Opus + Kimi forced: `95`, `25m`, `~$3–4`;
- GPT 5.4 xHigh + medium: `94`, `30m`, `~$1–3`;
- GPT 5.4 xHigh + low: `94`, `53m`, `~$3–6`.

В ручных вариантах около 14 dispatches потребовали `3–5` ходов Opus каждый; скрытая стоимость planner для двух запусков была около `$11`, и orchestration стала примерно втрое дороже solo. Причина не обязательно в слабом executor: задача связная, каждый шаг менял предпосылки следующего, поэтому handoff добавлял повторное чтение/проверку. Это наиболее прямое измеренное «где ломается»: тесно связанные implementation-задачи без хорошо проверяемых атомарных leaf units.

Источник: [AkitaOnRails, final comparison](https://akitaonrails.com/en/2026/04/25/llm-benchmarks-vale-a-pena-misturar-2-modelos/).

### B. Сильный planner не всегда является самым ценным местом для сильной модели

**[ЗАМЕР] [ПЕРВОИСТОЧНИК]** AgentCollab role ablation: large planner `24.6`, large executor `27.3` на BrowseComp_zh. PEAR одновременно показывает противоположную асимметрию на офисных tool tasks. Это не конфликт данных, а указатель на модератор: **роль, в которой возникает необратимая ошибка, зависит от workload**. Для research плохой план можно исправить после поиска, но неверно добытое/непрочитанное доказательство может сделать идеальный план бесполезным.

Источник: [AgentCollab, Table 2](https://arxiv.org/html/2603.26034).

### C. Передача между фазами теряет качество, если planner не видит траекторию

**[ЗАМЕР] [ПЕРВОИСТОЧНИК]** PEAR: planner-only memory на `GPT-5 / GPT-5-mini` дала `86.62 ± 2.50`, no-memory — `69.54 ± 5.37`; на `Deepseek-R1 / Deepseek-V3` — `85.18 ± 1.17` против `71.81 ± 2.72`. Значит, экономия токенов через слишком короткий handoff может стоить больше, чем сэкономленная слабая execution-фаза. Нужен не «summary вообще», а проверяемое состояние: решения, доказательства, открытые вопросы, результаты инструментов и причины отклонённых путей.

Источник: [PEAR, Table 2](https://arxiv.org/html/2510.07505).

### D. Миллионный context window надёжен на needle retrieval, но это не измерение research reasoning

**[ЗАМЕР] [ПЕРВОИСТОЧНИК]** Gemini 1.5 technical report, Figure 1: Gemini 1.5 Pro показал `>99.7%` needle recall до `1M` tokens во всех модальностях; в тексте авторы сообщают `>99%` до `10M`. Это доказывает способность принять и найти буквально совпадающий факт, но не синтезировать исследование. В самом отчёте Figure 1 назван synthetic retrieval task.

Источник: [Gemini 1.5 technical report, Figure 1, p. 2](https://arxiv.org/pdf/2403.05530).

### E. Без literal match «эффективное окно» во много раз короче заявленного

**[ЗАМЕР] [ПЕРВОИСТОЧНИК]** NoLiMa (2025) требует вывести скрытую ассоциацию, а не найти совпадающую строку. Таблица 10:

- GPT-4.1, claimed `1M`, effective `16K`: base `97.0`, 32K `79.8`, 64K `69.7`, 128K `64.7`;
- Gemini 2.0 Flash, claimed `1M`, effective `4K`: base `89.4`, 32K `41.0`, 64K `33.0`, 128K `16.4`;
- Llama 4 Scout, claimed `10M`, effective `1K`: base `81.7`, 32K `21.6`.

Здесь effective length — максимальная длина с не менее `85%` от short-context baseline. Это прямой замер context rot: номинальное окно говорит, сколько токенов API принимает, а не сколько модель надёжно использует.

Источник: [NoLiMa, Table 10](https://arxiv.org/html/2502.05167).

### F. На научных статьях 1M-контекст не решил даже поверхностное агрегирование

**[ЗАМЕР] [ПЕРВОИСТОЧНИК]** SciTrek (v5, 2026) — 2,121 вопрос по коллекциям full-text scientific articles, операции count/sort/aggregate/comparison; три запуска, exact match. Таблица 7:

- GPT-4.1 (1M): full-text `21.1` at 64K, `11.7` at 128K, `3.9` at 512K, `2.5` at 1M;
- Llama-4-Scout (claimed 10M): `5.4`, `2.8`, `1.3`, `1.1`;
- Qwen2.5-14B-Instruct-1M: `8.3`, `6.5`, `1.6`, `0.1`;
- Qwen-2.5-Coder + SQL execution after extraction: `38.4`, `35.3`, `34.1`, `25.6`;
- Gemini 2.5 Pro: `41.7` at 64K, `26.0` at 128K; 512K и 1M не запускались из-за prohibitive computational cost.

На тех же данных в компактном database-table представлении GPT-4.1 получил `69.3 / 53.8 / 24.8 / 16.1`, а SQL execution `90.6 / 89.4 / 86.8 / 87.5`. Следовательно, структура/сжатие доказательств важнее формального максимума окна. Это самый близкий найденный контр-замер к research по пачке научных источников.

Источник: [SciTrek, Table 7](https://arxiv.org/html/2509.21028).

### G. Реалистичный long-context benchmark показывает, что reasoning compute важнее одного размера окна

**[ЗАМЕР] [ПЕРВОИСТОЧНИК]** LongBench v2: 503 вопроса, контексты от 8K до 2M words, шесть категорий, включая multi-document QA, code repositories и agent history. В abstract: лучший direct-answer model `50.1%`, human experts за 15 минут `53.7%`, o1-preview с более длинным reasoning `57.7%`. Это не A/B окна при одной модели, но показывает, что доступ к длинному входу сам по себе не закрывает задачу; inference-time reasoning может быть сильнее номинальной длины окна.

Источник: [LongBench v2, abstract, p. 1](https://arxiv.org/pdf/2412.15204).

## Когда схема работает и когда ломается

| Условие | Что показывают замеры | Решение |
|---|---|---|
| План можно один раз переиспользовать на множестве сходных leaf-задач | DoT, Sub-goal Distillation и Morph дают большой выигрыш | Сильную модель амортизировать; cheap executor допустим с машинной проверкой |
| Leaf-задачи атомарны, выход формализован, ошибка быстро видна | Weak executor при strong planner в PEAR не теряет utility | Разделять и эскалировать только failures |
| Траектория длинная, сложность меняется по ходу | AgentCollab dynamic ближе всего к large-only | Не фиксировать модель на всю фазу; route по stagnation/failed checks |
| Execution добывает доказательства или меняет среду | Large executor `27.3` > large planner `24.6` | Не считать execution механическим; усиливать evidence/tool-critical steps |
| Реализация связная, шаги меняют план | Akita: solo `97/$4.04/18m`, mixed не лучше | Одна сильная модель или крупные contiguous chunks без частых handoff |
| Между фазами теряется trajectory state | PEAR no-memory теряет 10–30 п.п. | Передавать структурированное состояние и возвращать planner на replan |
| Экономия считается по цене API при подписке | Marginal $ до исчерпания квоты не отражает реальный ресурс | Оптимизировать solved-task per weekly quota и wall time, а не прайс-лист |
| В окно просто складывают весь корпус | NoLiMa/SciTrek: резкая деградация задолго до claimed limit | Сначала retrieve/structure/compress; полное окно — fallback, не default |

## Применимость к Orchestra

### Что можно переносить уверенно

1. **Не вводить глобальное правило `Opus=planner, Sol=executor`.** PEAR его частично поддерживает, AgentCollab на research прямо опровергает, DoT показывает работоспособность слабой модели даже в decomposition.
2. **Первый framing и replanning после обнаруженного тупика — хорошие кандидаты для Opus 5.** Это совпадает с AgentCollab warm-up/escalation и с высокой ценностью planner memory в PEAR.
3. **Mechanical execution с executable acceptance criteria — кандидат для Sol.** Bulk edits, повторяемые протоколы, тесты и извлечение по строгой схеме похожи на выигрышные leaf-задачи DoT/Sub-goal Distillation. Условие — fail loud и дешёвая внешняя проверка.
4. **Evidence-seeking research нельзя целиком считать mechanical execution.** AgentCollab измерил, что large information-seeker полезнее large planner. Для наших web/research задач Sol может выполнять поиск и таблицы, но выбор первоисточника, чтение неоднозначной таблицы, конфликт источников и итоговая калибровка должны иметь escalation path к Opus.
5. **Review — отдельная точка сильной модели, но прямого A/B в найденных источниках нет.** Рациональная причина — review должен ловить скрытые ошибки дешёвого executor; это inference из роли, а не опубликованный замер Opus/Sol. Кроме силы, полезна независимость runtime/model family.

### 1M Opus против 258K Sol

- **1M — преимущество вместимости, не гарантия понимания.** Gemini `>99.7%` на synthetic needle и NoLiMa/SciTrek расходятся на порядок по сложности. Поэтому нельзя обосновывать Opus для research только длиной окна.
- **258K достаточно для большинства отобранных доказательств, если handoff структурирован.** SciTrek показывает, что компактные database tables радикально лучше full text; это поддерживает curated evidence pack для Sol вместо сырого корпуса.
- **Opus 1M полезен как recovery path**, когда нужная связь могла быть отброшена при retrieval/summary или требуется перечитать многие зависимые документы. Но перед выбором нужно измерять фактический размер и качество на нашей задаче; «помещается» не равно «используется».
- **Частое переключение моделей тоже имеет цену:** AgentCollab связывает снижение switching ratio `49.64 → 45.07` одновременно с лучшим speedup и качеством. В Orchestra разумнее contiguous phase/chunk + явный escalation, чем model switch на каждом tool call.

### Предлагаемая измеримая политика, а не постоянная догма

- `research`: Sol по умолчанию для механического сбора; Opus на framing, конфликт источников, слабую/противоречивую evidence base и synthesis. Сравнить с Opus-only на одних и тех же задачах.
- `plan`: Opus для неоднозначных/связных задач; Sol допустим для планов из уже жёсткого ТЗ. Критерий — mutation/plan review, а не самооценка модели.
- `implement`: Sol для независимых leaf units с тестом; Opus для cohesive changes, где каждый шаг меняет архитектурные предпосылки.
- `review`: сильная независимая модель; дешёвый review допустим лишь как первый фильтр с эскалацией находок и не заменяет проверку результата.

Минимальный наш A/B должен считать не токены отдельной фазы, а **стоимость/квоту и wall time на принятую решённую задачу**, включая planner повторные чтения, handoff, исправления, review rounds и неуспешные траектории. Именно скрытая стоимость координации перевернула результат Akita, а trajectory-level latency отличила AgentCollab от RouteLLM.

## Источники

Все URL ниже были открыты в этой сессии; утверждения из поисковой выдачи без открытия в отчёт не включены.

1. **[ЗАМЕР] [ПЕРВОИСТОЧНИК]** PEAR: Planner-Executor Agent Robustness Benchmark, Findings of EACL 2026 — https://arxiv.org/html/2510.07505
2. **[ЗАМЕР] [ПЕРВОИСТОЧНИК]** AgentCollab: A Self-Evaluation-Driven Collaboration Paradigm for Efficient LLM Agents, arXiv 2026 — https://arxiv.org/html/2603.26034
3. **[ЗАМЕР] [ПЕРВОИСТОЧНИК]** Division-of-Thoughts, The Web Conference 2025 — https://arxiv.org/html/2502.04392
4. **[ЗАМЕР] [ПЕРВОИСТОЧНИК]** Sub-goal Distillation, CoLLAs 2024 — https://arxiv.org/html/2405.02749
5. **[ЗАМЕР] [ПЕРВОИСТОЧНИК]** RouteLLM, 2024 — https://arxiv.org/html/2406.18665
6. **[ЗАМЕР] [ПРАКТИКА]** Morph Multi-Agent Benchmarks, June 2026 — https://www.morphllm.com/benchmarks/multiagent
7. **[ЗАМЕР] [ПРАКТИКА]** AkitaOnRails mixed-model coding benchmark, April 2026 — https://akitaonrails.com/en/2026/04/25/llm-benchmarks-vale-a-pena-misturar-2-modelos/
8. **[ЗАМЕР] [ПЕРВОИСТОЧНИК]** Gemini 1.5 Technical Report, 2024 — https://arxiv.org/pdf/2403.05530
9. **[ЗАМЕР] [ПЕРВОИСТОЧНИК]** NoLiMa, 2025 — https://arxiv.org/html/2502.05167
10. **[ЗАМЕР] [ПЕРВОИСТОЧНИК]** SciTrek, 2026 — https://arxiv.org/html/2509.21028
11. **[ЗАМЕР] [ПЕРВОИСТОЧНИК]** LongBench v2, 2025 — https://arxiv.org/pdf/2412.15204

