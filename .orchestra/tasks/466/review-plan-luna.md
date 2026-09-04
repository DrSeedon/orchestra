<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Attempt journal

- Round 1 receipt: `review-receipt:f1b2ae09-6f3d-48d7-9d9f-4dee1d933e47`; completed with six blocking findings, one question and one suggestion.
- Resolution before Round 2: all eight findings accepted; plan and oracles changed; old impossible/incomplete oracle commits are marked excluded in `plan.md`; corrected T1 commit `032282db`, final T2 commit `b0557309`.
- Round 2 started as resume of this review thread; prose ceiling will be exhausted by its result.
- Round 2 result: three new blocking oracle gaps and two suggestions; negative verdict applies to the `b0557309` snapshot below.
- Post-ceiling owner resolution: the orchestrator prohibited a third model round and directed self-closure. Final RED oracle `fd9fc34d` adds separate seams for adoption/idempotence/exclusion, explicit-switch failure, strict-handoff failure, CAS cancellation, post-`as_of` exclusion and identical-retry/same-snapshot reopen. Prior RED snapshots `650f730f`, `7c549251`, `032282db`, `b0557309` are excluded forever.
- No reviewer verdict exists for `fd9fc34d`; the final plan gate belongs to the orchestrator. The full Round-2 dissent remains below unchanged.

Apparently the RED oracle brought its own typo to the gate. 🧨

## Summary

Do not approve Phase 3 yet. The five fields are defensible references, not duplicate aggregates, and the newest-review rule is compatible with #462 in principle. However, the frozen oracle contains an impossible assertion, while admission enforcement, replay identity, cancellation, and lifecycle atomicity have blocking gaps.

## Findings

### blocking — Fix the impossible stable-ID assertion

`test_run_receipt_466.py:359` asserts:

> `assert trace["run"]["task_stable_id"].endswith("646646646646")`

But the inserted value at line 297 ends with `466466466466`. Plan line 110 requires the trace to return the run’s identity, so a correct implementation cannot satisfy this assertion without corrupting or transforming the stored identifier.

### blocking — Test the actual T1 enforcement points

The plan requires:

> “In `app.merge_operations`, map `author_outcome_missing` to typed error `REVIEW_AUTHOR_OUTCOME_MISSING` ... Apply the same mapping at initial admission and execution-time activation revalidation.”

But the T1 oracle only executes:

> `blocked = _decision()`

It never calls merge admission or execution revalidation, and it has no typed `unavailable` case. The named RED command can therefore pass while both enforcement mappings remain missing.

### blocking — Revalidate already-admitted reviews after T1 rollout

The plan says:

> “T1 closes the 0/N author outcome bypass.”

An operation accepted under #462 may already contain a pinned `review_coverage.status == "satisfied"` for a `reviewed` receipt whose `author_outcome` is still `unknown`. The current execution path only revalidates missing or `not_active` pinned coverage, so such a pending operation can execute after T1 is deployed. The plan needs an unconditional current decision or a versioned admission check immediately before Git execution.

### blocking — Make run identity support reopen/reassignment

The plan says:

> “A reassigned/reopened task may have several non-overlapping run rows”

but also says:

> “The receipt id is deterministic from the NUL-separated `(scope, task_stable_id, session_id, task_snapshot_ref)`”

Reopening the same task on the same session with the same canonical snapshot produces the same ID as the previous completed run, so replay returns the old row instead of creating a new interval. The identity needs a distinct assignment epoch/event key while preserving replay idempotency.

### blocking — Add a real task-cancellation close owner

The plan requires:

> “`app.tm.release_session_task_binding` / archive or cancel → `status=interrupted`”

`app.tm.update_task` and `api_update_task` can commit `status='cancelled'`, but only session archiving invokes `release_session_task_binding`. A cancelled task can therefore retain an open `task_run` with `completed_at=NULL`, blocking later runs through the planned uniqueness guard.

### blocking — Make every assignment/run-open transition atomic

The plan requires:

> “All forward assignment writers must abort their binding if the run insert fails.”

The taskless route persists the switched branch before calling `bind_task_to_session`; finalization updates the next task in a separate transaction before the later lifecycle transaction. If run creation then fails, the session/task/branch state can commit without a matching `task_run`. The plan needs explicit compensation or one transaction boundary for each of these paths.

### question — Define trace behavior for open runs

The plan specifies:

> “`completed_at=NULL while open`”

and derives usage:

> “from `turn_usage` within `(session_id, scope, task_id, requested_at..completed_at)`”

An open run has no upper bound. The plan must state whether readers use “now”, return a live snapshot, or report an explicit gap; otherwise an ordinary `completed_at <= NULL` filter yields an empty trace.

### suggestion — Strengthen the no-duplicate schema oracle

The plan requires:

> “schema contains exactly the five named new reference fields and no forbidden aggregate copies”

The oracle only checks a hand-written set:

> `forbidden_copies = {`

and:

> `assert not (forbidden_copies & columns), (`

An unlisted duplicate such as `task_title`, `turns`, or `dollars` would pass. Compare the post-migration schema against the pre-migration schema plus exactly the five approved columns.

