# Plan: Directory Ownership + Pre-dispatch + Safe Auto-commit

Implements git-safety roadmap priorities 3, 4, 5. (1 squash + 2 nested-guard out of scope —
squash already done.) Philosophy: minimal surgical changes, advisory-not-blocking for ownership,
fail-loud for the silent auto-commit.

---

## Feature 1: Directory ownership at spawn (priority 3)

### 1a. DB column
`app/db.py`:
- Add to schema block (`CREATE TABLE sessions`, ~`:55`) — not strictly required for fresh DBs but keep consistent; the ALTER guard is the real migration:
- In the migration section (~`:382`, after `parent_name` guard):
  ```python
  if "owned_dirs" not in cols:
      c.execute("ALTER TABLE sessions ADD COLUMN owned_dirs TEXT DEFAULT ''")
  ```
- `save_session` (`:385`): add `s.setdefault("owned_dirs", "")`; add `owned_dirs` to INSERT column list, VALUES (`:owned_dirs`), and ON CONFLICT UPDATE set `owned_dirs=excluded.owned_dirs`.

### 1b. AgentSession field
`app/session.py`:
- Add field after `description` (`:83`): `owned_dirs: list = field(default_factory=list, repr=False)`.
- `_to_db_dict` (`:737`): `"owned_dirs": json.dumps(self.owned_dirs) if self.owned_dirs else "",`
- `to_dict` (`:766`): `"owned_dirs": self.owned_dirs,` (so dashboard/get_worker_info can show it).

### 1c. Shared parser + overlap helper  *(Codex F1)*
`app/workspace.py` — ONE shared parser used by MCP, API, rehydrate, comparisons. Accepts
`list | str | None`; tolerates malformed DB/MCP input → `[]`:
```python
def parse_owned_dirs(raw) -> list[str]:
    """Normalize owned_dirs from any source (JSON string, list, None). Bad input → []."""
    if not raw:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return []
    if not isinstance(raw, list):
        return []
    out = []
    for d in raw:
        if not isinstance(d, str):
            continue
        p = d.strip().strip("/")
        if p and p not in out:
            out.append(p)
    return out

def dirs_overlap(a: list[str], b: list[str]) -> list[str]:
    """Return list of overlapping dir-pairs as strings 'x ∩ y' (prefix-aware)."""
    hits = []
    for x in a:
        for y in b:
            if x == y or x.startswith(y + "/") or y.startswith(x + "/"):
                hits.append(x if len(x) >= len(y) else y)
    return sorted(set(hits))
```
Prefix-aware so `app/api` conflicts with `app/api/v1`.

### 1d. create_session plumbing
`app/manager.py::create_session` (`:351`):
- Signature: add `owned_dirs: list | None = None`.
- Early: `owned_dirs = parse_owned_dirs(owned_dirs)`.
- **Ownership conflict check (advisory)** — before building session, scan live sessions:
  ```python
  ownership_warning = ""
  if owned_dirs:
      conflicts = []
      for s in self.sessions.values():
          if s.scope == scope and s.status.value in ("idle", "running") and s.owned_dirs:
              ov = dirs_overlap(owned_dirs, s.owned_dirs)
              if ov:
                  conflicts.append((s.name, ov))
      if conflicts:
          ownership_warning = "; ".join(f"{n} owns {ov}" for n, ov in conflicts)
          logger.warning(f"owned_dirs overlap for new worker '{name}': {ownership_warning}")
  ```
- Set `session.owned_dirs = owned_dirs` on the AgentSession constructor (`:395`).
- **Inject into worker system_prompt** — only for non-orchestrator, after role prompt is built (near `:373`). Append a deterministic block:
  ```
  \n\n## Directory ownership
  You OWN these directories — edit ONLY files under them:
  - app/api/
  - app/models/
  Do NOT touch files outside your owned directories. If the task requires it — STOP and ask the orchestrator.
  ```
  Build via a small helper `_ownership_prompt(owned_dirs) -> str` in manager.py (returns "" if empty).
