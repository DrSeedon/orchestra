# Исследование: лимиты ChatGPT/Codex, обходы и риски

**Дата проверки:** 2026-07-18
**Контекст:** ChatGPT Pro $100/мес (5× Codex tier), Codex CLI 0.144.5 с ChatGPT-auth; отдельно используется ChatGPT Plus. Официально отдельной подписки «Codex Pro» нет: Codex включён в ChatGPT Plus/Pro [1][6].
**Статус:** Phase 1 research. Это техническая и договорная оценка, не юридическая консультация.

## Вывод для нас

1. **`codex exec` с ChatGPT-auth — штатный и низкорисковый в части quota rules способ использовать включённый в подписку Codex.** Это не перенос «безлимитного ChatGPT-чата» в CLI: CLI расходует **Codex/agentic pool**, общий с ChatGPT Work и некоторыми другими agentic-функциями, но не с обычными текстовыми чатами ChatGPT [1][2]. Географический и account-security риски оцениваются отдельно.
2. **Codex Pro 5× не безлимитный.** Для локальных задач OpenAI публикует ориентиры на одно пятичасовое окно: Sol 75–450, Terra 100–550, Luna 250–1400, GPT-5.5 75–400, GPT-5.4 100–500, GPT-5.4 mini 300–1750 сообщений. Это диапазоны, а не гарантированные request counts: фактический расход зависит от токенов, модели, reasoning, контекста, tool use, retrieval и caching [1][3].
3. **Абсолютный weekly cap публично не указан.** Документация говорит лишь, что дополнительные недельные лимиты могут применяться [1]. Наш штатный `account/rateLimits/read` трижды подряд показал основной отдельный 7-дневный bucket (`10080` минут) и отдельный 7-дневный Spark bucket, но не раскрыл абсолютное число сообщений или токенов.
4. **ChatGPT Plus не даёт неограниченный доступ к одной и той же старшей модели.** Для GPT-5.5 Instant опубликовано до 160 сообщений за 3 часа, затем включается mini fallback; для manually selected reasoning текущая GPT-5.6 docs говорит об отдельной allowance и fallback, но не публикует универсальное число. Маркетинговое `Unlimited* messages and interactions` означает, что общение не обрывается полностью, но конкретные модели и инструменты имеют caps/fallbacks [4][5][6].
5. **ChatGPT Pro действительно заявляет unlimited-доступ к части GPT-5-моделей, но с abuse guardrails и отдельными model allowances.** Codex при этом остаётся отдельным ограниченным продуктовым пулом. Публичного поддерживаемого флага, который направляет стандартную text-chat quota в Codex CLI, нет [1][6][7].
6. **API-key auth — не обход, а другой коммерческий контур.** `codex exec` с API key использует Platform API, стандартные API цены и лимиты организации (RPM/TPM), а не включённый подписочный Codex pool [2].
7. **Наибольший договорный риск дают не CLI и автоматизация сами по себе, а намеренный обход:** round-robin аккаунтов для преодоления cap, шаринг credentials, browser-session/token relays, перепродажа доступа и настройка маршрута специально для обхода rate limits. Terms прямо запрещают обход rate limits/restrictions; OpenAI указывает temporary restriction, suspension и deactivation как возможные последствия [7][8][9].
8. **Для нашей инфраструктуры есть отдельный географический риск:** Россия отсутствует в текущем списке поддерживаемых стран, а OpenAI предупреждает, что доступ из неподдерживаемой страны может привести к блокировке или приостановке аккаунта [10]. Это отдельный риск от quota abuse и он существует даже при корректном ChatGPT-auth.

## Вопрос и критерий ответа

- **Контекст:** официальный Codex CLI, ChatGPT consumer subscriptions и OpenAI Platform API.
- **Изменение под проверкой:** попытка получить больше Codex capacity через ChatGPT-auth, альтернативный backend, конфиги или дополнительные аккаунты.
- **Baseline:** штатный `codex login` с одним личным ChatGPT-аккаунтом и соблюдением отображаемых Codex limits.
- **Измеримый результат:** какой quota/billing pool реально уменьшается; какие окна возвращает официальный client protocol; есть ли публично поддерживаемый маршрут к обычной text-chat quota; какие действия прямо запрещены договором или подтверждённо вызывают enforcement.

## Гипотезы и фальсификаторы

### H1 — штатный ChatGPT-auth расходует отдельный Codex/agentic pool

