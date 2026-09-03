## Summary

No blocking findings. The PASS, timing, token, and Luna-cost arithmetic checks out; the report also correctly limits what 0 tool failures proves. Official descriptions and prices match the cited OpenAI pages.

Exact sentence confirming artifact review: “Это не расширяет допуск Spark.”

## Findings

suggestion: `docs/tasks/286/report.md:7` — The claim that each pair produced a byte-identical production diff is not auditable from `data.json`. The JSON records changed paths and external `diff.patch` paths, but contains neither the patches nor their hashes; the abbreviated hashes at lines 80–81 appear only in the report. Store the full SHA-256 for every run in `data.json` before calling this tier-1 confirmed evidence.

suggestion: `docs/tasks/286/report.md:59` — The evidence bundle does not substantiate that the parent roots were actually blocked. `prereg.md` specifies `InaccessiblePaths`, while `data.json` records only absent Git alternates, future-object unreachability, and empty leakage-marker results. “Recorded commands contain no leakage markers” cannot prove enforcement or exclude unrecorded reads. Either add the applied isolation configuration/result to the JSON or phrase root blocking as a harness assertion. The later global-isolation limitation is otherwise appropriately candid.

suggestion: `docs/tasks/286/report.md:124` — “примерно 25 таких benchmark batch” is not reproducible from the allowed evidence. The reused rows show a total Spark pool delta of 3 percentage points for the batch; a naïve linear extrapolation would be roughly 33 batches, with substantial uncertainty from integer rounding. Preserve the original derivation in `data.json`, or remove the numerical estimate.

suggestion: `docs/tasks/286/report.md:142` — The first routing rule extends beyond the measured population. The new fixtures establish two one-file Python tasks, not arbitrary ≤2-file tasks; the prior #222 code cell changed both production and test files, and “initial context ≤100K” is not recorded as a metric for the new runs. Narrow the route to the observed one-file class, or explicitly label the two-file and 100K boundaries as hypotheses. This matters because the report correctly acknowledges N=2 and reused #222 elsewhere.

suggestion: `docs/tasks/286/report.md:157` — “Новые четыре хода ошибок не дали” is broader than the frozen oracles establish. All four runs satisfy the preregistered PASS definition, but those narrow tests cannot establish absence of unrelated semantic errors. Prefer “все четыре хода прошли frozen oracle и scope checks.” The following 0/0 tool-failure interpretation is correct.

## Verdict

No blockers; approve as Phase 1 research after the evidence-labeling improvements above. All reported wall, cold-start, tool, token, sensitivity-cost, and percentage calculations reproduce from `data.json`. The public claims are current: Spark is a 128K text-only real-time coding research preview with non-final rates, while Luna is positioned for cost-sensitive high-volume workloads at $0.20/$0.02/$1.20 per MTok ([Spark announcement](https://openai.com/index/introducing-gpt-5-3-codex-spark/), [Luna model page](https://developers.openai.com/api/docs/models/gpt-5.6-luna), [Codex rate card](https://help.openai.com/en/articles/20001106)).

## Round (2026-08-16T09:05:09Z)

## Re-review status

1. Pairwise diff evidence — FIXED. Embedded patches hash correctly, and both task pairs are byte-identical.
2. Isolation wording — STILL BROKEN. The protocol now accurately says no enforcement probe existed, but limitation 6 still says “Доказаны … закрытые parent roots.” Replace with “harness configured closed parent roots”; closure was not proven.
3. Unsupported 25-batch estimate — FIXED.
4. Routing overgeneralization — FIXED. Confirmed evidence is narrowed to one writable Python file; two-file/near-100K routing is explicitly lower-confidence.
5. Error-free wording — FIXED. It now claims only frozen-oracle and scope-check success.

## New findings

None. No new blocking contradiction was introduced. The embedded `data.json` SHA-256 in `report.md` also matches the current file.

## Verdict

APPROVED; no blockers. One residual isolation wording suggestion remains above.

Exact artifact sentence: “Узкие tests не исключают unrelated semantic errors.”
