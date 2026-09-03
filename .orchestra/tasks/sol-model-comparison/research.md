# GPT-5.6 Sol vs Terra vs Luna for Orchestra

**Research date:** 2026-07-18

## Question

- **Context:** Orchestra runs local Codex CLI workers authenticated through a ChatGPT Pro 5× subscription. The current `pipeline.yaml` declares GPT-5.6 Sol at `medium` for disposable/system workers and Sol at `xhigh` for full-cycle workers, but the runtime still requires the spawner to pass the model explicitly; only effort is currently derived from the role.
- **Change under test:** route clear/high-volume work to Luna, everyday repository work to Terra, and reserve Sol for capability-first work; choose the lowest effort that preserves task success.
- **Baseline:** current Sol `medium` / Sol `xhigh` policy.
- **Outcome:** coding-task success first, then wall-clock latency and real subscription consumption; API-equivalent dollars are diagnostic only because Orchestra does not use API billing.

## Hypotheses considered

1. **H1:** Luna at a higher effort can replace lower-effort Sol for clear, disposable work because model-tier savings can fund more reasoning. **Falsifier:** coding-agent results show a material regression against the actual Sol `medium` baseline, or representative Orchestra trials lose completed-task rate after accounting for tests and retries.
2. **H2:** Terra at `max` can replace Sol at `xhigh` for full-cycle work because it approaches the same coding score at lower usage. **Falsifier:** general reasoning/research results or coding results retain a material Sol advantage that is valuable for phase-1 decisions.
3. **H3:** keeping Sol for every worker is optimal after the Pro upgrade because quality matters more than virtual API dollars. **Falsifier:** lower tiers meet the same success threshold while materially increasing the number of tasks per five-hour window.
4. **H4:** `max` and `ultra` are interchangeable effort labels. **Falsifier:** Codex documentation/runtime shows that `max` is single-agent reasoning while `ultra` is automatic multi-agent delegation.

## Pre-registered local experiment

- **Configurations:** Luna `high`, Terra `max`, Sol `xhigh`; two independent ephemeral Codex CLI runs each.
- **Task:** inspect one fixed Python concurrency snippet without tools or file edits.
- **Ground truth:** real defects are B1, B2, B3, and B5. B4 is a decoy: the implementation neither stores the exception nor mutates `_values` when the loader raises.
- **Pass/fail:** pass when a run reports at least four real defects, does not report B4 as a high-severity defect, and marks the implementation unsafe.
- **Metrics:** pass rate, elapsed wall time to final answer, and reported input/cached/output/reasoning tokens.
- **Scope limitation:** the fixture supplies the candidate bug IDs and descriptions, so it measures checklist recognition more than independent defect discovery. It tests local ChatGPT-auth latency, not repository editing or tool use. The raw JSONL was not retained, so the reported runs are not independently auditable. Treat this as a smoke test with zero weight in the production routing decision; the Artificial Analysis coding-agent suite remains the stronger agentic measurement.

## Executive conclusion

Do **not** replace Sol globally, and do **not** move disposable workers to Luna by default yet. The best-supported production policy is the current one, with Luna `high` as a measured pilot candidate:

| Workload | Recommended model × effort | Decision |
|---|---|---|
| Disposable `impl-*` / `fix-*`, clear AC and strong tests | **Sol `medium` production; Luna `high` pilot** | Luna is promising for bounded work, but public data shows 48 vs 55 for the actual Sol `medium` baseline. Require an Orchestra A/B before changing the default. |
| Long-lived system worker (`backend`, `frontend`) | **Sol `medium`** | Keep current setting. It is stronger and faster than the quota-saving Terra alternatives on the current coding-agent matrix. |
| Full-cycle research / planning / ambiguous changes | **Sol `xhigh`** | Keep current setting. It beats Terra `max` on both general intelligence and coding-agent score and is faster in the agent benchmark. |
| Exceptional one-off problem after a failed `xhigh` run | **Sol `max`** | Manual escalation only, not a default. |
| Any Orchestra role | **No `ultra`** | Ultra is nested multi-agent execution, not a reasoning-effort increment; Orchestra already owns decomposition and worker fan-out. |