**Гипотеза:** `codex exec` с ChatGPT OAuth расходует Codex/agentic allowance подписки, потому что Codex — отдельная включённая поверхность ChatGPT plan.
**Что опровергло бы:** официальный документ или измерение, показывающее, что CLI уменьшает обычный GPT-5.5 Instant/Thinking message cap стандартного ChatGPT-чата.

**Вердикт: CONFIRMED.** Authentication docs отделяют subscription access от API usage; Codex docs называют общий pool только для Codex, ChatGPT Work, ChatGPT for Excel и Workspace Agents [1][2]. Help Center отдельно говорит, что file/image/voice limits ChatGPT к Codex не относятся [11]. В исходниках это также разные ветви: ChatGPT-backed modes возвращают `uses_codex_backend() == true`, а `ApiKey` — false [28].

### H2 — существует поддерживаемый CLI-флаг, переключающий Codex на «безлимитный» text-chat pool

**Гипотеза:** auth/backend flag может направить `codex exec` в стандартный ChatGPT text backend и использовать его unlimited quota.
**Что опровергло бы:** исходники и reference показывают только два официальных OpenAI auth routes — ChatGPT subscription Codex и usage-based API — без третьего quota route.

**Вердикт: REFUTED для поддерживаемого продукта.** Публичный Codex поддерживает ChatGPT-auth и API-key auth. `chatgpt_base_url` относится к ChatGPT auth flow; custom model providers требуют собственную provider/auth-конфигурацию и не превращают text-chat allowance в Codex allowance [2][12]. В текущем CLI нет ветви, которая конвертирует ChatGPT bearer token в API key или entitlement стороннего provider [28][29]. Неофициальные browser-token relays могут технически эмулировать web traffic, но это уже не поддерживаемая поверхность и не доказательство отдельного легального pool.

### H3 — несколько аккаунтов сами по себе запрещены

**Гипотеза:** наличие двух личных/рабочих аккаунтов нарушает правила.
**Что опровергло бы:** официальный account switcher, разрешающий отдельные аккаунты и независимые subscriptions/workspaces.

**Вердикт: REFUTED в общей форме, но риск зависит от цели.** OpenAI Help Center поддерживает переключение между отдельными personal/work accounts [13]; это policy-supported возможность, а не безусловный договорный safe harbor. Использование аккаунтов как quota sharding именно для преодоления cap **с высокой вероятностью будет классифицировано** как запрещённое circumventing rate limits [7]. Это правовая оценка по цели и фактам схемы, а не опубликованное case-level решение OpenAI.

## 1. Конкретные лимиты Codex

### Pro $100 / 5× tier — публичный snapshot на 2026-07-18

| Модель | Ориентир local messages / 5h | Относительная стоимость по token rate card |
|---|---:|---:|
| GPT-5.6 Sol | 75–450 | 125 input / 12.5 cached / 750 output credits за 1M токенов |
| GPT-5.6 Terra | 100–550 | 62.5 / 6.25 / 375 |
| GPT-5.6 Luna | 250–1400 | 25 / 2.5 / 150 |
| GPT-5.5 | 75–400 | 125 / 12.5 / 750 |
| GPT-5.4 | 100–500 | 62.5 / 6.25 / 375 |
| GPT-5.4 mini | 300–1750 | 18.75 / 1.875 / 113 |

Диапазоны дословно взяты из текущей pricing docs для **Pro 5×** [1]. Это датированный публичный snapshot, который OpenAI может изменить. С апреля 2026 года расход Codex выражается через input/cached/output token rates, поэтому одинаковое число пользовательских prompts может потратить существенно разную долю окна [3]. «75–450 сообщений» — оценка числа типичных задач внутри shared 5h allowance, а не обещанный математический cap на 75 или 450 HTTP requests.

### Какие окна общие и какие отдельные

- Local messages и доступные cloud chats делят пятичасовое окно; дополнительно может применяться weekly limit [1].
- Codex, ChatGPT Work, ChatGPT for Excel и Workspace Agents используют общий agentic allowance/credit pool, когда функция доступна на плане [11].
- GPT-5.3-Codex-Spark имеет **отдельный dynamic limit**, который OpenAI может менять в зависимости от спроса; числовой публичной нормы для него нет [1].
- Fast mode расходует credits быстрее; выбор более дешёвой модели увеличивает число типичных задач в том же allowance [1][3].

### Что известно о weekly limit

Публичной таблицы вида «N токенов или N сообщений в неделю» нет ни для одной перечисленной Codex-модели на Plus, Pro 5× или Pro 20×. Не опубликованы также алгоритм rolling/calendar reset и гарантированное наличие одинакового weekly bucket у всех accounts. Официальная формулировка ограничивается `Additional weekly limits may apply` [1]. Поэтому конкретное абсолютное число из Reddit/GitHub без account telemetry нельзя считать универсальным лимитом.

