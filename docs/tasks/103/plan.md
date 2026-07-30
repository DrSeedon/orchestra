# #103 — Content-aware branch switching and deletion

## Decision

Replace both hash-only lifecycle guards with one shared content-status function. Preserve `rev-list == 0` as a cheap ancestry-safe allow. For hash-diverged branches, run a sanitized `git merge-tree` and allow only when the prospective result tree is exactly the resolved base tree.

The safety check must neutralize repository-defined merge behavior:

- force `merge.default=text`;
- force `merge.renormalize=false`;
- enumerate every effective `merge.<driver>.driver` key and override its command with `false` for the `merge-tree` invocation.

This prevents a custom driver from executing or declaring a false no-op while retaining Git’s built-in text/binary/union handling.

`force` will become a real public switch parameter. It remains explicit, defaults to `False`, bypasses only the committed-content check, and never bypasses dirty-tree or idle/lifecycle guards.

## Production changes

### `app/workspace.py`

Add `branch_content_status(worktree_path: str, base_ref: str) -> dict` beside the lifecycle helpers.

Contract:

- success returns:
  - `base_ref`;
  - `commits_ahead`;
  - `content_merged: bool`;
  - `reason`: `ancestor`, `content-noop`, `content-change`, or `conflict`;
- failure returns `{"error": <visible reason>}`;
- every Git/config/output parsing failure is fail-closed;
- every helper subprocess has a bounded timeout; `TimeoutExpired` becomes a visible detector error, preserving `delete_session`'s current anti-hang behavior;
- no checkout, reset, index write, worktree write, or ref update occurs.

Algorithm:

1. run `git rev-list <base_ref>..HEAD --count`;
2. command failure or malformed count → error;
3. count `0` → `content_merged=True`, reason `ancestor`;
4. read effective custom driver keys with `git config --name-only --get-regexp`;
   exit `1` means no matching custom drivers and is not an error;
5. run:

   ```text
   git
     -c merge.default=text
     -c merge.renormalize=false
     -c merge.<each-driver>.driver=false
     merge-tree --write-tree --no-messages <base_ref> HEAD
   ```

6. exit `1` → `content_merged=False`, reason `conflict`;
7. other non-zero → visible error;
8. resolve `<base_ref>^{tree}` and validate the one-line result tree;
9. equal trees → `content-noop`; different trees → `content-change`.

Update `switch_worktree_branch()`:

- retain the existing clean-tree check;
- treat a non-zero `git status` result as a visible failure instead of falling through to reset;
- when `force=False`, call `branch_content_status`;
- block on error or `content_merged=False` without moving HEAD/ref;
- use an honest message: the content could not be verified in the base, so merge first or explicitly pass public `force=True`;
- when `force=True`, preserve the current explicit override;
- leave checkout/create/merge behavior unchanged.

### `app/routes/sessions.py`

Update `switch_branch()`:

- accept `force` from the JSON body;
- require an actual boolean;
- forward it to `switch_worktree_branch`;
- do not change the existing session/lifecycle locking or persistence behavior.

Update `delete_session()`:

- retain running-worker, child-worker, dirty-tree, and explicit `force=true` guards;
- replace its duplicated async `rev-list` block with `await asyncio.to_thread(branch_content_status, wt, base_branch)`;
- allow deletion when `content_merged=True`;
- block with a visible reason when false or on detector error.

Do not change the already-forced `send_message` auto-switch or `merge_session(next_task_id=...)` paths.

### `app/mcp_stdio.py`

Update `switch_worker_branch()`:

- add `force: bool = False`;
- document that it explicitly discards committed content not verified in the base, while dirty trees remain blocked;
- send the boolean in the route JSON.

No changes to `kill_worker`: its public `force` path already exists.

## Tests

### `tests/test_workspace.py`

- multi-commit squash whose hashes differ but whose content is in the base switches successfully;
- the same squash with later base-only advancement still switches;
- genuinely unmerged worker content blocks, leaves HEAD/current branch unchanged, and does not create the requested branch;
- conflicting content blocks;
- custom merge driver that would otherwise keep the base and exit zero is neutralized and cannot cause a false allow;
- the custom-driver test uses an observable temp marker and proves the configured command itself was not executed;
- detached HEAD with verified content can create the requested branch;
- missing/invalid base and malformed Git output fail visibly as proportionate to existing test seams.

### `tests/test_api.py`

- `switch_branch(force=False)` forwards false;
- `switch_branch(force=True)` forwards true;
- non-boolean `force` returns 400;
- squash-merged delete reaches `manager.remove`;
- real unmerged content and detector errors block delete;
- persisted non-main base is forwarded to the shared detector;
- existing `send_message` auto-switch contract stays green.

### `tests/test_mcp_stdio.py`

- default switch sends `"force": false`;
- explicit force sends `"force": true`;
- the MCP doc/signature exposes the override that the error message advertises.

## Verification

1. Narrow tests:

   ```bash
   UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest -q \
     tests/test_workspace.py tests/test_api.py tests/test_mcp_stdio.py
   ```

2. Full suite:

   ```bash
   UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest -x -q \
     > /tmp/pytest-103.log 2>&1
   ```

3. Rebuild the nested multi-commit parent/child squash under a fresh `/tmp/orchestra-103-*` repository and invoke the real switch helper:

   - squash-equivalent child switches without `force`;
   - a sibling with real committed content remains on its original branch;
   - no test assertion relies only on mocks for Git behavior.

4. Run the actual new `branch_content_status()` read-only across every extant non-archived live worktree after resolving its real persisted/default base:

   - dirty trees are skipped before content evaluation;
   - record counts for ancestry allow, content-no-op allow, content-change block, conflict block, and errors;
   - require zero unexpected errors;
   - do not call switch/delete/reset/checkout on live worktrees.

5. Codex-review the implementation diff because this changes shared lifecycle/data-loss guards.

## Non-goals

- no change to squash merge strategy;
- no lifecycle-lock refactor;
- no changes to `branch_wip_status`;
- no prompt/pipeline rewrite;
- no service restart or deployment;
- no changes to `app/tg_bridge.py`.

## Tickets

### T1 — Safe end-to-end branch switch after squash

- Files: `app/workspace.py`, `app/routes/sessions.py`, `app/mcp_stdio.py`, `tests/test_workspace.py`, `tests/test_api.py`, `tests/test_mcp_stdio.py`
- AC:
  - a multi-commit squash-equivalent worker switches to `task-<id>/<name>` with `force=False`;
  - later base-only commits do not create a false block;
  - real worker-only or conflicting content leaves HEAD/current branch unchanged and creates no new task branch;
  - `git status` failure blocks before reset;
  - custom merge drivers cannot execute as the detector or turn real content into a no-op allow;
  - `switch_worker_branch(force=True)` exists publicly and reaches the helper;
  - every switch error mentioning an override refers to the now-public parameter.
- blocked-by: none

### T2 — Apply the same content guard to worker deletion

- Files: `app/routes/sessions.py`, `tests/test_api.py`
- AC:
  - a clean squash-equivalent worker reaches `manager.remove` with `force=false`;
  - a clean worker with real committed content remains blocked with `manager.remove` uncalled;
  - detector/config/Git failures block deletion visibly;
  - persisted parent/non-main bases are used;
  - existing `kill_worker(force=true)` behavior remains unchanged.
- blocked-by: T1
