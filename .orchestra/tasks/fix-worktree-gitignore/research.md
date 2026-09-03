# Research — worktree/spawn lifecycle bugs

## Question
Two reported bugs in Orchestra spawn/worktree lifecycle:
1. `inject_skills_to_worktree` leaves `.claude/skills/` untracked → `merge_worker` blocks on dirty tree.
2. spawn "session already exists" on archived workers — is the manager.py:404 fix complete?

## Findings

### Bug 1 — untracked `.claude/skills/` blocks merge — **CONFIRMED (for external repos only)**

Atomic claims:
- `inject_skills_to_worktree` copies skills to `worktree/.claude/skills/<name>/SKILL.md` — measured, `app/prompting.py:197-199`.
- `merge_worker`/`switch` reject on `git status --porcelain` non-empty output, which **includes untracked files** (`??`) — measured, `app/workspace.py:392-399`, `612-614`.
- Orchestra's **own** repo already ignores `.claude/` since the first MVP commit (`359b1fc`) — measured, `.gitignore:12`, `git check-ignore` confirms `.claude/skills/foo/SKILL.md` is ignored. → **Bug 1 does NOT reproduce in Orchestra's own repo.**
- BUT `create_worktree(repo_path, ...)` accepts an **arbitrary** `repo_path` (client projects). A repo without `.claude/` in its `.gitignore` → injected skills are untracked → merge blocked. → **Bug 1 IS real for external repos** (full-cycle role has skills `[codex-debate, self-analysis]`).

Confidence: **CONFIRMED** — direct code trace + `git check-ignore` measurement. The report's reproduce ("full-cycle worker → `.claude/skills/` untracked → merge fails") is accurate for any repo not already ignoring `.claude/`.

### Bug 2 — spawn "session already exists" on archived — **CONFIRMED BROKEN (report's own fix is dead code)**

The reported "fix already exists at manager.py:404" is **dead code that can never execute**:

Atomic claims:
- `existing = get_session_by_name(name, scope)` — `manager.py:396`.
- `get_session_by_name` query is `SELECT * FROM sessions WHERE name=? AND scope=? AND status != 'archived'` — measured, `db.py:610`. **It filters archived rows OUT.**
- Therefore `existing` is either a LIVE row or `None` — it can **never** be an archived row.
- The guard `if existing and existing.get("status") == "archived": delete_session(...)` at `manager.py:403-404` is **unreachable** — the condition is always False. The archived row is never deleted.
- The sessions table has `UNIQUE(name, scope)` — measured, `db.py:64`. INSERT (`db.py:495`) hits `IntegrityError` when an archived row with the same `(name, scope)` still exists.

→ kill_worker (archives) → spawn same name+scope → `get_session_by_name` returns None → the "already exists" guard passes → delete-archived guard is dead → INSERT → **IntegrityError**. Report's reproduce confirmed at root-cause level.

Confidence: **CONFIRMED** — code trace shows the branch is logically unreachable given the query filter.

#### Report's proposed fix is WRONG
Report suggests "DELETE ... WHERE name=? AND status='archived' WITHOUT scope filter (name globally unique for live agents)". This is incorrect:
- UNIQUE is on `(name, scope)`, NOT `name` alone (`db.py:64`). Name is **not** globally unique.
- Deleting archived rows across all scopes would clobber unrelated archived sessions in other scopes. Wrong.
- "same name + different scope" is a **non-issue**: different scope = no UNIQUE collision = INSERT succeeds. No fix needed there.

Correct fix: make the archived cleanup reachable by querying for the archived row explicitly (same name+scope), then delete it before INSERT.

## Affected files
- `app/manager.py` — `create_session` (~396-404): fix unreachable archived-delete.
- `app/db.py` — add a helper to fetch an archived row by (name, scope), OR delete-archived-by-name-scope directly.
- `app/workspace.py` — `create_worktree` (~172-192): ensure worktree `.gitignore` ignores `.claude/`.

## Risks / edge cases
- Bug 2 fix must stay **scoped** — only delete the archived row matching `(name, scope)`, never broaden to name-only.
- Bug 1 fix must be idempotent — don't duplicate `.claude/` if already present in a tracked `.gitignore`. Must not create a tracked/committable `.gitignore` change (would itself dirty the tree). Simplest: write/append to worktree-local `.gitignore` only if `.claude/` not already ignored (`git check-ignore`), or ignore via `.git/info/exclude` (untracked, per-worktree, never committed) — cleaner, no tree pollution.

## Sources
- All findings from direct source reads + `git check-ignore` / `git log` measurements this session. No external sources needed (internal code behavior).
