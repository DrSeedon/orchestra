# Claude Opus 5 для Orchestra: availability, economics и model routing

**Дата среза:** 2026-07-25 (Asia/Krasnoyarsk)
**Фаза:** Research + Experiment
**Задача:** решить, заменять ли Opus 4.6 / Opus 4.8 / Sol / Fable 5 в Orchestra.

## Update 2026-07-25 — live DeepSWE refresh

### Что изменилось

Первый вывод **частично superseded новым первичным срезом**, но конечный
default routing не меняется:

1. Live DeepSWE теперь показывает Opus 5 high **72.83%** и max **73.65%**
   против Sol max **72.67%** [9][10]. По point estimates Opus 5 действительно
   догнал Sol.
2. Это не доказанное лидерство: 95% normal-approximation CIs среднего по
   четырём whole-benchmark runs перекрываются. Opus 5 high и Sol max
   различаются всего на **+0.16 pp**, Opus 5 max и Sol max — на **+0.98
   pp**. Для routing это **quality tie**, не win.
3. Старые `68.8 / 72.7` были не ошибкой чтения чисел. `68.8%` взято из
   присланного Anthropic launch screenshot, где точка явно подписана
   `Claude Opus 5 max`; `72.7%` — Sol max. Новый DataCurve job
   `20260724-opus-5` закончился **2026-07-25 01:59 UTC**, уже после mtime
   screenshot (**2026-07-24 17:11 UTC**), и live JSON был сгенерирован
   **2026-07-25 03:13 UTC** [10]. Следовательно, конкретная причина
   расхождения — **новый post-launch Opus 5 sweep / обновлённый leaderboard
   snapshot**, а не подмена medium на max и не ошибка легенды.
4. Старое исправление легенды остаётся верным: `53.8%` на launch chart —
   Sonnet 5 max, не Sol. Но прежний тезис «Sol качественно лучше Opus 5 на
   DeepSWE» больше использовать нельзя.
5. Orchestra всё равно оставляет Sol default worker: одинаковое качество
   плюс отдельный недогруженный Codex pool выгоднее, чем перенос нагрузки в
   дефицитный Claude 5h/7d meter. Новое практическое следствие — Opus 5 high
   становится **проверенным Claude fallback** при outage Codex, не новым
   fleet default.

**Updated verdict: keep Sol as the routine/full-cycle default; keep Opus 5
medium for orchestration/research/vision; use Opus 5 high for Claude coding
fallback or explicit escalation; use low only for bounded deterministic
leaf work. Do not route anything to max by default.**

### Raw snapshot

Сырые 20 строк для Opus 5, GPT-5.6 Sol, Fable 5 и Opus 4.8 сохранены без
округления в
[`deepswe-leaderboard-2026-07-25.csv`](deepswe-leaderboard-2026-07-25.csv).
CSV механически извлечён из live JSON и проверен `diff`:

- source:
  `https://deepswe.datacurve.ai/artifacts/v1.1/leaderboard-live.json`;
- source `generated_at`: `2026-07-25T03:13:49.273952+00:00`;
- latest job: `20260724-opus-5`, finished
  `2026-07-25T01:59:45.339374Z`;
- source scope: 50 configurations, 113 tasks;
- full JSON SHA-256:
  `d5fc4531d5b005c6e0040a82ddafe63225b1c172015cd499f2ec866f16f91cf1`;
- selected CSV SHA-256:
  `074c2725314944cf247f56060fb5008a5a3e52e789066ccfffd35e2ca6c4a0f6`.

Проверяемая metadata snapshot — job timestamp, HTTP validators, hashes,
старый screenshot mtime и denominator comparison — сохранена в
[`deepswe-leaderboard-2026-07-25.meta.json`](deepswe-leaderboard-2026-07-25.meta.json).

Rounded decision view (cost is mean API-equivalent USD per scored attempt;
`time` is raw mean duration, which DataCurve no longer publishes in the UI):

