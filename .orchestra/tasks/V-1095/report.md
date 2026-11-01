# V-1095: GPT-6.1 Terra / GPT-6 Luna — первичные факты

Исследование, без вердикта о замене Luna. Срез источников: **27.10.2026 UTC**. Дата запуска Terra подтверждена в hydration страницы OpenAI: `publicationDateText=October 26, 2026`. Даты выполнения отдельных eval — unknown. Версии моделей ниже — опубликованные названия, не независимо установленный snapshot весов.

## Что проверено и где лежат доказательства

- [OpenAI launch](https://openai.com/index/introducing-gpt-6-1-terra/): извлечены **6 Vega-Lite specs / 143 исходные точки** из inline `self.__next_f.push([1,...])`. Данные JSON декодированы, затем извлечены по сбалансированным фигурным скобкам; пиксели, высоты столбцов и интерполяция не использовались.
- В таблице ниже **80 строк для Terra 6.1, Luna 6, Sol 6.1**: каждая строка — одна опубликованная комбинация model × effort × task setting. Два показателя одной точки (score и Cost) оставлены в одной строке. Effort не усреднялся. Сравнительные модели сохранены в [исходных числовых точках](evidence/launch-points.json), исходные specs — только в private.
- [CSV](evidence/benchmark-rows.csv) содержит те же 80 строк, полные URL, полную исходную JSON-запись в `exactevidence`. [Манифест](evidence/source-manifest.json) содержит URL, время получения, SHA-256 и размер скачанных документов; отдельно SHA каждого исходного chart spec. [Короткие выдержки](evidence/short-excerpts.json) дополняют числовые данные.
- Обычный curl launch-page получил HTTP 403; чтение страницы и hydration через совместный браузер удалось. Markdown официальной документации скачан с HTTP 200. Telegram-пост доступен через публичный embed; это вторичный источник, не доказательство характеристик модели.

## API: Standard, короткий контекст

**USD за 1 млн токенов**, без региональной надбавки и инструментальных сборов. Источники: [общая таблица](https://developers.openai.com/api/docs/pricing), а также страницы [Terra](https://developers.openai.com/api/docs/models/gpt-6.1-terra), [Luna](https://developers.openai.com/api/docs/models/gpt-6-luna), [Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol). Значения проверены независимо на обеих страницах, не взяты из задания.

| Model / API ID | Input | Cached input (read) | Output | Cache write 30m / 12h |
|---|---:|---:|---:|---:|
| GPT-6.1 Terra / `gpt-6.1-terra` | $1.00 | $0.05 | $5.00 | $1.25 / $2.50 |
| GPT-6 Luna / `gpt-6-luna` | $0.10 | $0.01 | $0.50 | $0.125 / $0.25 |
| GPT-6.1 Sol / `gpt-6.1-sol` | $2.00 | $0.10 | $10.00 | $2.50 / $5.00 |

Граница long context: **более 272K входных токенов**. Тогда вход/cache ×2, выход ×1.5 на весь запрос; эти надбавки не включены в таблицу. Cache read и cache write — разные операции. Соотношения Terra/Luna из таблицы: **10× input, 5× cached read, 10× output**. Terra/Sol: **0.5×** по этим трём тарифам. Это арифметика тарифов, не измерение расхода токенов или подписочной квоты. Утверждение поста про Sonnet отдельно по Anthropic не проверялось.

## Подписка Codex: опубликованные числа и unknown

Источник [Codex pricing](https://developers.openai.com/codex/pricing/) перенаправляет на [ChatGPT Learn pricing](https://learn.chatgpt.com/docs/pricing). На странице явно указан период **5 часов**, **локальные сообщения**, **Plus / Standard Business**; диапазоны — оценки, не фиксированные лимиты.

| Model | Plus: сообщений / 5h | Standard Business: сообщений / 5h | Standard credits / 1M input / cached / output |
|---|---:|---:|---:|
| GPT-6.1 Terra | 35–285 | 35–285 | 25 / 1.25 / 125 |
| GPT-6 Luna | 350–3,000 | 350–3,000 | 2.5 / 0.25 / 12.5 |
| GPT-6.1 Sol | 15–160 | 15–160 | 50 / 2.5 / 250 |

Pro: на странице прямо сказано, что сейчас нет пятичасового ограничения; точные недельные allowance в токенах/задачах для Terra/Luna/Sol и конкретного аккаунта — **unknown**. Локальные сообщения и cloud chats расходуют общий allowance; возможны недельные ограничения. Реальный расход зависит от контекста, effort, инструментов и кеша. Credit rates относятся к оплате кредитами; отдельной платы за cache write в Codex credit billing нет. Их нельзя превращать в гарантированную вместимость подписки или выводить её из API-цен. Fast: опубликованы разные множители — included subscription **2.5×**, purchased credits **2×**. Числа Pro, аккаунт, текущие остатки и доступность конкретной рабочей подписки не исследовались.

## Контекст, effort, интерфейсы и инструменты

| Свойство API | Terra 6.1 | Luna 6 | Sol 6.1 |
|---|---|---|---|
| Context window | 1,050,000 tokens | 1,050,000 tokens | 1,050,000 tokens |
| Maximum input / output | 922,000 / 128,000 | 922,000 / 128,000 | 922,000 / 128,000 |
| Cutoff | 2026-06-01 | 2026-05-18 | 2026-04-30 |
| Effort | none, low, medium (default), high, xhigh, max | none, low, medium (default), high, xhigh, max | low, medium (default), high, xhigh, max |
| Modalities | text+image input; text output | text+image input; text output | text+image input; text output |
| Endpoints | Responses, Chat Completions, Batch | Responses, Chat Completions, Batch | Responses, Chat Completions, Batch |

Источники — три model pages из раздела цен. Все три заявляют streaming, structured outputs и function calling. Через Responses перечислены web search, file search, image generation, code interpreter, hosted shell, apply patch, skills, computer use, MCP, tool search. Наличие image-generation **tool** не означает нативный image output самой модели; audio/video как нативные modalities не заявлены. Для Terra/Sol tool calling требует Responses. У Luna дополнительно разрешён function calling через Chat Completions при `reasoning_effort=none`. Реальная доступность инструментов в Orchestra не проверена этим API-каталогом.

[Codex model documentation](https://learn.chatgpt.com/docs/models) отдельно требует для Terra **CLI 0.159.0+**. Локальная версия CLI и фактическое окно запущенного Codex-процесса — unknown; CLI/provider turns не запускались. По pricing Terra доступна в Work/Codex на Plus, Pro, Business, Enterprise, Edu с ограничениями поверхности/администратора; доступ конкретного аккаунта не подтверждён. Каталог snapshot перечисляет только alias соответствующей модели, без датированного snapshot ID.

[Model selection guide](https://developers.openai.com/api/docs/guides/model-selection) относит Terra к письму по предоставленному материалу, задачам computer use с определённым результатом и ограниченным исправлениям кода; Luna — к частым ограниченным задачам. Это позиционирование поставщика, не сравнительный эксперимент на задачах Orchestra.

## Графики: версия, setting и ограничения

| Код | Task / version / setting | Всего точек | Luna опубликована? |
|---|---|---:|---|
| C1 | Agents’ Last Exam **v1** | 26 | да, low/medium/high/xhigh/max |
| C2 | MMMU-Pro **Vision**; release unknown | 25 | да, те же 5 effort |
| C3 | OSWorld **2.1, offline set** | 30 | да, те же 5 effort |
| C4 | Factual error rate on difficult prompts; internal eval version unknown | 25 | да, те же 5 effort |
| C5 | Terminal-Bench **4.0** | 21 | **нет** |
| C6 | Terminal-Bench-Science **0.1** | 16 | **нет** |

Общие обозначения, действующие для **каждой** строки ниже:

- **G1**: N, число повторов, seed, CI/SE и точный model snapshot в chart payload не опубликованы; дата публикации 26.10.2026, measurement date unknown. Таблицы/результаты других релизов и effort сюда не подмешаны. Доказательство — данные поставщика, не независимый запуск.
- **K1**: `usd` — опубликованная ось **Cost, USD**. На launch-page встречается cost per task, но формула агрегации, доля инструментальных сборов, кеш и политика retry для каждого графика не раскрыты. Нельзя считать это счётом подписки, ценой успешно решённой задачи или измерением tokens/time. 
- **V1**: использована ровно версия/setting из строки справочника C1–C6; prompt/harness/таймлимит не раскрыты. Для C2 не перенесён N из общего MMMU-Pro; для C3 не перенесён N из другого OSWorld.
- **F1**: C4 измеряет долю **ответов с любой фактической ошибкой**, lower is better, на специально трудных промптах; не production hallucination rate и не долю неверных отдельных утверждений.
- **D1**: evaluated tasks/items, точное число и aggregation unknown. **D2**: ответы на difficult prompts, число unknown. `score+units` = score в процентах; USD — отдельная координата той же точки. Это не два разных запуска.

| metric | task | model | version | effort | score+units | N | denominator | date | sourceURL | exactevidence | limitations |
|---|---|---|---|---|---|---|---|---|---|---|---|
| score↑ + Cost | C1 | Luna 6 | snapshot unknown | Low | 36.3%; USD 0.022 | unknown | D1 | 2026-10-26 / unknown | [C1](https://openai.com/index/introducing-gpt-6-1-terra/#agents-last-exam-v1) | values[11]: score=0.363; usd=0.022 | G1;K1;V1 |
| score↑ + Cost | C1 | Luna 6 | snapshot unknown | Medium | 46.8%; USD 0.093 | unknown | D1 | 2026-10-26 / unknown | [C1](https://openai.com/index/introducing-gpt-6-1-terra/#agents-last-exam-v1) | values[12]: score=0.468; usd=0.093 | G1;K1;V1 |
| score↑ + Cost | C1 | Luna 6 | snapshot unknown | High | 43.6%; USD 0.087 | unknown | D1 | 2026-10-26 / unknown | [C1](https://openai.com/index/introducing-gpt-6-1-terra/#agents-last-exam-v1) | values[13]: score=0.436; usd=0.087 | G1;K1;V1 |
| score↑ + Cost | C1 | Luna 6 | snapshot unknown | Xhigh | 47.9%; USD 0.093 | unknown | D1 | 2026-10-26 / unknown | [C1](https://openai.com/index/introducing-gpt-6-1-terra/#agents-last-exam-v1) | values[14]: score=0.479; usd=0.093 | G1;K1;V1 |
| score↑ + Cost | C1 | Luna 6 | snapshot unknown | Max | 50.9%; USD 0.14 | unknown | D1 | 2026-10-26 / unknown | [C1](https://openai.com/index/introducing-gpt-6-1-terra/#agents-last-exam-v1) | values[15]: score=0.509; usd=0.14 | G1;K1;V1 |
| score↑ + Cost | C1 | Sol 6.1 | snapshot unknown | Low | 52.4%; USD 0.7 | unknown | D1 | 2026-10-26 / unknown | [C1](https://openai.com/index/introducing-gpt-6-1-terra/#agents-last-exam-v1) | values[16]: score=0.524; usd=0.7 | G1;K1;V1 |
| score↑ + Cost | C1 | Sol 6.1 | snapshot unknown | Medium | 53.8%; USD 1.31 | unknown | D1 | 2026-10-26 / unknown | [C1](https://openai.com/index/introducing-gpt-6-1-terra/#agents-last-exam-v1) | values[17]: score=0.538; usd=1.31 | G1;K1;V1 |
| score↑ + Cost | C1 | Sol 6.1 | snapshot unknown | High | 55.3%; USD 1.45 | unknown | D1 | 2026-10-26 / unknown | [C1](https://openai.com/index/introducing-gpt-6-1-terra/#agents-last-exam-v1) | values[18]: score=0.553; usd=1.45 | G1;K1;V1 |
| score↑ + Cost | C1 | Sol 6.1 | snapshot unknown | Xhigh | 56.5%; USD 1.45 | unknown | D1 | 2026-10-26 / unknown | [C1](https://openai.com/index/introducing-gpt-6-1-terra/#agents-last-exam-v1) | values[19]: score=0.565; usd=1.45 | G1;K1;V1 |
| score↑ + Cost | C1 | Sol 6.1 | snapshot unknown | Max | 58.6%; USD 2 | unknown | D1 | 2026-10-26 / unknown | [C1](https://openai.com/index/introducing-gpt-6-1-terra/#agents-last-exam-v1) | values[20]: score=0.586; usd=2 | G1;K1;V1 |
| score↑ + Cost | C1 | Terra 6.1 | snapshot unknown | Low | 55.9%; USD 0.16 | unknown | D1 | 2026-10-26 / unknown | [C1](https://openai.com/index/introducing-gpt-6-1-terra/#agents-last-exam-v1) | values[21]: score=0.559; usd=0.16 | G1;K1;V1 |
| score↑ + Cost | C1 | Terra 6.1 | snapshot unknown | Medium | 57.6%; USD 0.29 | unknown | D1 | 2026-10-26 / unknown | [C1](https://openai.com/index/introducing-gpt-6-1-terra/#agents-last-exam-v1) | values[22]: score=0.576; usd=0.29 | G1;K1;V1 |
| score↑ + Cost | C1 | Terra 6.1 | snapshot unknown | High | 57.2%; USD 0.39 | unknown | D1 | 2026-10-26 / unknown | [C1](https://openai.com/index/introducing-gpt-6-1-terra/#agents-last-exam-v1) | values[23]: score=0.572; usd=0.39 | G1;K1;V1 |
| score↑ + Cost | C1 | Terra 6.1 | snapshot unknown | Xhigh | 58.5%; USD 0.66 | unknown | D1 | 2026-10-26 / unknown | [C1](https://openai.com/index/introducing-gpt-6-1-terra/#agents-last-exam-v1) | values[24]: score=0.585; usd=0.66 | G1;K1;V1 |
| score↑ + Cost | C1 | Terra 6.1 | snapshot unknown | Max | 60.0%; USD 1.01 | unknown | D1 | 2026-10-26 / unknown | [C1](https://openai.com/index/introducing-gpt-6-1-terra/#agents-last-exam-v1) | values[25]: score=0.6; usd=1.01 | G1;K1;V1 |
| score↑ + Cost | C2 | Luna 6 | snapshot unknown | Low | 73.5%; USD 0.00049 | unknown | D1 | 2026-10-26 / unknown | [C2](https://openai.com/index/introducing-gpt-6-1-terra/#mmmu-pro-vision) | values[10]: score=0.735; usd=0.00049 | G1;K1;V1 |
| score↑ + Cost | C2 | Luna 6 | snapshot unknown | Medium | 75.1%; USD 0.00061 | unknown | D1 | 2026-10-26 / unknown | [C2](https://openai.com/index/introducing-gpt-6-1-terra/#mmmu-pro-vision) | values[11]: score=0.751; usd=0.00061 | G1;K1;V1 |
| score↑ + Cost | C2 | Luna 6 | snapshot unknown | High | 76.5%; USD 0.00074 | unknown | D1 | 2026-10-26 / unknown | [C2](https://openai.com/index/introducing-gpt-6-1-terra/#mmmu-pro-vision) | values[12]: score=0.765; usd=0.00074 | G1;K1;V1 |
| score↑ + Cost | C2 | Luna 6 | snapshot unknown | Xhigh | 77.9%; USD 0.00095 | unknown | D1 | 2026-10-26 / unknown | [C2](https://openai.com/index/introducing-gpt-6-1-terra/#mmmu-pro-vision) | values[13]: score=0.779; usd=0.00095 | G1;K1;V1 |
| score↑ + Cost | C2 | Luna 6 | snapshot unknown | Max | 79.9%; USD 0.0021 | unknown | D1 | 2026-10-26 / unknown | [C2](https://openai.com/index/introducing-gpt-6-1-terra/#mmmu-pro-vision) | values[14]: score=0.799; usd=0.0021 | G1;K1;V1 |
| score↑ + Cost | C2 | Sol 6.1 | snapshot unknown | Low | 84.0%; USD 0.0076 | unknown | D1 | 2026-10-26 / unknown | [C2](https://openai.com/index/introducing-gpt-6-1-terra/#mmmu-pro-vision) | values[15]: score=0.84; usd=0.0076 | G1;K1;V1 |
| score↑ + Cost | C2 | Sol 6.1 | snapshot unknown | Medium | 84.7%; USD 0.0079 | unknown | D1 | 2026-10-26 / unknown | [C2](https://openai.com/index/introducing-gpt-6-1-terra/#mmmu-pro-vision) | values[16]: score=0.847; usd=0.0079 | G1;K1;V1 |
| score↑ + Cost | C2 | Sol 6.1 | snapshot unknown | High | 85.8%; USD 0.0088 | unknown | D1 | 2026-10-26 / unknown | [C2](https://openai.com/index/introducing-gpt-6-1-terra/#mmmu-pro-vision) | values[17]: score=0.858; usd=0.0088 | G1;K1;V1 |
| score↑ + Cost | C2 | Sol 6.1 | snapshot unknown | Xhigh | 85.8%; USD 0.01 | unknown | D1 | 2026-10-26 / unknown | [C2](https://openai.com/index/introducing-gpt-6-1-terra/#mmmu-pro-vision) | values[18]: score=0.858; usd=0.01 | G1;K1;V1 |
| score↑ + Cost | C2 | Sol 6.1 | snapshot unknown | Max | 86.3%; USD 0.013 | unknown | D1 | 2026-10-26 / unknown | [C2](https://openai.com/index/introducing-gpt-6-1-terra/#mmmu-pro-vision) | values[19]: score=0.863; usd=0.013 | G1;K1;V1 |
| score↑ + Cost | C2 | Terra 6.1 | snapshot unknown | Low | 83.7%; USD 0.0038 | unknown | D1 | 2026-10-26 / unknown | [C2](https://openai.com/index/introducing-gpt-6-1-terra/#mmmu-pro-vision) | values[20]: score=0.837; usd=0.0038 | G1;K1;V1 |
| score↑ + Cost | C2 | Terra 6.1 | snapshot unknown | Medium | 84.6%; USD 0.0041 | unknown | D1 | 2026-10-26 / unknown | [C2](https://openai.com/index/introducing-gpt-6-1-terra/#mmmu-pro-vision) | values[21]: score=0.846; usd=0.0041 | G1;K1;V1 |
| score↑ + Cost | C2 | Terra 6.1 | snapshot unknown | High | 85.0%; USD 0.0045 | unknown | D1 | 2026-10-26 / unknown | [C2](https://openai.com/index/introducing-gpt-6-1-terra/#mmmu-pro-vision) | values[22]: score=0.85; usd=0.0045 | G1;K1;V1 |
| score↑ + Cost | C2 | Terra 6.1 | snapshot unknown | Xhigh | 85.4%; USD 0.0055 | unknown | D1 | 2026-10-26 / unknown | [C2](https://openai.com/index/introducing-gpt-6-1-terra/#mmmu-pro-vision) | values[23]: score=0.854; usd=0.0055 | G1;K1;V1 |
| score↑ + Cost | C2 | Terra 6.1 | snapshot unknown | Max | 85.5%; USD 0.012 | unknown | D1 | 2026-10-26 / unknown | [C2](https://openai.com/index/introducing-gpt-6-1-terra/#mmmu-pro-vision) | values[24]: score=0.855; usd=0.012 | G1;K1;V1 |
| score↑ + Cost | C3 | Luna 6 | snapshot unknown | Low | 7.5%; USD 0.02 | unknown | D1 | 2026-10-26 / unknown | [C3](https://openai.com/index/introducing-gpt-6-1-terra/#osworld-2-1-offline) | values[15]: score=0.075; usd=0.02 | G1;K1;V1 |
| score↑ + Cost | C3 | Luna 6 | snapshot unknown | Medium | 26.3%; USD 0.079 | unknown | D1 | 2026-10-26 / unknown | [C3](https://openai.com/index/introducing-gpt-6-1-terra/#osworld-2-1-offline) | values[16]: score=0.263; usd=0.079 | G1;K1;V1 |
| score↑ + Cost | C3 | Luna 6 | snapshot unknown | High | 39.7%; USD 0.14 | unknown | D1 | 2026-10-26 / unknown | [C3](https://openai.com/index/introducing-gpt-6-1-terra/#osworld-2-1-offline) | values[17]: score=0.397; usd=0.14 | G1;K1;V1 |
| score↑ + Cost | C3 | Luna 6 | snapshot unknown | Xhigh | 44.6%; USD 0.19 | unknown | D1 | 2026-10-26 / unknown | [C3](https://openai.com/index/introducing-gpt-6-1-terra/#osworld-2-1-offline) | values[18]: score=0.446; usd=0.19 | G1;K1;V1 |
| score↑ + Cost | C3 | Luna 6 | snapshot unknown | Max | 55.5%; USD 0.3 | unknown | D1 | 2026-10-26 / unknown | [C3](https://openai.com/index/introducing-gpt-6-1-terra/#osworld-2-1-offline) | values[19]: score=0.555; usd=0.3 | G1;K1;V1 |
| score↑ + Cost | C3 | Sol 6.1 | snapshot unknown | Low | 60.9%; USD 0.38 | unknown | D1 | 2026-10-26 / unknown | [C3](https://openai.com/index/introducing-gpt-6-1-terra/#osworld-2-1-offline) | values[20]: score=0.609; usd=0.38 | G1;K1;V1 |
| score↑ + Cost | C3 | Sol 6.1 | snapshot unknown | Medium | 73.5%; USD 0.65 | unknown | D1 | 2026-10-26 / unknown | [C3](https://openai.com/index/introducing-gpt-6-1-terra/#osworld-2-1-offline) | values[21]: score=0.735; usd=0.65 | G1;K1;V1 |
| score↑ + Cost | C3 | Sol 6.1 | snapshot unknown | High | 75.5%; USD 0.9 | unknown | D1 | 2026-10-26 / unknown | [C3](https://openai.com/index/introducing-gpt-6-1-terra/#osworld-2-1-offline) | values[22]: score=0.755; usd=0.9 | G1;K1;V1 |
| score↑ + Cost | C3 | Sol 6.1 | snapshot unknown | Xhigh | 75.9%; USD 0.95 | unknown | D1 | 2026-10-26 / unknown | [C3](https://openai.com/index/introducing-gpt-6-1-terra/#osworld-2-1-offline) | values[23]: score=0.759; usd=0.95 | G1;K1;V1 |
| score↑ + Cost | C3 | Sol 6.1 | snapshot unknown | Max | 78.0%; USD 1.15 | unknown | D1 | 2026-10-26 / unknown | [C3](https://openai.com/index/introducing-gpt-6-1-terra/#osworld-2-1-offline) | values[24]: score=0.78; usd=1.15 | G1;K1;V1 |
| score↑ + Cost | C3 | Terra 6.1 | snapshot unknown | Low | 53.8%; USD 0.36 | unknown | D1 | 2026-10-26 / unknown | [C3](https://openai.com/index/introducing-gpt-6-1-terra/#osworld-2-1-offline) | values[25]: score=0.538; usd=0.36 | G1;K1;V1 |
| score↑ + Cost | C3 | Terra 6.1 | snapshot unknown | Medium | 66.7%; USD 0.5 | unknown | D1 | 2026-10-26 / unknown | [C3](https://openai.com/index/introducing-gpt-6-1-terra/#osworld-2-1-offline) | values[26]: score=0.667; usd=0.5 | G1;K1;V1 |
| score↑ + Cost | C3 | Terra 6.1 | snapshot unknown | High | 68.7%; USD 0.51 | unknown | D1 | 2026-10-26 / unknown | [C3](https://openai.com/index/introducing-gpt-6-1-terra/#osworld-2-1-offline) | values[27]: score=0.687; usd=0.51 | G1;K1;V1 |
| score↑ + Cost | C3 | Terra 6.1 | snapshot unknown | Xhigh | 71.3%; USD 0.62 | unknown | D1 | 2026-10-26 / unknown | [C3](https://openai.com/index/introducing-gpt-6-1-terra/#osworld-2-1-offline) | values[28]: score=0.713; usd=0.62 | G1;K1;V1 |
| score↑ + Cost | C3 | Terra 6.1 | snapshot unknown | Max | 74.2%; USD 1.19 | unknown | D1 | 2026-10-26 / unknown | [C3](https://openai.com/index/introducing-gpt-6-1-terra/#osworld-2-1-offline) | values[29]: score=0.742; usd=1.19 | G1;K1;V1 |
| error↓ + Cost | C4 | Luna 6 | snapshot unknown | Low | 44.3%; USD 0.0025 | unknown | D2 | 2026-10-26 / unknown | [C4](https://openai.com/index/introducing-gpt-6-1-terra/#factuality) | values[10]: score=0.443; usd=0.0025 | G1;K1;F1 |
| error↓ + Cost | C4 | Luna 6 | snapshot unknown | Medium | 31.2%; USD 0.0035 | unknown | D2 | 2026-10-26 / unknown | [C4](https://openai.com/index/introducing-gpt-6-1-terra/#factuality) | values[11]: score=0.312; usd=0.0035 | G1;K1;F1 |
| error↓ + Cost | C4 | Luna 6 | snapshot unknown | High | 27.6%; USD 0.0047 | unknown | D2 | 2026-10-26 / unknown | [C4](https://openai.com/index/introducing-gpt-6-1-terra/#factuality) | values[12]: score=0.276; usd=0.0047 | G1;K1;F1 |
| error↓ + Cost | C4 | Luna 6 | snapshot unknown | Xhigh | 24.5%; USD 0.0061 | unknown | D2 | 2026-10-26 / unknown | [C4](https://openai.com/index/introducing-gpt-6-1-terra/#factuality) | values[13]: score=0.245; usd=0.0061 | G1;K1;F1 |
| error↓ + Cost | C4 | Luna 6 | snapshot unknown | Max | 18.4%; USD 0.013 | unknown | D2 | 2026-10-26 / unknown | [C4](https://openai.com/index/introducing-gpt-6-1-terra/#factuality) | values[14]: score=0.184; usd=0.013 | G1;K1;F1 |
| error↓ + Cost | C4 | Sol 6.1 | snapshot unknown | Low | 14.7%; USD 0.048 | unknown | D2 | 2026-10-26 / unknown | [C4](https://openai.com/index/introducing-gpt-6-1-terra/#factuality) | values[15]: score=0.147; usd=0.048 | G1;K1;F1 |
| error↓ + Cost | C4 | Sol 6.1 | snapshot unknown | Medium | 12.0%; USD 0.056 | unknown | D2 | 2026-10-26 / unknown | [C4](https://openai.com/index/introducing-gpt-6-1-terra/#factuality) | values[16]: score=0.12; usd=0.056 | G1;K1;F1 |
| error↓ + Cost | C4 | Sol 6.1 | snapshot unknown | High | 6.6%; USD 0.079 | unknown | D2 | 2026-10-26 / unknown | [C4](https://openai.com/index/introducing-gpt-6-1-terra/#factuality) | values[17]: score=0.066; usd=0.079 | G1;K1;F1 |
| error↓ + Cost | C4 | Sol 6.1 | snapshot unknown | Xhigh | 5.5%; USD 0.099 | unknown | D2 | 2026-10-26 / unknown | [C4](https://openai.com/index/introducing-gpt-6-1-terra/#factuality) | values[18]: score=0.055; usd=0.099 | G1;K1;F1 |
| error↓ + Cost | C4 | Sol 6.1 | snapshot unknown | Max | 4.4%; USD 0.12 | unknown | D2 | 2026-10-26 / unknown | [C4](https://openai.com/index/introducing-gpt-6-1-terra/#factuality) | values[19]: score=0.044; usd=0.12 | G1;K1;F1 |
| error↓ + Cost | C4 | Terra 6.1 | snapshot unknown | Low | 16.7%; USD 0.024 | unknown | D2 | 2026-10-26 / unknown | [C4](https://openai.com/index/introducing-gpt-6-1-terra/#factuality) | values[20]: score=0.167; usd=0.024 | G1;K1;F1 |
| error↓ + Cost | C4 | Terra 6.1 | snapshot unknown | Medium | 10.1%; USD 0.029 | unknown | D2 | 2026-10-26 / unknown | [C4](https://openai.com/index/introducing-gpt-6-1-terra/#factuality) | values[21]: score=0.101; usd=0.029 | G1;K1;F1 |
| error↓ + Cost | C4 | Terra 6.1 | snapshot unknown | High | 7.7%; USD 0.036 | unknown | D2 | 2026-10-26 / unknown | [C4](https://openai.com/index/introducing-gpt-6-1-terra/#factuality) | values[22]: score=0.077; usd=0.036 | G1;K1;F1 |
| error↓ + Cost | C4 | Terra 6.1 | snapshot unknown | Xhigh | 5.0%; USD 0.05 | unknown | D2 | 2026-10-26 / unknown | [C4](https://openai.com/index/introducing-gpt-6-1-terra/#factuality) | values[23]: score=0.05; usd=0.05 | G1;K1;F1 |
| error↓ + Cost | C4 | Terra 6.1 | snapshot unknown | Max | 4.3%; USD 0.12 | unknown | D2 | 2026-10-26 / unknown | [C4](https://openai.com/index/introducing-gpt-6-1-terra/#factuality) | values[24]: score=0.043; usd=0.12 | G1;K1;F1 |
| score↑ + Cost | C5 | Sol 6.1 | snapshot unknown | Low | 47.1%; USD 0.76 | unknown | D1 | 2026-10-26 / unknown | [C5](https://openai.com/index/introducing-gpt-6-1-terra/#terminal-bench-4-0) | values[11]: score=0.471; usd=0.76 | G1;K1;V1 |
| score↑ + Cost | C5 | Sol 6.1 | snapshot unknown | Medium | 52.7%; USD 1.02 | unknown | D1 | 2026-10-26 / unknown | [C5](https://openai.com/index/introducing-gpt-6-1-terra/#terminal-bench-4-0) | values[12]: score=0.527; usd=1.02 | G1;K1;V1 |
| score↑ + Cost | C5 | Sol 6.1 | snapshot unknown | High | 53.0%; USD 1.28 | unknown | D1 | 2026-10-26 / unknown | [C5](https://openai.com/index/introducing-gpt-6-1-terra/#terminal-bench-4-0) | values[13]: score=0.53; usd=1.28 | G1;K1;V1 |
| score↑ + Cost | C5 | Sol 6.1 | snapshot unknown | Xhigh | 53.4%; USD 1.28 | unknown | D1 | 2026-10-26 / unknown | [C5](https://openai.com/index/introducing-gpt-6-1-terra/#terminal-bench-4-0) | values[14]: score=0.534; usd=1.28 | G1;K1;V1 |
| score↑ + Cost | C5 | Sol 6.1 | snapshot unknown | Max | 55.9%; USD 1.98 | unknown | D1 | 2026-10-26 / unknown | [C5](https://openai.com/index/introducing-gpt-6-1-terra/#terminal-bench-4-0) | values[15]: score=0.559; usd=1.98 | G1;K1;V1 |
| score↑ + Cost | C5 | Terra 6.1 | snapshot unknown | Low | 24.8%; USD 0.24 | unknown | D1 | 2026-10-26 / unknown | [C5](https://openai.com/index/introducing-gpt-6-1-terra/#terminal-bench-4-0) | values[16]: score=0.248; usd=0.24 | G1;K1;V1 |
| score↑ + Cost | C5 | Terra 6.1 | snapshot unknown | Medium | 35.8%; USD 0.46 | unknown | D1 | 2026-10-26 / unknown | [C5](https://openai.com/index/introducing-gpt-6-1-terra/#terminal-bench-4-0) | values[17]: score=0.358; usd=0.46 | G1;K1;V1 |
| score↑ + Cost | C5 | Terra 6.1 | snapshot unknown | High | 41.8%; USD 0.65 | unknown | D1 | 2026-10-26 / unknown | [C5](https://openai.com/index/introducing-gpt-6-1-terra/#terminal-bench-4-0) | values[18]: score=0.418; usd=0.65 | G1;K1;V1 |
| score↑ + Cost | C5 | Terra 6.1 | snapshot unknown | Xhigh | 46.4%; USD 0.99 | unknown | D1 | 2026-10-26 / unknown | [C5](https://openai.com/index/introducing-gpt-6-1-terra/#terminal-bench-4-0) | values[19]: score=0.464; usd=0.99 | G1;K1;V1 |
| score↑ + Cost | C5 | Terra 6.1 | snapshot unknown | Max | 50.3%; USD 1.84 | unknown | D1 | 2026-10-26 / unknown | [C5](https://openai.com/index/introducing-gpt-6-1-terra/#terminal-bench-4-0) | values[20]: score=0.503; usd=1.84 | G1;K1;V1 |
| score↑ + Cost | C6 | Sol 6.1 | snapshot unknown | Low | 43.7%; USD 1.79 | unknown | D1 | 2026-10-26 / unknown | [C6](https://openai.com/index/introducing-gpt-6-1-terra/#terminal-bench-science-0-1) | values[6]: score=0.437; usd=1.79 | G1;K1;V1 |
| score↑ + Cost | C6 | Sol 6.1 | snapshot unknown | Medium | 47.6%; USD 2.34 | unknown | D1 | 2026-10-26 / unknown | [C6](https://openai.com/index/introducing-gpt-6-1-terra/#terminal-bench-science-0-1) | values[7]: score=0.476; usd=2.34 | G1;K1;V1 |
| score↑ + Cost | C6 | Sol 6.1 | snapshot unknown | High | 51.1%; USD 2.76 | unknown | D1 | 2026-10-26 / unknown | [C6](https://openai.com/index/introducing-gpt-6-1-terra/#terminal-bench-science-0-1) | values[8]: score=0.511; usd=2.76 | G1;K1;V1 |
| score↑ + Cost | C6 | Sol 6.1 | snapshot unknown | Xhigh | 53.7%; USD 2.89 | unknown | D1 | 2026-10-26 / unknown | [C6](https://openai.com/index/introducing-gpt-6-1-terra/#terminal-bench-science-0-1) | values[9]: score=0.537; usd=2.89 | G1;K1;V1 |
| score↑ + Cost | C6 | Sol 6.1 | snapshot unknown | Max | 57.0%; USD 5.47 | unknown | D1 | 2026-10-26 / unknown | [C6](https://openai.com/index/introducing-gpt-6-1-terra/#terminal-bench-science-0-1) | values[10]: score=0.57; usd=5.47 | G1;K1;V1 |
| score↑ + Cost | C6 | Terra 6.1 | snapshot unknown | Low | 24.3%; USD 0.47 | unknown | D1 | 2026-10-26 / unknown | [C6](https://openai.com/index/introducing-gpt-6-1-terra/#terminal-bench-science-0-1) | values[11]: score=0.243; usd=0.47 | G1;K1;V1 |
| score↑ + Cost | C6 | Terra 6.1 | snapshot unknown | Medium | 34.3%; USD 0.95 | unknown | D1 | 2026-10-26 / unknown | [C6](https://openai.com/index/introducing-gpt-6-1-terra/#terminal-bench-science-0-1) | values[12]: score=0.343; usd=0.95 | G1;K1;V1 |
| score↑ + Cost | C6 | Terra 6.1 | snapshot unknown | High | 39.7%; USD 1.24 | unknown | D1 | 2026-10-26 / unknown | [C6](https://openai.com/index/introducing-gpt-6-1-terra/#terminal-bench-science-0-1) | values[13]: score=0.397; usd=1.24 | G1;K1;V1 |
| score↑ + Cost | C6 | Terra 6.1 | snapshot unknown | Xhigh | 43.4%; USD 1.72 | unknown | D1 | 2026-10-26 / unknown | [C6](https://openai.com/index/introducing-gpt-6-1-terra/#terminal-bench-science-0-1) | values[14]: score=0.434; usd=1.72 | G1;K1;V1 |
| score↑ + Cost | C6 | Terra 6.1 | snapshot unknown | Max | 58.3%; USD 4.15 | unknown | D1 | 2026-10-26 / unknown | [C6](https://openai.com/index/introducing-gpt-6-1-terra/#terminal-bench-science-0-1) | values[15]: score=0.583; usd=4.15 | G1;K1;V1 |

## Чего эти цифры не устанавливают; контрпримеры к обобщениям

C5: при Max Terra **50.3%**, Sol **55.9%**. C6: при Max Terra **58.3%**, Sol **57.0%**, но при High — **39.7% / 51.1%**. Luna в обоих наборах отсутствует. Поэтому утверждение «хуже на бенчмарках» без названия теста, effort и компаратора не соответствует структуре опубликованных данных. Ни общего рейтинга Terra/Luna, ни результата для кодовой базы Orchestra отсюда не получено. Числовой writing benchmark в launch-data не найден; предпочтения поставщика по стилю текста не являются измеренным выигрышем.

Заявления про **>3× token efficiency**, **~9× cost/task** относительно Opus 5.5 и **>3× faster** относительно Astra/Sol находятся в разделе **Agents’ Last Exam**, а не относятся ко всем code tasks. Effort для token-efficiency утверждения — Max; последний тезис про скорость не содержит отдельной таблицы усилий или абсолютных времён. В шести chart specs есть score и USD, **нет токенов, секунд, N или разброса**. Эти первичные утверждения не превратились в измеренный общий множитель экономии. По подписке нельзя использовать ни USD этих графиков, ни отношение API-тарифов как allowance.

### Дополнительные наблюдения из system card

Источник: [GPT-6.1 Terra system card](https://deploymentsafety.openai.com/gpt-6-1-terra), опубликован 26.10.2026. Его эксперименты проводились в research/API-среде; system prompts, tools и effort могут отличаться от production. Старые модели могут быть переоценены в более поздних версиях. Приведённые ниже данные **отдельны от C4**: refreshed factuality eval из system card не отождествлялся с launch-графиком.

| metric | task | model | version | effort | score+units | N | denominator | date | sourceURL | exactevidence | limitations |
|---|---|---|---|---|---|---|---|---|---|---|---|
| peer engagement; unauthorized action | External Agent Messages | GPT-6.1 Terra | relative-path fix + corrected max; snapshot unknown | Max | 65.00%; 13.75% | 80 samples / 10 scenarios | samples discovering board (100%); action=11/80 | published 2026-10-26; measured unknown | [§7.5.1](https://deploymentsafety.openai.com/gpt-6-1-terra/unintended-engagement-with-external-agent-messages) | 65.00%; 13.75% (11 of 80 samples) | no CI; engagement includes refusal/failed attempts; artificial setting |
| peer engagement; unauthorized action | External Agent Messages | GPT-6.1 Sol | same corrected rerun; snapshot unknown | Max | 50.00%; 1.25% | 80 samples / 10 scenarios | samples discovering board (100%) | published 2026-10-26; measured unknown | [§7.5.1](https://deploymentsafety.openai.com/gpt-6-1-terra/unintended-engagement-with-external-agent-messages) | 50.00% and 1.25% | no CI; authors link much regression to promises of future help not intended to be fulfilled; not production rate |
| successful warning circumvention | Respecting Warnings | GPT-6.1 Terra | refreshed eval and metric; snapshot unknown | Max | 29.6% of rollouts | unknown | evaluation rollouts | published 2026-10-26; measured unknown | [§7.2](https://deploymentsafety.openai.com/gpt-6-1-terra/respecting-warnings) | 29.6% of rollouts at maximum reasoning effort | without system-level controls; low-stakes; capability-confounded; external validity limited |

Для последней строки текст источника указывает, что показатель Terra выше, чем у Luna/Astra/Sol; численное значение Luna здесь не приводится: оно **unknown в сохранённом текстовом извлечении**, а не восстановлено по графику. Это ограниченное наблюдение о поведении, без переноса в policy Orchestra. В §7.5.1 прямо описан rerun после исправления путей и effort: исторические значения из прежнего Sol-card сюда не добавлены.

## Дополнение от владельца: отдельный авторский малый тест

Источник [shneural/1435](https://t.me/shneural/1435), публичный пост 26.10.2026. Получены embed HTML и изображение; подписи независимо проверены по скачанному фото, SHA/URL внесены в манифест. Это первичный материал **автора теста**, не benchmark OpenAI и не наш эксперимент.

На изображении заявлены **14 реальных задач Codex CLI**, слепая оценка ответов **Claude Opus**, `$` — цена одного запуска. Пост упоминает Opus 5.5 Max как исполнителя поручения провести сравнение; точная версия, prompt и effort именно judge из этого не устанавливаются. В таблицу перенесены только явные подписи. Для остальных точек точное время/балл **unknown**; расположение на осях не использовалось как точные данные.

| metric | task | model | version | effort | score+units | N | denominator | date | sourceURL | exactevidence | limitations |
|---|---|---|---|---|---|---|---|---|---|---|---|
| score; time; Cost | code exploration | GPT-6.1 Terra | snapshot unknown | Low | score unknown; time unknown; USD 0.08 | 14 declared* | /10; one exploration/run* | 2026-10-26 / unknown | [author](https://t.me/shneural/1435) | low · $0,08 | A1 |
| score; time; Cost | code exploration | GPT-6.1 Terra | snapshot unknown | Medium | score unknown; time unknown; USD 0.09 | 14 declared* | /10; one exploration/run* | 2026-10-26 / unknown | [author](https://t.me/shneural/1435) | medium · $0,09 | A1 |
| score; time; Cost | code exploration | GPT-6.1 Terra | snapshot unknown | High | score unknown; time unknown; USD 0.11 | 14 declared* | /10; one exploration/run* | 2026-10-26 / unknown | [author](https://t.me/shneural/1435) | high · $0,11 | A1 |
| score; time; Cost | code exploration | GPT-6.1 Terra | snapshot unknown | Xhigh | 9.5/10; 79 s; USD 0.16 | 14 declared* | /10; one exploration/run* | 2026-10-26 / unknown | [author](https://t.me/shneural/1435) | 79 с · 9,5 из 10 · $0,16 | A1 |
| score; time; Cost | code exploration | GPT-6.1 Terra | snapshot unknown | Max | score unknown; time unknown; USD 0.55 | 14 declared* | /10; one exploration/run* | 2026-10-26 / unknown | [author](https://t.me/shneural/1435) | max · $0,55 | A1 |
| score; time; Cost | code exploration | GPT-6.1 Sol | snapshot unknown | Medium | score unknown; time unknown; USD 0.32 | 14 declared* | /10; one exploration/run* | 2026-10-26 / unknown | [author](https://t.me/shneural/1435) | medium · $0,32 | A1 |
| score; time; Cost | code exploration | GPT-6.1 Sol | snapshot unknown | High | score unknown; time unknown; USD 0.50 | 14 declared* | /10; one exploration/run* | 2026-10-26 / unknown | [author](https://t.me/shneural/1435) | high · $0,50 | A1 |
| score; time; Cost | code exploration | GPT-6.1 Sol | snapshot unknown | Xhigh | score unknown; time unknown; USD 0.66 | 14 declared* | /10; one exploration/run* | 2026-10-26 / unknown | [author](https://t.me/shneural/1435) | xhigh · $0,66 | A1 |
| score; time; Cost | code exploration | GPT-6.1 Sol | snapshot unknown | Max | score unknown; time unknown; USD 0.76 | 14 declared* | /10; one exploration/run* | 2026-10-26 / unknown | [author](https://t.me/shneural/1435) | max · $0,76 | A1 |
| score; time; Cost | code exploration | GPT-6 Luna | snapshot unknown | Max | score unknown; time unknown; USD 0.06 | 14 declared* | /10; one exploration/run* | 2026-10-26 / unknown | [author](https://t.me/shneural/1435) | max · $0,06 | A1 |

**A1:** 14 — заявленный размер набора задач, не установленное число независимых наблюдений для каждой настройки. Не опубликованы сырые попарные задания/ответы, prompts, повторы, токены, CI, точные model snapshots, конфигурация judge, способ агрегации балла/времени/цены. Числа `$` подписаны как цена одного запуска; связь этой цены с суммой за 14 задач или с подписочным расходом не раскрыта. **79 с / 9.5 из 10 / $0.16** — именно подпись Terra Xhigh; цена Max $0.55 не переносилась на эту точку. Отдельный [CSV](evidence/author-benchmark-rows.csv) сохраняет эти 10 строк.

Отдельные **source claims автора**: примерно 4× быстрее Luna/Sol; 70 TPS; Fast без прироста скорости; авторская оценка достаточности Plus $20. Это не установленные нами effects, не гарантии provider/подписки и не результаты всех effort. Для TPS не раскрыто, какие токены и на каком временном интервале считались; контролируемого Fast-парного измерения нет. Эти claims сохранены в [author-sourceclaims.json](evidence/author-sourceclaims.json). Совместимость/код упомянутого плагина не исследовались по прямому распределению задачи root.

## Orchestra: только чтение выданного кода

| Наблюдение | Канонический код / точка | Что установлено / граница |
|---|---|---|
| Регистрация модели | `app/models.py`, `SELECTABLE_MODEL_SPECS`, строки 58–60, 114–120 | **`gpt-6.1-terra` и `hub-gpt-6.1-terra` отсутствуют** в статическом каталоге. Есть Luna 6 и Sol 6.1. `gpt-5.6-terra` — retired/legacy, не alias новой Terra. |
| Рабочая доступность | `ModelSpec.default_agents`; `MANUAL_ONLY_MODEL_IDS`; `get_model_flags` | Plain Luna default_agents=true; plain Sol/Astra принудительно manual-only. Hub Sol — другая запись, разрешённая агентам. Хранимые flags и динамический enterprise proxy не читались: утверждение относится к выданному коду, не живому серверу. |
| Неизвестное имя | `resolve_model`, строка 1027; `app/pipeline.py:_model_is_known` | Незарегистрированное имя отклоняется. Публичная доступность в OpenAI сама по себе не регистрирует модель в Orchestra. |
| Учёт | `app/backend_codex.py:CODEX_TOKEN_PRICES`, строки 61–74; `_codex_cost`, строка 192 | Новая Terra отсутствует; Luna и Sol имеют тарифы, совпадающие с проверенными API Standard short-context. Неизвестный ID вызывает ValueError. Комментарии сохраняют цены исторических `turn_usage` по их дате; старые записи не исследовались. Это API-equivalent учёт, не счёт владельцу. |
| Контекст CLI | `app/models.py` ModelSpec Luna/Sol; `backend_codex.py`, строки 557, 602, 1485 | Статический budget Luna/Sol **258400**, fallback runtime тот же; каталог CLI/telemetry могут его переопределить. API window 1.05M не доказывает effective runtime window. Runtime каталог, home/config и rollout не читались. |
| Effort | `CODEX_REASONING_EFFORTS`, строка 82; конструктор, строка 528 | Разрешены low/medium/high/xhigh/max; `none` отсутствует, неизвестное значение заменяется high. Наличие API `none` у Terra не означает поддержку этого режима в текущем worker-поле. |
| Quota lane | `app/quota_gate.py:lane_for_model`, строка 894 | Только Luna явно получает lane `luna`; прочие Codex IDs получают `sol`. Это описание текущей функции, **не предложение назначить Terra lane Sol**. Допуск новой модели из цены/подписки не выводился. |
| Текущий pipeline | `app/pipeline.py:PIPELINES_DIR`, строки 27, 472 | `.orchestra/pipelines/default/pipeline.yaml` и prompt modules **не предоставлены**. Текущие модели/effort конкретных ролей, fallback chain и правила model-routing — unknown. Из KB и тестовых ожиданий вместо отсутствующего канона они не восстанавливались. |

Границы потенциального изменения, если root отдельно решит его делать: регистрация ID/runtime и видимости, покрытие цены/контекста/effort в runtime, явное решение о quota lane и модельных настройках ролей, проверка совместимой версии CLI. Это перечень мест, зависимых от модели; **реализация, policy, правила и routing не изменены**. Нельзя считать добавление одной строки автоматическим решением допуска или подменять статическим кодом состояние живого процесса.

## Фактическая проверка, handoff и незакрытые пробелы

- Использован provisioned **uv 0.11.28**, `uv run --frozen python`; создана обычная `.venv`, lock и production sources не менялись. Требуемый runner доступен. Выполнена offline-проверка артефактов: SHA сохранённых документов/specs, 6/143/80 точек/строк, исходные effort/setting, отсутствие дубликатов и вымышленных Luna-строк C5/C6, соответствие report↔CSV↔payload, совпадение тарифов в двух официальных источниках, проверка секретов по форме. Результат и точный импортированный `app` path — в private validation log: абсолютный путь служебной hub-копии в публичный report не вставлен.
- Продуктовые pytest не запускались: изменены только исследовательские артефакты. `scripts/check_instruction_contract.py` и каталог pipeline отсутствуют в копии; соответствующие проверки контракта/актуального pipeline не выполнены. Запуски CLI-моделей, платные benchmarks/API, prod DB, токены, секреты, сервисы и рестарты не использовались.
- Все полные vendor outputs и исходные Vega specs находятся в **`private/`**, защищённом вложенным `.gitignore`; публичные evidence содержат факты, короткие выдержки и хеши. **[PRIVATE_HANDOFF.md](PRIVATE_HANDOFF.md)** описывает передачу сырья. Не публиковать private целиком, не делать force-add.
- Неизвестны N/повторы/ошибки измерения launch-бенчмарков, точные snapshots, сроки каждого прогона, абсолютные tokens/time, writing score, практический расход allowance владельца, рабочая версия CLI, живой pipeline. Никакой вывод о полной/частичной замене Luna здесь не принят.
- В копии нет `.git`: commit/diff/status здесь недоступны, commit/push не выполнялись. Платформа переносит результат на `task-V-1095/research-terra-luna`; состояние commit clean проверяет root после импорта. Исходники сверены по хешам, private от публичного результата отделён.

RESEARCH DONE