Наше прямое измерение 2026-07-18:

```text
codex-cli 0.144.5
Logged in using ChatGPT
model = "gpt-5.3-codex-spark"

3/3 account/rateLimits/read:
plan_type=prolite
codex: 48% used, window=10080 min, reset=2026-07-25T05:24:40Z
codex_bengalfox (Spark): 13% used, window=10080 min,
                         reset=2026-07-25T07:20:42Z
credits: has_credits=false, unlimited=false, balance=0
banked full resets: 2
secondary window: null
```

**Интерпретация:** три запроса в одном окне наблюдения вернули серверное состояние с 7-дневным общим Codex bucket и отдельным Spark bucket [18]. Это не доказывает calendar-week reset, rolling algorithm или универсальность такого представления для других accounts. Snapshot не показывает абсолютную capacity и в этот момент не вернул 5h window. Это также **не доказывает**, что пятичасовой enforcement отсутствует: публичная документация всё ещё описывает пятичасовое окно, а app-server snapshot может отражать только активные/применимые entitlement windows. Конфликт следует сохранять как наблюдение, а не «исправлять» догадкой.

## 2. Лимиты обычного ChatGPT

### ChatGPT Plus

- GPT-5.5 Instant: до 160 сообщений за 3 часа; после cap чат переключается на Instant mini до reset [4].
- Вручную выбранный GPT-5.6 Sol использует отдельную reasoning allowance; текущая статья не даёт одного универсального числа для Plus, а при исчерпании ChatGPT может продолжить на Thinking mini [4].
- Общий Help Center предупреждает, что Plus caps могут меняться вместе с нагрузкой и rollout [14].

Следовательно, **«безлимитный текст» на Plus — маркетинговая характеристика непрерывности сервиса, а не безлимитный доступ к фиксированной frontier model**. После model cap обычно остаётся fallback, поэтому пользователь может продолжать чат, но это не переносимый pool для Codex.

### ChatGPT Pro $100/$200

OpenAI описывает GPT-5 access на Pro как unlimited subject to abuse guardrails, но одновременно предупреждает, что отдельные модели, включая Pro-model, имеют самостоятельные allowances, различающиеся для 5× и 20× tiers [6][7]. При исчерпании отдельной allowance модель временно недоступна или происходит fallback; подписка не прекращается [6].

Codex остаётся явно ограниченным: $100 Pro даёт 5× Codex usage относительно Plus, $200 Pro — 20× [1][6]. Поэтому «Pro text is unlimited» не означает «Codex is unlimited».

## 3. ChatGPT-auth, API auth и поверхности Codex

### `codex exec` с ChatGPT-auth

- `codex login` с browser/device flow — официальный путь subscription access [2].
- CLI, IDE extension и desktop Codex переиспользуют сохранённый login; logout в одной локальной поверхности очищает общий cached login [2].
- `codex exec` переиспользует этот login по умолчанию [2].
- OpenAI отдельно документирует advanced ChatGPT-managed auth для trusted private CI runners, когда нужны именно ChatGPT/Codex subscription limits; cached auth нужно хранить как password и не использовать этот workflow для public/open-source runners [27].
- Разные Codex surfaces не создают независимые allowances: расход учитывается на account/workspace product pool [1][11].

### `codex exec` с API key

- `codex login --with-api-key` или scoped `CODEX_API_KEY` для одного `codex exec` переключают запрос на Platform API [2].
- Usage оплачивается по API pricing; применяются API-org/project RPM, TPM и spend limits, а не пятичасовой/недельный ChatGPT subscription allowance [2].
- Это поддерживаемый способ продолжать автоматизацию после ручного переключения auth domain, но он создаёт реальный pay-as-you-go расход. Нативного автоматического handoff не обнаружено; API key не «разблокирует» подписку.

### «ChatGPT backend вместо Codex backend»

В официальной архитектуре ChatGPT OAuth уже направляет Codex к ChatGPT-managed Codex service; API key направляет его к Platform Responses API. В CLI нет документированного режима `use ordinary ChatGPT text quota`. `chatgpt_base_url` — override login endpoint, а `model_provider`/`model_providers` — подключение другого Responses-compatible provider с его собственной авторизацией [12].

Практическое следствие: конфиг, который меняет URL или проксирует browser cookies/access tokens для эмуляции стандартного ChatGPT web, не открывает поддерживаемую третью surface. Он создаёт неофициальный credential relay с рисками утечки, account sharing, автоматического извлечения и обхода ограничений.

