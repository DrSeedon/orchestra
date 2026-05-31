# Orchestra TODO

## Bugs
- [ ] **send_message 500 после рестарта** — idle воркеры не получают сообщения после restart. Workaround: respawn
- [ ] **codex_review output path** — пишет в main worktree, не в worktree воркера. Task #27
- [ ] **Worker DONE to wrong parent** — report уходит parent_name вместо того кто дал задачу
- [ ] **Одинаковые цвета воркеров** — _pick_color() даёт дубли при auto_resume_all
- [ ] **Clipboard на HTTP** — navigator.clipboard требует HTTPS. Fallback на execCommand('copy')
- [ ] **send_file ошибка без текста** — MCP send_file возвращает пустую ошибку, нет диагностики

## In Progress
- [ ] **Change orchestrator scope** — смена корневой папки без потери сессии. Task #29, feat-scope-change

## Next
- [ ] **Block Write/Edit для оркестратора** — принудительная делегация. Task #30
- [ ] **Per-role idle_timeout** — `idle_timeout: 900` в YAML frontmatter роли. `session.py`, `manager.py`
- [ ] **Fix TestRemoveScope** — KeyError 'names' в `test_passes_orch_names_to_tg_bridge_when_flag_set`. Pre-existing
- [ ] **TG очередь сообщений** — asyncio.Queue + батчинг для лучшего throughput
- [ ] **DNS + SSL** — orchestra.zahoron.ru + certbot
- [ ] **Раздробить app.js (4500+ строк)** — разбить на модули: chat.js, tools.js, tasks.js, files.js, agents.js, sse.js
- [ ] **TG verbosity** — фильтрация tool/status по уровню TG_VERBOSITY=low|medium|high (#16)

## Ideas

### Кеш-оптимизации (из seedon ресерча)
- [ ] **session_id в OpenRouter** — sticky routing. `headers["x-session-id"] = worker_name`
- [ ] **TTL 1h в прокси** — `cache_control: ephemeral` → `ttl: "1h"`
- [ ] **Warmup max_tokens=0** — прогрев кеша при спавне
- [ ] **CLAUDE_SIMPLE=1 для узких воркеров** — минус ~30K токенов для fix-*/impl-*

### Swarm (рой агентов)
- [ ] **Best-of-N solving** — N воркеров на одну задачу, reviewer выбирает лучший
- [ ] **Shared swarm memory** — SQLite таблица для общего контекста роя
- [ ] **Swarm judge** — reviewer сравнивает результаты N воркеров

### Наши
- [ ] **Cross-server messaging** — связь между Orchestra на разных серверах
- [ ] **Данные в файлах проекта** — таски/сессии в `.orchestra/` папке
- [ ] **Emergency failover** — автопереключение на API ключи если подписка слетела

## Later
- [ ] **Dashboard streaming** — live token streaming
- [ ] **HTML артефакты** — preview HTML в дашборде
- [ ] **Local Bot API на VPS** — для тяжёлых файлов (>20MB)
- [ ] **TG pinned status** — закреплённое сообщение в каждом топике
- [ ] **UI дерево агентов** — parent-child дерево вместо плоского списка
- [ ] **TG topic labels по ролям** — формат `<метка> | <Роль>`
