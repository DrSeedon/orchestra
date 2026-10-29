# V-1127 — источники и происхождение

Дата чтения всех источников: **2026-10-29 UTC**. Это исследовательские записи, не копия полных статей. Точные HTTP-время/URL/status/SHA-256 доступных тел и хеши локальных исходников — [source-observations.json](source-observations.json). Время записи файла — время сбора, не дата публикации источника. Хеш подтверждает конкретное полученное тело, но без сохранённого тела не позволяет его восстановить.

| ID | Официальная страница | Фактически прочитанные разделы / способ |
|---|---|---|
| S1 | [API credits for ChatGPT subscribers](https://developers.openai.com/api/docs/guides/chatgpt-api-credits) | Credit amounts; Eligibility; What the credits cover; When your free credits run out; More about this benefit. Web open + прямой `.md` HTTP 200; содержание согласуется |
| S2 | [Sharing feedback, evaluation and fine-tuning data, and API inputs and outputs](https://help.openai.com/en/articles/10306912-sharing-feedback-evaluation-and-fine-tuning-data-and-api-inputs-and-outputs-with-openai) | Eligibility; model groups; refresh/overage; inputs/outputs sharing. Открыт через web по старому slug, redirect на указанную страницу; web: crawled today, updated 10 days ago. Прямой curl HTTP 403 |
| S2-old | [Официальное help-lb зеркало той же статьи](https://help-lb.openai.com/en/articles/10306912-sharing-feedback-evaluation-and-fine-tuning-data-and-api-inputs-and-outputs-with-openai) | Web: crawled last month; внутри updated 5 days ago. Старые Tier 1–2/3–5, нет `gpt-6.1-sol`; основной S2 содержит Build/Launch/Grow и эту модель. Прямой curl HTTP 403 |
| S3 | [Rate limits](https://developers.openai.com/api/docs/guides/rate-limits) | Usage tiers; standard rate limits; org/project scope; spend controls. Web + прямой `.md` HTTP 200 |
| S4 | [Spend limits](https://developers.openai.com/api/docs/guides/spend-limits) | Alerts versus hard limits; enforcement propagation; error codes; monthly reset. Web + прямой `.md` HTTP 200 |
| S5 | [Function calling](https://developers.openai.com/api/docs/guides/function-calling) | Вступление с Responses-only для Astra/Sol; tool flow; Token Usage; handling outputs. Web + прямой `.md` HTTP 200 |
| S6 | [API Pricing](https://developers.openai.com/api/docs/pricing) | Tools; model token charges; separate endpoint pricing. Web + прямой `.md` HTTP 200 |
| S8 | [Prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching) | Input/cached/cache-write accounting; cached prompts and rate limits. Web + прямой `.md` HTTP 200 |
| S9 | [Data controls in the OpenAI platform](https://developers.openai.com/api/docs/guides/your-data) | Default training policy; abuse logs versus application state; ZDR. Web + прямой `.md` HTTP 200 |
| S10 | [API changelog](https://developers.openai.com/api/docs/changelog) | Oct 28 API credits announcement; Oct 26 `gpt-6.1-terra`. Web + прямой `.md` HTTP 200 |
| S11 | [ChatGPT Work admin FAQ](https://learn.chatgpt.com/docs/enterprise/work-admin-faq) | Core administrative controls / Credits: Work/Codex common allowance. Web + прямой `.md` HTTP 200 |
| S12 | [ChatGPT pricing](https://learn.chatgpt.com/docs/pricing) | Plan usage, fair use. Старый developers Codex pricing URL перенаправляет сюда; web + прямой `.md` HTTP 200 |
| S13 | [SentinelX plugin](https://openai.com/business/plugins/sentinelx/) | Developer; How it works; Work examples; availability. Web: crawled today. Прямой curl HTTP 403. Install/OAuth ссылки не активировались |

## Короткие дословные доказательства

**S1, What the credits cover, 11 слов:**

> Codex usage through API keys is not supported by this benefit.

**S2, How can I confirm..., две непересекающиеся выдержки, суммарно 19 слов:**

> You need a positive account balance to use OpenAI models and the free tokens.

> tool use are not included.

Второй фрагмент завершает общий список исключений, не определяя термин tool use. Других дословных выдержек этих источников в отчёте нет; названия моделей, параметры и числовые значения приведены как факты.

## Как читать различия снимков

`Crawled today` у web и HTTP 200 у прямого GET — разные виды наблюдений. Относительный возраст обновления внутри старого кеша не является датой обновления сегодня. Поэтому help-lb не используется для нынешних названий tiers/состава группы; S2 приоритетнее по свежести доступного web-снимка. Доказать точную дату перехода старых tiers в новые по этим двум снимкам нельзя. Подтверждён только текущий прочитанный контракт и отличие представлений.

У S1 актуальное тело независимо получено напрямую. Это новая льгота с датой анонса 28 октября в S10; прежние общие объяснения о раздельной оплате ChatGPT/API не опровергают конкретный новый грант. Предварительное сообщение родителя о Pro $100 не было сохранённым историческим снимком: из него нельзя выводить хронологию остальных сумм.

Веб-инструмент не принимал `.md` (`400 Unsupported content-type: text/markdown`); для Markdown использован обычный curl. Первоначальная обрезка changelog через `head` привела к curl 23 / закрытому stdout; последующий сборщик получил и хешировал полное тело с HTTP 200. Эти ошибки не являются ошибками API моделей.

Поиск по официальным доменам на сочетания complimentary / Responses API / function calling / tool use / cached не дал отдельного определения incentive-границы. Отрицательный поиск не доказывает отсутствие закрытых или будущих правил. Никакие аккаунтные запросы или платные эксперименты для устранения неопределённости не выполнялись.

## Локальное доказательство

Существующий [V-1122/report.md](../V-1122/report.md) прочитан как предыдущее исследование, а не свежая проверка upstream-кода SentinelX. Новая проверка касается только официальной карточки, действующих квотных документов и доступного кода Orchestra. В исходной worker-copy нет `.git`; исходный commit и состояние production не установлены. В manifest записаны только относительные repo paths и контентные хеши, не окружение или credentials.