### Что реально делает CLI 0.144.5

Статический аудит исходников на commit `56395bddaf26eb2829387ca6a417bf9128e5b239`, дополненный локальными auth/help checks CLI 0.144.5, показал auth-selected маршруты ниже. Это вывод из commit-pinned source, не packet capture; user-level provider config может изменить фактический destination.

| Операция | ChatGPT/backend auth | API-key auth |
|---|---|---|
| Model response | `POST https://chatgpt.com/backend-api/codex/responses` | `POST https://api.openai.com/v1/responses` |
| Model catalog | `GET https://chatgpt.com/backend-api/codex/models` | API model catalog, если выбран соответствующий provider |
| Subscription usage | `GET https://chatgpt.com/backend-api/wham/usage` | Недоступно: app-server требует ChatGPT-backed auth |

Base URL выбирается по auth mode; явный user-level `openai_base_url` или custom `model_provider` может изменить destination, но не преобразует credentials или quota [29][30][31]. Project-local `.codex/config.toml` не может менять credential-redirection keys (`openai_base_url`, `chatgpt_base_url`, `model_provider`, `model_providers`), чтобы репозиторий не перенаправил credentials молча [12].

Проверенные `codex exec --help` и `codex login --help` не содержат quota/backend-флага: есть model/config/profile/OSS routing, ChatGPT browser/device auth и API-key auth [18]. `CODEX_API_KEY` действует только для `codex exec`; `CODEX_ACCESS_TOKEN` предназначен для trusted ChatGPT/Codex automation [2][27][32]. В текущем source остался только Responses wire protocol; старый `wire_api = "chat"` удалён [29].

Популярная связка `OPENAI_API_KEY` + `OPENAI_BASE_URL` version-sensitive. В CLI 0.144.5 встроенный одноразовый exec-контракт использует `CODEX_API_KEY`; custom provider может сам назвать `OPENAI_API_KEY` своим `env_key`. Для built-in provider текущие docs/source поддерживают top-level `openai_base_url`, но не документируют `OPENAI_BASE_URL` как эквивалентный environment override [12][32][34].

Это и есть ответ на вопрос о разных «surfaces»: транспорт и auth endpoints различаются, но отдельной поддерживаемой поверхности для расходования обычной text-chat allowance через Codex CLI нет.

## 4. Методы и оценка риска

| Метод | Работает как | Поддерживается | Риск |
|---|---|---:|---:|
| `codex login` → ChatGPT OAuth → `codex exec` | Тратит включённый Codex/agentic pool | Да | Низкий |
| API key / scoped `CODEX_API_KEY` | Отдельный платный API usage | Да | Низкий договорный; финансовый |
| Terra/Luna/mini, caching, компактный context | Медленнее расходует тот же pool | Да | Низкий |
| Покупка credits или banked reset | Продлевает usage после included limit | Да, если доступно аккаунту | Низкий |
| ChatGPT Work вместо Codex | Тратит тот же agentic pool | Да | Не является обходом |
| Стандартный ChatGPT text chat вручную | Использует chat model allowance/fallback | Да | Низкий, но не CLI automation |
| Custom provider со своей оплатой | Использует quota стороннего/API provider | Да как provider feature | Зависит от provider; не обход OpenAI quota |
| Browser cookie/access-token relay в сторонний CLI | Эмулирует неподдерживаемый web traffic | Нет | Высокий: credentials/ToS/enforcement |
| Несколько своих аккаунтов для разделения work/personal | Независимые accounts/workspaces | Да | Низкий при реальном разделении |
| Round-robin аккаунтов после каждого cap | Quota sharding | Нет | Высокий: намеренный rate-limit circumvention |
| Передача одного Pro account нескольким людям/агентам разных владельцев | Account sharing/resale | Нет | Высокий |
| Использование из неподдерживаемой страны через меняющиеся VPN/proxy | Обход geographic access | Нет | Высокий и независимый от quota |

## 5. ToS и enforcement

### Прямо запрещено

Consumer Terms запрещают:

- делиться account credentials или предоставлять аккаунт другим [7];
- автоматически или программно извлекать data/output [7];
- обходить rate limits/restrictions или protective measures [7];
- перепродавать/распространять доступ к сервису [7].

OpenAI Help Center поддерживает переключение между несколькими отдельными accounts/workspaces и работу одного владельца с нескольких устройств [13][15]. Terms не дают этим сценариям отдельного safe harbor. Если automation переключает аккаунты именно после cap, схема по назначению выглядит как circumventing rate limits; окончательная договорная квалификация остаётся facts- и jurisdiction-dependent.

