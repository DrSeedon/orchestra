# #249 — стоит ли добавлять Google Antigravity CLI как runtime Orchestra

Дата проверки: **2026-08-13**. Проверенная версия: **Antigravity CLI 1.1.12**.

## Вопрос и критерий

**Контекст.** Orchestra запускает несколько десятков агентов под одним Unix-пользователем,
разделяет их git worktree и использует только подписочные OAuth-креды. API-ключи запрещены.
Исходная покупка — 18 месяцев Google AI Pro по Jio-промо; Jio edition нельзя считать равной
розничной без отдельного подтверждения.

**Изменение под проверкой.** Добавить официальный `agy` как runtime. Старый `gemini` проверяется
как отдельная дверь, потому что Google перенёс consumer users в Antigravity, но оставил Gemini
CLI для Code Assist Standard/Enterprise.

**Baseline.** Не добавлять runtime, пока нет одновременно:

1. OAuth без API-ключа;
2. owned account с поддерживаемым регионом;
3. headless structured stream с tools/MCP;
4. точного resume по conversation ID;
5. изоляции state, scratch и worktree для параллельных workers;
6. compact-compatible lifecycle;
7. preflight, который не публикует worker с мёртвой credential/eligibility;
8. измеренной runway, достаточной для полезного класса задач.

## Гипотезы и фальсификаторы

### H1 — `agy` технически пригоден

Official OAuth, stream JSON, tools, MCP, exact resume и per-worker home складываются в
`BackendLike`-совместимый transport.

**Фальсификатор:** MCP только обнаруживается, ID отсутствует, два процесса пересекаются по
state/scratch, либо headless tool use требует TUI.

### H2 — пригодность закрыта не CLI, а аккаунтом

Russia-associated accounts отклоняются product gate, а account с allowlisted Terms-country
проходит на той же машине.

**Фальсификатор:** supported-region control получает тот же error либо Russia account проходит
после одной смены IP.

### H3 — купленный Jio Pro даёт дешёвый новый runtime pool

Jio entitlement должен открыть `agy` и повышенный Pro quota.

**Фальсификатор:** Jio account закрыт регионом, Jio terms не называют Antigravity, либо live quota
другого аккаунта нельзя перенести на Jio.

## Итоговое решение

**Antigravity CLI технически выглядит пригодным для backend Orchestra, но сейчас интеграцию не
начинать.** Причина теперь не CLI: на 1.1.12 живьём прошли headless stream, native tools, MCP,
exact resume, параллельная worktree-изоляция через `--add-dir` и полная state/scratch-изоляция
через отдельный `HOME`.

Практический blocker — **нет собственного eligible account**:

- оба личных аккаунта пользователя связаны по Google Terms с Россией и получают одинаковый
  location error;
- единственный eligible control — старый управляемый аккаунт бывшего работодателя,
  `multicastgames.com`, Terms-country Latvia;
- это чужой corporate account: администраторы управляют доступом и могут видеть активность.
  Аккаунт может исчезнуть в любой момент и **не может быть опорой архитектуры**.

Следовательно, Phase 2 имеет смысл только после появления собственного Google-аккаунта с
поддерживаемой Terms-country. На рабочем аккаунте ничего не покупать и не активировать.
Покупка AI Pro на одном из Russia-associated accounts географический gate не исправит: платный
Jio account и free control с той же country уже отказали одинаково.

## 1. Карта путей

1. **Старый consumer Gemini CLI:** manual `NO_BROWSER` OAuth технически жив, но Free/Google AI
   Pro/Ultra перестали обслуживаться **18.06.2026**.[1]
2. **Gemini CLI Standard/Enterprise:** не затронут deprecation, но требует отдельной Code Assist
   subscription/license и Google Cloud project; badge «Рабочий • Pro» этого не доказывает.[1][21]
3. **Antigravity CLI:** официальный successor жив; OAuth, eligible turns и runtime surfaces
   подтверждены.
4. **Jio account:** не проходит account-region eligibility, поэтому его Antigravity tier и
   increased quota не измерены.
5. **Latvia corporate control:** проходит, но годится только как испытательный стенд.

## 2. Закрытый путь: Gemini CLI consumer OAuth

