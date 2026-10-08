# V-780: dynamic workflows from linked worker worktrees

## Finding

`dynamic_workflow` previously checked only that `repo` was a directory. The runner later passed it to `app.workspace.create_worktree()`, whose `validate_repo_root()` required `<repo>/.git` to be a real directory. Worker workspaces use a `.git` file pointing into the primary repository's `.git/worktrees/` directory, so the first writable task failed during preparation. `spawn_worker` shares the same validator through `SessionManager.create_session()`; a linked `repo_path` was normalized there and then rejected too. Other worktree creation callers also pass through `create_worktree()`.

A separate Git directory uses the gitfile mechanism too, but it is not a linked worktree. Validation therefore accepts a gitfile only when Git resolves its per-worktree git directory under the primary repository's `.git/worktrees/`, the common directory is that primary root's real `.git` directory, and the primary checkout resolves back to itself. Separate gitfile repositories and symlinked/external Git directories remain rejected.

## Changes

`validate_repo_root()` now resolves supported linked worktree paths to the primary Git root, so `create_worktree()` and `spawn_worker` use the correct shared repository metadata. `resolve_worktree_context()` validates that the supplied path is itself a checkout root and returns the primary root and exact `HEAD` commit. `dynamic_workflow` passes the primary root and pinned commit to `wf_run.py`; task worktrees are therefore based on the caller's current commit, including a detached checkout. The runner preserves this pin in its resume command. The new optional `base_commit` argument to `create_worktree()` is additive; existing branch selection behavior is unchanged when it is omitted.

## Verification

- Requested suite `uv run --frozen python -m pytest tests/test_wf_run.py tests/test_dynamic_workflows.py tests/test_workspace.py -q` — 186 passed in 67.51s. Raw output: `tests.log`.
- The first full run exposed one test double whose old three-argument signature did not accept the new commit-pin argument; 184 other tests passed. The double was updated, the affected test passed in isolation, and the complete suite then passed.
- Focused rerun `uv run --frozen python -m pytest tests/test_wf_run.py::test_workspace_preparation_uses_pinned_commit_from_linked_checkout tests/test_dynamic_workflows.py -q` — 22 passed. The later validator tightening was checked with `uv run --frozen python -m pytest tests/test_workspace.py::TestValidateRepoRoot tests/test_dynamic_workflows.py::test_dynamic_workflow_accepts_linked_worktree_and_pins_its_head tests/test_dynamic_workflows.py::test_dynamic_workflow_rejects_external_git_dir_before_queueing -q` — 11 passed. An earlier focused attempt exposed a test setup error (it passed both `base_branch` and `base_commit`); the test now passes only the pinned commit.
- Added tests verify linked-path normalization, linked-path worktree creation, a dynamic tool call's primary repo and exact commit arguments, actual workflow preparation at that pinned commit, and pre-queue rejection of a separate external git directory.
- `python -m compileall -q app/workspace.py app/mcp_stdio.py scripts/wf_run.py`, `python scripts/check_instruction_contract.py`, and `git diff --check` — passed.
- Imported module paths: `/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-workflow-tool/app/workspace.py` and `/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-workflow-tool/app/mcp_stdio.py`.

No live model calls were used. No Orchestra restart was performed.