При этом сам `codex exec` или unattended CI не равен нарушению: официальный non-interactive guide поддерживает API-key automation и описывает ChatGPT-managed auth для trusted private runners [27]. Это подтверждает существование штатной automation surface, но не создаёт договорного safe harbor для bulk extraction, credential sharing или quota circumvention.

### Что OpenAI документирует как последствия

- Unlimited access может быть временно ограничен abuse guardrails; пользователь получает уведомление и может обратиться в support [6][7].
- Suspicious Activity Alert могут вызвать необычные локации, резкие изменения usage и несколько concurrent sessions; ограничения могут затронуть отдельные features [16].
- Deactivation возможна за обход security/access restrictions, ненадлежащий шаринг accounts/API keys и повторные нарушения после warnings [9].
- Доступ из страны вне supported list может привести к block/suspension [10].

В исходниках quota, overload, policy и region failures — отдельные server-driven состояния: subscription `usage_limit_reached`, API `QuotaExceeded`, временные `slow_down`/`server_is_overloaded`, `cyber_policy` и restricted-region 403 не смешиваются в один «бан» [33]. Клиентского переключателя ban/unban или quota override в проверенных auth/provider/error paths нет; Codex отображает решение backend. Сам факт достижения cap не равен warning или deactivation.

### Что не удалось подтвердить

На момент проверки не найден публично проверяемый кейс, где OpenAI официально назвал **одиночный штатный `codex exec` с ChatGPT-auth** причиной бана. Такой auth route документирован и разрешён. Community reports о банах без письма enforcement и причинной связи следует считать anecdotes, а не доказательством.

## 6. Community и GitHub: что является сигналом, а что нет

GitHub issues подтверждают, что пользователи регулярно видят:

- неожиданный быстрый расход 5h/weekly percentages;
- рассинхрон banner, `/status` и web usage dashboard;
- отдельное или повышенное списание у Spark;
- продолжение уже начатого turn после достижения cap.

Однако maintainer replies и token rate card дают более простое объяснение большинству «ворует quota» случаев: модели имеют разные token rates, большие/cached contexts всё равно стоят credits, а active turn может завершиться после достижения лимита [3][11][17]. Issue report доказывает наличие жалобы, но не доказывает backend abuse или универсальную формулу weekly cap.

### Что называют workaround

1. **Изолированные `CODEX_HOME` и ротация accounts.** Официальная конфигурация позволяет вынести state/credentials/sessions в разные `CODEX_HOME`; community использует это для `~/.codex-a`, `~/.codex-b` и переключения сохранённых `auth.json` [19]. Упоминаются `codex-account-switcher`, CodexUse Accounts Pool/auto-roll, `codex-lb`, `codex-multi-auth` и OpenClaw profile rotation [20][21].
   **Оценка:** изоляция state — CONFIRMED; существование reports/tools — CONFIRMED как факт публикации; надёжное увеличение usable quota — LIKELY, не измерено. Ни один инструмент в этом исследовании не запускался, а для `codex-account-switcher` есть report о неполной поставке helper script [20].
2. **API/alternate-provider fallback.** Люди вручную logout/login с API key либо настраивают OpenAI-compatible providers (например, DeepSeek), чтобы CLI продолжал работать уже на другой оплачиваемой quota [22][23].
   **Оценка:** отдельный API/provider pool реален; это не перенос ChatGPT quota. Native автоматический `ChatGPT subscription → API key` fallback в просмотренных issues был feature request, а одновременный API key при активном ChatGPT-auth встречал ограничения [22][23]. Это observed absence для указанных версий, не доказательство вечного архитектурного запрета.
3. **Model/effort tuning.** Переключение на Luna/Terra/mini и снижение reasoning effort называют workaround, но это обычная оптимизация: она растягивает allowance, не обходит limiter [1][3].
4. **Phantom-limit remediation.** Несколько issue clusters описывают `usage limit reached`, когда `/status` или web dashboard показывают остаток. В таких случаях очистка stale state или смена версии может лечить client/UI bug; дополнительные аккаунты маскируют симптом, а не решают quota [24][25].

### Reddit и X/Twitter

Независимый community-поиск также не смог прочитать Reddit напрямую: Reddit JSON endpoints возвращали HTML/403 через все доступные proxy routes. Агрегированный поиск сообщил те же темы — `CODEX_HOME`/`auth.json` swapping, `codex-lb`/multi-auth, DeepSeek provider, ручной API re-login и model switching — но это Tier 3–4 evidence, поскольку исходные threads не были прочитаны [26].

