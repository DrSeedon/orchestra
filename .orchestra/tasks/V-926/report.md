# V-926 — DeepSeek Flash 1017, OpenRouter и Search/Fetch

Дата проверки: 17 октября 2026. Код Orchestra, ключи и `.env` не менялись. Три оплаченных запроса сделаны через уже существующий OpenRouter-ключ и только через разрешённый маршрут `deepseek/deepseek-v4.1-flash`; суммарная стоимость по ответам OpenRouter — $0.000257548 (около $0.00026). Сырые данные без ключей и reasoning-полей сохранены в [`raw/`](raw/).

## Краткий ответ

`1017` — опубликованный 17 октября новый снимок V4.1 Flash. DeepSeek пишет об обновлении API и оставляет свой API-идентификатор `deepseek-flash`; OpenRouter добавил для снимка отдельный маршрут `deepseek/deepseek-v4.1-flash-1017`. Наш текущий разрешённый маршрут автоматически на снимок не перешёл: метаданные всех трёх наших запросов показывают вариант `deepseek/deepseek-v4.1-flash-20260910`.

Заявление «244 ток/с» не подтверждается проверенными материалами: changelog DeepSeek не приводит абсолютного throughput, а текущая страница OpenRouter для 1017 показывает лучший провайдерский P50 146 ток/с. Наши короткие пробы старого варианта дали по метаданным OpenRouter 130, 77 и 95 ток/с; это один запрос на провайдера и не бенчмарк 1017. Утверждение о $500/мес также не соответствует официальной таблице API: Ultrafast для GPT-6.1 Sol тарифицируется за токены ($12/$60 за миллион input/output при коротком контексте), а не как установленный на этой странице месячный тариф.

Search/Fetch — отдельные HTTP API DeepSeek; для модели они могут быть обёрнуты в `web_search`/`web_fetch` tools самим Harness. Их вызывают с DeepSeek API key, напрямую либо через server-side integrations. Бесплатность до 31 октября 16:00 UTC относится к инструментам клиентов, использующих DeepSeek API, а не к OpenRouter-ключу. В Harness Orchestra сейчас нет выделенных web-search/fetch tools; Codex настроен на live поиск, а Claude search зависит от фактического Claude Code runtime/backend.

## 1. Что означает 1017 и какой вариант у нас

