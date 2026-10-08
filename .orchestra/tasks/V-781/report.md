# V-781 — refresh taskless worker branch on assignment

The parent `send_message` path creates and binds a task for a taskless idle worker. Its branch refresh recognized the legacy `task-adhoc/` name and `needs_switch`, but not the current `adhoc-*` branch name produced after merge. In that state it bound the task and delivered the message without moving the worker's HEAD, so main could advance while the worker stayed on the old commit. The `needs_switch` branch also used `force=True`, which could discard committed work.

The assignment path now recognizes both adhoc formats. It resolves the local `main` ref at assignment time, checks the worker's uncommitted files and commits relative to that ref, and returns HTTP 409 with a stale-base message without switching when work exists or the state cannot be verified. A clean worktree switches to the new task branch from current `main` without force. If validation refuses, the newly created task remains `new` and unbound in the task queue; the branch and worktree remain untouched.

| Case | Outcome | Evidence |
|---|---|---|
| Main advances after the idle worker's adhoc branch was created | Fixed | `test_taskless_send_assignment_starts_from_current_main`: before the fix, branch remained `adhoc-*`; after the fix, its new task branch HEAD equals current main and includes the new main file. |
| Worktree contains uncommitted changes | Fixed | Parametrized `test_taskless_send_refuses_to_move_branch_with_unlanded_work`: HTTP 409 says base is stale; branch and HEAD stay unchanged; task remains unbound; delivery is not sent. |
| Worktree contains an unmerged commit | Fixed | Same parametrized test, committed-work case, with the same no-switch/refusal assertions. |

The regression tests were first run against the old code: all three cases failed (the clean branch was not refreshed; dirty and committed work were silently assigned). After implementation, the full merge/switch/task-binding set passed: `/home/kesha/orchestra/.venv/bin/python -m pytest tests/test_stale_task_assignment_781.py tests/test_task_tracker_integration.py tests/test_task_binding_417.py tests/test_adhoc_switch.py tests/test_lifecycle_quarantine_499.py tests/test_merge_recovery_wedge.py -q` → **74 passed in 80.07s**. Raw output is in `pytest.log`; `app` imported from `/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-merge/app/__init__.py`.

After commit `c8f18eb0` included the regression tests, mutation check removed recognition of `adhoc-*`; the committed test file then failed all 3 cases. The mutation output is in `mutation-red.log`; after restoring the code, the same test file passed **3 tests**.

The route change requires the owner's Orchestra restart after merge. No restart was performed.
