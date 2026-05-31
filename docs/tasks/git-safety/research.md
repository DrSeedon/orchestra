# Research: Directory Ownership + Pre-dispatch + Safe Auto-commit

Task: implement git-safety roadmap items priority 3 (directory ownership), 4 (pre-dispatch
conflict sim), 5 (safer auto-commit). Priorities 1 (squash merge) and 2 (nested-repo guard)
are out of scope here — squash is **already implemented** (see below).

## Current architecture (what exists now)

### Spawn flow
1. Orchestrator calls MCP `spawn_worker(name, task, repo_path, model, system_prompt, task_id, description, base_branch, role, mcp_servers)` — `app/mcp_stdio.py:55`.
2. → `POST /api/sessions` with `CreateSessionRequest` (`app/main.py:91`, endpoint `:366`).
3. → `manager.create_session(...)` (`app/manager.py:351`).
   - `_auto_commit_if_dirty(repo_path)` runs FIRST (`:340`, called `:416`): if main repo dirty → `git add -A` + `git commit -m "wip: auto-save before worker spawn"`. **Silent, buries user WIP.**
   - `create_worktree(...)` (`app/workspace.py:50`) creates the worktree + branch `task-N/<name>` or `feat/<scope>/<name>`.
   - Worker `system_prompt` is built by role + appended custom prompt, then `_safe_format_prompt` injects `worker_name/orchestrator_name/scope/branch`.
4. Session persisted via `save_session` (`app/db.py:385`).

### DB schema (sessions table — `app/db.py:41`)
- Columns added incrementally via `ALTER TABLE` guards (`:239`+). Pattern: check `if "<col>" not in cols` then `ALTER TABLE sessions ADD COLUMN ...`.
- Relevant existing JSON-in-TEXT precedent: `mcp_servers_custom TEXT DEFAULT ''` — stored as `json.dumps(...)` in `AgentSession._to_db_dict` (`app/session.py:760`), parsed back via `_parse_custom_mcp` on rehydrate (`app/manager.py:562`).
- `save_session` uses one big INSERT … ON CONFLICT(id) DO UPDATE with named params; every column must appear in setdefault + INSERT + UPDATE.

### AgentSession model (`app/session.py:59`)
- `@dataclass`. Fields: `task_id`, `description`, `mcp_servers_custom`, etc.
- `_to_db_dict` (`:737`) — what gets persisted. `to_dict` (`:766`) — what API/dashboard sees.
- Rehydrate path constructs `AgentSession(...)` in `manager.py:563`.

### Merge flow (`app/workspace.py:251` merge_worktree_to_main)
- Global `fcntl` lock on `.git/orchestra-merge.lock`.
- Rejects dirty worktree (`:283`).
- **Squash already implemented** (`:345` `git merge --squash`), `_build_squash_message` aggregates `#N` refs. Priority 1 from roadmap = DONE.
- **Pre-merge conflict precheck already exists** (`:307`): `git merge-tree --write-tree target branch`, parses `CONFLICT` lines → returns `{"ok": False, "conflicts": [...]}`. This is the exact primitive we reuse for pre-dispatch sim.
- Unrelated histories → `_cherry_pick_branch` fallback.

### switch_worker_branch flow
- MCP `switch_worker_branch(name, task_id, from_ref)` (`mcp_stdio.py:325`) → `POST /api/sessions/{name}/switch-branch` (`main.py:728`) → `switch_worktree_branch(worktree_path, new_branch, from_ref)` (`workspace.py:476`).
- Rejects dirty worktree (`:485`) and unmerged commits (`:488` — `merge-base --is-ancestor HEAD from_ref`).
- So switching **requires the worker to have committed first**. The "WIP commit" is done **by the worker itself** via `git commit -m "WIP: #192"` (prompted in `orchestrator.md:129`), NOT by Orchestra code.

### Orchestrator prompt (`app/prompts/roles/orchestrator.md`)
- `<parallel-tasks>` (`:215`): current rule is purely advisory — "same files → one worker sequential". No tooling backs it.
- Worker lifecycle examples (`:105`+) show `WIP: #192` commits done manually by the worker.

## Key finding: the task mixes TWO different "auto-commit" things

The task §3 ("Safer auto-commit") conflates two unrelated mechanisms:

