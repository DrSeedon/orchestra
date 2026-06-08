# Orchestra Bug Reports

## Open

### 🔴 send_message 500 после рестарта
- **Reporter:** Parsing-orchestrator (2026-05-26)
- send_message к idle воркерам = 500 после restart Orchestra. Свежие воркеры работают
- **Status:** вероятно починен фиксами auto_resume + ensure_loaded_any (2026-06-03). Проверить после рестарта
- **Assignee:** проверка после ребута

### 🟡 Worker DONE report уходит parent_name вместо task giver
- **Reporter:** seedon-orchestrator (2026-05-31)
- Воркер спавнен orchestrator-A, задачу дал orchestrator-B через send_message. DONE уходит к A (parent)
- **Assignee:** backend (в работе 2026-06-04)

### 🟡 Ambiguous task linking: один номер таска в двух проектах
- **Reporter:** dev-lead (2026-05-31)
- link_commits_to_task не передаёт project-фильтр → ambiguity warning, коммиты не привязаны
- **Assignee:** backend (в работе 2026-06-04)

### 🟡 payment_receive + task prices в тысячах — теряются дробные (500₽)
- **Reporter:** ParsingMaxim (2026-06-01)
- Цены и платежи хранятся в тысячах, нельзя указать точную сумму
- **Assignee:** taskmanager (в работе 2026-06-04)

## Closed (2026-06-01)

- ✅ **codex_review output path** — решено: Codex через bash (cwd=worktree), не через MCP bg job
- ✅ **codex_review exec never writes output** — root cause: bg job timeout → no notification. Fixed in #41
- ✅ **Codex Reconnecting через прокси** — root cause: HTTPS_PROXY inherited. Fixed: strip proxy env
- ✅ **Deepgram SSL BAD_RECORD_MAC** — root cause: aiohttp trust_env=True + VLESS. Fixed: trust_env=False + certifi
- ✅ **send_file silent false-positive** — Fixed: validate TG response, explicit error
- ✅ **kill_worker удаляет логи** — Fixed: archive_session instead of delete_session
- ✅ **Zombie workers after restart** — Fixed: auto_resume_all filters archived
- ✅ **Merge конфликт после squash** — Fixed: auto-reset worktree after merge (#38)

## [2026-06-05 06:36 UTC] codex_review output path resolves to main repo, not worker worktree (repeat)
- **Reporter:** infra
- **Scope:** /mnt/data/Projects/Python/seedon
When worker infra (worktree at /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-seedon/infra) calls codex_review with relative output path like "docs/tasks/47/codex-review-plan.md", the bg job writes to /mnt/data/Projects/Python/seedon/docs/tasks/47/ (main repo CWD) instead of the worker's worktree. This is the same class of bug as the earlier "codex_review не видит diff суб-репо" report — the codex bg job runs in the context of the main Orchestra project, not the worker's isolated worktree. Workaround: orchestrator runs codex_review instead of worker, or use absolute worktree path in output param. This has happened 3+ times across tasks #34, #42, #47.

## [2026-06-05 11:52 UTC] Codex review (codex exec) unreachable — 403 Cloudflare / websocket refused
- **Reporter:** research-runtime
- **Scope:** /mnt/data/Projects/Python/seedon
codex-debate Quick Review failed for task #55. `codex exec` без прокси → 403 Forbidden от chatgpt.com/backend-api/codex/responses (cf-ray, Cloudflare geo/datacenter block). С Hiddify-прокси 12334 → websocket wss://chatgpt.com/backend-api/codex/responses Connection refused (os error 111). Auth ок (auth_mode chatgpt, id_token есть). Это сетевой блок: proxy 12334 маршрутизирует только Anthropic, а прямой IP geo-блокируется Cloudflare. Workers не могут запускать Codex review без рабочего маршрута до OpenAI. Воспроизводится 2/2.