The concrete production recommendation for `pipeline.yaml` is therefore **no model/effort change**: keep the existing `worker` and `full-cycle` values. If a Luna pilot is approved, add a distinct disposable role for its `high` effort, but also pass `model: gpt5.6luna` explicitly at spawn time. Adding `model` to the role alone does not route the session today. The current `worker` role covers both disposable and system workers, so changing it to Luna would trade away measured quality, while changing it to Terra does not improve the quality/latency frontier.

## 1. Model family: capability, architecture, price, context

OpenAI describes Sol, Terra, and Luna as three durable capability tiers that can advance independently: Sol is the flagship, Terra roughly corresponds to the older `mini` tier, and Luna roughly corresponds to the older `nano` tier.[1][3][5] OpenAI has not disclosed parameter counts, layer counts, routing topology, training compute, or whether each SKU is a separately trained dense/MoE model. “Architecture” claims beyond the public tier mapping are therefore unsupported.

| Property | Sol | Terra | Luna |
|---|---:|---:|---:|
| Official position | Frontier / complex open-ended work | Everyday balance of intelligence and cost | Clear, repeatable, high-volume work |
| Approx. earlier tier | Unsuffixed flagship | `mini` | `nano` |
| API input / cached / output, per 1M | $5 / $0.50 / $30 | $2.50 / $0.25 / $15 | $1 / $0.10 / $6 |
| Codex credits input / cached / output, per 1M | 125 / 12.5 / 750 | 62.5 / 6.25 / 375 | 25 / 2.5 / 150 |
| API context / max output | 1,050,000 / 128,000 | 1,050,000 / 128,000 | 1,050,000 / 128,000 |
| Codex Pro 5× local messages / 5h | 75–450 | 100–550 | 250–1,400 |

API prices come from OpenAI’s launch and model pages; the credit rates and Pro ranges are the current Codex subscription rate card.[3][4][5] A subscription message is not a fixed unit: context, effort, tool use, retrieval, and caching all affect consumption, so the ranges cannot be converted into a reliable “messages per effort” table.[4]

All three API pages report the same February 16, 2026 knowledge cutoff.[5] Orchestra does **not** receive the public 1.05M window through ChatGPT-auth Codex CLI. The local Codex 0.144.5 catalog reports a 272,000-token window with 95% effective use, and a live rollout emitted `model_context_window=258400`; this exactly matches `272000 × 0.95`. Orchestra’s existing 258,400 constants are therefore correct for this surface, not evidence that the public API docs are wrong.

**Confidence: CONFIRMED** — official primary docs plus a direct runtime measurement. Parameter-level architecture remains **UNCERTAIN** because OpenAI does not publish it.

## 2. What effort controls

Reasoning effort is an upper guidance level for how much internal reasoning the model may use. It is adaptive rather than a fixed token reservation: easy prompts can use little reasoning even at a high setting, while difficult prompts can consume much more.[1] Higher effort generally increases answer latency and token/credit use and can improve planning, checking, and hard-problem success; the improvement is workload-dependent and shows diminishing returns.

| User-facing label | Codex CLI / `pipeline.yaml` | Meaning for Orchestra |
|---|---|---|
| Light | `low` | “Light” is the app/web/IDE label; the CLI spelling is `low`.[2] |
| Medium | `medium` | Balanced default for agentic coding and research. |
| High | `high` | More planning/checking for difficult multi-step work. |
| Extra High | `xhigh` | Long, difficult research/coding; use only when measured benefit matters. |
| Max | `max` | Maximum **single-agent** reasoning depth. |
| Ultra | not a normal effort | Automatic task delegation to subagents; a different execution topology.[2][3] |

The public API also documents `none`, while Orchestra’s backend currently accepts legacy `minimal` and the set `low|medium|high|xhigh|max`. It does not accept `light`, `none`, or `ultra`; an unsupported value silently falls back to `high` in `CodexBackend`. Consequently, putting `effort: ultra` in `pipeline.yaml` today would **not** enable Ultra—it would quietly run `high`.

