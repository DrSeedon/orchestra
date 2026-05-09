# Orchestra TODO

## Next
- [ ] **Auto-compact** — trigger at context >90% automatically (platform-level). Tool `compact_worker` already works — need auto-trigger in session.py after ResultMessage
- [ ] **kill_worker fix** — Internal Server Error for stale worktrees
- [ ] **Diff view for Edit tool** — parse old_string/new_string, render red/green diff on frontend
- [ ] **System prompt viewer** — button in agent info shows full system_prompt
- [ ] **File preview in dashboard** — click .md/.txt/.png opens in modal
- [ ] **TG media support** — photos/docs/voice in TG bridge (plan in docs/tg-media/PLAN.md)
- [ ] **Global SSE stream** — replace polling with single EventSource for all dashboard updates
- [ ] **Orchestra skill** — `/orchestra` slash command from any Claude Code session
- [ ] **Watchdog** — auto-ping worker if idle >10min without send_message after receiving task
