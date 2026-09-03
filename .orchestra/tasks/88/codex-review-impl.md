## Summary

Naturally, the path guard has an empty-path-shaped hole in it. 🙃 Normal primary repositories, nested paths, linked worktrees, bare repositories, symlinked roots, and differing scopes are otherwise handled correctly, but two lifecycle failures and three Git/protocol edge cases remain.

## Findings

### blocking: Reject missing repository paths before session side effects

**File:** [app/manager.py:412](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-repo-path/app/manager.py:412)

`if use_worktree and repo_path` skips validation for `repo_path=""` or `None`. An empty `cwd` passes `Path("").is_dir()` as the current directory, after which the manager deletes archived state, persists and starts a session without any worktree. `spawn_worker` notices missing response fields only after creation, leaving an orphan worker. When `use_worktree` is true, explicitly reject a missing/empty `repo_path`, then validate it unconditionally; add an ordering test for both `""` and `None`.

### blocking: Do not report success when initial task delivery failed

**File:** [app/mcp_stdio.py:168](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-repo-path/app/mcp_stdio.py:168)

The response from `/api/sessions/{name}/send` is discarded, so a 4xx/5xx or malformed send response still produces “Task sent.” The worker then exists without its initial task while the caller believes the lifecycle completed successfully. Capture and validate the send result before constructing the success response; on failure, report that the worker was created but task delivery failed, and add an API-error test.

### suggestion: Preserve primary worktrees that use a gitfile

**File:** [app/workspace.py:161](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-repo-path/app/workspace.py:161)

Requiring `repo/.git` to be a directory rejects valid primary worktrees created with `git init --separate-git-dir` and primary submodule checkouts, even though their top-level path is exact and they are not linked worktrees. Detect linked worktrees by resolving and comparing `git rev-parse --git-dir` with `--git-common-dir`, rather than rejecting every gitfile repository; add a separate-git-dir regression test.

### suggestion: Report repository metadata resolved by the API process

**File:** [app/mcp_stdio.py:168](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-repo-path/app/mcp_stdio.py:168)

The client recomputes `Repository` and assumes the common directory is `<repo>/.git`. Relative paths can resolve differently in the MCP and API processes, and an accepted `.git` symlink—or a supported separate git dir—has a different canonical common directory. Have the session-creation API return the repository root and common directory produced by server-side validation, require those fields, and print them verbatim.

### suggestion: Reject non-string success metadata as malformed

**File:** [app/mcp_stdio.py:157](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-repo-path/app/mcp_stdio.py:157)

Truthiness alone accepts malformed JSON such as `{"worktree_path": 123, "branch": ["task-88/child"]}` and sends the initial task, contrary to the malformed-success contract. Require both fields to be non-empty strings before sending, and extend the parameterized test with wrong-type and whitespace-only values.

## Verdict

**Changes requested.** The ordinary path works, but the empty-path bypass and ignored task-delivery failure can leave workers in the wrong or incomplete lifecycle state. The guard currently bolts the linked-worktree door while leaving the empty-path window wide open. 🪟

## Round (2026-07-26T08:31:02Z)

## Round 2

## Summary

Five fixes landed; naturally, the newly accepted Git layout breaks one step later. 🙃 `git diff` is empty, so this review uses `/tmp/task88-impl.diff` as the authoritative eight-file artifact.

- **FIXED — missing repository path:** [app/manager.py:412](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-repo-path/app/manager.py:412) rejects `""` and `None` before deletion, persistence, task mutation, or auto-commit; [tests/test_manager.py:146](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-repo-path/tests/test_manager.py:146) covers both.
- **FIXED — ignored task-delivery failure:** [app/mcp_stdio.py:177](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-repo-path/app/mcp_stdio.py:177) validates the send response and reports the created worker without claiming “Task sent.”
- **FIXED — primary gitfile worktrees:** [app/workspace.py:168](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-repo-path/app/workspace.py:168) distinguishes linked worktrees by comparing Git dir and common dir; the separate-git-dir acceptance test is at [tests/test_workspace.py:78](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-repo-path/tests/test_workspace.py:78).
- **FIXED — authoritative repository metadata:** [app/routes/sessions.py:134](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-repo-path/app/routes/sessions.py:134) returns server-resolved repository/common-dir values, which [app/mcp_stdio.py:171](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-repo-path/app/mcp_stdio.py:171) prints verbatim.
- **FIXED — malformed metadata types:** [app/mcp_stdio.py:156](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-repo-path/app/mcp_stdio.py:156) requires four non-empty strings before sending the task; wrong-type and whitespace cases are tested.

