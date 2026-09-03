# Research: Subscription Strategy — Max $200+Codex $20 vs Max $100+Codex $100

**Date:** 2026-07-21
**Phase:** 1 (Research + Experiment)
**Task:** orchestrator request — is total agent capacity halved after the 2026-07-18 switch?

> ⚠️ **SUPERSEDED IN PART — read [addendum-codex200.md](addendum-codex200.md) after this.**
> A later pass mined `usage_snapshots.provider_usage` (per-provider windows), which was not
> available to the analysis below. It shows **Codex is the hard-blocked resource and Claude
> never blocked**. **Recommendation "Option A" below is WITHDRAWN** — it would have cut the
> constrained resource 5×. Endorsed config: **Codex $200 (20×) + Claude $100 (5×)**, all workers
> → Sol. The measurements and F1–F7 findings below remain valid.

---

## Question (framed)

- **Context:** Orchestra runs Claude (orchestrators, full-cycle) + Codex/Sol (workers) on consumer subscriptions.
- **Change under test:** Claude Max $200→$100 **and** Codex $20→$100, executed 2026-07-18.
- **Baseline:** the prior allocation (Max $200 + Codex $20 = $220/mo).
- **Measurable outcome:** total agent throughput — limit % consumed per unit of delivered work,
  plus the published allowance multipliers on each side.

## TL;DR verdict

The user's instinct — **"capacity went down"** — is **CORRECT**, and the mechanism is real.
But the specific arithmetic (21 → 10 units) is **wrong in both terms**, and the true loss is
**smaller than 2× and is concentrated entirely on the Claude side**. The Codex side went *up* 5×.

| Claim | Verdict |
|---|---|
| "Max 20× = ~20 units, Max 5× = ~5 units, so Claude dropped 4×" | **REFUTED as stated.** The multiplier is *per session vs Pro*, not an absolute capacity unit. Measured real-world loss = **1.77×**, not 4×. |
| "Codex $20 → $100 = 1 unit → 5 units" | **CONFIRMED.** Officially and exactly ×5 (verified arithmetically across 3 models × both range endpoints). |
| "Units are addable: 21 → 10, a 2× total loss" | **REFUTED.** Claude and Codex are separate non-fungible pools; the units are different sizes and cannot be summed. |
| "Overall working capacity fell" | **LIKELY TRUE but narrower than feared** — Claude capacity ~1.8× worse, Codex capacity 5× better. Net effect depends entirely on workload routing. |

---

## Findings

### F1 — Anthropic publishes NO absolute numbers. The user's "20 units vs 5 units" has no official basis. `CONFIRMED`

Verbatim, `support.claude.com/en/articles/11049741` (fetched this session, independently
re-verified by me after the subagent):

> "Max 5x: $100 per month" … "Max 20x: $200 per month"
> "Max 5x provides 5 times more usage **per session** than the Pro plan"
> "Max 20x provides 20 times more usage **per session** than the Pro plan"

Three consequences the user's model misses:

1. The multiplier is relative to **Pro**, and is scoped to **per session** (the 5-hour window).
   It is *not* a statement about weekly capacity.
2. Nominally 20/5 = **4× between tiers for 2× the price** — so on paper the $200 tier is
   twice as capacity-efficient per dollar. But this applies only to the *session* window.
3. **The weekly window is a separate mechanism with no published multiplier at all.**
   Anthropic reserves discretion verbatim: *"may limit your usage in other ways, such as weekly
   and monthly caps or model and feature usage, at our discretion."*

The support page that once carried hard message counts (`11014257-about-claude-max-plan-usage`)
now returns **HTTP 404** — retired. **Any figure like "225/900 messages per 5h" or
"240–480 Sonnet hours/week" is citing a dead or pre-2026 page.** Confidence: CONFIRMED —
primary source, fetched twice, by two independent agents.

**Evidence tier:** 2 (primary source), re-verified.

### F2 — Measured real-world Claude loss is 1.77×, not 4×. `CONFIRMED`

Our own telemetry across the 07-18 downgrade (full method + confounder analysis in
[measurements.md](measurements.md)):

