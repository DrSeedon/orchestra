# Orchestra TODO

## Next
- [ ] **Auto-compact** — trigger at context >90% automatically (platform-level). Tool `compact_worker` already works — need auto-trigger in session.py after ResultMessage
- [ ] **Global SSE stream** — replace polling with single EventSource for all dashboard updates
- [ ] **Orchestra skill** — `/orchestra` slash command from any Claude Code session
- [ ] **Watchdog** — auto-ping worker if idle >10min without send_message after receiving task