### 2.1 Headless login без ключа существует

В исходнике `gemini-cli` v0.55.1:

- `NO_BROWSER=true` включает manual authorization;
- redirect фиксирован как `https://codeassist.google.com/authcode`;
- используется PKCE;
- CLI просит `Enter the authorization code:`.[25]

Direct probe дошёл до authorization URL и token exchange. Заведомо неверный код вернул:

```text
Failed to authenticate with authorization code:invalid_grant
```

Это адресно подтверждает OAuth-механику без API key; не подтверждает entitlement.

### 2.2 Consumer backend снят

Официальная формулировка с датой:

> Starting June 18, 2026, Gemini Code Assist IDE extensions stopped serving requests … This also
> applies to usage of Gemini CLI.[1]

Та же страница закрывает `Login with Google` для consumer users и направляет их в Antigravity;
отдельный migration announcement и guide подтверждают тот же successor path.[1][2][11]

**CONFIRMED:** закрыт consumer path старого `gemini`, а не Google CLI вообще.

### 2.3 Почему Workspace badge «Pro» не открывает старый CLI

Пользовательский screenshot показывает `Рабочий • Pro` на управляемом Workspace-аккаунте.
Official Workspace help объясняет badge `Pro` как expanded access к Gemini Apps models/features;
это не название Code Assist edition.[23]

Code Assist Standard/Enterprise — отдельный Gemini for Google Cloud продукт. До доступа нужны:

- купленная Standard/Enterprise subscription;
- назначенная пользователю license;
- включённая Gemini for Google Cloud API;
- IAM roles и выбранный Google Cloud project.[21][22]

Current official quota table для этого отдельного продукта даёт 1500 requests/user/day Standard
и 2000 Enterprise; эти числа нельзя переносить на Workspace badge или Antigravity tier.[20]

Локальный read-only log успешного `agy` дополнительно записал:

```text
applyAuthResult: email=[REDACTED], authMethod=consumer, quotaProject=
```

То есть текущая Antigravity-сессия вошла как consumer без quota project. Ни screenshot, ни local
metadata не дают признака Code Assist Standard/Enterprise license. Проверять её через auto-license,
выбор project или `selfAssignLicense` нельзя: это уже действие от имени чужой организации.

**LIKELY:** этот `Pro` — Workspace Gemini Apps access, а не незатронутая Code Assist license.
Поэтому старый Gemini CLI остаётся **UNVERIFIED/UNAVAILABLE для проекта**, не «доказанно мёртвым
для любых corporate accounts».

## 3. Antigravity 1.1.12: OAuth и eligibility

### 3.1 Версия и login

Официальный installer проверяет SHA-512 native binary.[3] Live binary и repository tag:

```text
agy --version
1.1.12

tag commit: f7519c9084190ed421e89dd81c63970b5177c9ef
tag date:   2026-08-10T18:26:06-07:00
```

SSH flow печатает external URL, браузер возвращает код на
`https://antigravity.google/oauth-callback`, пользователь вставляет код в terminal. Localhost
listener и SSH port-forward не нужны; API key не участвует.[5]

Первый login требует controlling TTY. Полностью unattended login остаётся открытым issue #223;
после bootstrap token используется headlessly.[13]

### 3.2 Region A/B/C

Два независимых OAuth на Russia-associated accounts дали дословно:

```json
{"conversation_id":"","status":"ERROR","response":"","error":"Eligibility check failed: Your current account is not eligible for Antigravity, because it is not currently available in your location.","duration_seconds":0,"num_turns":0,"usage":{"input_tokens":0,"output_tokens":0,"thinking_tokens":0,"cache_read_tokens":0,"total_tokens":0}}
```

Третий OAuth на Latvia-associated corporate account дал `status:"SUCCESS"` на той же VPS.
Egress не менялся: FR IPv4 / DE IPv6; обе страны есть в current allowlist.[5]

| Account | Google Terms country | Plan signal | Same egress | Result |
|---|---|---|---|---|
| personal 1 | Russia | Jio AI Pro | FR/DE | location ERROR |
| personal 2 | Russia | free/unknown | FR/DE | same ERROR |
| corporate control | Latvia | Workspace «Pro» | FR/DE | SUCCESS |

