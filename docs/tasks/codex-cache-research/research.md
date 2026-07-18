# Codex CLI prompt cache / TTL / session economics

**Дата проверки:** 2026-07-18

**Среда:** Codex CLI `0.144.5`, ChatGPT-auth (текущий план Pro 5x), `gpt-5.6-sol`, Orchestra worktree
**Итог:** для GPT-5.6 Sol prompt caching есть и активно работает. У публичного API нет Claude-подобного TTL ровно в 1 час: default — **минимум 30 минут**, после чего запись может жить дольше без гарантированного максимума [1]. Для ChatGPT-auth Codex отдельный TTL contract не опубликован; локально подтверждён hit через 31.2 минуты, но не всеобщая 30-минутная гарантия. Делать preventive compact ради cache TTL не нужно; compact нужен только из-за давления на context window.

## Вопрос

- **Context:** локальные Sol workers Orchestra используют Codex CLI с ChatGPT-auth.
- **Change under test:** сохранять/возобновлять Codex thread и/или заранее compact-ить его.
- **Baseline:** новый Codex thread без resume и без ручного compact.
- **Outcome:** `cached_input_tokens / input_tokens`, сохранение hit после пауз, API-equivalent cost, subscription credits и риск потери контекста.

## Гипотезы и falsifiers

1. **H1:** resume улучшает cache reuse, потому что Codex сохраняет thread id, transcript и `prompt_cache_key`. **Falsifier:** исходники создают новый cache key при resume либо resume в пределах TTL стабильно даёт zero hit при неизменном prefix.
2. **H2:** у GPT-5.6 API TTL не равен фиксированному 1 часу; API default задаёт минимум 30 минут, а дальнейшее удержание opportunistic. Для ChatGPT-auth CLI это рабочая гипотеза, не публичный contract. **Falsifier:** официальная документация ChatGPT-auth задаёт другой TTL либо controlled CLI measurements систематически расходятся с API policy.
3. **H3:** preventive compact ради cache economics невыгоден, потому что он заменяет длинную историю новым summary-prefix и требует нового cache fill. **Competing alternative:** compact перед истечением TTL обновляет старый cache и сохраняет скидку. **Falsifier:** реализация refresh-ит прежний prefix без его замены либо post-compact turns стабильно дешевле без context-pressure.
4. **H4:** Pro 5x меняет quota, но не cache TTL/discount. **Falsifier:** plan docs, request fields или response metadata задают отдельный Pro cache policy.

## Метод

1. Прочитаны official Prompt Caching, API pricing, Codex pricing и Codex manual [1][2][3][4].
2. Проверены `codex --help`, `codex exec --help`, `codex exec resume --help` и установленная версия (`0.144.5`).
3. Проверен tag исходников именно установленной версии `rust-v0.144.5` (`87db9bc…`) и upstream HEAD `5c0e582…` от 2026-07-18 [5][6][7].
4. Проверен текущий `app/backend_codex.py` и его token/cost pipeline.
5. Из `~/.codex/sessions/2026/07/**/*.jsonl` извлекались только metadata и `token_count`; содержимое сообщений не читалось. До запуска критерий был таким: ненулевой hit после паузы даёт lower bound retention; zero hit не доказывает expiry без доказательства byte-identical prefix. Точный read-only parser сохранён в `measure_rollouts.py` рядом с этим документом.

### Measurement snapshot

Срез зафиксирован на `2026-07-18T07:43:00Z`. Фильтр: CLI `0.144.5`, модель `gpt-5.6-sol`; для gap-анализа исключены пары с compaction между calls и сменой модели.

| Метрика | Результат |
|---|---:|
| Rollout files с usage после фильтров | 37 |
| Sol model calls | 1,969 |
| Sessions | 35 |
| Input / cached / fresh tokens | 241,677,391 / 232,209,664 / 9,467,727 |
| Weighted cache ratio | **96.08%** |
| First-call sessions с видимым cache hit | 28 / 35 |
| First-call median visible cache ratio | 40.06% |
| Cache-write tokens в protocol CLI 0.144.5 | **не доступны: field отсутствует** |
| Exact duplicate `token_count` events removed | 1 |

Gap results:

