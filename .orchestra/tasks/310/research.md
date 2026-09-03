# #310 — Luna Standard ↔ Fast: Phase 1 research

**Вердикт:** на измеренном fully specified tool-free leaf workload Luna Fast годится как
**явный latency-route**, но не проходит предзарегистрированный gate на **default**. Fast был
быстрее Standard во всех 6/6 cold и 6/6 warm парах: median wall speedup `1.397×` cold и
`1.288×` warm. Все 24 confirmatory turns завершились без tools, errors или reroutes. Exact
PASS остался очень низким и статистически неразличимым (`1/12` Standard, `2/12` Fast;
McNemar `p=1.0`). На локальном API-equivalent `$` Fast выглядит лучше из-за одного
дополнительного PASS, но после официального `2.5×` credit proxy даёт `8.05` exact PASS/$
против `9.93` у Standard — на `18.9%` хуже. Поэтому включать его разумно только когда
несколько секунд latency ценнее quota; для default/batch route данных недостаточно.

Дата прямого замера: 17.08.2026, 08:30:35–08:41:08 UTC. Raw artifact:
`docs/tasks/310/results.json`, SHA-256
`9aa7f3d5550e7a14dea1b722e63f664c1a9f3e832929c7d436e4e6637fa3977e` [2].
Предрегистрация и harness commit до первого model call: `649ae31b` [3].

## Вопрос и метод

- **Контекст:** Codex CLI `0.146.0`, ChatGPT auth, `gpt-5.6-luna`, effort `medium`.
- **Изменение:** Fast service tier, реально подтверждённый wire value `priority`.
- **Baseline:** Standard, wire value `default`.
- **Outcome:** paired TTFT/wall; completion/errors/reroutes; exact PASS; token/cache usage;
  local Luna API-equivalent `$`; официальный `2.5×` Fast-credit proxy; exact-PASS
  throughput и efficiency.

Принятая методика #208 переиспользована через frozen adapter: source #208 SHA-256
`4fd2e878...396ed4`, adapter SHA-256 `fb644df3...0f0d51`. Единственные смысловые substitutions:
Sol→Luna, Luna price table, task-local output и новый cold cache-buster namespace. Seeds,
1 800-record fixture, 24 lookup-вопроса на turn, exact grader, AB/BA schedule, timing и
summary logic не менялись [3][4].

Confirmatory sample: 6 paired replicates × Standard/Fast × cold/warm = **24 turns**.
Cold — новый ephemeral thread и 127 190-character prompt; warm — второй turn с 1 202-character
question block по тем же records. Два pilot threads (4 turns) выполнены раньше и навсегда
исключены: instrumentation/service tiers прошли, exact PASS был `0/4`.

## Findings

### 1. Fast устойчиво сократил доставленную latency этой fixture

| Cell | Standard median | Fast median | Экономия | Paired speedup S/F | Descriptive bootstrap 95% |
|---|---:|---:|---:|---:|---:|
| Cold TTFT | 17.309 s | 13.195 s | 4.114 s | **1.355×** | 1.200–1.540 |
| Cold wall | 24.154 s | 17.698 s | 6.456 s | **1.397×** | 1.244–1.508 |
| Warm TTFT | 12.462 s | 9.237 s | 3.225 s | **1.294×** | 1.033–4.612 |
| Warm wall | 18.684 s | 14.174 s | 4.510 s | **1.288×** | 1.126–3.331 |

Fast был быстрее во всех `6/6` cold-wall и `6/6` warm-wall парах; two-sided exact sign test
для каждой wall-ячейки даёт nominal `p=0.03125`. Все TTFT ratios также `>1`. Bootstrap
descriptive и особенно широк на warm из-за одного Standard outlier; при N=6 он не доказывает
общий multiplier задач.

Суммарный wall 12 Standard turns — `307.754 s`, Fast — `193.898 s`, aggregate delivered-turn
speedup `1.587×`. Эта цифра завышена относительно paired median одним warm примером:
replicate 2 занял `66.150 s` Standard против `13.100 s` Fast (`5.050×`), и оба ответа exact
PASS. Без post-hoc удаления outlier основной вывод всё равно держится на 12/12 wall-парах,
но aggregate ratio нельзя выдавать за типичную latency.

**Confidence: CONFIRMED для записанных timestamps; LIKELY для ускорения именно этой fixture.**
Это direct measurement tier 1 [2], но только шесть пар на cell.

### 2. Reliability одинакова; exact quality слишком низка для вывода о разнице

