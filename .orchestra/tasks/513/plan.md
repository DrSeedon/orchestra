# #513 — plan: review a target worker without waking it

## Outcome

Add one optional `target_worker` argument to `codex_review`. It is accepted only for `mode="implementation"`; when present, the caller remains the owner of the review artifact, resume thread, usage record, background job, and wake-up, while the named same-scope non-orchestrator worker becomes the reviewed subject and the identity stored in the qualifying receipt.

The merge gate is not changed. `coverage_decision` continues to require the exact `scope + session_id + task_id + target_sha + production_snapshot_sha256`, and both existing `REVIEW_COVERAGE_MISSING` refusals remain in place.

## Design

### Split actor from review subject before receipt reservation

In `app/mcp_stdio.py::codex_review`, replace the overloaded `info`/`cwd` state with two explicit records:

- `actor_info` / `actor_cwd`: always resolved from `/api/sessions/{WORKER_NAME}`. It owns relative `output_abs`, `codex_sessions.json`, receipt-finalizer usage fields, `bg_jobs.target_name`, `bg_jobs.created_by`, `target_scope`, and the completion notification.
- `subject_info` / `review_cwd`: equal to the actor for the existing self-review path; when `target_worker` is non-empty, resolved separately from `/api/sessions/{target_worker}?scope=SCOPE`. It owns `resolve_implementation_subject(review_cwd, base_branch)`, the generated `git diff target_sha...worker_head`, and receipt `session_id`, `worker_name`, `scope`, `task_id`, `target_sha`, `worker_head`, `production_snapshot_sha256`, and `production_paths_json`.

For a targeted review, store `decision_actor=WORKER_NAME`. Keep `turn_usage.session_id/scope/task_id` on `actor_info`: the caller initiated and owns the model run, while the target worker never executed a turn. The receipt independently binds the reviewed work to the target worker/task. The test freezes this distinction as actor usage arguments plus target receipt fields.

Resolve and validate the target before receipt reservation, quota readiness, or background-job creation:

1. `target_worker` with a mode other than `implementation` is `invalid_argument` on field `target_worker`.
2. A 404 from the target lookup becomes `target_worker_not_found`; no review job starts.
3. The returned normalized scope must equal normalized `SCOPE`; mismatch becomes `target_worker_scope_mismatch`.
4. `is_orchestrator` must be false; otherwise return `target_worker_not_worker`.
5. Receipt-critical target fields must be non-empty and internally consistent: `id`; exact returned `name == target_worker`; `task_id`; `worktree_path`; and `base_branch`. Empty/mismatched values return `target_worker_invalid_session` with the offending field. A non-existent worktree returns the same typed code for `worktree_path`.
6. `resolve_implementation_subject` validates that the base ref exists and retains its clean committed worktree check. A missing base or dirty target returns the existing `invalid_argument` before receipt/job creation, and no file is changed.

Requiring a bound `task_id` does not close a legal taskless merge path: #465 requires committed adhoc work to be explicitly promoted and bound to a new task before unchanged `merge_worker` is called. A targeted receipt intended for merge admission must therefore target the post-promotion bound session.

Do not add a server route or a second receipt type. This path runs a real reviewer against the exact target diff, so it needs no policy decision endpoint. No local role assertion is used as authorization: the operation does not bypass review, and the exact target receipt is still required by merge admission.

### Keep target worktree read-only

Run only the review command's `cd` in `review_cwd`. Build `output_abs`, `sessions_path`, `round_tmp`, the git exclude setup, and success-file path from `actor_cwd`. For targeted review, resolve `output_abs` and require it to stay within the resolved actor worktree; absolute or `..`/symlink paths that resolve into the target or elsewhere return `invalid_argument` on field `output` before receipt reservation. Existing self-review output behavior remains unchanged. Keep `/tmp/codex_review_{WORKER_NAME}_...` scratch names and background-job delivery on `WORKER_NAME`.

This separation is a correctness condition, not cosmetic ownership. Writing `.orchestra/tasks/.../review*.md` or `codex_sessions.json` under the blocked target would dirty the very worktree admission is about, and that worker cannot wake to commit it.

### Preserve exact merge admission

`app/review_coverage.py` and `app/merge_operations.py` receive no production changes. The #513 test reaches `accept_merge_operation` twice through independent controls:

- no receipt: `409`, `REVIEW_COVERAGE_MISSING`, `RECORD_REVIEW_THEN_NEW_OPERATION`, and zero inserted merge operations;
- initially matching receipt followed by an `app/**` commit: the precondition is `satisfied`, then the changed snapshot returns the same typed refusal.