| Пауза между model calls | N | Ненулевой hit | Median cache ratio | Range |
|---|---:|---:|---:|---:|
| `<5m` | 1,901 | 1,879 | 98.31% | 0–99.92% |
| `5–10m` | 8 | 8 | 98.33% | 4.24–99.48% |
| `10–30m` | 5 | 3 | 96.23% | 0–98.96% |
| `30–60m` | 2 | 1 | 48.60% | 0–97.19% |
| `2–6h` | 1 | 1 | 16.30% | 16.30% |
| `12–24h` | 2 | 0 | 0% | 0% |

Конкретные long-gap calls: после **31.2 min** — `126,720 / 130,382` cached (**97.19%**); после **57.4 min** — `0 / 178,151`; после **282.7 min** — `9,984 / 61,258` (**16.30%**); после 15.1 h — zero hit в двух sessions. Только 31.2-minute call даёт положительный lower bound для одного matching prefix. Остальные calls не различают expiry, prefix change, routing и startup/static prefix; совокупность данных **согласуется** с API policy, но не подтверждает её как CLI contract.

Внутренний `plan_type` в sample был смешанным и не следует напрямую трактовать как публичное название подписки:

| Internal plan label | Calls | Input | Cached | Cache ratio |
|---|---:|---:|---:|---:|
| `plus` | 684 | 71,290,070 | 68,205,568 | 95.67% |
| `prolite` | 1,285 | 170,387,321 | 164,004,096 | 96.25% |

Пара с gap 57.4 min пересекла `plus → prolite`, поэтому её нельзя использовать для проверки влияния плана или точного TTL. Aggregate подтверждает, что caching работал при обоих labels, но не доказывает одинаковую policy.

## Findings

### 1. Prompt caching есть; единица reuse — exact prefix внутри thread

**CONFIRMED — official API docs + installed CLI source + measurements.**

- OpenAI автоматически включает caching для prompts от 1,024 tokens. Hit требует exact prefix; static instructions/tools должны оставаться в начале и совпадать [1].
- GPT-5.6 использует `prompt_cache_key` для более надёжного matching. Codex CLI `0.144.5` ставит в этот key thread id и сохраняет его для всех requests thread [5].
- Cache — server-side. Новый subprocess сам по себе не уничтожает запись; важны thread key, exact prefix и retention.
- `cached_input_tokens` приходит в `response.completed.usage.input_tokens_details`, затем попадает в CLI `token_count` / JSONL. Это источник истины для hit; отдельного полезного `x-cache` header CLI не публикует [1][5].

В 28 из 35 first emitted `token_count` был partial hit, median 40.06%. Это **не опровергает экономический cold start**: CLI делает startup WebSocket prewarm с `generate=false`, а версия `0.144.5` не показывает cache-write tokens. Видимый generated call мог уже читать prefix, созданный ранее в том же startup по write/cold economics. Для whole-process cold penalty нужен controlled experiment с write counters либо credit deltas; текущий sample его не даёт.

### 2. API TTL GPT-5.6 — минимум 30 минут; CLI contract не опубликован

**CONFIRMED для API contract; LIKELY для ChatGPT-auth Codex endpoint — source не задаёт override, measurements согласуются.**

- Для GPT-5.6 единственный поддерживаемый `prompt_cache_options.ttl` — `30m`; он же default. Это **minimum lifetime**, не maximum: OpenAI может держать prefix дольше [1].
- Правило `5–10 min inactivity, максимум 1h` относится к старой `in_memory` policy моделей до GPT-5.6. Переносить его на Sol нельзя [1].
- Codex CLI `0.144.5` передаёт `prompt_cache_key`, но не передаёт `prompt_cache_options.ttl`/`prompt_cache_retention`, поэтому использует default своего ChatGPT-auth service [5]. Публичная документация не обещает, что этот private surface наследует API default. CLI help также не содержит cache/TTL flags.
- Measurement нашёл почти полный hit после 31.2 min, miss после 57.4 min и partial `9,984`-token hit после 4.7 h. Последний может быть static/startup prefix, а не прежняя conversation history. Следовательно, timer вида «hot до 60:00» для Sol будет ложной точностью.

Практическая индикация для dashboard: для ChatGPT-auth не показывать guaranteed `hot` timer вообще. Можно показывать **recent ≤30m** как ожидание, основанное на API policy и локальном наблюдении, а после 30m — **unknown**. Основной сигнал — последний observed cache hit, не fixed TTL.

### 3. `codex exec` против `codex exec resume`

**CONFIRMED — CLI help/manual + source.**

