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
- [ ] **Opus MCP tool latency** — Opus с 55k+ context обрабатывает MCP tool calls медленно (3-4 минуты). Sonnet с маленьким контекстом — 6-7с. Причина: весь контекст отправляется в API на каждый tool call. Решение: compact context, или использовать Sonnet для оркестратора
- [ ] **kill_worker для DB-only sessions** — если воркер не в памяти, kill_worker не делает stop/archive, просто пишет текст. Нужно обновлять DB статус и переименовывать
