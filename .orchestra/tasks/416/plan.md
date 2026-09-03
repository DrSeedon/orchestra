# #416 — preserve the merge cause without changing the no-op invariant

## Outcome

Keep the existing invariant: equal non-empty target snapshots plus zero transferred commits is not
a merge and remains `NO_COMMITS_MERGED`. Fix only the destructive assignment inside that branch:

```python
"error": raw_error or "merge produced no new commits"
```

If the raw result already contains a non-empty error, the caller receives that exact reason. If it
does not, the existing default text remains. No new state model, priority table, or public code is
introduced.

For the incident path, the preserved reason must also identify the dirty target checkout and its
Git status entries. The MCP text must tell the caller to clean that target, not verify the healthy
worker branch.

## Changes

### Preserve the raw error in `normalize_merge_result`

In `app/merge_operations.py::normalize_merge_result`:

1. Read the non-empty normalized text of `raw.get("error")` before replacing the raw dict.
2. Keep the existing no-op predicate and its `ok=false`, `state=failed`,
   `commit_point=not_reached`, and `code=NO_COMMITS_MERGED` assignments.
3. Assign the preserved raw error when present; otherwise use the existing
   `merge produced no new commits` default.
4. Leave `conflicts`, snapshots, paths, counts, and every other spread field untouched.

The existing #413 control remains the invariant oracle: it must still return
`NO_COMMITS_MERGED`. Its raw `post-merge accounting failed` text is now preserved, which is the
approved contract; the code/state, not a replacement message, carries the no-op invariant.

### Deliver an actionable dirty-target message

In `app/workspace.py::_clean_worktree_error`, keep `git status --porcelain` and the ten-entry cap,
but include `path.resolve()`:

```text
target working tree is dirty at '<absolute checkout path>'
(1 file(s): docs/tasks/49/) — commit or discard first
```

In `app/merge_operations.py::_classify_failure`, the `NO_COMMITS_MERGED` branch keeps that public
error code. When its preserved message says `target working tree is dirty`, select the existing
`CLEAN_TARGET_THEN_NEW_OPERATION` action and retain `paths_text`; otherwise keep today's
`CHECK_WORKER_THEN_NEW_OPERATION` fallback for a reasonless no-op.

`app/mcp_stdio.py::_merge_tool_result` already delivers `error.message` followed by
`next_action.message`; it is tested as a consumer and is not edited.

## Files

- Modify `app/merge_operations.py`: the no-op error assignment and dirty-target action inside
  `_classify_failure`.
- Modify `app/workspace.py`: `_clean_worktree_error` includes the resolved checkout path.
- Frozen RED oracle: `tests/test_merge_reason_preservation_416.py` at `9921a28d`.
- Phase artifacts: `docs/tasks/416/plan.md`; `docs/tasks/416/review-plan.md` remains the honest
  record of the rejected expanded plan, not approval evidence for this replacement.

## Excluded oracle replays

`d1da0dde`, `f472fcc7`, and `937ce2fd` are excluded. They belonged to the rejected priority-table
design and cannot be used as acceptance evidence. The only current frozen oracle is `9921a28d`.

## Compatibility and non-goals

- No schema, response shape, state, retry, reservation, deduplication, or diff-budget change.
- No new public error code; `NO_COMMITS_MERGED` remains the no-op code.
- No conflict/UNKNOWN precedence work and no classification matrix.
- No automatic clean, stash, checkout, or retry; dirty WIP remains untouched.
- Do not change `_branch_worktree_path`, `merge_cwd`, routes, MCP schema, or the foreign
  `comfy-image-pipeline` repository.
- The second incident attempt remains LIKELY, not CONFIRMED.

## Verification

- Before implementation, run each ticket command and observe the recorded assertion failure.
- After both tickets, run:
  `uv run pytest -q tests/test_merge_reason_preservation_416.py tests/test_merge_operations.py tests/test_workspace.py tests/test_mcp_stdio.py`.
- Final full regression, without `-x`:
  `uv run python -m pytest -q > /tmp/pytest-416.log 2>&1`; read the log once.
- Phase 3 mutation: restore unconditional
  `"error": "merge produced no new commits"` → T1 must turn red; restore production and rerun
  green. Remove the checkout path from `_clean_worktree_error` → T2 must turn red; restore and
  rerun green.
- If `uv.lock` changes, stop and do not commit it.

## Review decision

No new model review: the three-round ceiling is exhausted and the task owner explicitly prohibited
another round. The old `review-plan.md` verdict applies to the superseded table design. The owner
will mechanically inspect this compressed plan and mutate its frozen test before implementation
approval.

## Tickets

### T1 — Preserve a non-empty raw error inside the no-op result
- Files: `app/merge_operations.py`, `tests/test_merge_reason_preservation_416.py`.
- Test: `tests/test_merge_reason_preservation_416.py::test_t1_noop_preserves_existing_error_or_uses_default` — committed RED in `9921a28d`.
  Command: `uv run pytest -q tests/test_merge_reason_preservation_416.py::test_t1_noop_preserves_existing_error_or_uses_default tests/test_merge_operations.py::test_normalize_rejects_zero_commit_noop_even_when_upstream_is_failed`.
  RED: exit 1, `1 failed, 2 passed`; failing assertion:
  `E AssertionError: assert 'merge produc...o new commits' == 'target worki...discard first'`.
- AC: the command is green; non-empty raw error is returned byte-for-byte; empty raw error uses
  `merge produced no new commits`; both cases and #413 remain `FAILED`, `NOT_REACHED`, Git
  `FAILED`, code `NO_COMMITS_MERGED`.
- blocked-by: none

### T2 — Name the dirty target checkout, entries, and cleanup action
- Files: `app/workspace.py`, `app/merge_operations.py`,
  `tests/test_merge_reason_preservation_416.py`; consumer verified but not edited:
  `app/mcp_stdio.py::_merge_tool_result`.
- Test: `tests/test_merge_reason_preservation_416.py::test_t2_dirty_target_path_files_and_action_reach_merge_caller` — committed RED in `9921a28d`.
  Command: `uv run pytest -q tests/test_merge_reason_preservation_416.py::test_t2_dirty_target_path_files_and_action_reach_merge_caller`.
  RED: exit 1; failing assertion:
  `E AssertionError: assert '/tmp/pytest-of-maxim/pytest-601/test_t2_dirty_target_path_file0/repo' in 'target working tree is dirty (1 file(s): docs/tasks/49/) — commit or discard first'`.
- AC: the command is green; raw and MCP text contain the resolved target checkout and
  `docs/tasks/49/`; normalized message equals raw message while code remains
  `NO_COMMITS_MERGED`; action is `CLEAN_TARGET_THEN_NEW_OPERATION`; caller text contains
  `Clean the target worktree, then start a new merge operation.` and contains neither
  `verify the worker branch` nor `merge produced no new commits`; target ref and untracked WIP
  remain unchanged.
- blocked-by: T1