| Команда | Thread/transcript | `prompt_cache_key` | Cache consequence |
|---|---|---|---|
| `codex exec ...` | Новый thread | Новый thread id | First turn может получить partial internal hit, но full session-prefix reuse не гарантирован |
| `codex exec resume <SESSION_ID> ...` | Продолжает сохранённый thread | Тот же thread id | Старый exact prefix eligible для hit, если ещё удерживается и не изменён |

В CLI `0.144.5` resume — subcommand, не flag: `codex exec resume <SESSION_ID> "prompt"` или `codex exec resume --last "prompt"` [4]. Resume восстанавливает conversation даже после cache expiry, но тогда transcript нужно заново prefill-ить по fresh rate.

Текущая предпосылка задачи уже устарела: `app/backend_codex.py` теперь запускает persistent `codex app-server --stdio`, затем вызывает `thread/start` либо `thread/resume`; он больше не запускает отдельный `codex exec` на каждый Orchestra turn. Cache semantics при этом те же: thread id остаётся стабильным.

### 4. Cold-start penalty: 10x в Pro credits, до 12.5x в API-equivalent input

**CONFIRMED — official Codex/API pricing.**

Для ChatGPT subscription OpenAI публикует для Sol [3]:

- fresh input: **125 credits / 1M tokens**;
- cached input: **12.5 credits / 1M**;
- output: **750 credits / 1M**.

Значит один и тот же input prefix стоит **10x** credits cold против cached. Это input-only ratio; одинаковый output уменьшает ratio всего turn. Отдельного cache-write тарифа в Codex subscription rate card нет.

Для API-equivalent долларов Sol [1][2]:

- ordinary input: **$5 / 1M**;
- cached read: **$0.50 / 1M**;
- GPT-5.6 cache write: **$6.25 / 1M** (`1.25x` input);
- output: **$30 / 1M**.

Поэтому ordinary uncached/read = **10x**, а первый cache write/read = **12.5x**. Формула:

```text
API$ = ((I - R - W) * 5 + R * 0.5 + W * 6.25 + O * 30) / 1_000_000
credits = ((I - R) * 125 + R * 12.5 + O * 750) / 1_000_000

I = total input, R = cached reads, W = cache writes, O = output
```

На measurement snapshot текущая lower-bound модель Orchestra (без `W`) дала `$188.892` API-equivalent вместо `$1,233.836` при контрфактическом полностью uncached input: модель показывает **84.69%** reduction до неизвестной cache-write surcharge. Это не эмпирическая стоимость startup и не реальный дополнительный счёт. В subscription units опубликованная трёхколоночная rate card даёт `4,722.30` против `30,845.89` credits и ту же относительную разницу; Pro subscription остаётся фиксированной оплатой, а credits/rate limits отражают расход allowance.

### 5. Pro $100 5x не даёт отдельного TTL

**LIKELY — documentation-based; mixed local plan labels не позволяют независимо подтвердить H4.**

- Pro 5x увеличивает Codex usage/rate limits относительно Plus; официальный plan page не обещает больший TTL или другой cached-input discount [3].
- Из response headers/`codex.rate_limits` CLI извлекает used percent, window duration/reset и plan/credits metadata. Cache TTL/hit там нет; hit определяется token usage [5].
- Локальный sample содержит internal labels `plus` и `prolite`; он показывает caching при обоих, но не является controlled plan comparison. Практическая политика: считать Sol TTL и cache ratio одинаково для Plus/Pro, пока OpenAI не опубликует обратное. Pro влияет на доступный budget, не на документированный алгоритм prefix matching.

### 6. Preventive compact ради cache не нужен

**CONFIRMED как рекомендация из source mechanics; native Codex и Orchestra manual compact — разные операции.**

- `/compact` предназначен для освобождения context window, а не для продления prompt-cache TTL [4].
- **Native Codex compact:** remote compact request повторно использует тот же `prompt_cache_key`; сам compact может читать текущий cache, затем заменяет длинную историю summary-based context внутри того же thread [5]. Старый full-prefix cache это не «освежает».
- **Native auto-compact:** local model metadata даёт raw window `272,000`, effective UI/rollout window `258,400` (`95%`) и не задаёт отдельный limit. Codex выводит threshold как `90%` raw window, то есть `244,800` tokens — около `94.74%` displayed effective window [7]. Server model config всё ещё может задать меньший threshold.
- **Orchestra `compact_worker`:** `app/session.py:656-812` просит у старого agent handoff summary, disconnect-ит backend, делает `_ensure_backend(force_fresh=True)` и seed-ит новый thread summary-preamble. Это extra summary turn + новый cache key + ack turn; native compact-key reuse к этой кнопке не относится.
- Early compact в обоих вариантах создаёт работу и риск потерять execution-critical детали; Orchestra path дополнительно гарантированно начинает fresh thread. В issue tracker есть reports о progressive information loss после повторных native compactions [10][11].