1. **`_auto_commit_if_dirty(repo_path)`** — Orchestra code, commits the **main repo** before spawn. This is the roadmap's priority-5 "make `_auto_commit_if_dirty` less destructive". It's real, silent, and buries user WIP. **This is the one to fix in code.**
2. **Worker `WIP: #task-id` commits** — done by the worker (LLM) following the prompt, inside its own worktree, before `switch_worker_branch`. There is **no Orchestra code** doing this. Making these "explicit with full description" + "show WIP on resume" is a **prompt change**, not a code change — we can improve `orchestrator.md`/`worker.md` wording, but Orchestra can't force the LLM's commit message format.

→ Plan will treat §3 as: (a) fix `_auto_commit_if_dirty` to be non-destructive/loud (code), and (b) tighten the WIP-commit prompt guidance + add a "WIP summary on resume" helper that surfaces uncommitted/unmerged state when an orchestrator resumes a branch (code surfacing + prompt).

## Files that will be affected
- `app/db.py` — add `owned_dirs TEXT DEFAULT ''` column + ALTER guard; thread through `save_session` setdefault/INSERT/UPDATE.
- `app/session.py` — add `owned_dirs: str = ""` (or `list`) field to `AgentSession`; `_to_db_dict`; optionally `to_dict`.
- `app/main.py` — `CreateSessionRequest.owned_dirs`; pass to `create_session`.
- `app/manager.py` — `create_session(owned_dirs=...)`: ownership-conflict precheck vs other live workers; inject into system prompt; persist. Rehydrate path. Safer `_auto_commit_if_dirty`. Pre-dispatch file-overlap check.
- `app/workspace.py` — pre-dispatch helper: which files changed in main since branch point (`git diff --name-only <merge-base>..main`), + `simulate_conflict` reusing merge-tree.
- `app/mcp_stdio.py` — `spawn_worker(owned_dirs=...)`; surface ownership warning in return string.
- `app/prompts/roles/orchestrator.md` + `worker.md` — owned_dirs in spawn docs, parallel-tasks section, explicit WIP commit format.

## Risks & edge cases
- **owned_dirs storage**: JSON-in-TEXT (precedent: `mcp_servers_custom`). Empty default `''` not `'[]'` to match column-add pattern; parse with guard.
- **Ownership conflict = warning, not block.** Task says "предупреждение оркестратору" — spawn must still succeed, return advisory text. Don't fail loud here (intentional design: orchestrator decides).
- **Path normalization**: `owned_dirs: ["app/api/", "app/api"]` must compare equal. Normalize (strip trailing `/`, relative to repo root). Overlap check = prefix match on normalized paths.
- **Which workers count as "owners"**: only running/idle (not archived) in the same scope/repo. Need to read from `manager.sessions` (live) — DB rows for archived are excluded.
- **Pre-dispatch file-overlap** needs the worker's branch point. At spawn the branch doesn't exist yet → compare `owned_dirs` of the NEW worker against `owned_dirs` of EXISTING workers (static overlap), AND optionally what changed in main vs each existing worker's branch base. Keep it simple: static owned_dirs overlap is the 80% win.
- **`simulate_conflict`** requires both branches to exist. Only usable AFTER both workers committed — useful as an orchestrator pre-merge tool, less so pre-spawn. Document accordingly.
- **`_auto_commit_if_dirty` fix**: switching to stash could surprise (stash pop later?). Safer minimal fix: keep committing but with a loud, dated, clearly-labelled message AND return a flag so the spawn result can warn the orchestrator. Avoid stash (no clean pop point in spawn flow).
- **Concurrent spawns**: two orchestrator spawns racing on same repo — ownership check reads live sessions; minor TOCTOU but advisory-only so harmless.
- **Rehydrate**: must default `owned_dirs` for old rows (no column) — ALTER with DEFAULT '' handles it; `.get("owned_dirs", "")`.

## External references
- Roadmap source: `docs/tasks/git-workflow-research.md` §5 (changes 3/4/5) + §6.3/6.4/6.5. This task = direct implementation of those.
- Design doc: `docs/research/git-branching-design.md` — principle "Fail loud, no hidden auto-commit" (§3, :34).
- `git merge-tree --write-tree` precedent already in `workspace.py:307`.
