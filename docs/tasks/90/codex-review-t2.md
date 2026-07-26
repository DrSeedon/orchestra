The normal checked-out-parent flow works, but target-owner resolution can return a nonexistent prunable checkout and trigger an uncaught filesystem error. This leaves a valid Git repository state unable to merge through the API.

Review comment:

- [P2] Handle prunable worktree entries before returning an owner — /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/audit-worktree/app/workspace.py:451-451
  When a target branch's registered checkout has been deleted without pruning, Git still reports that entry as `prunable`, but this loop returns its nonexistent path. `merge_worktree_to_main()` then uses it as the `git status` working directory and raises `FileNotFoundError`, causing the merge API to return 500 until the metadata is manually pruned; skip or reject prunable owners before returning the path.

## Round (2026-07-26T17:17:19Z)

Git’s ghost worktree has finally been denied entry 👻

### Re-review status

- **Prior P2 — FIXED.** Complete porcelain records are parsed; prunable or missing owners are rejected, and the `RuntimeError` is converted to `{ok: false}` without modifying the child. See [app/workspace.py](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/audit-worktree/app/workspace.py:455).

### New findings

None within the T2 diff.

### Verdict

**APPROVED.**

Validation: `tests/test_workspace.py` — **66 passed**; `git diff --check` clean. The checkout ghost now gets an error response instead of a key to the API’s 500 room.
