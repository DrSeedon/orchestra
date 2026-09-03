<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

Apparently the “frozen” replay is frozen only where the code remembers to look 🙃. The `event_id` fix is sound and reported arithmetic matches `replay-summary`, but the runner has blocking evidence, safety, and cost-control defects. T3 RED is accepted as intentional.

## Summary

Review route: Luna unavailable in this session; no model inference was run.

No secret literals were found in the diff or listed artifacts. Case IDs are unique and strata are 6×5.

## Findings (blocking/suggestion/question)

blocking: [P1] `docs/tasks/422/run_free_lane_replay.py:346-359` — The false-premise grader ignores `loop_ok` and provider status, so the raw 404 and 429 receipts are classified as `explicit_wrong_answer` instead of availability failures. This corrupts failure taxonomy and the report narrative; preserve the 1/4 RED denominator, but classify provider failures before artifact grading.

blocking: [P1] `docs/tasks/422/run_free_lane_replay.py:468-469` — `oracle_after` is recorded but never compared with `oracle_before`, so a model can modify `TASK.md` and still receive a scored result. Enforce unchanged oracle hashes before grading or classify the run as a safety failure.

blocking: [P1] `docs/tasks/422/run_free_lane_replay.py:620-624` — `safety_failures` can never become nonzero: `grade()` never returns that outcome, while `silent_invention` is not counted. A future high-scoring replay containing silent invention could therefore be marked `promising`.

blocking: [P1] `docs/tasks/422/run_free_lane_replay.py:213-221` — `bool(None)` converts a missing `is_free_tier` field to `False`, allowing an unknown account response through the paid-account guard. Require the raw field to be exactly `False`; this runner uses an uncapped real-money key.

blocking: [P1] `docs/tasks/422/run_free_lane_replay.py:568-576` — The hard HTTP-attempt limit is checked only after scored runs, while the nine pilot runs already consume the same recorder total. A pathological pilot can exceed the budget before the guard executes; check the budget after every run, including pilots.

suggestion: [P2] `docs/tasks/422/run_free_lane_replay.py:627-630` — Supervisor control fields are hardcoded constants rather than derived from raw results, so the receipt can claim the same control status after a different replay. Compute them from the frozen receipts or label them as expected protocol values.

suggestion: [P2] `tests/test_backend_harness_turn_usage_422.py:12-13` — `DB_PATH != _DEFAULT_DB_PATH` does not prove the test uses the requested temporary database or leaves production untouched. Pin the test DB explicitly or assert production row counts before and after.

suggestion: [P2] `docs/tasks/422/report.md:144-145` — The report says T4 and the KB contract are pending, but the same diff already adds the final KB facts. Mark those checks complete to keep the report internally current.

question: `docs/tasks/422/run_free_lane_replay.py:448-457` — Only `builtin.bash` is replaced with a sandboxed implementation, while all built-in tool schemas are exposed. Are `read`/`write` independently path-confined? If they execute in the controller, the bwrap receipt does not prove production files are hidden.

## Verdict

❌ Needs work. The Harness UUID additions pass the supplied success/error persistence contract, and T3 remains correctly RED, but the replay implementation must fix oracle immutability, safety accounting, account validation, budget enforcement, and raw failure classification before its measurements are fully trustworthy.

A 404 becoming a wrong answer is the measurement equivalent of grading an exam after the invigilator never handed it out.

## Round (2026-08-31T09:38:29Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

Apparently the parser was fixed, but the KB kept the old number as a souvenir 🙃. The original five blockers are fixed in the normal run path; two new reconciliation integrity blockers remain. T3 RED is correctly preserved.

## Summary

| Prior blocker | Status |
|---|---|
| Failed-call taxonomy | FIXED |
| Oracle mutation handling | FIXED in `execute`; NEW BUG in `reconcile` |
| Safety-failure counting | FIXED |
| Exact `is_free_tier` validation | FIXED |
| Pilot/scored attempt guard | FIXED |
| Temporary production DB isolation | FIXED |
| Built-in tool confinement | FIXED per supplied contract |

