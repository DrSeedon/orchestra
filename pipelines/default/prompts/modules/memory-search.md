<memory-search>
## Semantic memory — `search_memory` tool

Orchestra indexes this project's knowledge into a semantic memory: past `docs/tasks/*.md`
(research, plans, reports, retros), `CLAUDE.md`, `BUGS.md`, and agent messages (DONE reports,
decisions, coordination). Use `search_memory(query)` to retrieve it by meaning — not grep.

**When to call it (deterministic triggers):**
- You lost context after a compact/restart and need to recall a past decision or approach.
- Before researching/implementing something that "feels done before" — check if a past task
  already solved it (`search_memory("how we handled X")`) instead of redoing the work.
- You hit a bug that smells familiar — `search_memory("<error / symptom>")` may surface the
  prior root-cause and fix.

**When NOT to call it:** you already have the file open, or you need an exact string/line
(use grep). Memory is for "what did we learn / decide about X", not exact-match lookup.

Searches YOUR project only. `cross_project=True` widens to all projects — rarely needed, and
only for genuinely cross-cutting infra questions. Results carry attribution
(`[file: path]` or `[log: kind from author]`) so you can open the full source.
</memory-search>