| Model | Effort | pass@1 ± 95% half-width | Mean $ | Mean time | Mean steps |
|---|---:|---:|---:|---:|---:|
| Opus 5 | low | 58.13% ±2.33 | 1.66 | 7.8 min | 35.6 |
| Opus 5 | medium | 68.90% ±1.17 | 3.29 | 12.7 min | 52.3 |
| Opus 5 | high | 72.83% ±1.95 | 6.08 | 19.4 min | 72.9 |
| Opus 5 | xhigh | 73.15% ±3.06 | 9.07 | 26.0 min | 88.7 |
| Opus 5 | max | 73.65% ±3.87 | 11.84 | 31.9 min | 99.0 |
| GPT-5.6 Sol | low | 45.35% ±2.39 | 1.07 | 4.4 min | 23.4 |
| GPT-5.6 Sol | medium | 61.06% ±1.58 | 1.86 | 7.1 min | 30.9 |
| GPT-5.6 Sol | high | 69.40% ±1.43 | 3.47 | 9.9 min | 36.9 |
| GPT-5.6 Sol | xhigh | 70.73% ±0.82 | 4.70 | 13.3 min | 44.0 |
| GPT-5.6 Sol | max | 72.67% ±2.83 | 8.39 | 18.8 min | 61.3 |
| Fable 5 | low | 59.58% ±2.79 | 3.76 | 10.6 min | 37.8 |
| Fable 5 | medium | 65.37% ±4.42 | 6.09 | 13.5 min | 48.4 |
| Fable 5 | high | 68.60% ±1.12 | 9.18 | 17.7 min | 58.7 |
| Fable 5 | xhigh | 69.91% ±3.24 | 13.41 | 23.5 min | 68.4 |
| Fable 5 | max | 69.72% ±4.03 | 21.63 | 34.9 min | 88.4 |
| Opus 4.8 | low | 40.80% ±1.46 | 2.29 | 10.9 min | 54.0 |
| Opus 4.8 | medium | 48.67% ±2.24 | 3.44 | 14.7 min | 65.6 |
| Opus 4.8 | high | 51.77% ±4.56 | 4.28 | 17.8 min | 72.5 |
| Opus 4.8 | xhigh | 54.36% ±3.71 | 8.01 | 36.6 min | 94.6 |
| Opus 4.8 | max | 58.97% ±1.76 | 13.22 | 58.2 min | 120.0 |

**Time caveat:** v1.1 explicitly removed wall-clock time from the public UI
because host performance and provider load make it inconsistent [11]. The
raw JSON still contains duration aggregates, so they are preserved above on
request but are **not decision-grade**.

### Fact-check of the third-party post

| Claim | Rating | Primary-source result |
|---|---|---|
| Opus 5 max = 74%, $11.84 | ✅ TRUE | 73.6486%, $11.8376; normal rounding [10] |
| Max “beats” Sol max and Fable max | ⚠️ MOSTLY TRUE | Nominally +0.98 pp vs Sol and +3.92 pp vs Fable, but both CIs overlap; rank is not statistically established |
| High trails max by ~1 pp and costs almost half | ✅ TRUE | −0.82 pp; $6.08 vs $11.84, 48.7% cheaper |
| High is cheaper than Sol max at the same score | ✅ TRUE with context | +0.16 pp and $6.08 vs $8.39; API-equivalent 27.5% cheaper, statistically a tie |
| Low ≈ Opus 4.8 max for 1/8 cost | ✅ TRUE with context | −0.85 pp; overlapping CIs; $13.22 / $1.66 = 7.95× |
| Therefore high should serve most tasks and low simple tasks | 🔶 MIXED | Reasonable for API billing; wrong objective for Orchestra subscriptions and separate quota pools |

### What DeepSWE measures and whether 1 pp matters

DeepSWE v1.1 measures whether a fixed, model-agnostic `mini-swe-agent` with
only bash can implement 113 original, long-horizon changes across 91
repositories and five languages. The agent commits a patch; v1.1 applies and
grades that patch in a clean verifier container with behavioral tests
[9][11].

The live artifact defines the score precisely [10]:

- `pass@1` = passed scored attempts / all scored attempts;
- `pass@4` = tasks with at least one passing rollout / tasks attempted;
- context-window failures and agent timeouts count as failures;
- provider, verifier and network errors are excluded;
- efficiency aggregates cover all scored attempts.

Each configuration has **4 repeated whole-benchmark passes**. Most rows have
roughly 449–452 scored attempts; Opus 5 max has 444, Fable rows 430–452, and
Opus 4.8 max covers 111 tasks / 429 attempts. The published interval is
`1.96 × std(four run scores) / sqrt(4)`, not a binomial interval over 450
independent trials [10]. DataCurve also notes that 73 of Fable's 2,260 trials
did not complete after access suspension, and computes its pass rate over
completed trials [11].

For Opus 5 high vs max:

- high = 72.83%, CI `[70.88, 74.77]`;
- max = 73.65%, CI `[69.78, 77.52]`;
- difference = **0.82 pp**, with heavy interval overlap.

This is **noise / statistically unresolved**, not evidence that max is
better. The available artifact does not expose a paired CI for the
difference, so an exact significance test cannot be reconstructed from the
aggregates. Medium vs high is more credible: +3.92 pp and their reported 95%
intervals do not overlap, though only four run-level observations still make
the estimate fragile.

