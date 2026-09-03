<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

Apparently `NULL` has been promoted to a complete lifecycle state 😏

## Summary

The switch-guard conclusion is supported: the non-force guard precedes `checkout --detach` and `reset --hard`. The `NULL + done` terminal state is also supported, but the proposed adoption gate and binding order can misattribute or reopen tasks. The report also conflates raw rows (`104`) with filtered worktrees (`11`).

Review route: Luna was requested, but no `codex_review` capability is available here; this is the scoped local review.

## Findings

1. `blocking: .orchestra/tasks/465/research.md:90-92 — the adoption predicate is too broad → require unmerged content and reject terminal target tasks.`

“Unbound adhoc branch with committed content” includes the documented `content_verified` row, not only blocked work. More importantly, `app/tm.py:814-820` changes any unowned task to `in_progress` regardless of its previous status, so an explicit primary can reopen a `done` task from the normal `NULL + done` state (`app/tm.py:896-901`, `tests/test_task_tracker_integration.py:1299-1319`).

2. `blocking: .orchestra/tasks/465/research.md:90-98 — binding is not atomic with later merge validation → finish all rejecting preflight checks before binding, or define an explicit recoverable checkpoint.`

`bind_task_to_session` commits the session/task ownership at `app/tm.py:777-847`, while the proposed flow still allows later branch, HEAD, ref, or merge validation to reject. The report’s own candidate-ref risk means an invalid adhoc commit could leave the wrong task permanently bound and `in_progress` even though no merge occurred.

3. `suggestion: .orchestra/tasks/465/research.md:41-75 — “raw predicate count = 11” is incorrect → distinguish raw rows from deduplicated qualifying worktrees.`

The report prints `snapshot_adhoc_unbound_rows=104`; `11` is the later `worktrees_with_commits_non_archived` count. Therefore `10` is a subset of the filtered 11, not of the raw predicate result. State the deduplication key and use the correct denominator in the Phase 2 oracle.

4. `suggestion: .orchestra/tasks/465/research.md:16-17, 93 — evaluate H3 as a safety alternative, not only as a two-call cost.`

A guarded bind-only adoption path followed by the unchanged merge flow preserves `next_task_id` semantics and avoids putting a new DB binding mutation inside merge admission. It is safer only if adoption independently verifies branch/HEAD agreement, unmerged content, and target-task eligibility; calling the existing binder without those checks is insufficient.

## Verdict

Needs work: 2 blocking findings and 2 suggestions. H2 and F4 are substantively correct, but Phase 2 should not proceed until adoption eligibility and binding failure semantics are made explicit.

Otherwise the deadlock just puts on a “recovery” badge and keeps blocking the doorway.

## Round (2026-09-03T11:46:15Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

Apparently the deadlock got a better predicate and lost its favorite loophole 😏

## Summary

Prior blocker 1: **FIXED**. Promotion now requires `needs_switch=False`, exact branch/HEAD agreement, positive unmerged content, and a `new` unowned unreserved target; normal `NULL + done` is excluded.

Prior blocker 2: **FIXED**. Primary binding was removed from `merge_worker`; promotion is a separate checkpoint, while the destructive switch guard and merge semantics remain unchanged.

No new blocking flaw found. The Git/SQLite partial-failure case is explicitly identified as a mandatory Phase 2 rollback/quarantine and oracle requirement, appropriate for this Phase 1 architecture review.

## Findings (blocking/suggestion/question)

No blocking findings. The updated design closes both prior blockers without weakening the existing detach/reset guard or reopening `done` tasks.

## Verdict

**APPROVED** — final prose round passes. Phase 2 must enforce the stated Git/DB failure oracle before implementation.

Exact sentence from the updated research:

> “H3 is the selected design because it makes attribution a completed lifecycle transition before merge while preserving the merge safety contract.”

The deadlock has not been cured yet, but at least it no longer gets to choose its own diagnosis.