**CONFIRMED:** для нашего случая account-associated country определяет различие. IP-only и общий
bug #630 как объяснение именно этих трёх результатов опровергнуты одним разрешающим control.[15]
FAQ прямо велит сверять country на Google Terms page; policy описывает её как устойчивое account
property, а не страну разового запроса.[5][6]

## 4. Модели и реальная квота

### 4.1 Authenticated model surface

Рабочая форма команды — глобальный flag перед subcommand:

```bash
agy --output-format json models
```

Она вернула:

- `gemini-3.6-flash-{high,medium,low}`;
- `gemini-3.5-flash-{high,medium,low}`;
- `gemini-3.1-pro-{high,low}`;
- `claude-sonnet-4-6`;
- `claude-opus-4-6-thinking`;
- `gpt-oss-120b-medium`.

Authenticated registry совпадает с current official models surface.[9]

Форма `agy models --output-format json` закономерно падает:

```text
flags provided but not defined: -output-format
```

### 4.2 Два независимых weekly pools

Live `/quota` вернул две группы:

```text
Gemini Models          Weekly Limit Remaining  100%  reset 2026-08-20T07:47:15Z
Claude and GPT models  Weekly Limit Remaining  100%  reset 2026-08-20T07:47:15Z
```

Provider description:

> Within each group, models share a weekly limit. Quota is consumed proportionally to the cost
> of the tokens … tied directly to your individual tier.

Группа 1: Gemini Flash + Gemini Pro. Группа 2: Claude Opus + Claude Sonnet + GPT-OSS. Это
подтверждает отдельный third-party quota surface, но registry/quota bucket всё ещё не равны
успешному inference entitlement конкретной модели.

### 4.3 Измеренная стоимость стенда

Перед usage probes обе группы были `remaining_fraction=1`. Тринадцать successful terminal
results на `gemini-3.6-flash-low` суммарно сообщили:

```text
input_tokens=276577
output_tokens=3445
thinking_tokens=1546
cache_read_tokens=256572
total_tokens=280022
```

Финальный zero-token `/quota`:

```text
Gemini remaining_fraction = 0.83995521068573  (~84%)   reset 2026-08-20T07:50:47Z
Claude/GPT remaining_fraction = 1.0           (100%)   reset 2026-08-20T08:00:45Z
```

Смешанный пакет коротких tool/resume/MCP probes потратил **16.0045 п.п.** Gemini weekly pool.
Грубая нормализация даёт около **81 таких результатов на полный weekly pool**, но это не
абсолютный request limit: задачи неодинаковы, cost пропорционален model/token cost, а server не
публикует базовую единицу.

Важно: preregistered stop был 5 п.п., но quota не была снята после каждого turn; batch перескочил
порог до следующего sample. Это protocol deviation зафиксировано в
`experiment-protocol.md`; все inference probes остановлены. Claude/Opus inference намеренно не
проверялся после ограничения на чужой corporate account.

**Вывод:** этот наблюдённый tier не бездонный. Для 20 workers measured mixed batch означает
примерно четыре таких коротких результата на worker за неделю. Он полезнее как дополнительный
резерв и редкий дорогой route, чем как default массовый pool. Числовую разницу free/AI Pro
установить нельзя: plans публикуют «basic/more generous», а не absolute base.[8]

### 4.4 Что известно про AI Pro и Jio

Antigravity pricing обещает Google AI Pro более щедрые лимиты и flexible AI credit pool.[7]
Но текущий `/quota` на corporate account называет лишь `individual tier`, а Workspace badge Pro
не привязан документом к Antigravity AI Pro. Поэтому measured 16% нельзя подписывать как free или
Pro baseline.

Jio announcement подтверждает сам пакет и 2 TB, но не называет Antigravity/CLI.[16] Jio account
не прошёл geography; его повышенный CLI quota **UNCERTAIN**, не нулевой и не подтверждённый.

## 5. Runtime contract: live results

### 5.1 Headless stream и tools

`agy --output-format stream-json -p ...` выдаёт incremental JSONL:

