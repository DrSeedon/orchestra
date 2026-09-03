# Task #92 — fail-loud worktree removal

## Result

Worktree deletion now has an outcome-based contract:

- an already absent path is an idempotent success;
- a nonzero `git worktree remove` result raises while the path still exists;
- stale cleanup reports a path only after confirming its disappearance.

`SessionManager.remove()` hydrates detached DB rows, removes their worktree, and
archives only afterward. Loaded sessions are no longer removed from the runtime
registry before cleanup succeeds. `remove_scope()` sends every remaining
detached row through the same removal path instead of archiving it directly.

The worker and orchestrator delete routes return the exact cleanup failure as
HTTP 500 instead of returning `ok: true`.

## Files

- `app/workspace.py` — fail-loud Git result, absent-path no-op, post-removal
  existence check, and `scope_dir` → `repo_dir` naming-only cleanup.
- `app/manager.py` — detached hydration and remove-before-archive ordering for
  single-session and scope removal.
- `app/routes/sessions.py`, `app/routes/system.py` — explicit deletion failure
  responses.
- `tests/test_workspace.py` — real locked-worktree failure and stale-report
  regression coverage.
- `tests/test_manager.py` — loaded/detached success, failure, missing-path, and
  scope cleanup ordering.
- `tests/test_api.py` — exact worker/orchestrator HTTP failure responses.
- `docs/tasks/92/codex-review-impl.md` — two-round adversarial review.

## Git experiment

A temporary repository under `/tmp` was created, committed, given a linked
worktree, and that worktree was locked before removal:

```text
remove_rc=128
path_exists=yes
output=fatal: cannot remove a locked working tree;
use 'remove -f -f' to override or unlock first
```

The repository was then unlocked, removed through Git, and the temporary
directory deleted. The same real failure is used by the regression tests.

## Verification

- TDD baseline: `6 failed, 4 passed`, matching the six missing contracts.
- Focused T5 tests after implementation: `10 passed in 3.13s`.
- Workspace/manager/API suite: `233 passed in 45.19s`.
- Full suite under the global test lock:
  `1095 passed, 20 skipped in 92.57s`; raw output:
  `/tmp/pytest-92.log`. The lock was released immediately afterward.
- `git diff --check`: clean.
- Codex review: **APPROVED** in both rounds. Round 2 explicitly rechecked
  TOCTOU, loaded/detached state, partial scope removal, archive failure retry,
  API propagation, and test strength; no findings remained.

## Live read-only validation

The production SQLite DB was opened with `mode=ro` and
`PRAGMA query_only=ON`; no row was changed:

```text
total_sessions=332
cwd_missing_total=247 by_status={'archived': 247}
worktree_missing_total=249 by_status={'archived': 248, 'idle': 1}
missing_path_contract=idempotent_noop
result=PASS
```

This confirms that missing paths are normal historical state, including one
current idle row, so they must not be treated like failed deletion of an
existing worktree.

## Compatibility and remaining risk

- Intentional behavior change: deleting a session whose existing worktree Git
  refuses to remove now returns HTTP 500 and leaves the session unarchived.
- `remove_scope()` can still complete earlier sessions before a later removal
  fails; each completed session has already passed cleanup, and the exact
  failure is returned for retry.
- No MCP request/response shape changed. Activating the Python route/manager
  changes requires the later shared restart; no restart was performed.
- No live worktree or DB row was mutated.
