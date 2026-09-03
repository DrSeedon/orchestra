# Git Workflow Research — Multi-Agent Orchestration (Orchestra)

> Research doc. Date: 2026-05-31. Covers worktree isolation, merge strategies, branch
> lifetime, conflict prevention, multi-worker coordination, industry patterns, and a
> concrete implementation plan for Orchestra's `workspace.py` / `manager.py`.

---

## 1. Current Orchestra Approach (as built)

### 1.1 Worktree creation — `app/workspace.py::create_worktree`
- One **git worktree per worker session**, rooted at `worktrees/<scope-slug>/<name>/`.
- Branch naming:
  - With `task_id` → `task-<N>/<name>` (e.g. `task-49/backend-opus`)
  - Without `task_id` → `feat/<scope-slug>/<name>`
- Branched from `base_branch` (default `main`) via `git worktree add <path> -b <branch> <base>`.
- Existing branch is **reused** (`git worktree add <path> <branch>` без `-b`) if not checked out elsewhere; `_is_branch_checked_out_elsewhere` guards the "one checkout per named branch" git rule.
- Branch name validated via `git check-ref-format`.
- Project files (`CLAUDE.md`, `.worktreeinclude`, `.mcp.json`, `.env`) are **copied** into the worktree at creation (falls back to `repo.parent` if not in repo root). This is Orchestra's equivalent of Claude Code's `.worktreeinclude` propagation.
- Skills injected into `<worktree>/.claude/skills/` (`manager.py::_inject_skills_to_worktree`).

### 1.2 Spawn flow — `app/manager.py::create_session`
- Before creating the worktree: `_auto_commit_if_dirty(repo_path)` — auto-commits the **main repo's** dirty tree with `wip: auto-save before worker spawn`. (Prevents the new worktree from branching off uncommitted state, but silently buries user WIP into a commit.)
- `base_branch` is threaded through from the spawn MCP tool.

### 1.3 Merge — `app/workspace.py::merge_worktree_to_main` (via MCP `merge_worker`)
A heavily-guarded sequential merge under a **global file lock** (`.git/orchestra-merge.lock`, `fcntl.LOCK_EX`). Steps:
1. Save orchestrator's current branch (restore in `finally`).
2. Reject if worker tree is **dirty** (`git status --porcelain`).
3. Verify `target_branch` exists and is not checked out elsewhere.
4. `_ensure_repo_on_branch`: stash main repo if dirty, checkout target.
5. `git merge-base target branch` → if it fails, histories are **unrelated** → fall back to `_cherry_pick_branch` (replays every commit via `cherry-pick --no-commit`).
6. Otherwise **pre-check** with `git merge-tree --write-tree target branch` → returns conflict file list without touching the tree.
7. If clean: `git merge --no-edit branch` (a **merge commit / fast-forward**, NOT squash).
8. `_parse_merged_commits` extracts task refs (`#N`, `PREFIX-N`) + numstat for task linking.
9. `finally`: restore orchestrator branch **then** `stash pop` (order is critical — documented in code).

### 1.4 Branch switch — `switch_worktree_branch` (via MCP `switch_worker_branch`)
- Lets a worker move to a new task branch **after merge**, from `from_ref` (default `refs/heads/main`; feature workers pass `refs/heads/feature/<...>`).
- Requires clean tree + current branch fully merged into `from_ref` (`merge-base --is-ancestor`).
- Merges `from_ref` into the new/existing branch (auto-sync at switch time).

### 1.5 Removal — `remove_worktree`
- `git worktree remove --force`, with logic to resolve the correct parent repo from the `.git` gitdir pointer.

