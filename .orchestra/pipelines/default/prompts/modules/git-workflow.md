<git-workflow>
## Git & worktree mechanics

### Isolation
- Each worker runs in an isolated git worktree on a platform-managed task branch.
- Workers edit only inside their own worktree and never switch branches, run `git stash` (shared across linked worktrees), merge into `main` or push unless explicitly authorized.
- `owned_dirs` guides coordination and scopes Hub file bundles; explicit task exclusions always bind.

### Sparse worktrees & private storage
- Large historical directories (`artifacts`, `.orchestra/tasks`) may be sparse-excluded. Read merged history via `git show main:<path>` or `git grep ... main`; run `git sparse-checkout add /<dir>/` only when modifying an excluded path. Derive main root via `git rev-parse --git-common-dir` if read-only inspection is needed—never edit main directly.
- `.orchestra/private/` is an untracked shared directory surviving worktree cleanup for non-public artifacts; keep credentials and secrets out of tracked commits and honor pre-push/merge secret guards.

### Commits & integration
- Commit finished work on your task branch with the exact task prefix (`#42: ...` or `V-42: ...`) unless told not to commit, and report exact `HEAD` SHA. Orchestrators inspect diffs (`worker_wip` / `git diff main...<branch>`) and integrate via `merge_worker`.
</git-workflow>
