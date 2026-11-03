# V-1236 — late completion after merge(continue): diagnosis + fork (no code changed)

## Evidence (current code, read-only)
- merge(continue) resets the worker branch onto the target (tests/test_switch_after_continue_620.py:
  `_rev(worktree) == _rev(repo,"main")`), task run stays `requested`, session stays bound.
- merge(complete) on that worker: app/workspace.py ~1795 returns `NO_COMMITS_MERGED`
  (target_before == worker_head); route re-checks at app/routes/sessions.py ~2985; operation layer
  at app/merge_operations.py ~1436 and `_classify_failure` ~1338. Admission
  (accept_merge_operation: root acceptor, exact head, task_run `requested`) passes, git stage refuses.
  Completion (`tm.finalize_merge_outcome`) only runs after a git commit point.
- switch_worker_branch(complete_previous) needs `task_id` and `new_task and previous_task_id`
  (sessions.py ~3507, ~3552): it completes the previous task only while assigning a DIFFERENT task
  (test_switch_with_complete_previous_closes_task_as_done_with_note). So a native action exists
  only when a next task is supplied; none for "complete with nothing next".
- Archive -> tm.release_session_task_binding requeues an in_progress task as `new` (duplicate work).
- Receipts: ia/merge_receipts._bindings requires `commit_point == target_committed`, target
  before == admitted sha, target_recheck matched, merged worker head == accepted head. A no-Git
  completion cannot satisfy it without either lying about a commit or a new receipt semantic.

## Fork (needs root choice before implementation — new lifecycle owner / receipt semantic)
A. merge_worker(complete) late path (recommended; no new parameters). In execute_merge_session,
   when git refuses with "same commit" NO_COMMITS and outcome=complete, no next_task, worker idle,
   clean, no unmerged commits, worker HEAD == expected_head == target tip: require a prior
   merge_operations record of the SAME session+task whose target_after == that head and
   commit_point REACHED (exact prior receipt); then run the existing prepare_merge_finalization
   (complete) + finalize_merge_outcome with commits={} and no Git write. Needs a decision on the
   receipt: reuse the prior operation's receipt by reference (new result field
   `late_completion_of=<op id>`, new commit_point/operation state such as LANDED_NO_GIT) instead
   of record_merge_receipt. Idempotence: same operation_id replays the stored result; a second
   operation finds task already done -> refused by `explicit merge task must be in_progress`/task
   lookup, no state change.
B. switch_worker_branch(complete_previous) accepting task_id == bound task: smaller, but no exact
   expected_head pin or acceptor authentication (switch route has none) — weaker provenance.
C. Route-only fix (skip receipts): works only when receipts are not configured; unusable in prod.

## Not done
No source or CHANGELOG change; no tests run (nothing implemented). Fork sent to root via outbox.
