<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

Almost scientific—until `--resume` can turn the production DB into the lab rat. 😏

## Summary

The recorded numbers are internally correct: n=28, both MRRs, ΔMRR, paired t, and 20,000 baseline-only split-half noise all reproduce exactly. The no-change conclusion is appropriately scoped and does not claim intrinsic inferiority.

One blocking safety issue remains.

## Findings

### blocking — Reject source/candidate aliases during resume

**File:** `docs/tasks/364/bench/giga_bench.py:347-356`

`--resume` only checks that the candidate exists; it does not verify that it differs from the source. Passing the production DB as `--candidate` opens it writable, creates `bench364_progress`, and modifies production vectors. An interrupted run could leave production with mixed vector generations. Reject identical files using a same-file check before opening the candidate.

### suggestion — Validate paired inputs before calculating statistics

**File:** `docs/tasks/364/bench/giga_bench.py:418-419`

`zip(candidate, baseline_values)` silently truncates or mispairs inputs. `analyze()` does not assert equal length, query order, `(index, q, gold)` identity, or matching provenance hashes. The current JSON is aligned, but a stale or truncated arm could produce false ΔMRR and t values.

### suggestion — Pin the baseline model bytes

**Files:** `docs/tasks/364/bench/giga_bench.py:150`, `docs/tasks/364/bench/results.json:300`

The baseline records only the model name and uses a mutable cache; it does not record or verify the ONNX/model-file hash. A cache replacement could change baseline vectors while corpus, query, and harness hashes remain unchanged.

### suggestion — Soften H2’s “CONFIRMED” wording

**File:** `docs/tasks/364/research.md:19`

One fixed corpus and one observed effect support “not distinguishable here,” not a general confirmation that n=28 cannot detect effects below ~0.10 MRR. This does not change the no-change decision, but avoids overstating statistical power.

## Verdict

**CHANGES REQUESTED.** The numerical comparison and scoped conclusion pass review, but the resumable path can write directly into the source database, violating the task’s production-safety requirement.

## Round (2026-08-26T05:43:18Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

The second pass found the fixes where they were supposed to be—suspiciously efficient. 😏

## Summary

All four prior findings are fixed. Current metrics, paired identity, provenance hashes, and the scoped no-change conclusion remain correct.

## Findings

- **FIXED — blocking alias:** `samefile`/`resolve` rejection occurs before any writable candidate open; the supplied control leaves `bench364_progress` unchanged and produces no result.

- **FIXED — paired inputs:** `analyze()` enforces 28 rows, exact `(index, q, gold)` identity, matching provenance hashes, pinned baseline ONNX, and pinned Giga revision. Unequal RR lengths now fail.

- **FIXED — baseline pin:** baseline ONNX revision and SHA are validated and recorded; metrics reproduce exactly.

- **FIXED — H2 wording:** the claim is explicitly scoped to this frozen comparison.

No new conclusion-invalidating findings.

## Verdict

**APPROVED.**

Exact line from the reviewed report:

> `Transformers 4.57.0, PyTorch 2.10.0+cu128, GTX 1650, batch=16, max_length=512.`
