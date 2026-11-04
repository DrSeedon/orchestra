<git-workflow>
## Git workflow

### Isolation and scope
- Each worker runs in an isolated git worktree on a managed task branch.
- Workers do not create/switch branches or touch main; the orchestrator integrates through
  merge_worker, normally as a squash merge. Do not merge or push without task authority.
- Edit repository files only in your assigned worktree. Task-required external writes
  remain subject to explicit boundaries; isolation grants no access to shared services.
- owned_dirs is coordination metadata, not a local edit allowlist. Change what the approved
  outcome needs, respect exclusions and explain unexpected edits. Hub bundle scoping has
  its own stricter admission rules in model-routing.
- Preserve unrelated work. Do not use git stash: linked worktrees share its stack.

### Sparse worktrees
Source and your own task directories are present; large historical artifacts may be absent.
For a missing file you only need to read, use git show main:<path> or git grep against main.
A readable main checkout can also supply merged reference material; derive its root from
git rev-parse --git-common-dir, never guess or edit it.
Use git sparse-checkout add /<dir>/ only when you need to change an excluded directory,
including when git add or merge reports out-of-sparse changes. Do not copy files in by hand.

### Commits and handoff
Commit completed work on the task branch before DONE unless the task explicitly forbids
commits. Inspect git diff and git status; report any authorized uncommitted state clearly.
Use a concise subject with the exact task reference, for example #42: fix retry handling
or V-42: fix retry handling. WIP subjects state what remains. No receipt templates,
amending prior commits or rewriting another worker's history.

Workers do not push task branches unless an explicitly authorized remote review workflow
requires it. A local SHA proves only a local commit: verify the required remote ref with
git ls-remote before claiming publication. Report the exact HEAD and checks for acceptance.
Coordinate overlaps and check integration behavior; directory labels alone prove neither
conflict nor compatibility. The orchestrator must inspect the result before merge.

### Private artifacts
.orchestra/private/ is an ignored shared project folder, not a repository; its contents
survive a worker worktree. In a public repository, artifacts that must not be published
belong there rather than in tracked files. In a private repository follow owner policy.
Moving material into the tracked tree still requires publication/privacy checks. Honor
merge/pre-push secret guards; fix the content rather than bypassing a refusal.
</git-workflow>
