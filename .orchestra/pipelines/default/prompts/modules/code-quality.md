<code-quality>
## Engineering, worktrees & repository hygiene

### Runtime environment & test discipline
- **Cgroup & host limits**: on exit `137` / `SIGKILL`, check process cgroup `memory.max`, `memory.current` and `memory.events` alongside host RAM before blaming code; lower concurrency or footprint rather than altering cgroup/unit limits. Use `acquire_test_lock` / `release_test_lock` when serializing heavy shared-resource suites.
- **Single source of policy & raw data fidelity**: keep validation at the boundary it protects so optional metadata failures never break safe execution paths. Store complete raw external records first and apply business filtering at query/view time unless source/memory limits require narrowing (state coverage limits explicitly).
- **Contract tests**: test durable behavior, authorization, recovery and assembly contracts rather than fragile editorial phrasing. Never weaken frozen acceptance tests; report defective frozen assertions with evidence.

### Worktree & Git mechanics
- **Worktree isolation**: Each worker runs in an isolated worktree on a dedicated task branch (`task-123` / `task-V-42` / `worker/<name>`). Edit only inside your assigned worktree; never switch branches, run `git stash` (shared across linked worktrees), merge into `main` or push unless explicitly authorized. `owned_dirs` guides coordination and scopes Hub file bundles; explicit task exclusions always bind.
- **Sparse worktrees & `.orchestra/private/`**: large directories (`artifacts`, `.orchestra/tasks`) may be sparse-excluded—read merged history via `git show main:<path>` or `git grep ... main`, and run `git sparse-checkout add /<dir>/` only when modifying an excluded path (derive main root via `git rev-parse --git-common-dir` if read-only inspection is needed; never edit main directly). `.orchestra/private/` is an untracked shared directory surviving worktree cleanup for non-public artifacts; keep secrets out of tracked commits.
- **Commits**: commit finished work on your task branch with the exact task prefix (`#42: ...` or `V-42: ...`) unless told not to commit, and report exact `HEAD` SHA. Orchestrators inspect diffs (`worker_wip` / `git diff main...<branch>`) and integrate via `merge_worker`.

### Repository & instruction layout
- **Out-of-scope defects & changelogs**: log unrelated defects in `TODO.md` without fixing them unasked. Update `CHANGELOG.md` (Added / Fixed / Changed / Removed / Known tradeoff) by hand without internal paths or customer data; update an existing `architecture.md` after structural changes without creating one unasked.
- **Instruction files** (owner decision, 2026-10-17): keep root `AGENTS.md` below `16 KiB` with `CLAUDE.md` symlinked to `AGENTS.md`, placing conditional topic rules in `.orchestra/kb/rules-*.md` (never `.claude/rules/`). Record enduring owner decisions in the same turn (with date and verbatim quote in project rules, or `owner decision, <date>` with concise English summary inside `.orchestra/pipelines/**`).
</code-quality>