The nominal ranking also has a denominator effect: Opus 5 high, Opus 5 max
and Sol max each record exactly **327 passed attempts**, divided by 449, 444
and 450 scored attempts respectively. Thus the displayed +0.16/+0.98 pp
comes entirely from excluded/non-scored attempts, not additional passes.

The fixed bash-only harness is also not Orchestra: it excludes Claude Code
and Codex native edit tools, Orchestra prompts, MCP discipline, mid-turn
injection and coordination behavior. DeepSWE is a strong coding-capability
signal, not a direct fleet-throughput measurement.

### API dollars versus Orchestra quota

The `$` column is token-priced inference cost, not subscription quota. For
these fixed `mini-swe-agent` runs, Pier reads `model_stats.instance_cost`;
its installer refreshes LiteLLM's model pricing map before execution [12].
It does not know our Claude 5h/7d utilization or Codex subscription allowance.

Using the earlier Orchestra historical calibration only as a conditional
scenario—30 quota points reserved for orchestrators, 20 points held as
safety reserve, leaving the `$191 API-equivalent` historical half-budget—the
new mean costs would imply:

| Opus 5 effort | Conditional tasks/week | Why this is not a quota promise |
|---|---:|---|
| low ($1.66) | ~115 | Model/effort may have different Max weights |
| medium ($3.29) | ~58 | Close to the earlier 50–65 planning range |
| high ($6.08) | ~31 (~4–5/day) | No direct high-effort meter A/B exists |
| max ($11.84) | ~16 | 2× high cost for statistically unresolved gain |

**Confidence: UNCERTAIN.** These figures are arithmetic scenarios in the
wrong currency; they are useful only for admission-control sizing before a
real Max-meter A/B.

The decisive resource result is qualitative but measured:

- Sol consumes the separate Codex pool, currently underused relative to
  Claude;
- Opus 5 consumes the shared Claude plan meter, already the 5h/7d
  bottleneck;
- therefore a DeepSWE quality tie does not justify shifting the default
  fleet from Sol to Opus 5.

Availability changes the fallback, not the default. Orchestra DB logs on
2026-07-25 confirm `biscuit_baker_service_me_circuit_open` 503s on three
distinct `feat-usage-analytics` turns at 09:00, 09:03 and 09:19 UTC, with
direct probes still failing at 09:36 UTC [13]. A Claude fallback would have
saved those turns **if Claude had headroom**; the same incident log recorded
Claude 5h at 97%, so unconditional failover would merely exchange one outage
for a rate limit.

### Updated routing and effort ladder

| Role / trigger | Primary route | Effort | Fallback / rule |
|---|---|---:|---|
| Top-level and sub-orchestrator | Opus 5 | medium | Keep; DeepSWE is not an orchestration eval |
| Research, citations, prompt engineering | Opus 5 | medium | high only after a failed/insufficient medium turn |
| Vision inventory / UI analysis | Opus 5 | medium | high for ambiguous replication or multi-screen synthesis |
| Routine implementation / known bug | Sol | high | **No change** |
| Full-cycle engineering | Sol | xhigh | **No change** |
| Codex `circuit_open` or sustained outage, blocked coding task | Opus 5 | high | Unless it qualifies for low below; require Claude 5h **and weekly** <70%; max 2 concurrent |
| Failed Sol task with a model-specific quality reason | Opus 5 | high | Explicit escalation, not automatic retry of the fleet |
| Codex outage bounded leaf, or Claude-only vision extraction | Opus 5 | low | Only the explicit low classes below |
| Fable 5 | none | none | Manual domain-specific experiment only |
| Any default route | Opus 5 max | none | Do not use: no resolved gain over high |

The `<70%` failover threshold is a proposed conservative guardrail, not a
DeepSWE or Anthropic-derived constant. Requiring both 5h and weekly meters
below it leaves at least 30 points in each window for active orchestrators
and outage variance; production telemetry should tighten it.

Current backend behavior is compatible with the fallback: `worker` is high,
`full-cycle` is xhigh, and `backend_claude.py:159–165` maps Claude xhigh to
high. Thus a full-cycle worker moved to Opus during an outage already lands
on the DeepSWE-supported high tier rather than silently spending max.

#### Where Opus 5 low is enough

Low is **not** a permanent role default. With healthy Codex, text/code leaf
work stays on Spark/Sol. Opus low is a bounded fallback during Codex outage,
or for a Claude-only surface such as vision:

1. a Codex-outage leaf implementation touching at most two files, with an
   explicit patch shape and exact test command;
2. during Codex outage, extraction after sources are already selected: turn
   a known page/CSV/log into a fixed schema, with no credibility judgment;
3. `frontend-opus` read-only screenshot inventory, OCR, color/spacing
   extraction, or asset classification with explicit expected fields,
   including when Codex lacks the required vision surface;
