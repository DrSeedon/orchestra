# V-996: worker bound to a cancelled task cannot deliver new work

Cause (read from code, claude-runtime state read-only: idle, task_id V-830, needs_switch 0, task_run `interrupted`, V-830 `cancelled`):
cancelling a task only finishes its task_run (`tm.py` ~1419/1862); the session keeps `task_id` and branch. A new task sent by
`send_message` therefore ran on `task-V-830/...`; `merge_operations` then fails `task_run["status"] != "requested"` (WORK_ASSIGNMENT_CHANGED)
and `promote` refuses a bound session. Merge-complete avoids this because it sets `task_id=""`, `needs_switch=True`.

Fix (smallest): `SessionManager._auto_switch_before_delivery` — an IDLE session whose bound task is `cancelled`
(`tm.task_binding_is_cancelled`) gets `task_id=""`, `needs_switch=True` (`persist_lifecycle`), then the normal auto-switch
creates a fresh adhoc branch and releases the cancelled task's worker link. The new work is then taskless adhoc work that
`merge_worker(task_id=<new>)` promotes (documented path). Non-cancelled bindings untouched.

Checks: `tests/test_v996_cancelled_task_binding.py` (cancelled → adhoc branch, binding cleared; in_progress → unchanged).
With adhoc_switch, manager, lifecycle_quarantine_499, task_tracker_integration, merge_branch_drift: 256 passed (`tests.log`; the one
failure there was a fake session without `task_id`, fixed with `getattr`, rerun in `tests2.log`: 186 passed). Mutation (fix disabled) → the
cancelled test is red (`mutation.log`).
Limits: claude-runtime's live branch was not touched; a worker that already committed on the stale branch is not repaired;
done (not cancelled) bindings keep the existing quarantine behaviour. Restart needed (Python).
