# Orchestra TODO

## From Codex Round 5

- [ ] DB calls через `asyncio.to_thread()` — sync SQLite блокирует event loop (до 5с с busy_timeout). Для dev tool не критично, но правильнее обернуть
- [ ] `_run_turn()` exceptions в background task — unobserved. Добавить done callback для логирования. Сейчас status → ERROR виден в poll, но exception теряется
- [ ] Auto-resume rehydrate все поля из DB (worktree_path, branch, created_at)
- [ ] `.claude/agents/*.md` парсинг frontmatter — в спеке обещано, не реализовано. Либо добавить, либо убрать из спеки

## UX

- [ ] Dashboard: показать ошибку если создание оркестратора зафейлилось (сейчас modal показывает текст ошибки, но мелко)
- [ ] **Inter-agent messages visible in chat** — видеть ВСЮ коммуникацию между агентами. Каждый агент получает цвет. Когда worker пишет orchestrator'у — бабл с цветом worker'а и подписью "worker-1 → orchestrator". И наоборот. Любой agent→agent message видно в чате выбранного агента
- [ ] **Streaming text** — видеть текст по мере генерации (посимвольно/чанками), а не целиком после ResultMessage. SDK поддерживает `include_partial_messages=True` — нужно обрабатывать partial content в `_listen_loop` и пушить в логи инкрементально