| Period | Turns | 5h% consumed | API-equiv work ($) | **% per $ of work** |
|---|---:|---:|---:|---:|
| Pre-downgrade (≤07-17) | 576 | 486.0 | 831.98 | **0.584** |
| Post-downgrade (≥07-18) | 328 | 419.0 | 405.40 | **1.034** |

**Ratio = 1.77×.** Each unit of delivered work now eats 1.77× more of the 5-hour window.

**Read this as a LOWER BOUND, not a point estimate.** `5h:NN%` is an integer, so turns consuming
<1% register as zero delta. Measured truncation: **82.5%** of pre-period turns were zero-delta vs
**66.1%** post — i.e. the *pre* period is under-counted more, which biases the ratio *downward*.
Correcting would raise it. Confidence interval ~**1.5–2.2×** given quantization noise and the
short window. See self-review A1 in [codex-review-research.md](codex-review-research.md).

Pass/fail was fixed *before* running: ≈4× would support the user's theory, ≈2× linear-with-price,
≈1× no cost. **Result landed near the "linear with price" line (2×), not the "linear with
multiplier" line (4×).**

This is the single most important number in this report, because Anthropic publishes nothing
that answers the question (F1). Four confounders were tested and ruled out (model mix, context
size, agent concurrency, Sol-turn pollution) — three of them *inverted* (the spike days had
lower context and fewer agents).

**Why 1.77× and not the nominal 4×:** the nominal 4× applies to the *session* window only, and
the May 6 2026 SpaceX-compute announcement *doubled* Claude Code's 5-hour limits for all paid
tiers — verbatim *"doubling Claude Code's five-hour rate limits"*
(`anthropic.com/news/higher-limits-spacex`). A tier-independent 2× uplift compresses the
practical gap between tiers. This is a hypothesis for the mechanism, not a measured claim.

**Evidence tier:** 1 (direct measurement), n=904 turns. Confidence CONFIRMED for the ratio;
the *explanation* for why it is 1.77 rather than 4 is LIKELY, not proven.

### F3 — Codex side: exactly ×5, officially. The user's only correct term. `CONFIRMED`

There is **no standalone "Codex Pro" product**. The ~$100/mo tier is **ChatGPT Pro at the 5×
multiplier**. Pro is no longer a single $200 SKU — since **April 9, 2026** it is a tier with a
multiplier chosen at checkout: **$100 = 5×, $200 = 20×.**

Verbatim, `learn.chatgpt.com/docs/pricing` (canonical — `developers.openai.com/codex/pricing`
308-redirects here; fetched and independently re-verified by me):

> Pro: "From $100/month" with "5x or 20x higher rate limits than Plus"

Published local-messages-per-5h ranges:

| Model | Plus ($20) | **Pro 5× ($100)** | Pro 20× ($200) |
|---|---|---|---|
| GPT-5.6 Sol | 15–90 | **75–450** | 300–1800 |
| GPT-5.6 Terra | 20–110 | **100–550** | 400–2200 |
| GPT-5.6 Luna | 50–280 | **250–1400** | 1000–5600 |

Scaling is **exactly linear** — ×5 and ×20 hold across all 3 models × both range endpoints with
no rounding drift. So the user's "Codex 1 unit → 5 units" is **exactly right**: Codex capacity
genuinely quintupled.

> "The usage limits for local messages and cloud chats share a **five-hour window**.
> Additional weekly limits may apply."

**Weekly Codex numbers: NOT PUBLISHED** for any tier. Relevant because Codex is currently
locked out until Jul 25 on a *weekly* cap — i.e. we hit an undocumented ceiling.

**Evidence tier:** 2 (primary), re-verified.

### F4 — The units are NOT addable. The "21 → 10" arithmetic is invalid. `CONFIRMED`

The user's model sums Claude units and Codex units into one total. This is invalid for three
independent reasons:

1. **Different denominators.** A Claude "unit" is 1/20th of Max-20×-per-session; a Codex "unit"
   is Plus-tier Codex allowance. There is no exchange rate between them. Adding them is adding
   different currencies.