## Findings

### blocking: Resolve the primary checkout instead of the common-dir parent

**Diff:** [app/workspace.py:168](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-repo-path/app/workspace.py:168)

Separate-git-dir repositories are now accepted, but `_resolve_repo()` still returns `git_common_dir.parent`. For `repo=/tmp/repo` and `git_common_dir=/tmp/metadata`, later merge/switch operations target `/tmp`, and removal cannot recover the checkout when `scope != repo_path`. A targeted reproduction returned `target branch 'main' does not exist`. Resolve the primary checkout through `git worktree list --porcelain` or retain the canonical repository path, then test create→merge→remove with a separate Git dir and differing scope.

### blocking: Do not run fallible Git discovery after session creation

**Diff:** [app/routes/sessions.py:134](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-repo-path/app/routes/sessions.py:134)

`manager.create_session()` has already persisted and started the worker before the route reruns `resolve()` and `git rev-parse`. If the path changes or Git discovery fails, the endpoint returns an error although the worker exists; `spawn_worker` reports only “Spawn failed” and never delivers the task. Compute and retain repository/common-dir metadata during manager preflight, then return those values without another fallible lookup after the lifecycle commit point.

## Verdict

**NOT APPROVED.** All five prior findings are fixed, but two new blocking lifecycle issues remain. The 940-test suite does not cover the accepted separate-git-dir repository through merge/removal—the validator admits the right repo, then the hallway sends merge to its landlord. 🏚️

## Round (2026-07-26T08:41:28Z)

## Round 3

## Summary

The `.git` constitution has finally been ratified. 🙃 `git diff` is empty; review used the authoritative `/tmp/task88-impl.diff` containing nine changed files.

- **FIXED — missing `repo_path`:** [app/manager.py:414](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-repo-path/app/manager.py:414) rejects `""`/`None` before deletion or persistence.
- **FIXED — task-delivery failure:** [app/mcp_stdio.py:177](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-repo-path/app/mcp_stdio.py:177) validates the send response and never falsely reports “Task sent.”
- **RESOLVED BY CONTRACT — gitfile primary checkouts:** [app/workspace.py:161](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-repo-path/app/workspace.py:161) now requires a real, non-symlink local `.git` directory and rejects separate/external Git dirs.
- **FIXED — authoritative metadata:** [app/manager.py:417](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-repo-path/app/manager.py:417) captures canonical metadata during preflight; [app/routes/sessions.py:134](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-repo-path/app/routes/sessions.py:134) returns it verbatim.
- **FIXED — malformed metadata:** [app/mcp_stdio.py:156](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-repo-path/app/mcp_stdio.py:156) requires four non-empty strings before task delivery.
- **RESOLVED BY CONTRACT — separate-git-dir lifecycle:** the strict guard at [app/workspace.py:161](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-repo-path/app/workspace.py:161) makes that layout unreachable; for every accepted checkout, `common_dir.parent == repo`.
- **FIXED — post-creation Git discovery:** transient fields are defined at [app/session.py:200](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-repo-path/app/session.py:200), populated before persistence at [app/manager.py:540](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-repo-path/app/manager.py:540), and returned without filesystem access.

## Findings

No new blocking crash, wrong-repository, security, or orphan-lifecycle defects found.

## Verdict

**APPROVED.** All prior blockers are fixed or explicitly resolved by the narrowed product contract. The repo-path door now admits exactly one Git layout, which is refreshingly effective once everyone stops arguing about the windows. ✅
