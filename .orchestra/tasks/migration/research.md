# Research: Full agent migration between servers (laptop ↔ VPS)

**Task:** Investigate technical feasibility of migrating a full Orchestra orchestrator/worker
(with its live conversation context) between machines — laptop (`/mnt/data/Projects/Python/orchestra`)
and VPS Contabo DE (`158.220.127.161`, `/home/kesha/orchestra/`).

**Verdict (short):** ✅ **Migration IS technically feasible and near-lossless** for the persistent
part of an agent (DB row + CLI transcript + git repo/worktree + scope docs). What CANNOT be
carried is only volatile runtime state (loaded context window in RAM, in-flight turn, pending
tool calls) — but Orchestra already discards those on every restart via `auto_resume_all`, so
migration is no worse than a local restart. **The real blocker is not technical — it's TOS**
(§3). Confidence: **CONFIRMED** for mechanics, **LIKELY-with-caveat** for TOS.

---

## 1. What holds an agent's state — full inventory

An Orchestra agent is reconstituted from **four independent stores**. Verified by reading
`app/manager.py`, `app/session.py`, `app/backend_claude.py`, `app/db.py` and inspecting the live DB.

| # | Store | Location | Holds | Portable? |
|---|-------|----------|-------|-----------|
| A | **SQLite row** (`sessions` table) | `data/orchestra.db` | name, scope, cwd, model, role, `session_id` (=CLI id), `worktree_path`, branch, parent, mcp_servers_custom, owned_dirs, pipeline, profile, costs, context_pct, `session_id_history` | ✅ row copy |
| B | **CLI transcript** (the actual conversation) | `~/.claude/projects/<encoded-cwd>/<session_id>.jsonl` | full replayable message history — THIS is the context | ✅ file copy (with path caveat) |
| C | **Git repo / worktree** | scope path + `worktrees/<enc>/<worker>` | code the agent works on, its branch | ✅ git (clone/bundle/push) |
| D | **Scope docs** | `<scope>/CLAUDE.md`, `<scope>/docs/workers/<name>.md`, `.mcp.json`, `.env` | project rules, worker persistent memory, scope MCP config | ✅ travels inside the git repo (C) |

Supporting DB tables (secondary, per-session): `inbox` (pending messages, FK→session),
`bg_jobs` (background timers/watchers, FK by `target_session_id`), `logs` (chat history for
dashboard — cosmetic), `subagents` (telemetry). All keyed by the session `id` (row A).

**Key insight — the transcript (B) is the context.** From official docs [1] and verified
in the live file: on `--resume`, Claude Code *replays* the JSONL line-by-line to rebuild the
message array (compacting if too large). So the file **alone** restores full context on the
new machine — there is no server-side conversation storage to lose.

### The DB↔CLI linkage (verified)
`sessions.session_id` (e.g. Orchestra-orchestrator = `d6bd34bc-…`) **is** the CLI session UUID.
The transcript for it lives at:
```
~/.claude/projects/-mnt-data-Projects-Python-orchestra/d6bd34bc-…-….jsonl   (1.5 MB, verified exists)
```
Encoding rule (verified in `manager._migrate_cli_session`, manager.py:687):
```python
encoded_dir = cwd.replace("/", "-").lstrip("-")
```
On resume, `backend_claude.py:144` sets `options.resume = session_id` and `options.cwd = cwd`.
The SDK/CLI looks up the transcript in the project dir **derived from the current cwd**, then
replays it. Nothing binds it to the host.

---

## 2. Is the CLI session portable between machines?

**YES — confirmed by three independent sources + the codebase.**

### 2a. session_id is NOT machine-bound
Grepped the live 1.5 MB transcript for host binding:
- `userType: "external"` — generic, not a host id.
- **No** `machineId`, no hostname, no user-id in structural metadata. (The only "hostname"
  string hits are *inside message content* — agents literally ran `hostname -I` in bash.)
- Baked-in fields: `"cwd":"/mnt/data/Projects/Python/orchestra"` (726 occurrences) and
  `"gitBranch":"main"`. These are **informational replay data**, not validated on resume —
  resume keys off the *current* cwd + `--resume <id>`, not the transcript's internal cwd.

### 2b. Official Anthropic position [1]
> "Transcripts live on the local disk. To share sessions across machines, sync the files…"

