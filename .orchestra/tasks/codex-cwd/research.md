# Research — codex_review runs in main repo instead of worker's worktree

## Question
Why does the `codex_review` MCP tool run `codex` CLI with cwd = MAIN repo instead of
the calling worker's git worktree? (Bug reported twice in BUGS.md, reproduces stably.)

## Root cause — CONFIRMED

The bug is **not** in the command construction, and **not** in bg_jobs CWD inheritance.
The `codex_review` tool already:
- resolves the worker's dir via `GET /api/sessions/{WORKER_NAME}` (`mcp_stdio.py:683-686`)
- prepends `cd {cwd} && ...` to the codex command (`mcp_stdio.py:700`, `:717`)

The real defect: **`AgentSession.to_dict()` does not include `worktree_path` or `cwd`.**

`mcp_stdio.py:686`:
```python
cwd = info.get("worktree_path") or info.get("cwd") or info.get("scope", SCOPE)
```

`GET /api/sessions/{name}` (`routes/sessions.py:130-136`):
```python
return found.to_dict() if found.loaded else found.db_row
```

- **Loaded session** (worker actively running → the normal case when it calls codex_review):
  `to_dict()` (`session.py:1037-1064`) has **neither** `worktree_path` **nor** `cwd`.
  → both `.get()` return `None` → falls back to `info.get("scope")`.
  `scope` = the MAIN repo path (from `spawn_worker`: `scope = SCOPE or repo_path`, where
  SCOPE is the repo root, not the worktree). **→ codex `cd`s into the main repo.** BUG.
- **Detached session** (hydrated from DB): returns `db_row`, which via `_to_db_dict`
  (`session.py:1007`) **does** carry `worktree_path`. → works correctly.

So the bug manifests exactly when the worker is loaded — i.e. always, for a live worker
calling the tool. This matches the "reproduces stably" report.

### Verification trail (source-level)
- `session.py:111` — `worktree_path: str | None` is a real session field, set at spawn
  (`manager.py:541`), persisted to DB (`_to_db_dict` `session.py:1007`, schema `db.py:56`).
- `to_dict()` `session.py:1037-1064` — enumerated every key; `worktree_path`/`cwd` absent.
- `_hydrate_row` `manager.py:769` — detached row carries `worktree_path` → confirms the
  detached path works, isolating the defect to `to_dict()`.

Confidence: **CONFIRMED** (single deterministic code path, no runtime ambiguity).

## Secondary bug — codex timeout on large diffs (LIKELY)
`mcp_stdio.py:732` sets `timeout_seconds: 300` (5 min) for the bg run job, and the tool's
return text advertises "5-min timeout". Large diffs can exceed this. Task says: raise if
possible. Low-risk change — bump to 600s (10 min). No downside for small diffs (job ends
on process exit, timeout is only the kill ceiling).

## Fix (minimal, surgical)
Add `worktree_path` and `cwd` to `AgentSession.to_dict()` (`session.py:1037`). One-field
data addition; `codex_review` already reads them. No change to bg_jobs, no cd-injection
change needed.

Optionally bump `codex_review` bg-job timeout 300 → 600 and update the advertised text.

## Affected files
- `app/session.py` — `to_dict()` add `worktree_path`, `cwd` (the fix)
- `app/mcp_stdio.py` — timeout 300→600 + return-text wording (secondary)

## Risks / edge cases
- `to_dict()` is also consumed by the dashboard (`GET /api/sessions`, `sessions.py:116`)
  and TG. Adding two keys is additive — no consumer breaks on extra keys. Verified
  `to_dict()` is only ever read as a dict / serialized to JSON.
- Orchestrators have `worktree_path = None` (no worktree) → `codex_review` falls back to
  `cwd` (their real repo dir), which is correct. `cwd` is now also exposed, so the fallback
  chain `worktree_path → cwd → scope` finally works as originally intended.
- No worktree case (worker spawned with `use_worktree=False`): `worktree_path` is None,
  `cwd` = repo → correct.

## Not doing
- No change to `bg_jobs._run_exec` — its CWD inheritance is irrelevant since the command
  string does its own `cd`. Touching it would be scope creep.
- No new endpoint — the existing `GET /api/sessions/{name}` is the right source once
  `to_dict()` is complete.
