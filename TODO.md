# Orchestra TODO

## Bugs
- [ ] **Одинаковые цвета воркеров** — _pick_color() даёт дубли при auto_resume_all
- [ ] **Clipboard на HTTP** — navigator.clipboard требует HTTPS. Fallback на execCommand('copy')
- [ ] **VPS прокси нестабильны** — SSH tunnel'ы зависают. Частично пофикшено (#44 auto-restart)

## Next
- [ ] **Auto-capture при compact** — после compact сохранять ключевые факты из summary в `docs/session-memory.md`. Агент при следующем spawn получает accumulated knowledge. Идея из AgentMemory
- [ ] **Typed memory в CLAUDE.md** — разделить на секции: facts (семантика), procedures (как делать), history (что было). Сейчас всё в куче — агент тратит tokens на поиск. Идея из AgentMemory
- [ ] **Stale memory detection** — при compact проверять memory файл. Записи старше N дней без упоминания → пометить stale. Идея из AgentMemory
- [ ] **Cross-agent context inject** — при send_message воркеру автоматически приложить `docs/tasks/<id>/research.md` если есть. Не semantic search, просто file attach
- [ ] **worker_wip показывать ctx%** — сейчас нужен list_agents отдельно (фидбэк seedon)
- [ ] **Hot-reload system_prompt** — менять промпт воркера на лету без респавна (фидбэк seedon)
- [ ] **merge_worker показывать diff** — changeset перед мержем, не слепой мерж (фидбэк seedon)
- [ ] **Per-role idle_timeout** — `idle_timeout: 900` в YAML frontmatter роли
- [ ] **DNS + SSL** — orchestra.zahoron.ru + certbot
- [ ] **Раздробить app.js (4500+ строк)** — модули: chat.js, tools.js, tasks.js, files.js, agents.js, sse.js
- [ ] **TG verbosity** — фильтрация tool/status по уровню TG_VERBOSITY=low|medium|high (#16)
- [ ] **Scope-level spawn lock** — _session_locks мёртвый код, HTTP spawn мимо очереди (deferred from #40)
- [ ] **Persist _pending_messages** — memory-only queue теряется при рестарте (deferred from #40)

## Ideas
- [ ] **Codex как streaming tool** — видеть прогресс codex в реальном времени
- [ ] **Cross-server messaging** — связь между Orchestra на разных серверах
- [ ] **Emergency failover** — автопереключение на API ключи если подписка слетела
- [ ] **Best-of-N solving** — N воркеров на одну задачу, reviewer выбирает лучший
- [ ] **TG топики для воркеров** — создавать только когда воркер running, скрывать при idle/kill