**Рекомендация:** не делать TTL-driven precompact и не compact-ить idle Sol workers «чтобы оставить горячими». Оставить native auto-compact. Orchestra manual compact использовать только при context pressure или перед заведомо длинной фазой близко к лимиту, воспринимая его как компромисс context capacity vs fidelity, а не cache optimization.

### 7. Orchestra сейчас недосчитывает GPT-5.6 cache-write cost

**CONFIRMED — local code + installed/upstream protocol diff.**

В `app/backend_codex.py`:

- `_codex_cost()` считает `fresh * input + cached * cached + output`, без `cache_write` surcharge;
- `_usage_breakdown()` читает только `inputTokens`, `cachedInputTokens`, `outputTokens`;
- metadata всегда ставит `cache_create: 0`.

Установленный CLI `0.144.5` действительно не экспортирует cache-write field в `TokenUsage`, поэтому backend не мог посчитать его точно [6]. Upstream HEAD от 2026-07-18 уже добавил `cache_write_input_tokens` / `cacheWriteInputTokens` в protocol и app-server token usage [7]. После обновления CLI Orchestra сможет учитывать writes.

До этого dashboard `$` следует маркировать как **API-equivalent lower bound**. Точный диапазон при неизвестном `W`:

```text
lower = ((I-R)*5.00 + R*0.50 + O*30) / 1M
upper = ((I-R)*6.25 + R*0.50 + O*30) / 1M
```

## Counter-evidence и ограничения

- GPT-5.5 users сообщали почти zero cache hits; OpenAI collaborator сначала не увидел anomaly в server stats, затем reopened issue после других reports [9]. Это показывает, что cache regressions возможны и model-specific; результат Sol `96.08%` нельзя переносить на каждую модель/дату.
- Fresh app-server sessions с byte-identical startup context в одном report получили только около 55% cached; автор связал это с thread-id-specific `prompt_cache_key` [8]. Наш visible first-call median 40.06% согласуется с partial reuse, но из-за startup prewarm не измеряет whole-process cold cost.
- Gap measurement не контролировал byte-identical serialized requests, routing machine и скрытые server breakpoints. Поэтому hit доказывает survival конкретного prefix, а miss не доказывает expiry. Partial `9,984` hit после 4.7 h может быть startup/static prefix.
- Public docs определяют API contract. ChatGPT-auth Codex использует собственный endpoint и quota headers; отдельного public TTL contract для subscription surface нет. Поэтому `30m minimum` нельзя называть гарантией CLI: это только ожидаемая policy, совместимая с одним positive observation через 31.2 min.
- Sample смешивает internal `plan_type=plus` и `plan_type=prolite`; переход labels совпал с 57.4-minute miss. Он не подходит для controlled Plus-vs-Pro либо TTL comparison.
- First emitted usage не охватывает невидимую стоимость startup prewarm/write, а installed protocol не показывает `W`. Partial first-call hit не доказывает дешёвый whole-process cold start.
- Installed `0.144.5` скрывает cache-write tokens. Из-за этого measured cost — lower bound, а theoretical `12.5x` API write/read взят из official pricing, не из локального `W` measurement.

## Рекомендации для Orchestra

1. **Session lifecycle:** продолжать `thread/resume`; не создавать новый thread для каждого turn. Не убивать worker только ради cache, но и не держать его процесс живым ради TTL — server cache зависит от key/prefix, а не PID.
2. **Cache status:** для ChatGPT-auth Codex поставить contractual `cache_ttl=null`, сохранить отдельно API reference `api_min_ttl=1800` и empirical `observed_survival_lower_bound=1872s`. В UI: `recent ≤30m` без обещания hit, затем `unknown`; основной индикатор — последний observed `cache_hit`.
3. **Compaction:** убрать идею TTL-driven precompact для Codex. Полагаться на native auto-compact; Orchestra fresh-thread manual compact — только по context pressure/fidelity decision.
4. **Accounting now:** считать subscription credits и API-equivalent `$` отдельно. Для CLI `0.144.5` показывать `$` как lower bound.
5. **Accounting after CLI upgrade:** прочитать `cacheWriteInputTokens`, протянуть его через `_read_rollout_*`, `_usage_delta`, app-server notification и metadata `cache_create`; применить `$6.25/M` для Sol writes.
6. **Parallel workers:** не рассчитывать на full cache sharing между разными threads. Stable shared cache key сейчас не является публичным app-server control; оптимизировать общий static prefix всё равно полезно, но savings измерять first-turn telemetry.