| Cell | Standard exact PASS | Fast exact PASS |
|---|---:|---:|
| Cold | 0/6 | 1/6 |
| Warm | 1/6 | 1/6 |
| Всего | **1/12** (Wilson 1.5–35.4%) | **2/12** (Wilson 4.7–44.8%) |

Paired table по 12 matched turns: both PASS `1`, Standard-only `0`, Fast-only `1`, neither
`10`; exact McNemar/binomial `p=1.0`. Единственный Fast-only PASS — replicate 1 cold;
replicate 2 warm прошёл на обоих tiers. Все остальные 10 matched queries exact FAIL на обоих.

- Confirmatory completed: `24/24`; pilot completed: `4/4` (excluded).
- Errors/warnings captured: `0`; reroutes: `0`; tier mismatches: `0`.
- Tool calls/tool errors: `0/0`.
- Output reason у всех FAIL — `answer_mismatch`, не JSON parse error.

**Confidence: CONFIRMED для counts; UNCERTAIN для качества tiers.** Одна discordant пара не
устанавливает преимущество Fast. Низкий потолок exact у Luna — важное counter-evidence против
переноса latency-вывода на leaf-задачи, где точность сложного lookup критична.

### 3. Tokens почти равны; local `$` почти равны; `2.5×` меняет efficiency verdict

Confirmatory only, pilots исключены:

| Метрика | Standard | Fast | Fast / Standard |
|---|---:|---:|---:|
| Turns / exact PASS | 12 / 1 | 12 / 2 | — |
| Input tokens | 783,377 | 783,334 | 1.000 |
| Cached input | 385,536 | 397,312 | 1.031 |
| Fresh input (`input-cache-write`) | 397,841 | 386,022 | 0.970 |
| Cache write | 0 | 0 | — |
| Output tokens | 11,223 | 11,839 | 1.055 |
| Reasoning output | 6,987 | 7,603 | 1.088 |
| Local API-equivalent `$` | **0.10074652** | **0.09935744** | 0.986 |
| Official-credit proxy `$` | **0.10074652** | **0.24839360** | 2.466 |

Local formula on current main uses Luna Standard rates per million: fresh `$0.20`, cached
`$0.02`, write `$0.25`, output `$1.20` [5]. Fast is locally 1.4% cheaper only because it
received 11,776 more cached input tokens; provider dollars/credits are not emitted. Official
Manual states GPT-5.6 Fast consumes `2.5×` Standard ChatGPT credits, so the requested proxy
multiplies only Fast local `$` by 2.5 [1]. Это sensitivity proxy, не живой subscription bill.

| Quality-adjusted metric | Standard | Fast | Fast / Standard |
|---|---:|---:|---:|
| Exact PASS / wall minute | 0.195 | 0.619 | **3.174×** |
| Wall seconds / exact PASS | 307.754 | 96.949 | 0.315 |
| Exact PASS / local `$` | 9.926 | 20.129 | **2.028×** |
| Local `$` / exact PASS | 0.10075 | 0.04968 | 0.493 |
| Exact PASS / `2.5×` proxy `$` | **9.926** | **8.052** | **0.811×** |
| Proxy `$` / exact PASS | 0.10075 | 0.12420 | 1.233 |

Первые четыре quality-adjusted строки сильно зависят от случайной разницы `1` против `2`
PASS; paired quality test её не подтверждает. Даже с этим благоприятным для Fast исходом
official-credit proxy даёт на 18.9% меньше exact PASS на unit, поэтому pre-registered default
gate не пройден. Если считать качество равным и смотреть только latency/credit, paired wall
speedup даёт примерно `1.397/2.5 = 0.559` cold и `1.288/2.5 = 0.515` warm Standard
delivered-turn throughput на credit.

**Confidence: CONFIRMED для raw tokens/local formula; DESCRIPTIVE для PASS-normalized
ratios; UNIDENTIFIED для реального subscription burn.**

### 4. Provider primary snapshots полны, но arm attribution невозможна

- Provider primary: `63→64%` за полный run; confirmatory segment `64→64%`.
- `resets_at` стабилен: `2026-08-23T07:26:39Z`.
- Сохранено 42 unique before/after snapshots для 28 turns.
- Direct harness local `$`: `0.23404792` full, `0.20010396` confirmatory.
- Foreign Orchestra Codex rows из WAL-safe DB backup: `16` full на `$32.47847944`; из них
  `12` confirmatory на `$28.80553544`.
