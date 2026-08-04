<memory-search>
## Semantic memory — `search_memory` tool

**Mandatory pre-work order:** `pwd` → this memory gate → frame/restate → first
`Read`/`Grep`/code scan. At the gate, MUST call `search_memory("<goal + subsystem or symptom>")` for:
- research, investigation, audit, diagnosis, comparison, architecture, or planning;
- implementation/fix unless the task names the exact file and line/function to change;
- continuation after compact/restart.

Past tasks may already contain the answer, failed approaches, and decisions; skipping this
search repeats work and burns quota. Open attributed hits; no useful hit → inspect code normally.

**Skip only for:** an exact local edit naming file + line/function + desired change; typo/format-only
work; running a named command/test; current-status lookup. Use grep for exact strings/current lines.

Index: `docs/tasks/*.md`, `CLAUDE.md`, agent messages. Scope is this repo; fresh merges
can lag, so verify current code. Use `cross_project=True` only when the task explicitly spans
repositories or shared infrastructure across them.
</memory-search>
