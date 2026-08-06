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

## Your own transcript — query it with code, don't re-read it

`search_memory` covers PAST tasks. Your CURRENT run is stored server-side too, and one call
returns it as structured JSON (`tool`, `tool_result`, `text`, `user_message`, each with `id` and
`ts`) — so you can grep, count and filter your own history instead of scrolling context. It
survives compaction, because it lives on the server, not in your window:

```bash
curl -s -H "Authorization: Bearer $INTERNAL_TOKEN" --get \
  --data-urlencode "scope=$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")" \
  "http://127.0.0.1:8888/api/sessions/$(basename "$(git rev-parse --show-toplevel)")/logs"
```

Both values derive themselves — run it as written. Never hand-write `scope`: it is the
REPOSITORY path (`/home/kesha/orchestra`), not the worktree directory name, and the endpoint
answers a bare `{"error":"not found"}` when it is wrong. Pipe into `python3 -c` and aggregate;
dumping the whole answer into context defeats the point.

Use it for questions about your own run — which files you already touched, what a command
printed 40 turns ago, how many times you retried something.
</memory-search>