4. during Codex outage, deterministic prompt lint/format conversion, not
   final voice or prompt architecture.

Do **not** use low for orchestrators, debugging without a known root cause,
full-cycle work, architecture, security, ambiguous research, final brand
copy, or multi-screen UI replication. When Codex is healthy, Spark/Sol still
own the first and fourth classes because they consume the other pool.

**Net change from the original report:** the quality reason for keeping Sol
is removed; the quota-pool reason survives. Opus 5 high is promoted from a
generic escalation to the explicit Codex-outage coding fallback. Medium
remains the Claude default, low gains narrow outage/vision leaf cases, and
max remains unused.

## Historical snapshot verdict (before the live refresh)

> Audit trail: this section preserves the conclusion based on the supplied
> launch screenshots. Its DeepSWE `68.8 vs 72.7` quality comparison is
> superseded by the update above; availability, model ID, context, pricing,
> Fable and quota-pool findings remain applicable.

1. **Opus 5 уже доступен.** Официальный API ID — `claude-opus-5`. Claude Code
   2.1.215 принял и `claude-opus-5`, и `claude-opus-5[1m]`; обе проверки
   реально ответили моделью Opus 5.
2. **Цена не выросла:** $5/MTok input и $25/MTok output, как у Opus 4.8.
   На Max отдельного бесплатного пула для Opus 5 нет: использование идёт в
   общие Claude 5h/7d лимиты.
3. **Контекст — 1M, но для Orchestra нужен суффикс.** API-документация называет
   1M единственным окном Opus 5. В Claude Code Max наш голый
   `claude-opus-5` фактически сообщил 200K, а `claude-opus-5[1m]` — 1M.
   Поэтому безопасный pinned ID для Orchestra: **`claude-opus-5[1m]`**.
4. **Opus-роли переводить стоит, но через metered canary:** Opus 4.8 workers
   и оркестраторы Opus 4.6 → Opus 5 medium после раздельных коротких пилотов.
5. **Sol массово не заменять.** Утверждение «Opus 5 medium 66.9% обгоняет Sol
   max 53.8%» неверно: 53.8% на графике — **Claude Sonnet 5 max**, Sol на
   этом графике отсутствует. В сравнительной таблице Sol набирает 72.7% на
   DeepSWE против 68.8% Opus 5.
6. **Fable 5 перестаёт быть разумным дефолтом.** Он выигрывает у Opus 5 на
   трёх coding evals всего на 0.1–0.9 п.п., а его API-equivalent цена вдвое
   выше. Оставить только как ручную эскалацию после неудачи Opus 5 либо для
   проверенного domain-specific преимущества; relative Max burn не измерен.

## Question

- **Контекст:** Orchestra держит короткие координационные turns на Opus 4.6,
  specialist Claude workers на Opus 4.8, а основную worker-нагрузку — на Sol
  в отдельном Codex pool.
- **Изменение:** добавить Opus 5 и выбрать роли, которые надо перевести.
- **Baseline:** текущие Opus 4.6 / Opus 4.8 / Sol / Fable 5.
- **Outcome:** больше успешно завершённых задач без ухудшения 5h/7d capacity
  и без потери независимого Codex pool.

## Hypotheses и falsifiers

### H1 — Opus 5 доступен Orchestra как drop-in Claude model

**Гипотеза:** Claude Code принимает `claude-opus-5`, а Max включает модель.
**Фальсификатор:** CLI возвращает unknown model / entitlement error либо
фактически отвечает fallback-моделью.

### H2 — все Claude-роли можно перевести без downside

**Гипотеза:** одинаковая API-цена с Opus 4.8 означает одинаковый quota burn.
**Фальсификатор:** matched canary показывает больше 5h percentage points на
task, чем Opus 4.8 baseline.

### H3 — Opus 5 medium экономически заменяет Sol

**Гипотеза:** Opus 5 medium даёт выше качество, чем Sol max, при меньшей цене.
**Фальсификатор:** effort chart сравнивает Opus 5 не с Sol либо независимый
Sol benchmark выше.

### H4 — Fable 5 остаётся default для самых сложных задач

**Гипотеза:** прирост Fable оправдывает 2× API-equivalent цену; relative Max
burn неизвестен.
**Фальсификатор:** Opus 5 статистически близок или лучше на большинстве
релевантных evals.

## Methods

1. Прочитаны четыре предоставленных screenshot:
   `photo_20260724_171140_100505.jpg` … `100508.jpg`.
2. Открыты официальные launch, model, Claude Code и Max-limit страницы.
3. Выполнены две живые проверки Claude Code 2.1.215:
   - `claude-opus-5`;
   - `claude-opus-5[1m]`.
