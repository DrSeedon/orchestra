# V-982: bind existing tasks without disturbing running workers

Read the complete `/api/report_bug` record `20261020T070400.630731Z-d967d54d8d8845c5ba283956e0c3c645.md`. Investigation and changes started from local revision `af5ea6ce1`. No external project, task record, worktree, worker process or service was inspected or changed; the reproduction uses temporary Git repositories, an isolated task store and the test database.

The report's state is possible: keyed direct delivery starts taskless adhoc work without assigning a task. The legacy unkeyed send path instead allocates a new task, while `switch_worker_branch(promote_current=True)` requires idle and clean work. Neither is a suitable operation for explicitly assigning an existing task to a running worker with WIP. The report's `#V-251:` commit headers also failed the existing leading-reference parser.

`bind_worker_task(name, task_id)` now calls `POST /api/sessions/{name}/bind-task`. It requires the authenticated same-scope durable parent and resolves the existing scoped task. It uses the existing canonical binding transaction to publish in-progress status, session/task ownership, matching unmerged commit links and the task-run receipt. It does not create tasks, send messages, rename branches, reset HEAD or write worker files. Pending session persistence drains before the binding transaction. The transaction runs through `await asyncio.to_thread(...)` so task-store lock waits and projection refresh do not block the event loop; the live task id is updated immediately when it returns, without another await.

Conflicting session/task owners, split ownership, reservations, completed tasks, foreign scopes/parents/tasks, absent proof, pending branch switches, inconsistent branch metadata and unavailable history refuse assignment. The parent, branch, task status and ownership are checked again in the binding transaction. Repeating the same assignment leaves one task and one run. `#V-251:` headers now resolve to `V-251`; prose references remain subject to the existing leading-header constraint.

Commit links describe the captured HEAD at assignment and include only headers referencing that task. Commits appended later use the normal merge linkage. An unlabeled commit is preserved in Git but is not inferred to belong to a task. Explicit binding avoids guessing a task from prose or commit messages.

## Validation

Imported app: `/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-task-binding/app/__init__.py` (`uv run --frozen python -c 'import app; print(app.__file__)'`).

`uv run --frozen python -m pytest tests/test_bind_worker_task_982.py tests/test_task_binding_417.py tests/test_task_binding_refusal.py tests/test_vps_task_prefix.py tests/test_task_tracker_integration.py tests/test_taskless_delivery_702.py tests/test_switch_after_continue_620.py tests/test_task_runtime.py tests/test_git_task_api.py tests/test_workspace.py tests/test_mcp_stdio.py -q`: **362 passed in 64.55s**, exit 0. Raw output: [tests.log](tests.log). This run preceded the final adhoc-fixture refinement, addition of the end-to-end merge test and the acceptance correction offloading the binding transaction.

Final `uv run --frozen python -m pytest tests/test_bind_worker_task_982.py -q`: **15 passed in 12.32s**, exit 0. Raw output: [final-regression.log](final-regression.log). The final fixture starts with a running taskless worker on an `adhoc-*` branch, six `#V-251:` commits and an untracked file. It verifies unchanged branch, HEAD, complete commit history, index/diffs, dirty-file bytes and running status after assignment/retry; canonical Git task state and the task-run receipt; pending-save ordering; twelve refusal cases; and successful normal acceptance/merge after the worker finishes its WIP.

Acceptance correction after `3b4830ce7271b6998aa6e16e8a442ead3e330071`: offload `_tm.bind_task_to_session` through `await asyncio.to_thread(...)` and update `live.task_id` immediately on return. The pending-save regression additionally asserts that binding executes outside the event-loop thread. Re-ran `uv run --frozen python -m pytest tests/test_bind_worker_task_982.py -q`: **15 passed in 9.93s**, exit 0, [offloaded-regression.log](offloaded-regression.log). Incremental diff and staged secret-form checks passed; imported app path is unchanged.

Merge-gate correction after `9492777a07bdf3ebc1eeda9b3a54a1fe7e163f59`: added the intentional `POST /api/sessions/{name}/bind-task` route to `tests/route_surface_snapshot.json`. A structural comparison against the prior committed snapshot verifies exactly that one addition and no removed routes. `uv run --frozen python -m pytest tests/test_routes_surface.py tests/test_bind_worker_task_982.py -q`: **17 passed in 10.22s**, exit 0, [route-surface-regression.log](route-surface-regression.log). Incremental diff and staged secret-form checks passed; imported app path is unchanged. No merge was retried.

Two in-memory mutations against the committed regression file exited 1 as expected; no source files were mutated:

- Removing optional `#` support for prefixed headers makes `test_mcp_binds_running_dirty_worker_to_existing_prefixed_task` fail on the missing six commit links: [header-mutation.log.gz](header-mutation.log.gz).
- Replacing `_live_bindings` with an empty result makes `test_binding_refuses_conflicts_without_changing_wip[split_owner]` fail because assignment incorrectly succeeds: [owner-mutation.log.gz](owner-mutation.log.gz).

The mutation outputs are stored losslessly compressed because pytest includes trailing whitespace in traceback source excerpts; decompression preserves the original command output verbatim.

`uv run --frozen python scripts/check_instruction_contract.py`: exit 0, AGENTS.md below 16 KiB and CLAUDE.md remains its symlink. `git diff --check`: exit 0. `scripts/secret_scan.py` was run with `uv run --frozen python` on every changed source, test, changelog and task evidence file and again on the staged changes: no secret-form findings.

## Integration

The merge landed as `95f9d202536646b416204d4913d934c89402025e`; `origin/main` was verified at the same SHA. Exact main CI run `39386729403` completed successfully. The owner-delegated API restart replaced MainPID `840206` with `1163912`; `/` returned 302, application startup completed, `MemoryHigh/MemoryMax` remained 14/16 GiB, and `oom_score_adj` remained 800. Restart returned `cut_turns=3` and `cut_names` `Orchestra-orchestrator`, `ege-rus-uroki`, `bolshoe-dz-tolya`; startup injected restart notices for all three and all three were running again. Startup restored 25 background jobs and expired 0. Telegram polling and the bridge reached ready state after a transient disconnect during shutdown. The new MCP tool is available after reconnect.

At the first post-deploy check, the reported cross-project data was unchanged. Katya later invoked the new bind tool for the existing V-251 assignment. A read-only verification then showed task status `in_progress`, five linked commits, and `kurs-stepik` running with `task_id=V-251` on its original adhoc branch. The same-scope parent performed the binding; no cross-scope identity was impersonated and the Orchestra owner did not modify the Katya task or worktree. This resolves the reported mismatch. The available evidence does not distinguish a platform defect from a missed explicit binding step; the new API provides that recovery operation.
