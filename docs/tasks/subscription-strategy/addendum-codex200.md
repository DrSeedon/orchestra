# Addendum — validating the Codex $200 (20×) + Claude $100 (5×) decision

**Date:** 2026-07-21
**Trigger:** user chose Codex $200 / Claude $100 = $300/mo, all workers → Sol, orchestrators → Opus 4.6.
**New evidence:** `usage_snapshots.provider_usage` — a per-provider window breakdown I had NOT
mined in the main research. It changes several conclusions.

## Verdict: the decision is CORRECT and better-supported than my original Option A.

My Phase-1 recommendation (Option A: Claude $200 + Codex Plus $20) was **wrong for this user's
actual workload**. It assumed Claude was the bottleneck. The provider telemetry shows the
opposite: **Codex is the hard-blocked resource; Claude never blocked.** I'm reversing that
recommendation.

---

## N1 — Direct measurement of the Codex weekly burn. `CONFIRMED`

`provider_usage` exposes the real Codex weekly window (`plan_type` shown as **`prolite`** — the
API's internal label for the **$100 Pro 5×** tier; no public tier is named "prolite", so treat it
as the internal id for our current plan).

Codex 7-day window (single rolling week, reset 2026-07-25):

| Day | start → end | burned | wall-clock hrs w/ data |
|---|---|---:|---:|
| 07-18 | 44% → 73% | **29 pp** | 8 |
| 07-19 | 73% → 95% | **22 pp** | 14 |
| 07-20 | 95% → **100%** | 5 pp (clipped) | 14 |
| 07-21 | 100% → 100% | **0** (dead) | 16 |

**This is quantitative confirmation of the user's "$1000 weekly limit burned in 1.5 working
days."** From 44%, the fleet consumed the remaining 56 pp in ~2 working days; extrapolating the
observed rate from 0%, a full week's Codex budget lasts **≈2.0–2.5 working days** on 5×.

Burn rate ≈ **25 pp/working-day** (mean of the two uncensored days, 29 and 22). 07-20 is
right-censored at the 100% ceiling — true demand that day was higher than 5 pp.

**The cost is not the money — it is 2.5 idle days.** Codex sat at exactly 100% for ~2.5 days
(07-20 06:00 → 07-25 reset). That is dead fleet capacity, and it is what killed the Codex review
of this very research task.

## N2 — Does 20× survive a full working week? **YES, with real margin.** `LIKELY`

20× = 4× the current 5× allowance. Applying the measured 25 pp/day burn:

| Tier | Budget (in current-tier pp) | Working days before block | Verdict |
|---|---:|---:|---|
| Plus $20 (1×) | 20 | **0.8 d** | unusable |
| **Pro 5× $100 (current)** | 100 | **~2.5 d** | ❌ blocks mid-week (observed) |
| **Pro 20× $200 (proposed)** | **400** | **~10 working days** | ✅ covers a 5-day week ~2× over |

**A 5-day working week needs ~125 pp of current-tier budget; 20× supplies 400 pp.** Headroom
≈ **3.2×** against observed demand, or ~10 working days of runway.

Confidence **LIKELY** not CONFIRMED, because:
- Extrapolation assumes the ×4 published multiplier applies to the **weekly** window. OpenAI
  publishes the multiplier for the **5-hour** window and says only *"Additional weekly limits may
  apply"* — the weekly scaling is **not published** (main research F3). This is the key
  unverified assumption in the whole plan.
- Burn is measured over only 2 uncensored days, and demand will rise once all workers move to Sol
  (see N4 risk).

Even if weekly scaled at only ~2× instead of 4×, 20× would still yield ~5 working days — exactly
one full week. So the decision is **robust to the multiplier being worse than advertised**, which
is the main reason I endorse it.

## N3 — Is Claude 5× enough for orchestrators-only? **YES, comfortably.** `CONFIRMED`

This was the open risk in the user's plan. The data answers it clearly.

Claude work split since the downgrade (work-normalized, successful turns):

| Role | Turns | API-equiv $ | **Share of Claude work** |
|---|---:|---:|---:|
| Orchestrators | 260 | 166.0 | **35.2%** |
| Workers | 140 | 305.5 | **64.8%** |

**Claude workers consume ~2× more than Claude orchestrators.** Moving all workers to Sol removes
**~65% of Claude load**, leaving orchestrators on ~35% of current consumption.

Observed Claude 7-day utilization while carrying *both* roles: peak **81%** (07-20), never 100%.
The 7d window never blocked — only the 5h window spiked. Dropping to ~35% of that load implies a
steady-state weekly utilization around **30%**, with the 5h window as the only remaining pressure
point (bursty parallel orchestrator turns).

