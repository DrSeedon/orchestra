# RESEARCH: Claude Code Fast Mode — влияние, экономика, лимиты

**Задача:** научно разобрать fast mode — что это, сколько жрёт, станет ли хуже/лучше по лимитам подписки Max 20x.
**Дата:** 2026-07-03
**Статус:** research only, жду approval.

> ⚡ **TL;DR (главное, читать это):** Fast mode на подписке **НЕ бесплатный и НЕ считается в лимиты подписки**. Он биллится **отдельно, из "usage credits" (pay-as-you-go по реальным $)**, с **первого токена по цене $10/$50 за Mtok** (2x Opus 4.8). Для нас это значит: наша "монополька $200 фикс" на fast mode **НЕ распространяется** — каждый fast-запрос = реальные деньги сверх подписки. При этом фича требует включённого биллинга (usage credits). **Вывод: для Orchestra fast mode бесполезен** — SDK его технически не умеет включить (strict-typed betas), а даже если бы умел — это были бы реальные траты, а не виртуальные. Рекомендация: **не включать**.

---

## 1. Что такое fast mode технически? (факт vs маркетинг)

### Это НЕ другая модель — ФАКТ (подтверждён официальной докой)
Anthropic docs дословно: *"Fast mode runs the same model with a faster inference configuration. There is no change to intelligence or capabilities. Same model weights and behavior (not a different model)."* [1]

Claude Code docs: *"Fast mode is not a different model. It uses Claude Opus with a different API configuration that prioritizes speed over cost efficiency. You get identical quality and capabilities with faster responses."* [2]

**Вердикт:** "identical quality" — это НЕ маркетинг, это техническая правда. Те же веса модели, тот же Opus 4.8, просто инференс-конфиг с приоритетом скорости над cost-efficiency (Anthropic выделяет больше compute на генерацию). Флаг `usage.speed` в ответе (`"fast"`/`"standard"`) позволяет объективно проверить что реально применилось. [1]

### Как включается
- **API:** параметр `speed: "fast"` + beta-header `anthropic-beta: fast-mode-2026-02-01`. [1]
- **Claude Code CLI:** команда `/fast` (Tab-toggle) ИЛИ `"fastMode": true` в user settings. Требует Claude Code **v2.1.36+**. НЕ работает в VS Code extension. [2]
- **Модели:** только Opus 4.8 ($10/$50) и Opus 4.7 ($30/$150, deprecated, удаляется 2026-07-24). На 4.6 — `speed:"fast"` тихо игнорируется (billed standard). На остальных — ошибка. [1][2]
- **Дефолт в CC:** Opus 4.8 — fast-default в v2.1.154+. Если ты на другой модели и жмёшь `/fast` — CC автопереключает на Opus. [2]

---

## 2. Насколько реально быстрее? (измеренные цифры)

### ~2.5x — это OTPS (output tokens/sec), НЕ общее время и НЕ TTFT
Anthropic docs дословно: *"Up to 2.5x higher output tokens per second compared to standard speed. Speed benefits are focused on output tokens per second (OTPS), **not time to first token (TTFT)**. Compatible with streaming, where the OTPS gain is most visible."* [1]

**Что это значит на практике:**
- Ускоряется **только скорость генерации output-токенов** (стриминг «печатает» быстрее).
- **TTFT (пауза до первого токена) НЕ меняется** — сколько ждал начала ответа, столько и ждёшь.
- Выигрыш виден **только при streaming** и **только на длинной генерации** (много output-токенов).

### Где это даёт выигрыш для НАШИХ workload:
| Workload | Output-объём | Выигрыш от fast mode |
|---|---|---|
| **Оркестратор** (короткие ответы + tool-вызовы) | маленький output, много TTFT-пауз на tool round-trips | **почти нулевой** — 2.5x от 50 токенов = экономия долей секунды, а tool-latency и TTFT не ускоряются |
| **Воркер** (длинная генерация кода) | большой output | **заметный** — генерация файла на 2000 токенов реально быстрее в ~2.5x по wall-clock самой генерации |