Community backup guides [2] confirm: keeping the `.jsonl` files **is** what enables `/resume`
across machines. Anthropic explicitly documents this workflow.

### 2c. The ONE gotcha — path encoding must match
Session lookup is **scoped to the project dir derived from cwd** [1]. Resume from a mismatched
dir → `"No conversation found with session ID: …"`. So on the target machine:
- The transcript must land in the folder whose **encoded name matches the target cwd**.
- Because laptop cwd (`/mnt/data/Projects/Python/orchestra`) ≠ VPS cwd
  (`/home/kesha/orchestra`), the encoded dir differs:
  - laptop: `-mnt-data-Projects-Python-orchestra`
  - VPS:    `-home-kesha-orchestra`
  → **the migration script must place the file in the target-encoded dir** AND update
    `sessions.cwd`/`worktree_path` in the DB row to the target paths. This is exactly what the
    existing **scope-change** feature already does locally (manager.py:673-695) — cross-server
    migration is the same operation with an added `scp`.

### 2d. v2.1+ nested artifacts
Recent CLI (this machine runs `2.1.197`) also stores, under `<session-uuid>/`:
`subagents/` (subagent transcripts) and `tool-results/` (large tool payloads) [1].
Migration must copy the whole `<session_id>*` glob, not just the top `.jsonl`. The existing
code already globs `f"{session_id}*"` (manager.py:693) — matches only the flat file; **for full
fidelity the new script should also copy the `<session_id>/` sibling directory** if present.

### 2e. Version-compat caveat
The JSONL entry format is **internal and changes between CLI versions** [1][3]. Plain
copy-and-resume is fine, but **both machines must run compatible `claude` CLI versions**.
Mismatch risk: replay parse errors. → Migration precondition: pin/verify CLI version parity.

---

## 3. Legal / TOS constraints — ⚠️ THE REAL BLOCKER

This is the part that matters more than the mechanics. **Orchestra runs on a Claude Max 20x
OAuth subscription, not an API key** — verified:

- `~/.claude/.credentials.json` → `claudeAiOauth` with `subscriptionType: "max"`,
  `rateLimitTier: "default_claude_max_20x"`, scopes incl. `user:sessions:claude_code`.
- **No `ANTHROPIC_API_KEY`** in `.env` (grepped — absent). `backend_claude.py` sets no API key;
  the SDK inherits the CLI's OAuth session from `~/.claude/`.
- Matches CLAUDE.md: "Max 20x subscription ($200/мес) … all $ virtual".

### Findings [4][5]
1. **Feb 19 2026 — Agent SDK requires API-key auth.** Anthropic's Legal & Compliance docs were
   updated: *"the Agent SDK now explicitly requires API key authentication — OAuth tokens from
   Free/Pro/Max accounts cannot be used with the Agent SDK."* Orchestra uses `claude-agent-sdk`
   on a **Max OAuth** token → this is **already in tension with current TOS**, independent of
   migration.
2. **No prohibition on the CLI binary on any host.** *"What remains allowed: using the actual
   claude CLI binary on any machine — local, VPS, CI/CD."* So running Claude Code on the VPS is
   fine per se.
3. **Copying session `.jsonl` is not restricted.** No TOS clause bars moving your own transcript
   files between your own machines. The restricted thing is **credential routing/extraction**
   (Jan 2026 crackdown on OpenClaw/OpenCode/Goose that extracted OAuth tokens into their own
   API clients [4]).
4. **Credential portability = the grey zone.** For the migrated agent to *run* on the VPS it
   needs auth there. Two paths:
   - Copy `~/.claude/.credentials.json` (the Max OAuth token) to the VPS → this is
     **"routing Max-plan credentials"** onto another host/instance. Closest to the enforced-against
     behavior. **Not recommended.**
   - Log in separately on the VPS with the same account (`claude` interactive login) → same
     token, sanctioned path, but **one subscription used across 2 always-on hosts** conflicts with
     *"advertised limits assume ordinary, individual usage"* [4].

### TOS bottom line
- **Moving the transcript file: allowed.** ✅
- **Moving/routing the Max OAuth credential to a second always-on server: TOS grey→red.** 🟡🔴
- **Fully compliant path: API keys under Commercial Terms** — *"for anything production,
  always-on, or business-related, API keys … are the clear path — no automation restrictions"* [4].

