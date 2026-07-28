# Orchestra TODO

## Bugs
- [ ] **Тест-изоляция: test_default_equals_upstream загрязняет 106 тестов** — `load_pipeline.cache_clear()` + monkeypatch `PIPELINES_DIR`. Pre-existing. Deselect в CI
- [ ] **Pending tm_sync_log без fire в CLI-контексте** — `_fire_sync` пишет pending до schedule; нет loop → запись висит
- [ ] **TG media buffer race (P2)** — _resolve_media после timeout-flush может записать в чужой слот. Нужен generation counter
- [ ] **Message disappears on agent switch** — SSE reconnect gap. 300ms delay added (partial fix)
- [ ] **TG дубли expandable+image** — partially fixed (skip expandable for Read/Grep/Bash/Glob when image sent), but Edit/Write may still duplicate
- [ ] **RAG-бэкфилл на merge_worker ненадёжен/медленный** — после merge индекс ещё старый: `search_memory` отдаёт предыдущую версию файла как «текущую». Ручной `POST /api/memory/reindex` чинит за ~4 мин. Триггер fire-and-forget → недоказуемо, «не сработал» или «не успел». Проверить: реально ли триггерится и сколько занимает. Найдено при архивации session notes 2026-07-26
- [ ] **Устаревшие копии скиллов в Claude-worktree** — `.claude/skills/` копируется при СОЗДАНИИ worktree и не обновляется: у `audit-fullcycle` до сих пор лежит `self-analysis`, удалённый 2026-07-26. Та же болезнь, что была с AGENTS.md. Осознанно вынесено за скоуп #89
- [ ] **`skills_catalog()` мёртвая** — `app/prompting.py:103`, 0 вызовов во всём репо. Глобит `prompts/skills/*.md`, но инжект резолвит скиллы ПО ИМЕНАМ из pipeline.yaml. Решить что из двух: (а) забыли подключить блок «Available skills» в промпт оркестратора → тогда оркестратор не видит доступные скиллы, это баг; (б) пережиток апстрима → удалить. Найдено при чистке divergent-thinking/self-analysis 2026-07-25

## In Progress
- [ ] **#90 worktree/merge lifecycle — T4..T7 заморожены до 2 августа** (воркер `audit-worktree`, ctx:55%, ждёт квоту Codex). T1 (`2ad44dc`), T2 (`6b08652`), T3 (`4badfa3`, забран руками после падения воркера на rate_limit) СМЕРЖЕНЫ. Осталось: T4 (turn-finished signal вместо grace 2 с — трогает ядро turn-цикла, делать осторожно), T5 (fail-loud remove/cleanup + `scope_dir`→`repo_dir`), T6 (атомарный switch/task state), T7 (hash-suffix для slug, exact-set skill sync). План: `docs/tasks/90/plan.md`, аудит: `docs/tasks/90/audit.md`. **T3 не проходил Codex-ревью** — квота кончилась; при возобновлении отревьюить diff `4badfa3` первым делом
- [ ] **tg_bridge split P5** — refactor-tg worker (Opus 4.8, ctx:12%) has research+plan done, awaiting impl approval. Split into tg_bot/tg_stream/tg_render/tg_topics

## Ждут решения юзера (2026-07-26)
- [ ] **Codex-квота выбрана до 2026-08-02 11:57** (недельный лимит, не 5h). 28 живых сессий на `gpt-5.6-sol` нерабочие: `frontend`, `prompt-engineer`, `feat-skill-index`, `audit-worktree` + воркеры seedon/COG/inscryption. **Решено 27.07**: T3 забран руками, T4–T7 заморожены. Открытым остаётся, что делать с Sol-воркерами ДРУГИХ проектов на эту неделю
- [ ] **`report_bug` гадит в рабочий чекаут** — пишет в `BUGS.md` и оставляет незакоммиченным. После T2 #90 (fail-loud на грязный target) любой входящий баг-репорт блокирует ВСЕ мержи. Варианты: report_bug коммитит свою запись сам / BUGS.md выносится из рабочего дерева. Решить после T7
- [ ] **Перевод остатка CLAUDE.md на английский** — файл чисто агентский (юзер его не читает), кириллица = 2 байта/символ → двойной запас по 32 KiB-лимиту Codex. Делать ОТДЕЛЬНЫМ шагом после архивации, не смешивая
- [ ] **R8: orchestration.md (255 строк)** — НЕ резать вслепую по статье Anthropic. Сначала замер следа инструкций, как в fullcycle-audit
- [ ] **Правило в «Грабли»**: «сузил валидацию на shared runtime → прогони по всем живым sessions.scope из БД, не только по фикстурам» (от fix-repo-path) — ЗАПИСАНО, подтверждение получено постфактум
- [ ] **Личные скиллы из ~/.claude/skills в пайплайн** — какие реально нужны воркерам? Не все скопом. Задача #89 дала механизм (оглавление), осталось решить состав

