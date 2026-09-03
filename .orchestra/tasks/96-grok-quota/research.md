# #96 — реальные окна лимитов аккаунта, переданного как SuperGrok

Дата измерений: **2026-07-28**. Runtime: **grok 0.2.112
(`9bbd559437`)**, модель `grok-4.5-build`, OAuth-подписка из ответа CLI:
`XPremiumPlus` / отображаемое имя `X Premium+`. Контекст задачи называет этот
аккаунт SuperGrok; измеренные API не подтверждают, что маркетинговые названия
SuperGrok и X Premium+ взаимозаменяемы. Поэтому вывод ниже относится именно к
переданному OAuth-аккаунту и не обобщается на все варианты подписки SuperGrok.

## Вердикт

**Для переданного OAuth-аккаунта сервер сообщает недельный credit-period.**
Правильный HTTP-источник:

```text
GET https://cli-chat-proxy.grok.com/v1/billing?format=credits
```

На живом аккаунте ответил:

- использовано: **10.0%** недельных credits;
- тип периода: **`USAGE_PERIOD_TYPE_WEEKLY`**;
- начало: **2026-07-25 18:49:05.891405 UTC**;
- server-reported конец, который TUI подписывает `Next reset`:
  **2026-08-01 18:49:05.891405 UTC** =
  **2026-08-02 01:49:05.891405 Asia/Krasnoyarsk**;
- длительность: **604 800 секунд = 168 часов = 7 суток**.

Это отдельное представление того же `/v1/billing`: без query-параметра сервер
по-прежнему отдаёт месячный счётчик `used / monthlyLimit`. Предыдущий вывод
«короткого окна нет для проверенного аккаунта» **REFUTED**: был найден
правильный path, но не скрытый `format=credits`. Фактический переход через
границу ещё не наблюдался, поэтому реальный reset в эту секунду не доказан.

**Часового или иного дополнительного окна не обнаружено.** Это не равнозначно
доказательству его отсутствия: бинарник и живые ответы показывают weekly/monthly,
а технические `x-ratelimit-*` не сдвинулись даже под параллельной нагрузкой и не
содержат reset. Поэтому по ним нельзя честно восстановить ещё одно окно.

## Вопрос и критерий

### Контекст

У Grok Build уже был найден календарный месячный счётчик
`GET /v1/billing`: `used=485`, `monthlyLimit=20000`,
`2026-07-01 → 2026-08-01`. Требовалось проверить утверждение, что у подписки
переданного аккаунта есть более короткое usage-window, сопоставимое с окнами
Claude/Codex. Tier этого аккаунта API называет `XPremiumPlus`; соответствие
маркетинговому имени SuperGrok не устанавливалось.

### Сравнение

- **Baseline:** только календарный месяц и неинформативные
  `x-ratelimit-limit/remaining-*`.
- **Гипотеза:** CLI знает отдельное недельное/rolling окно, но получает его через
  скрытый query-параметр, ACP extension или локальный cache.

### Решающий результат

Окно считается найденным только если живой ответ одновременно даёт:

1. процент использования;
2. тип/длительность периода;
3. абсолютную server-reported границу, которую сам CLI называет следующим
   сбросом.

Строка в бинарнике без живого ответа — только указатель, не доказательство.

## Гипотезы и фальсификаторы

### H1 — короткое окно скрыто за другим форматом billing

Гипотеза: CLI запрашивает не новый `/usage`, а специальный формат
существующего `/billing`.

Фальсификатор: в бинарнике нет другого billing request, а все варианты
`/billing` возвращают только месячные поля.

**Результат: CONFIRMED.** В бинарнике найден literal
`/billing?format=credits`; живой GET вернул недельные поля [M1][M3].

### H2 — `x-ratelimit-*` кодируют rolling/часовое окно

Гипотеза: `remaining-requests/tokens` уменьшаются и затем восстанавливаются,
что позволяет вычислить окно.

Фальсификатор: счётчики остаются равны limit на последовательной и одновременной
нагрузке; reset-полей нет.

**Результат: REFUTED для доступного эксперимента.** 12 последовательных и
20 параллельных успешных inference-запросов не изменили ни один header [M5].
Это не доказывает, что upstream никогда не применит технический limiter, но
делает эти headers непригодными как источник quota проверенного аккаунта.

### H3 — кроме месяца коротких окон нет

Фальсификатор: живой ответ с `WEEKLY`, start/end и percentage.

**Результат: REFUTED.** Такой ответ получен независимо через TUI/ACP gateway и
прямой HTTP [M2][M3].

## Findings

### F1. Недельный период и процент — CONFIRMED

Evidence tier: **1, прямое измерение**, два маршрута к одному upstream-ответу:
TUI-вызов `x.ai/billing` и прямой HTTP [M2][M3].