Конкретный проверяемый X/Twitter thread о workarounds или банах не найден. Это **gap**, а не доказательство отсутствия обсуждений.

Прямое чтение Reddit JSON API через Direct и пять зарегистрированных proxy routes вернуло HTTP 403 3/3 host variants (`api.reddit.com`, `old.reddit.com`, `www.reddit.com`). Поэтому Reddit-выводы должны опираться только на открытые и сохранённые тексты независимого community-поиска; snippets поисковика без прочитанного thread не считаются источником.

## 7. Наша ситуация

Проверено локально:

```text
codex-cli 0.144.5
codex login status → Logged in using ChatGPT
~/.codex/config.toml → model = "gpt-5.3-codex-spark"
account entitlement → plan_type = "prolite"
```

Вывод:

1. Наш `codex exec` использует **ChatGPT-managed Codex subscription pool** текущего Pro $100 аккаунта; backend возвращает внутренний `plan_type=prolite`. Публичной спецификации, гарантирующей универсальное соответствие строки `prolite` названию 5× tier, нет, поэтому сам internal label не следует использовать для billing logic.
2. Это тот же pool для поддерживаемых Codex surfaces/agentic features этого аккаунта, но **не обычный unlimited/ fallback text-chat pool**.
3. Spark имеет отдельный weekly bucket (`codex_bengalfox`), поэтому работа на Spark не должна автоматически считаться свободной относительно основного Codex bucket; backend сейчас показывает оба.
4. Отдельная ChatGPT Plus subscription помогает CLI только если именно её account выбран через `codex login`; quotas разных accounts не складываются. В измерении использовался текущий Pro login, а не отдельный Plus account.
   Если «Pro $100 + Plus» находятся на одном аккаунте, Plus не является вторым суммируемым Codex pool: Pro уже включает Plus-функции. Если это два аккаунта, pools раздельны и автоматически не объединяются [6][13].
5. Перевод Orchestra на round-robin personal accounts ради продолжения после reset был бы самым ясным признаком intentional circumvention. Использование одного account, официального CLI и доступных models/credits/resets — нормальный product use.

## 8. Рекомендации

### Делать

1. Оставить ChatGPT OAuth как основной auth для Codex CLI; хранить `auth.json` как password и не передавать его между людьми или внешними сервисами.
2. Считать source of truth штатный Usage dashboard или `account/rateLimits/read`, а не чужие «N prompts/week».
3. Планировать capacity по token economics: Luna/Terra/mini для массовых простых задач, Sol для действительно сложных; сохранять cache-friendly sessions и не раздувать context без необходимости.
4. После included limit использовать только продуктовые варианты: banked reset, credits или API key с budget/spend controls.
5. Держать один стабильный account/network pattern, 2FA и минимальное число concurrent sessions; это снижает false-positive suspicious activity.
6. Разделять риски: quota compliance не устраняет geographic risk неподдерживаемой страны.
7. При исчерпании allowance деградировать явно: зафиксировать auth surface/model/typed error/reset time без token/credentials, поставить workload на паузу или более дешёвую модель и эскалировать ручное решение о banked reset, credits либо платном API.
8. Перепроверять pricing/limits перед изменением capacity plan и не реже раза в неделю для активной эксплуатации: модельная матрица и динамические лимиты меняются без клиентского релиза.

### Не делать

1. Не строить bridge из ChatGPT browser cookies/access tokens в Codex-compatible proxy.
2. Не менять аккаунт автоматически при достижении 5h/weekly cap.
3. Не покупать/арендовать аккаунты и не шарить один Pro credential между независимыми пользователями.
4. Не полагаться на undocumented `/wham/usage` или внутренние endpoints как стабильный контракт; app-server уже предоставляет поддерживаемый локальный protocol snapshot.
5. Не называть ChatGPT Plus text quota «безлимитной»: для capacity planning нужны model-specific caps и fallbacks.

## Confidence и контрдоказательства

