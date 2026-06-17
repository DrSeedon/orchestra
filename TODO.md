# Orchestra TODO

## Bugs
- [ ] **Тест-изоляция: test_default_equals_upstream загрязняет 106 тестов** — `load_pipeline.cache_clear()` + monkeypatch `PIPELINES_DIR`. Pre-existing. Deselect в CI
- [ ] **Pending tm_sync_log без fire в CLI-контексте** — `_fire_sync` пишет pending до schedule; нет loop → запись висит
- [ ] **TG media buffer race (P2)** — _resolve_media после timeout-flush может записать в чужой слот. Нужен generation counter
- [ ] **Message disappears on agent switch** — SSE reconnect gap. 300ms delay added (partial fix)
- [ ] **TG дубли expandable+image** — partially fixed (skip expandable for Read/Grep/Bash/Glob when image sent), but Edit/Write may still duplicate

## In Progress
- [ ] **tg_bridge split P5** — refactor-tg worker (Opus 4.8, ctx:12%) has research+plan done, awaiting impl approval. Split into tg_bot/tg_stream/tg_render/tg_topics

## Next
- [ ] **send_message auto-switch (#80)** — task_id param for auto switch_branch before delivery. Priority HIGH
- [ ] **Sound notification on idle (#79)** — Web Audio API + browser Notification when agent finishes
- [ ] **Auto-learning из ошибок (#76)** — Self-Harness: weakness mining → harness proposal → validation
- [ ] **OpenRouter Fusion (#78)** — multi-model deliberation API for code review
- [ ] **Design review скилл** — impeccable + taste-skill for frontend workers
- [ ] **merge_worker показывать diff** — changeset перед мержем
- [ ] **Раздробить app.js (4500+ строк)** — модули: chat.js, tools.js, tasks.js, files.js, agents.js, sse.js
- [ ] **TG verbosity** — фильтрация tool/status по уровню TG_VERBOSITY=low|medium|high
- [ ] **VPS parsing cost guard** — предупреждать/блокировать turn'ы дороже $X

## Ideas
- [ ] **Codex как streaming tool** — видеть прогресс codex в реальном времени
- [ ] **Cross-server messaging** — связь между Orchestra на разных серверах
- [ ] **Emergency failover** — автопереключение на API ключи если подписка слетела
- [ ] **Best-of-N solving** — N воркеров, reviewer выбирает лучший (или OpenRouter Fusion)
