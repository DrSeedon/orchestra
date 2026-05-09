# Orchestra TODO

## Done ✅
- [x] External stdio MCP server (no in-process deadlocks)
- [x] Simplified session.py (fresh client per turn)
- [x] Worker Inbox + Job Registry
- [x] Turn timeout (600s)
- [x] Smart color picker, SSE realtime logs, Offline CSS
- [x] Systemd service, Health check loop, Dynamic cli_path
- [x] File browser panel, drag-and-drop
- [x] Delete orchestrator, Remember last orchestrator
- [x] Stop vs Delete (unload vs remove+cascade)
- [x] Context % (last iteration, per-model 200k/1M, cache hit %)
- [x] Context bar in agent list + status badges
- [x] Auto-report + context warning >90%
- [x] Inject messages to running agents
- [x] Prompt hot-reload (read from disk, inject on first turn)
- [x] Base/orchestrator/worker shared prompts
- [x] Cross-project messaging (list_orchestrators, ensure_loaded_any)
- [x] TG Bridge integrated in FastAPI (topics, expandable blockquotes, tool icons, tool+result merged)
- [x] notify_kesha + Kesha inbox server
- [x] report_bug MCP tool → BUGS.md
- [x] compact_worker MCP tool (summary → reset → continue)
- [x] Restart button (⟳, sudo -n, SIGINT, 2s timeout)
- [x] Orchestrator tabs (pill buttons, recent-first)
- [x] Image paste (Ctrl+V, md5 dedup)
- [x] Draft per agent (unsent text preserved)
- [x] Tool icons (🖥 Bash, 📖 Read, 🎼 orchestra)
- [x] Tool+result in one bubble (frontend + TG)
- [x] URL linkify in tool_result, click-to-expand
- [x] AskUserQuestion + run_in_background blocked via can_use_tool deny
- [x] MCP absolute path, no .mcp.json copy to worktrees
- [x] Worker CWD rules, trailing slash fix, ghost workers fix
- [x] Multi-repo tested (Parsing 5 sub-repos)
- [x] Codex review integration (2 rounds, 6 blocking fixed)

## Next
- [ ] **Auto-compact** — trigger at context >90% automatically (platform-level, not prompt). Compact already works via compact_worker MCP tool — need auto-trigger in session.py after ResultMessage
- [ ] **kill_worker fix** — Internal Server Error for some workers (stale worktree/git state)
- [ ] **Diff view for Edit tool** — parse old_string/new_string, render red/green diff on frontend
- [ ] **System prompt viewer** — button in agent info panel shows full system_prompt
- [ ] **File preview in dashboard** — click .md/.txt/.png opens in modal
- [ ] **TG media support** — photos/docs/voice in TG bridge (plan in docs/tg-media/PLAN.md)
- [ ] **Global SSE stream** — replace polling with single EventSource for all dashboard updates
- [ ] **Orchestra skill** — `/orchestra` slash command from any Claude Code session
- [ ] **Watchdog** — auto-ping worker if idle >10min without send_message after receiving task
