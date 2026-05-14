# Orchestra TODO

## Now
- [ ] **TG persistent client fix** — heartbeat/watchdog уже смерджен (v2.6.0). Мониторить после рестарта
- [ ] **Dashboard streaming (Phase 1)** — flip `include_partial_messages=True`, add `_ui_queue` per session, rewrite SSE endpoint to drain queue instead of polling DB. ~2-3h. Ресёрч: `docs/research/streaming-redesign.md`
- [ ] **Git status in agent cards** — extend sidebar card: `main+3 💾0 "fix: update endpoint"`. API: `GET /api/git-status?scope=`. 10s cache. ~2h. Ресёрч: `docs/research/git-tree-view.md`

## Later
- [ ] **TG streaming (Phase 2)** — TgStreamer state machine replaces stream_logs polling. 5s throttle + batching. ~3-4h. Ресёрч: `docs/research/streaming-redesign.md`
- [ ] **Auto-merge worker** — `merge_worktree_to_main()` with `git merge-tree` precheck. FF-first → 3-way fallback. fcntl lock. Ресёрч: `docs/research/auto-merge.md`
- [ ] **Task Context Space** — `task_context` param in `spawn_worker()`, auto-adds docs folder to prompt
- [ ] **HTML артефакты** — preview HTML в дашборде + send_file в TG