### Summary of Orchestra's current position vs industry
| Dimension | Orchestra today | Industry default |
|---|---|---|
| Isolation | git worktree per worker | ✅ git worktree per agent (Cursor, Claude Code, Codex, uzi, claude-squad) |
| Branch | per-task (`task-N/name`) or per-worker (`feat/...`) | ✅ short-lived per-task |
| Merge | **merge commit / ff** (`git merge --no-edit`) | ⚠️ industry leans **squash-merge** for noisy agent commits |
| Pre-merge check | ✅ `merge-tree --write-tree` | ✅ same primitive (Clash tool) |
| Merge serialization | ✅ global `fcntl` lock | ✅ serialized merges |
| Unrelated histories | ✅ cherry-pick fallback | — (Orchestra-specific, see §3 problem 1) |
| Auto-sync during work | ❌ none (only at switch) | ✅ matches consensus (no mid-work rebase) |
| File-level locking | ❌ none | ⚠️ `.ai/locks/` pattern exists but not universal |

Orchestra is **already close to industry best practice**. The main gaps are merge strategy (merge vs squash), the nested-repo footgun, and the lack of structural conflict prevention for parallel workers on the same repo.

---

## 2. Problems Found

1. **Nested git repos → unrelated histories.** A worktree is created from the parent repo, but the worker edits files inside a *child* repo that has its own `.git` (not a submodule). Commits land in the child's history; `merge-base` against `main` fails; the cherry-pick fallback fires and replays "unrelated" commits — often producing duplicate or empty commits. Root cause: **the worktree boundary and the edit boundary don't match.**
2. **Multiple workers on the same repo → merge conflicts.** No directory ownership or file locking; two workers can edit the same file and only discover it at merge time.
3. **Long-lived per-worker branches diverge from main.** The `feat/<scope>/<name>` naming encourages a worker branch that accumulates many tasks and drifts.
4. **Orchestrator commits to main while workers are active.** `_auto_commit_if_dirty` buries user WIP; workers branched from an earlier main then face a moving target with no auto-sync until merge/switch.

---

## 3. Strategy Analysis

### 3.1 Worktree isolation patterns (Topic 1, 2, 7 from research)

**Three primitives:**
| Approach | Disk | Create speed | Process isolation | Nested-git safety |
|---|---|---|---|---|
| **git worktree** (current) | shared object store, only working files duped | near-instant | none (shared ports/env/DB) | **siblings only — NOT nested** |
| separate clone | full dupe | minutes | none | full |
| container (Docker/Dagger) | full dupe | seconds–min | full | full |
| container + worktree (`container-use`) | full dupe | medium | full | full |

**Industry**: worktree-per-agent is the convergent default — Cursor 2.0 (up to 8 parallel), Claude Code (`--worktree`, `.claude/worktrees/`), OpenAI Codex (detached-HEAD background worktrees), uzi, claude-squad, crystal. Containers are used where **process** isolation matters (OpenHands, Devin, SWE-Agent run in Docker; ports/DBs/untrusted code).

**Nested git repos (the Orchestra problem 1):**
- If a dir inside the repo has its own `.git`, git treats it as **opaque** — invisible to outer history, skipped by `git add .`. Worktree boundaries (`.git` file pointer) are not respected by some tooling.
- Submodule + worktree is officially **experimental** in git; `submodule.*` / `core.worktree` config is shared across worktrees and breaks. Known bug: Claude Code #27201 (worktree from inside submodule targets the outer repo).

**Recommendation for sub-repos:**
- **Detect** a nested `.git` inside the intended edit path at spawn time and **fail loud** (or pick the correct `repo_path`).
- If the child repo is a genuine separate project the worker must edit → spawn the worker with `repo_path` = the **child** repo, so the worktree is created from the right repo and `merge-base` works.
- Do **not** rely on the cherry-pick "unrelated histories" fallback as a feature — it's a symptom. Keep it as a last resort but warn.
- If the relationship should be tracked → convert to a real **git submodule** (and keep worktrees on the outer repo only, never operate worktree commands inside the submodule), or **git subtree** (avoids the dual-repo model entirely — single history, no `.gitmodules`), or fold into a **monorepo**.

**Monorepo note**: monorepos are *favorable* for multi-agent work (full cross-package context, atomic changes). If sub-repos are really one product, folding them into one repo + directory-ownership per worker is the cleanest fix.

### 3.2 Merge strategies (Topic 3)

The core problem: agent commits are noisy (`wip`, `try A`, `revert`, `fix typo`). Orchestra already sees this — `_auto_commit_if_dirty` literally creates `wip:` commits.

