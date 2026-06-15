# Orchestra TODO

## Bugs
- [ ] **Тест-изоляция: test_default_equals_upstream загрязняет 106 тестов** — `load_pipeline.cache_clear()` + monkeypatch `PIPELINES_DIR` травят все файлы после себя. Pre-existing. Гейт гоняет файл отдельно
- [ ] **test_upstream_markers_present_in_ours[orchestrator] падает на main** — тег `<task-management>` потерян при выносе промпт-модулей
- [ ] **Pending tm_sync_log без fire в CLI-контексте** — `_fire_sync` пишет pending до schedule; нет loop → запись висит
- [ ] **Одинаковые цвета воркеров** — _pick_color() даёт дубли при auto_resume_all
- [ ] **Clipboard на HTTP** — navigator.clipboard требует HTTPS. Fallback на execCommand('copy')
- [ ] **TG media buffer race (P2)** — _resolve_media после timeout-flush может записать в чужой слот нового буфера. Нужен generation counter

## Next
- [ ] **Auto-learning из ошибок (#76)** — Self-Harness: weakness mining → harness proposal → validation. Paper arxiv.org/abs/2606.09498. Логи в SQLite, промпты модульные, тесты есть — все куски готовы
- [ ] **Design review скилл** — impeccable антипаттерны + taste-skill принципы для frontend-opus и html-artifacts
- [ ] **worker_wip показывать ctx%** — сейчас нужен list_agents отдельно
- [ ] **Hot-reload system_prompt** — менять промпт воркера на лету без респавна
- [ ] **merge_worker показывать diff** — changeset перед мержем
- [ ] **Per-role idle_timeout** — `idle_timeout: 900` в YAML frontmatter роли
- [ ] **Раздробить app.js (4500+ строк)** — модули: chat.js, tools.js, tasks.js, files.js, agents.js, sse.js
- [ ] **TG verbosity** — фильтрация tool/status по уровню TG_VERBOSITY=low|medium|high
- [ ] **Cross-agent context inject** — при send_message приложить docs/tasks/<id>/research.md

## Ideas
- [ ] **Codex как streaming tool** — видеть прогресс codex в реальном времени
- [ ] **Cross-server messaging** — связь между Orchestra на разных серверах
- [ ] **Emergency failover** — автопереключение на API ключи если подписка слетела
- [ ] **Best-of-N solving** — N воркеров на одну задачу, reviewer выбирает лучший