→ **Recommendation:** if migration to an always-on VPS is a real workflow, the VPS should
authenticate with an **`ANTHROPIC_API_KEY` (Commercial)**, not a copied Max OAuth token. The
transcript/DB/git migration is orthogonal and stays valid regardless of which auth the target uses.

---

## 4. What is genuinely portable (sufficient to restore an agent)

Restoring an agent on the target = reproducing stores A+B+C+D. **This is sufficient** — verified
against `_load_from_db` (session.py:206 `_make_backend` → resume) + `auto_resume_all`
(manager.py:1136). On restart Orchestra rebuilds every live agent from **exactly** the DB row +
CLI transcript; it holds nothing else in durable form. Migration = "restart, but the DB row and
transcript arrive from another host."

| Portable & sufficient | How |
|---|---|
| `sessions` row (A) | `INSERT`/upsert into target DB with rewritten `cwd`, `worktree_path`, `scope` |
| CLI transcript (B) | `scp` `.jsonl` (+ `<id>/` dir) into target-encoded `~/.claude/projects/<enc>/` |
| `inbox`, `bg_jobs` rows | copy rows keyed by session id (optional — pending msgs/timers) |
| Git repo / branch (C) | push branch or `git bundle`; recreate worktree on target |
| `CLAUDE.md`, `docs/workers/<name>.md`, `.mcp.json` (D) | inside the git repo → travels with C |

## 5. What is lost (and why it doesn't matter)

| Lost | Why | Impact |
|---|---|---|
| **Context window in RAM** | volatile; SDK subprocess memory | **None** — rebuilt by replaying transcript (B) on resume |
| **In-flight turn** | active `query()` generation | Interrupted, same as any restart. Re-send last message |
| **Pending tool calls** | mid-turn tool exec | Dropped — same as restart; agent re-plans |
| **`logs` rows** (dashboard chat) | cosmetic mirror of transcript | Optional to copy; context intact without them |
| **Live SSE/broker/stream state** | in-memory pub/sub | Reconnects on target |

**These are identical to what Orchestra already discards on `sudo systemctl restart orchestra`**
(CLAUDE.md: "Активные turns прерываются, но idle воркеры восстанавливаются, контекст НЕ теряется").
Migration inherits that exact guarantee. **Precondition: migrate only an IDLE agent** (no active
turn), else you lose the in-flight turn — trivially enforced.

---

## 6. Proposed architecture — `migrate_agent(name, from, to)`

**Design principle:** cross-server migration = the existing **scope-change** operation
(manager.py:645-695) + an `scp`/`git push` hop. Reuse that proven path; do not invent a parallel one.

### Preconditions (fail loud if unmet)
1. Agent **IDLE** on source (no running turn). `bg_create(type=run)` not mid-fire.
2. Source working tree **clean** & branch pushed (worker) OR committed (orchestrator scope).
3. **CLI version parity** source↔target (`claude --version`).
4. Target has auth (**API key strongly preferred over copied OAuth — see §3**).

### Order of operations
```
migrate_agent(name, from_server, to_server, target_scope, target_cwd):

  # 0. Freeze
  stop_worker(name) on source            # idle, drain persist (session._drain_persist)

  # 1. Git (store C+D — code + CLAUDE.md + docs/workers travel here)
  on source: git push origin <branch>    # or: git bundle create <name>.bundle --all
  on target: git clone/fetch; git worktree add <target_worktree> <branch>

  # 2. CLI transcript (store B) — the context
  enc_src = from_cwd.replace('/','-').lstrip('-')
  enc_dst = target_cwd.replace('/','-').lstrip('-')
  scp  ~/.claude/projects/$enc_src/$session_id*        target:~/.claude/projects/$enc_dst/
  scp -r ~/.claude/projects/$enc_src/$session_id/  (if exists — v2.1 subagents/tool-results)

  # 3. DB row (store A) — REWRITE host-specific paths
  read sessions row (+ inbox, bg_jobs) from source DB
  rewrite: cwd→target_cwd, worktree_path→target_worktree, scope→target_scope
  keep AS-IS: session_id, session_id_history, model, role, costs, context_pct, pipeline
  upsert into target orchestra.db   (delete archived dup first — UNIQUE(name,scope), manager.py:404)

  # 4. Auth (store outside all 4 — see §3)
  ensure target ~/.claude authenticated (API key in .env  ▶ preferred)

  # 5. Bring up on target
  on target: auto_resume_all picks up the new row → _make_backend(resume=session_id)
             → SDK --resume replays transcript from $enc_dst dir → context restored

  # 6. Verify + retire source
  send test message on target; confirm context ("what were you doing?")
  on source: kill_worker(name, force) or mark archived   # avoid two live copies of same agent
```

