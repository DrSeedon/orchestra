# Orchestra TODO

## Bugs
- [ ] **Compact перебивается входящими сообщениями** (ORC-4) — compact стартовал, пришёл auto-report от воркера → compact вернул empty summary → listener died → каскад. Нужно: блокировать send() пока compact идёт, или queue
- [ ] **Taskmanager worktree divergence** — после merge worktree остаётся на старом коде. Нужно: switch_worker_branch после каждого merge
- [ ] **Одинаковые цвета воркеров** — _pick_color() даёт дубли при auto_resume_all

## Next
- [ ] **VPS migration** — OVH отменил. Plan B: Hostinger/Coingate или Timeweb upgrade
- [ ] **TG pinned status** — закреплённое сообщение в каждом топике, обновляется после turn_end

## Later
- [ ] **Emergency migrate** — кнопка "⚡ Migrate to GPT"
- [ ] **Dashboard streaming** — live token streaming
- [ ] **Task Context Space** — task_context folder при spawn
- [ ] **HTML артефакты** — preview HTML в дашборде
- [ ] **Worker templates** — preset system_prompt для частых ролей
