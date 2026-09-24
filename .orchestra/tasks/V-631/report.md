# V-631 — merge taskless adhoc work

`merge_worker` now accepts an explicit `task_id` for an unbound adhoc session. The explicit path only completes an `in_progress` task. It reserves and finalizes through the existing merge lifecycle, linking the resulting commit and closing the task. A running or waiting session holding the task blocks before Git; an idle holder blocks when its task branch contains unmerged commits or dirty files. Missing and archived holders, a clean idle holder, and the same session are reclaimable. A bound session cannot use `task_id` to select another task.

The MCP tool forwards `task_id` and requires merge schema 2 through the existing task lifecycle capability check. Finalization closes the task run receipt belonging to the prior task owner when reclaiming its assignment.

Verification with test-local SQLite and task storage provided by `tests/conftest.py`:

- `/home/kesha/orchestra/.venv/bin/python -m pytest tests/test_task_tracker_integration.py tests/test_mcp_stdio.py -q` — **167 passed**.
- Mutation probe restored the old `session has no bound task` refusal for requests carrying explicit `task_id`; `/home/kesha/orchestra/.venv/bin/python -m pytest tests/test_task_tracker_integration.py -k 'explicit_task_merge' -q` — **6 failed**, covering all three permitted-owner cases and all three live-holder refusals. The mutation was reverted before the final passing run.

V-44 in seedon was not accessed or changed. No Orchestra restart was performed.