The local Codex catalog confirms `ultra` is offered for Sol and Terra, but not Luna, and describes it as “maximum reasoning with automatic task delegation.” OpenAI’s launch evaluation used four agents for Ultra, counting all agents’ output tokens and cost while measuring latency from the root agent.[3] This is precisely the decomposition layer Orchestra already implements, so nested Ultra would obscure ownership, usage accounting, and failure attribution.

**Confidence: CONFIRMED** — official documentation, the local model catalog, and the actual backend validation path agree.

## 3. Benchmark evidence and Raschka’s claim

### Launch results at the top setting

OpenAI’s July 9 table and Artificial Analysis’ release analysis report the following top-setting results.[3][6]

| Benchmark | Sol | Terra | Luna | GPT-5.5 |
|---|---:|---:|---:|---:|
| AA Coding Agent Index v1.1 | 80.0 | 77.4 | 74.6 | 76.4 |
| DeepSWE v1.1 | 72.7% | 69.6% | 67.2% | 67.0% |
| Terminal-Bench 2.1 | 88.8% | 87.4% | 84.7% | 85.6% |
| Agents’ Last Exam | 52.7% | 50.4% | 50.3% | 46.9% |
| AA Intelligence Index v4.1 | 58.9 | 55.0 | 51.2 | 54.8 |

This establishes the tier order but also shows that the gaps are often small relative to the 2×/5× token prices. It does **not** prove that a smaller tier is always equivalent: Sol’s advantage grows on some long-context, cyber, science, and abstract-reasoning evaluations.[3]

### Current per-effort coding-agent matrix

Artificial Analysis’ live Codex comparison was re-scaled after the launch: its current composite tops out at 61 rather than the v1.1 launch score of 80. The two versions must not be mixed in one arithmetic comparison. The current page gives the following internally comparable matrix.[7]

| Effort | Luna score / time | Terra score / time | Sol score / time |
|---|---:|---:|---:|
| `low` | 23 / 1.9m | 34 / 2.8m | 49 / 3.7m |
| `medium` | 38 / 3.4m | 44 / 4.3m | 55 / 5.2m |
| `high` | 48 / 5.7m | 51 / 6.2m | 58 / 6.3m |
| `xhigh` | 51 / 6.6m | 53 / 6.9m | 59 / 7.4m |
| `max` | 54 / 8.0m | 57 / 8.4m | 61 / 10.2m |

The launch chart behind Sebastian Raschka’s recommendations used the older v1.1 scale and total API cost of the full evaluation suite.[10] Its qualitative Pareto observation remains useful, but the literal labels require translation:

- “Below Sol High, use Luna at a higher effort” is **directionally supported**, not universally equivalent. On the current matrix, Luna `high` roughly matches Sol `low` (48 vs 49), while Luna `max` roughly matches Sol `medium` (54 vs 55).
- “Replace Sol Extra High with Terra Ultra” depends on **Ultra**, not Terra `max`. Orchestra cannot express that configuration through `effort`, and nested subagents are undesirable here.
- “Sol Ultra is not worth the extra over Max” is consistent with diminishing returns and with OpenAI’s own guidance that most tasks do not need Max or Ultra.[2]

Artificial Analysis also reports that Luna and Sol, rather than Terra, form the general intelligence-versus-cost Pareto frontier across the tested efforts.[6] Terra remains a sensible middle SKU, but it is not automatically the best default merely because its sticker price sits between the other two.

**Confidence: CONFIRMED for measured scores; LIKELY for workload routing** — the agent suite is broad and independent, but no public benchmark reproduces Orchestra’s exact prompts, tools, cache state, and gated workflow.

## 4. Speed: decode rate is not task latency

At the same `max` effort, Artificial Analysis’ first-party API measurements fetched on July 18 show the smaller models decoding much faster, but reasoning time dominates time-to-first-answer.[8][9][11]

| Model (`max`) | Output speed | Time to first answer token | Approx. 500-token completion after first answer token |
|---|---:|---:|---:|
| Sol | 55.0 tok/s | 129.28s | 9.1s |
| Terra | 135.8 tok/s | 137.48s | 3.7s |
| Luna | 185.5 tok/s | 98.45s | 2.7s |