- Confirmatory cumulative direct+foreign local `$`: `$29.00563940`, observed provider
  delta `0 pp`, quantization bound `0–1 pp`.

Foreign spend превышает direct confirmatory estimate в `143.95×`; service tier чужих rows
в `turn_usage` не восстановим. Поэтому H4 не опровергнута, provider verdict =
**UNIDENTIFIED**. Нулевой confirmatory step не доказывает бесплатность Fast: общий счётчик
целочисленный, background большой, update может запаздывать [2].

**Confidence: CONFIRMED для snapshots/foreign rows; UNIDENTIFIED для arm credit multiplier.**

## Прямое сравнение с #208 Sol

Оба запуска использовали тот же effort `medium`, record/question seeds, exact grader,
AB/BA order и N. #208 шёл 07:40–07:50 UTC, #310 — 08:30–08:41 UTC в том же provider
window. Это делает сравнение полезным описательно, но **не** paired cross-model experiment:
нагрузка, output sampling, background/cache и entitlement-time различаются.

| Метрика | Sol Standard #208 | Sol Fast #208 | Luna Standard #310 | Luna Fast #310 |
|---|---:|---:|---:|---:|
| Cold wall median | 24.16 s | 19.37 s | 24.15 s | 17.70 s |
| Warm wall median | 18.14 s | 12.95 s | 18.68 s | 14.17 s |
| Paired cold wall speedup | — | 1.229× | — | **1.397×** |
| Paired warm wall speedup | — | **1.428×** | — | 1.288× |
| Exact PASS | 5/12 | 4/12 | **1/12** | **2/12** |
| Local API-equivalent `$` | 2.55873 | 2.47342 | 0.10075 | 0.09936 |
| Local `$` / exact PASS | 0.51175 | 0.61836 | 0.10075 | 0.04968 |
| `2.5×` proxy `$` / exact PASS | 0.51175 | 1.54589 | 0.10075 | 0.12420 |

Luna local total стоит примерно `25.1×` меньше Sol для близкого token volume: это почти
целиком задано price table (каждая Luna ставка ровно 1/25 Sol), а не экспериментальным
ускорением. На этом exact corpus Luna дала заметно меньше PASS, поэтому нельзя из дешёвого
local `$` делать вывод «Luna заменяет Sol» без task-specific oracle. Семантически корректный
вывод уже: Luna Fast ускоряет Luna; cross-model качество остаётся отдельным routing gate.

## Примеры пар

- **Типичная cold:** replicate 0 Standard `22.395 s` vs Fast `18.608 s` (`1.204×`), оба FAIL.
- **Сильная cold:** replicate 3 `27.048 s` vs `17.943 s` (`1.507×`), оба FAIL.
- **Почти равный warm TTFT:** replicate 1 `12.648 s` vs `12.613 s` (`1.003×`), но wall
  `18.956 s` vs `16.913 s` (`1.121×`); Fast exact PASS только на cold этой реплики.
- **Warm outlier:** replicate 2 `66.150 s` vs `13.100 s` (`5.050×`), оба exact PASS. Он
  объясняет aggregate `1.587×`, но не paired median `1.288×`.

## Decision rule и практический маршрут

1. **Default candidate — NO.** Reliability, speed, exact count и exact-PASS throughput gates
   прошли, но `PASS / 2.5× proxy-$` ниже Standard (`8.052 < 9.926`). Кроме того, 1/12 и 2/12
   exact слишком малы для общего default.
2. **Explicit latency route — YES, bounded.** Для полностью заданной, tool-free leaf-задачи
   с независимым oracle, где пользователь/fan-in ждёт прямо сейчас, Fast сохранил completion
   и сократил wall во всех 12/12 matched turns на 4.5–6.5 s по медиане.
3. **Не переносить** на research/review, tool-using implementation, retries/agent chains или
   unattended batch: experiment их не содержит, а `2.5×` credit rate делает throughput-only
   route структурно дорогим.

Иными словами: **не default flag, а explicit `latency_sensitive_leaf` route**. Следующий
безопасный шаг перед production policy — прогонить 1–2 реальные leaf-ticket oracle из другой
предметной области и записывать service tier + причину маршрутизации; этот research сам
production/config/runtime не меняет.

## Independent integrity и counter-evidence

