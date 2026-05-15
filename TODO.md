# Orchestra TODO

## Later
- [ ] **Git commit → task link** — коммит с `PAR-42` в message → автопривязка к задаче + подсчёт LOC по diff. Rate ₽/LOC
- [ ] **LOC tracking per task** — считать строки по реальным коммитам. Привязка к PAR задачам
- [ ] **CI failure auto-routing** — PR fail → логи автоинжект воркеру → самофикс
- [ ] **Emergency migrate** — кнопка "⚡ Migrate to GPT". Server-side: логи → spawn на GPT → inject summary
- [ ] **Task Context Space** — `task_context` folder при spawn, воркер читает TASK.md/PLAN.md автоматом
- [ ] **Dashboard streaming** — `include_partial_messages=True`, live token streaming
- [ ] **HTML артефакты** — preview HTML в дашборде + send_file в TG
- [ ] **Worker templates** — preset system_prompt для частых ролей