2. **Non-fungible work.** Claude runs orchestrators + full-cycle research; Codex runs Sol
   implementation workers. Codex capacity cannot absorb an orchestrator turn — the orchestrator
   *is* the Claude session. Spare Codex allowance does not rescue a saturated Claude window.
3. **Separate pools, no routing.** Prior research (`docs/tasks/codex-limits-abuse/research.md`,
   H2 **REFUTED**) established there is no supported route from one quota to the other.

So the correct framing is **two independent budgets**, each with its own ceiling:
- **Claude budget: ~1.77× worse** (measured).
- **Codex budget: 5× better** (published).

**Evidence tier:** 2 + prior internal research. CONFIRMED.

### F5 — Both vendors are now 4×-capacity-for-2×-price at the top tier. `CONFIRMED (Codex) / LIKELY (Claude)`

A structural symmetry worth acting on:

| | mid tier | top tier | price ratio | capacity ratio | capacity per $ |
|---|---|---|---|---|---|
| Claude Max | $100 (5×) | $200 (20×) | 2× | 4× *(per-session, nominal)* | **top tier 2× better** |
| ChatGPT Pro | $100 (5×) | $200 (20×) | 2× | 4× *(published, exact)* | **top tier 2× better** |

**On both platforms the $200 tier is NOMINALLY twice as capacity-efficient per dollar as the
$100 tier.** "Nominally" is load-bearing: for Claude this is the *published per-session* ratio,
and our own measurement (F2) shows the **realized** gap is ~1.77×, not 4×. So the expected gain
from upgrading Claude back to $200 is **~1.8×, not 4×.** The Codex row is exact (published table);
the Claude row is nominal-only.
Splitting $200 across two $100 mid-tiers buys the *least* efficient point on both curves
simultaneously. That is the real structural mistake in the current allocation — not the 4×
capacity loss the user hypothesized.

Caveat: for Claude this is the *nominal per-session* ratio (F1); our measurement (F2) shows the
realized ratio is 1.77×, so the Claude row is **LIKELY**, not CONFIRMED. The Codex row is
arithmetically exact from the published table.

### F6 — Post-downgrade error/retry storms are a new, real cost. `CONFIRMED`

| Period | Error turns | Total | Error rate |
|---|---:|---:|---:|
| Pre (≤07-17) | **0** | 599 | 0.0% |
| Post (≥07-18) | **37** | 416 | **8.9%** |

Zero → 8.9%. These are limit-rejection retry storms. They log `$0.00 turn` (no work delivered)
while the 5h% **still climbs across them** (observed 07-21: 11%→14% over a run of error turns).
So they burn quota for nothing — a second-order tax on top of the 1.77×, and a source of
operator friction (stalled agents) not captured by the ratio.

**Evidence tier:** 1 (direct measurement). CONFIRMED.

### F7 — Fable 5 on Max burns the weekly budget disproportionately. `CONFIRMED`

`support.claude.com/en/articles/15424964` — from **July 20, 2026**, Fable 5 is standard on Max,
capped at **"up to 50% of your weekly usage limits"**, and verbatim:

> "Fable 5 draws from your plan's regular weekly usage limits and **uses them faster than other Claude models**"

This corroborates the CLAUDE.md note about `seedon-orchestrator` on Fable 5 burning ~30% of the
5h window alone. On the now-halved Claude budget this is materially more damaging than it was
pre-downgrade. **Actionable independent of the subscription decision.**

**Evidence tier:** 2 (primary). CONFIRMED.

---

## Counter-evidence / what argues against the conclusion

Recording these honestly rather than burying them:

1. **The measurement window is short** — 5 days pre vs 4 days post (576 vs 328 turns). A longer
   post-window could move 1.77×. It will not move it to 4× (that would require the post-period
   ratio to more than double), but 1.5×–2.2× is a fair confidence interval.
2. **The day-level series is not a clean step.** 07-19 (0.446) sits *inside* the pre-downgrade
   range; 07-20/21 spike to 1.4/2.1. Aggregate is sound, daily is noisy at n≈50–57.
