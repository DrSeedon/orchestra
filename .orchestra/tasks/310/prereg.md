# #310 — предрегистрация Luna Standard ↔ Fast

Записано 17.08.2026 **до первого вызова модели**. До этой записи выполнены только чтение
принятой методики #208, чтение текущего pricing source, официальный docs lookup и локальный
`--self-test`; ни `turn/start`, ни иной model call для #310 не выполнялся. Confirmatory
критерии, порядок, fixture, grader и формулы после первого model call не меняются. Любая
починка стенда после model call аннулирует затронутый pilot/confirmatory run и требует явной
пометки excluded; пилоты никогда не попадают в подтверждающую выборку.

## Вопрос (research-method Step 0)

- **Контекст:** Codex CLI с ChatGPT auth, `gpt-5.6-luna`, effort `medium`, fully specified
  tool-free leaf task с большим lookup-контекстом и exact JSON contract.
- **Изменение:** Fast service tier (`serviceTier="fast"`, wire response ожидается
  `priority`).
- **Baseline:** Standard (`serviceTier=null`, wire response ожидается `default`) на той же
  модели, effort, fixture и app-server.
- **Измеряемый исход:** paired TTFT/wall; completion/error/reroute; exact PASS; input/cache
  read/cache write/output/reasoning tokens; локальная Luna API-equivalent цена; официальный
  Fast-credit proxy `2.5 ×`; exact-PASS throughput и exact-PASS на local-dollar/proxy-dollar.

Главный вопрос: может ли Luna Fast быть разумным default или хотя бы явным маршрутом для
полностью заданных latency-sensitive leaf tasks? Эксперимент не проверяет агентные цепочки,
tools, редактирование кода, review или открытый reasoning.

## Гипотезы и falsifiers (Step 1)

**H1 — Fast полезен как явный latency-route.** При одинаковом содержании Fast уменьшает
user-visible latency без наблюдаемого reliability/quality-дефекта. Falsifier: median paired
speedup `Standard/Fast <= 1` в любой из cold/warm wall-ячеек; model reroute/tool/error;
незавершённый turn; либо exact discordance, где только Standard проходит не менее двух
пар, а только Fast — ни одной.

**H2 — Fast разумен как default leaf-route.** Помимо H1, цена дополнительной скорости не
ухудшает доставку точного результата на официальном credit proxy. Falsifier: Fast имеет
ниже exact-PASS throughput (`PASS / total wall`) или ниже `PASS / (local cost × 2.5)` при
том, что Standard имеет хотя бы один PASS. Это строгий default-gate, а не утверждение, что
равенство малой выборки доказывает non-inferiority.

**H3 — end-to-end выигрыша нет.** Luna generation настолько коротка или prefill/queue/local
overhead настолько велики, что 1.5× заявленное model-speed не сокращает доставленный turn.
Falsifier: median paired TTFT и wall speedup `>1` в обеих cold/warm ячейках и не менее 5/6
пар каждой wall-ячейки быстрее на Fast. Bootstrap CI остаётся описательным при N=6.

**H4 — included-credit burn нельзя атрибутировать стенду.** Целочисленный общий primary
счётчик и чужие Codex turns смешивают arms. Falsifier: нет ни одного foreign Codex
`turn_usage`, `resets_at` стабилен и provider snapshots дают чистый пост-переходный отрезок.
Иначе provider layer получает только `UNIDENTIFIED`; официальный `2.5×` используется как
документированный proxy, а не как измеренная дельта живого счётчика.

## Замороженный протокол

- Reuse принятого `docs/tasks/208/fast_bench.py` из current main
  `f7fa7eb70296ce785f58fa83c9cdf3a93e48766b`, source SHA-256
  `4fd2e878e3f50081cd5f731ee75fdac01500204ef71dea2421585d0e8c396ed4`.
- `bench.py` загружает этот source и делает только проверяемые substitutions: model
  `gpt-5.6-sol→gpt-5.6-luna`; local price table `$5/$0.5/$6.25/$30 →
  $0.2/$0.02/$0.25/$1.2`; output → `results.json`; cache-buster namespace `208→310`.
  Seeds records/questions, schema, grader, schedule, timing and analysis остаются побайтно
  логически теми же, что #208.
- Frozen adapter SHA-256:
  `fb644df3270717ed10c06e6282cb45e4f1863c12a88deecb5fe2cc5fe10f0d51`.
  Pre-call `python3 docs/tasks/310/bench.py --self-test` → `PASS`, cold `127190` chars,
  warm `1202`, answers SHA-256
  `28b8b79c901d505352e64e36a3cc2e6b3e2b14caa5fa23ddff85668732e0d6b6`.
- Effort `medium`, как в #208. Один isolated app-server на весь run; отдельный временный
  `CODEX_HOME` с symlink только на auth; глобальный config/runtime не меняются.
- 6 пар на tier × cold/warm = **24 confirmatory turns**. Fixed AB/BA order:
  `N0,F0,F1,N1,N2,F2,F3,N3,N4,F4,F5,N5`.