- `init` с `conversation_id`, model, cwd и tools;
- `step_update` для user/model/tool steps;
- `tool_info` с parameters, output либо error;
- terminal `result` со status, response, usage и тем же `conversation_id`.

Live native `write_to_file` и `run_command` дали matching side effects. Первый headless attempt
без policy был auto-denied и при этом terminal result имел `SUCCESS`; parser обязан смотреть
`step_update.state/error`, а не верить только terminal status. Для production нужен narrow
`permissions.allow` в изолированном settings, не глобальный `--dangerously-skip-permissions`.[4]

**CONFIRMED:** stream parseable, tool events и side effects живые.

### 5.2 Exact resume: upstream issue #7 протух

Два fresh conversations вернули ID и в `init`, и в terminal `result`:

```text
A = 3927d04e-f04f-4004-9f65-c2f54091847a
B = cd67d3c4-611f-436b-a6ac-417e3efb4e5a
```

Два одновременных exact resume:

```bash
agy --conversation 3927d04e-f04f-4004-9f65-c2f54091847a ...
agy --conversation cd67d3c4-611f-436b-a6ac-417e3efb4e5a ...
```

вернули правильные разные memories `AURORA-249-A-71C4` и `BOREAL-249-B-92F7`, не вызвав tools.

**CONFIRMED на 1.1.12, 2026-08-13:** root ID доступен и exact identity достижима; `-c` как mutable
«последний в cwd» механизму Orchestra не нужен. Current resume docs описывают exact-ID flag;
open issue #7 описывает старое поведение.[10][12]

### 5.3 Default scratch ломает изоляцию

Без workspace flag два процесса из разных cwd одновременно выполнили:

```text
pwd; sleep 2; printf COLLIDE-A|B > collision-249.txt
```

Оба tool output показали один cwd:

```text
/home/kesha/.gemini/antigravity-cli/scratch
```

Остался один файл с `COLLIDE-B`; значение A потеряно. **CONFIRMED:** разные shell cwd сами по себе
не изолируют agent tools.

### 5.4 `--add-dir` — реальная workspace boundary

С `--add-dir <cwd>` tool `pwd` совпал с переданным каталогом, а файл появился там, не в shared
scratch. Различающий concurrent control запустил два процесса с разными `--add-dir`, одинаковым
filename и разными values. Сохранились оба:

```text
probes/a/add-dir-collision.txt = ADDDIR-A
probes/b/add-dir-collision.txt = ADDDIR-B
```

**CONFIRMED:** flag влияет на execution workspace, а не только на prompt.

### 5.5 Отдельный `HOME` изолирует весь runtime state

Для двух процессов созданы разные temporary HOME; в каждый скопирован mode-600 OAuth token.
Одновременный run без `--add-dir` создал независимо:

- `.gemini/antigravity-cli/cache/last_conversations.json`;
- отдельные conversation DB/WAL;
- отдельные logs, locks, installation ID;
- отдельный `.gemini/antigravity-cli/scratch/home-collision.txt`.

Tool `pwd` показал разные per-home scratch paths, файлы сохранили `HOME-A` и `HOME-B`, shared copy
не появилась. Обе временные token copies после проверки удалены; original не изменялся.

**CONFIRMED:** per-worker `HOME` снимает общую state/scratch race. Для backend нужен одновременно
per-worker HOME и `--add-dir <worktree>`. Оба механизма измерены отдельно; их совместный invocation
не повторялся после quota stop, поэтому composition — **LIKELY**, а не live-confirmed.

### 5.6 MCP

Workspace `.agents/mcp_config.json` описал один stdio server `runtime_probe`. Prompt запрещал shell
и требовал `record_probe("MCP-249-5E8A")`. Stream вернул:

```json
{"tool":"call_mcp_tool","ServerName":"runtime_probe","ToolName":"record_probe"}
{"state":"DONE","output":"RECORDED:MCP-249-5E8A"}
```

Server-side file содержал точный marker. **CONFIRMED:** MCP invocation, не только discovery, работает.
MCP есть и в official Code Assist/Antigravity product surface; open issue #71 не описывает current
1.1.12 result.[14][24]

### 5.7 Compact

