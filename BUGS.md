# Orchestra Bug Reports

## Open

### 🔴 send_message 500 после рестарта
- **Reporter:** Parsing-orchestrator (2026-05-26)
- send_message к idle воркерам = 500 после restart Orchestra. Свежие воркеры работают
- **Workaround:** respawn воркера
- **Assignee:** backend

### 🟡 Worker DONE report уходит parent_name вместо task giver
- **Reporter:** seedon-orchestrator (2026-05-31)
- Воркер спавнен orchestrator-A, задачу дал orchestrator-B через send_message. DONE уходит к A (parent)
- **Assignee:** нет

### 🟡 Ambiguous task linking: один номер таска в двух проектах
- **Reporter:** dev-lead (2026-05-31)
- link_commits_to_task не передаёт project-фильтр → ambiguity warning, коммиты не привязаны
- **Severity:** low

### 🟡 payment_receive amount в тысячах — теряются дробные (500₽)
- **Reporter:** ParsingMaxim (2026-06-01)
- 29.5k невозможно передать, округляется до 29k
- **Severity:** low

## Closed (2026-06-01)

- ✅ **codex_review output path** — решено: Codex через bash (cwd=worktree), не через MCP bg job
- ✅ **codex_review exec never writes output** — root cause: bg job timeout → no notification. Fixed in #41
- ✅ **Codex Reconnecting через прокси** — root cause: HTTPS_PROXY inherited. Fixed: strip proxy env
- ✅ **Deepgram SSL BAD_RECORD_MAC** — root cause: aiohttp trust_env=True + VLESS. Fixed: trust_env=False + certifi
- ✅ **send_file silent false-positive** — Fixed: validate TG response, explicit error
- ✅ **kill_worker удаляет логи** — Fixed: archive_session instead of delete_session
- ✅ **Zombie workers after restart** — Fixed: auto_resume_all filters archived
- ✅ **Merge конфликт после squash** — Fixed: auto-reset worktree after merge (#38)