| Finding | Confidence | Почему |
|---|---|---|
| ChatGPT-auth CLI — штатный subscription route | **CONFIRMED** | Два официальных документа + локальный login status |
| API auth — отдельный usage-based API pool | **CONFIRMED** | Authentication docs + pricing docs |
| Pro 5× per-model 5h ranges | **CONFIRMED** | Текущая официальная таблица |
| Weekly absolute capacity не опубликована | **CONFIRMED** | Официальная таблица даёт только qualifier; локальный protocol даёт percentage/window, не absolute |
| Наш snapshot вернул 7d основной и отдельный Spark bucket | **CONFIRMED для измеренного окна** | 3 одинаковых прямых измерения app-server; reset algorithm и универсальность не доказаны |
| Обычный ChatGPT text pool нельзя штатно направить в CLI | **CONFIRMED для supported product** | Auth/config docs + auth-selected endpoints и отсутствие третьего auth route в source |
| Browser-token relays дают дополнительную usable quota | **UNCERTAIN** | Технические anecdotes без воспроизводимого безопасного эксперимента; эксперимент нарушал бы границы исследования |
| За сам факт штатного ChatGPT-auth банят | **REFUTED как общее правило; отдельные кейсы UNCERTAIN** | Route официально документирован; подтверждённой причинной связи не найдено, но это не исключает enforcement по другим факторам |
| За intentional multi-account quota sharding возможна санкция | **LIKELY** | Прямой ToS-запрет + официально описанные enforcement outcomes; публичного case-level решения OpenAI нет |

### Контрдоказательства и конфликты

1. **Docs: 5h + weekly; наш snapshot: только 7d.** Это может быть entitlement rollout, смена pricing model или неполное представление protocol snapshot. Без server-side contract нельзя объявить 5h отменённым.
2. **Pricing: `Unlimited* messages`; Help Center: 160/3h на GPT-5.5 Instant Plus.** Формулировки совместимы только если `unlimited` относится к общему interaction/fallback experience, а не к фиксированной модели.
3. **Pro: unlimited GPT-5; Pro-model имеет отдельную allowance; Codex ограничен 5×/20×.** «Unlimited Pro» нельзя переносить между product surfaces.
4. **Community claims о банах и workarounds** часто не содержат enforcement email, account history, country/proxy context или точный auth route. Их вес — Tier 4 anecdote.

## Scope, затронутые файлы и edge cases

- Production code, Codex config, accounts и remote state не менялись. Единственный целевой артефакт — этот `docs/tasks/codex-limits-abuse/research.md`; опасные workaround-схемы не воспроизводились.
- Числа зависят от даты, model rollout, плана и workspace policy. Managed Business/Enterprise, API org tiers и промо-entitlements нельзя экстраполировать из нашего Pro account.
- Внутренние названия `prolite`, `codex_bengalfox` и endpoint `/wham/usage` не являются публичным стабильным API-контрактом.
- Ошибку `usage_limit_reached` нужно отличать от API quota, overload, safety и region failures; одинаковый UI-текст не доказывает одинаковую backend-причину [33].
- Отсутствие прямого Reddit/X evidence и публичной case-level истории банов оставляет community/enforcement часть **UNCERTAIN**, даже при высокой уверенности в ToS и auth architecture.

## Источники