## Verdict

❌ Phase 3 approval is not recommended. Fix the impossible oracle first, then close the admission/replay/lifecycle gaps and strengthen the missing ACs. The plan’s rehearsal requirement is the right bar: “`init_db()` twice must produce the same five fields/indexes and preserve all existing receipts byte-for-field.”

Right now this is a handoff where the branch changes, the receipt doesn’t, and everyone still calls the worker successfully delivered.

## Round (2026-09-03T13:26:57Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

Round 2 is much cleaner: the oracle stopped lying, but several lifecycle doors still have no alarm. 🚪

## Summary

All eight Round-1 design findings are fixed in the current plan/oracles. No edits were made. `git diff` showed only the untracked plan file; the current oracle contents were reviewed directly.

## Prior finding statuses

1. **FIXED — impossible stable-ID assertion.** The oracle now requires exact identity:

   > `assert trace["run"]["task_stable_id"] == (`

   followed by the exact UUID at [test_run_receipt_466.py:573](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/run-receipt/.orchestra/tasks/466/test_run_receipt_466.py:573).

2. **FIXED — admission/execution T1 coverage and unavailable control.** The oracle now includes:

   > `async def test_t1_merge_admission_returns_actionable_author_outcome_error(`

   and:

   > `unavailable.update(`

   The admission and execution paths are both represented, and unavailable remains non-authoritative.

3. **FIXED — pinned satisfied reviews are revalidated.** The plan now states:

   > `Execution revalidation is unconditional for every active-policy production decision, including an already-pinned status=satisfied.`

4. **FIXED in design — reopen-safe identity.** The plan now specifies:

   > `A new accepted assignment gets a random task-run:<uuid4> receipt id.`

   and explicitly distinguishes retries from later reassignment.

5. **FIXED in design — cancellation owners.** Both APIs are now named:

   > `app.tm.api_update_task(status='cancelled') and app.tm.api_update_task_if_current(status='cancelled')`

6. **FIXED in design — atomicity/compensation rules.** The plan explicitly covers taskless binding, explicit switch, and strict handoff, including:

   > `explicit switch: receipt failure must raise through the existing task-assignment rollback path, restoring branch/session/task state;`

7. **FIXED — open-run `as_of`.** The plan defines `effective_end=as_of`, and the oracle checks:

   > `assert live["run"]["effective_end"] == "2026-09-03T00:30:00+00:00"`

8. **FIXED — exact schema delta.** The oracle now asserts:

   > `assert columns == BASE_REVIEW_RECEIPT_COLUMNS | APPROVED_TASK_RUN_COLUMNS, (`

## New findings

### blocking — Adoption oracle does not prove incomplete evidence or idempotence

The plan requires:

> `This row means “observation began here”, not “the task was accepted here”; the trace returns an acceptance_before_receipt gap.`

The test only checks `task_source`, empty snapshot/prompt fields, and `status='requested'`:

> `assert run["task_source"] == "legacy_inflight"`  
> `assert run["task_snapshot_ref"] == ""`  
> `assert run["prompt_template_start"] == ""`

It never checks the `acceptance_before_receipt` gap, validates that `requested_at` is the adoption time, calls `db.init_db()` twice after adoption, or proves completed historical tasks are not adopted. A bad implementation could invent an acceptance boundary or create duplicate adoption rows while passing the named RED command.

### blocking — Atomicity coverage only exercises taskless binding

The plan separately requires explicit-switch and strict-handoff behavior:

> `strict next-task finalization: the run insert is part of the legacy task update stage.`

The lifecycle oracle injects failure only into:

> `def test_t2_run_insert_failure_aborts_taskless_binding(tmp_path, monkeypatch):`

There is no failure test for explicit branch switching or next-task finalization. Either path can therefore omit rollback/quarantine or incorrectly claim success without a run row while the frozen T2 command remains green.

### blocking — Only one of two cancellation owners is tested

The plan names both cancellation entry points, but the oracle invokes only:

> `result = tm.api_update_task("466", status="cancelled", project="project")`

There is no `api_update_task_if_current(status="cancelled")` case. A regression in that second owner could leave the task-run open and still pass the current T2 oracle.

### suggestion — Prove that `as_of` excludes later owner rows

The plan says the live trace:

> `derives a live snapshot through that boundary.`

The fixture has owner rows only before `00:30`; it never adds a turn, log, or review after the supplied `as_of`. The test proves the reported boundary, but not that later data is excluded.

### suggestion — Add explicit retry and same-snapshot reopen cases

The plan promises:

> `Retry idempotency comes from the partial unique open-run indexes ... and a later reassignment after the previous row is terminal gets a new id`

The oracle opens one run once and tests a handoff to a different task. It does not retry identical open parameters or reopen the same task/session with the same snapshot after terminal completion, so both halves of the identity contract remain untested.

## Verdict

❌ Do not approve Phase 3 yet. The Round-1 fixes are present, but the adoption and lifecycle oracles still allow important persistence regressions to pass. The current plan is like a migration passport with the right blank fields—but nobody has checked whether the border stamp is real.