Changelog 1.1.3 подтверждает automatic context compaction boundary.[4] Но:

```text
agy help compact
Error: unknown subcommand: compact
```

В 1.1.12 `-p "/clear"` относится к interactive-only commands и явно отказывается притворяться,
что очистил context.[4] Native external manual compact отсутствует.

Это не полный blocker: для non-Codex backends текущий `AgentSession.compact()` уже делает
summary turn → disconnect → fresh session → preamble (`app/session.py:2050-2325`). Новый backend
может идти этим generic path. Compatibility с fresh Antigravity session требует RED test в Phase 2;
в этом research живой compact не нагружался до context limit.

### 5.8 Credential cleanup

После последнего zero-token `/quota` основной corporate OAuth token
`~/.gemini/antigravity-cli/antigravity-oauth-token` (до удаления: mode 600, 503 bytes) удалён через
`unlink`. Вместе с ранее удалёнными двумя temporary copies итоговый поиск дал
`remaining_named_tokens=0`. Это локальная очистка VPS, не server-side revoke; следующий `agy`
потребует нового ручного OAuth.

## 6. Что делать при потере аккаунта/credential

Текущая Orchestra публикует session до backend connect: `spawn_worker` может создать IDLE worker,
а credential failure вскрывается на первой доставке. Это уже проявилось как `Grok credentials not
found`.

Для Antigravity обязательны:

1. до `publish_ready_session` выполнить zero-token `agy --output-format json -p '/quota'` в том же
   per-worker HOME;
2. проверить `status=SUCCESS`, requested model registry и отсутствие auth prompt;
3. только потом публиковать worker;
4. mid-session auth/eligibility/license error классифицировать terminally и без retry storm;
5. не считать наличие token file доказательством entitlement.

`/quota` live возвращает `usage` со всеми нулями и пригоден для preflight. Частота проверки,
circuit-breaker scope и новый status — Phase 2 design choices; требование «ошибка до публикации»
подтверждено текущим lifecycle и live eligibility behavior.

## 7. Маршрутизация и стоимость исчерпания

Если появится собственный eligible account:

| Route | Реалистичный класс | Основание |
|---|---|---|
| Gemini Flash | короткие закрытые задачи и overflow | самый дешёвый model в Gemini group, но measured mixed batch уже стоил 16% |
| Gemini Pro | редкий сложный second opinion | не трогает Claude Max, но делит Gemini weekly pool |
| Claude Sonnet/Opus 4.6 | самый ценный потенциальный route | отдельный Google third-party group; мог бы разгрузить болезненный Claude Max |

Claude/Opus здесь — **registry + quota-surface**, не live inference entitlement. Запуск запрещён после
обнаружения managed corporate account. Это главное, что следует проверить первым и минимально на
будущем собственном account.

Пул с дешёвым последствием исчерпания действительно следует расходовать раньше Claude Max, но
не раньше получения собственного аккаунта. Чужой корпоративный pool нельзя считать «бесплатным»:
последствие — аудит работодателя и внезапная потеря доступа.

## 8. Другие двери без API key

### Jules

`@google/jules` 0.1.42 поддерживает `jules login --no-launch-browser`; direct probe дошёл до manual
OAuth без API key. Official limits: free 15 tasks/rolling 24h, 3 concurrent; Pro 100/day, 15
concurrent.[19] Jules — async GitHub agent, не streaming local `BackendLike`; полезен отдельно, но
не заменяет runtime.

### Third-party wrappers

Antigravity FAQ предупреждает, что использование его login в third-party software может привести
к suspension/termination.[5] Допустимый design — официальный `agy` subprocess. Извлекать OAuth
token и ходить сторонним backend нельзя.

## 9. Что реально полезно в купленном Jio AI Pro

Подтверждено именно Jio-анонсом Google:[16]

- higher access к Gemini app / Gemini Pro;
- image generation (Nano Banana);
- video generation (Veo 3.1);
- expanded NotebookLM;
- **2 TB**, а не 5 TB, для Photos/Gmail/Drive и Android WhatsApp backup.

