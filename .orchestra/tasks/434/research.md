# #434 — Claude Fable 5.1: качество, кеш, подписка и расход пула

Дата среза: 2026-09-02 (Asia/Krasnoyarsk; живые пробы 2026-09-01 UTC).

## Question

- **Context:** Orchestra работает через Claude Max; доллары в дашборде — виртуальный API-эквивалент, фактический ограничитель — пятичасовое и недельное подписочные окна.
- **Change under test:** заменить или дополнить Claude Opus 5 моделью Claude Fable 5.1.
- **Baseline:** `claude-opus-5[1m]` в том же репозитории, с тем же prompt и effort.
- **Outcomes:** (1) п.п. `five_hour`/`seven_day`; (2) фактический reuse cache между отдельными CLI-процессами; (3) покрытие Max; (4) успех на существующем детерминированном оракуле.

## Hypotheses considered and falsifiers

1. **H1: Fable 5.1 не переиспользует кеш между отдельными CLI-процессами.** Фальсификатор: второй и третий отдельные вызовы дают высокий `cache_read_input_tokens` и нулевой `cache_creation_input_tokens`. **REFUTED:** Fable-2 и Fable-3 дали `86,317 read / 0 create`.
2. **H2: предыдущий промах кеша вызван истечением короткого TTL за несколько минут.** Фальсификатор: новый cache write помечен как 1h, а повтор за минуты остаётся холодным. **LIKELY REFUTED для текущего Claude Code:** первый Fable write — `ephemeral_1h_input_tokens=76,085`, а повтор через ~2.5 минуты полностью прочитал кеш. TTL первого, присланного постановщиком опыта не записан, поэтому причина именно того опыта остаётся открыта.
3. **H3: первый вызов холодный или меняется динамический prefix, после стабилизации prefix кеш работает.** Фальсификатор: три байт-одинаковых команды продолжают пересоздавать большую часть контекста. **SUPPORTED:** Fable прошла `11.85% → 100% → 100%` cache hit; Opus — `11.96% → 16.07% → 100%`.
4. **H4: снижение API-цены cache read снижает расход недельного Max-окна.** Фальсификатор: matched Opus/Fable двигают подписочные counters одинаково либо официальный источник ограничивает скидку token-billed surfaces. **UNCERTAIN, с отрицательным уклоном:** блог ограничивает скидку формулировкой «wherever usage is billed by token, such as on our API»; Fable-specific weekly counter не пересёк даже 1 п.п., поэтому измерение не различает веса.
5. **H5: Fable 5.1 лучше Opus 5 на наших закрытых задачах.** Фальсификатор: matched tickets с заранее существующим RED-оракулом не дают роста pass rate/steps-to-green. **UNTESTED:** весь разрешённый Fable-бюджет ушёл на cache/subscription discriminator; запускать слабый субъективный judge запрещено постановкой.

## Protocol and measurement limits

- Последовательность заморожена в `run_cache_probe.py`: Opus/Fable/Opus/Fable/Opus/Fable; prompt `Reply with exactly PONG and nothing else.`; отдельный CLI-процесс на вызов; `effort=high`; никакой параллельности.
- Бюджет: не более 3 п.п. пятичасового окна на Fable. Первый Fable-вызов наблюдаемо дал +1 п.п.; после 429 ещё два вызова консервативно учтены по +1. Консервативный итог = 3 п.п.; видимое движение общего окна за всю серию = 6→8%, то есть +2 п.п. вместе с тремя Opus-вызовами и чужой активностью.
- `GET /api/usage` **не является свежим per-call oracle:** `_USAGE_CACHE_TTL = 300` и ветка возврата кеша находятся в `app/routes/system.py:562,1028-1034`. Fresh upstream `https://api.anthropic.com/api/oauth/usage` дал 6→7% вокруг Fable-1, затем ответил 429. Локальный кеш обновился плановым снимком в `2026-09-01T18:22:05.247861+00:00` и показал 8%/2%/Fable 1%.
- Следствие: точный model-specific коэффициент подписочного burn этим коротким опытом **не измерен**. Доступные counters целочисленные, общий аккаунт разделяют другие потребители, а upstream не разрешил требуемую частоту опроса.
- Raw evidence: `cache-probe.jsonl`; executable protocol: `run_cache_probe.py`.

## Findings

### 1. Официальный анонс и качество производителя

**CONFIRMED как заявление производителя; UNCONFIRMED на наших задачах — primary source, но не независимый oracle.**

Официальная страница Anthropic [1] перечисляет Fable 5.1 / Opus 5:

| Benchmark | Fable 5.1 | Opus 5 |
|---|---:|---:|
| Terminal-Bench-Science 0.1 | 52.6% | 29.0% |
| Terminal-Bench 4.0 | 55.8% | 52.3% |
| GDPval-AA v2 | 1853 | 1824 |
| OSWorld 2.0 partial | 77.9% | 75.4% |
| AutomationBench | 31.4% | 26.9% |
| CursorBench 3.2.0 | 73.4% | 70.0% |

Ограничения самой страницы:

- Terminal-Bench-Science имеет standard error ±3.5–4.5 п.п.; разрыв 23.6 п.п. крупный, но это всё ещё замер производителя.
- OSWorld использует August 2026 task release и не сравним с прежними публичными числами.
- Safeguards были включены: на некоторых OSWorld-задачах Fable получала 0; на других cyber/bio вмешательствах ответ завершали Opus 4.8/Opus 5. Это одновременно занижает benchmark Fable и доказывает, что выбранная модель не всегда исполняет весь агентный цикл сама.
- Детерминированного сравнения на наших RED-тикетах не было. Формулировка «Fable 5.1 доказанно лучше у нас» запрещена данными.

### 2. Цена кеша: скидка настоящая, но только token-billed

**CONFIRMED — primary source [1].**

- API model id: `claude-fable-5-1`.
- Base input/output без изменений: $10/M и $50/M.
- Cache read: −75%, $0.25/M, то есть `0.025×` base input и вдвое дешевле Opus 5 cache read ($0.50/M).
- Anthropic заявляет около −25% typical и до −45% highly-agentic против Fable 5. Footnote: usage-based pricing, default effort, четыре недели actual August 2026 usage.
- Страница дословно ограничивает эффект поверхностями, где usage billed by token, «such as on our API». Про снижение subscription-window weights страница не говорит.

### 3. Кеш в нашем текущем Claude Code реально переиспользуется

**CONFIRMED — direct measurement, tier 1.**

| Call | Cache read | Cache create | Hit share | Virtual API $ | Wall |
|---|---:|---:|---:|---:|---:|
| Opus-1 | 10,235 | 75,353 | 11.96% | 0.7597 | 8.404s |
| Fable-1 | 10,232 | 76,085 | 11.85% | 1.5255 | 6.459s |
| Opus-2 | 13,739 | 71,730 | 16.07% | 0.7252 | 8.411s |
| Fable-2 | 86,317 | 0 | 100% | 0.02279 | 7.967s |
| Opus-3 | 85,469 | 0 | 100% | 0.04381 | 7.929s |
| Fable-3 | 86,317 | 0 | 100% | 0.02279 | 12.753s |

- Warm Fable read действительно стоит примерно половину warm Opus в виртуальном API-эквиваленте.
- Cold Fable стоит примерно 2× cold Opus.
- Первый Fable write был 1h; следовательно, «14k read / 71k create на втором вызове» из входа задачи не является постоянным свойством модели. Тот опыт не сохранил TTL и точные байты динамического prompt prefix, поэтому его причину восстановить нельзя.
- Opus тоже не прогрелся полностью со второго раза, а с третьего прогрелся. Это counter-evidence против диагноза «особая поломка кеша Fable».

### 4. Cache-heavy дешевле только при достаточном reuse; cache-write TTL меняет знак

**CONFIRMED арифметически на измеренных токенах и официальных ценах; относится только к API-эквиваленту.**

Пусть `I/R/W/O` — fresh input / cache read / cache write / output tokens. Тогда Fable 5.1 дешевле Opus 5:

- при 5m cache write: `R > 20I + 25W + 100O`;
- при 1h cache write: `R > 20I + 40W + 100O`.

Формула `R > 20I + 100O` неверна: она теряет cache write, который после скидки становится главным штрафом.

Read-only срез `turn_usage` по Opus 5 с 2026-08-03: 2,536 turns; `I=60,639`, `R=6,397,688,064`, `W=131,746,289`, `O=11,692,213`; shares 0.0009% / 97.8062% / 2.0141% / 0.1787%.

- 5m pricing (текущий исторический калькулятор Orchestra): Opus $4,314.87; Fable 5.1 $3,831.47; ratio **0.888×**.
- 1h pricing (как в прямом CLI-probe): Opus $4,808.92; Fable 5.1 $4,819.56; ratio **1.002×**.

Следствие: тезис «Fable дешевле для оркестраторов» верен для нашего исторического cache-heavy профиля **только если managed backend сохраняет 5m economics и высокий hit rate**. Прямой CLI пишет 1h; перенос результата на `claude-agent-sdk` до добавления модели не доказан.

