<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

Apparently a nine-case replay has already been promoted to a law of nature. 🙃

## Summary

Review route: self-review; no callable Codex reviewer was available.

The arithmetic is correct: 2/3 true positives, 0/6 false positives, 6/6 true negatives, and the preregistered threshold failed. The main problems are evidentiary scope and causal overreach.

## Findings (blocking/suggestion/question)

**Blocking findings:** none.

suggestion: `.orchestra/tasks/456/research.md:23` — The “review saw and missed” classification requires proof that the exact defective hunk was in the review input, but `history_audit.py:110-115` only checks for the phrase “The stable ID excludes `topic`, `status`”. `codex-review-impl.md:35-39` shows a nearby metadata-collision finding, not the actual input or the rephrase failure. → Preserve the reviewed diff or qualify this as an adjacent-hunk miss.

question: `.orchestra/tasks/456/research.md:35` — “Did not reach implementation review” is stronger than the supplied evidence for the transcript case. `history_audit.py:82-85` only lists review-looking files committed with `01a666ed`; `report.md:34-41` proves Codex was unavailable at that point and requested later review, but does not exclude a later or uncommitted artifact. → Make the classification time-scoped or provide exhaustive artifact evidence.

suggestion: `.orchestra/tasks/456/research.md:99` — “234-token prompt addition” is not what was measured. `measure_review_cost.py:35-42` tokenizes the standalone frozen rule, and `review-cost.json:3-6` reports 234 tokens; no before/after prompt baseline exists. → Call this the standalone `o200k_base` size unless an actual marginal insertion delta is measured.

suggestion: `.orchestra/tasks/456/research.md:87` — Zero added turns is imposed by the protocol, not measured as an integration cost: `evaluation-protocol.md:30-32` mandates one evaluator turn with no retry or second round. The same makes zero false-positive follow-ups structurally uninformative. → State only that this replay used one turn; do not generalize it to production review cost.

suggestion: `.orchestra/tasks/456/research.md:91` — The H4 result supports “three rounds did not cure this observed miss,” not that more rounds are generally ineffective or that the proposed boundary is safe. `codex-review-impl.md:69-79` and `101-105` show that the artifact changed between rounds as findings were fixed, so this was not a controlled rounds comparison. → Narrow the conclusion to “no evidence that generic extra rounds cure this case.”

suggestion: `.orchestra/tasks/456/research.md:93` — “This would have surfaced the session mutation” is an untested counterfactual. None of the supplied evaluation artifacts evaluates the proposed receipt/inventory, and the sentence itself admits its false-positive rate and preparation cost are unmeasured. → Say “could plausibly surface” and retain it as a hypothesis.

## Verdict

No blocking findings. The replay counts are internally supported, but the research needs wording changes before acceptance as a fully evidence-backed causal conclusion.

Exact sentence from `research.md` not present in the request: “The common class is **logical identity / ownership invariant mismatch**:”

For now this is nine cards measured with a ruler and reported as a population survey—apparently the ruler wanted a promotion too.