Deep Research и Gemini в Docs/Gmail доступны в соответствующих AI/Workspace plans, но Jio-specific
перечень не связывает каждый generic benefit с перепроданной gift activation. Их надо проверять в
интерфейсе Jio account product-by-product, не переносить retail marketing.

Покупка поэтому не бесполезна для веб-продуктов, но **не дала Orchestra runtime**: account-region
закрывает Antigravity, consumer Gemini CLI снят, а Jio→Antigravity Pro quota остаётся gap.

## 10. Ограничения и следующий минимальный тест

1. Corporate Latvia account нельзя привязывать к архитектуре, даже если он технически проходит.
2. Нельзя покупать на нём plan, назначать license, выбирать org project или активировать API.
3. Absolute quota не опубликована; 16% — mixed-batch measurement, не universal conversion.
4. Claude models не запускались; `models` и `/quota` не доказывают inference.
5. Combined per-worker HOME + `--add-dir` логически следует из двух controls, но после quota stop
   не проверен одним invocation.
6. Native manual compact отсутствует; generic Orchestra compact требует implementation test.
7. Jio cancellation semantics не опубликованы; saved refresh token может жить дольше entitlement.
   General partner terms оставляют provider управление cancellation/suspension, но не описывают
   Jio resale/gift-link failure.[17][18]

После появления **собственного** supported-region account нужен только один минимальный gate batch:

1. per-worker HOME + `--add-dir` в одном run;
2. один `claude-sonnet-4-6` tool turn;
3. `/quota` immediately before/after;
4. negative empty-HOME preflight до session publication.

До этого backend не писать и AI Pro специально ради corporate account не покупать.

## Confidence summary

| Finding | Confidence | Evidence tier |
|---|---|---|
| Consumer Gemini CLI снят 18.06.2026 | **CONFIRMED** | current official deprecation + old OAuth probe |
| Standard/Enterprise Gemini CLI не снят | **CONFIRMED** | official deprecation/setup docs |
| Workspace «Pro» = Code Assist Standard/Enterprise | **REFUTED как доказанный вывод** | products have different license/project contracts; local auth is consumer |
| Antigravity OAuth SSH без API key | **CONFIRMED** | official docs + three successful OAuth exchanges |
| Наш eligibility outcome объясняется account country | **CONFIRMED** | Russia/Russia fail vs Latvia pass, same host/egress |
| Successful stream/tool parser surface | **CONFIRMED** | direct JSONL + side effects |
| Exact root resume пригоден | **CONFIRMED** | two IDs, two simultaneous correct resumes |
| Default scratch безопасен | **REFUTED** | simultaneous same-file collision, A overwritten |
| `--add-dir` изолирует workspace | **CONFIRMED** | simultaneous distinct same-name files |
| Per-worker HOME изолирует state/scratch | **CONFIRMED** | two complete independent homes and files |
| MCP invocation работает | **CONFIRMED** | stream event + server return + side-effect marker |
| Manual native compact есть | **REFUTED** | help/changelog; generic Orchestra fallback remains viable |
| Claude/Opus доступны для inference | **LIKELY / UNTESTED LIVE** | official model docs + registry + 100% third-party bucket; no inference |
| Live tier выдержит массовые 20-worker задачи | **REFUTED для measured mix** | 13 short results consumed 16%; ~81/week normalized |
| Jio получает повышенный Antigravity quota | **UNCERTAIN** | no Jio-specific join; Jio account blocked by region |
| Сейчас стоит начинать backend | **REFUTED** | no owned eligible account; two remaining release tests |

## Counter-evidence

- Против старого вывода «Antigravity недоступен»: Latvia control passed and overturned it.
- Против open issue #7: current 1.1.12 returns ID in both `init` and `result` and exact resume works.
- Против «разные cwd достаточно»: both tools executed in one global scratch and collided.
- Против «общий scratch навсегда blocker»: `--add-dir` and isolated HOME each passed a concurrent
  allowing control.
- Против «Pro badge оживляет Gemini CLI»: Code Assist docs require a distinct licensed Cloud
  setup, while the live Antigravity auth is `consumer` with empty `quotaProject`.
- Против «Claude — только marketing»: authenticated registry and quota bucket both expose it;
  inference remains deliberately untested.
