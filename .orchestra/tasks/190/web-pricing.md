# Тарифы ChatGPT/Codex — веб-ресёрч у первоисточника

**Дата обращения ко всем источникам: 2026-08-11.**
**Метод:** `WebSearch` → сырые источники. Официальная дока OpenAI тянулась как **markdown** (суффикс `.md` — сама страница рекламирует эту возможность), а не через `WebFetch`, поэтому цитаты ниже дословные. `help.openai.com` и `chatgpt.com` отдают 403 на `curl` И на `WebFetch` (Cloudflare, «Enable JavaScript and cookies to continue») — они читались через текстовый прокси `r.jina.ai`, это помечено у каждого источника.

---

## Главный ответ (для решения юзера)

**Рабочий вариант за $20 существует.** ChatGPT Plus ($20/мес) даёт `codex` CLI, `codex exec` и модель **GPT-5.6 Sol** — то есть ровно то, на чём стоит наш `codex_review`. Это подтверждено матрицей доступности функций на официальной странице (см. п.2).

**Что теряется при переходе $100 → $20:**
1. **GPT-5.3-Codex-Spark пропадает совсем.** Он Pro-only, это записано в доке двумя независимыми местами. Наш роутинг Spark как «быстрый leaf-worker» перестанет существовать физически.
2. **Объём падает ровно в 5 раз** (10–100 сообщений Sol / 5h против 50–500).

---

## 1. Полная линейка тарифов ChatGPT на 11.08.2026

Источник [1] — официальная страница Codex Pricing, дословно из карточек тарифов (`PricingCard`):

| Тариф | Цена (дословно) | Подзаголовок в доке |
|---|---|---|
| Free | `$0 /month` | «Explore Codex capabilities on quick coding tasks.» |
| Go | `$8 /month` | «Use Codex for lightweight coding tasks.» |
| Plus | `$20 /month` | «Power a few focused coding sessions each week.» |
| Pro | `From $100 /month` | «Choose 5x or 20x higher rate limits than Plus.» |
| Business | `$20 / user / month*` | сноска: «*2+ users, billed annually. $25 per user per month when billed monthly.» |
| Enterprise & Edu | цена не указана, `Contact sales` | — |
| API Key | цена не указана | «Great for automation in shared environments like CI.» |

**Отдельной подписки «Codex» не существует.** Дословно, подзаголовок страницы [1]:

> ChatGPT Work and Codex are included in your ChatGPT Free, Go, Plus, Pro, Business, Edu, or Enterprise plan

Второй независимый первоисточник [3]:

> Codex is included across ChatGPT plans, including Free and Go. Usage limits vary by plan.

**Pro — это два тарифа под одним именем**, $100 (5x) и $200 (20x). Дословно из карточки Pro [1]:

> - Access to GPT-5.3-Codex-Spark (research preview), a fast Codex model for day-to-day coding tasks
> - 5x or 20x more Codex usage than Plus*
> - Unlimited ChatGPT Voice on the $200/month tier; tasks still draw from your Codex usage budget

Тариф Pro $100 запущен **9 апреля 2026** [6, вторичный]:

> The $100 Pro plan delivers "5x more Codex than the Plus plan"

---

## 2. Кто даёт доступ к Codex CLI и к GPT-5.6 Sol

Это самый важный пункт задачи. Источник [1], раздел **Feature availability** — матрица «функция × тариф». Она отрисована иконками (SVG-галочка / прочерк), поэтому извлекалась из сырого HTML с подстановкой маркера вместо `<svg>`. Ниже — что реально стоит в ячейках (`✓` = галочка, `—` = прочерк в источнике):

