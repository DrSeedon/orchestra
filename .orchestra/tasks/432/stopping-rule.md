# Pre-registered stopping rule — generation `g3-resumable-20260905`

Frozen 2026-09-05 ~09:05 UTC, **before any main pair was complete**.
State at freeze: 17 slots COMPLETED, 1 STARTED, 82 NOT_STARTED. Of the main phase exactly
one slot was done (`main-364-r1-B_scout`) and **zero triads**, so no A-vs-B comparison
existed yet in any form. Codex 7d pool at freeze: **70%**.

## Why the frozen design cannot finish

The 100-slot design was budgeted in slots, not in pool. Measured cost per slot:

| window | Codex 7d pool | slots completed | note |
|---|---|---|---|
| 06:37 UTC | 51% | — | last foreign Sol turn was 06:26 at pool 50% |
| 08:53 UTC | 69% | 14 (idx 2..15) | only 2.5M foreign Luna tokens in between |

**18 points / 14 slots = ~1.29 pool points per slot.** Attribution is clean because the
only other Codex consumers in that window were three Luna turns totalling 2.5M tokens
against this experiment's ~40M (`turn_usage`, runtime='codex').

83 slots remain × 1.29 ≈ **108 points needed; the window holds 30** (100 − 70), and the
window does not reset until **2026-09-11 10:53 UTC**. The design cannot complete, and an
unguarded run would spend the entire fleet's Codex pool for six days and still stop
somewhere in the middle of the main phase.

## The rule

1. **Ceiling.** `run_all` reads the live Codex 7d pool before starting each slot and stops
   without starting it once utilisation ≥ **85%**. 85 leaves headroom under the project
   rule "держать ≥5% пула Codex под Luna-исполнителей закрытых тикетов" and under the
   ≥90% "Sol не брать" line, so this experiment does not strand other projects.
2. **Fail-closed.** An unreadable quota stops the run (`quota_unreadable`). An unreadable
   quota is empty output, and empty output is never read as headroom.
3. **Truncation is tail-only.** Slots execute in the order frozen at `init_generation`,
   which was fixed before any outcome was known. Stopping removes a suffix of that order.
   No slot is reordered, skipped, or selected on its result.
4. **Only complete triads enter the paired analysis.** A main pair requires `A`,
   `B_scout` and `B_main` all COMPLETED for the same task and repetition. A triad cut by
   the ceiling is dropped whole; a partial triad is never analysed.
5. **`inconclusive` is not a result.** A slot with `provider_started_at` and no completion
   is retried whole (existing `reconcile_generation` contract). It is neither success nor
   model failure.
6. **The denominator is reported as run, not as planned.** The report states the number of
   complete pairs actually measured and the tasks they came from, next to the planned 24.
   Truncation lowers n and widens the interval; it does not change the estimator.

## What this rule can and cannot deliver

Already banked, independent of the ceiling: the **A/A self-noise** of the cost metric from
12 completed identical-repeat slots (6 tasks × 2) — median relative difference **19.1%**,
mean 25.9%, max 53.7%, with **1 of 6** identical repeats flipping outcome.

At ~1.29 points/slot, 85% − 70% = 15 points buys **~11 slots ≈ 3–4 complete triads**. With
a 19% noise floor and n≈4 clusters the interval will be wide, and "разница меньше шума"
is an expected and legitimate outcome under rule 6. Raising the ceiling buys n at the cost
of the shared pool; that trade is the owner's to make, not this run's.
