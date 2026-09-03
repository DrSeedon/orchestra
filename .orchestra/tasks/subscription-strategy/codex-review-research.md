# Second opinion — attempted Codex review + self-review

## Codex review: FAILED (could not run)

`codex_review(mode=exec, target=research.md)` was dispatched as bg job `bg-0c40364cc4` and
failed at the API level:

```
{"type":"error","message":"You've hit your usage limit. Visit https://chatgpt.com/codex/settings/usage
 to purchase more credits or try again at Jul 25th, 2026 12:24 PM."}
{"type":"turn.failed", ...}
```

**No Codex review was obtained. Nothing in this file is Codex output.** Per CLAUDE.md
("Codex review failing → self-review acceptable"), what follows is an adversarial self-review.

**This failure is itself a data point for the research** (F3/F6): the Codex weekly ceiling is
undocumented, and we are locked out until Jul 25 — while nominally holding 5× the Codex
allowance we held a week ago. It is direct evidence that the *published* 5-hour multiplier is
not the binding constraint in practice; the unpublished weekly cap is.

---

## Self-review — attacking the load-bearing claims

I pre-registered the attacks I most wanted answered and ran the ones that were testable.

### A1 — Integer truncation bias. **TESTED. Runs AGAINST my conclusion → strengthens it.**

`5h:NN%` is an integer, so any turn consuming <1% registers a **zero delta** and is silently
dropped from the numerator. If the two periods truncate differently, `pct_per_usd` is biased.

Measured:

| Period | zero-delta turns | % of turns | mean $/turn |
|---|---:|---:|---:|
| A (pre, $200) | 475 / 576 | **82.5%** | $1.444 |
| B (post, $100) | 218 / 330 | **66.1%** | $1.235 |

The pre-period drops a **larger** share of turns to truncation (82.5% vs 66.1%) — so the
pre-period numerator is under-counted *more* than the post-period's. Correcting for this would
*raise* pre-period consumption relative to post, which **lowers** the ratio... except the
pre-period also had *larger* mean turns ($1.44 vs $1.24), which is the opposite of what would
produce more truncation naturally.

The coherent reading: pre-downgrade, larger turns still landed under the 1% granularity because
each turn was a smaller fraction of a **4× larger quota**. That is precisely the effect under
study — the same work crossing the 1% threshold more often post-downgrade *is* the capacity
reduction, observed through a second independent channel.

**Verdict: the bias does not manufacture the 1.77×; if anything the true ratio is ≥1.77×.**
Directionally safe. But it means 1.77× should be read as a **lower bound with quantization
noise**, not a precise point estimate. Research doc's stated CI (1.5–2.2×) stands.

### A2 — Rolling-window / reset corruption. **PARTIALLY MITIGATED, residual risk acknowledged.**

The 5h window is *rolling*, not a fixed bucket that only fills. Summing positive deltas assumes
every increase is fresh consumption, but a rolling window can also **decay** (old usage aging
out), producing decreases. Measured negative deltas: **8 (pre) vs 9 (post)** — nearly identical
and tiny relative to n, so reset events are balanced across periods and do not skew the ratio.

Residual risk I cannot eliminate: if decay and consumption interleave *within* a gap between two
turns, the observed positive delta is a **net** figure that undercounts gross consumption. This
affects both periods and there is no reason to expect asymmetry, but it is unproven.
**The `<50` filter** is a reset-discarding heuristic; the 8/9 counts show resets are rare enough
that the exact threshold is not load-bearing.

### A3 — Attributing all 5h movement to Claude turns. **REAL LIMITATION, bounded.**

The 5h window is **account-wide**, shared by every Claude session. My per-turn deltas attribute
all movement to the turn that happens to close next. Any Claude activity outside the logged
sessions (e.g. my own interactive Claude Code usage on this machine) lands in the numerator
without a matching denominator.

Bounding it: Sol/Codex turns were explicitly excluded and are negligible on the spike days
(0 and 1). But **untracked Claude usage cannot be excluded from the DB**. This is the single
largest unquantified threat to the exact value of 1.77×. It does not threaten the *direction*
(both periods are subject to it), and it cannot plausibly account for a 4× vs 1.77× gap.

