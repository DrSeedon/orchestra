# Orchestra TODO

## Bugs
- [ ] **Task linking "FAILED — unknown"** — link_commits_to_task не парсит таск из коммит-сообщения после merge. manager.py
- [ ] **send_message 500 после рестарта** — idle воркеры не получают сообщения после restart. Workaround: respawn
- [ ] **Worker DONE to wrong parent** — report уходит parent_name вместо того кто дал задачу
- [ ] **Одинаковые цвета воркеров** — _pick_color() даёт дубли при auto_resume_all
- [ ] **Clipboard на HTTP** — navigator.clipboard требует HTTPS. Fallback на execCommand('copy')
- [ ] **payment_receive дробные** — amount в тысячах (int), 29.5k невозможно. Нужен float или в рублях (фидбэк VPS ParsingMaxim)
- [ ] **VPS прокси нестабильны** — SSH tunnel'ы зависают, Tinyproxy/Squid теряют коннекты. Частично пофикшено (#44 auto-restart)

## Next
- [ ] **Codex-review → skill** — перенести codex-review из module в skill codex-debate (объединить). Освободит ~50 строк из каждого промпта. Задача для prompt-engineer
- [ ] **worker_wip показывать ctx%** — сейчас нужен list_agents отдельно (фидбэк seedon)
- [ ] **Hot-reload system_prompt** — менять промпт воркера на лету без респавна (фидбэк seedon)
- [ ] **merge_worker показывать diff** — changeset перед мержем, не слепой мерж (фидбэк seedon)
- [ ] **TG топики для воркеров** — создавать TG топики ТОЛЬКО когда воркер реально работает (running). В названии: `<worker-name> | <orchestrator-name>`. Появляется при start running, скрывается/удаляется при idle/kill. Логи воркера стримятся в его топик пока работает. Idle воркеры НЕ должны иметь топик — только активные
- [ ] **Per-role idle_timeout** — `idle_timeout: 900` в YAML frontmatter роли
- [ ] **DNS + SSL** — orchestra.zahoron.ru + certbot
- [ ] **Раздробить app.js (4500+ строк)** — модули: chat.js, tools.js, tasks.js, files.js, agents.js, sse.js
- [ ] **TG verbosity** — фильтрация tool/status по уровню TG_VERBOSITY=low|medium|high (#16)
- [ ] **Scope-level spawn lock** — _session_locks мёртвый код, HTTP spawn мимо очереди (deferred from #40)
- [ ] **Persist _pending_messages** — memory-only queue теряется при рестарте (deferred from #40)
- [ ] **Auto-rebase перед merge** — workspace.py, убрать конфликты squash merge

## Ideas
- [ ] **Codex как streaming tool** — видеть прогресс codex в реальном времени
- [ ] **Cross-server messaging** — связь между Orchestra на разных серверах
- [ ] **Emergency failover** — автопереключение на API ключи если подписка слетела
- [ ] **Best-of-N solving** — N воркеров на одну задачу, reviewer выбирает лучший

## Done (move to CHANGELOG)
