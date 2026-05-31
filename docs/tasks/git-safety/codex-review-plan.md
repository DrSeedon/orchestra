# Codex Review — plan.md (round 1)

Codex (GPT-5.5) reviewed `plan.md` against the actual code. Verdict: **proceed after tightening**.
None require a larger design. Findings below + my resolution.

## Findings

### F1 (suggestion): shared owned_dirs parser — malformed DB/MCP input
> owned_dirs is parsed in 4 places (MCP JSON string, API list, DB rehydrate, in-memory). A malformed
> DB value like `"app/api"` (bare string) or `[1]` (non-string) makes `normalize_owned_dirs` iterate
> characters or crash on `d.strip()`. Use ONE shared parser requiring a JSON list of strings,
> normalizing, returning `[]` on invalid input. Reuse for MCP, API, rehydrate, comparisons.

**Verified against code:** correct. `mcp_servers` is a JSON string in MCP, `owned_dirs` would be a
`list[str]` in the Pydantic API model but a raw string from MCP and from DB. Inconsistent types =
bug surface.
**Resolution: ADOPT.** Single helper `parse_owned_dirs(raw) -> list[str]` in `workspace.py`:
accepts `list | str | None`; if str → `json.loads` (guarded); require every item be a non-empty
str else skip; normalize (strip `/`, dedupe). Used everywhere. Drop the separate
`normalize_owned_dirs` — fold into this one parser.

### F2 (suggestion): auto-commit sketch still ignores git return codes
> The fix should fail loud, but the sketch ignores return codes from `git add -A` and `git commit`.
> If commit fails (identity/hooks/index lock/GPG), spawn continues and the warning falsely claims
> the WIP was committed. Check both subprocess results; either raise before create_worktree or
> return an explicit "failed to auto-save" warning without claiming a commit exists.

**Verified:** correct — current code (`manager.py:345-346`) and my sketch both ignore returncodes.
**Resolution: ADOPT.** Check `commit.returncode`. On failure → return warning
`"FAILED to auto-save dirty main repo (git commit rc=N: <stderr>) — spawn proceeds on dirty base"`
and do NOT claim success. Don't raise/block: spawn should still proceed (advisory philosophy),
but the orchestrator must see the truth. `git add` failure folds into the commit failure path.

### F3 (suggestion): branch_wip_status base_ref wrong for feature-branch workers
> Defaults to `refs/heads/main`, but workers can be spawned from `base_branch` and switch_worker_branch
> accepts `from_ref`. For a worker based on a feature branch, `main..HEAD` reports the feature
> branch's existing commits as worker WIP. Pass the branch base or let the endpoint accept base_ref.

**Verified:** correct. `create_worktree(..., base_branch)` and `switch_worktree_branch(from_ref)`.
**Resolution: ADOPT.** `branch_wip_status` already takes `base_ref` param. The `worker_wip` MCP tool
+ endpoint accept optional `base_ref` (default `refs/heads/main`) so the orchestrator can pass the
worker's actual base when it's a feature branch. Document default clearly. Keeping it a param (not
auto-derived) matches the simple/flat philosophy — orchestrator knows the base it spawned from.

### F4 (suggestion): simulate_conflict — missing branch vs unrelated histories ambiguity
> Sketch only runs merge-base; a missing branch and genuinely unrelated histories both become
> "unrelated histories". Add `git rev-parse --verify <branch>^{commit}` (or show-ref) before
> merge-base, then keep the merge-tree parsing.

**Verified:** correct — misleading tool output, not a git-state risk.
**Resolution: ADOPT.** Verify both refs with `git rev-parse --verify <ref>^{commit}` first →
`{"ok": False, "error": "branch '<x>' not found"}` if missing; only then merge-base/merge-tree.

### F5 (question): WIP commit text hard-codes "main"
> create_session supports base_branch; the repo checkout can be on a feature branch when
> _auto_commit_if_dirty(repo_path) runs. Should the warning say "source repo checkout" / include
> the actual current branch instead of "main"?

**Verified:** valid. `repo_path` HEAD may not be `main`.
**Resolution: ADOPT (minor).** Change wording from "on the main repo" → "in the source repo
checkout" and include the actual current branch name (cheap `git symbolic-ref --short HEAD`).
Avoids a false "main" claim.

## Summary of changes to plan
All 5 are suggestions (no blocking). Adopting all:
1. One `parse_owned_dirs` helper for every entry point (replaces `normalize_owned_dirs`).
2. `_auto_commit_if_dirty` checks returncode, never falsely claims commit.
3. `worker_wip` / `branch_wip_status` accept `base_ref` param.
4. `simulate_conflict` verifies refs exist before merge-base.
5. Auto-commit message says "source repo checkout" + actual branch, not "main".

No re-run needed — all findings are localized wording/robustness tweaks, no design change.