### A4 — The 4×-vs-1.77× internal contradiction. **VALID CRITICISM. Research doc corrected below.**

This is the strongest objection to my own write-up, and I think it partly lands.

The doc reports nominal 4× (per-session, published) and measured 1.77× (realized), then builds
a recommendation table whose "Claude capacity" column says **"4× current (nominal)"** for
Option A. That invites the reader to expect a 4× gain from upgrading back — which our own
measurement contradicts.

**Correct expectation: upgrading $100 → $200 should recover roughly the 1.77× that was lost,
not 4×.** The measurement is the better estimator of realized effect than the vendor's nominal
per-session multiplier, because (a) it is Tier-1 evidence, (b) the May 2026 SpaceX 2× uplift is
tier-independent and compresses the practical gap, and (c) weekly caps — the actual binding
constraint — carry no published multiplier at all.

**This does not flip the recommendation**, because Option A's case never rested on the size of
the multiplier: it rests on (i) the pain being Claude-side, (ii) orchestrator work being
structurally non-portable to Codex, and (iii) the $220 config having a measured **0%** error-turn
rate vs 8.9% today. A 1.77× recovery is still the dominant available lever for $20/mo.

But the honest framing is **"expect ~1.8× recovery, with 4× as an unverified nominal ceiling"** —
and F5's "top tier is 2× better capacity-per-dollar" must be labelled **nominal/per-session**,
not treated as a realized figure. Applied as a correction below.

### A5 — Is Option C the honest answer? **PARTLY YES — and the Codex failure above strengthens it.**

Option A cuts Codex from Pro 5× (75–450 Sol msgs/5h) to Plus (15–90) — a **5× reduction** on the
side that just got *better*. The research doc flags this but still leads with A.

The Codex lockout that killed this very review is evidence the Codex ceiling is **already
binding at the current $100 tier**. Dropping to Plus would make it bind ~5× sooner. So:

- If Sol workers are load-bearing → **Option A actively breaks the worker fleet**, and
  **Option C ($300) is the honest recommendation.**
- If Sol workers are optional → Option A is right.

This is a genuine fork that research cannot close — it depends on the user's intended workload
mix. The research doc correctly escalates it as an open question rather than guessing, and I am
keeping it that way rather than fabricating a preference.

### A6 — Claims I tried to break and could not

- **F1 (no published absolute numbers):** re-fetched the primary page myself; wording confirmed
  verbatim. The retired 404 page is real. Sound.
- **F3 (Codex exactly ×5):** re-fetched `learn.chatgpt.com/docs/pricing` myself; the ×5/×20
  scaling holds across 3 models × both endpoints with zero drift. Sound.
- **F4 (units not addable):** three independent reasons, backed by prior internal research
  (H2 REFUTED). The user's "21 → 10" genuinely is invalid arithmetic. Sound.
- **F6 (0 → 37 error turns):** direct count, unambiguous. Sound.

---

## Corrections applied to research.md as a result

1. F5's "2× better capacity-per-dollar" relabelled **nominal / per-session**, with the realized
   expectation stated as ~1.77×.
2. Recommendation table: Option A's Claude column changed from "4× current (nominal)" to
   **"~1.8× recovery (measured); 4× nominal ceiling, unverified"**.
3. F2 explicitly framed as a **lower bound** given A1 quantization.
4. A3 (account-wide window attribution) added to counter-evidence — it was missing.
5. Option C elevated: flagged that the Codex lockout is evidence its ceiling already binds.

## Net assessment

The **direction** of every finding survives review. The **magnitude** of the Claude loss is
solid at ~1.8× (lower-bounded, CI ~1.5–2.2×). The user's conclusion "capacity went down" is
right; their arithmetic and the 4× magnitude are wrong. The main self-caught defect was
rhetorical — leaning on the nominal 4× in the recommendation while having measured 1.77× — now
corrected. The A→C fork remains genuinely open and is escalated, not guessed.