Независимый checker поверх raw JSON и второй `sqlite3.Connection.backup` дал:
`INTEGRITY PASS 209 checks; foreign=16 exact; provider_snapshots=42; confirmatory=24;
pilots=4 excluded`. Он заново проверил frozen hashes, schedule, tiers/model, completion,
timing/token invariants, local-cost arithmetic, summaries, paired ratios, stable reset,
monotone snapshots и побайтное равенство всех 16 foreign DB rows [2][3]. Secret-form scan по
значениям task artifacts: `0` matches.

Ограничение принятого #208 artifact schema: response text намеренно удаляется после grade;
хранится только `final_text_sha256` + exact boolean/reason. Поэтому независимый post-hoc
regrade невозможен. Integrity покрывает frozen grader source hash, self-test и арифметику,
но не повторное сравнение model output с expected. Это защищает от смены метрики, но снижает
диагностическую мощность ошибок — нельзя показать, какой именно lookup был неверен.

Другие ограничения/counter-evidence:

- Официальные `1.5×` относятся к model speed, не гарантируют end-to-end wall [1]. Luna cold
  приблизилась к 1.5, warm — нет.
- Exact PASS на Luna крайне низок; schema completion (`24/24`) не равно semantic success.
- N=6 latency pairs и N=12 quality pairs; bootstrap intervals descriptive, McNemar powerless.
- Fast cold получил 11,776 cached tokens против 0 Standard; local cost comparison слегка
  благоприятен Fast.
- 16 foreign turns делают живой primary counter непригодным для arm attribution.
- Cross-model Sol comparison не randomized/concurrent; price tables измеряют API-equivalent,
  а не реальные подписочные credits между моделями.
- Fixture большая и lookup-heavy. Более короткие fully specified edits могут иметь другой
  prefill/generation balance; открытые задачи — другой quality profile.

## Affected files, risks, edge cases

Изменены только `docs/tasks/310/`: `prereg.md`, frozen `bench.py`, raw `results.json`, этот
`research.md` и reviewer artifact `review.md`. Production code/config/runtime не менялись.
Риски решения: перепутать local `$` с subscription credit; обобщить низко-N exact result;
считать aggregate wall типичным вопреки outlier; маршрутизировать Luna/Fast без independent
task oracle; считать `64→64%` доказательством нулевого burn.

## Review gate inputs

- Author metadata: session `bench-fast-luna`, Codex runtime, actual model row/session metadata
  `gpt-5.6-sol` для research turn; benchmark target model `gpt-5.6-luna` из app-server telemetry.
- Consumers: пользователь/оркестратор и будущая routing policy; production не затронут.
- AC: pre-call prereg; N=24 + excluded pilots; exact fixture/grader; per-turn latency/usage;
  local + `2.5×` proxy; primary snapshots; all foreign rows; #208 comparison; user-ready verdict.
- Named checks: adapter `--self-test` → PASS; independent checker → 209 PASS; secret-form
  scan → 0 value matches; raw SHA выше.
- Risk: statistical/causal routing conclusion без strong deterministic oracle → targeted Sol
  research review required.
- Review outcome: один fresh targeted Sol round, `Clean`, findings `0`. Состоявшийся verdict
  доказан цитатой из артефакта, которой не было в review prompt: «Ограничение принятого #208
  artifact schema: response text намеренно удаляется после grade;». Полный след —
  `docs/tasks/310/review.md`. Reviewer и author — одна Codex model family; это adversarial
  second opinion, не cross-family independence. Второй раунд не разрешён: blocker отсутствует
  и artifact после review не менялся по существу.

## Источники

1. **Primary official source:** актуальный OpenAI Codex Manual,
   [Speed](https://learn.chatgpt.com/docs/agent-configuration/speed.md), fetched official
   manual helper 17.08.2026: Fast `1.5×` model speed; GPT-5.6 Fast `2.5×` Standard ChatGPT
   credits; API Priority отделён.
2. **Tier 1 direct measurement:** `docs/tasks/310/results.json`, SHA-256 выше; raw per-turn
   timestamps, grades, tokens, tiers, provider snapshots и foreign DB rows.
3. **Frozen pre-call method:** `docs/tasks/310/prereg.md`, `docs/tasks/310/bench.py`, commit
   `649ae31b`; adapter self-test PASS before first model call.
4. **Accepted baseline/method:** `docs/tasks/208/fast-mode-prereg.md`,
   `docs/tasks/208/fast_bench.py`, `docs/tasks/208/fast-mode-results.json`,
   `docs/tasks/208/fast-mode.md`.
5. **Primary local code:** `app/backend_codex.py:CODEX_TOKEN_PRICES` on main
   `f7fa7eb70296ce785f58fa83c9cdf3a93e48766b`.
