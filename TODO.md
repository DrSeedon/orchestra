# Orchestra TODO

## Bugs
- [ ] **Compact перебивается входящими сообщениями** — compact стартовал, пришёл auto-report от воркера → compact вернул empty summary → listener died → каскад ошибок. Нужно: блокировать входящие send() пока compact идёт, или queue их
- [ ] **Taskmanager worktree divergence** — после merge worktree остаётся на старом коде (ALLOWED_TRANSITIONS возвращается). Нужно: switch_worker_branch после каждого merge

## Next
- [ ] **VPS migration** — OVH отменил. Plan B: Hostinger/Coingate или Timeweb upgrade. Ресёрч: `docs/research/vps-migration.md`
- [ ] **Worker description в list_agents** — feature request от Mods-orchestrator: показывать роль/описание воркера + task_id
- [ ] **TG pinned status** — закреплённое сообщение в каждом топике, обновляется после turn_end

## Later
- [ ] **Emergency migrate** — кнопка "⚡ Migrate to GPT"
- [ ] **Dashboard streaming** — live token streaming
- [ ] **Task Context Space** — task_context folder при spawn
- [ ] **HTML артефакты** — preview HTML в дашборде
- [ ] **Worker templates** — preset system_prompt для частых ролей
