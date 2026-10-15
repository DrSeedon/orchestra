# V-865 blind scoring rubric (frozen before runs)

## What the assessor receives

For each case: the exact evidence snapshot and question from `manifest.md`, plus two answers marked X and Y. The assessor does not receive A/B labels, randomized order, candidate-rule text, condition mapping, or the hypothesis about which arm should win. Score each answer independently before comparing it. Use only the supplied evidence and this rubric.

## Case score

Assign `correct=1` only if the answer gets the requested exact arithmetic right or, for inference cases, gives the strongest conclusion justified by the evidence while not overstating causation, population generality, or certainty. Assign `correct=0` for a material arithmetic/factual error, unsupported causal/generalized/significance claim, or failure to state that a decision-relevant result is unresolved. Minor phrasing differences do not matter.

For deterministic controls C10–C12, the supplied finite observations are the entire target: score exact calculation/reporting. Do not demand a confidence interval, significance test, extra sample, or abstention. A correct description of an exact finite-set count is not evidence about an unobserved population.

For every answer, report `overclaim` (unsupported inferential strength), `unnecessary_inference` (statistical uncertainty/test demanded for a fixed exact control), and one short evidence-based rationale. Mark these only when present; an answer can be correct and still have unnecessary inference.

## Blind paired outcome

Per case compare X and Y after scoring:

- `X_only`: X correct, Y incorrect.
- `Y_only`: Y correct, X incorrect.
- `tie_both_correct` or `tie_both_wrong` otherwise.

After unblinding, `B_win` means B correct and A incorrect; `B_loss` means A correct and B incorrect. Primary test is a one-sided exact McNemar/sign test on discordant pairs only. The precommitted screening pass is at least 5 B wins and zero B losses (5/5 gives exact one-sided p=0.03125) and no new B-only error on deterministic controls C10–C12. This is a large-effect screening rule, not evidence that a smaller effect is absent. No other metric can replace the primary outcome after results are seen.

## Cost and validity fields

The assessor must not score cost, verbosity, or stylistic preference as correctness. Record provider-reported `cost_usd`/API-equivalent, tokens, runtime, and completion status from run artifacts separately. A missing, timed-out, malformed, or truncated answer is `correct=0` with an explicit reason. If the blind assessor itself cannot apply the rubric, record `inconclusive`; do not silently relabel it.