| Feature (дословно) | ChatGPT Plus | ChatGPT Pro | Business | Enterprise/Edu | API Key |
|---|---|---|---|---|---|
| Codex cloud | ✓ | ✓ | ✓ | ✓ | — |
| ChatGPT Work on the web | ✓ | ✓ | ✓ | ✓ | — |
| ChatGPT desktop app for local chats | ✓ | ✓ | ✓ | ✓ | ✓ |
| **Codex CLI** | **✓** | ✓ | ✓ | ✓ | ✓ |
| IDE extension | ✓ | ✓ | ✓ | ✓ | ✓ |
| **Codex SDK, `codex exec`, and scriptable workflows** | **✓** | ✓ | ✓ | ✓ | ✓ |
| Codex access tokens for trusted automation | — | — | ✓ | ✓ | — |
| ChatGPT for Excel | ✓ | ✓ | ✓ | ✓ | — |
| **GPT-5.6** | **✓** | ✓ | ✓ | ✓ | ✓ |
| Fast mode | ✓ | ✓ | ✓ | ✓ | ✓ |
| **Codex-Spark research preview** | **—** | **✓** | **—** | **—** | **—** |
| Image generation and editing | ✓ | ✓ | ✓ | ✓ | ✓ |
| Voice dictation | ✓ | ✓ | ✓ | ✓ | — |
| ChatGPT Voice | ✓ | ✓ | ✓ | ✓ | — |

**Вывод по п.2:** да, тариф за $20 с рабочим `codex` CLI и моделью codex-класса существует. Карточка Plus перечисляет это же словами [1]:

> - Codex on the web, in the CLI, in the IDE extension, and on iOS
> - Cloud-based integrations like automatic code review and Slack integration
> - The GPT-5.6 model family, including Sol, Terra, and Luna
> - GPT-5.6 Luna for higher usage limits on lighter-weight or high-volume workloads
> - Flexibly extend usage with ChatGPT credits

**Spark — Pro-only, подтверждено дважды в одном первоисточнике** (матрица выше + отдельный абзац) [1]:

> GPT-5.3-Codex-Spark is in research preview for ChatGPT Pro users only, and isn't available in the API at launch. Because it runs on specialized low-latency hardware, usage is governed by a separate usage limit that may adjust based on demand.

Отдельно про `codex exec` под API-ключом [2] — это НЕ подписочный путь и стоит по API-тарифу:

> When you sign in with an API key, Codex uses standard API pricing instead of included ChatGPT plan credits.
> Use API key authentication for programmatic Codex CLI workflows, such as CI/CD jobs.

---

## 3. Лимиты по тарифам: что OpenAI публикует в проверяемом виде

**Публикует:** диапазоны сообщений на **пятичасовое окно**, по моделям. **НЕ публикует:** ни одного числа для **недельного** лимита.

Дословная сноска, повторённая под КАЖДОЙ из пяти таблиц на странице [1]:

> *The usage limits for local messages and cloud chats share a five-hour window. Additional weekly limits may apply. For Enterprise/Edu users with flexible pricing, there are no fixed rate limits - usage scales with credits. Enterprise and Edu plans without flexible pricing have the same per-seat usage limits as Plus for most features

Таблицы (колонка **Local Messages / 5h** — это CLI; колонки *Cloud chats* и *Code Reviews* в источнике заполнены значением `Not available` для всех моделей и всех тарифов, включая Pro 20x — выглядит как дефект страницы, но воспроизводится и в HTML, и в `.md`, поэтому привожу как есть):

| Модель | Plus | Pro 5x | Pro 20x | Business | API Key |
|---|---|---|---|---|---|
| GPT-5.6 Sol | 10-100 | 50-500 | 200-2,000 | 10-100 | Usage-based |
| GPT-5.6 Terra | 25-200 | 125-1,000 | 500-4,000 | 25-200 | Usage-based |
| GPT-5.6 Luna | 250-2,000 | 1,250-10,000 | 5,000-40,000 | 250-2,000 | Usage-based |
| GPT-5.5 | 15-80 | 75-400 | 300-1600 | 15-80 | Usage-based |
| GPT-5.4 | 20-100 | 100-500 | 400-2000 | 20-100 | Usage-based |
| GPT-5.4 mini | 60-350 | 300-1750 | 1200-7000 | 60-350 | Usage-based |

Соотношения сходятся с маркетингом: Pro 5x = ровно 5× Plus, Pro 20x = ровно 20× Plus. **Business по лимитам равен Plus.** Free и Go в таблицах вообще отсутствуют — своих чисел для них OpenAI не даёт.

**Числа — не гарантия, и дока это прямо оговаривает** [1]:

> The number of messages you can send depends on the model used, size and complexity of your tasks, and whether you run them locally or in the cloud. Small scripts or routine functions may consume only a fraction of your allowance, while larger projects, long-running tasks, or extended sessions that require the agent to hold more context will use significantly more per message.
> Tasks that look similar can consume different amounts of your allowance. Model choice, context, reasoning, tool use, retrieval, and caching all affect usage, so prompt length alone isn't a reliable estimate.

