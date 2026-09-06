<knowledge-and-context>
## Knowledge and context (all agents)

Canonical project memory lives in `.orchestra/kb/`. Task artifacts are supporting evidence, not a
second memory store.

- Persist knowledge to files — write research results, solutions, configs to `.orchestra/` or `RESEARCH.md`. Context is lost on compaction/restart, files are not
- **Where your knowledge goes.** NEVER use the runtime's own memory directory (`~/.claude/projects/.../memory/`) — no agent here can read it back, and on this machine it does not exist. Durable knowledge goes to files in the repo: a lesson about how YOU work → `.orchestra/workers/<your-name>.md`; a rule for the project → its canonical owner under the project authoring policy; a research finding → the knowledge base (`.orchestra/kb/`) plus `.orchestra/tasks/<id>/`
- **Context economy:** every tool_result stays in your context and is re-read every turn. Minimize replay:
  - grep/search BEFORE full Read — find the lines you need, then Read with offset+limit
  - For literal-context search, use `grep -aboF '<literal>' <file>` and slice by byte offset in Python; avoid `.{0,N}` bounded windows (`N>=20`) for grep-like tools because of the V8-heap blowup path documented in `.orchestra/kb/grep-memory-blowup.md`.
  - Large exploration: spawn-capable roles may delegate a bounded slice; terminal workers report scope growth to their orchestrator instead of spawning
  - Workers: no narration between tool calls. One line before your first action, one at blockers, and the DONE report. Your thinking block does reasoning — don't duplicate in chat
</knowledge-and-context>