### 5. Max покрывает Fable 5.1, но скидка не добавляет лимит

**CONFIRMED entitlement; UNCERTAIN subscription weighting.**

- Официальный Help Center [2] говорит: на Max Fable — standard part плана, можно потратить до 50% общего weekly limit, Fable draws from regular weekly limits и uses them faster; это не дополнительные 50%.
- Fable 5.1 запустилась при `extra_usage.is_enabled=false` и `user_disabled=true`; живой usage ответ содержит `weekly_scoped`, `display_name=Fable`, `percent=1`. Это подтверждает, что текущий Max entitlement включает новый exact model id без usage credits.
- Начало опыта: fresh 5h/7d/Fable = 6%/1%/1%. После Opus-1: 6%/1%/1%. После Fable-1: 7%/1%/1%. Поздний общий снимок после Opus-2+Fable-2: 8%/2%/1%; дальше не менялся.
- За всю диагностическую серию общий weekly counter пересёк не более одной границы 1 п.п.; Fable-scoped counter не пересёк границу 1 п.п. Точный вклад Fable меньше разрешения наблюдения и смешан с Opus/другими потребителями.
- Ни официальный анонс, ни короткий замер не доказывают, что $0.25/M меняет subscription weighting. Для routing безопасная презумпция: **не меняет, пока matched long-window measurement не покажет обратное**.

### 6. Спецификация и safeguards

**CONFIRMED — system card [3] + live CLI.**

- Knowledge cutoff: June 2026.
- Thinking нельзя отключить в Fable 5.1 API; Claude Code default effort — High, Cowork/Claude.ai — Medium [1][3].
- System card называет production API output limit 128k. Live Claude Code JSON в этом опыте сообщал `maxOutputTokens=64,000` для Fable и 32,000 для Opus; это текущая CLI-конфигурация вызова, а не опровержение API-cap.
- Benign single-turn over-refusal в system card ниже Opus: API 0% против 0.09%; Claude.ai 0.34±0.06% против 0.47±0.08%. Утверждение «Fable чаще отказывается на обычной работе» **REFUTED этим evaluation**, хотя это всё ещё исследование производителя.
- На adversarial prompt-injection benchmark fallback был 23% overall и примерно в половине coding rollouts; это не оценка обычного coding traffic. В long ProgramBench 72% episodes имели хотя бы один fallback, но fallback затронул <1% turns. Риск замены модели внутри длинной траектории реален, его частота на наших задачах неизвестна.

## Counter-evidence and unresolved gaps

- Benchmarks и refusal data — Anthropic evaluating Anthropic; независимого 5.1 benchmark на дату среза нет.
- Warm-cache success не объясняет старый частичный hit. Возможные причины: отличавшийся dynamic prefix, другой cache TTL, rollout/config до CLI 2.1.257. Без старого raw JSON различить нельзя.
- Подписочный counter округлён до 1 п.п.; upstream usage API rate-limited; общий аккаунт имеет внешних потребителей. Exact Fable-vs-Opus weekly multiplier не измерен.
- Качество на наших закрытых тикетах не измерено из-за исчерпания разрешённого Fable-бюджета.
- Direct CLI использовал 1h cache write; будущий Orchestra managed backend работает через другой runtime seam. Нужен production-shaped proof после отдельного решения добавить модель, но до широкого routing.

## Decision branches with cost

### A. Не вводить сейчас — recommended

- Дополнительный недельный расход: **0 п.п.**
- Цена решения: остаёмся на Opus и не получаем возможный quality uplift/тёплый API-эквивалент 0.888×.
- Основание: ключевой subscription multiplier не измерен; качество на наших oracles не измерено; Fable имеет отдельный 50%-й ceiling общего weekly limit.

### B. Узкий canary для cache-heavy долгой сессии — только после отдельного решения пользователя

- Предварительный бюджет: не более **1 п.п. Fable-scoped weekly** и matched Opus/Fable, один consumer, без параллельности. Точный task cost до прогона неизвестен; сегодняшняя вся серия пересекла ≤1 п.п. общего weekly и 0 видимых Fable-scoped п.п.
- Приёмка: заранее существующий RED-оракул + fresh provider snapshots с интервалом, разрешённым rate limit + cache TTL/type из raw usage.
- Имеет смысл только для cache-heavy профиля; для output-heavy worker Fable платит 2× output и легко проигрывает.

### C. Широкий default

