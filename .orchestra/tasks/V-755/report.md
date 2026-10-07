# V-755 — mutation gate overlays changed test artifacts

`evaluate_mutation_gate()` previously copied only changed `tests/*.py` files into the disposable target checkout. When the worker updated a JSON route snapshot, mutation pytest instead paired target source with target's old snapshot; that consistent old pair passed, so the merge gate reported `tests_not_guarding_source` despite the worker's updated snapshot test.

The mutation tree now overlays every changed path under `tests/`, including fixtures and snapshots, while retaining source files from the target commit. Python test-node selection remains limited to changed `.py` tests.

| Case | Outcome | Evidence |
|---|---|---|
| Changed route source + changed JSON snapshot + updated test that compares snapshot to source | Fixed | `test_mutation_gate_overlays_changed_snapshot_with_changed_test`: red before the fix; `guarded_source_change` after it. The mutation result lists both the JSON snapshot and Python test under `test_artifacts`. |
| Updated snapshot + changed test that does not compare against source | Fixed | `test_mutation_gate_rejects_updated_snapshot_without_source_guard`: result is `tests_not_guarding_source`. |
| Deleted changed test file | Preserved | `test_mutation_paths_keep_dot_directories_and_drop_deleted_tests` verifies the deleted path remains in the overlay list so it is removed from target tree. |

Checks: `/home/kesha/orchestra/.venv/bin/python -m pytest tests/test_merge_test_gate.py tests/test_merge_gate_mutation_702.py -q` → **49 passed in 38.76s**; raw output is in `pytest.log`. `app` imported from `/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-merge/app/__init__.py`. `git diff --check` passed.

The changed Python code requires the owner's Orchestra restart after merge; no restart was performed.
