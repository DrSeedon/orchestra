# Merge-gate environment diagnosis

## Conclusion

The five files named by the 409 error were green. The apparent attribution came from
`app/merge_operations.py:1754`, which keeps only the final 400 characters of the combined batch
output. The final batch contained those five files and had `status=passed`; actual failing batches
were 4–7.

## Direct result

Command in the task worktree:

```text
.venv/bin/python -m pytest -q --tb=long tests/test_startup_bridge.py tests/test_task_repair_completion_422.py tests/test_tg_bot_api_unit.py tests/test_tm.py tests/test_workspace.py
```

Result: `148 passed in 7.76s`, RC 0. There are no failure tracebacks to attach.

The stored result for merge operation `fcf3d95b-7c0e-491c-bf23-3632ced1e441` says:

```text
batch 4/9 status=failed
batch 5/9 status=failed
batch 6/9 status=failed
batch 7/9 status=failed
batch 8/9 status=passed
batch 9/9 status=passed tests=tests/test_startup_bridge.py,tests/test_task_repair_completion_422.py,tests/test_tg_bot_api_unit.py,tests/test_tm.py,tests/test_workspace.py
```

The same record has `failed_tests=[]` and `passed_count=0`; its shortened 409 message begins in the
middle of the passed batch-9 filename list.

## Environment axes

- Packages: `pip freeze` from the worktree and main `.venv` has an empty diff.
- Process environment: key/value comparison differs only in `PWD`.
- `.env`: both files contain 19 keys, have no differing keys or values, and have the same SHA-256
  `ac3ddeb1286ad7a9192e96a5856fd47605fd511457ab1070c3b34c403edd682f`.
- Layout: `tests/test_task_repair_completion_422.py:57` reads
  `.orchestra/tasks/315/acceptance/fixtures/t2_task_store_records.json` relative to cwd. Running the
  branch test from the main cwd changes its result from `2 passed` to `1 failed, 1 passed` with
  `FileNotFoundError`, because main at `4e5940ef` still has the pre-move layout. This cross-root
  configuration was not used by the merge gate; the gate ran in the worktree, where batch 9 passed.

Platform bug reported as `Merge gate error names passed final batch instead of failing batches`.