- Перед ними один Standard и один Fast pilot с replicate 999 = 4 turns. Pilot обязан
  подтвердить service tier, completion, usage и TTFT telemetry; он навсегда excluded.
- В каждой реплике 1 800 детерминированных records; cold содержит 24 двухшаговых lookup,
  warm — другие 24 по тем же records. Pair arms получают одинаковые records/questions.
  Cold имеет task-310 cache-buster, не участвующий в ответе; warm — второй turn того же
  ephemeral thread.
- Exact grader сравнивает весь массив из 24 объектов `{q, final, sum}`. Любое отличие —
  FAIL; parse/schema mismatch не частично засчитывается. Tools запрещены, но каждый фактический
  tool call/error сохраняется.
- TTFT = `turn/start` write → первый непустой `item/agentMessage/delta`; также хранится первый
  model delta. Wall = `turn/start` write → `turn/completed`.
- Usage = последний `thread/tokenUsage/updated.last`. Хранятся `inputTokens`,
  `cachedInputTokens`, `cacheWriteInputTokens`, `outputTokens`, `reasoningOutputTokens`.
- Local Luna API-equivalent estimate использует current-main
  `app/backend_codex.py:CODEX_TOKEN_PRICES`: fresh input `$0.20/M`, cached `$0.02/M`,
  cache write `$0.25/M`, output `$1.20/M`. `inputTokens` включает cached/write; fresh
  вычисляется как `input - cached - write`. Provider dollars это не выдаёт.
- Credit-weighted proxy: Standard `local_cost × 1`; Fast `local_cost × 2.5`. Это
  чувствительность к официальному ChatGPT credit multiplier, не API bill и не измерение
  included counter.
- `/api/usage` primary снимается before/after каждого turn. Каждый foreign Orchestra Codex
  turn между baseline/final извлекается через `sqlite3.Connection.backup` живой WAL-БД;
  raw rows и интервальная атрибуция сохраняются в `results.json`.

## Зафиксированный анализ

- Latency: paired ratios `Standard/Fast`, median, 20 000 fixed-seed bootstrap resamples и
  percentile 95% interval отдельно cold/warm для TTFT/wall; число Fast-faster pairs и
  two-sided exact sign-test сообщаются отдельно. Bootstrap при N=6 — descriptive.
- Quality: exact PASS по arm/phase и суммарно; Wilson 95%; paired discordance
  both/Standard-only/Fast-only/neither и exact McNemar/binomial test для discordant pairs.
- Reliability: completed/errors/tool calls/tool errors/reroutes — точные counts.
- Throughput: `exact_passes / total_wall_seconds` и обратная величина
  `wall_seconds / exact_pass`; отдельно без смешения cold/warm и aggregate.
- Efficiency: `exact_passes / local_API_equivalent_$`, `$ / exact_pass`, затем то же для
  documented-credit proxy (Fast denominator ×2.5, Standard ×1). Нулевой PASS → denominator
  metric `null`, а не бесконечность.
- Сравнение с #208 Sol: те же fixture/grader/order/effort и метрики; сравниваются только
  описательные ratios/quality/cost-efficiency. Нельзя приписывать модели различия времени
  суток, нагрузки, entitlement, cache или stochastic output.

## Decision rule

1. **Default candidate** только если H1 не опровергнута, Fast exact PASS не ниже Standard,
   exact-PASS throughput не ниже Standard и exact-PASS на `2.5×` proxy-dollar не ниже
   Standard. При N=12 формулировка остаётся «candidate», не общий production verdict.
2. **Explicit latency route** если default-gate не пройден, но H1 не опровергнута и Fast
   даёт наблюдаемое ускорение обеих wall-ячеек без arm-specific reliability/quality дефекта.
3. **Не маршрутизировать** если H1 опровергнута. Один schema-constrained corpus не может
   обосновать route за пределами fully specified tool-free leaf tasks.

## Стоп и integrity

- Немедленный stop: tier mismatch, model reroute, reset-window change, missing usage/TTFT,
  failed pilot instrumentation, direct local-cost cap или turn timeout.
- Pilots не заменяются confirmatory rows и никогда не входят в N=24.
- После run независимый checker заново читает raw turns и проверяет: schedule/pair identity,
  24 confirmatory + 4 excluded pilot turns, tier/model/status, token invariants, exact grade
  по скрытым deterministic fixture answers, summary arithmetic, local/proxy cost, timestamps,
  foreign rows against a second WAL-safe backup, source/harness hashes and secret-form scan.
- Минимальные secret patterns: `y0_`, `sk-or-v1-`, `ya29.`, `gh[pousr]_`, `AIza`,
  `Bearer <25+>`; ids/hashes в артефакте не считаются секретами.

## Primary source snapshot

Свежий Codex Manual, `Speed`, fetched 17.08.2026: Fast заявлен как `1.5×` model speed;
GPT-5.6 Fast расходует `2.5×` Standard credits; API Priority — отдельный режим/биллинг.
Source: https://learn.chatgpt.com/docs/agent-configuration/speed.md