## Affected files / риски / edge cases

- `app/backend_codex.py` — cache-write parsing, cost formula, model cache policy, metadata.
- `tests/test_backend_codex.py` и `tests/test_codex_usage.py` — fixtures с `cacheWriteInputTokens`, cold/write/read formulas, resume gaps.
- Dashboard/cache status consumer — не применять Claude 1h semantics к Codex.
- Edge cases: cache write field отсутствует на CLI `0.144.5`; cached/write counters могут быть cumulative; native compact и Orchestra fresh-thread compact имеют разные semantics; compaction/model/plan transition сбрасывают сопоставимость; first emitted usage может скрывать startup write; exact prefix ломается при изменении developer instructions, tools/MCP schemas или порядка content.

## Sources

1. **Tier 2 — primary official docs:** OpenAI Prompt Caching, включая GPT-5.6 `30m` minimum TTL, exact-prefix rules, write/read accounting. https://developers.openai.com/api/docs/guides/prompt-caching
2. **Tier 2 — primary official docs:** OpenAI API Pricing, GPT-5.6 Sol `$5 / $0.50 / $6.25 / $30` per 1M input/cached/write/output. https://developers.openai.com/api/docs/pricing
3. **Tier 2 — primary official docs:** Codex Pricing, Pro 5x limits и Sol `125 / 12.5 / 750` credits per 1M input/cached/output. https://learn.chatgpt.com/docs/pricing
4. **Tier 2 — primary official docs:** Codex developer commands/manual: `exec resume`, `/compact`, `/status`, `/usage`. https://learn.chatgpt.com/docs/developer-commands
5. **Tier 2 — primary source code:** Codex CLI `rust-v0.144.5`, thread-id `prompt_cache_key`, request construction и compact key reuse. https://github.com/openai/codex/blob/87db9bc18ba5bc82c1cb4e4381b44f693ee35623/codex-rs/core/src/client.rs
6. **Tier 2 — primary source code:** Codex CLI `rust-v0.144.5` `TokenUsage` (без cache-write field). https://github.com/openai/codex/blob/87db9bc18ba5bc82c1cb4e4381b44f693ee35623/codex-rs/protocol/src/protocol.rs
7. **Tier 2 — primary source code:** Codex upstream `5c0e582` от 2026-07-18: 90% auto-compact policy и новый `cache_write_input_tokens`. https://github.com/openai/codex/blob/5c0e582c59892dbec89af78ae62c784d3da6c9cb/codex-rs/protocol/src/openai_models.rs and https://github.com/openai/codex/blob/5c0e582c59892dbec89af78ae62c784d3da6c9cb/codex-rs/protocol/src/protocol.rs
8. **Tier 4 — single community measurement:** openai/codex #21796, partial cache reuse across fresh app-server threads and thread-id key analysis. https://github.com/openai/codex/issues/21796
9. **Tier 4 — community reports + OpenAI collaborator response:** openai/codex #20301, low GPT-5.5 cache hits. https://github.com/openai/codex/issues/20301
10. **Tier 4 — single community analysis:** repeated compaction information loss, #14347. https://github.com/openai/codex/issues/14347
11. **Tier 4 — single community experiment:** compact drops tool/reasoning detail, #14589. https://github.com/openai/codex/issues/14589
12. **Tier 1 — direct measurement:** local CLI help/source inspection and 1,969 deduplicated `gpt-5.6-sol` model calls from 35 sessions, snapshot cutoff `2026-07-18T07:43:00Z`; exact metadata-only parser: `docs/tasks/codex-cache-research/measure_rollouts.py`.

## Adversarial second opinion

Codex review сначала вернул **NEEDS CHANGES**: блокирующим было превращение 30-minute API guarantee в ChatGPT-auth guarantee. Дополнительно review нашёл prewarm confounder, mixed plan labels, различие native/Orchestra compact, ошибку `232,560 → 244,800`, один duplicate usage event и пропущенный model-transition filter. После исправлений и повторной проверки parser/cost arithmetic Round 3 завершён вердиктом **APPROVED**; полный протокол — `codex-review-research.md`.