| Strategy | Pros | Cons | Fit for Orchestra |
|---|---|---|---|
| **Squash** `merge --squash` | one clean commit per task on main; trivial `bisect`; hides agent noise | loses per-step history | **Recommended default.** Matches the per-task branch model and `#N` task linking (one commit ↔ one task). |
| **Merge commit** `merge --no-ff` (current) | full audit trail; explicit merge point | clutters main with WIP; ugly `log`/`bisect` | keep as opt-in for audit |
| Rebase | linear history | rewrites SHAs; WIP still lands unless cleaned | only with interactive cleanup — too fiddly for automation |
| Cherry-pick | pick specific good commits | manual | ensemble/"pick best of N" pattern; already the unrelated-history fallback |

**Industry consensus = squash.** The git-native maker-checker pattern explicitly squashes "dozens of broken AI trial-and-error commits into one clean commit." Azure DevOps / GitHub default agent integrations to squash.

**Caveat for Orchestra:** `_parse_merged_commits` walks `old_head..HEAD` and parses `#N` from each commit to link tasks. Squash collapses to **one** commit — the squash commit message must carry the task ref(s). This is *easier*, not harder: one squash commit = one `#N`. Implementation must set the squash commit message to include the task ref.

**Hybrid (optional):** keep the full worker branch (don't delete it, or push to a `refs/agents/` namespace) for audit, while main gets the clean squash. Best of both.

### 3.3 Branch lifetime (Topic 4)

- **Short-lived per-task is the consensus** (every tool: uzi, claude-squad, Composio, open-swe, Cursor, Claude Code). Branch = task identifier; merge/squash; delete branch + worktree.
- **Long-lived per-worker = anti-pattern** except a narrowly-scoped worker that never conflicts (e.g. a docs-only agent).
- **Orchestra implication:** prefer the `task-N/<name>` naming; treat `feat/<scope>/<name>` (no task) as ephemeral and short. `switch_worker_branch` already implements the "merge then move to next task" lifecycle — keep it, make per-task the norm.
- **Rebase onto main as main moves:** only at task boundaries (before merge / at switch), **never mid-work** (SHA churn disorients the agent). Orchestra's `switch_worktree_branch` already merges `from_ref` at switch time — correct.

### 3.4 Conflict prevention (Topic 5)

Three-layer model:
1. **Pre-flight detection** — `git merge-tree --write-tree A B` simulates a merge with no working-tree changes. Orchestra **already does this** in `merge_worktree_to_main`. Extend it: before *dispatching* two workers, the orchestrator can simulate their branches against each other.
2. **Directory/file ownership** — assign each worker an explicit owned-dir list and forbidden-dir list. Structural impossibility > detection. (Claude Code agent-teams use `.ai/locks/`; Composio uses dir-scoped tasks.)
3. **Serialized merge** — never merge two branches simultaneously; merge one, rebase the rest. Orchestra **already serializes** via the global `fcntl` lock. ✅

### 3.5 Multi-worker coordination — same file (Topic 6)

Ranked options:
1. **Prevent structurally** — partition tasks so no two workers touch the same file (best).
2. **File-level lock** — `.ai/locks/<file>.lock` with agent id + expiry (crash-safe).
3. **Pessimistic / serialize** — orchestrator delays task B until task A merges if they overlap.
4. **Optimistic + resolve at merge** — work freely, detect via `merge-tree`, have an agent resolve.
5. **Shared files owned by main** — config/`.env`/interfaces copied into worktrees read-only at creation (Orchestra already copies `PROJECT_FILES`; make clear these are read-only and shouldn't be merged back).

Published patterns: **pipeline** (B branches off A's branch), **ensemble** (N solve same task, pick best via cherry-pick), **maker-checker** (maker writes, checker reviews same branch, squash final).

### 3.6 Auto-sync (Topic 7)

**Consensus: sync only at merge boundary, not during work.** Mid-work rebase invalidates the agent's context and causes tool disorientation. Orchestra matches this (sync happens at `switch_worker_branch`, not during a task). The one recommended exception: if a **shared dependency file** (`pyproject.toml`, `package.json`) changes on main during a long task, push that single file into active worktrees — but Orchestra only does this at creation, not on drift. Low priority.

---

## 4. Industry Patterns Reference (concrete mechanisms)

| Tool | Isolation | Merge | Notable |
|---|---|---|---|
| **Devin** | VM per session | branch → non-draft PR, fixup commits | GitHub App perms; branch-protection aware |
| **SWE-Agent** | Docker, clone | **patch, not commit** (`git diff` → `git apply`) | research/eval design |
| **OpenHands** | swappable Local/Docker/Remote workspace | git inside container; opens PR | append-only EventLog, replayable |
| **Copilot Coding Agent** | cloud | issue → branch → draft PR → human merge | sunset Workspace, GA Sep 2025 |
| **OpenAI Codex** | **git worktree, detached HEAD** | user reviews/merges | managed (15 kept) + permanent worktrees |
| **Cursor 2.0** | worktree + branch, temp dir | `/apply-worktree` merges back | up to 8 parallel; `.cursor/worktrees.json` setup hooks |
| **Claude Code** | `.claude/worktrees/<n>`, `worktree-<n>` | prompt keep/remove; no auto-resolve | `.worktreeinclude` for secrets; subagent `isolation: worktree` |
| **LangChain open-swe** | per-thread branch `openswe-{thread_id}` | commit + draft PR; safety-net middleware | PR-comment routing via `@openswe` |
| **uzi** | worktree + tmux, per-agent port range | `uzi checkpoint` = commit + rebase | Go CLI |
| **claude-squad** | worktree per agent | manual review → merge, auto-cleanup | Go TUI |
| **Composio orchestrator** | worktree + branch + own PR | sequential PR merges, **auto-rebase on conflict** (15-min → human) | most complete automation |
| **container-use (Dagger)** | container + worktree | review → merge | process isolation on top of file isolation |

Key takeaways for Orchestra:
- The **worktree-per-agent + serialized merge** core is industry-standard and Orchestra has it.
- **Squash** is the prevailing merge for noisy agent commits — Orchestra's biggest divergence.
- **Detached HEAD** (Codex) is an alternative to Orchestra's "one checkout per named branch" guard — Orchestra's guard is fine.
- **Pre-merge `merge-tree`** (Clash) — Orchestra already has it.
- **Process isolation** (containers) — only needed if Orchestra runs untrusted code or needs port/DB isolation; not required for current trusted use.

---

## 5. Recommended Approach for Orchestra

**Keep** (already best-practice): worktree-per-worker, per-task branch naming, serialized `fcntl` merge lock, `merge-tree` pre-check, no mid-work auto-sync, `switch_worker_branch` lifecycle, project-file propagation.

**Change:**
1. **Default merge = squash** (with merge-commit as opt-in). Carry task ref into the squash message so `_parse_merged_commits` still links `#N`. *(Highest value, lowest risk.)*
2. **Nested-repo guard at spawn**: detect a `.git` inside the worker's edit path that differs from `repo_path`'s git dir → fail loud with a clear message, or auto-correct `repo_path` to the child repo. Stop the unrelated-history → cherry-pick path from being the silent norm.
3. **Directory ownership (optional, for parallel-on-same-repo)**: let a spawn declare `owned_dirs` / `forbidden_dirs`; surface in the worker prompt; optionally enforce a pre-merge check that a worker only changed files in its owned set.
4. **Pre-dispatch conflict simulation (optional)**: before spawning a 2nd worker on the same repo, run `merge-tree` between the two intended branches; warn the orchestrator if they'd collide.
5. **Make `_auto_commit_if_dirty` less destructive**: instead of a buried `wip:` commit, prefer a clearly-labelled commit or warn the orchestrator that user WIP exists. (Low priority, but it surprises users.)

**Skip** (not needed now): containers/process isolation (trusted code), mid-work auto-rebase (consensus says don't), submodule worktree operations (experimental).

---

## 6. Implementation Plan

### 6.1 Squash merge (Change 1) — `app/workspace.py`
- `merge_worktree_to_main`: add a `strategy` param (`"squash" | "merge"`, default `"squash"`).
- Squash path:
  - Compute commit count `git rev-list --count target..branch` (already done) and capture task refs from the branch's commit messages (reuse `_TASK_REF_RE` over `git log target..branch`).
  - `git merge --squash branch` then `git commit -m "<aggregated message with #N refs>"`. Build the message from the branch's commits (e.g. first line + collected `#N`).
  - For `_parse_merged_commits`: it walks `old_head..HEAD`; after squash there's exactly one commit carrying the refs — works unchanged as long as the squash message includes `#N`.
- Keep the **unrelated-histories cherry-pick** fallback and the **merge-commit** path behind `strategy="merge"`.
- Plumb `strategy` through `mcp_stdio.py::merge_worker` (new optional arg, default squash) and the `/api/sessions/{name}/merge` endpoint.

### 6.2 Nested-repo guard (Change 2) — `app/workspace.py::create_worktree` (+ `manager.py`)
- After resolving `repo`, before `git worktree add`: walk the repo for a **nested `.git`** that doesn't belong to `repo` (e.g. `git -C <repo> rev-parse --git-common-dir` vs a `.git` found in a subdir). If the worker's task targets that subdir, raise `ValueError("nested git repo detected at <path> — spawn with repo_path=<that path> instead")`.
- Lighter version: at **merge** time, when `merge-base` fails (unrelated histories), do **not** silently cherry-pick — return a structured warning `{"ok": False, "state": "unrelated_histories", "hint": "worker likely edited a nested repo; check repo_path"}` and require an explicit opt-in flag to use the cherry-pick fallback.

### 6.3 Directory ownership (Change 3, optional) — `manager.py` + `workspace.py`
- `create_session` / spawn tool: accept `owned_dirs: list[str]`.
- Inject into the worker system prompt ("you may only edit files under: …").
- Pre-merge enforcement in `merge_worktree_to_main`: `git diff --name-only target..branch`; if any path is outside `owned_dirs`, return `{"ok": False, "state": "ownership_violation", "files": [...]}`.

### 6.4 Pre-dispatch conflict sim (Change 4, optional) — `manager.py`
- Helper `simulate_conflict(repo, branch_a, branch_b) -> list[str]` using `git merge-tree --write-tree branch_a branch_b` (same parsing as the existing pre-check).
- Orchestrator can call it before spawning a second worker on the same repo.

### 6.5 Safer auto-commit (Change 5, low priority) — `manager.py::_auto_commit_if_dirty`
- Replace silent `wip: auto-save before worker spawn` with either: (a) a stash that's reported back, or (b) a commit whose message flags it as user WIP, and surface a note to the orchestrator so it isn't buried.

### Touch list
- `app/workspace.py` — squash path, nested-repo guard, ownership check, conflict-sim helper.
- `app/manager.py` — `owned_dirs` plumbing, safer auto-commit, optional pre-dispatch sim.
- `app/mcp_stdio.py` — `merge_worker(strategy=...)`, optional `spawn_worker(owned_dirs=...)`.
- API endpoints `/api/sessions/{name}/merge` (+ spawn) — pass new params.

### Suggested order
1. **Squash merge** (biggest win, contained).
2. **Nested-repo guard** (kills problem 1 at the source).
3. Ownership + pre-dispatch sim (parallel-on-same-repo safety).
4. Safer auto-commit (polish).

---

## 7. Sources
Devin GitHub docs · SWE-Agent (Princeton, GitHub + paper) · OpenHands runtime arch + arxiv 2511.03690 · GitHub Copilot Coding Agent blog/docs · OpenAI Codex Worktrees docs · Cursor Worktrees docs · Claude Code Worktrees docs · LangChain open-swe · uzi · claude-squad · Composio agent-orchestrator (architecture-design.md) · container-use (Dagger, InfoQ) · Clash conflict-detection tool (HN) · git-native maker-checker squash gist (szkiba) · Addy Osmani "Code Agent Orchestra" · Claude Code Agent Teams · git worktree official docs · Claude Code issue #27201 (submodule boundary) · Azure DevOps squash-merge docs.