Сырой HTTP-ответ `GET /v1/billing?format=credits`:

```json
{
  "config": {
    "currentPeriod": {
      "type": "USAGE_PERIOD_TYPE_WEEKLY",
      "start": "2026-07-25T18:49:05.891405+00:00",
      "end": "2026-08-01T18:49:05.891405+00:00"
    },
    "creditUsagePercent": 10.0,
    "onDemandCap": {"val": 0},
    "onDemandUsed": {"val": 0},
    "productUsage": [
      {"product": "GrokBuild", "usagePercent": 5.0},
      {"product": "Api", "usagePercent": 2.0},
      {"product": "GrokImagine", "usagePercent": 2.0},
      {"product": "GrokChat", "usagePercent": 1.0}
    ],
    "isUnifiedBillingUser": true,
    "prepaidBalance": {"val": 0},
    "topUpMethod": "TOP_UP_METHOD_SAVED_PAYMENT_METHOD",
    "billingPeriodStart": "2026-07-25T18:49:05.891405+00:00",
    "billingPeriodEnd": "2026-08-01T18:49:05.891405+00:00"
  }
}
```

Арифметика ответа:

```text
end - start       = 604800 seconds
                   = 168 hours
                   = 7 days
5% + 2% + 2% + 1% = 10% creditUsagePercent
```

`creditUsagePercent` — общий unified показатель, а не только Grok Build. В
этом единственном снимке сумма четырёх `productUsage` совпала с ним:
`5 + 2 + 2 + 1 = 10`. Это наблюдаемое равенство, а не доказанный контракт
аддитивного учёта для всех ответов. Для панели безопасная подпись — недельные
credits аккаунта X Premium+, а не «процент Grok Build modelCalls».

### F2. Граница, которую CLI называет следующим сбросом — CONFIRMED; сам reset — не наблюдался

Evidence tier: **1, прямое измерение** [M2][M3][M4].

```text
start UTC   2026-07-25T18:49:05.891405+00:00
end UTC     2026-08-01T18:49:05.891405+00:00
start +07   2026-07-26T01:49:05+07:00
reported end +07  2026-08-02T01:49:05+07:00
```

TUI `/usage` независимо отобразил тот же результат с округлением секунд:

```text
Session usage (since start or last resume):
  Input tokens:   81,517 (57,088 cached)
  Output tokens:  1,174 (1,165 reasoning)
  Total tokens:   82,691
  Model calls:    3 · API time: 19s
  Cost:           $0.0730

Weekly limit: 10%
Next reset: August 2, 01:49
```

Граница была побайтно одинаковой во всех **39** локальных лог-записях от
`2026-07-27T13:33:36.224Z` до `2026-07-28T09:45:35.606Z` [M4].

Ограничение вывода: сам переход через `2026-08-01T18:49:05Z` ещё не наблюдался.
То, что runtime подписывает конец как `Next reset`, подтверждено; фактическое
обнуление в эту секунду пока не измерено.

### F3. Сервер сообщает стабильный weekly interval, но semantics учёта неизвестна — CONFIRMED / UNCERTAIN

Evidence tier: **1, прямые локальные логи runtime**, но без server-side
объяснения коррекции [M4].

Изменения `creditUsagePercent` при неизменных start/end:

```text
2026-07-27T13:42:49.738Z   2.0
2026-07-27T13:44:48.068Z   3.0
2026-07-27T13:51:10.959Z   5.0
2026-07-27T14:16:58.952Z   6.0
2026-07-27T14:35:38.601Z   7.0
2026-07-27T14:45:24.561Z   8.0
2026-07-27T14:53:02.852Z   9.0
2026-07-27T15:41:39.311Z  10.0
2026-07-27T16:01:25.088Z  11.0
2026-07-27T16:09:22.940Z  12.0
2026-07-28T09:45:08.533Z  10.0
```

`currentPeriod.start/end` во всех строках:

```text
USAGE_PERIOD_TYPE_WEEKLY
2026-07-25T18:49:05.891405+00:00
2026-08-01T18:49:05.891405+00:00
```

Стабильность server-reported start/end в этой выборке — **CONFIRMED**. Но
утверждать «дискретный fixed bucket» или «rolling window» нельзя: процент
уменьшился с 12 до 10 до заявленного reset. Возможные объяснения —
асинхронная коррекция/репрайсинг unified credits или rolling-компонент внутри
недельного reporting period — **UNCERTAIN**, данных для выбора нет.

Практическое следствие: показывать server-reported процент как снимок, не
экстраполировать его монотонно и не вычислять остаток из локальной суммы
`modelCalls`.

### F4. Месячный и недельный ответы выбирает один query-параметр — CONFIRMED

Evidence tier: **1, прямые HTTP-запросы** [M3].

Без параметра:

```http
GET /v1/billing
HTTP 200
```

```json
{
  "config": {
    "monthlyLimit": {"val": 20000},
    "used": {"val": 485},
    "onDemandCap": {"val": 0},
    "billingPeriodStart": "2026-07-01T00:00:00+00:00",
    "billingPeriodEnd": "2026-08-01T00:00:00+00:00",
    "history": [
      {"billingCycle":{"year":2026,"month":6},"includedUsed":{"val":0},"onDemandUsed":{"val":0},"totalUsed":{"val":0}},
      {"billingCycle":{"year":2026,"month":5},"includedUsed":{"val":0},"onDemandUsed":{"val":0},"totalUsed":{"val":0}},
      {"billingCycle":{"year":2026,"month":4},"includedUsed":{"val":0},"onDemandUsed":{"val":0},"totalUsed":{"val":0}}
    ]
  }
}
```

С параметром:

```http
GET /v1/billing?format=credits
HTTP 200
```

возвращает weekly-ответ из F1.

Контроль query values:

```text
format=usage    -> HTTP 200, месячная форма
format=weekly   -> HTTP 200, месячная форма
format=monthly  -> HTTP 200, месячная форма
format=credits  -> HTTP 200, недельная credit-форма
```

Значение не угадывается по аналогии: распознаётся именно literal `credits`.

### F5. Бинарник содержит точный скрытый маршрут и weekly UI — CONFIRMED

Evidence tier: **2, первичный артефакт — установленный binary** [M1].

`strings` вокруг `xai-grok-shell/src/extensions/billing.rs`:

```text
Authentication required to fetch billing data
Billing data requires auth with grok.com. Run `grok login` to authenticate.
./billing?format=credits
Bearer
x-grok-client-mode
billing: upstream error
billing: fetched credits config
```

UI literals:

```text
WEEKLY
MONTHLY
Usage
Monthly limit
Weekly limit
Next reset:
Credits:
```

Терминальная форма исчерпания тоже различает weekly:

```text
No billing data available.
You hit your weekly limit.
Upgrade to a higher tier for more usage
Purchase credits to keep using Grok Build
```

Это указало, где искать, но verdict основан не на strings, а на живом ответе
F1.

### F6. `x.ai/billing` сработал в TUI, но недоступен в проверенной ACP stdio-конфигурации — CONFIRMED

Evidence tier: **1, protocol experiment** [M2][M8].

TUI debug:

```text
INFO agent.ext_method{method=x.ai/billing}: Received extension method call: method=x.ai/billing
INFO ... extensions::billing: handling billing config request
DEBUG ... received "ext_method" response:
{"config":{"creditUsagePercent":10.0,
"currentPeriod":{"type":"USAGE_PERIOD_TYPE_WEEKLY",
"start":"2026-07-25T18:49:05.891405+00:00",
"end":"2026-08-01T18:49:05.891405+00:00"},
"onDemandCap":{"val":0},"onDemandUsed":{"val":0},"prepaidBalance":{"val":0},
"isUnifiedBillingUser":true,
"billingPeriodStart":"2026-07-25T18:49:05.891405+00:00",
"billingPeriodEnd":"2026-08-01T18:49:05.891405+00:00"},
"subscription_tier":"X Premium+"}
```

Но отдельный `grok agent --no-leader stdio` после успешных `initialize` и
`session/new` ответил:

```json
{"jsonrpc":"2.0","id":3,"error":{"code":-32601,"message":"Method not found"}}
```

То есть Orchestra не может просто добавить `_request("x.ai/billing", {})` в
текущий `backend_grok`: в проверенном запуске `grok agent --no-leader stdio`
этот метод не зарегистрирован. Это не доказывает, что extension принципиально
TUI-only: на регистрацию могут влиять launch mode, capabilities или init
metadata. Прямой HTTP — воспроизводимый источник для измеренной конфигурации.

### F7. `/usage` — локальная TUI-команда, поэтому её не было в ACP availableCommands — CONFIRMED

Evidence tier: **1, terminal experiment**, corroborated binary/user-guide only
as navigation [M2].

До создания сессии введённый `/billing` ушёл как обычный model prompt.
После старта сессии `/usage` исполнился локально, вызвал одновременно
`x.ai/session/usage` и `x.ai/billing`, затем показал raw block из F2.

Предыдущая проверка `initialize._meta.availableCommands` не могла её найти:
этот список описывает agent commands, а `/usage`/alias `/cost` живёт в pager.

### F8. Дополнительного hourly/rolling API не найдено — UNCERTAIN, не «не существует»

Evidence tier: **1, negative HTTP/binary/load measurements** [M1][M5][M6].

