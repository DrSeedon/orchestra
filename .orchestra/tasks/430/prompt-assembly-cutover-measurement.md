# Prompt assembly across mixed project layouts

## Pre-fix scratch measurement

Environment: two temporary canonical Git repositories plus an isolated SQLite; production
`data/orchestra.db` and registered fleet checkouts were not opened.

The assembled `full-cycle` prompt contained:

```text
<memory-search>
## Project memory — file-first mode

**Mandatory pre-work order:** `pwd` → this memory gate → frame/restate → first
`Read`/`Grep`/code scan. The gate has TWO steps, both before your first `Read`/`Grep`.

`ORCHESTRA_LAYOUT_MISSING` or `ORCHESTRA_LAYOUT_PARTIAL` → stop and run the command from the error: `scripts/migrate_orchestra_layout.py --repair <absolute-repository>`. Never fall back to the old path.

**Step 1 — the knowledge base, `.orchestra/kb/`.** Read `.orchestra/kb/README.md`, pick every topic that
```

The prompt was never delivered. Old layout returned:

```text
ORCHESTRA_LAYOUT_MISSING: .orchestra/layout.json is missing; repository=/tmp/orchestra-prompt-cutover-ix55ocna/old; repair: /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/move-dot-orchestra/.venv/bin/python /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/move-dot-orchestra/scripts/migrate_orchestra_layout.py --repair /tmp/orchestra-prompt-cutover-ix55ocna/old
```

Partial layout returned:

```text
ORCHESTRA_LAYOUT_MISSING: .orchestra/layout.json is missing; repository=/tmp/orchestra-prompt-cutover-ix55ocna/partial; repair: /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/move-dot-orchestra/.venv/bin/python /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/move-dot-orchestra/scripts/migrate_orchestra_layout.py --repair /tmp/orchestra-prompt-cutover-ix55ocna/partial
```

For both repositories, `SessionManager.create_session` raised the same `LayoutMigrationError`,
`manager.sessions` stayed at 0, and isolated DB session count stayed at 0. The old
`docs/workers/agent.md` was neither read nor returned as an empty memory block.

Conclusion: the agent stopped before receiving any prompt; this was a fleet-wide stop condition,
not a loud but recoverable failure inside memory-search.

## Stage-1 compatibility contract

- No `.orchestra/layout.json`: runtime prompt assembly may read personal memory from
  `docs/workers/`; if a partial project already has `.orchestra/workers/`, the new root wins.
- Valid `.orchestra/layout.json`: only `.orchestra/workers/` is read; the legacy root is never a
  fallback after cutover.
- Global mandatory prompt paths remain at the old address until every registered project receipt
  is `current`.

Post-fix isolated scratch output:

```json
{"db_sessions": 3, "in_memory_sessions": 3, "layouts": {"migrated": {"created": true, "layout_exists": true, "legacy_root_exists": false, "memory_marker_present": true}, "old": {"created": true, "layout_exists": false, "legacy_root_exists": true, "memory_marker_present": true}, "partial": {"created": true, "layout_exists": false, "legacy_root_exists": true, "memory_marker_present": true}}}
```