The positive path completes the receipt produced by targeted `codex_review` and then requires `accept_merge_operation` to return `202` with `coverage_outcome=reviewed`.

### Public README contract

Update both stale statements in the same implementation task:

- the ✅ comparison row must contain the exact delivery anchor `An orchestrator can review a target worker's exact snapshot without waking that worker`, remove the closed own-session limitation, preserve the exact-snapshot refusal claim, and refresh any shifted `app/mcp_stdio.py` line anchor;
- the Cross-Model Review section must say the merge code now enforces review coverage for production paths, instead of saying enforcement does not exist.

`.orchestra/tasks/513/check_readme.py` owns the #513 text delivery check. `.orchestra/tasks/511/check_table.py` independently checks all comparison rows and the continued presence of `RECORD_REVIEW_THEN_NEW_OPERATION`; both commands must pass.

## Files

- `app/mcp_stdio.py` — optional targeted implementation subject, typed validation, actor/subject separation.
- `tests/test_review_target_worker_513.py` — immutable targeted-review and fail-closed merge oracle.
- `README.md` — close the target-worker limitation and stale enforcement statement; refresh code anchors.
- `.orchestra/tasks/513/check_readme.py` — already-frozen delivery check.
- `.orchestra/tasks/513/plan.md`, review artifact, and Phase-3 report.

`app/review_coverage.py` and `app/merge_operations.py` are assertion targets only and are not planned for modification. `.orchestra/workers/fix-review-receipt.md` changes only if the mandatory end-of-task memory check finds a reusable personal lesson.

## What not to touch

- Receipt schema or `app/db.py`.
- `record_review_outcome` and its HTTP routes.
- Quota admission in `app/session.py`, `app/quota_gate.py`, or model routing.
- Production prefixes, snapshot hash formula, policy marker, review verdict interpretation, or merge operation lifecycle.
- Reviewer model selection, round ceilings, or the existing self-review call shape.

## Oracle independence and mutation checks

The final immutable oracle is commit `3732d1c6`. The earlier runs/commits `c509bd1d` and `7ed0503b` are **excluded**: the first did not freeze actor-owned `turn_usage`, and the second lacked reviewer-required path containment, preflight durability checks, mode validation, and malformed-session validation. Neither may be cited as the final oracle. Current baseline for the final command is `17 failed, 2 passed in 17.35s`, grouped by independently asserted seams:

1. `T1 addressed-review seam: receipt kept the caller session instead of the target worker`.
2. `T1 missing-target seam: nonexistent target silently launched a caller review`.
3. `T1 scope seam: a target returned from another scope launched a review`.
4. `T1 role seam: target_worker accepted an orchestrator as a reviewed worker`.
5. Two mode cases: `T1 mode seam (review|exec): target_worker was silently ignored outside implementation`.
6. Five structural fields: `T1 target-identity seam (id|name|task_id|worktree_path|base_branch): malformed worker launched a review`.
7. `T1 target-worktree seam: nonexistent target worktree launched a review`.
8. `T1 target-base seam: unresolved target base launched a review`.
9. Two containment cases: `T1 output-boundary seam (absolute|traversal): targeted artifact escaped actor worktree`.
10. `T1 dirty-target seam: uncommitted target launched a background review`.
11. `T1 review-cwd seam: addressed review still generated the caller's diff`.

Every preflight rejection additionally asserts zero `review_receipts`, zero `turn_usage`, zero background jobs, and no quota-readiness call. The no-receipt and stale-receipt controls are already green on the baseline because the existing gate is correct; they are not allowed to become vacuous. The stale test first proves its seeded receipt is `satisfied` on the original head before moving the head.

After implementation is green, mutate one seam at a time and restore before the next:

- replace subject receipt identity with actor identity → addressed receipt/merge test must fail;
- remove each missing/scope/role validation independently → its named rejection test must fail and show a job was attempted;
- remove mode validation → the `review`/`exec` cases must fail before any API call;
- accept each empty/mismatched receipt-critical field or a missing worktree/base ref → its field/base case must fail before durable writes;
- allow an output resolved outside `actor_cwd` → the absolute/traversal cases must fail;
- resolve the implementation subject from `actor_cwd` → target-diff test must fail;
- build `output_abs` from `review_cwd` → artifact ownership assertion must fail;
- route `target_name` or `created_by` to the subject → the corresponding wake/creator assertion must fail;
- attribute usage to the subject → actor usage assertion must fail;
- remove the clean-target resolution or use actor cleanliness → dirty-target test must fail while its before/after tree assertions remain intact;
- weaken the exact receipt lookup to admit no receipt or an old snapshot → the no-review or stale-snapshot test must fail, respectively.