Новые пути (уже проверенные в #95 пути намеренно не повторялись):

```text
/v1/billing/usage
/v1/billing/credits
/v1/billing/limits
/v1/billing/current
/v1/usage/current
/v1/usage/weekly
/v1/account/usage
/v1/account/limits
/v1/rate_limits/current
/v2/billing
/v2/usage
/v2/rate_limits
```

На `cli-chat-proxy.grok.com` и `api.x.ai` все дали HTTP 404. Сырые формы:

```html
<html>
<head><title>404 Not Found</title></head>
<body>
<center><h1>404 Not Found</h1></center>
<hr><center>nginx</center>
```

```text
The requested resource was not found. Please check the URL and try again.
Documentation is available at https://docs.x.ai/
```

`GET cli-chat-proxy.grok.com/v1/user?include=subscription` существует и
вернул `subscriptionTier: "XPremiumPlus"`, но quota/window полей в ответе нет.
На `api.x.ai` этот путь дал 404.

В релевантной UI-группе бинарника присутствуют `WEEKLY` и `MONTHLY`; рядом
нет hourly/daily/rolling варианта. Это ограниченный факт о версии 0.2.112,
не доказательство всех server-side guardrail.

### F9. Rate-limit headers не являются наблюдаемым usage-счётчиком — CONFIRMED

Evidence tier: **1, заранее заданный load test** [M5].

Критерий до запуска: если `remaining` хотя бы раз станет меньше `limit`,
наблюдать восстановление; если все ответы останутся full, окно не выводить.

12 последовательных запросов:

```text
i   time_utc                  http  limit_req  remaining_req  limit_tok  remaining_tok
1   2026-07-28T09:50:52.242Z  200   8300       8300           53000000   53000000
2   2026-07-28T09:50:56.405Z  200   8300       8300           53000000   53000000
3   2026-07-28T09:50:58.468Z  200   8300       8300           53000000   53000000
4   2026-07-28T09:51:00.877Z  200   8300       8300           53000000   53000000
5   2026-07-28T09:51:03.368Z  200   8300       8300           53000000   53000000
6   2026-07-28T09:51:05.783Z  200   8300       8300           53000000   53000000
7   2026-07-28T09:51:08.719Z  200   8300       8300           53000000   53000000
8   2026-07-28T09:51:11.873Z  200   8300       8300           53000000   53000000
9   2026-07-28T09:51:13.972Z  200   8300       8300           53000000   53000000
10  2026-07-28T09:51:16.073Z  200   8300       8300           53000000   53000000
11  2026-07-28T09:51:17.953Z  200   8300       8300           53000000   53000000
12  2026-07-28T09:51:19.726Z  200   8300       8300           53000000   53000000
```

Это могли скрыть быстрые refill. Поэтому второй запуск стартовал 20 `curl`
jobs в фоне (`probe 1 & ... probe 20 &`, затем общий `wait`). Все 20 вернули
один и тот же ряд:

```text
20 × HTTP 200
x-ratelimit-limit-requests:      8300
x-ratelimit-remaining-requests:  8300
x-ratelimit-limit-tokens:        53000000
x-ratelimit-remaining-tokens:    53000000
```

Реальность нагрузки подтверждена response usage:

```json
{
  "responses": 20,
  "errors": 0,
  "total_prompt_tokens": 4240,
  "total_completion_tokens": 40,
  "total_cost_usd_ticks": 101580000
}
```

У headers нет `reset`, `retry-after` или window fields. Скорость
восстановления не измеряется, потому что просадка **не воспроизвелась**.
Точный maximum in-flight не инструментировался, но completion mtimes всех 20
header-файлов легли в диапазон `2026-07-28 16:55:28.306269791 +07:00` —
`16:55:29.540266399 +07:00`, то есть **1.234 s**; это сохраняет проверяемый
признак overlap, а не только заявление о способе запуска.

### F10. Unsolicited quota notification и локальный cache не найдены — LIKELY

Evidence tier: **1, local inspection и короткий headless turn** [M7].

- `models_cache.json` содержит model/context/reasoning metadata, quota keys нет.
- `sessions/session_search.sqlite` и `worktrees.db` не имеют quota/usage/billing
  columns/tables.
- `grok inspect --json` не показал usage/billing state.
- `grok models --debug-file` сходил только в `/v1/models`.
- В debug одного успешного headless turn не было billing/weekly/quota/reset
  terms; quota пришла только по явному TUI billing fetch.
- `~/.grok/logs/unified.jsonl` содержит историю уже полученных
  `billing: fetched credits config`, но не отдельный cache/API state. Это
  полезная история измерений, не авторитетный текущий источник.

Полный «длинный ACP turn со всеми типами subagent/goal событий» после
нахождения прямого источника не запускался: он не нужен для извлечения окна.
Поэтому отсутствие push-notification имеет confidence **LIKELY**, не
CONFIRMED.

## Counter-evidence и ограничения

1. **Процент уменьшился 12% → 10% внутри неизменного weekly period.**
   Следовательно, нельзя обещать монотонный расход или выводить remaining из
   локальных modelCalls.
2. **Фактический момент reset ещё не пересечён.** Start/end и UI `Next reset`
   достоверны; поведение ровно на boundary будет известно после 2 августа.
3. **Hour-level guardrail может существовать только server-side.** Ни binary
   0.2.112, ни API, ни headers его не раскрыли; терминальный 429 не получен.
4. **Response относится к unified account с API-tier `XPremiumPlus`.**
   `productUsage` включает Build, API, Imagine и Chat. Контекст задачи
   называет аккаунт SuperGrok, но API не доказал эквивалентность этих названий;
   на другом типе аккаунта форма может отличаться.
5. **`creditUsagePercent` имеет целочисленную процентную гранулярность в
   наблюдениях** (`2.0`, `3.0`, …, `12.0`, `10.0`). Мелкий ход может не
   изменить отображаемое значение.

## Adversarial second opinion

Первый раунд Codex дал verdict **Not supported as written**: документ
обобщал `XPremiumPlus` на SuperGrok, называл reported end фактическим reset,
слишком широко трактовал ACP registration и не сохранял часть raw extracts.
Все load-bearing возражения были проверены и исправлены; исходное несогласие
сохранено в `codex-review-research.md`.

Повторный раунд в той же сессии: **Supported, no blocking findings**. Он
подтвердил только узкий verdict из этого файла и отдельно перечислил
неразрешённое: фактический reset, fixed-vs-rolling semantics, другие tier и
скрытый hourly guardrail. Единственная suggestion — добавить overlap evidence
для burst — закрыта completion envelope в F9/E2.

## Что именно доступно для панели

| Величина | Поле | Текущее измерение |
|---|---|---|
| Использовано | `config.creditUsagePercent` | `10.0%` |
| Длительность | `currentPeriod.end - start` | `604800 s / 7d` |
| Reported end / ожидаемый reset UTC | `currentPeriod.end` | `2026-08-01T18:49:05.891405Z` |
| Reported end локально | timezone conversion | `2026-08-02 01:49:05 +07:00` |
| Тип | `currentPeriod.type` | `USAGE_PERIOD_TYPE_WEEKLY` |
| Разбивка | `productUsage[]` | Build 5%, API 2%, Imagine 2%, Chat 1% |
| Абсолютный weekly denominator | отсутствует | **не выдумывать** |
| Hourly/rolling window | отсутствует | **не найдено / не показывать** |

Для текущего аккаунта достаточно именно weekly credit-form. Месячный
`used/monthlyLimit` можно хранить как отдельную метрику, но он не заменяет и
не вычисляет weekly.

## Риски будущей реализации (код не менялся)

- OAuth token живёт ограниченное время; 401 означает re-auth problem, не
  отсутствие endpoint.
- Прямой HTTP обязан использовать реальный `format=credits`; `format=weekly`
  молча возвращает месячную форму.
- Нужно валидировать `currentPeriod.type`, start/end и percent; если форма
  изменилась, показывать «нет данных», не ноль.
- `x.ai/billing` через проверенный внешний `grok agent stdio` сейчас
  method-not-found; не проектировать текущую реализацию на этот ACP extension.
- Не смешивать unified weekly percentage с месячным `used`; единица месячного
  поля в этом эксперименте повторно не выводилась (в #95 она измерялась
  отдельно).
- Не использовать `x-ratelimit-remaining-*` как процент quota: эксперимент
  не подтвердил их расход.

## Затронутые файлы

Продакшн-код и `app/` **не менялись**. Созданы только этот исследовательский
артефакт и adversarial review рядом с ним.

## Встроенные сырые evidence extracts

Ни один extract ниже не содержит Bearer, ключ, `team_id`, `user_id`,
`session_id`, email или полный ответ `/v1/user`.

### E1. Все 39 найденных billing records

Поля ниже извлечены из `~/.grok/logs/unified.jsonl` без PID и соседних
событий. `null` означает, что в первых семи ответах percentage отсутствовал.

```text
timestamp                    percent  type                       start                              end
2026-07-27T13:33:36.224Z     null     USAGE_PERIOD_TYPE_WEEKLY   2026-07-25T18:49:05.891405+00:00  2026-08-01T18:49:05.891405+00:00
2026-07-27T13:34:13.635Z     null     USAGE_PERIOD_TYPE_WEEKLY   2026-07-25T18:49:05.891405+00:00  2026-08-01T18:49:05.891405+00:00
2026-07-27T13:34:45.820Z     null     USAGE_PERIOD_TYPE_WEEKLY   2026-07-25T18:49:05.891405+00:00  2026-08-01T18:49:05.891405+00:00
2026-07-27T13:35:15.336Z     null     USAGE_PERIOD_TYPE_WEEKLY   2026-07-25T18:49:05.891405+00:00  2026-08-01T18:49:05.891405+00:00
2026-07-27T13:38:08.258Z     null     USAGE_PERIOD_TYPE_WEEKLY   2026-07-25T18:49:05.891405+00:00  2026-08-01T18:49:05.891405+00:00
2026-07-27T13:38:56.845Z     null     USAGE_PERIOD_TYPE_WEEKLY   2026-07-25T18:49:05.891405+00:00  2026-08-01T18:49:05.891405+00:00
2026-07-27T13:39:54.048Z     null     USAGE_PERIOD_TYPE_WEEKLY   2026-07-25T18:49:05.891405+00:00  2026-08-01T18:49:05.891405+00:00
2026-07-27T13:42:49.738Z     2.0      USAGE_PERIOD_TYPE_WEEKLY   2026-07-25T18:49:05.891405+00:00  2026-08-01T18:49:05.891405+00:00
2026-07-27T13:44:48.068Z     3.0      USAGE_PERIOD_TYPE_WEEKLY   2026-07-25T18:49:05.891405+00:00  2026-08-01T18:49:05.891405+00:00
2026-07-27T13:45:48.913Z     3.0      USAGE_PERIOD_TYPE_WEEKLY   2026-07-25T18:49:05.891405+00:00  2026-08-01T18:49:05.891405+00:00
2026-07-27T13:47:51.472Z     3.0      USAGE_PERIOD_TYPE_WEEKLY   2026-07-25T18:49:05.891405+00:00  2026-08-01T18:49:05.891405+00:00
2026-07-27T13:49:44.070Z     3.0      USAGE_PERIOD_TYPE_WEEKLY   2026-07-25T18:49:05.891405+00:00  2026-08-01T18:49:05.891405+00:00
2026-07-27T13:51:10.959Z     5.0      USAGE_PERIOD_TYPE_WEEKLY   2026-07-25T18:49:05.891405+00:00  2026-08-01T18:49:05.891405+00:00
2026-07-27T13:54:15.393Z     5.0      USAGE_PERIOD_TYPE_WEEKLY   2026-07-25T18:49:05.891405+00:00  2026-08-01T18:49:05.891405+00:00
2026-07-27T13:54:20.471Z     5.0      USAGE_PERIOD_TYPE_WEEKLY   2026-07-25T18:49:05.891405+00:00  2026-08-01T18:49:05.891405+00:00
2026-07-27T14:06:57.374Z     5.0      USAGE_PERIOD_TYPE_WEEKLY   2026-07-25T18:49:05.891405+00:00  2026-08-01T18:49:05.891405+00:00
2026-07-27T14:16:58.952Z     6.0      USAGE_PERIOD_TYPE_WEEKLY   2026-07-25T18:49:05.891405+00:00  2026-08-01T18:49:05.891405+00:00
2026-07-27T14:20:04.631Z     6.0      USAGE_PERIOD_TYPE_WEEKLY   2026-07-25T18:49:05.891405+00:00  2026-08-01T18:49:05.891405+00:00
2026-07-27T14:21:54.310Z     6.0      USAGE_PERIOD_TYPE_WEEKLY   2026-07-25T18:49:05.891405+00:00  2026-08-01T18:49:05.891405+00:00
2026-07-27T14:29:09.829Z     6.0      USAGE_PERIOD_TYPE_WEEKLY   2026-07-25T18:49:05.891405+00:00  2026-08-01T18:49:05.891405+00:00
2026-07-27T14:30:03.669Z     6.0      USAGE_PERIOD_TYPE_WEEKLY   2026-07-25T18:49:05.891405+00:00  2026-08-01T18:49:05.891405+00:00
2026-07-27T14:32:27.545Z     6.0      USAGE_PERIOD_TYPE_WEEKLY   2026-07-25T18:49:05.891405+00:00  2026-08-01T18:49:05.891405+00:00
2026-07-27T14:35:38.601Z     7.0      USAGE_PERIOD_TYPE_WEEKLY   2026-07-25T18:49:05.891405+00:00  2026-08-01T18:49:05.891405+00:00
2026-07-27T14:35:49.179Z     7.0      USAGE_PERIOD_TYPE_WEEKLY   2026-07-25T18:49:05.891405+00:00  2026-08-01T18:49:05.891405+00:00
2026-07-27T14:36:09.582Z     7.0      USAGE_PERIOD_TYPE_WEEKLY   2026-07-25T18:49:05.891405+00:00  2026-08-01T18:49:05.891405+00:00
2026-07-27T14:39:12.040Z     7.0      USAGE_PERIOD_TYPE_WEEKLY   2026-07-25T18:49:05.891405+00:00  2026-08-01T18:49:05.891405+00:00
2026-07-27T14:43:26.373Z     7.0      USAGE_PERIOD_TYPE_WEEKLY   2026-07-25T18:49:05.891405+00:00  2026-08-01T18:49:05.891405+00:00
2026-07-27T14:45:24.561Z     8.0      USAGE_PERIOD_TYPE_WEEKLY   2026-07-25T18:49:05.891405+00:00  2026-08-01T18:49:05.891405+00:00
2026-07-27T14:47:08.448Z     8.0      USAGE_PERIOD_TYPE_WEEKLY   2026-07-25T18:49:05.891405+00:00  2026-08-01T18:49:05.891405+00:00
2026-07-27T14:53:02.852Z     9.0      USAGE_PERIOD_TYPE_WEEKLY   2026-07-25T18:49:05.891405+00:00  2026-08-01T18:49:05.891405+00:00
2026-07-27T15:41:39.311Z     10.0     USAGE_PERIOD_TYPE_WEEKLY   2026-07-25T18:49:05.891405+00:00  2026-08-01T18:49:05.891405+00:00
2026-07-27T15:54:48.260Z     10.0     USAGE_PERIOD_TYPE_WEEKLY   2026-07-25T18:49:05.891405+00:00  2026-08-01T18:49:05.891405+00:00
2026-07-27T16:01:25.088Z     11.0     USAGE_PERIOD_TYPE_WEEKLY   2026-07-25T18:49:05.891405+00:00  2026-08-01T18:49:05.891405+00:00
2026-07-27T16:03:16.998Z     11.0     USAGE_PERIOD_TYPE_WEEKLY   2026-07-25T18:49:05.891405+00:00  2026-08-01T18:49:05.891405+00:00
2026-07-27T16:09:22.940Z     12.0     USAGE_PERIOD_TYPE_WEEKLY   2026-07-25T18:49:05.891405+00:00  2026-08-01T18:49:05.891405+00:00
2026-07-28T09:45:08.533Z     10.0     USAGE_PERIOD_TYPE_WEEKLY   2026-07-25T18:49:05.891405+00:00  2026-08-01T18:49:05.891405+00:00
2026-07-28T09:45:10.070Z     10.0     USAGE_PERIOD_TYPE_WEEKLY   2026-07-25T18:49:05.891405+00:00  2026-08-01T18:49:05.891405+00:00
2026-07-28T09:45:31.877Z     10.0     USAGE_PERIOD_TYPE_WEEKLY   2026-07-25T18:49:05.891405+00:00  2026-08-01T18:49:05.891405+00:00
2026-07-28T09:45:35.606Z     10.0     USAGE_PERIOD_TYPE_WEEKLY   2026-07-25T18:49:05.891405+00:00  2026-08-01T18:49:05.891405+00:00
```

### E2. Все 20 ответов concurrent burst

Launch pattern и completion envelope:

```text
probe 1 & ... probe 20 &; wait
earliest headers completion  2026-07-28 16:55:28.306269791 +07:00
latest headers completion    2026-07-28 16:55:29.540266399 +07:00
completion spread            1.234 s
maximum in-flight            not instrumented
```

```text
i   http  limit_req  remaining_req  limit_tok  remaining_tok
1   200   8300       8300           53000000   53000000
2   200   8300       8300           53000000   53000000
3   200   8300       8300           53000000   53000000
4   200   8300       8300           53000000   53000000
5   200   8300       8300           53000000   53000000
6   200   8300       8300           53000000   53000000
7   200   8300       8300           53000000   53000000
8   200   8300       8300           53000000   53000000
9   200   8300       8300           53000000   53000000
10  200   8300       8300           53000000   53000000
11  200   8300       8300           53000000   53000000
12  200   8300       8300           53000000   53000000
13  200   8300       8300           53000000   53000000
14  200   8300       8300           53000000   53000000
15  200   8300       8300           53000000   53000000
16  200   8300       8300           53000000   53000000
17  200   8300       8300           53000000   53000000
18  200   8300       8300           53000000   53000000
19  200   8300       8300           53000000   53000000
20  200   8300       8300           53000000   53000000
```

### E3. Полная матрица новых endpoint probes

Из ответа `/v1/user?include=subscription` сохранён только факт HTTP 200 и
извлечённый tier; полный body удалён из-за идентификаторов.

```text
host                         path                            status  content-type
cli-chat-proxy.grok.com      /v1/billing/usage              404     inode/x-empty
cli-chat-proxy.grok.com      /v1/billing/credits            404     inode/x-empty
cli-chat-proxy.grok.com      /v1/billing/limits             404     inode/x-empty
cli-chat-proxy.grok.com      /v1/billing/current            404     inode/x-empty
cli-chat-proxy.grok.com      /v1/usage/current              404     text/html
cli-chat-proxy.grok.com      /v1/usage/weekly               404     text/html
cli-chat-proxy.grok.com      /v1/account/usage              404     text/html
cli-chat-proxy.grok.com      /v1/account/limits             404     text/html
cli-chat-proxy.grok.com      /v1/rate_limits/current        404     text/html
cli-chat-proxy.grok.com      /v2/billing                    404     text/html
cli-chat-proxy.grok.com      /v2/usage                      404     text/html
cli-chat-proxy.grok.com      /v2/rate_limits                404     text/html
cli-chat-proxy.grok.com      /v1/user?include=subscription  200     application/json
cli-chat-proxy.grok.com      /v1/auto-topup                 404     text/html
api.x.ai                     /v1/billing/usage              404     text/plain
api.x.ai                     /v1/billing/credits            404     text/plain
api.x.ai                     /v1/billing/limits             404     text/plain
api.x.ai                     /v1/billing/current            404     text/plain
api.x.ai                     /v1/usage/current              404     text/plain
api.x.ai                     /v1/usage/weekly               404     text/plain
api.x.ai                     /v1/account/usage              404     text/plain
api.x.ai                     /v1/account/limits             404     text/plain
api.x.ai                     /v1/rate_limits/current        404     text/plain
api.x.ai                     /v2/billing                    404     text/plain
api.x.ai                     /v2/usage                      404     text/plain
api.x.ai                     /v2/rate_limits                404     text/plain
api.x.ai                     /v1/user?include=subscription  404     text/plain
api.x.ai                     /v1/auto-topup                 404     text/plain
```

### E4. ACP stdio exchange

Для аудита protocol result ниже показана вся существенная
request/response-последовательность; capabilities и `sessionId` сокращены, но
method, id и error сохранены буквально.

```json
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":1,"clientInfo":{"name":"grok96-probe","version":"1"}}}
{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":1,"agentCapabilities":"<redacted: non-secret capability object>","agentInfo":{"name":"grok","version":"0.2.112"}}}
{"jsonrpc":"2.0","id":2,"method":"session/new","params":{"cwd":"/tmp/grok96-acp","mcpServers":[]}}
{"jsonrpc":"2.0","id":2,"result":{"sessionId":"<redacted>"}}
{"jsonrpc":"2.0","id":3,"method":"x.ai/billing","params":{}}
{"jsonrpc":"2.0","id":3,"error":{"code":-32601,"message":"Method not found"}}
```

## Измерения / источники

- **[M1] Tier 2, primary artifact:** `~/.grok/downloads/grok-linux-x86_64`,
  SHA/version label `grok 0.2.112 (9bbd559437)`; `strings`, byte-offset
  extraction вокруг `extensions/billing.rs`, `limitWeekly`, terminal errors.
- **[M2] Tier 1, direct measurement:** интерактивный TUI в `/tmp`,
  `/usage`, `--debug-file`; безопасный billing-only extract
  `/tmp/grok96-billing-evidence.txt`. Исходный debug был обнулён после того,
  как тестовый model turn попытался прочитать auth file; секреты в
  артефакт не переносились.
- **[M3] Tier 1, direct measurement:** authenticated GET на
  `cli-chat-proxy.grok.com/v1/billing` с query variants; raw safe JSON в
  F1/F4; рабочие копии `/tmp/grok96-{plain,credits,usage,weekly,monthly}.json`.
- **[M4] Tier 1, direct runtime log history:** только безопасные поля
  `ts`, `creditUsagePercent`, `currentPeriod` из
  `~/.grok/logs/unified.jsonl`; все 39 строк встроены в E1, рабочий extract
  `/tmp/grok96-billing-history.tsv`.
- **[M5] Tier 1, direct load measurement:** 12 sequential и 20 concurrent
  successful `/v1/chat/completions`; sequential rows в F9, concurrent rows в
  E2; рабочие extracts `/tmp/grok96-load-series.tsv`,
  `/tmp/grok96-burst.tsv`.
- **[M6] Tier 1, direct negative measurement:** novel endpoint matrix на
  `cli-chat-proxy.grok.com` и `api.x.ai`; вся безопасная matrix встроена в E3,
  рабочий extract `/tmp/grok96-endpoint-matrix.tsv`.
- **[M7] Tier 1, local measurement:** file listing, SQLite schemas,
  `models_cache.json` keys, `grok inspect --json`, `grok models
  --debug-file`, один headless turn.
- **[M8] Tier 1, protocol measurement:** JSON-RPC `initialize` /
  `session/new` / `x.ai/billing` к `grok agent --no-leader stdio`;
  безопасная последовательность встроена в E4;
  `x.ai/billing -> -32601 Method not found`.