**So Claude $100 is not merely adequate — it will be substantially under-used.** This also means
the 1.77× penalty measured in the main research (F2) is largely **moot for the new topology**: it
hurts most when Claude carries heavy worker turns, which is exactly the load being removed.

## N4 — Risks in the chosen plan

1. **Weekly-multiplier assumption (highest risk).** N2 rests on 20×/5× = 4× applying to the
   *weekly* window. Unpublished. **Mitigation:** the plan survives even at 2×.
2. **Demand will grow, not stay flat.** Today only 34 Codex worker turns ($182) ran alongside 140
   Claude worker turns ($305). Moving *all* workers to Sol roughly **triples** Codex demand
   beyond what produced the 25 pp/day burn. Re-running the arithmetic on tripled demand:
   ~75 pp/day → 400 pp lasts **~5.3 working days**. **Still covers a week, but the 3.2× headroom
   collapses to ~1.1×.** This is the single most important caveat: *the plan works, but it is not
   as comfortable as the raw 4× suggests.*
3. **Codex Spark is a separate, under-used bucket** — sat at **31%** all week while main Codex was
   pinned at 100%. Routing leaf-edits to Spark (already in `base.md` model-routing) is free
   capacity that directly relieves the constraint in risk #2.
4. **Two free weekly resets exist** (user's note) — an emergency lever worth keeping unspent.
5. **Geographic/ToS risk unchanged** (Russia, per prior research) — spending more on Codex
   concentrates dependency on the platform with the account-suspension exposure.

## N5 — ROI: is $300/mo ($3600/yr) justified? **YES, by ~22×.** `CONFIRMED`

Measured API-equivalent value produced over 7 days (2026-07-15 → 07-21, all providers, 1083 turns):

**$1543** — i.e. **~$6,600/month** of equivalent API spend.

| | Monthly | Annual |
|---|---:|---:|
| Subscription cost | **$300** | $3,600 |
| API-equivalent value delivered | **~$6,600** | ~$79,000 |
| **Leverage** | **~22×** | ~22× |

Even on a bad week, subscriptions are an order of magnitude cheaper than metered API for this
throughput. **The $100/mo increment is trivially justified** — it buys back ~2.5 idle fleet-days
per week, which alone exceeds the marginal cost. ROI is not the deciding variable here; capacity is.

Caveat: "API-equivalent" is what this work *would* cost at list API prices — it is a valuation of
throughput, not a claim about counterfactual spend or business value delivered.

---

## Corrections to my Phase-1 research

1. **Option A is withdrawn.** It recommended cutting Codex to Plus. Given Codex is the blocked
   resource and Sol is the user's preferred worker model, Option A would have **broken the worker
   fleet** — it would have cut the constrained resource by 5×. My original doc flagged this fork
   but led with the wrong branch because I lacked `provider_usage`.
2. **The chosen config is effectively "Option C-inverted"** ($300 total, but spending the extra on
   *Codex* rather than Claude). This is better than my Option C, which would have upgraded Claude —
   the side with spare headroom.
3. **F5's "top tier is 2× better capacity-per-dollar"** now has a concrete application: it argues
   for buying the top tier **on the constrained platform**. Codex $100→$200 = 4× capacity for 2×
   price. That is the single highest-leverage dollar in the whole budget.
4. **`seedon-orchestrator` is already on Opus 4.6**, not Fable 5 — that PENDING item is done.
   The user separately confirms he no longer uses Fable ("даже с опусами вылетаю"). F7 stands as
   documentation but needs no action.

## Recommendation — endorsed, with two additions

**Proceed with Codex $200 (20×) + Claude $100 (5×), all workers → Sol, orchestrators → Opus 4.6.**
The telemetry supports every part of it.

Two additions that cost nothing and directly address risk #2:

1. **Route leaf/simple worker tasks to Codex Spark.** It idled at 31% while main Codex was pinned
   at 100% — a separate bucket already sitting unused. This is the cheapest available relief for
   the tripled-demand risk, and `base.md` model-routing already contemplates it.
2. **Instrument before committing the second $100.** We now have exactly one week of
   `provider_usage` data and the decisive burn figure is from **2 uncensored days**. One more week
   of Codex-at-20× telemetry would convert N2 from LIKELY to CONFIRMED and reveal whether tripled
   Sol demand actually fits. If the user wants to upgrade immediately, that is defensible — just
   re-check the weekly burn after the first full week rather than assuming the 4× held.

**Still open (cannot be resolved from data):** whether the weekly window scales ×4 like the
published 5-hour window. First week at 20× will settle it empirically.