Each mutation command records the production marker count before mutation and after restoration, then reruns the green target command after restore. No mutation result is evidence unless the immutable test at `3732d1c6` catches it.

## Rollout and the self-referential merge

The connected MCP process loads `app/mcp_stdio.py` from current `main`, not from this worktree. Therefore #513 cannot use its new `target_worker` argument to certify itself before merge. After the implementation commit, this same worker must call the already-live `codex_review(mode="implementation")` self-review path, which is already snapshot-correct for its own session/task; that real receipt lets the unchanged merge gate admit #513. No model change of the worker is required while its current turn remains active.

The new targeted path becomes live only after the merged Python is restarted/reconnected by the normal platform lifecycle. Unit acceptance runs the branch code in a fresh process and is the pre-merge proof; a post-merge live probe is rollout evidence, not a reason to weaken the pre-merge gate.

## Tickets

### T1 — Targeted implementation review with exact receipt and caller-owned delivery

- Files: `app/mcp_stdio.py`, `tests/test_review_target_worker_513.py`.
- Test: `/home/kesha/orchestra/.venv/bin/python -m pytest -q tests/test_review_target_worker_513.py` — committed RED in final oracle `3732d1c6`; prior oracle/runs `c509bd1d` and `7ed0503b` excluded after usage-attribution and reviewer-blocking strengthening.
- RED: exit 1, `AssertionError: T1 addressed-review seam: receipt kept the caller session instead of the target worker`; total `17 failed, 2 passed in 17.35s`, with the independent failure groups listed above.
- AC: the named command is green; `/home/kesha/orchestra/.venv/bin/python -m pytest -q tests/test_review_coverage_gate_462.py tests/test_mcp_codex_review.py tests/test_mcp_quota_gate.py` is green; every mutation listed above makes only its named seam red and the restored command is green.
- blocked-by: none.

### T2 — Publish the real enforced target-review behavior

- Files: `README.md`, `.orchestra/tasks/513/check_readme.py`.
- Test: `/home/kesha/orchestra/.venv/bin/python .orchestra/tasks/513/check_readme.py && /home/kesha/orchestra/.venv/bin/python .orchestra/tasks/511/check_table.py` — delivery check committed RED in `c509bd1d` and unchanged in final oracle `3732d1c6`.
- RED: exit 1, `README #513 delivery failed: target-worker review capability is absent from the comparison row; closed target-worker limitation is still published; README still says the merge gate is not enforced`.
- AC: the named delivery command is green and the comparison row's live `app/mcp_stdio.py`/`app/merge_operations.py` line anchors resolve after the code edit.
- blocked-by: T1.

## Plan review inputs

- **Changed production files and consumers:** `app/mcp_stdio.py::codex_review`; consumers are caller MCP schema, target session lookup, receipt reservation/finalizer, Codex command cwd, bg-job delivery, turn usage, and merge coverage lookup. `README.md` is the external public consumer.
- **Author metadata:** `gpt-5.6-sol`, Codex runtime, live session `bfa9f5f2-57e0-46d5-a826-c5b7ec45a323`.
- **Exact AC:** both ticket commands and the focused regression command above, plus the listed one-seam mutations; no one-process full suite.
- **Named RED outputs:** T1 `17 failed, 2 passed in 17.35s`; T2 three-clause delivery failure; final frozen oracle `3732d1c6`. The focused pre-implementation regression is green: `55 passed in 29.00s`.
- **Risk floor and route:** this changes an externally consumed MCP contract and the authoring path for a review/admission receipt. Canonical route is Sol, but no auxiliary Sol review was explicitly authorized; one Luna plan pass is permitted and cannot lower the risk floor.

## Plan review outcome

Round 1 Luna returned four blocking findings. All were verified against current code and accepted: targeted output could escape `actor_cwd`; preflight tests did not exclude orphan receipts/usage or quota calls; the non-implementation mode contract was untested; target receipt-critical identity fields were under-validated. The executable oracle was re-frozen at `3732d1c6` with all four closures.

Round 2 marked all four prior blockers **FIXED** and added one suggestion: the mutation paragraph still named excluded oracle `7ed0503b`. The stale reference is corrected to `3732d1c6` above. No third round is opened because `codex-debate` does not permit a new round for a suggestion alone. Both rounds contain substantive findings but neither artifact supplies a reviewer-run command plus output or a full verbatim line from the reviewed plan that was absent from the prompt; the formal review result is therefore **вердикта нет — review without completion evidence**. The original dissent and both rounds remain in `.orchestra/tasks/513/review-plan-luna.md`.