3. **Cache-hit rate is the one confounder I could NOT fully exclude.** Per-turn token columns
   aren't stored (session-level cumulative only). Cached tokens are cheap in $ but may still
   consume quota, which would bias `pct_per_usd` upward. Mitigating evidence: prior internal
   research (`docs/tasks/cache-optimization/research.md`) measured cache-hit at ~96.9–97.0%,
   stable across Opus 4.6/4.8 — so a large swing in the 4-day window is unlikely but unproven.
4. **`$ turn` is an API-equivalent proxy, not true tokens.** If Anthropic meters quota on a
   basis that diverges from API pricing (e.g. weighting output tokens differently), the
   normalizer is imperfect.
5. **The nominal-4× reading might still be right for *weekly* limits.** We measured the **5-hour**
   window. Weekly caps are a separate undocumented mechanism (F1). If weekly scales closer to 4×,
   the user's pessimism would be more justified for sustained multi-day workloads than our
   session-window measurement suggests. **This is the biggest open risk in the report.**
6. **Codex weekly ceiling is real and undocumented** — we are locked out until Jul 25. The
   published 5× uplift is a *5-hour-window* guarantee; the binding constraint in practice turned
   out to be the unpublished weekly cap.
7. **The 5h window is account-wide; my deltas attribute all movement to the next Claude turn
   that closes.** Any Claude usage outside the logged Orchestra sessions (e.g. interactive
   Claude Code on this machine) enters the numerator with no matching denominator. Both periods
   are subject to it, so direction is safe, but this is the **largest unquantified threat to the
   exact value** of 1.77×. It cannot plausibly explain a 4×-vs-1.77× gap.
8. **Integer quantization** (see F2) — 66–83% of turns register a zero delta, so the estimator
   is coarse. Direction of the bias favours a *higher* true ratio, but precision is limited.

---

## Recommendation

**Primary: consolidate to one $200 top tier rather than two $100 mid tiers.**

Both platforms price the top tier at 4× capacity for 2× cost (F5). The current split buys the
worst point on both curves. Which platform to consolidate on depends on where the pain is:

| Option | Cost | Claude capacity | Codex capacity | When it's right |
|---|---|---|---|---|
| **A. Max $200 + Plus $20** | $220 | **~1.8× recovery** (measured; 4× nominal ceiling, unverified) | **1/5 current** | Claude is the bottleneck (orchestrators, research). **Reverts to the known-good prior state.** |
| **B. Max $100 + Pro $100** *(current)* | $200 | baseline | baseline | Only if workload is genuinely Codex-heavy |
| **C. Max $200 + Pro $100** | $300 | **~1.8× recovery** | current | If budget can stretch; removes both ceilings |

**Recommended: Option A**, for these reasons:
- The measured pain (F2, F6) is **entirely on the Claude side** — 1.77× worse plus a 0→8.9%
  error-storm rate. Codex got *better*, not worse.
- Orchestrators and full-cycle research **cannot be moved to Codex** (F4) — that work is
  structurally Claude-bound, so Claude capacity is the true system bottleneck.
- The prior configuration ($220) is empirically known to have produced **zero** limit-error turns.
- It costs only $20/mo more than today.

**Caveat on Option A — and it is a serious one:** it cuts Codex to Plus (15–90 Sol msgs/5h), a
**5× reduction** on the side that just improved. Hard evidence that this matters: **the Codex
review for this very research task failed with "You've hit your usage limit … try again at
Jul 25th"** — the Codex ceiling is *already binding at the current $100 tier*. Dropping to Plus
would make it bind roughly 5× sooner.

So the fork is real and research cannot close it:
- **Sol workers load-bearing → Option A actively breaks the worker fleet; Option C ($300) is the
  honest answer.**
- **Sol workers optional → Option A is right.**

This depends on intended workload mix and is escalated to the user rather than guessed.

**Do first, regardless of tier choice (free wins):**
1. **Move `seedon-orchestrator` off Fable 5 → Opus 4.6** (F7). Fable is documented to burn weekly
   limits faster and is capped at 50% of them. Already flagged as PENDING in CLAUDE.md.
