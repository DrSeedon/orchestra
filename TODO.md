# Orchestra TODO

## Next
- [ ] **VPS migration** — перенос Orchestra на VPS. OVH отменил — пробовать Hostinger/Coingate или Timeweb upgrade. Ресёрч: `docs/research/vps-migration.md`
- [ ] **TG pinned status** — закреплённое сообщение в каждом топике оркестратора, обновляется после каждого turn_end. Содержит: статус, воркеры + статусы, текущая задача, context %, debt. `bot.pin_chat_message()` + `bot.edit_message_text()`

## Later
- [ ] **Emergency migrate** — кнопка "⚡ Migrate to GPT". Server-side: логи → spawn на GPT → inject summary
- [ ] **Dashboard streaming** — `include_partial_messages=True`, live token streaming
- [ ] **Task Context Space** — `task_context` folder при spawn, воркер читает TASK.md/PLAN.md автоматом
- [ ] **HTML артефакты** — preview HTML в дашборде + send_file в TG
- [ ] **Worker templates** — preset system_prompt для частых ролей
