<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

Nothing says “safe lifecycle change” like quarantining a worker with the flag that auto-switches it. 😏 The frozen T1/T2 oracles are valid, but the plan is not approvable yet.

## Summary

- T1 is a valid intentional GREEN control: it checks `task_id=""`, `needs_switch=1`, task `done`, and owner `NULL`.
- Exact T2 command produces 8 assertion failures, with no collection/import failure.
- #103 guard passes.
- Three blocking lifecycle/data-integrity issues remain.

## Findings

### blocking: `needs_switch=True` is not a quarantine state

**Location:** [plan.md](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-merge-deadlock/.orchestra/tasks/465/plan.md:62)

The existing manager treats `needs_switch=True` as an instruction to auto-switch before the next delivery ([manager.py](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-merge-deadlock/app/manager.py:972)). After an unknown or partial promotion result, the next message can force-switch away from `task-N/worker` and persist `task_id=""`, leaving the task owner and session binding inconsistent. The plan needs a real durable quarantine state or corresponding delivery/merge guards, and must include `app/manager.py` in scope.

### blocking: promotion eligibility is not an atomic CAS

**Location:** [plan.md](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-merge-deadlock/.orchestra/tasks/465/plan.md:46)

The proposed helper only pre-reads `status='new'`, owner `NULL`, and no reservation. Existing `api_update_task_if_current` rechecks identity/revision, but reservations do not increment `sync_revision` ([tm.py](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-merge-deadlock/app/tm.py:934)), so a reservation can appear after eligibility and still be accepted. The final task claim must atomically enforce status, owner, reservation, identity, and revision; add an interleaving test.

### blocking: shadow-mode projection debt can be reported as success

**Location:** [plan.md](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-merge-deadlock/.orchestra/tasks/465/plan.md:65)

In shadow mode, `api_update_task_if_current` updates legacy first and returns legacy’s `ok=True` together with `projection_debt` when the canonical update rejects or raises ([tm.py](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-merge-deadlock/app/tm.py:3024), [tm.py](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-merge-deadlock/app/tm.py:2048)). A route checking only `ok` and `canonical_applied` could clear quarantine after only one store changed. The plan must explicitly classify `candidate_write_failed` and candidate rejection debt as unknown/partial, with a real shadow-mode oracle.

### suggestion: prove force rejection occurs before Git access

**Location:** [test_task_tracker_integration.py](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-merge-deadlock/tests/test_task_tracker_integration.py:1087)

The force-combination test checks final branch/HEAD state but does not detect Git calls that happened and were later reversed. Add a Git seam/call sentinel so the “before Git” contract is actually enforced.

### suggestion: cover the promotion reporting contract

**Location:** [plan.md](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-merge-deadlock/.orchestra/tasks/465/plan.md:9)

The plan requires `previous_branch`, `commits_ahead`, and `reason`, especially for the 1100+ commit histories, but the success oracle asserts only state, branch, and HEAD. Add assertions for the operator-facing metadata.

## Verdict

**NOT APPROVED.** T1 and the RED baseline are sound, but the quarantine flag and task-claim ordering can create a lifecycle wedge or cross-store ownership corruption. Otherwise the quarantine is just a “do not enter” sign on an automatic door.

## Round (2026-09-03T12:16:24Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

The plan now remembers that a quarantine flag needs an actual bouncer. 😏 All prior findings are addressed; the exact T2 baseline still fails with 11 assertion failures, T1 passes, and the #103 guard passes.

## Summary

The updated plan and oracle at `6ce2570f` are consistent with the requested fixes. No new blocking contradiction found.

## Findings

- `fixed:` Quarantine now distinguishes `task_id != "" && needs_switch=True`; delivery attempts are tested before Git access.
- `fixed:` Final task claiming now repeats status, owner, reservation, identity, and revision checks transactionally; reservation interleaving is covered.
- `fixed:` Shadow exceptions, rejection, and projection debt are classified as partial/unknown regardless of top-level `ok`.
- `fixed:` Force/promotion rejection has a Git sentinel.
- `fixed:` Promotion response metadata includes `previous_branch`, `commits_ahead`, and `reason`.
- `new findings:` none.

## Verdict

**APPROVED.** The re-review closes all prior findings, and the RED command is a legitimate pre-implementation baseline with no collection/import failure. The updated plan states: “A read-only preflight may fail early for UX, but it is not authorization; the transactional claim repeats every eligibility predicate at the mutation point.”

The guard is finally a guard, not a sticky note on the automatic door.
