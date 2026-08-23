<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Summary

Comparator arithmetic is correct, quality limitations are appropriately disclosed, no causal shares are invented, and no GPT/Kimi result is transferred to `gpt-5.6-sol`. The hidden acceptance oracle is identical across pilot arms.

The proposed pilot is not yet capable of supporting its stated mechanism claim because its decision rule omits a quantitative effect/noise threshold and fails closed only on cache/schema mismatches—not on retry or other matched-control violations.

## Findings

1. `blocking:` [research.md:222](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-scaffold-overhead/docs/tasks/378/research.md:222) — The four-run pilot has no preregistered rule distinguishing a scaffold effect from run noise. Two observations per arm provide a noise observation, but lines 235–238 permit reporting a scaffold ratio whenever all runs pass and cache/schema checks agree. No minimum effect, comparison against within-arm dispersion, or paired estimator is defined. Thus “Four runs can establish a mechanism-sized effect” is unsupported: any nonzero cost difference could be reported as the mechanism. Define the estimator and a pilot-derived/noise-relative threshold, or weaken the conclusion to “observe a candidate effect requiring confirmation.”

2. `blocking:` [research.md:214](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-scaffold-overhead/docs/tasks/378/research.md:214) — Retry equality is declared but not enforced by the verdict rule. The design says provider retries and agent retries are disabled, yet lines 235–237 invalidate only model/effort/acceptance, cache, and schema mismatches. The captured retry count could therefore be nonzero or differ between arms while the pilot still reports a scaffold ratio. Require observed `provider_retries == agent_retries == 0` for every run—or classify retries as part of the treatment and narrow the mechanism claim accordingly. Apply the same fail-closed rule to compaction and maximum-turn enforcement.

3. `suggestion:` [raw-normalized.csv:1](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-scaffold-overhead/docs/tasks/378/raw-normalized.csv:1) — The CSV does not contain every normalization field named by the report or mark each one explicitly unknown. Missing columns include provider/surface, snapshot, service tier, temperature, task repository/SHA, prompt bytes, timeout/stop budget, acceptance oracle, model-call count, tool-call count, compaction count, pricing date, and transport fields. Additionally, absent screenshot values are blank rather than explicitly classified as `unknown` or `missing`. Add columns with explicit states, or state that the CSV intentionally covers only a defined subset and point to the ledger for the remaining fields.

4. `suggestion:` [source-ledger.md:67](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-scaffold-overhead/docs/tasks/378/source-ledger.md:67) — “IRRECOVERABLE FROM THE FORWARDED MATERIAL” is stronger and more categorical than the recorded negative searches prove, even though the next sentence correctly acknowledges unindexed, deleted, private, or lost-link sources. Use “not recovered from the supplied material and documented searches” or “not identifiable from the forwarded material.” This would align with the report’s accurate limitation: “Public-source search can prove that no matching indexed artifact was found, not that no public artifact ever existed.”

## Verdict

**Needs work — 2 blocking findings.**

The numerical conclusions themselves survive review:

- Claude Code ratios and aggregates recompute correctly.
- Cline and Hermes aggregates recompute correctly.
- No Codex dollar ratio exists.
- Equal raw scores are not misrepresented as proven semantic-quality matches.
- The decomposition explicitly declines to assign causal percentages.
- The proposed Sol pilot is presented as a new matched experiment, not evidence transferred from the screenshot.

The benchmark’s fail-closed acceptance rule and complete normalization schema need correction before it can test even the narrowly stated mechanism claim.

## Round (2026-08-23T18:22:41Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Summary

All four prior findings are fixed. No regression or new blocking issue found.

## Findings

- **F1 — FIXED:** The four-run pilot is explicitly exploratory, reports paired ratios and arm spreads, and forbids claiming an established scaffold effect at `n=2`.
- **F2 — FIXED:** The validity rule now fails closed on retries, compactions, turn caps, timeouts, budgets, cache, schema, model, effort, task, and oracle mismatches.
- **F3 — FIXED:** The ledger defines the bounded CSV scope and distinguishes `unknown` from `missing_in_screenshot`; prior blank cells are explicit.
- **F4 — FIXED:** Source recovery is accurately limited to the supplied material and documented searches, while allowing for unindexed or deleted sources.
- **New findings:** None.

Evidence quote from the changed artifact: “The four-run pilot cannot validate a global “4×” policy.”

## Verdict

**APPROVED.** All blockers are closed.
