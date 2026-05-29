# Orchestra TODO

## Bugs
- [ ] **Одинаковые цвета воркеров** — _pick_color() даёт дубли при auto_resume_all
- [ ] **Clipboard на HTTP** — navigator.clipboard требует HTTPS. Fallback на execCommand('copy')
- [ ] **send_message 500 после рестарта** — idle воркеры не получают сообщения после restart. Workaround: respawn
- [ ] **send_file ошибка без текста** — MCP send_file возвращает пустую ошибку, нет диагностики

## Next
- [ ] **Per-role idle_timeout** — `idle_timeout: 900` в YAML frontmatter роли. Full-cycle = 15 мин, worker = 5 мин. Решает "засыпание" между фазами пайплайна. `session.py`, `manager.py`
- [ ] **Fix TestRemoveScope** — KeyError 'names' в `test_passes_orch_names_to_tg_bridge_when_flag_set`. Pre-existing баг
- [ ] **TG очередь сообщений** — throttle снижен до 1с и дроп убран, но при burst'ах всё ещё последовательная отправка. Нужна asyncio.Queue + батчинг (несколько tool calls в одно сообщение) для лучшего throughput
- [ ] **DNS + SSL** — orchestra.zahoron.ru + certbot
- [ ] **Раздробить app.js (4500+ строк)** — разбить на модули: chat.js, tools.js, tasks.js, files.js, agents.js, sse.js
- [ ] **Модульные промпты** — вынести TaskManager/YouGile/платежи в опциональные модули (#15)
- [ ] **TG verbosity** — фильтрация tool/status по уровню TG_VERBOSITY=low|medium|high (#16)

## Ideas

### Из форка Вадима (mccalpink/orchestra, ветки v2-pipeline + personal)
- [ ] **docs_feature scaffold** — при spawn воркера на фичу автоматом создаётся `docs_work/<feature>/` с шаблонами `_sprint.md`, `_pm.md`, `_analysis.md`, `_impl.md`. Symlink в worktree. Решает проблему "контекст потерялся при compaction". Файлы: `workspace.py`, `manager.py`
- [ ] **TG topic labels по ролям** — формат `<метка> | <Роль>` вместо просто имени. Группировка по feature. Subtree running check per orchestrator. Файлы: `tg_bridge.py`
- [ ] **UI дерево агентов** — `renderAgentList` показывает parent-child дерево вместо плоского списка. Файлы: `app.js`, `dashboard.html`
- [ ] **codex-debate** — замена codex-review: итеративный дебат между моделями вместо одноразового ревью. 421 строк SKILL.md. Файлы: `app/skills/codex-debate/`
- [ ] **TG тесты** — 289 строк тестов для tg_bridge.py. Файлы: `tests/test_tg_bridge.py`

### Swarm (рой агентов)
- [ ] **Best-of-N solving** — `spawn_swarm(task, n=3, strategy="best-of-n")` MCP tool. Спавнит N воркеров на одну задачу разными подходами, reviewer/мета-оркестратор выбирает лучший результат. Аналог xAI Grok Arena Mode. Файлы: `manager.py`, `mcp_stdio.py`
- [ ] **Shared swarm memory** — SQLite таблица `swarm_state(swarm_id, key, value, worker, ts)`. Воркеры одного роя читают/пишут общий контекст. Решает проблему дублирования работы при параллельных воркерах. Файлы: `db.py`, `mcp_stdio.py`
- [ ] **Swarm judge** — `judge_results(swarm_id)` — reviewer-агент сравнивает результаты N воркеров, выбирает/мерджит лучший. Можно Opus reviewer или cross-model (GPT-5.5 vs Opus). Файлы: `manager.py`, `mcp_stdio.py`

### Наши
- [ ] **Cross-server messaging** — связь между Orchestra на разных серверах через webhook
- [ ] **Данные в файлах проекта** — таски/сессии в `.orchestra/` папке, git sync между машинами
- [ ] **Emergency failover** — автопереключение на API ключи если подписка слетела
- [ ] **Soft model swap** — stop → save summary → respawn с новой моделью + summary в промпт

## Later
- [ ] **Dashboard streaming** — live token streaming
- [ ] **Task Context Space** — task_context folder при spawn
- [ ] **HTML артефакты** — preview HTML в дашборде
- [ ] **Local Bot API на VPS** — для тяжёлых файлов (>20MB)
- [ ] **TG pinned status** — закреплённое сообщение в каждом топике