These are API snapshots, not guarantees for ChatGPT-auth Codex. They are also volatile as routing changes. More importantly, “TTFT” for a reasoning model includes hidden thinking before the first answer token. Effort changes that delay dramatically: AA reports about 4–5s for Sol `medium`, 11.36s for Sol `high`, 43.37s for Sol `xhigh`, and 6.45s for Luna `high`.[8][11][12]

In the full coding-agent benchmark, tool calls and reasoning reverse some naive decode-speed expectations: Sol `xhigh` completed tasks in 7.4 minutes versus Terra `max` at 8.4 and Luna `max` at 8.0.[7] Therefore, choose by **wall time per successful task**, not tokens/second alone.

**Confidence: CONFIRMED snapshot, LIMITED generalization** — direct AA measurements and the live agent suite agree that Luna decodes fastest, while agent wall time depends on effort and behavior.

## 5. Local Codex experiment

Raw results from the pre-registered two-run check:

| Configuration | Passes | Final-answer wall time | Input / cached tokens | Output / reasoning tokens |
|---|---:|---:|---:|---:|
| Luna `high` run 1 | pass | 10.470s | 15,618 / 8,960 | 376 / 226 |
| Luna `high` run 2 | pass | 8.894s | 15,618 / 8,960 | 294 / 142 |
| Terra `max` run 1 | pass | 15.967s | 16,809 / 9,984 | 663 / 516 |
| Terra `max` run 2 | pass | 12.365s | 16,809 / 9,984 | 472 / 327 |
| Sol `xhigh` run 1 | pass | 20.202s | 16,809 / 9,984 | 364 / 204 |
| Sol `xhigh` run 2 | pass | 16.959s | 16,809 / 9,984 | 310 / 169 |

All six runs found B1/B2/B3/B5, rejected decoy B4, and marked the code unsafe. Mean wall time was 9.682s for Luna `high`, 14.166s for Terra `max`, and 18.581s for Sol `xhigh`. The non-monotonic reasoning-token totals demonstrate adaptive effort; they do **not** show that Luna is generally smarter or ready to replace Sol `medium`. The checklist was leading, the task saturated at 100% success, and the raw JSONL was not preserved. These results are a latency sanity check only.

**Confidence: LIMITED** — `n=2`, leading checklist, no tool use, and no retained raw log. No production decision depends on this fixture.

## 6. Codex Pro 5×, Max, and Ultra limits

The $100 Pro tier maps to the documented “Pro 5×” allowance: 75–450 Sol, 100–550 Terra, or 250–1,400 Luna local messages per shared five-hour window; additional weekly limits may apply.[4] OpenAI does not publish a separate Max or Ultra message count, a deterministic effort multiplier, or a guaranteed weekly number. The only defensible statement is that more reasoning, larger context, and more tools consume the allowance faster.[4]

Max is available to users with GPT-5.6 access, but should not be the default. In current AA data, Sol `xhigh → max` moves general intelligence 58→59 and the coding-agent score 59→61 while agent time rises 7.4→10.2 minutes.[7][8][12] That is a valid manual escalation for a failed high-value task, not a fleet setting.

Ultra is available in Codex on Plus and higher plans, but it uses subagents rather than a larger single-agent reasoning budget.[2][3] There is no published fixed quota multiplier. OpenAI’s own benchmark accounting includes all four agents’ tokens, so Ultra should be expected to burn allowance materially faster even when wall-clock time improves.[3]

**Confidence: CONFIRMED on published ranges and availability; UNCERTAIN on per-effort/weekly limits because OpenAI does not publish them.**

## 7. Recommended Orchestra policy

### Disposable workers

Keep **Sol `medium`** as the production default. Run **Luna `high`** only as an explicit pilot for tasks with a clear spec, narrow ownership, and an executable verifier. Luna `high` nearly matches Sol `low`, but the actual baseline is Sol `medium` and the live coding matrix shows a material 48→55 gap. OpenAI's per-model message ranges suggest that Luna can preserve more allowance, but they do not prove higher throughput for Luna `high` in Orchestra's tool-heavy workflow.

