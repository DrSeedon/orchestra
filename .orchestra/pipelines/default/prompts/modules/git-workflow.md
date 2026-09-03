<git-workflow>
## Git workflow rules

### Branching
- Each worker runs in an isolated `git worktree` on its own branch (`task-<id>/<worker-name>`), created automatically by Orchestra
- Workers do NOT create or switch branches themselves — branching is managed by Orchestra
- Workers NEVER touch `main` directly — only the orchestrator merges via `merge_worker()`
- All merges are **squash** — one clean commit per task in main history

### Territory
- Edit files ONLY inside your own worktree (`worktrees/<scope>/<name>/...`), never in the main repository root
- **Ownership is conditional, and `owned_dirs` is optional at spawn:**
  - Your prompt contains an ownership block → those directories are a hard boundary. Do NOT edit outside them unless explicitly told to
  - No ownership block → the task defines your scope. Work the files the task needs; this is normal, not a blocker to escalate
- Shared files (`pyproject.toml`, `config.py`) — coordinate through orchestrator, never edit independently

### Conflict prevention
- Two workers editing the SAME files = guaranteed merge conflict
- Different directories = safe to work in parallel
- When in doubt — ask orchestrator before touching shared files

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
