# Review #35 — Architecture, Dead Code & Optimization

Scope: all Python in `app/` (backend_claude, session, manager, workspace, models, events, db, main, mcp_stdio, tg_bridge, tm + the helpers they touch).

Severity: **P0** crash/correctness · **P1** real bug or meaningful debt · **P2** simplification/cleanup · **P3** nit.

---

## P0 — Crash / correctness

### [P0] `restart_cli` calls a method that doesn't exist → 500 on every use
`app/main.py:558`
```python
await session._disconnect_client()
```
`AgentSession` has **no** `_disconnect_client` — the method is `_disconnect_backend` (renamed during the codex-backend refactor; the old name lingers only in `CHANGELOG.md:261` and `docs/archive/research/codex-backend-plan.md:80`). The `♻️ Restart CLI` button is wired in `dashboard.html:147` + `app.js:355`, so clicking it 500s. Line 559 also reaches into `session.status.__class__("idle")` to dodge the `AgentStatus` import — fragile.

**Fix:**
```python
await session._disconnect_backend()
session.status = AgentStatus.IDLE   # import AgentStatus from app.session
session._persist()
```
(`AgentStatus` is already importable from `app.session`.)

---

## P1 — Real bugs / meaningful debt

### [P1] `tm.py` ignores `ORCHESTRA_DB_PATH` → two modules, two databases
`app/tm.py:16-28` hardcodes its own `DB_PATH` and `_conn()`, duplicating `app/db.py:9-35`. But `db.py` honors `ORCHESTRA_DB_PATH` (env override for per-worktree/test DBs, added so parallel branches don't lock each other — see `_resolve_db_path`), while `tm.py` does **not**. Any test or worktree that sets `ORCHESTRA_DB_PATH` gets `db.py` pointed at DB-A and `tm.py` pointed at DB-B (the default `data/orchestra.db`). Silent split-brain: sessions in one file, tasks in another.

**Blast radius (per Codex):** bites only when `ORCHESTRA_DB_PATH` is set — i.e. tests and parallel worktrees (exactly what that override was added for). Default single-DB production is unaffected. Still P1: the fix is a deletion, not new code, and it removes a live test-isolation footgun.

**Fix:** delete `tm.py`'s `DB_PATH` + `_conn()`, `from app.db import _conn`. One connection helper, one path resolution. (12 lines deleted > a second copy.)

### [P1] `_codex_reasoning_effort` is a dead branch — both arms return `"high"`
`app/session.py:147-150`
```python
def _codex_reasoning_effort(self) -> str:
    if self.is_orchestrator:
        return "high"
    return "high"
```
The `if` does nothing. Either it should differentiate (orchestrator vs worker effort) or it should be `return "high"`. As written it's a trap: reads like there's a policy, there isn't.

**Fix:** collapse to `return "high"`, or inline `"high"` at the one call site (`session.py:134`) and delete the method.

### [P1] `tg_bridge` log-streaming is an N-loop of 0.5–2s DB polls — one task per orchestrator, forever
`app/tg_bridge.py:848-969` (`stream_logs`) runs `while True: get_logs(...); sleep(2)` per orchestrator topic, and `app/main.py:482-497` (`stream_session_logs`) runs `sleep(0.5)` per open dashboard SSE connection. Every loop is a fresh `sqlite3.connect()` + `SELECT ... WHERE id > ?`. With K orchestrators + M dashboard tabs that's (K/2 + 2M) connects/sec against one WAL file, 24/7, even when every agent is idle. This is the single biggest steady-state cost in the system.

**Fix (MVP-appropriate):** keep polling but (a) reuse one connection per loop instead of reconnecting each tick (`_conn()` opens a new fd + 3 PRAGMAs every 500 ms), and (b) back off the interval when the last poll returned 0 rows (e.g. 0.5s→3s while idle). No pub/sub rebuild needed. `idx_logs_session (session_id, id DESC)` already makes the query cheap; the connect churn is the waste.

### [P1] `auto_resume_all` resets every non-idle row to `idle` for ALL scopes, unconditionally
`app/manager.py:882` `UPDATE sessions SET status='idle' WHERE status != 'idle'` runs inside `auto_resume_all` with no scope filter and before load attempts. Rows whose `cwd`/`scope` no longer exists (skipped at 890/903) are silently flipped to `idle` in the DB but never loaded into memory — they now show as resumable "idle" agents that aren't running. Minor, but it makes the DB lie about state for dead worktrees. Consider only flipping rows you actually attempt to resume, or mark unloadable rows `error`/`archived`.

---

## P2 — Dead code & simplification

### [P2] Dead module: `app/backend.py` (`AgentBackend` Protocol) never imported
`app/backend.py` — the `AgentBackend` Protocol is defined but **zero** imports exist anywhere in `app/` (grep confirms only the definition site). `session._make_backend` instantiates `ClaudeBackend`/`CodexBackend` directly; nothing type-checks against the Protocol. It's aspirational documentation, not wiring.
**Fix:** delete the file, or if you want it as a contract, actually annotate `AgentSession._backend: AgentBackend`. Right now it's "оставлю на всякий случай" — git remembers.

### [P2] Dead DB functions: `get_orchestrators`, `get_resumable_orchestrators`, `mark_stale_sessions`
`app/db.py:635, 644, 653` — none are called from anywhere in `app/` (grep: only definitions). `auto_resume_all` does its own inline `SELECT`s instead of using `get_resumable_orchestrators`. `mark_stale_sessions` is fully orphaned. ~35 lines of unused SQL.
**Fix:** delete all three.

### [P2] Dead no-op: `tg_bridge._react_processing`
`app/tg_bridge.py:368-369` is `async def _react_processing(msg): pass`, awaited 6× in the media handlers (984, 1005, 1034, 1046, 1060, 1072). It does nothing — leftover from a reaction feature that was gutted.
**Fix:** delete the function and the 6 call sites.

### [P2] Dead alias: `workspace._ensure_repo_on_main`
`app/workspace.py:157` `_ensure_repo_on_main = _ensure_repo_on_branch` — "обратная совместимость" alias, never referenced (grep: only the assignment). Project rule is explicitly *no compat shims*.
**Fix:** delete the line.

### [P2] Redundant wrapper: `manager.auto_resume_orchestrators`
`app/manager.py:925-926` is a one-line passthrough to `auto_resume_all`, with one caller (`main.py:37`). The name also lies — it resumes workers too.
**Fix:** call `auto_resume_all` directly in `main.py:37`, delete the wrapper.

### [P2] Three near-identical "expandable blockquote" senders in tg_bridge
`app/tg_bridge.py` — `_send_expandable_return` (386), `_send_expandable` (461), and the body of `_edit_expandable` (441) all build the same `header\n{conv_body}` + single `EXPANDABLE_BLOCKQUOTE` entity + try/except fallback. `_send_expandable` and `_send_expandable_return` differ only in `return`. The send/edit split is real (different Bot API call), but send-vs-send-return is pure duplication.
**Fix:** keep one `_send_expandable` that returns the message; drop `_send_expandable_return`. ~15 lines. (Verify callers don't depend on the non-returning variant swallowing the result — they don't; the return is just ignored.)

### [P2] `_extract_tool_result` JSON-unwrap is dead for the orchestra MCP path
`app/backend_claude.py:73-78` tries `json.loads(text)` and returns `parsed['result']` if present. Orchestra's own MCP tools (`mcp_stdio.py`) return **plain strings**, not `{"result": ...}` envelopes. This unwrap only fires for tools that happen to emit that exact shape. Harmless, but it's speculative handling of a format the codebase doesn't produce — flag for confirmation rather than blind delete (some third-party MCP might rely on it).

### [P2] `is_orchestrator` persisted as a column AND derived from `role` — two sources of truth
`session.py:785` writes `is_orchestrator` (derived from `role`) to its own DB column, while every read path already recomputes it via `is_orchestrator_role(role)` (`manager.py`, `db.py:638`). The column is redundant with `role`; queries that still use `is_orchestrator = 1 OR role IN (...)` (`db.py:638, 647`) carry the belt-and-suspenders cost. Not urgent (migration risk), but worth noting: `role` is the real key, `is_orchestrator` is a cached bool that can drift.

---

## P3 — Nits / consistency

### [P3] Inline `import` scattered where a top-level import would do
Repeated function-body imports of stable stdlib/local modules: `import os` (`backend_claude.py:103`), `import json as json` inside `mcp_stdio.spawn_worker` (82, 92 — imported twice in one function), `import subprocess, datetime` (`manager.py:376`), `import json` (`main.py:478, 890, 900, 1168`), `from app.db import _conn` repeated in 4 `main.py` endpoints (596, 614, 633, 687). Lazy imports are justified to break cycles (`tg_bridge`, `bg_jobs`) — but these are plain stdlib/no-cycle cases. Minor context noise; tighten opportunistically when touching the function.

### [P3] `max_tokens = 200000` magic default repeated ≥5 places
`backend_claude.py:239,258`, `session.py:411,759`, `main.py:471`, `manager.py:758`. `CONTEXT_LIMITS` in `models.py` is the single source — but the `.get(model, 200000)` fallback literal is copy-pasted. Define `DEFAULT_CONTEXT_LIMIT = 200000` in `models.py` and reference it.

### [P3] `_CODEX_BIN` hardcodes an absolute user path
`mcp_stdio.py:601` `_CODEX_BIN = "/home/maxim/.npm-global/bin/codex"`. Breaks on the VPS / any other user. Should be `shutil.which("codex") or os.environ.get("CODEX_BIN", ...)` like `backend_claude.py:104` already does for the `claude` CLI. Inconsistent with the existing pattern in the same codebase.

### [P3] `change_scope` migrates `bg_jobs`/`test_lock`/`tm_projects` but the function lives in db.py while the orchestration lives in manager — split brain on "what moves with a scope"
`db.py:460-505` knows the full list of tables keyed by scope. If a new scope-keyed table is added, this is the one place that must be updated, but nothing enforces it. Not a bug today — flagging as a maintenance landmine. A one-line comment listing "tables keyed by scope" at the top would help future-you.

---

## Summary of concrete deletions (safe, mechanical)
| What | Where | ~Lines |
|------|-------|-------|
| `_disconnect_client` → `_disconnect_backend` (P0 fix) | main.py:558 | 2 |
| `tm.py` DB_PATH + `_conn` dup → import from db (P1) | tm.py:16-28 | -12 |
| `_codex_reasoning_effort` dead branch (P1) | session.py:147 | -3 |
| `app/backend.py` dead Protocol | whole file | -18 |
| `get_orchestrators` / `get_resumable_orchestrators` / `mark_stale_sessions` | db.py | -35 |
| `_react_processing` + 6 calls | tg_bridge.py | -7 |
| `_ensure_repo_on_main` alias | workspace.py:157 | -2 |
| `auto_resume_orchestrators` wrapper | manager.py:925 | -2 |
| `_send_expandable_return` merge into `_send_expandable` | tg_bridge.py | -15 |

Net: ~95 lines removed, one user-facing 500 fixed, one split-brain DB risk closed — no behavior change beyond the P0/P1 fixes.

## Codex cross-review reconciliation
Codex (`codex-architecture.md`) could only validate the two findings I passed inline — its `codex_review` tool runs in the source-repo cwd, not this worktree, so it saw `review-architecture.md` as "missing" (it lives on this branch). It independently confirmed:
- **P0** `_disconnect_client` → **blocking**, crashes with `AttributeError`. Confirmed against `_disconnect_backend` at `session.py:736`. No change.
- **P1** `tm.py` DB path → **real, but scope the severity**. Codex's point is fair: it only bites when `ORCHESTRA_DB_PATH` is set. Per `db.py:_resolve_db_path`'s own docstring, that override exists *specifically* for "разным worktree/веткам и тестам держать свою БД" — so the split-brain is live exactly in the test/worktree workflow the override was built for, but **not** in default single-DB production. I'm keeping it at P1 (the fix is a 12-line deletion that also removes a duplicate connection helper — cheap, and it closes a real test-isolation footgun) but the practical blast radius is tests/worktrees, not the prod DB. Adjusted the finding text to say so.

The remaining findings (dead code, polling cost, etc.) were not externally validated — they're verified by my own grep against the tree (call-site counts cited inline).

## What I deliberately did NOT flag
- The `merge_worktree_to_main` flat 130-line function (workspace.py:252) reads as a long arrow but every branch is a distinct git failure mode with a real recovery path. Splitting it would scatter the `finally` stash/restore invariant — leave it flat. **3 lines > abstraction** cuts the other way here.
- The verbose `_handle_event` dispatch (session.py:329) — a dict-dispatch table would be "cleverer" but the explicit `elif` chain is the readable, debuggable form for ~10 event types. Keep.
- `db._migrate` — ugly but it's append-only migration history; rewriting risks data. Don't touch.