### ⚠️ Эти числа протухают за недели — замер по нашему же репозиторию

Наш `docs/tasks/codex-limits-abuse/research.md:54` (проверка 18.07.2026) записал для **Pro 5x**: `GPT-5.6 Sol 75–450`. Сегодня, 11.08.2026, та же таблица того же URL даёт `50-500`. **Изменилось за 24 дня**, вниз по нижней границе и вверх по верхней. Аналогично Terra: было `100–550`, стало `125-1,000`; Luna: было `250–1400`, стало `1,250-10,000`.

Практический вывод: любое решение, опирающееся на конкретное число из этой таблицы, надо перепроверять перед оплатой. У страницы [1] **даты обновления не опубликовано** — я её не нашёл ни в HTML, ни в markdown-версии.

### Что происходит при исчерпании

Дословно [1]:

> We want you to be able to complete work already in progress. If you reach your usage limits during an active turn, the agent will be able to continue working on that turn, subject to fair use limits.
> ChatGPT Plus and Pro users who reach their usage limit can purchase additional credits to continue working without needing to upgrade their existing plan.
> If you are approaching usage limits, you can also switch to a smaller model to make your usage limits last longer.
> All users may also run extra local chats using an API key, with usage charged at standard API rates.

### Общий пул — важно для нашего кейса

> Usage limits are shared with other agentic features once pricing for those features is effective. This currently includes ChatGPT for Excel on Plus and Pro. [1]

> Usage from Codex, ChatGPT Work, ChatGPT for Excel, and Workspace Agents draws from the same agentic usage and credit pool when those features are available on your plan. [3]

---

## 4. `plan_type: "prolite"` — что это

**Ответ: `prolite` = ChatGPT Pro $100/мес (тариф «Pro 5x»). Уверенность высокая.** `pro` в том же перечислении — это Pro $200 (20x). Это два разных значения, оба означающие «Pro», различающиеся множителем.

Доказательства, от сильного к слабому:

