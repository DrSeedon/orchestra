<git-workflow>
## Git workflow rules

### Branching
- Each worker runs in an isolated `git worktree` on its own branch (`task-<id>/<worker-name>`), created automatically by Orchestra
- Workers do NOT create or switch branches themselves — branching is managed by Orchestra
- Workers NEVER touch `main` directly — only the orchestrator merges via `merge_worker()`
- All merges are **squash** — one clean commit per task in main history

### Territory
- Edit files ONLY inside your own worktree (`worktrees/<scope>/<name>/...`), never in the main repository root
- `owned_dirs` is optional coordination metadata, not an edit allowlist.
  Change files required by the approved outcome, including shared config and tests.
  Respect explicit task exclusions and explain unexpected changes.
- Worktrees isolate repository edits, not shared services or credentials.
- Do not use `git stash` in repositories with linked worktrees: the stash stack is shared by all of them. Keep unfinished work in your task branch or in a task-local patch.

### Partial worktree
- Your worktree may be a partial (sparse) copy: large or historical directories (by default `artifacts/` and the `.orchestra/tasks/` of other tasks) are absent, while your own task directories and all source are present.
- To READ something that is absent, do not load it. Read it from the main checkout of your project, which holds the merged work of past tasks: its root is the parent directory of `git rev-parse --git-common-dir` (run it in your worktree; never guess the path, each project has its own). `git show main:<path>` and `git grep <pattern> main -- <dir>` work from your worktree on any backend, including ones that cannot read outside it.
- Load a directory (`git sparse-checkout add /<dir>/`) only when you are going to CHANGE a file in it. Signs that you need it: `git add` says paths "exist outside of your sparse-checkout definition", or `git status` shows a modified file that `git add`/`git commit` leaves out, or `merge_worker` refuses because changes lie outside the sparse checkout. Run the command from the message, then `git add` and commit again. Never copy files in by hand.
- New files of your task go into your own directories (for example `.orchestra/tasks/<your-id>/`), which are present.

### Conflict prevention
- Coordinate overlapping edits and interfaces with the relevant worker; file overlap alone
  does not imply a conflict, and separate directories do not prove semantic compatibility.
- Check actual diffs and integration tests before merge; do not stop solely over a directory label.

### Commits
- ALWAYS commit before reporting DONE — `git status` must be clean
- Commit messages: `#<task-id>: <what you did>` (e.g. `#49: add rate limiting`)
- WIP commits (when interrupted): `WIP #<task-id>: <what's unfinished and why>`
- Upstream already killed a turn (503/timeout)? → commit every finished file/unit immediately, not one batch at the end
- Never amend commits — create new ones

### Before merge
- `git status` — clean working tree required
- **Local is not remote:** a SHA from `git log` proves only a local commit. Claim that a commit is
  on a remote or published only after checking the required ref with `git ls-remote <remote> <ref>`
  and comparing the returned SHA; otherwise report it as local only.
- All changes committed to your LOCAL branch. Do NOT `git push` — merge is local (`merge_worker` squashes your branch in place) and task branches are not published. Push only if the task explicitly names a remote review workflow
- Report DONE to orchestrator — they handle the merge
</git-workflow>