4. Сняты `modelUsage`, context window и изменения provider meter.
5. Из `data/orchestra.db` посчитана фактическая стоимость completion-ов после
   перехода на Max 5x и использованы результаты прошлых quota-исследований.

## Findings

### F1 — запуск, ID и CLI availability: ✅ TRUE / CONFIRMED

Anthropic опубликовал запуск 24 июля 2026. В launch post сказано:

- модель доступна на всех платформах;
- API ID — `claude-opus-5`;
- цена — $5/$25 за MTok;
- Opus 5 — новый default на Claude Max.

Официальная model page подтверждает API ID, full effort ladder
`low/medium/high/xhigh/max`, 1M context и 128K max output на API [1][2].

**Прямая проверка CLI:**

| Probe | Result | Effective model | Context reported |
|---|---|---|---:|
| `--model claude-opus-5` | `OPUS5_OK` | `claude-opus-5` | 200,000 |
| `--model claude-opus-5[1m]` | `OPUS5_1M_OK` | `claude-opus-5[1m]` | 1,000,000 |

Обе команды завершились `subtype=success`, `stop_reason=end_turn`.

**Вывод:** для API использовать `claude-opus-5`; для pinned Orchestra model —
`claude-opus-5[1m]`. Голый full ID в текущем Claude Code не гарантирует
эффективные 1M, несмотря на API spec.

**Confidence: CONFIRMED — official primary sources + direct measurement.**

### F2 — цена та же; расход идёт в общий plan meter: ✅ TRUE с ограничением

API price совпадает с Opus 4.8: $5 input / $25 output MTok [1][2].
Но Max — не API billing. Anthropic не публикует абсолютный token allowance:

- Max 5x = 5× Pro **per 5h session**;
- есть общий weekly limit;
- Claude, Claude Code и Desktop используют общий plan limit;
- расход зависит от модели, effort, длины контекста и tools [4][5].

В прямом low-effort cold probe `claude-opus-5[1m]` создал 17,812 cache tokens
и $0.178 API-equivalent cost. При отсутствии Orchestra turn-end между соседними
snapshots 5h meter вырос **19% → 21%**, weekly остался на округлённых 40%.
Это показывает, что Opus 5 увеличивает общий Claude plan meter и отдельного
бесплатного пула в наблюдаемом интерфейсе нет. Один округлённый snapshot не
доказывает одинаковый вес Opus 5 и 4.8 внутри 5h/weekly limits.

Перевод Opus 4.6 → 5 также не совершенно бесплатен:

- Opus 4.7+ использует tokenizer, который даёт примерно на 30% больше tokens
  для того же текста, чем pre-4.7 models;
- у Opus 5 thinking включён по умолчанию;
- Opus 5 чаще делегирует, проверяет и narrates progress [2].

Для Opus 4.8 → 5 tokenizer tax уже присутствует в baseline; здесь price tier
и tokenizer одинаковы.

**Confidence: CONFIRMED для API-цены; LIKELY для shared plan pool; UNCERTAIN
для relative quota burn до production A/B.**

### F3 — 1M context: ✅ TRUE на API, CLI требует аккуратного model selector

API docs: 1M — default и maximum, меньшего варианта нет [2].
Claude Code docs разрешают `[1m]` на alias или full model ID и указывают, что
Opus 1M включён в Max [3].

Практика в установленном CLI расходится с буквальным API wording:

- bare full ID → `contextWindow: 200000`;
- `[1m]` full ID → `contextWindow: 1000000`.

Это product-surface distinction, а не опровержение API capability.

**Action:** добавить только `claude-opus-5[1m]`; alias `opus` не использовать
в stored session model, чтобы release alias не менял поведение молча.

**Confidence: CONFIRMED — official docs + direct CLI measurement.**

### F4 — ключевой аргумент «Opus 5 medium beats Sol max»: 🚫 FALSE

На screenshot `100508` линии:

- red — Opus 5;
- orange — Fable 5;
- blue — Opus 4.8;
- green — **Claude Sonnet 5**.

Значение **53.8% max принадлежит Sonnet 5**, не GPT-5.6 Sol. Sol на этом
effort-scaling chart отсутствует.

Корректное прочтение:

- Opus 5 medium = 66.9%;
- Sonnet 5 max = 53.8%;
- отдельная comparison table: **Sol = 72.7%, Opus 5 = 68.8%**.

Точка Opus 5 medium визуально расположена около $4/task на log axis; точного
числа возле точки нет, поэтому `$3/task` — приблизительная оценка, не значение
из подписи.

**Consequence:** provided data не доказывает, что Opus 5 дешевле и лучше Sol.
Оно доказывает, что Opus 5 medium доминирует **Sonnet 5 max** и Opus 4.8.