- Return value: `create_session` returns the `AgentSession`; the **API endpoint** surfaces the warning (see 1e). Attach warning to session transiently? No — pass it back. Simplest: stash on a local and return via endpoint by re-checking. **Decision:** store `ownership_warning` as a non-persisted attr `session._spawn_warning = ownership_warning` (private, like other `_` fields) so the endpoint can read `session._spawn_warning`. Add field `_spawn_warning: str = field(default="", repr=False)` to AgentSession.

### 1e. API + MCP
`app/main.py`:
- `CreateSessionRequest` (`:91`): add `owned_dirs: list[str] = []`.
- endpoint `create_session` (`:366`): pass `owned_dirs=req.owned_dirs`; after success include warning in response: `d = session.to_dict(); d["spawn_warning"] = session._spawn_warning; return d`.

`app/mcp_stdio.py::spawn_worker` (`:55`):
- Add param `owned_dirs: str = ""` (JSON array string, consistent with `mcp_servers` being a JSON string). Parse like mcp_servers; on parse error return clear msg.
- Add to body if present.
- Append to return string when server reports `spawn_warning`: the `_api` POST returns the dict → read `result.get("spawn_warning")` and append `⚠️ Ownership overlap: <warning>` to the success line.
- Update docstring: `owned_dirs — JSON array of dirs this worker owns, e.g. ["app/api/", "app/models/"]. Injected into worker prompt; overlap with another live worker → warning (not blocked).`

### 1f. Rehydrate
`app/manager.py` rehydrate (`:563`): `owned_dirs=parse_owned_dirs(db_row.get("owned_dirs"))` — same shared parser, tolerates malformed/legacy values.

---

## Feature 2: Pre-dispatch conflict simulation (priority 4)

