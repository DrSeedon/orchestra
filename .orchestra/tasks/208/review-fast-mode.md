<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Summary

The raw arithmetic checks out: tiers were `default`/`priority`, latency and token totals reproduce from JSON, quality is 5/12 versus 4/12, and provider-credit attribution is correctly marked `UNIDENTIFIED`.

However, the “≈99% disabled” controller policy materially outruns a single-model, single-fixture experiment and has no measured 99% denominator.

Proof of reading: “Fast оказался на 3.3 % дешевле в локальных `$` из-за небольших различий cache/output, не из-за tier pricing.”

## Findings

- blocking: [fast-mode.md:182](/home/kesha/orchestra/worktrees/home-kesha-orchestra/bench-effort/docs/tasks/208/fast-mode.md:182) — The recommendation to disable Fast for “≈99%” of turns is unsupported. The experiment measured one schema-constrained, tool-free fixture on one model/effort, while the report explicitly says tool-using chains were not tested. It neither measures the share of production traffic that is latency-critical nor validates the whitelist criteria. The evidence supports “default off pending workload-specific measurement,” but not the 99% figure or this production-wide policy. Remove the percentage and frame the whitelist as a provisional policy assumption, separately from the empirical result.

- suggestion: [fast-mode.md:73](/home/kesha/orchestra/worktrees/home-kesha-orchestra/bench-effort/docs/tasks/208/fast-mode.md:73) — “CONFIRMED” overstates the cold-wall evidence. The percentile bootstrap over six ratios gives 1.054–1.349, but only 5/6 pairs favor Fast; an exact paired sign test gives two-sided \(p=0.219\). Warm wall is stronger at 6/6 (\(p=0.03125\)). Report the bootstrap as descriptive and distinguish “observed median acceleration” from statistically established directional evidence.

- suggestion: [fast-mode.md:95](/home/kesha/orchestra/worktrees/home-kesha-orchestra/bench-effort/docs/tasks/208/fast-mode.md:95) — Overlapping separate Wilson intervals are not a valid paired comparison. The correct paired table is already present: Standard-only 2, Fast-only 1, yielding exact McNemar \(p=1.0\). The conclusion remains unchanged, but it should be justified by the paired test rather than interval overlap.

- suggestion: [fast-mode.md:193](/home/kesha/orchestra/worktrees/home-kesha-orchestra/bench-effort/docs/tasks/208/fast-mode.md:193) — “One extra exact FAIL erased successful throughput” treats 5 versus 4 stochastic passes as a stable denominator. The computed sample ratios—50.71 versus 50.34 seconds/PASS—are arithmetically correct, but N=12 and McNemar \(p=1.0\) do not establish equal or lower quality-adjusted throughput. Label this descriptive only; it cannot carry the controller verdict.

## Verdict

Needs work: the measured tier application, raw totals, cost provenance boundaries, and quota-confounding conclusion are sound, but the 99%-off production decision must be narrowed to match the evidence.

## Round (2026-08-17T08:08:54Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Summary

All four prior findings are fixed. Direct JSON recomputation confirms the reported latency, quality, token, cost, tier, and quota figures.

Exact changed-artifact quote: “Условия whitelist выше — проверяемая гипотеза политики, не валидированные этим стендом правила.”

## Findings

- blocking — FIXED: The unsupported empirical “≈99%” claim is removed. Any 99%-off rollout is now explicitly labeled a provisional policy prior, while the evidence supports only default-off pending workload-specific measurement.

- suggestion — FIXED: Latency now includes exact paired sign tests: cold wall 5/6, \(p=0.21875\); warm wall 6/6, \(p=0.03125\). Bootstrap intervals are correctly labeled descriptive.

- suggestion — FIXED: Quality now uses the paired discordance table and exact McNemar \(p=1.0\), rather than inferring equivalence from overlapping Wilson intervals.

- suggestion — FIXED: Wall-seconds/PASS is explicitly descriptive and excluded as a policy basis.

- NEW BUG: none.

## Verdict

Completed. No blocking or suggestion findings remain; the report is calibrated to the N=6/N=12 evidence and clearly separates measurements from provisional controller policy.