**(а) Исходники Codex.** PR [openai/codex#17419](https://github.com/openai/codex/pull/17419) «Support prolite plan type», создан 2026-04-11T03:36:51Z, **смержен 2026-04-11T20:58:16Z**. Дословно из body PR [7]:

> Problem: Codex rate-limit fetching failed when the backend returned the new `prolite` subscription plan type.
> Solution: Add `prolite` to the backend/account/auth plan mappings, keep unknown WHAM plan values decodable, and regenerate app-server plan schemas.

Дословно из диффа (`codex-rs/app-server-protocol/schema/json/ServerNotification.json` и ещё 5 файлов схем, правка идентична):

```diff
         "go",
         "plus",
         "pro",
+        "prolite",
         "team",
         "self_serve_business_usage_based",
         "business",
```

То есть `prolite` — **отдельное от `pro` значение enum'а**, добавленное задним числом. Дата мержа (11.04.2026) — через два дня после запуска тарифа Pro $100 (09.04.2026 [6]).

**(б) Наблюдение смены тарифа на живом аккаунте.** [openai/codex#21216](https://github.com/openai/codex/issues/21216) [8, читан через WebFetch → пересказ, не дословно]: у репортёра `plan_type` сменился `pro` → `prolite` 5 мая 2026 между 16:44:41 и 16:45:12 BST при **даунгрейде Pro 20x → Pro 5x**, и вернулся в `pro` при восстановлении Pro 20x. Это ровно то соответствие, которое я утверждаю.

**(в) Утечка до запуска.** До анонса в коде checkout-страницы OpenAI нашли тариф «Pro Lite» за $100/мес под идентификаторами `PROLITE` / `chatgptprolite` [9, вторичный].

**(г) Побочное подтверждение, что строка новая и ломала клиентов:** [openai/codex#18805](https://github.com/openai/codex/issues/18805) (21.04.2026), Codex CLI 0.121.0 — app-server отвергал собственный аккаунт:

> Codex app-server provider probe failed: Invalid account/read payload: Expected "free" | "go" | "plus" | "pro" | "team"…

со списком принимаемых значений `"free", "go", "plus", "pro", "team", "self_serve_business_usage_based", "business", "enterprise_cbp_usage_based", "enterprise", "edu", "unknown"` — без `prolite`.

**Оговорка.** В официальной документации OpenAI строка `prolite` **не встречается вообще** — я её не нашёл ни на одной странице `learn.chatgpt.com`. Это внутренний идентификатор биллинга, а не публичный контракт; наш `/api/usage` читает его из ответа бэкенда. Вывод «prolite = Pro $100» держится на исходниках Codex + наблюдении даунгрейда, и он согласуется с нашим фактическим тарифом ($100/мес). Отдельно: наш `/api/usage` отдаёт `prolite` и для spark — это ожидаемо, `plan_type` описывает **аккаунт**, а не модель.

---

## 5. Credits / pay-as-you-go

**Докупать лимиты Codex поверх Plus ($20) можно — это официально поддерживаемый путь.** Дословно [4] (заголовок статьи: «Using Credits for Flexible Usage in ChatGPT (Free/Go/Plus/Pro)», **Updated: 15 hours ago** на момент обращения):

> We're adding the ability for you to purchase credits when you reach your plan's included limits, without the need to upgrade your plan. Credits currently can only be used with Codex (for Plus/Pro users only) and ChatGPT for Excel.

> Your plan's included usage is used first. After you hit plan limits, usage draws from your credit balance.

> If you hit a usage limit in Codex on Plus or Pro, you'll see an option to add credits. You can also buy credits from **Codex Settings > Usage > Credits** on both web and the Codex app.

Есть авто-пополнение:

> Eligible Plus and Pro users can also turn on Auto top-up from **Codex Settings > Usage**. When your credit balance drops below your selected minimum balance, we automatically purchase only the amount needed to return it to your selected target balance using your default payment method on file.

Условия:

> Credits are non-refundable, except where required by law.
> Credits are valid for 12 months from purchase. Unused credits expire and do not roll over after the expiry date.
> Credits are non-transferable, have no cash value, and cannot be resold or gifted.

### Rate card — сколько кредитов ест модель (дословно [1])

| Credits per 1M tokens | Input | Cached input | Output |
|---|---|---|---|
| GPT-5.6 Sol | 125 credits | 12.5 credits | 750 credits |
| Daybreak Blue | 125 credits | 12.5 credits | 750 credits |
| Daybreak Red | 312.5 credits | 31.25 credits | 1875 credits |
| GPT-5.6 Terra | 50 credits | 5 credits | 300 credits |
| GPT-5.6 Luna | 5 credits | 0.5 credits | 30 credits |
| GPT-5.5 | 125 credits | 12.50 credits | 750 credits |
| GPT-5.4 | 62.50 credits | 6.250 credits | 375 credits |
| GPT-5.4 mini | 18.75 credits | 1.875 credits | 113 credits |
| GPT-5.3-Codex-Spark | research preview *(ставки не опубликованы)* | | |
| GPT-Image-2 (image) | 200 credits | 50 credits | 750 credits |
| GPT-Image-2 (text) | 125 credits | 31.25 credits | 250 credits |

> GPT-5.6 usage averages 5-40 credits per message. Fast mode consumes credits at a higher rate for supported models. [1]

Отметить: **cached input в 10 раз дешевле input** (12.5 против 125 у Sol). Для нас это существенно — по замеру #178 68% нашего расхода это `cache_read`.

### 🔴 Чего OpenAI НЕ публикует: цену кредита в долларах

Я проверил три первоисточника — страницу Pricing [1], статью про кредиты [4] и Codex rate card [5]. **Ни на одной нет цены кредита в $.** Rate card [5] говорит только:

> Codex usage is priced based on API token usage, calculated as credits per million input tokens, cached input tokens, and output tokens.

То есть публично известно, сколько кредитов ты потратишь, но не сколько стоит кредит — цена видна только в самом интерфейсе покупки (`Codex Settings > Usage > Credits`). Вторичные обзоры называют **≈$0.04 за кредит**, но это блоги, я это первоисточником не подтвердил и цифру рекомендую не использовать для расчётов, пока кто-нибудь не откроет экран покупки в аккаунте.

**Про наши поля.** `credits: {has_credits: false, unlimited: false, balance: "0"}` читается как «кредиты не подключены, баланс нулевой» — то есть мы сейчас живём строго на включённом в тариф объёме. `reset_credits: 1` по смыслу совпадает не с кредитами-деньгами, а с **banked rate-limit reset** — отдельной сущностью из реферальной программы [1]:

> From June 11 through June 24, 2026, eligible Plus and Pro users can invite up to three friends. When an eligible recipient sends their first Codex message, both people receive a banked rate-limit reset. Banked rate-limit resets are usable for 30 days after they're granted.

И [3]:

> To use a banked reset, open the profile menu and select the usage summary showing the available reset count, such as **1 reset available**.
> Using a full banked reset resets both your 5-hour and weekly usage windows. As a result, your weekly reset date will move to roughly seven days after you redeem it.

`reset_credits: 1` ↔ «1 reset available» — совпадение точное по формулировке, но это **моя интерпретация по смыслу, а не подтверждённое соответствие поля**: официальной спецификации ответа `/backend-api/wham/usage` OpenAI не публикует. Если это так — у нас лежит неиспользованный сброс обоих окон, включая недельное.

---

## Сводная таблица

| Тариф | Цена | Codex CLI / `codex exec` | GPT-5.6 Sol | Codex-Spark | Sol сообщений / 5h | Недельный лимит | Докупка кредитов | Источник |
|---|---|---|---|---|---|---|---|---|
| Free | $0 | ✓ (Codex включён) | ✓ | — | не опубликовано | не опубликован | нет (только Plus/Pro) | [1][3][4] |
| Go | $8 | ✓ (Codex включён) | ✓ | — | не опубликовано | не опубликован | нет (только Plus/Pro) | [1][3][4] |
| **Plus** | **$20** | **✓** | **✓** | **—** | **10-100** | «may apply», чисел нет | **✓** | [1][4] |
| Pro 5x (`prolite`) | $100 | ✓ | ✓ | ✓ | 50-500 | «may apply», чисел нет | ✓ | [1][4][7] |
| Pro 20x (`pro`) | $200 | ✓ | ✓ | ✓ | 200-2,000 | «may apply», чисел нет | ✓ | [1][4][7] |
| Business | $20/юзер (год) или $25/мес, от 2 мест | ✓ | ✓ | — | 10-100 | «may apply», чисел нет | ✓ (workspace credits) | [1] |
| Enterprise/Edu | Contact sales | ✓ | ✓ | — | с flexible pricing — «no fixed rate limits»; без него = как Plus | — | ✓ (workspace credits) | [1] |
| API Key | по API-тарифу | ✓ | ✓ | — | Usage-based | нет | n/a | [1][2] |

---

## Чего выяснить НЕ удалось

1. **Цена кредита в долларах.** Не опубликована ни на одном из трёх проверенных первоисточников [1][4][5]. Видна только на экране покупки в аккаунте. Вторичная оценка ≈$0.04/кредит не подтверждена.
2. **Любые числа недельного лимита.** OpenAI ограничивается формулировкой «Additional weekly limits may apply» под каждой из пяти таблиц. Ни для одного тарифа, ни для одной модели чисел нет. Не опубликован и алгоритм сброса (rolling vs calendar).
3. **Лимиты Free и Go.** Эти тарифы есть в карточках цен и в [3], но в таблицах лимитов их строк нет вообще.
4. **Ставки кредитов для GPT-5.3-Codex-Spark.** В rate card строка есть, но вместо чисел стоит «research preview». Плюс отдельная оговорка [1]: «usage is governed by a separate usage limit that may adjust based on demand» — то есть Spark и не считается по общей таблице.
5. **Дата обновления страницы Pricing [1].** Ни в HTML, ни в markdown-версии её нет. Для help-статей дата есть и она свежая ([4] — 15 часов, [3] — 2 дня на момент обращения).
6. **Сколько «local messages» съедает один наш `codex_review`.** Дока прямо говорит, что сообщения не равны запросам и расход зависит от токенов/контекста/tool use. Пересчитать «10–100 сообщений Plus» в «N ревью» по докам нельзя — это надо мерить на своём аккаунте через `/status` или usage dashboard.
7. **Официальное подтверждение `prolite` = Pro $100 от OpenAI.** Строка отсутствует в документации целиком; вывод построен на исходниках Codex и наблюдении даунгрейда (см. п.4).
8. **`chatgpt.com/pricing` (общая витрина тарифов ChatGPT, не Codex).** Отдаёт 403 и на `curl`, и на `WebFetch`. Линейка выше взята с Codex-страницы [1], которая перечисляет те же тарифы; отдельные не-Codex фичи Plus/Pro я не проверял.

---

## Источники

Все открыты **11.08.2026**. Тир помечен: **[Первоисточник]** = страница OpenAI или исходники openai/codex; **[Вторичный]** = пресса/блог.

1. **[Первоисточник]** OpenAI — Codex Pricing. Тарифные карточки, таблицы лимитов на 5h, rate card в кредитах, матрица Feature availability, реферальная программа.
   https://learn.chatgpt.com/docs/pricing — читалось как https://learn.chatgpt.com/docs/pricing.md (57 241 байт markdown) + сырой HTML (661 633 байта) для матрицы Feature availability, отрисованной иконками. Дата обновления страницы не указана.
2. **[Первоисточник]** OpenAI — Codex Authentication. Sign in with ChatGPT vs API key, «standard API pricing instead of included ChatGPT plan credits».
   https://learn.chatgpt.com/docs/auth — читалось как https://learn.chatgpt.com/docs/auth.md (15 024 байта).
3. **[Первоисточник]** OpenAI Help Center — Using Codex with your ChatGPT plan. «Codex is included across ChatGPT plans, including Free and Go», общий agentic-пул, banked reset. **Updated: 2 days ago.**
   https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan — прямой доступ 403 (Cloudflare), читалось через `r.jina.ai`.
4. **[Первоисточник]** OpenAI Help Center — Using Credits for Flexible Usage in ChatGPT (Free/Go/Plus/Pro). Кредиты только для Plus/Pro, auto top-up, срок годности 12 месяцев, невозвратность. **Updated: 15 hours ago.**
   https://help.openai.com/en/articles/12642688 — прямой доступ 403, читалось через `r.jina.ai`.
5. **[Первоисточник]** OpenAI Help Center — Codex rate card. Подтверждает токенную модель тарификации; цены кредита в $ не содержит.
   https://help.openai.com/en/articles/20001106-codex-rate-card — прямой доступ 403, читалось через `r.jina.ai`.
6. **[Вторичный]** TechCrunch, публикация **2026-04-09** — запуск тарифа Pro $100/мес, «5x more Codex than the Plus plan».
   https://techcrunch.com/2026/04/09/chatgpt-pro-plan-100-month-codex/ — читалось через `WebFetch` (пересказ, цитата приведена как процитированная инструментом).
7. **[Первоисточник / исходники]** openai/codex PR #17419 «Support prolite plan type». Создан 2026-04-11T03:36:51Z, смержен 2026-04-11T20:58:16Z. Дифф и body получены напрямую: `https://github.com/openai/codex/pull/17419.diff` и GitHub REST API.
   https://github.com/openai/codex/pull/17419
8. **[Первоисточник / issue, анекдот]** openai/codex issue #21216 — `plan_type` меняется `pro` ↔ `prolite` при даунгрейде Pro 20x → Pro 5x (05.05.2026). Читалось через `WebFetch`, то есть **пересказ, не дословно**.
   https://github.com/openai/codex/issues/21216
9. **[Первоисточник / issue]** openai/codex issue #18805 (21.04.2026, CLI 0.121.0) — app-server отвергал `planType = "prolite"`; в тексте ошибки полный список допустимых значений enum без `prolite`. Читалось через `WebFetch`.
   https://github.com/openai/codex/issues/18805
10. **[Вторичный]** Пред-анонсная находка тарифа «Pro Lite» $100/мес в коде checkout-страницы OpenAI (февраль 2026), идентификаторы `PROLITE` / `chatgptprolite`. Известно из выдачи `WebSearch`; **саму страницу я не открывал**, поэтому цитата не приводится и факт помечен как слабый.
11. **[Внутренний]** Наш собственный `docs/tasks/codex-limits-abuse/research.md:54`, проверка 18.07.2026 — для сравнения с сегодняшними числами (Pro 5x Sol было 75–450, стало 50-500).
