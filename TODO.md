# Orchestra TODO

## Next
- [ ] **VPS migration** — перенос Orchestra на VPS. Ресёрч: требования (RAM/CPU/disk), какой VPS, systemd setup, DB миграция, TG bridge, прокси, git worktrees, 24/7 доступ

## Later
- [ ] **Emergency migrate** — кнопка "⚡ Migrate to GPT". Server-side: логи → spawn на GPT → inject summary
- [ ] **Dashboard streaming** — `include_partial_messages=True`, live token streaming
- [ ] **Task Context Space** — `task_context` folder при spawn, воркер читает TASK.md/PLAN.md автоматом
- [ ] **HTML артефакты** — preview HTML в дашборде + send_file в TG
- [ ] **Worker templates** — preset system_prompt для частых ролей
