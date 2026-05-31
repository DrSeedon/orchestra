<git-workflow>
## Git workflow rules

### Branching
- Each worker runs in an isolated `git worktree` on its own branch (`task-<id>/<worker-name>`)
- Workers NEVER touch `main` directly — only the orchestrator merges via `merge_worker()`
- All merges are **squash** — one clean commit per task in main history

### Territory
- Each worker "owns" specific directories (set at spawn via `owned_dirs`)
- Do NOT edit files outside your owned directories unless explicitly told to
- Shared files (`pyproject.toml`, `config.py`) — coordinate through orchestrator, never edit independently

### Conflict prevention
- Two workers editing the SAME files = guaranteed merge conflict
- Different directories = safe to work in parallel
- When in doubt — ask orchestrator before touching shared files

### Commits
- ALWAYS commit before reporting DONE — `git status` must be clean
- Commit messages: `#<task-id>: <what you did>` (e.g. `#49: add rate limiting`)
- WIP commits (when interrupted): `WIP #<task-id>: <what's unfinished and why>`
- Never amend commits — create new ones

### Before merge
- `git status` — clean working tree required
- All changes committed and pushed to your branch
- Report DONE to orchestrator — they handle the merge
</git-workflow>
