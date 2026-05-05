# Orchestra TODO

## Done ✅
- [x] External stdio MCP server (no in-process deadlocks)
- [x] Simplified session.py (fresh client per turn)
- [x] Worker Inbox + Job Registry
- [x] Turn timeout (300s)
- [x] Smart color picker
- [x] SSE realtime logs
- [x] Offline CSS (Tailwind bundled)
- [x] Hiddify proxy everywhere
- [x] Systemd service
- [x] Health check loop
- [x] Dynamic cli_path
- [x] Auto sender tag

## Next
- [ ] SSE for session list/stats (not just logs)
- [ ] Worker templates — `.claude/agents/*.md` as presets
- [ ] Auto-compact at 30% context
- [ ] Media in chat (images/files from workers)
- [ ] Multi-orchestrator support in dashboard
- [ ] Worker restart with retry on failure
