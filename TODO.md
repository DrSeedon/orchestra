# Orchestra TODO

## Bugs
- [ ] **Одинаковые цвета воркеров** — _pick_color() даёт дубли при auto_resume_all
- [ ] **Clipboard на HTTP** — navigator.clipboard требует HTTPS. Fallback на execCommand('copy')
- [ ] **send_message 500 после рестарта** — idle воркеры не получают сообщения после restart. Workaround: respawn
- [ ] **send_file ошибка без текста** — MCP send_file возвращает пустую ошибку, нет диагностики

## Next
- [ ] **TG очередь сообщений** — сейчас non-important (tool/status) дропаются при gap < 3с. Нужна asyncio.Queue с rate-limit вместо drop. Текущий _tg_send_safe дропает ~70% tool-логов при активной работе воркера. TG лимит группы ~20 msg/min, наш throttle 0.33 msg/s = 20 msg/min — можно снизить интервал до 1-2с или добавить батчинг
- [ ] **DNS + SSL** — orchestra.zahoron.ru + certbot
- [ ] **Раздробить app.js (4500+ строк)** — разбить на модули: chat.js, tools.js, tasks.js, files.js, agents.js, sse.js
- [ ] **Модульные промпты** — вынести TaskManager/YouGile/платежи в опциональные модули (#15)
- [ ] **TG verbosity** — фильтрация tool/status по уровню TG_VERBOSITY=low|medium|high (#16)

## Ideas
- [ ] **Cross-server messaging** — связь между Orchestra на разных серверах через webhook
- [ ] **Данные в файлах проекта** — таски/сессии в `.orchestra/` папке, git sync между машинами
- [ ] **Emergency failover** — автопереключение на API ключи если подписка слетела
- [ ] **Soft model swap** — stop → save summary → respawn с новой моделью + summary в промпт

## Later
- [ ] **Dashboard streaming** — live token streaming
- [ ] **Task Context Space** — task_context folder при spawn
- [ ] **HTML артефакты** — preview HTML в дашборде
- [ ] **Worker templates** — preset system_prompt для частых ролей
- [ ] **Local Bot API на VPS** — для тяжёлых файлов (>20MB)
- [ ] **TG pinned status** — закреплённое сообщение в каждом топике