## Urgent (needs restart)
- [ ] **RESTART ORCHESTRA** — не перезапускались с 2026-07-25 (сервер стартовал 06:48). **Система в РАССИНХРОНЕ**: `app/mcp_stdio.py` подхватывается новыми MCP-процессами немедленно, `app/routes/` живёт в памяти systemd → новый MCP шлёт `target=""`, старый route падает `target branch '' does not exist`. **Обход до рестарта: `merge_worker(name, target="main")` явно.** Колонки `base_branch`/`needs_switch` в живой БД ещё НЕТ — миграция выполнится на старте. COG-оркестратор просил дождаться гейта у `impl-inscryption`/`impl-deck-search`. Всё ниже смержено в main и НЕ РАБОТАЕТ до `sudo systemctl restart orchestra`: **#90 T1+T2+T3 (persisted base_branch, merge в checked-out target, атомарный squash + честный контракт линковки)**, Opus 5 registry, TG topic-lock fix, codex-sleep fix, preview CSP, transaction-safe compact, **Usage Analytics v2 + /api/usage/analytics**, **кнопка «Разбудить после сброса» (limit_wake.py)**, **полный ремонт TG (6 багов, тесты 56→97)**, **обновление зеркала AGENTS.md на коннекте**, **оглавление скиллов для Sol (#89)**, **строгая валидация repo_path (#88)**
- [ ] **После рестарта — проверить 3 бага из BUGS.md**, помеченных restart-marker: TG diff images (с 08.06), TG expandable deadlock (вероятно уже починен 5fba15d), auto_resume model overwrite
- [ ] **После рестарта — проверить AGENTS.md у Sol-воркеров**: у `frontend` и `prompt-engineer` файла НЕТ ВООБЩЕ (были Claude-воркерами, зеркало не создавалось), у `audit-fullcycle` лежит старая копия 61 643 байта. Должно самовылечиться на реконнекте — ПОДТВЕРДИТЬ
- [ ] **Effort xhigh crash on Claude** — backend_claude.py: auto-downgrade xhigh→high for claude models. Fix written, needs restart
- [ ] **Codex usage limit infinite retry** — session.py: "hit your usage limit" not in terminal patterns → retried forever. Fix written, needs restart
- [ ] **seedon-orchestrator Fable 5 → Opus 5** — burning 4× limit, DB update needed + restart
- [ ] **TG expandable deadlock** — important=True on expandable caused total TG outbound deadlock. REVERTED. Needs different approach (debounce/separate queue). NOTE: topic_status half of this is now fixed (a566371)
- [ ] **auto_resume overwrites DB model** — live server rewrites `sessions.model` from in-memory on shutdown/persist. Observed 2026-07-25: bulk UPDATE to Opus 5 was silently reverted for loaded agents. Workaround = re-run UPDATE and restart. Root cause still unfixed
- [ ] **Post-restart: verify Opus 5 stuck** — after restart re-check `SELECT name,model FROM sessions WHERE model LIKE 'claude-opus-4%'`; if agents reverted, session_id may pin the old model → NULL it
- [ ] **Measure codex-sleep fix** — 7 days or 30 Sol review jobs, then decide if a PreToolUse sleep guard is still needed (baseline: 74 sleeps / 1579 Codex bash calls = 4.69%)

## Next
- [ ] **Opus 5 canary metrics** — research recommended measuring before fleet-wide trust: ≤+15% median agentic steps, ≤+25% cost & 5h-points per completion vs Opus 4.6/4.8 baseline. Not yet measured — we switched everything at once on user's order
- [ ] **Admission budget for Opus 5** — research advises ≤8 new Opus tasks per 5h window, ≤2 concurrent Claude sessions until a real A/B exists
- [ ] **gamedesign-researcher unloadable** — `role 'researcher' not resolvable in pipeline 'default'` on every startup; role was deleted when merged into full-cycle. Either migrate the session's role or archive it
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