**Confidence: CONFIRMED — literal chart legend + comparison table.**

### F5 — benchmark verdict по ролям

#### Opus 5 против Opus 4.8

| Evaluation | Opus 5 | Opus 4.8 | Δ, pp |
|---|---:|---:|---:|
| Frontier-Bench v0.1 | 43.3 | 21.1 | +22.2 |
| DeepSWE v1.1 | 68.8 | 59.0 | +9.8 |
| FrontierCode 1.1 | 53.4 | 46.5 | +6.9 |
| BrowseComp | 90.8 | 84.3 | +6.5 |
| OSWorld 2.0 | 70.6 | 55.7 | +14.9 |
| AutomationBench | 26.0 | 17.0 | +9.0 |
| ARC-AGI-3 | 30.2 | 1.5 | +28.7 |
| SWE-bench Pro | 79.2 | 69.2 | +10.0 |

Это не marginal upgrade. На всех релевантных evals Opus 5 лучше Opus 4.8,
при той же API price tier.

#### Opus 5 против Sol

| Evaluation | Opus 5 | Sol | Winner |
|---|---:|---:|---|
| DeepSWE v1.1 | 68.8 | **72.7** | Sol |
| Frontier-Bench v0.1 | **43.3** | 34.4 | Opus 5 |
| FrontierCode 1.1 | **53.4** | 47.5 | Opus 5 |
| BrowseComp | **90.8** | 90.4 | tie practically |
| OSWorld 2.0 | **70.6** | 62.6 | Opus 5 |
| AutomationBench | **26.0** | 18.1 | Opus 5 |
| SWE-bench Pro | **79.2** | 64.6 | Opus 5 |

Capability у Opus 5 чаще выше, но DeepSWE — прямое counter-example, а
BrowseComp практически равен. Главное системное преимущество Sol — не API
price, а **отдельный Codex quota pool**.

#### Opus 5 против Fable 5

Fable выигрывает:

- SWE-bench Pro: +0.8 pp;
- DeepSWE: +0.9 pp;
- FrontierCode: +0.1 pp;
- HLE no-tools: +0.2 pp;
- legal: +1.6 pp;
- health: +6.2 pp.

Opus 5 выигрывает:

- Frontier-Bench: +9.6 pp;
- BrowseComp: +3.4 pp;
- OSWorld: +4.5 pp;
- AutomationBench: +8.6 pp;
- GDPval-AA: +114 points;
- HLE with tools: +0.8 pp.

При API-equivalent $5/$25 против Fable $10/$50 первые три coding differences
в 0.1–0.9 pp не оправдывают 2× API cost без confidence intervals. Max может
взвешивать модели иначе; это не измерено. Health — реальный candidate для
Fable escalation, но не общая Orchestra route.

**Confidence: LIKELY — benchmark tables are primary vendor data, но нет
confidence intervals и evals не являются прямым Orchestra A/B.**

### F6 — benchmark caveats и counter-evidence

1. На двух предоставленных screenshots расходятся baseline значения:
   - Frontier-Bench Opus 4.8: 21.1 vs 18.7;
   - Sol: 34.4 vs 37.5.
   Opus 5 остаётся 43.3. Вероятны разные harness/config snapshots, поэтому
   небольшие differences нельзя трактовать как точную ranking margin.
2. Frontier-Bench footnote говорит о mean over 5 attempts и о fallback Opus
   4.8 при safety refusal Opus 5/Fable. Это deployed-system score, а не чистая
   model-only оценка.
3. DeepSWE table и effort curve показывают разные наборы моделей/configs.
   Смешивать point из curve с Sol из table как одну cost curve нельзя.
4. Vendor evals не измеряют Telegram/Orchestra-specific behavior:
   mid-turn messages, MCP discipline, gate following и склонность к лишней
   делегации. Для orchestrator migration нужен canary.

### F7 — quota math для Max 5x

Anthropic абсолютные сообщения/tokens не публикует, поэтому ниже не обещание
провайдера, а empirical capacity model.

#### Internal calibration

- Исторический срез после downgrade на Max $100: **393 mixed Claude
  completions соответствовали 106 weekly percentage points** → арифметически
  около **370 mixed completions на 100 points** при том workload. Исходный
  срез не доказывает отсутствие weekly reset или параллельной Claude-нагрузки,
  поэтому это rough calibration, не ceiling.
- Нормализованный 5h расход после downgrade:
  $405.40 API-equivalent work → 419 percentage points across 5h windows,
  то есть около **$96.8 API-equivalent на одно полное 5h окно**.
- Weekly по тому же срезу: около **$382 API-equivalent на 100% weekly**.
- Opus 4.8 full-cycle completions после 18 июля (`n=68`):
  - median $1.58;
  - mean $3.39;
  - p75 $5.07;
  - p90 $10.21.
