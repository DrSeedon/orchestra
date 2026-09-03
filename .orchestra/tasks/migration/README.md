# migrate_agent.py — move an orchestrator between servers

Copies an Orchestra orchestrator **and all its non-archived workers** (full durable state)
from one host to another over SSH. After it runs, restart Orchestra on the target — its
`auto_resume_all` replays the transcripts and brings every agent back with intact context.

## What it copies
| Store | Source | What |
|---|---|---|
| SQLite `sessions` row | `data/orchestra.db` | one row per agent, host paths rewritten |
| `logs` / `inbox` / `subagents` | same DB (FK = `sessions.id`) | chat log, pending msgs, subagent telemetry |
| CLI transcript | `~/.claude/projects/<enc-cwd>/<session_id>.jsonl` (+ v2.1 `<id>/` subdir) | the actual conversation context |
| git worktrees | `<orchestra>/worktrees/<slug>/<worker>` | each worker's branch (via `git bundle`) + recreated worktree |
| `docs/workers/<name>.md` | scope repo | worker persistent memory |
| `CLAUDE.md` | scope repo | project rules |

## Usage
```bash
python scripts/migrate_agent.py \
  --name ParsingMaxim \
  --from root@laptop --to root@158.220.127.161 \
  --from-orchestra /mnt/data/Projects/Python/orchestra \
  --to-orchestra   /home/kesha/orchestra \
  --from-scope /mnt/data/Projects/Python/Parsing \
  --to-scope   /home/kesha/projects/Parsing \
  [--dry-run]
```
`--dry-run` lists the orchestrator + workers and the rewritten scopes without touching the target.

## After it finishes
1. On target: `sudo systemctl restart orchestra` → `auto_resume_all` resumes every migrated agent.
2. Verify: send a test message, ask "what were you working on?" — context should be intact.
3. **Retire the source** (`kill_worker`/archive) so the same `session_id` isn't live on two hosts
   (two live copies → divergent transcripts + double rate-limit burn).

## Preconditions (fails loud otherwise)
- Orchestrator + every non-archived worker must be **IDLE** (no running turn).
- Target already `claude login`-authenticated and has the scope git repo present.
- **CLI version parity** source↔target (the JSONL transcript format is internal and drifts
  between `claude` releases — mismatch can break replay).

## Path rewriting (the two encodings)
- **CLI transcript dir**: `cwd.replace('/','-').lstrip('-')` — case preserved
  (mirrors `manager._migrate_cli_session`).
- **Worktree subdir**: `<orchestra>/worktrees/<slugify(scope)>/<name>`, `slugify` = non-alnum→`-`,
  lowercased (mirrors `workspace._slugify`).

Only `scope`, `cwd`, `worktree_path` are rewritten. **`id`, `session_id`, `session_id_history`,
model, role, costs, parent linkage stay as-is** — they're not host-bound (`session_id` is the
resume key; `sessions.id` is the FK target for child tables — two different UUIDs, do not confuse).

## Mechanics notes
- Host↔host transfer goes through a local temp hop (`scp src→/tmp→dst`), so no host-to-host SSH
  trust is required.
- Worker branches move via `git bundle` (works even without a shared git remote).
- DB writes are applied as one `BEGIN…COMMIT` script; archived name/scope dups on the target are
  deleted first to free `UNIQUE(name,scope)`.
