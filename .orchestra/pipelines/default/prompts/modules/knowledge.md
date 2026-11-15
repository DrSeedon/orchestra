<knowledge>
## Project memory, logs & knowledge base

Orchestra provides four distinct stores—use them freely as capabilities rather than rigid rituals:

1. **Conversation & voice logs (`search_logs`, `get_log_context`)**:
   - Before answering about past decisions, events or user instructions, search project logs (`search_logs` case-insensitive regex over user chat, voice transcripts and agent messages; pass `all_projects=true` or `kinds` when needed) and read hits with `get_log_context`, citing dates (owner decision, 2026-10-21).
   - Whenever reporting a zero/negative search or scan result, state exact coverage (sources, date range, record count and any truncation).

2. **Shared Knowledge Base (`.orchestra/kb/` + `.orchestra/kb/README.md`)**:
   - Stores verified findings that would be expensive to rediscover: non-obvious external behavior, empirical measurements, hard constraints and rejected approaches.
   - **Anti-garbage filter**: never write code/file inventories, paraphrases of standard docs, status logs or routine edit summaries into `.orchestra/kb/`. Update existing topic files instead of duplicating; any new `.orchestra/kb/<topic>.md` file requires a matching `- [name](topic.md) — search terms` line in `.orchestra/kb/README.md` so the platform index exposes it.
   - **Harness/prompt/routing change entries** (owner decision, 2026-10-18): record a verdict (`helped`, `hurt`, `no observed effect` or `confounded`) backed by a before/after contrast plus a `cue` naming when it applies (arXiv https://arxiv.org/abs/2610.14224).

3. **Task evidence (`.orchestra/tasks/<id>/`)**: raw outputs, benchmark artifacts, plans and task reports.

4. **Worker scratchpad (`.orchestra/workers/<name>.md`)**: optional, ultra-brief role notes injected into your own prompt; keep lean and never duplicate KB content.
</knowledge>
