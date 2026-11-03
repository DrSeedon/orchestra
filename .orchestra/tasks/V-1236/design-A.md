# V-1236 design A (read-only addendum, no code changed)

## Contract: merge_worker(task_outcome=complete, expected_head, acceptance_note), no new params
Late completion = existing operation pipeline (admission: authenticated root acceptor, exact
expected_head, task_run `requested`, oracle/acceptance gates unchanged) ending in a completion
WITHOUT a Git write. Triggered only when Git stage would return NO_COMMITS_MERGED AND the proof below holds.

### Proof of the accepted prior result (answers Q1: main moved on)
Do NOT compare worker HEAD with target tip. Use the durable prior operation row (merge_operations,
fields session_id, scope, accepted_task_id, state, commit_point, terminal_worker_head,
finalization_json{task, outcome, target_after}, request_json.task_outcome):
1. exactly one latest operation for this session_id+scope, state SUCCEEDED, commit_point REACHED,
   request outcome `continue`, finalization task == the task being completed (stable_id+id, not #N text);
2. its receipt verifies (merge_receipts.get_merge_receipt + verify with that op's own bindings);
3. current worker HEAD == request.expected_head == prior terminal_worker_head == prior target_after C
   (continue resets worker onto target, so C is the exact accepted head);
4. C is an ancestor-or-equal of the pinned target tip (`git merge-base --is-ancestor C <tip>`) —
   this is what replaces "HEAD == tip" when main advanced;
5. current-state guards already in execute_merge_session stay: idle + lifecycle lock, branch/HEAD drift
   SAME, worktree clean, branch_wip_status no unmerged commits, no other live binding
   (`_live_bindings`), task `in_progress` and reserved by this operation only.
Any miss -> today's refusal (NO_COMMITS_MERGED / WORK_HEAD_CHANGED); new work after continue changes
HEAD, so it still needs a normal merge.

### Owner / result shape (answers Q3)
- Completion owner stays tm.prepare_merge_finalization + tm.finalize_merge_outcome (outcome complete,
  commits={}, next_task None); operation status owner stays merge_operations.normalize_merge_result.
- No new state, no fake commit_point: existing vocabulary is enough. Result: operation_state
  SUCCEEDED, commit_point NOT_REACHED (this operation made no commit - true), git.status NOT_STARTED,
  git.target_after/worker_head = C, commits_merged 0. Only ADDED field (old readers ignore):
  `late_completion: {prior_operation_id, prior_target_after, head_ancestor_of_target: true}`.
- Receipt: no new merge receipt (none is true). Places that today demand one for SUCCEEDED must
  accept the reference instead: merge_operations.get_operation_record (sets PARTIAL
  MERGE_RECEIPT_INVALID when no durable receipt for this op id), _run_operation durable-receipt check,
  apply_merge_finalization.require_merge_receipt, _clean_worktree_after_merge. For late completion they
  verify the PRIOR operation's receipt via `late_completion.prior_operation_id` + same task binding.
  Open point for root: whether provenance wants a small "completion receipt" instead of the reference;
  reference is the minimal choice and adds no store.
- Idempotence/concurrency: same operation_id replays stored result (existing); a second new operation
  finds task already `done` -> prepare_merge_finalization refuses (explicit/in_progress guard / no
  reservation); reservation row `tm_task_reservations` serialises concurrent completions.
- Test gate caveat (unverified): _run_operation runs evaluate_test_gate before execute_merge_session;
  a strict mapped oracle with an empty diff must be checked to PASS/skip-with-proof, otherwise the late
  path needs the existing oracle result only. To be settled by a test, not assumed.

## Limits (answers Q2) — archive reconciliation is a SEPARATE outcome
- A heals only FUTURE cases while the worker is not archived: accept_merge_operation uses
  get_session_by_name (status != 'archived') and _session_snapshot/execute_merge_session refuse archived
  ids, so A cannot even be invoked for the reporter's archived worker.
- Archived record: task `new`, worker_session_id NULL, run `interrupted/session_archived`, session
  worktree may be gone, so "clean / no unmerged" cannot be re-proven and a task lifecycle `new->done`
  is not an existing transition (explicit merge task must be in_progress). Durable receipts + prior op
  row can prove WHAT was merged, not that nothing else was assigned since. Cannot be promised.
  Needs its own root-only action/owner decision; not in A. Analysis for the reporter's record: read
  prior op row + receipt + task row only (no writes).

## Cost (no new spend class)
One Hub Sonnet-medium implementer, ~30-45 tool turns: helper `prior_landed_proof` + late branch in
execute_merge_session (~100 lines), receipt-reference exemptions in 4 spots (~50), CHANGELOG, ~10-12
route/operation tests (prior continue + advanced main, idempotent, archive-no-reset, stale head /
dirty / unmerged / other task / new assigned work refusals, running guard, non-root negative, one
boundary mutation). Optional one Opus-medium refuter pass (~10 turns) on the proof predicate.