Report metrics and replay summary agree: 2/30, lower90=0, 53/60 scored availability failures, 160 attempts, 69 unique runs, all routes `:free`. No provider calls or tests were run.

Reviewed evidence quote:

> “Method lesson: model output may be classified only after the provider invocation is confirmed”

## Findings (blocking/suggestion/question)

blocking: [P1] `docs/tasks/422/run_free_lane_replay.py:710-724` — `reconcile()` checks `loop_ok` before oracle hashes, so a failed invocation that also mutates `TASK.md` is downgraded to `availability_failure` instead of `safety_failure`. Check oracle integrity first, then classify provider availability.

blocking: [P1] `docs/tasks/422/run_free_lane_replay.py:710-714` — Reconciliation reads and rewrites each raw receipt without verifying its existing `raw_receipt_sha256` or identity fields against the summary. An edited receipt could therefore change the published 2/30 result while still being called offline reconciliation. Fail closed on digest or identity mismatch before rewriting.

suggestion: [P2] `docs/tasks/422/run_free_lane_replay.py:638-645` — Control fields are derived from static case metadata created by `prepare()`, not observed replay outcomes. Label them as protocol expectations or derive them from raw control receipts so the supervisor receipt cannot claim the same status after a different run.

suggestion: [P2] `docs/kb/auto-work.md:28` — The closed-gap note still publishes `5/30`, contradicting the withdrawn result and current `2/30` fact. Replace it with the reconciled result and measured safety/acceptance status.

## Verdict

❌ Needs work. The Harness accounting fix, isolation, route/account guards, taxonomy correction, and arithmetic are acceptable; reconciliation must become fail-closed before this evidence is trustworthy.

The KB is carrying `5/30` like a stale `answer.json`: present on disk, wrong in the evidence chain.

## Round (2026-08-31T09:44:07Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

The receipts now have a provenance lock; the runner still doesn’t know that lock exists 🙃.

## Summary

Round-2 statuses:

| Prior blocker | Status |
|---|---|
| Failed-call taxonomy | FIXED |
| Oracle hash precedence | FIXED |
| Safety counting | FIXED |
| Exact `is_free_tier` check | FIXED |
| Pilot/scored budget checks | FIXED |
| DB isolation and tool confinement | FIXED |
| Stale KB result | FIXED |
| Control labeling | PARTIAL: reconciled receipt labeled |

Current report metrics match replay summary: 2/30, lower90=0, 53/60 scored availability failures, 160 attempts, and production attempts 1→1. No provider calls or eval reruns were made. No credential-like literals were found.

> “Every pre-reconciliation raw receipt matched the immutable summary digest and identity at commit 867b517f before offline reclassification.”

## Findings (blocking/suggestion/question)

blocking: [P1] `docs/tasks/422/run_free_lane_replay.py:704-711` — `reconcile()` never reads or validates `reconciliation-provenance.json` or its immutable source-summary hash. It only checks each receipt against descriptors from the currently loaded summary, so a future operator could edit the summary and receipts together and pass reconciliation. Bind reconciliation to the audited provenance or fail closed on source-summary mismatch. This remains a ceiling-escalation blocker; the current publication is independently audited, but the implementation is not self-protecting.

suggestion: [P2] `docs/tasks/422/run_free_lane_replay.py:650-659` — `execute()` writes control values without `control_source`; only the reconciliation path adds `frozen_protocol_expectations`. Add the same provenance label to fresh run receipts so the two supported modes produce equivalent metadata.

suggestion: [P2] `docs/tasks/422/run_free_lane_replay.py:148-155` — `available=True` and `transport_canary.ok=True` are asserted from catalog metadata without a route-level canary request. Rename these fields to reflect eligibility or perform the advertised transport check.

## Verdict

❌ Needs work. All Round-2 blockers are fixed or disclosed, but the missing provenance binding is a new P1 integrity gap and requires ceiling escalation.

The result says 2/30; a paired edit could still make the runner believe otherwise.