The go/no-go test should compare at least Luna `high`, Luna `max`, and Sol `medium` on representative Orchestra tasks, recording first-pass test success, retries, total wall time, context consumed, and five-hour/weekly allowance depletion. Until Luna reaches the same completed-task threshold, route failures and ambiguous work back to Sol rather than retrying creatively.

### System workers

Keep **Sol `medium`**. Current data shows Sol `medium` at 55 / 5.2m versus Terra `max` at 57 / 8.4m: Terra buys only two index points for about 62% more wall time, while Terra `high` and `xhigh` are both weaker and slower than Sol `medium`.[7] With Pro 5× and warm long-lived contexts, the modest quota saving does not justify a default regression. Terra `max` is a reasonable temporary limit-pressure fallback, not the primary setting.

### Full-cycle research

Keep **Sol `xhigh`**. It scores 58 on the current AA Intelligence Index versus Terra `max` at 55, and 59 versus 57 on the current coding-agent index, while completing the agent suite faster (7.4m versus 8.4m).[7][8][9][12] Full-cycle Phase 1 makes high-leverage decisions where a small capability advantage is worth more than virtual API-equivalent dollars.

Do not default to Sol `max`: the measured gain over `xhigh` is small. Do not use Ultra inside a full-cycle worker: Phase 1 already has explicit Orchestra-level parallel research, and nested fan-out would make evidence provenance and usage accounting worse.

### Production `pipeline.yaml`

Keep the quality-first settings for existing roles:

```yaml
roles:
  worker:
    model: gpt5.6sol
    effort: medium

  full-cycle:
    model: gpt5.6sol
    effort: xhigh
```

For an approved Luna pilot, add a separate role rather than weakening every `worker`:

```yaml
  disposable:
    kind: worker
    label: Disposable
    model: gpt5.6luna
    effort: high
    when: Clear one-shot implementation or fix with executable acceptance tests
    not_for: Research, ambiguous scope, architecture, or work without a verifier
```

This YAML supplies the pilot's `high` effort and documents the intended model, but it does not currently enforce the model. `manager.create_session()` resolves the model argument before looking up the role, while `spawn_worker` requires an explicit model; the pilot must therefore spawn with both `role="disposable"` and `model="gpt5.6luna"`. A later implementation should make role model resolution authoritative (with an explicit override only when requested) so `pipeline.yaml` becomes the single source of truth. Adding an `effort` argument to `spawn_worker` is another possible implementation, but would create two policy paths.

## Hypothesis outcomes

| Hypothesis | Outcome | Evidence |
|---|---|---|
| H1: higher-effort Luna can replace lower-effort Sol | **UNPROVEN against current default** | Luna `high`≈Sol `low`, not Sol `medium`; Luna `max`≈Sol `medium`. Requires a representative Orchestra A/B before default routing. |
| H2: Terra `max` should replace Sol `xhigh` full-cycle | **REFUTED as default** | Sol is +3 general-intelligence points, +2 coding points, and ~1 minute faster per agent task. |
| H3: keep Sol for every worker | **NOT REFUTED for production** | Keep current defaults. Luna remains a plausible disposable pilot because model-level allowance ranges are larger, but end-to-end throughput is unmeasured. |
| H4: Max and Ultra are effort synonyms | **REFUTED** | Max is single-agent reasoning; Ultra delegates to subagents. |

## Counter-evidence and cautions

- Raschka’s graph makes Terra Ultra attractive against Sol Extra High, but that comparison depends on an execution mode Orchestra intentionally does not expose. Translating “Ultra” to `max` changes the claim.
- The live AA Coding Agent Index was re-scaled from the launch v1.1 values. Rankings remain similar, but absolute scores such as 80 and 61 are not directly comparable.[3][7]
- OpenAI’s own benchmark table is first-party release evidence; Artificial Analysis provides independent evaluation, but OpenAI supported its pre-release access.[6] Neither reproduces Orchestra’s prompts or gating.
- The system card reports cases where Sol claimed unfinished work was complete or fabricated research verification.[13] Orchestra’s evidence-based done conditions, external tests, and adversarial review remain necessary; a stronger model is not a substitute for verification.
- Exact subscription usage cannot be inferred from API dollars. Orchestra should validate the policy on its own completed-task rate, wall time, retries, and five-hour/weekly depletion before changing more roles.
- Role-level `model` is currently descriptive rather than authoritative during session creation. Any future routing proposal that edits only `pipeline.yaml` is incomplete until spawners or manager model resolution are changed.