### 2a. simulate_conflict helper
`app/workspace.py` — new helper (reuses existing merge-tree parsing logic from `:307`):
```python
def simulate_conflict(repo_path: str, branch_a: str, branch_b: str) -> dict:
    """Dry-run merge of two existing branches. Returns {ok, conflicts:[...]} or {ok:False, error}."""
    repo = _resolve_repo(repo_path, repo_path)
    # Codex F4: verify both refs exist FIRST — don't conflate "missing branch" with "unrelated histories"
    for ref in (branch_a, branch_b):
        v = subprocess.run(["git","rev-parse","--verify",f"{ref}^{{commit}}"], cwd=str(repo), capture_output=True, text=True)
        if v.returncode != 0:
            return {"ok": False, "error": f"branch '{ref}' not found"}
    mb = subprocess.run(["git","merge-base",branch_a,branch_b], cwd=str(repo), capture_output=True, text=True)
    if mb.returncode != 0:
        return {"ok": False, "error": "unrelated histories — cannot simulate"}
    r = subprocess.run(["git","merge-tree","--write-tree",branch_a,branch_b], cwd=str(repo), capture_output=True, text=True)
    if r.returncode == 0:
        return {"ok": True, "conflicts": []}
    conflicts = [l.split()[-1] for l in r.stdout.splitlines() if l.startswith("CONFLICT") and l.split()]
    if conflicts:
        return {"ok": True, "conflicts": conflicts}
    return {"ok": False, "error": (r.stderr.strip() or r.stdout.strip() or "merge-tree failed")}
```
(`ok:True, conflicts:[...]` means "simulation ran, here's what would conflict". `ok:False` = couldn't run.)

### 2b. Spawn-time file-overlap warning (the realistic pre-dispatch check)
At spawn the new branch doesn't exist yet → can't merge-tree it. The roadmap's pre-dispatch
intent is satisfied by the **owned_dirs static overlap** already in Feature 1d. ADDITIONALLY,
when spawning a worker **with a task_id** (existing branch may exist on reuse) we skip sim.

**Decision:** keep pre-dispatch SIMPLE — Feature 1's owned_dirs overlap IS the pre-dispatch warning.
Expose `simulate_conflict` as an orchestrator MCP tool for the **two-committed-branches** case
(pre-merge), where it actually works:

`app/mcp_stdio.py` — new tool:
```python
@mcp.tool()
async def check_conflict(worker_a: str, worker_b: str) -> str:
    """Dry-run: would merging these two workers' branches conflict? Both must have committed work."""
```
→ `POST /api/sessions/check-conflict` (new endpoint in main.py) resolves both sessions' worktree
branches + repo, calls `simulate_conflict`, returns conflict list or "no conflicts".

This gives the orchestrator a real tool to decide merge order, without inventing a fake
pre-spawn branch. Document in orchestrator.md.

---

## Feature 3: Safer auto-commit + WIP visibility (priority 5)

### 3a. Fix _auto_commit_if_dirty (the real bug)
`app/manager.py:340`. Current: silent `git add -A` + `wip: auto-save before worker spawn`.
**Fix:** make it loud and labelled, return what it did so the orchestrator is warned.
```python
@staticmethod
def _auto_commit_if_dirty(repo_path: str) -> str:
    import subprocess, datetime
    r = subprocess.run(["git","status","--porcelain"], cwd=repo_path, capture_output=True, text=True)
    if not r.stdout.strip():
        return ""
    files = [l[3:] for l in r.stdout.strip().splitlines()]
    cur = subprocess.run(["git","symbolic-ref","--short","HEAD"], cwd=repo_path, capture_output=True, text=True)
    branch = cur.stdout.strip() or "(detached HEAD)"          # Codex F5: don't hard-code "main"
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    msg = (f"WIP: auto-saved uncommitted changes before worker spawn ({ts})\n\n"
           f"Orchestra committed {len(files)} dirty path(s) in the source repo checkout "
           f"(branch {branch}) to give the new worker a clean base. Review and amend/reset "
           f"if this buried work-in-progress:\n"
           + "\n".join(f"- {f}" for f in files))
    add = subprocess.run(["git","add","-A"], cwd=repo_path, capture_output=True, text=True)
    if add.returncode != 0:                                    # Codex F2: check returncodes
        logger.error(f"auto-commit git add failed in {repo_path}: {add.stderr.strip()}")
        return f"FAILED to auto-save dirty source repo (git add rc={add.returncode}) — spawn proceeds on DIRTY base"
    commit = subprocess.run(["git","commit","-m",msg], cwd=repo_path, capture_output=True, text=True)
    if commit.returncode != 0:                                 # Codex F2: never falsely claim a commit
        logger.error(f"auto-commit failed in {repo_path}: {commit.stderr.strip()}")
        return (f"FAILED to auto-save dirty source repo (git commit rc={commit.returncode}: "
                f"{commit.stderr.strip()[:120]}) — spawn proceeds, changes NOT committed")
    logger.warning(f"Auto-committed {len(files)} dirty path(s) in {repo_path} (branch {branch}) before spawn")
    return f"auto-committed {len(files)} dirty file(s) (branch {branch}) before spawn — review the WIP commit"
```
- In `create_session` (`:416`): capture `wip_note = await asyncio.to_thread(self._auto_commit_if_dirty, repo_path)` and fold into `session._spawn_warning` (append).
- Keeps behaviour (commit, not stash — no clean pop point in spawn flow) but **labelled + surfaced + returncode-checked**, fixing the silent-burial bug AND the silent-failure bug. No backward-compat shim. Spawn still proceeds on failure (advisory philosophy) but the warning tells the truth.

### 3b. WIP commit prompt guidance (worker + orchestrator)
This is prompt-only (Orchestra can't force LLM commit text):
- `app/prompts/roles/worker.md` (~`:60`): add explicit WIP format:
  ```
  - When asked to stop mid-task: commit WIP with a DESCRIPTIVE message — what's done, what's left:
    git commit -m "WIP: #49 — done X, Y; TODO: Z, edge-case W"
  ```
- `app/prompts/roles/orchestrator.md` (`:128-129`): update the URGENT example to ask for the descriptive WIP format, and reference the resume helper (3c).

### 3c. WIP visibility on resume
When orchestrator resumes/switches a branch, surface what's uncommitted/unmerged. Add a read-only
helper + MCP tool (NO mutation):
`app/workspace.py`:
```python
def branch_wip_status(worktree_path: str, base_ref: str = "refs/heads/main") -> dict:
    """Report uncommitted files + unmerged commits (subjects) for a worktree."""
    wt = Path(worktree_path).resolve()
    dirty = subprocess.run(["git","status","--porcelain"], cwd=str(wt), capture_output=True, text=True)
    uncommitted = [l[3:] for l in dirty.stdout.strip().splitlines()] if dirty.stdout.strip() else []
    log = subprocess.run(["git","log",f"{base_ref}..HEAD","--format=%s"], cwd=str(wt), capture_output=True, text=True)
    unmerged = [l for l in log.stdout.strip().splitlines() if l.strip()] if log.returncode == 0 else []
    return {"uncommitted": uncommitted, "unmerged_commits": unmerged}
```
`app/mcp_stdio.py` — new tool `worker_wip(name, base_ref="refs/heads/main")` → `GET
/api/sessions/{name}/wip?base_ref=...` (new endpoint) → returns uncommitted files + unmerged commit
subjects. **Codex F3:** `base_ref` is a param (default `refs/heads/main`) so for a worker spawned
from a feature branch the orchestrator passes that base — otherwise `main..HEAD` would mislabel the
feature branch's own commits as worker WIP. Orchestrator calls it before resuming a worker to see
"what's left". Document in orchestrator.md resume flow (note the base_ref default + when to override).

---

## What NOT to touch
- `app/tg_bridge.py`, frontend (`app.js`, `dashboard.html`, CSS).
- Squash merge / nested-repo guard (separate roadmap items, squash already done).
- Merge lock, `_ensure_repo_on_branch`, cherry-pick fallback — unchanged.
- Don't make ownership a hard block — advisory only (explicit design decision).
- Don't switch `_auto_commit_if_dirty` to stash (no clean pop point in spawn lifecycle).

## Migration / compatibility notes
- New column `owned_dirs TEXT DEFAULT ''` via ALTER guard — old rows get `''` → parsed to `[]`.
- No API breaking changes: all new fields/params optional with defaults.
- `_spawn_warning` is a transient private attr, not persisted.

## New MCP tools added (3)
- `spawn_worker(..., owned_dirs="[...]")` — extended, not new.
- `check_conflict(worker_a, worker_b)` — pre-merge dry-run.
- `worker_wip(name)` — resume-time WIP visibility.
Each is a single deterministic path (one tool = one job), consistent with Agent Determinism principle.

## Test plan (edge cases)
- owned_dirs normalize: trailing slash, dupes, empty list, `["app/api","app/api/v1"]` overlap.
- dirs_overlap: prefix match both directions, no false positive on `app/api` vs `app/apix`.
- Ownership conflict: two live workers same scope overlapping dirs → warning string; archived worker ignored.
- _auto_commit_if_dirty: clean repo → "" no commit; dirty → labelled commit + note returned.
- branch_wip_status: clean+merged → empty lists; dirty+unmerged → populated.
- simulate_conflict: unrelated histories → ok:False; clean merge → conflicts:[]; real conflict → file list.
- Rehydrate session with/without owned_dirs column value.

## Suggested implementation order
1. DB column + AgentSession field + save/rehydrate (foundation).
2. owned_dirs helpers + create_session plumbing + prompt injection.
3. API + MCP spawn_worker extension.
4. _auto_commit_if_dirty fix.
5. simulate_conflict + check_conflict tool + endpoint.
6. branch_wip_status + worker_wip tool + endpoint.
7. Prompt edits (worker.md, orchestrator.md).
