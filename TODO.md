# Orchestra TODO

## Bugs
- [ ] **Одинаковые цвета воркеров** — _pick_color() даёт дубли при auto_resume_all
- [ ] **Clipboard на HTTP** — navigator.clipboard требует HTTPS. Fallback на execCommand('copy')

## Next
- [ ] **DNS + SSL** — orchestra.zahoron.ru + certbot
- [ ] **Раздробить app.js (4200+ строк)** — разбить на модули: chat.js, tools.js, tasks.js, files.js, agents.js, sse.js
- [ ] **Реальный cost с кешем** — считать real_cost_usd из cache_read/cache_create/input/output tokens по реальным ценам
- [ ] **TG pinned status** — закреплённое сообщение в каждом топике, обновляется после turn_end

## Ideas
- [ ] **Cross-server messaging** — связь между Orchestra на разных серверах через webhook
- [ ] **Данные в файлах проекта** — таски/сессии в `.orchestra/` папке, git sync между машинами
- [ ] **Emergency failover** — автопереключение на API ключи если подписка слетела

## Later
- [ ] **Dashboard streaming** — live token streaming
- [ ] **Task Context Space** — task_context folder при spawn
- [ ] **HTML артефакты** — preview HTML в дашборде
- [ ] **Worker templates** — preset system_prompt для частых ролей
- [ ] **Local Bot API на VPS** — для тяжёлых файлов (>20MB)
