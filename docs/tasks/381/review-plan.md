<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Summary

The plan matches the current production seams and signatures. The four T381 tests are valid RED oracles rather than collection/setup failures, and the shared `AttributeError` text correctly exercises structural classification.

However, several stated invariants are not mechanically enforced by the frozen tests.

## Findings

suggestion: [tests/test_initial_deliveries.py:779](/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-initial-delivery-class/tests/test_initial_deliveries.py:779) — The quarantine oracle checks replay prevention only after the row has become `DELIVERY_UNKNOWN`. It never performs a matching POST while the row remains `DISPATCHING`. Therefore the plan’s requirement that both `DISPATCHING` and `DELIVERY_UNKNOWN` reject replay is not mechanically covered.

suggestion: [tests/test_initial_deliveries.py:772](/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-initial-delivery-class/tests/test_initial_deliveries.py:772) — Historical `DELIVERY_UNKNOWN` preservation is not tested. The test creates a new unknown row through the new execution path, captures its error before recovery, and never reloads it afterward. An implementation could retrospectively rewrite historical unknown rows or their envelopes without failing T381.

suggestion: [tests/test_initial_deliveries.py:677](/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-initial-delivery-class/tests/test_initial_deliveries.py:677) — The retry oracle manually seeds `FAILED_BEFORE_SUBMIT` instead of executing a real failed first attempt. Its “one prompt/provider call across retry” assertions count only the successful retry through `_RecordingManager`; they do not mechanically prove that the first attempt plus retry preserves exactly one logical prompt, pending-fact attachment, and provider call as required by plan invariant 5.

suggestion: [docs/tasks/381/plan.md:196](/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-initial-delivery-class/docs/tasks/381/plan.md:196) — The AC requires legacy #311 T2/T3 to remain green but does not include their exact executable commands or selectors. Counts alone (`10 passed`, `9 passed`) are insufficient to reproduce which subsets constitute T2 and T3.

## Verdict

**NEEDS WORK**

No blocking implementation-design defect was found, but the frozen oracle set does not mechanically cover every invariant the plan claims as definitive—especially live `DISPATCHING` replay prevention and historical unknown preservation. No files were edited.

## Author resolution before Round 2

- ACK finding 1: matching POST is now executed while a second row is still `DISPATCHING`; the test
  asserts the receipt remains `DISPATCHING` and the wake list stays empty.
- ACK finding 2: a separately seeded historical `DELIVERY_UNKNOWN` keeps its exact `error_json`
  across recovery and a matching receipt read.
- ACK finding 3: T2 now produces `FAILED_BEFORE_SUBMIT` through a real first
  `run_initial_delivery -> AgentSession.send` failure and finishes through a real healthy session;
  it counts prompt preparation, provider send, immutable log, and `user_log_id` across both attempts.
- ACK finding 4: exact executable #311 T2/T3 commands are now in the plan and ticket AC.
- Definitive RED was refrozen at `621891aa0d44425610c564ac72f4b6c0c8b72726`;
  `1315c35ad124182fc854d863e63612ad1159d16f` is excluded.
- Attempt 2 requested 2026-08-23: resume the same Sol review after these artifact changes.

## Round (2026-08-23T16:10:18Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Round 2

## Summary

All four Round 1 suggestions are fixed. The new freeze SHA and ticket commands match, T381 remains definitively RED with five behavioral assertion failures, and legacy #311 commands remain green.

Evidence line from the plan: “Failed initial insert/commit still leaves no delivery row.”

## Findings

No open findings.

- FIXED — live matching `DISPATCHING` receipt returns without waking a runner.
- FIXED — independently seeded historical `DELIVERY_UNKNOWN.error_json` remains byte-identical through recovery and receipt reads.
- FIXED — retry oracle executes a real pre-provider failure followed by a real healthy `AgentSession.send`, asserting one prompt preparation, provider call, and user log.
- FIXED — exact legacy commands are executable:
  - T2: `10 passed, 10 deselected`
  - T3: `9 passed, 91 deselected`
- VERIFIED — combined T381 command: `5 failed, 15 deselected`; failures are missing-behavior assertions, not collection/setup errors.
- VERIFIED — changes from the prior freeze are confined to T381 test functions; the test file is unchanged since `621891aa0d44425610c564ac72f4b6c0c8b72726`.

## Verdict

**APPROVED**
