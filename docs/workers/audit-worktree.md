# audit-worktree — personal memory

## Before resolving a "your branch is behind" conflict — check if your work already landed
The orchestrator sometimes rescues commits by cherry-pick (e.g. when `merge_worker` would wipe an
uncommitted worktree). Then your branch is behind by ~100 commits and *contains nothing new*.
Check FIRST, it changes the whole job from "merge features" to "adopt main":

```
git log --oneline main --grep="#<task>"          # are my commits already in main?
for f in <files>; do [ "$(git rev-parse HEAD:$f)" = "$(git rev-parse main:$f)" ] && echo IDENTICAL $f; done
git diff main HEAD --stat                        # what HEAD adds over main (deletions = main-only work)
```

Read that last diff in the right direction: with a stale branch, most of `git diff main HEAD` is
main's work shown as deletions. The real delta is only the `+` lines.

## Finish the merge by proving tree identity, not by counting resolved markers
`git diff --cached main --stat` empty = the merge is exactly main. That check caught two things
grep-for-conflict-markers would not:
- `uv.lock` rewritten by a failed `uv run` (env contamination, never in my commits) → `git checkout main -- uv.lock`
- a stale test of mine that survived auto-merge and went red against main's rewritten contract

## A surviving test can be a stale duplicate — check the new layer before rewriting it
My T2 test asserted `merge_worker` returns a string containing `"switch failed: ..."`. Main moved
that to `app/merge_operations.py` (`PARTIAL` + `commit_point == "REACHED"`), covered in
`tests/test_merge_operations.py`. The guarantee survived, my test did not. Verify the invariant
still has coverage in its new home, then delete — don't rewrite against a contract that's gone.

## `uv run` here rebuilds the venv through the proxy and times out
Use the main checkout's venv directly for tests in a worktree:
`/mnt/data/Projects/Python/orchestra/.venv/bin/python -m pytest ...`

## Two locks in the merge path that are NOT duplicates
- `merge_operations.claim_operation` — per `operation_id`, in SQLite. Stops the *same* request twice.
- `workspace.repo_mutation_lock` — per git common-dir, cross-process `flock`. Stops *different*
  operations (and spawn/switch/rollback) colliding in one repo.
Two distinct merges on one repo pass `claim_operation` and still need the flock. Don't "dedupe" them.
