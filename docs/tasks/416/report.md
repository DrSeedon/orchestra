# #416 — implementation report

## Result

`merge_worker` keeps the existing `NO_COMMITS_MERGED` invariant without replacing a non-empty
raw failure reason. A dirty target result now reaches the caller with the absolute target checkout,
the Git status entries, and `CLEAN_TARGET_THEN_NEW_OPERATION`; the healthy worker branch is no
longer named as the thing to inspect.

## Tickets

### T1 — Preserve the raw no-op reason

- `app/merge_operations.py:1026-1042`: the no-op branch uses
  `raw.get("error") or "merge produced no new commits"` while retaining
  `NO_COMMITS_MERGED`, FAILED/NOT_REACHED, snapshots and counts.
- `app/merge_operations.py:1053-1061`: no-op Git status is FAILED without taking CONFLICT away
  from results that contain conflict evidence.
- Frozen command:
  `uv run pytest -q tests/test_merge_reason_preservation_416.py::test_t1_noop_preserves_existing_error_or_uses_default tests/test_merge_operations.py::test_normalize_rejects_zero_commit_noop_even_when_upstream_is_failed`
  → `3 passed in 1.77s`.

### T2 — Deliver the dirty target and permitted action

- `app/workspace.py:834-851`: `_clean_worktree_error` includes `path.resolve()` and retains the
  existing ten-entry Git status cap.
- `app/merge_operations.py:941-951`: dirty-target text under `NO_COMMITS_MERGED` selects
  `CLEAN_TARGET_THEN_NEW_OPERATION`; a reasonless no-op retains the old worker-check fallback.
- `app/mcp_stdio.py::_merge_tool_result` required no edit: its existing formatting delivers the
  preserved error plus action.
- Frozen command:
  `uv run pytest -q tests/test_merge_reason_preservation_416.py::test_t2_dirty_target_path_files_and_action_reach_merge_caller`
  → `1 passed in 1.89s` (and `1 passed in 2.16s` after mutation rollback).

## Mutation evidence

Both mutations were run only against green tests, with backup → mutation → rollback in one shell
command, `touch` after Python restore, and a final green rerun.

### T1 — restore destructive error replacement

```text
T1_PRODUCTION_MARKER_BEFORE=1
T1_MUTANT_MARKER_DURING=1
T1_MUTANT_RC=1          # 1 failed, 2 passed
T1_PRODUCTION_MARKER_AFTER=1
T1_MUTANT_MARKER_AFTER=0
T1_RESTORED_RC=0       # 3 passed
```

### T2 — remove target checkout path

```text
T2_PRODUCTION_MARKER_BEFORE=1
T2_MUTANT_MARKER_DURING=1
T2_MUTANT_RC=1          # missing resolved target path
T2_PRODUCTION_MARKER_AFTER=1
T2_MUTANT_MARKER_AFTER=0
T2_RESTORED_RC=0        # 1 passed
```

## Regression evidence

- Focused production consumers:
  `tests/test_merge_reason_preservation_416.py` + #413 + workspace dirty + MCP failure
  → `6 passed in 2.09s`.
- Four affected test files together:
  `tests/test_merge_reason_preservation_416.py tests/test_merge_operations.py tests/test_workspace.py tests/test_mcp_stdio.py`
  → `263 passed, 2 failed`; the two unrelated failures reproduced on detached `main` with the
  same node ids.
- Monolithic `uv run python -m pytest -q` was killed at 82% with RC 137. It is not treated as
  acceptance evidence.
- Exhaustive replacement run split all 180 `tests/test_*.py` files into 12 fresh pytest processes:
  `3354 passed, 46 failed, 88 skipped, 3 xfailed, 3 deselected`.
- All 46 failing node ids were rerun on detached `main@152300b5`; result was exactly
  `46 failed`. Therefore the branch introduced **zero new failing node ids** across the full
  `tests/` corpus. The detached baseline worktree was removed after comparison.

## Pre-mortem checks

1. **Reasonless no-op loses its honest fallback** → T1 empty-error control still returns
   `merge produced no new commits`.
2. **#413 contradictory no-op becomes success** → existing #413 control remains
   FAILED/NOT_REACHED with `NO_COMMITS_MERGED`.
3. **No-op status masks actual conflict evidence** → conflict status branch remains ahead of the
   no-op FAILED branch; affected workspace/normalizer suites ran in the 263-pass focused result.
4. **Merge cleanup mutates target WIP or ref** → T2 asserts the untracked file bytes and target ref
   are unchanged.
5. **MCP still sends the caller to the worker branch** → T2 rejects both `verify the worker branch`
   and the generic no-commit text, and requires the cleanup action/path/status entry.

## Compatibility, deployment, and TODO

- Breaking schema/API changes: none.
- Behavioral correction: dirty no-op action changes from worker verification to target cleanup.
- No foreign repository, WIP, target ref, diff-budget, operation state, reservation, or retry
  semantics were modified.
- Python service restart is required after merge for the live runtime to load these changes.
- TODO outside #416: the existing 46 baseline failing node ids remain project debt; none is in the
  changed merge code or frozen #416 oracle.

## Review

Review: skipped — explicit owner instruction after the three-round plan-review ceiling. Mechanical
gate evidence supplied by the owner: original RED, a mutated wrong-code control turned red, and the
minimal oracle shape was accepted. Implementation acceptance rests on the immutable `9921a28d`
oracle, the two caught mutations above, focused consumer tests, and full-corpus branch/main node-id
comparison.

## Commits

- `8f836a39` — preserve raw no-op merge reason.
- `05fa35bc` — deliver actionable dirty target reason.
- `88ea0353` — preserve conflict Git status while keeping no-op FAILED.