**Вывод по скорости:** fast mode ускоряет ровно то, чего у оркестратора мало (длинный output), и не трогает то, что у него доминирует (TTFT + tool round-trips). Для воркеров-кодеров выигрыш реален, но см. раздел 3 — цена этого выигрыша.

### Независимые бенчи
Vendor claim 2.5x OTPS — подтверждается вторичными источниками, но это всё пересказ той же цифры Anthropic, а не независимое измерение OTPS. Единственный **production-датапоинт по стоимости** (не по скорости): **Databricks** гонял Opus 4.8 Fast в своём Genie AI agent и отрапортовал **61% дешевле** по токен-costs vs Opus 4.7 [4] — но это про *миграцию 4.7→4.8* (4.8 fast в 3x дешевле чем 4.7 fast), НЕ про «fast дешевле standard». ⚠️ **Флаг:** независимого стороннего замера именно OTPS 2.5x я не нашёл — цифра только vendor.

---

## 3. Сколько ЖРЁТ — токены и лимиты (КРИТИЧНО)

### Цена: 2x за токен (НЕ 6x для Opus 4.8)
| Режим | Opus 4.8 input/output | Множитель |
|---|---|---|
| Standard | $5 / $25 за Mtok | 1x |
| **Fast** | **$10 / $50 за Mtok** | **2x** |
| Opus 4.7 fast (deprecated) | $30 / $150 | 6x |

Источник цен — официальная doc-таблица [1][2]. **Флаг по «6x»:** цифра 6x из некоторых источников — это про **Opus 4.7/4.6** ($30/$150 = 6x от $5/$25), НЕ про 4.8. Для 4.8 fast — ровно **2x**. Пирог для нас: наши агенты на **Opus 4.8[1m]**, значит множитель **2x**.

### Fast mode тратит СТОЛЬКО ЖЕ токенов, просто дороже за токен
Тот же ответ = то же кол-во токенов (веса и поведение идентичны, разд. 1). Fast mode **НЕ раздувает** число токенов на ответ — он умножает **цену** каждого токена на 2. Исключение — **first-enable charge** (см. ниже).

### ⚠️ First-enable charge — скрытая доп-стоимость
*"The first time you enable fast mode in a conversation, you pay the full fast mode uncached input token price for the entire conversation context."* [2]
- Включил `/fast` в середине длинного диалога → платишь fast-цену за **весь накопленный контекст** как uncached input (это единоразово на разговор).
- Плюс: переключение fast↔standard **инвалидирует prompt cache** (разные speed не шарят cached-префиксы) → следующий запрос = cache miss = снова полный input. [1]
- **Мораль:** если уж включать — только с **начала** сессии, не в середине. Для нас (persistent client, длинные сессии) середина = дорого.

### 🎯 ГЛАВНОЕ: как fast mode считается в лимитах подписки Max 20x
**Ответ (официальная doc, дословно):**

> *"For Claude Code users on subscription plans (Pro/Max/Team/Enterprise), fast mode is available **via usage credits only and not included in the subscription rate limits**."* [2]

> *"Fast mode usage draws directly from **usage credits, even if you have remaining usage on your plan**. This means fast mode tokens **do not count against your plan's included usage** and are **charged at the fast mode rate from the first token**."* [2]

**Что это ЛОМАЕТ в нашей модели «монополька $200 фикс»:**
- **Наши все $ виртуальные** — это верно **только для standard mode** (входит в подписку Max 20x).
- **Fast mode — НЕ входит в подписку.** Он биллится из **usage credits = реальные деньги, pay-as-you-go**, по $10/$50 за Mtok, **с первого токена**, **даже если лимиты подписки ещё не выбраны**.
- Требует, чтобы у аккаунта были **включены usage credits** (биллинг сверх плана). Если не включены — `/fast` просто не заработает / упадёт.

**Так БЫСТРЕЕ ли упрёмся в лимит 5h/7d?**
- В лимиты подписки (5h окно + 7d weekly) fast mode **вообще не попадает** — он их **не трогает**. Технически: наши окна подписки от fast НЕ пострадают, потому что fast-токены идут мимо них.
- **НО** это не «бесплатный обход лимита» — это **перекладывание расхода в реальные деньги**. Мы не «упрёмся в лимит быстрее», мы **начнём платить настоящими долларами** сверх $200/мес.
- У fast mode есть **свой отдельный rate-limit пул** (per-minute token bucket, headers `anthropic-fast-*-tokens-*`) [1]. При его исчерпании → авто-fallback на standard speed (иконка `↯` сереет), потом авто-возврат. [2]

