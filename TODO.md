# Orchestra TODO

## From Codex Round 5

- [ ] DB calls через `asyncio.to_thread()` — sync SQLite блокирует event loop (до 5с с busy_timeout). Для dev tool не критично, но правильнее обернуть
- [x] `_run_turn()` exceptions — done callback логирует + ставит ERROR
- [x] Auto-resume rehydrate все поля из DB (worktree_path, branch, created_at)
- [ ] `.claude/agents/*.md` парсинг frontmatter — в спеке обещано, не реализовано. Либо добавить, либо убрать из спеки

## UX

- [ ] Dashboard: показать ошибку если создание оркестратора зафейлилось (сейчас modal показывает текст ошибки, но мелко)
- [ ] **Inter-agent messages visible in chat** — видеть ВСЮ коммуникацию между агентами. Каждый агент получает цвет. Когда worker пишет orchestrator'у — бабл с цветом worker'а и подписью "worker-1 → orchestrator". И наоборот. Любой agent→agent message видно в чате выбранного агента
- [x] **Streaming text** — StreamEvent chunks rendered live
- [ ] **Worker templates** — `.claude/agents/*.md` файлы как шаблоны воркеров. При `spawn_worker` можно указать template (необязательно). Оркестратор может создавать новые шаблоны через filesystem. Dashboard: dropdown с доступными шаблонами + MCP тул `list_templates`
- [ ] **Custom system prompt при спавне** — оркестратор может дописать доп. инструкции поверх шаблона при создании воркера (параметр `extra_instructions` в `spawn_worker`). Шаблон + доп. инструкции = финальный system prompt
- [ ] **Media in chat** — MCP тул для агентов чтобы показывать картинки/файлы/диаграммы в дашборде. Агент вызывает `show_media(path="/tmp/screenshot.png")` → dashboard рендерит `<img>`. Поддержка: PNG, JPG, SVG, может markdown с mermaid
- [ ] **Inter-agent inject ordering** — когда worker шлёт сообщение orchestrator'у через MCP во время tool execution, inject ставится в очередь внутри Claude CLI. Сообщение не теряется, но порядок в чате может выглядеть странно (tool_result после inject). Ограничение SDK, не наш баг. Возможный workaround: буферизовать inject и показывать после текущего tool result
- [ ] **spawn_worker latency** — первый spawn ~60с (worktree + SDK CLI start + connect). Это нормально, но можно pre-warm SDK или показывать прогресс в UI
## ~~Data Layer Refactor (single source of truth)~~ ✅ DONE

Реализовано в v1.1.0:
- `SessionManager.archived: dict[str, dict]` — stopped/error сессии в памяти
- `load_archived()` загружает из DB при startup
- `list_sessions()` — чисто из памяти, без DB merge
- `stop()` перемещает active → archived
- tools.py: все через `_manager`, ноль прямых DB imports (кроме get_logs)
- main.py: все через manager, DB только для init_db и get_logs

- [x] **kill_worker для DB-only sessions** — реализовано через `archive_by_id()` в manager

## SDK Bugs & Stability (claude-agent-sdk v0.1.72, 122 open issues)

**ROOT CAUSE зависания оркестратора**: SDK issue #701 — CLI hang after 40+ tool calls (600s timeout).
Вторая причина: #425 — receive_messages() backpressure hang при break в generator.

- [ ] **Pin SDK version** — `claude-agent-sdk>=0.1.70,<0.2`. Без пина любой `uv sync` ломает всё
- [ ] **Per-turn timeout** — обернуть `_listen_loop` в `asyncio.wait_for(timeout=300)`. SDK issue #533/#701 — silent 10-min hangs. При timeout → interrupt + retry или ERROR
- [ ] **Drain receive_messages fully** — _listen_loop делает `break` на ResultMessage. По #425 это может оставить backpressure. Добавить drain после break или async for без break
- [ ] **max_turns per role** — orchestrator=100, worker=25. Кеша добавил 25 глобально, но оркестратору мало
- [ ] **Zombie MCP cleanup** — SDK #889: close() не убивает grandchildren. Добавить `start_new_session=True` при spawn CLI + `os.killpg()` в _cleanup_client
- [ ] **Heartbeat watchdog** — как claude_code_agent_farm: таймер на каждый turn, если нет нового лога 5+ мин → считать stuck, interrupt + retry
- [ ] **Auto-compact** — при context > 30% вызывать SDK `compact()`. claude-mpm делает auto-summary at 70/85/95%. Opus деградирует после 40%
- [ ] **BaseExceptionGroup guard** — SDK #890: второй query() в том же loop крашит. Обернуть в try/except BaseExceptionGroup
- [ ] **Resume safety** — SDK #856: resume после tool_use = 400 error. При resume failure → start fresh session с compact summary