2. **Fix the retry storms** (F6) — 8.9% of post-downgrade turns burn quota for zero work.
   CLAUDE.md notes the `session.py` terminal-limit patterns fix is written but **awaiting restart**.

---

## Corrections to project docs (found during research)

1. **CLAUDE.md is wrong on Codex:** *"Codex Pro upgrade with $20 (2026-07-18): 5× more reasoning
   budget for Sol workers."* Per official wording it is **5× usage allowance**, not reasoning
   budget. Reasoning effort (`medium`/`high`/`xhigh`) is a per-request knob available on *every*
   tier — raising worker effort consumes allowance faster, it isn't unlocked by the tier. This
   matters because it changes how to reason about `pipeline.yaml` effort settings.
2. **CLAUDE.md 1.9× figure:** stated as "0.142% → 0.270% per turn (1.9×)". My unnormalized
   per-turn replication gives **1.37×**; work-normalized gives **1.77×**. The 1.9× is in the right
   neighbourhood but its derivation isn't reproducible from current data — treat 1.77× as the
   current best estimate.
3. **"July 16 global reset" and "+50% weekly extension to Aug 19"** (CLAUDE.md) — **no primary
   source found.** Only secondary outlets. The documented reset was May 15, 2026. Flag as unverified.
4. **Stale Anthropic doc conflict:** `support.claude.com/.../9797557` still references an
   **Opus-only** weekly bucket; the current Max article says the second bucket is **Sonnet-only**.
   Treat Sonnet-only as current; the Opus weekly cap appears retired.

---

## Affected files / next steps (if Phase 2 is approved)

This is a **business/config decision, not a code change**. Minimal code touchpoints:
- `CLAUDE.md` — fix the 4 corrections above.
- DB: `seedon-orchestrator` model → Opus 4.6.
- `app/session.py` — limit-retry fix already written, awaiting restart (verify it lands).

**Open question for the user that research cannot settle:** are Sol workers load-bearing enough
to justify keeping Codex at $100 (Option C, $300), or can they run on Plus (Option A, $220)?

---

## Sources

All URLs below were fetched during this session (by me directly, or by a subagent and then
re-verified by me for the two load-bearing pages [1][7]).

1. https://support.claude.com/en/articles/11049741-what-is-the-max-plan — Max 5×/20× prices + "per session" wording + two weekly buckets. *(re-verified directly)*
2. https://claude.com/pricing — Pro $20/mo; `anthropic.com/pricing` 301-redirects here
3. https://support.claude.com/en/articles/8325606-what-is-the-pro-plan — Pro baseline
4. https://support.claude.com/en/articles/12429409-manage-usage-credits-for-paid-claude-plans — 5h reset
5. https://support.claude.com/en/articles/15424964-claude-fable-5-on-your-plan — Fable 50% weekly cap, "uses them faster"
6. https://www.anthropic.com/news/higher-limits-spacex — May 6 2026 doubling of Claude Code 5h limits
7. https://learn.chatgpt.com/docs/pricing — ChatGPT tiers, Codex 5h ranges, credits rate card. *(re-verified directly; canonical, 308 from developers.openai.com/codex/pricing)*
8. https://support.claude.com/en/articles/9797557-usage-limit-best-practices — stale Opus-weekly reference (conflict noted)
9. https://support.claude.com/en/articles/11014257-about-claude-max-plan-usage — **HTTP 404, retired** (recorded to show old numbers are dead)

**Internal (Tier-1 measurement):**
- `docs/tasks/subscription-strategy/measurements.md` — this session's telemetry analysis
- `docs/tasks/codex-limits-abuse/research.md` — separate-pool finding (H1 CONFIRMED, H2 REFUTED)
- `docs/tasks/cache-optimization/research.md` — 96.9–97.0% cache-hit stability

**Blocked / could not verify:** `help.openai.com` articles (HTTP 403), `chatgpt.com/pricing` (403).
No claim above rests on them.