1. **[Primary]** OpenAI Codex Pricing — usage estimates, 5h/shared weekly qualifier, Pro 5×/20×, separate Spark limit: https://learn.chatgpt.com/docs/pricing#what-are-the-usage-limits-for-my-plan
2. **[Primary]** OpenAI Codex Authentication — ChatGPT subscription auth vs API-key usage-based auth, `codex exec` automation: https://learn.chatgpt.com/docs/auth
3. **[Primary]** OpenAI Codex rate card — token-based credit rates since 2026-04-02: https://help.openai.com/en/articles/20001106
4. **[Primary]** OpenAI GPT-5.6 in ChatGPT — 160/3h Instant cap for Plus, reasoning allowances/fallbacks: https://help.openai.com/en/articles/20001354
5. **[Primary]** ChatGPT pricing comparison — `Unlimited*` marketing label and plan feature matrix: https://chatgpt.com/pricing
6. **[Primary]** OpenAI About ChatGPT Pro tiers — 5×/$100 and 20×/$200, separate model allowances: https://help.openai.com/en/articles/9793128
7. **[Primary]** OpenAI Rest-of-World Terms of Use — account access, automated extraction, rate-limit circumvention: https://openai.com/policies/row-terms-of-use/
8. **[Primary]** OpenAI Account Sharing Policy: https://help.openai.com/en/articles/10471989
9. **[Primary]** OpenAI account deactivation reasons and appeals: https://help.openai.com/en/articles/10562188
10. **[Primary]** OpenAI ChatGPT supported countries: https://help.openai.com/en/articles/7947663
11. **[Primary]** Using Codex with your ChatGPT plan — shared agentic pool, separate feature limits, active-turn behavior: https://help.openai.com/en/articles/11369540
12. **[Primary]** OpenAI Codex configuration reference — `chatgpt_base_url`, model providers and protected provider/auth config: https://learn.chatgpt.com/docs/config-file/config-reference
13. **[Primary]** OpenAI account switching — independent accounts/workspaces/subscriptions: https://help.openai.com/en/articles/20001068
14. **[Primary]** What is ChatGPT Plus? — variable message caps: https://help.openai.com/en/articles/6950777
15. **[Primary]** OpenAI Account Sharing Policy — multiple devices and individual ownership: https://help.openai.com/en/articles/10471989
16. **[Primary]** OpenAI Suspicious Activity Alerts — location, spikes and concurrent sessions: https://help.openai.com/en/articles/10471992
17. **[Primary/Anecdote]** openai/codex issue #16623, including OpenAI collaborator reply that GPT-5.4’s higher rate explains faster depletion: https://github.com/openai/codex/issues/16623
18. **[Direct measurement]** Local Codex CLI 0.144.5: `codex login status`; `codex exec --help`; `codex login --help`; three `account/rateLimits/read` calls; latest rollout `token_count.rate_limits`, 2026-07-18.
19. **[Primary]** Codex advanced config/auth docs — `CODEX_HOME` state and credentials isolation: https://developers.openai.com/codex/config-advanced and https://developers.openai.com/codex/auth
20. **[Secondary]** Published `codex-account-switcher` package/reviews: https://lobehub.com/skills/duclm1x1-dive-ai-codex-account-switcher
21. **[Secondary]** CodexUse profiles/accounts pool/auto-roll guides: https://codexuse.com/blog/
22. **[Primary/Anecdote]** openai/codex issue #2478 — requested ChatGPT→API fallback on subscription 429: https://github.com/openai/codex/issues/2478
23. **[Primary/Anecdote]** openai/codex issue #21017 and related #10869 — switching API key while ChatGPT-auth is active: https://github.com/openai/codex/issues/21017 and https://github.com/openai/codex/issues/10869
24. **[Primary/Anecdote]** openai/codex phantom-limit issue cluster, example #30041: https://github.com/openai/codex/issues/30041
25. **[Community forum/Anecdote]** Pro CLI phantom-limit report with available quota: https://community.openai.com/t/bug-pro-account-cannot-use-codex-cli-youve-hit-your-usage-limit-despite-available-quota/1382937
26. **[Aggregated community evidence]** Reddit summaries from an independent Perplexity pass; direct Reddit JSON was unavailable. Claims retained only as reports, not verified mechanisms.
27. **[Primary]** OpenAI non-interactive mode — API-key automation and advanced ChatGPT-managed auth on trusted private runners: https://learn.chatgpt.com/docs/non-interactive-mode#use-api-key-auth
28. **[Primary/source]** Codex `AuthMode` and `uses_codex_backend()` at audited commit: https://github.com/openai/codex/blob/56395bddaf26eb2829387ca6a417bf9128e5b239/codex-rs/protocol/src/auth.rs#L6-L54
29. **[Primary/source]** Built-in provider base selection, Responses-only wire protocol and response path: https://github.com/openai/codex/blob/56395bddaf26eb2829387ca6a417bf9128e5b239/codex-rs/model-provider-info/src/lib.rs#L38-L82 and https://github.com/openai/codex/blob/56395bddaf26eb2829387ca6a417bf9128e5b239/codex-rs/core/src/client.rs#L145-L160
30. **[Primary/source]** Subscription usage path `/backend-api/wham/usage`: https://github.com/openai/codex/blob/56395bddaf26eb2829387ca6a417bf9128e5b239/codex-rs/backend-client/src/client/rate_limit_resets.rs#L80-L108
31. **[Primary/source]** App-server rejects subscription usage queries for direct API-key auth: https://github.com/openai/codex/blob/56395bddaf26eb2829387ca6a417bf9128e5b239/codex-rs/app-server/src/request_processors/account_processor.rs#L1016-L1036
32. **[Primary/source]** `CODEX_API_KEY` exec-only precedence gate: https://github.com/openai/codex/blob/56395bddaf26eb2829387ca6a417bf9128e5b239/codex-rs/login/src/auth/manager.rs#L1215-L1227
33. **[Primary/source]** Quota, overload, safety and region error mapping: https://github.com/openai/codex/blob/56395bddaf26eb2829387ca6a417bf9128e5b239/codex-rs/codex-api/src/api_bridge.rs#L18-L175
34. **[Primary/maintainer correction]** Current top-level `openai_base_url` syntax and rejected `OPENAI_BASE_URL` workaround report: https://github.com/openai/codex/issues/16719#issuecomment-4185124336