**Итог по разделу 3 (ключевой вывод):**
> Fast mode на подписке = **реальные траты сверх $200/мес**, а не виртуальные. Он НЕ жжёт лимиты подписки (идёт мимо них), но жжёт **живые деньги**. Trade-off не «скорость vs лимиты», а **скорость vs реальный кошелёк**.

---

## 4. Как включить в SDK (claude-agent-sdk) — и почему НЕЛЬЗЯ

### ❌ Блокер: SDK технически не умеет включить fast mode
Orchestra гоняет **всех** агентов через `claude-agent-sdk` (`ClaudeAgentOptions` в `app/backend_claude.py:135`). Fast mode через SDK **не включается**:

1. **`ClaudeAgentOptions.betas` — strict-typed:** `list[SdkBeta]`, где `SdkBeta = Literal["context-1m-2025-08-07"]`. SDK **отклоняет** любой другой beta-флаг, включая `fast-mode-2026-02-01`. [3][5]
2. **`extra_args` — не помогает:** `extra_args: dict[str, str|None]` пробрасывает **CLI-флаги** в bundled Claude CLI, **НЕ HTTP-заголовки**. Beta-header через него не поставить. [3]
3. Открытый feature-request (SDK issue #845): просят добавить `extra_headers` или расширить `SdkBeta` — но пока **не реализовано**. [5]

**Единственный «чистый» путь по докам** — вызывать Messages API напрямую с `speed="fast"` + `betas=["fast-mode-2026-02-01"]` [1]. Но Orchestra работает НЕ через сырой Messages API, а через SDK-клиент (persistent client per session) — переписывать backend на raw API ради fast mode = архитектурный слом.

### Теоретический обходной путь (НЕ рекомендуется)
CLI-флаг `"fastMode": true` в user settings файле CC ([2]) мог бы подхватиться, если SDK стартует bundled CLI с нашим `CLAUDE_CONFIG_DIR` (у нас он переопределяется, `backend_claude.py:133`). Но:
- Это включит fast **глобально для профиля**, без гранулярного контроля per-agent.
- Всё равно упрётся в биллинг: **usage credits = реальные $** (разд. 3).
- Требует CC **v2.1.36+** в bundled-версии SDK — надо проверять.

**Флаг для отключения на всякий:** env `CLAUDE_CODE_DISABLE_FAST_MODE=1` — жёстко вырубает fast mode. [2] Можно добавить в наш env-блок (`backend_claude.py:126-128`) как guard, чтобы случайный `fastMode:true` в профиле не начал жечь деньги.

---

## 5. РЕКОМЕНДАЦИЯ с trade-off

### Вердикт: **НЕ включать fast mode в Orchestra.**

**Три независимых причины, любой достаточно:**

1. **💸 Это реальные деньги, а не монополька.** Вся наша модель «оптимизируем качество, не цену, $ виртуальные» держится на том, что мы в подписке. Fast mode **выходит из-под подписки** и биллится **живыми $** ($10/$50 Mtok, с первого токена, мимо included usage) [2]. Один воркер-кодер на длинной сессии в fast = десятки реальных долларов. Это прямое противоречие принципу «Max 20x = фикс $200».

2. **🔧 SDK его не умеет.** `betas` strict-typed, `extra_args` не пробрасывает headers [3][5]. Чтобы включить — надо либо ждать SDK-фичу (#845), либо переписывать backend на raw Messages API, либо хакать через профиль-настройку (глобально, без per-agent контроля). Овчинка не стоит выделки.

3. **📉 Профиль выигрыша не совпадает с нашим bottleneck.** Fast ускоряет **только OTPS** (длинный output), НЕ TTFT и НЕ tool-latency [1]. Наш оркестратор — короткие ответы + tool round-trips → выигрыш ~0. Наша боль — **rate-limit 5h окно** (упирается по токенам подписки), а fast mode её **не решает**: он не сокращает число токенов, он их выносит в отдельный платный пул. Быстрее печатать код воркер будет, но лимиты 5h/7d от этого не разгрузятся (они и так standard-only).

### Разбор по кандидатам «а кому бы дать»:
- **Всем** — ❌ нет (реальные $ ×N агентов).
- **Только оркестраторам** — ❌ нет смысла (короткий output → выигрыш почти нулевой, а платить полную fast-цену за их огромный контекст на first-enable — дорого).
- **Только воркерам-кодерам** — технически тут выигрыш по скорости есть, но это реальные $ и SDK не пробрасывает. ❌
- **Только для «срочного» вручную** — единственный сценарий где *теоретически* оправдано: юзер сам, в личной Claude Code сессии (НЕ через Orchestra SDK), жмёт `/fast` когда сидит и ждёт живого ответа на горящей задаче, осознавая что платит реальные $. Это **вне Orchestra**, к нашему backend отношения не имеет.

### Что делать с нашей реальной болью (rate-limit 5h окно)
Fast mode её НЕ лечит. Настоящие рычаги против 5h-лимита (мимо fast mode):
- **effort level** (снизить thinking-токены на простых задачах) — экономит **реальные токены подписки**, разгружает окно. [2 упоминает как отдельный от fast рычаг]
- **prompt caching** (input по ~1/10 цены при повторах) — меньше токенов в лимит.
- **модель по задаче** (Haiku/Sonnet на мелочь вместо Opus) — уже делаем.
- **меньше tool-calls / короче промпты** — уже принцип проекта (AI Efficiency в CLAUDE.md).

**Опционально (defensive):** добавить `CLAUDE_CODE_DISABLE_FAST_MODE=1` в env-блок `backend_claude.py`, чтобы гарантировать что никакой агент случайно не включит fast и не начнёт жечь реальные деньги. Дёшево, безопасно, соответствует принципу «fail loud / детерминизм».

---

## Источники
- [1] Anthropic Platform Docs — Fast mode (research preview): https://platform.claude.com/docs/en/build-with-claude/fast-mode — **первоисточник**: OTPS not TTFT, speed param + beta header, цены $10/$50, separate rate limits (`anthropic-fast-*` headers), prompt-cache invalidation, `usage.speed` verification.
- [2] Claude Code Docs — Speed up responses with fast mode: https://code.claude.com/docs/en/fast-mode — **первоисточник**: `/fast` + `fastMode:true`, v2.1.36+, «usage credits only, not included in subscription rate limits», «charged from the first token», first-enable full-context charge, `CLAUDE_CODE_DISABLE_FAST_MODE=1`, auto-fallback.
- [3] Claude Agent SDK Python reference: https://code.claude.com/docs/en/agent-sdk/python — `betas` strict-typed, `extra_args`=CLI flags не headers.
- [4] VentureBeat — Opus 4.8 3x cheaper fast mode, Databricks Genie 61% cheaper vs 4.7: https://venturebeat.com/technology/anthropics-claude-opus-4-8-is-here-with-3x-cheaper-fast-mode-and-near-mythos-level-alignment — production cost datapoint (миграция 4.7→4.8).
- [5] SDK feature request #845 (opt into extra anthropic-beta headers): https://github.com/anthropics/claude-agent-sdk-python/issues/845 — подтверждает что fast-mode beta через SDK сейчас невозможен.
- [6] Claude Code fast-mode billing warning issue #56782 + feature req #31880 (fast should consume quota, not bill separately): https://github.com/anthropics/claude-code/issues/56782 — подтверждает «нет in-CLI предупреждения о выходе из-под подписки», юзеры жалуются.

## Флаги vendor vs measured
- ✅ **Measured/официально:** цены $10/$50 (4.8), separate rate-limit пул, «usage credits only не входит в подписку», OTPS-not-TTFT, SDK betas strict-typed.
- ⚠️ **Vendor claim, независимо не подтверждён:** «2.5x OTPS» — цифра только от Anthropic, стороннего замера OTPS не нашёл. Databricks 61% — это про cost-миграцию 4.7→4.8, не про скорость.
