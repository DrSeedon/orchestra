# V-702 — merge gate and merge operations

## Outcome by item

| Item | Outcome | Evidence |
|---|---|---|
| T012 | Fixed | `app/merge_test_gate.py:441-454` treats pytest exit 4 as inconclusive; `:572-599` preserves dot-prefixed paths; `:755-758` excludes deleted worker test files from the mutation overlay. Committed regression tests in `tests/test_merge_gate_mutation_702.py` cover deleted paths, `.orchestra/...`, and usage exit 4. |
| T020 | Already absent | The current prompt says workers never touch `main` and merges are squash (`.orchestra/pipelines/default/prompts/modules/git-workflow.md:4-8`). Conflict recovery prescribes a fresh branch and cherry-pick (`.orchestra/pipelines/default/prompts/modules/orchestration.md:178-179`). Search of active default prompts found no instruction to merge `main` into an outdated worker branch, so there is no current contradiction to edit. |
| T072 | Fixed | `app/mcp_stdio.py:2292-2296,2334` includes `is_terminal=false` and `is_failure=false` in structured pending/running results. `tests/test_mcp_stdio.py:2732-2741` checks the structured result. |
| T095 | Already absent | `app/workspace.py:1517-1521` refuses to merge a target checked out by the worker itself; `:1821-1830` converts an unchanged target into `NO_COMMITS_MERGED`. `tests/test_merge_worker_lifecycle_702.py:9-32` confirms self-merge refusal leaves the target HEAD unchanged; `tests/test_merge_reason_preservation_416.py` covers zero-commit normalization. |
| T096 | Already absent | `app/routes/sessions.py:3323-3360` rolls back the Git branch and restores lifecycle state when task binding raises. The committed injected-failure regression at `tests/test_task_tracker_integration.py:1688-1750` checks both branch rollback and restored binding. No code change was needed. |
| T099 | Fixed | When the session has no bound task, `app/routes/sessions.py:2338-2367` checks for a completed `task_run` receipt and returns a distinct `next_action`; `app/merge_operations.py:1102-1111` carries that action into the public operation result. `tests/test_unbound_merge_recovery_702.py` covers absent history and a completed task run; `tests/test_taskless_merge_no_id_702.py` verifies the public `merge_worker` result. |
| T101 | Fixed | `app/merge_operations.py:1095-1101` returns `WAKE_PARENT`, directing the worker to message its parent; only the orchestrator can retry with `waive_diff_budget=True`. `tests/test_diff_budget_recovery_702.py` verifies the structured recovery route. |
| T159 | Fixed | Ordinary post-completion delivery keeps the existing adhoc auto-switch. `merge_worker` defaults an explicit `task_id` to `task_outcome='complete'` (`app/mcp_stdio.py`); the operation API persists that task ID in the idempotency request and, for a taskless adhoc session, invokes `switch_branch(..., promote_current=True)` before admission (`app/routes/merge_operations.py`, `app/merge_operations.py`). `tests/test_taskless_delivery_702.py` runs complete → MCP `send_message` → commit → MCP `merge_worker(task_id=...)` against a real worktree and verifies the target file and task closure. The no-ID `PROMOTE_ADHOC_WORK` refusal remains covered by `tests/test_taskless_merge_no_id_702.py`. |

## Checks

- `/home/kesha/orchestra/.venv/bin/python -m pytest tests/test_merge_gate_mutation_702.py -q` — 2 passed.
- `/home/kesha/orchestra/.venv/bin/python -m pytest tests/test_merge_worker_lifecycle_702.py tests/test_unbound_merge_recovery_702.py tests/test_taskless_delivery_702.py tests/test_taskless_merge_no_id_702.py -q` — 4 passed after the T159 correction.
- `/home/kesha/orchestra/.venv/bin/python -m pytest tests/test_mcp_stdio.py -q -k 'merge_worker_running_past_the_cap_reads_as_progress_not_failure'` — 1 passed, 124 deselected.
- `/home/kesha/orchestra/.venv/bin/python -m pytest tests/test_diff_budget_recovery_702.py -q` — 1 passed.
- `/home/kesha/orchestra/.venv/bin/python -m pytest tests/test_task_tracker_integration.py::test_t3_switch_assignment_exception_rolls_back_branch_and_lifecycle -q` — 1 passed.
- `git diff --check` — clean. Test import path: `/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-merge/app/__init__.py`.

## Mutation checks

`evaluate_mutation_gate` used target revision `f122aa50e41cefeb026074fce322deb1b939574f`; each final check overlays committed worker tests onto target sources.

| Fixed item | Mutation result | Raw output |
|---|---|---|
| T012 | `PASSED / guarded_source_change`; both path/deletion and exit-4 regressions fail on target sources. | `mutation-T012.txt` |
| T072 | `PASSED / guarded_source_change`; the old structured result lacks the nonterminal flags and fails the test. | `mutation-results.txt` |
| T099 | `PASSED / guarded_source_change`; the old unbound merge result lacks the distinct action. | `mutation-T099.txt` |
| T101 | `PASSED / guarded_source_change`; the old result routes to generic retry instead of parent escalation. | `mutation-T101.txt` |
| T159 | `PASSED / guarded_source_change`; the old merge path landed the file but left the explicit target task `new`; the corrected path promotes and closes it. | `mutation-T159.txt` |

The first combined T099/T159 mutation attempt exceeded the gate's 25-second probe budget while selecting three lifecycle tests together. The committed tests were split by behavior and each final mutation check then completed independently. The initial attempt output is retained in `mutation-T099-T159.txt`.

Python changes require an Orchestra restart by the owner.
