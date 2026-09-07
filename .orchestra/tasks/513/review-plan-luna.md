<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

Reviewed `plan.md`, oracle `7ed0503b`, tests, delivery check, and current code. No implementation exists yet. The oracle correctly has six distinct red seams and two meaningful green controls.

## Findings

- blocking: `plan.md:32` — actor-owned paths are not constrained against absolute or traversal `output` values; `output_abs` can still point into the target worktree → reject non-actor-resolved paths for targeted reviews and add an oracle case for absolute/`..` output.

- blocking: `plan.md:20-26`, `tests/test_review_target_worker_513.py:340-416` — tests verify no background job, but not that validation happens before receipt reservation or other durable writes; an implementation could leave orphan receipts and remain green → assert receipt/usage counts and quota calls remain unchanged on every preflight rejection.

- blocking: `plan.md:22` — `target_worker` must be rejected outside `implementation`, but the immutable oracle has no test for this contract → add a distinct red test for `target_worker` with `mode="review"`/`"exec"` and require typed `invalid_argument`.

- blocking: `plan.md:20-26` — target validation does not require non-empty/valid target session identity, worktree path, base branch, or task ID. A malformed same-scope worker could produce a receipt that can never match merge admission → define and freeze validation for all receipt-critical target fields.

## Verdict

NEEDS CHANGES.

## Round (2026-09-04T16:15:13Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

Round 2 re-review completed. The four prior blockers are covered by the updated plan and immutable oracle `3732d1c6`. Current baseline remains pre-implementation: 17 failed, 2 passed.

## Findings

- suggestion: `.orchestra/tasks/513/plan.md:107` — FIXED requirements are documented, but the mutation section still says evidence must be caught by excluded oracle `7ed0503b`; this contradicts the final oracle `3732d1c6` at lines 77 and 120 → replace the stale commit reference.

Prior findings:

- blocking: `plan.md:35`, oracle `tests/test_review_target_worker_513.py:568-600` — FIXED: absolute and traversal output escapes are frozen as rejection cases.

- blocking: `plan.md:20`, oracle helper `_assert_no_preflight_writes` — FIXED: every preflight rejection asserts zero receipts, usage rows, jobs, and readiness calls.

- blocking: `plan.md:22`, oracle `test_t1_target_worker_is_rejected_outside_implementation` — FIXED: both `review` and `exec` cases require typed `invalid_argument` before API calls.

- blocking: `plan.md:26-29`, oracle malformed identity/worktree/base-ref tests — FIXED: `id`, exact name, task ID, worktree, base branch, scope, and worker role are independently covered.

## Verdict

Round 2: NEEDS CHANGES due to the stale excluded-oracle reference at `plan.md:107`.