- Потенциальный расход: до **50 п.п. общего weekly limit** на Fable, после чего Fable в плане исчерпана; это не добавочная полоса.
- **REJECTED текущими данными:** exact subscription economics и наша quality delta неизвестны; отдельный scoped ceiling делает Fable непригодной единственным default.

## Verdict

**Fable 5.1 выглядит сильной по первичным benchmark-данным, а её дешёвый cache read настоящий и в нашем CLI реально достигает 100% hit. Но для нашей подписочной экономики скидка не доказана: официально она относится к token-billed usage, а короткий counter-test не разрешил model-specific weekly weight. Не добавлять широко и не менять `app/models.py`; следующий законный шаг — отдельный узкий matched canary после решения пользователя.**

## Affected files, risks, edge cases for any future plan

- `app/models.py` — exact model id и pricing; **не изменён по прямому запрету**.
- `app/backend_claude.py` / Agent SDK cache-control — нужно доказать 5m vs 1h write economics и hit rate на managed path.
- quota mapping/admission — Fable имеет общий weekly + scoped 50% limit; нельзя смотреть только на общий Anthropic counter.
- safeguards may fallback to Opus mid-trajectory; tests must record actual canonical model per turn.
- Output-heavy workers and cold starts can cost ~2× API-equivalent even when warm reads are 0.5× Opus.

## Review decision gate inputs

- Changed files/consumers: только `docs/tasks/434/*`; production consumer отсутствует.
- Author metadata: `research-fable51`, runtime `codex`, model `gpt-5.6-sol` (live `sessions` row).
- AC: ответить про quality/cache/Max/pool routing; ≤3 п.п. Fable five-hour; no swarm; `app/models.py` untouched.
- Checks: raw `cache-probe.jsonl`; exact SQL and arithmetic above; official HTML SHA-256 `89d04e91364cf8f5d10f8502a89030914b6bed4e0a9ed9a4374601d270e875d3`; system-card PDF SHA-256 `b0d59edc7a60eef32a879c13d713cce60c3fefd7e6b5183afdc8b835af3c8c39`.
- Route: causal/statistical conclusion would route to Sol, but auxiliary Sol review is not authorized. One Luna fact/completeness pass is allowed by `codex-debate`.
- Outcome: Luna timed out after independently confirming the narrow cache claim and both pricing calculations; no final verdict and no blocking finding were emitted. Recovery: `review-research-luna.md`.

## Candidate KB promotion (not applied due explicit `docs/tasks/434/` write boundary)

- `fact:fable51-cache-economics` · искать: `Fable 5.1`, `cache read`, `0.25`, `subscription` · Fable 5.1 cache read is $0.25/M only on token-billed surfaces; current CLI warmed to 100% reuse, but subscription-window weighting remains unmeasured · evidence: this file + `cache-probe.jsonl` · 2026-09-02 #434.
- `fact:api-usage-five-minute-cache` · искать: `/api/usage`, `300`, `force refresh` · `/api/usage` caches Anthropic telemetry for 300 seconds and cannot be used as a seconds-scale before/after oracle · evidence: `app/routes/system.py:562,1028-1034` + fresh 7% vs GET 6% in `cache-probe.jsonl` · 2026-09-02 #434.
- **Пробелы:** exact Fable-vs-Opus weekly multiplier; managed SDK cache TTL/hit behavior; matched closed-ticket quality; ordinary-work fallback rate.

## Sources

1. **Tier 2 primary:** Anthropic, [Introducing Claude Fable 5.1 and Claude Mythos 5.1](https://www.anthropic.com/claude-fable-and-mythos-5-1), fetched 2026-09-02.
2. **Tier 2 primary:** Anthropic Help Center, [Claude Fable 5 on your plan](https://support.claude.com/en/articles/15424964-claude-fable-5-on-your-plan), fetched 2026-09-02.
3. **Tier 2 primary:** Anthropic, [Claude Fable 5.1 & Claude Mythos 5.1 System Card](https://www.anthropic.com/claude-fable-5-1-mythos-5-1-system-card), fetched 2026-09-02.
4. **Tier 1 direct measurement:** `docs/tasks/434/cache-probe.jsonl`, `docs/tasks/434/run_cache_probe.py`.
5. **Tier 1 direct measurement:** read-only SQLite query over `/mnt/data/Projects/Python/orchestra/data/orchestra.db`, `turn_usage`, Opus 5 rows since `2026-08-03` (2,536 rows at query time).
6. **Tier 2 primary code:** `app/routes/system.py:562,623-640,1028-1034` — upstream and 300-second cache behavior.
