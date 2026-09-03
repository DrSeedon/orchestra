<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Summary

The #380 causal reproduction and rejection of nodeid-only subtraction are well supported. However, the recommended “smallest safe” approach omits an enforcement mechanism required by its own safety invariants, leaving a merge-admission hole.

## Findings

- blocking: `docs/tasks/386/research.md:277-310` — The recommendation relies on “the existing server-owned per-ticket acceptance command” and oracle immutability, but current contracts enforce neither oracle presence nor immutability. `acceptance.py:151-152` treats an empty command as `SKIPPED`; `merge_operations.py:987` permits `SKIPPED`; and the command executes inside the candidate worktree, whose tests, fixtures, `conftest.py`, and pytest configuration may differ from the pinned target. The regression gate also admits `SKIPPED` for no mapped tests and fully deselected files (`merge_test_gate.py:292-299,407-419`). Thus a candidate can weaken the named oracle or alter selection/configuration and still satisfy the stated five-step recommendation. The document recognizes this at lines 289-291 and requires an oracle-mutation RED control at lines 348-352, but omits the corresponding admission contract from lines 305-310 and says no change to `acceptance.py` is justified at lines 386-387. Before Phase 2 planning, make the recommendation internally consistent by explicitly including fail-closed verification that the required server-owned oracle exists and that its test/fixture/config/selection inputs match the frozen target—or narrow the safety claim and verdict accordingly.

- suggestion: `docs/tasks/386/research.md:224-270` — The timing and cache conclusions give outputs and summary values but not the exact recorded `/usr/bin/time`, load-capture, export, and pytest commands. Consequently the reported measurements cannot be replayed from this artifact, and “minimum cache key” also omits the batching partition and per-batch timeout allocation that affect the current execution contract. Record the exact commands and include batching/budget policy in the invocation identity, or label those conclusions as non-reproducible observations rather than confirmed evidence.

## Verdict

NEEDS WORK — one blocking merge-admission gap.

Review evidence quote: “A red baseline also needs a stability policy.”

## Author response after Round 1

- ACK blocking: verified `acceptance.py:151-152`, `merge_operations.py:987`, and
  `merge_test_gate.py:292-299,407-419`. The recommendation now requires a non-empty oracle pinned
  in the operation snapshot, byte-identical frozen test/fixture/helper/conftest/config/selection
  inputs, positive `PASSED` evidence, and fail-closed handling of `SKIPPED` for the special
  intentionally-RED workflow. Current acceptance alone is now explicitly labeled insufficient.
- ACK suggestion: added exact archive/load/time/pytest/path-map replay commands. The baseline cache
  identity now includes batching partition, total budget, and per-batch timeout allocation policy.

## Round (2026-08-23T23:10:14Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Round 2

## Summary

Prior blocking gap is FIXED. The revised admission contract now explicitly rejects missing, skipped, mutable, or weakened ticket-oracle evidence while retaining target-relative regression coverage and target-head pinning.

## Findings

- suggestion: `docs/tasks/386/research.md:250-288` — Replay commands cover one target→candidate pair, while the reported experiment alternated both trees twice and included a pilot. The commands also emit path lists but do not replay `select_tests()`. Consider clarifying that this is a representative replay protocol, or include the exact loop/order and mapping call used for the full table.

## Verdict

APPROVED.

Evidence quote: “This recommendation does not choose the eventual parameter/storage/API shape.”
