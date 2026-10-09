# V-791 — mutation failures must be attributable to the source rollback

## Result

`evaluate_mutation_gate()` now runs the selected test nodes twice from equivalent `git archive` trees. The control tree overlays the worker's changed source files; the mutation tree retains target sources. Both use the same changed tests and test data, and both omit `.git`. A test node is mutation evidence only when pytest reports it PASSED in control and FAILED/ERROR in the target-source run. Thus Git-dependent nodes that fail in both trees cannot prove the mutation was caught.

The existing target-tree failure remains `tests_not_guarding_source` when control is entirely green but no attributable red is observed. If control or an unclassifiable mutation failure prevents a comparison, the mutation result is `inconclusive` rather than false proof.

## Regression evidence

`test_mutation_gate_ignores_git_environment_failure_but_counts_source_regression` commits two changed test nodes: one reads changed application code and fails on target sources; the other calls `git branch --show-current` and fails because neither archive tree has `.git`. It asserts that only the application regression appears in `mutation_failed_tests`, while the Git-only failure appears in both `control_failed_tests` and `unattributed_failed_tests`.

Before the implementation, this regression failed: the old gate treated every mutation-tree failure as `guarded_source_change`, with no distinction between the Git-only environment failure and the source regression. After the implementation, the focused regression and three adjacent mutation-gate cases passed (`4 passed in 5.20s`). Full gate-suite results and raw output are in `pytest.log`.

## Scope and runtime

Changed `app/merge_test_gate.py`, `tests/test_merge_test_gate.py`, `tests/test_merge_gate_mutation_702.py`, and `CHANGELOG.md`. The test imported `app` from this worktree. The Python change requires an owner-initiated Orchestra restart after merge; no restart was performed.