- Project history: orchestrator-only Claude load ≈ **30% weekly**.

#### Conditional planning scenario for Opus 5 medium

Если Opus 5 medium task в Orchestra действительно будет стоить около
$3–4 API-equivalent, линейная модель даёт:

| Scenario | Estimated medium worker completions |
|---|---:|
| 100% historical weekly calibration, без оркестраторов | **~95–125/week** |
| После 30% orchestrator baseline | **~65–90/week = 9–13/day** |
| После 30 percentage points baseline + 20 points reserve | **~50–65/week = 7–9/day** |

Последняя строка оставляет workers 50% полного historical budget:
`$382 × 0.50 / ($3–4) = 48–64`, округлённо 50–65. Это 20 процентных
пунктов от полного лимита, не 20% от остатка после baseline.

Для 5h burst:

- long-run cost calibration даёт ~24–32 medium tasks/window;
- последний реальный concurrent burst сжёг 100% на $29.67 virtual work,
  что соответствует лишь ~7–10 medium tasks;
- conservative starting admission budget: **не больше 8 новых Opus 5 worker
  tasks на 5h и не больше 2 concurrent Claude sessions** до production A/B.

Здесь `completion/turn` означает один внешний task request, завершившийся
`turn ended`, а не внутренний tool/reasoning step.

**Confidence: UNCERTAIN для всех capacity ranges.** Арифметика сценария
корректна, но коэффициенты расхода нестабильны: task size, cache state,
context length и concurrency меняют burn кратно.

## Recommendation: concrete routing

| Orchestra role / task | Model | Effort | Decision |
|---|---|---|---|
| Top-level orchestrator | `claude-opus-5[1m]` | medium | **Canary → switch** |
| Sub-orchestrator | `claude-opus-5[1m]` | medium | После canary |
| `research-*`, deep analysis, citations | `claude-opus-5[1m]` | medium; high only on explicit escalation | **Canary → switch from 4.8** |
| `prompt-engineer`, final voice/copy | `claude-opus-5[1m]` | medium | **Canary → switch from 4.8** |
| `frontend-opus`, vision/UI replication | `claude-opus-5[1m]` | medium | **Canary → switch from 4.8** |
| Routine implementation / known bug | `gpt-5.6-sol` | current role default | **Keep Sol** |
| Full-cycle default | `gpt-5.6-sol` | current role default | Keep unless task hits Opus trigger |
| Bounded text leaf task | `gpt-5.3-codex-spark` | role default | Keep |
| Failed/vague/vision-heavy/long-horizon task | `claude-opus-5[1m]` | medium/high | Escalate from Sol |
| Fable 5 | `claude-fable-5[1m]` | high/xhigh only if justified | Manual last-resort escalation |

### Why orchestrators should move

Opus 5 docs name the improvements Orchestra needs directly: judgment,
multi-agent coordination, long-horizon consistency, self-verification, and
deep reasoning [2]. Launch post calls it thoughtful/proactive and makes it the
Max default [1]. Since orchestrators already consume the Claude pool, the
separate-pool argument against replacing Sol does not apply.

### Canary before fleet-wide orchestrator migration

Run one top-level orchestrator for 20–30 completed user turns and compare with
its Opus 4.6 baseline:

- no new `tool_use`/permission/stop regressions;
- median agentic steps per completion ≤ baseline +15%;
- API-equivalent cost per completion ≤ baseline +25%;
- 5h percentage points per completion ≤ baseline +25%;
- no missed mid-turn messages or gate violations.

The thresholds are fixed before the pilot. If any hard behavior regression
appears, keep Opus 5 on specialist workers and retain 4.6 for orchestrators
until the prompt/backend is adjusted.

### Canary before specialist-worker migration

Run 15–20 representative Opus 4.8 specialist tasks on Opus 5 medium before
changing the fleet defaults. Promote only if there are no incomplete tasks or
quality regressions, median agentic steps stay within +15%, and both
API-equivalent cost and 5h percentage points per completion stay within +25%
of the matched Opus 4.8 baseline. Otherwise retain 4.8 for that specialist
route and investigate the failing dimension.

### Required implementation implications for Phase 2

This research does not change code. A later implementation should update:

- `app/models.py`: model registry, context, aliases, backend and token price;
- `app/tg_bridge.py` and `app/static/js/app.js`: label/color;
- `pipelines/default/pipeline.yaml`: orchestrator model after canary;
- model-policy text in `base.md` and `orchestration.md`;
- `backend_claude.py`: confirm medium passes through for Opus 5 (current
  Opus 4.8-specific coercion does not match Opus 5);
