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
- All changes committed to your LOCAL branch. Do NOT `git push` — merge is local (`merge_worker` squashes your branch in place) and task branches are not published. Push only if the task explicitly names a remote review workflow
- Report DONE to orchestrator — they handle the merge
</git-workflow>