В changelog DeepSeek за 17.10 сказано, что V4.1 Flash обновлён до `DeepSeek-V4.1-Flash-1017`; для официального DeepSeek API метод вызова и цена не меняются, используется имя `deepseek-flash`. Это новый датированный снимок модели, а не новая схема API. Официальная заметка указывает на выпущенные веса [Hugging Face](https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash-1017). [DeepSeek changelog, 17.10](https://api-docs.deepseek.com/updates/), [анонс 1017](https://api-docs.deepseek.com/news/news261017/).

OpenRouter каталогизирует 1017 отдельным slug `deepseek/deepseek-v4.1-flash-1017` и описывает его как снимок от 17 октября. Отдельно доступен прежний `deepseek/deepseek-v4.1-flash`, созданный 10 сентября. В API Endpoints каталоге у старого slug 36 endpoint-записей / 31 имя провайдера, у 1017 — 5 endpoint-записей для трёх имён: DeepSeek, DeepInfra и InferenceNet. [OpenRouter: Flash 1017](https://openrouter.ai/deepseek/deepseek-v4.1-flash-1017), [каталог OpenRouter API](https://openrouter.ai/api/v1/models/deepseek/deepseek-v4.1-flash-1017/endpoints), [старый slug](https://openrouter.ai/deepseek/deepseek-v4.1-flash).

Проверка маршрута: `app/models.py:488–492` разрешает только `deepseek/deepseek-v4.1-flash`; `-1017` в allowlist нет. Каждый из трёх пробных запросов был явно закреплён за одним из текущих предпочтительных провайдеров из `app/harness/llm.py:31–38`, без fallback. OpenRouter generation metadata каждого запроса указали модель `deepseek/deepseek-v4.1-flash-20260910` и фактического провайдера DeepInfra, StreamLake или GMICloud. Значит, по фактическому ответу API, нынешний маршрут пока обслуживает вариант от 10 сентября; автоматического обновления до 1017 нет.

## 2. Скорость и цена

### OpenRouter, новый slug 1017

OpenRouter показывает P50 throughput по провайдерам и опубликованные endpoint rates. «Best across providers» — 146 ток/с P50, это меньше заявления 244 примерно на 40%. В таблице OpenRouter для доступных endpoint-ов:

| Провайдер / вариант | Input $/М | Output $/М | Cache read $/М | P50 ток/с |
|---|---:|---:|---:|---:|
| InferenceNet | $0.10 | $0.50 | $0.002 | 120 |
| DeepInfra со скидкой | $0.14 | $0.42 | $0.0042 | 47 |
| DeepSeek | $0.15 | $0.60 | $0.003 | 146 |
| DeepInfra Priority со скидкой | $0.21 | $0.63 | $0.0063 | 43 |
| DeepInfra Flex со скидкой | $0.112 | $0.336 | $0.00336 | 39 |

Цены и скорость — моментальный снимок каталога OpenRouter; у Flex-строки страница помечает, что этот endpoint не участвует в Standard routing. Публичная страница модели указывает 146 ток/с как лучший provider P50. Это статистика поставщика, не гарантия одной конкретной задачи. [Страница 1017 и таблица провайдеров OpenRouter](https://openrouter.ai/deepseek/deepseek-v4.1-flash-1017).

### Наш разрешённый маршрут (снимок 20260910)

Сделано по одному короткому стриминговому запросу с `reasoning.enabled=false`, принудительным provider order и `allow_fallbacks=false`. Метрики `tokens_completion / generation_time` взяты из OpenRouter generation API; response usage и metadata расходились по числу completion tokens, поэтому приводятся также сырые JSON поля. Ограниченный одиночный запрос не позволяет судить о типичной скорости.

| Провайдер | Фактическая модель | Completion / generation time | API tok/с | Латентность до первой генерации | Фактическая стоимость запроса |
|---|---|---:|---:|---:|---:|
| DeepInfra | `…-20260910` | 142 / 1.094 с | 129.8 | 233 мс | $0.000053222 |
| StreamLake | `…-20260910` | 154 / 2.008 с | 76.7 | 1.012 с | $0.000078695 |
| GMICloud | `…-20260910` | 197 / 2.064 с | 95.4 | 959 мс | $0.000125631 |

GMICloud завершил запрос по лимиту (`native_finish_reason=length`) и не выдал видимого текста; поэтому его 95.4 — только отношение полей API, а не сопоставимый пользовательский output rate. Во всех случаях OpenRouter generation metadata подтверждает старый снимок. Сырые запросы, очищенные от reasoning-полей, SSE usage и generation metadata лежат в [`openrouter-probes.jsonl`](raw/openrouter-probes.jsonl). Сырые OpenRouter catalog responses — [`openrouter-endpoints-legacy.json`](raw/openrouter-endpoints-legacy.json) и [`openrouter-endpoints-1017.json`](raw/openrouter-endpoints-1017.json).

По текущему Endpoints API тарифы прежнего slug у провайдеров различаются: DeepInfra Flex $0.112/$0.336 за М input/output, DeepInfra standard $0.14/$0.42, StreamLake $0.1497/$0.5988, DeepSeek $0.15/$0.60, GMICloud $0.18/$0.72; cache read — соответственно $0.00336, $0.0042, $0.002994, $0.003 и $0.0036. Сводка API и правила получения измерений описаны в [OpenRouter Endpoints API](https://openrouter.ai/docs/api/api-reference/endpoints/list-all-endpoints-for-a-model) и [Generation API](https://openrouter.ai/docs/api/api-reference/generations/get-request-&-usage-metadata-for-a-generation). Обычный маршрут допускает fallback; реальные цена и скорость зависят от фактического provider, а не только от alias.

### Проверка сравнения с GPT-6.1 Sol Ultrafast

OpenAI называет Ultrafast самым быстрым API service tier, но в проверенных документах не обещает 244 ток/с. Доступ зависит от API usage tier и TPM limit. Официальная таблица API указывает GPT-6.1 Sol Ultrafast: $12 input / $60 output за 1M токенов короткого контекста (long-context — $24/$90); отдельно описан 6× коэффициент относительно Standard. Это токеновая API-оплата, не подтверждение «$500/мес». Скорость из OpenRouter и такой API тариф нельзя прямо сравнить без одинакового prompt/режима/счёта выходных токенов и реальных измерений обоих endpoint-ов. [OpenAI Ultrafast](https://developers.openai.com/api/docs/guides/ultrafast-mode), [официальная таблица тарифов](https://developers.openai.com/api/docs/pricing?latest-pricing=ultrafast), [модель GPT-6.1 Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol).

## 3. Search / Fetch

DeepSeek публикует два сырьевых JSON endpoint-а на `https://api.deepseek.com`:

- `POST /v1/tools/search`, тело с `query` (не более 128 символов), опциональными `count` (1–50), `ori_question`, `localization`, `need_content`; ответ — массив структурированных результатов.
- `POST /v1/tools/fetch`, тело с `url`; ответ содержит заголовок и извлечённое содержимое страницы в Markdown.

Обе операции используют `Authorization: Bearer <DeepSeek API Key>`. Это отдельные HTTP endpoints, не `tools: [{type:function,…}]` для chat completion; вызывающий Harness может представить их модели как обычные tools. В текущих документах не нашёл описания маршрута этих DeepSeek endpoints через OpenRouter. OpenRouter может предоставлять собственный `openrouter:web_search`, но это отдельная функция OpenRouter, а не DeepSeek Search/Fetch. [OpenRouter server tool](https://openrouter.ai/docs/features/plugins/overview).

DeepSeek указывает бесплатность Search/Fetch до 31.10.2026 16:00 UTC; с этого момента каждое API тарифицируется отдельно по $0.75 за 1000 успешных запросов. Успех означает HTTP 200 и непустой `results` для Search или содержимое для Fetch; ошибки/пустой Search не тарифицируются. Лимит каждого API — 5 QPS на аккаунт, у Fetch дополнительно лимит по домену. Для бесплатного server-side режима источник требует DeepSeek API user/key; карта или обязательное пополнение для free-периода в просмотренной документации не оговорены. В официальном DeepSeek Harness web tools называются `web_search` и `web_fetch`; его исходник описывает их как tools с provider через `ctx.web`, тогда как новый API guide описывает underlying Search/Fetch как raw JSON HTTP endpoints. [Harness `tool-web`](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/web/tool-web/src/index.ts), [DeepSeek Search & Fetch guide](https://api-docs.deepseek.com/guides/search/), [Search API reference](https://api-docs.deepseek.com/api/search/), [DeepSeek pricing and billing](https://api-docs.deepseek.com/quick_start/pricing/), [анонс периода и цены](https://api-docs.deepseek.com/news/news261017/).

Есть несовпадение официальных инструкций по Codex: новость от 17 октября говорит, что server-side Search/Fetch в Codex временно бесплатны для DeepSeek API users; отдельная инструкция интеграции Codex утверждает, что встроенный `web_search` доступен только при `deepseek-v4-pro`, а setup для `deepseek-flash` его отключает. Значит, бесплатная интеграция заявлена, но из доступной инструкции нельзя подтвердить её для Flash/Codex-конфигурации. [анонс 1017](https://api-docs.deepseek.com/news/news261017/), [Codex integration guide](https://api-docs.deepseek.com/quick_start/agent_integrations/codex/).

## 4. Что сейчас доступно агентам и сколько стоил бы перенос

- **Harness:** встроенная поверхность в `app/harness/tools.py:431–474` — shell и файловые инструменты, не Search/Fetch. Harness принимает OpenRouter-ключ, `tools`, и опциональные MCP-серверы; default pipeline указывает `mcp_servers: []` (`app/backend_harness.py:184–205`, `.orchestra/pipelines/default/pipeline.yaml:4–8`). Проекты/сессии могут добавить MCP отдельно, поэтому вывод «совсем никогда» был бы неверным. `bash` может запускать сетевые команды, если среда разрешает сеть, но это не специализированный web search tool.
- **Codex:** Orchestra явно запускает с `web_search="live"` (`app/backend_codex.py:2270–2278`). Это доступный встроенный поиск Codex, а не вызов DeepSeek API.
- **Claude:** Orchestra задаёт стандартный `claude_code` preset, `tools=None` и наследование default tool surface (`app/backend_claude.py:791–805`); отдельный DeepSeek Search/Fetch не задаёт. В инструкции DeepSeek Claude Code search включается при переключении `ANTHROPIC_BASE_URL` и `ANTHROPIC_AUTH_TOKEN` на DeepSeek API key; это переводит модельный backend Claude Code на DeepSeek, а не просто добавляет web search к текущей Claude-модели. Поэтому данное DeepSeek-обещание не относится автоматически к нынешним Claude workers на обычном Anthropic backend. [DeepSeek Claude Code integration](https://api-docs.deepseek.com/quick_start/agent_integrations/claude_code/).

Оценка только для возможного переноса в Harness: примерно 2–4 рабочих файла (схемы/исполнение инструментов, credential plumbing для DeepSeek API, тесты), ориентировочно 150–250 строк; существующий loop уже поддерживает обычный function calling. Новых зависимостей, вероятно, не требуется. Неизбежная внешняя часть — отдельный DeepSeek API key для среды/сессии; наличие такого ключа намеренно не проверялось. Цена использования после free-периода: $0.00075 за каждый успешный Search и столько же за успешный Fetch; тысяча пар search+fetch — $1.50, сверх токенов модели. Это инженерная оценка по текущей структуре, реализация не проводилась.

## Решение по пунктам

| Пункт | Брать / не брать / уже есть | Цена переноса / пользования | Основание |
|---|---|---|---|
| Маршрут Flash 1017 в Orchestra | **Не брать автоматически.** Уже открытый маршрут продолжает отвечать снимком 20260910. 1017 — отдельный платный slug, которого нет в allowlist. | 1–2 файла для переключения route/catalog и allowlist после отдельного допуска; модельная цена по OpenRouter — от $0.10/$0.50 за М input/output на перечисленных 1017 endpoints. | Три generation metadata; `app/models.py:488–496`; [OpenRouter 1017](https://openrouter.ai/deepseek/deepseek-v4.1-flash-1017). |
| 244 ток/с | **Не подтверждено.** 1017 P50 OpenRouter — 146 best provider; наши тесты сделаны на старом снимке и ниже, но единичные. | Нет переноса. | [OpenRouter 1017 stats](https://openrouter.ai/deepseek/deepseek-v4.1-flash-1017); raw probes. |
| DeepSeek Search/Fetch в Harness | **Не брать сейчас как замену всему поиску:** специализированных tools у Harness нет, но live поиск уже включён для Codex; наличие поиска зависит от Claude Code surface/runtime, а доступ к DeepSeek tools потребовал бы перевести Claude backend на DeepSeek API. Отдельная интеграция API возможна. | 2–4 файла, ~150–250 строк; нужен DeepSeek API key. С 31.10 16:00 UTC — $0.00075 за успешный запрос Search или Fetch. | `app/harness/tools.py`, pipeline `mcp_servers: []`; [DeepSeek API guide](https://api-docs.deepseek.com/guides/search/), [Claude integration](https://api-docs.deepseek.com/quick_start/agent_integrations/claude_code/). |
| Web-search у Codex | **Уже есть** через live встроенный инструмент. | $0 дополнительного переноса в Orchestra; стоимость зависит от подключённого Codex runtime/account и не выводится из тарифов DeepSeek API. | `app/backend_codex.py:2270–2278`. |
| Web-search у Claude | **Зависит от runtime;** код Orchestra не задаёт отдельную функцию поиска. Бесплатное DeepSeek Search/Fetch не действует автоматически при обычном Anthropic backend. | Нет переноса в Orchestra; для DeepSeek Search требуется отдельный API key/backend или новый Harness tool integration. | `app/backend_claude.py:791–805`; [DeepSeek Claude Code integration](https://api-docs.deepseek.com/quick_start/agent_integrations/claude_code/). |

## Материалы и ограничения

Видео 66 секунд проверено 11 кадрами; `ffprobe` обнаружил только видеопоток без аудио. На экране видна длинная задача в DeepSeek Harness с действиями по файлам/терминалу; числового токенового замера и сравнения моделей в ролике не видно.

Три endpoint-пробы — одна на каждого провайдера, один короткий запрос около 100 слов. Это проверяет фактический routing и даёт грубый ориентир, но не стабильный benchmark; только DeepInfra/StreamLake завершили запрос с видимым текстом. Цена каждого запроса и все исходные данные OpenRouter включены в raw-файл. В нём не сохранены reasoning-тексты, поскольку они не нужны для измерения скорости и не являются выводимым ответом модели.
