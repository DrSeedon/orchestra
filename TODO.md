# Orchestra TODO

## Bugs
- [ ] **Тест-изоляция: test_default_equals_upstream загрязняет 106 тестов** — `load_pipeline.cache_clear()` + monkeypatch `PIPELINES_DIR`. Pre-existing. Deselect в CI
- [ ] **Pending tm_sync_log без fire в CLI-контексте** — `_fire_sync` пишет pending до schedule; нет loop → запись висит
- [ ] **TG media buffer race (P2)** — _resolve_media после timeout-flush может записать в чужой слот. Нужен generation counter
- [ ] **Message disappears on agent switch** — SSE reconnect gap. 300ms delay added (partial fix)
- [ ] **TG дубли expandable+image** — partially fixed (skip expandable for Read/Grep/Bash/Glob when image sent), but Edit/Write may still duplicate

## In Progress
- [ ] **tg_bridge split P5** — refactor-tg worker (Opus 4.8, ctx:12%) has research+plan done, awaiting impl approval. Split into tg_bot/tg_stream/tg_render/tg_topics

## Urgent (needs restart)
- [ ] **RESTART ORCHESTRA** — user rejected the sudo prompt 3× on 2026-07-25; all Python changes below are merged to main and inert until `sudo systemctl restart orchestra`: Opus 5 registry, TG topic-lock fix, codex-sleep fix, preview CSP, transaction-safe compact
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