- Против «дешёвый unlimited pool»: a small mixed Flash-low probe batch consumed 16% weekly.

## Второе мнение Codex

Два разрешённых prose rounds были выполнены до появления Latvia control. Ревью исправило
завышенные causal claims, разделило registry/entitlement и признало прежний negative gate. Затем
новое live evidence развернуло главный вывод: account passed, issue #7 оказался stale, tools/MCP/
isolation были измерены. Поэтому файл `codex-review-research.md` сохранён как историческое
adversarial review, но его финальный verdict **не является approval этой обновлённой версии**.
Третий prose round не запускался: ceiling skill исчерпан.

## Затрагиваемые файлы возможной Phase 2

- новый `app/backend_antigravity.py`;
- registration/capabilities в `app/runtime_registry.py`;
- model IDs, provider pool и cost accounting в `app/models.py` и SQL/UI provider mappings;
- preflight до `publish_ready_session` в `app/manager.py`;
- terminal auth/quota/tool-error mapping в `app/session.py`;
- RED tests для parser, exact resume, HOME/worktree isolation, MCP, generic compact и credential loss.

Код в Phase 1 не менялся.

## Источники

Все URL открыты 2026-08-13. Более мелкая atomic matrix с direct quotations находится в
`google-source-matrix.md`.

1. [Google: Gemini Code Assist consumer deprecation](https://developers.google.com/gemini-code-assist/docs/deprecations/code-assist-individuals?hl=en)
2. [Google Developers Blog: transition to Antigravity CLI](https://developers.googleblog.com/an-important-update-transitioning-gemini-cli-to-antigravity-cli/)
3. [Official Antigravity CLI installer](https://antigravity.google/cli/install.sh)
4. [Antigravity CLI 1.1.12 changelog](https://github.com/google-antigravity/antigravity-cli/blob/1.1.12/CHANGELOG.md)
5. [Antigravity FAQ](https://antigravity.google/docs/faq)
6. [Google policy FAQ: account-associated region](https://policies.google.com/faq?hl=en_us)
7. [Antigravity pricing](https://antigravity.google/pricing)
8. [Antigravity plans and quotas](https://antigravity.google/docs/plans)
9. [Antigravity models](https://antigravity.google/docs/models)
10. [Antigravity resume](https://antigravity.google/docs/cli/commands/resume)
11. [Gemini CLI → Antigravity migration](https://antigravity.google/docs/cli/gcli-migration)
12. [Antigravity CLI issue #7](https://github.com/google-antigravity/antigravity-cli/issues/7)
13. [Antigravity CLI issue #223](https://github.com/google-antigravity/antigravity-cli/issues/223)
14. [Antigravity CLI issue #71](https://github.com/google-antigravity/antigravity-cli/issues/71)
15. [Antigravity CLI issue #630](https://github.com/google-antigravity/antigravity-cli/issues/630)
16. [Google India: Jio Google AI Pro offer](https://blog.google/intl/en-in/company-news/partnering-with-reliance-to-bring-the-best-of-google-ai-to-more-people-across-india/)
17. [Google One: third-party subscriptions](https://support.google.com/googleone/answer/15801606?hl=en)
18. [Google One terms](https://one.google.com/terms-of-service)
19. [Jules limits](https://jules.google/docs/usage-limits/)
20. [Current Gemini Code Assist quotas](https://docs.cloud.google.com/gemini/docs/quotas?hl=en)
21. [Set up Code Assist Standard/Enterprise](https://docs.cloud.google.com/gemini/docs/codeassist/set-up-gemini)
22. [Manage Code Assist licenses](https://docs.cloud.google.com/gemini/docs/codeassist/manage-licenses?hl=en)
23. [Gemini Apps with a work/school account](https://support.google.com/gemini/answer/14620100?co=DASHER._Family%3DBusiness-Enterprise&hl=en)
24. [Gemini Code Assist overview](https://developers.google.com/gemini-code-assist/docs/overview)
25. [Gemini CLI OAuth source, checked commit](https://raw.githubusercontent.com/google-gemini/gemini-cli/1ac3377395868295e128b96726d605a900b5946b/packages/core/src/code_assist/oauth2.ts)