## Adversarial second opinion

A local GPT-5.5 `high` review returned `VERDICT: BLOCKED` on the first draft. Its four material objections were accepted: Luna `high` had been compared to Sol `low` rather than the actual Sol `medium` baseline; YAML role models do not currently control runtime routing; the local checklist was leading and lacked retained raw JSONL; and model-level subscription ranges do not prove effort-specific Orchestra throughput. This revision demotes Luna to a pilot, keeps the production config unchanged, documents the explicit spawn requirement, and removes the local smoke test from the decision evidence. The first review is preserved in `codex-review-research.md`; a bounded second pass accepted all resolutions with `VERDICT: ACCEPT` in `codex-review-research-round2.md`.

## Affected files and implementation risks

- `pipelines/default/pipeline.yaml` — current role defaults; a new `disposable` role would live here.
- `app/backend_codex.py` — valid effort set excludes `ultra` and silently falls back to `high`; the 258,400 effective context and token prices are correct for the current surface.
- `app/models.py` — model aliases and effective Codex context constants.
- `app/mcp_stdio.py` — `spawn_worker` requires a model argument but has no effort override.
- `app/manager.py` — the explicit model argument is used directly, while effort is resolved from the selected pipeline role. This makes `pipeline.yaml` model values non-authoritative at spawn time.

Risks for a later change: existing sessions persist their current model/effort; adding a role must preserve routing determinism; accepting `ultra` without dedicated lifecycle/accounting would create nested orphan-management and cost-attribution problems; unsupported effort values should fail loud rather than silently become `high`.

## Sources

1. **Primary:** [OpenAI — Using GPT-5.6 / latest model guidance](https://developers.openai.com/api/docs/guides/latest-model)
2. **Primary:** [OpenAI — Codex models and reasoning controls](https://developers.openai.com/codex/models)
3. **Primary:** [OpenAI — GPT-5.6 launch, benchmarks, availability, pricing](https://openai.com/index/gpt-5-6/)
4. **Primary:** [OpenAI — Codex pricing, credits, and subscription usage limits](https://learn.chatgpt.com/docs/pricing#what-are-the-usage-limits-for-my-plan)
5. **Primary:** [OpenAI API model pages: Sol](https://developers.openai.com/api/docs/models/gpt-5.6-sol), [Terra](https://developers.openai.com/api/docs/models/gpt-5.6-terra), [Luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna)
6. **Direct independent measurement:** [Artificial Analysis — GPT-5.6 benchmarks across Intelligence, Speed and Cost](https://artificialanalysis.ai/articles/gpt-5-6-has-landed)
7. **Direct independent measurement:** [Artificial Analysis — live Claude Code vs Codex model-variant matrix](https://artificialanalysis.ai/agents/coding-agents/comparisons/claude-code-vs-codex)
8. **Direct independent measurement:** [Artificial Analysis — Sol max](https://artificialanalysis.ai/models/gpt-5-6-sol) and [Sol xhigh](https://artificialanalysis.ai/models/gpt-5-6-sol-xhigh)
9. **Direct independent measurement:** [Artificial Analysis — Terra max](https://artificialanalysis.ai/models/gpt-5-6-terra)
10. **Secondary analysis of direct measurements:** [Sebastian Raschka — model×effort Pareto interpretation](https://x.com/rasbt/status/2075573860796436626)
11. **Direct independent measurement:** [Artificial Analysis — Luna max](https://artificialanalysis.ai/models/gpt-5-6-luna) and [Luna high](https://artificialanalysis.ai/models/gpt-5-6-luna-high)
12. **Direct independent measurement:** [Artificial Analysis — Sol medium](https://artificialanalysis.ai/models/gpt-5-6-sol-medium) and [Sol high](https://artificialanalysis.ai/models/gpt-5-6-sol-high)
13. **Primary:** [OpenAI GPT-5.6 System Card](https://deploymentsafety.openai.com/gpt-5-6)