### Paths that MUST be rewritten (host-specific)
- `sessions.cwd`, `sessions.worktree_path`, `sessions.scope`
- CLI project-dir encoding (place file in `enc_dst`, not `enc_src`)
- `.env` `HTTPS_PROXY` (target may need a different proxy — VPS ≠ laptop)
- Any absolute path in `mcp_servers_custom` / scope `.mcp.json` (e.g. Playwright paths)

### Paths that must NOT change
- `session_id` (the resume key), `session_id_history`, model, role, pipeline, parent linkage.

### Implementation shape
A standalone script `scripts/migrate_agent.py` (SSH-driven, run from the source), **not** an
in-process MCP tool — it spans two hosts, two DBs, two filesystems. It should:
transaction the DB row copy, verify the transcript arrived, and refuse to leave two live copies.
Reuse `_migrate_cli_session`'s encoding + `change_scope`'s DB path-rewrite logic.

---

## 7. Counter-evidence / risks

- **JSONL format drift** [1][3] — internal format changes per CLI release. **Mitigation:** version
  parity precondition; migrate soon, don't archive-then-migrate across upgrades.
- **TOS on OAuth/SDK** [4] — the Agent-SDK-needs-API-key rule (Feb 2026) already applies to
  Orchestra's *current* setup, migration or not. Migration to an always-on VPS **amplifies** the
  "individual/ordinary usage" concern. Strongest counter-evidence to "just copy credentials."
- **Two live copies** — if source isn't retired, the same `session_id` runs on two hosts →
  divergent transcripts, double rate-limit burn. Script MUST retire source (step 6).
- **`context_pct` mismatch** — DB stores it; if target CLI compacts differently on replay, the
  number may drift. Cosmetic (dashboard), not correctness.
- **Not proven end-to-end here** — I did not run an actual laptop→VPS resume (no VPS access in
  this task). Mechanics are CONFIRMED by code + docs + live-file inspection; the full round-trip
  is **LIKELY**, and should be smoke-tested on one throwaway worker before trusting it.

---

## 8. If migration were impossible — the fallback (it's not needed, but documented)

**"Spawn fresh + inject context"**: on target, `spawn_worker` a new agent (fresh session_id),
then inject a compacted summary + `CLAUDE.md` + `docs/workers/<name>.md` as the first message.
Loses turn-by-turn history but keeps intent/rules. **Not required** — true resume works — but this
is the graceful degradation if version drift breaks a specific transcript.

---

## Sources
- [1] Manage sessions — Claude Code Docs: https://code.claude.com/docs/en/sessions
- [2] claude-code-backup-guide (cross-machine `/resume` via `.jsonl`): https://github.com/jtklinger/claude-code-backup-guide
- [3] Claude Code JSONL transcript format (internal, version-drift): https://claude-dev.tools/docs/jsonl-format
- [4] Claude Code ToS explained (SDK requires API key Feb 2026; CLI on any host allowed; OAuth-routing crackdown): https://autonomee.ai/blog/claude-code-terms-of-service-explained/
- [5] Claude Code Legal & Compliance: https://code.claude.com/docs/en/legal-and-compliance

## Affected files (for Phase 2, if approved)
- **New:** `scripts/migrate_agent.py` (SSH-driven cross-host migrator)
- **Reuse:** `app/manager.py:683 _migrate_cli_session` (encoding), `app/db.py change_scope` (path rewrite)
- **Read-only ref:** `app/session.py:206 _make_backend`, `app/manager.py:1136 auto_resume_all`
- **Config:** target `.env` (`ANTHROPIC_API_KEY` preferred, `HTTPS_PROXY` for VPS)