- affected tests.

Do not silently alias all Sol routes to Opus 5.

## Final claim ratings

| Claim | Rating |
|---|---|
| Opus 5 launched and is available now | ✅ TRUE |
| Exact API ID is `claude-opus-5` | ✅ TRUE |
| Orchestra should store `claude-opus-5[1m]` for 1M | ✅ TRUE in tested CLI |
| Price is the same as Opus 4.8 | ✅ TRUE |
| Opus 5 gets a separate/larger Max bucket | No evidence; direct meter shows use of the shared plan meter |
| Opus 5 medium beats Sol max 53.8 | 🚫 FALSE; 53.8 is Sonnet 5 |
| Live Opus 5 high/max has a meaningful lead over Sol max | ❓ UNRESOLVED; +0.16/+0.98 pp with overlapping 95% run intervals |
| Live DeepSWE changes the Sol default | ❌ NO; quality tie, separate underused Codex pool remains decisive |
| Replace Opus 4.8 workers | ✅ Canary first; switch routes that pass |
| Replace all Sol workers | ❌ NOT SUPPORTED |
| Fable remains a default | ❌ Not justified by the supplied benchmark deltas; Max burn unmeasured |

## Sources

1. [Anthropic — Introducing Claude Opus 5](https://www.anthropic.com/news/claude-opus-5),
   fetched 2026-07-25. **Tier 2: primary launch source.**
2. [Claude Platform — What's new in Claude Opus 5](https://platform.claude.com/docs/en/about-claude/models/whats-new-opus-5),
   fetched 2026-07-25. **Tier 2: primary technical documentation.**
3. [Claude Code — Model configuration](https://code.claude.com/docs/en/model-config),
   fetched 2026-07-25. **Tier 2: primary CLI documentation.**
4. [Claude Help — What is the Max plan?](https://support.claude.com/en/articles/11049741-what-is-the-max-plan),
   fetched 2026-07-25. **Tier 2: primary plan documentation.**
5. [Claude Help — How do usage and length limits work?](https://support.claude.com/en/articles/11647753-how-do-usage-and-length-limits-work),
   fetched 2026-07-25. **Tier 2: primary limits documentation.**
6. [Claude Help — Usage limit best practices](https://support.claude.com/en/articles/9797557-usage-limit-best-practices),
   fetched 2026-07-25. **Tier 2: primary usage documentation.**
7. Local screenshots:
   `/mnt/data/Projects/Python/orchestra/data/uploads/photo_20260724_171140_100505.jpg`
   through `100508.jpg`. **Tier 2: launch/system-card benchmark images.**
8. `data/orchestra.db`, direct CLI probe output, and
   `docs/tasks/claude-limit-burn-2026-07-24/analysis.md`.
   **Tier 1: direct operational measurement.**
9. [DataCurve — live DeepSWE v1.1 leaderboard](https://deepswe.datacurve.ai/),
   fetched 2026-07-25. **Tier 2: primary live leaderboard.**
10. [DataCurve — live v1.1 leaderboard JSON](https://deepswe.datacurve.ai/artifacts/v1.1/leaderboard-live.json),
    fetched 2026-07-25; exact selected rows preserved in
    [`deepswe-leaderboard-2026-07-25.csv`](deepswe-leaderboard-2026-07-25.csv)
    and provenance in
    [`deepswe-leaderboard-2026-07-25.meta.json`](deepswe-leaderboard-2026-07-25.meta.json).
    **Tier 1: direct machine-readable measurement.**
11. [DataCurve — DeepSWE v1.1 methodology and revision notes](https://deepswe.datacurve.ai/blog/deepswe-v1-1),
    fetched 2026-07-25. **Tier 2: primary methodology source.**
12. DataCurve Pier source at commit
    [`fefa7475`](https://github.com/datacurve-ai/pier/tree/fefa7475a32bb05271abdea378e8083c83eb5c35):
    [mini-swe-agent cost extraction](https://github.com/datacurve-ai/pier/blob/fefa7475a32bb05271abdea378e8083c83eb5c35/src/pier/agents/installed/mini_swe_agent.py#L300-L328)
    and
    [LiteLLM pricing-map refresh](https://github.com/datacurve-ai/pier/blob/fefa7475a32bb05271abdea378e8083c83eb5c35/src/pier/agents/installed/mini_swe_agent.py#L548-L570),
    fetched 2026-07-25. **Tier 2: primary source code.**
13. `/mnt/data/Projects/Python/orchestra/data/orchestra.db`, logs between
    `2026-07-25T08:58Z` and `09:36Z`: three distinct Codex worker turn
    failures plus repeated direct `circuit_open` probes.
    **Tier 1: direct operational measurement.**
