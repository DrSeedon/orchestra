# Orchestra Bug Reports

## Open

### 🟡 Full test suite: ~14 failures from event-loop pollution (pre-existing)
- **Reporter:** Streaming worker / task #83 (2026-06-21)
- Running the FULL suite produces ~132 failures (incl. Playwright OOM), but each failing test **PASSES in isolation**. Without Playwright: 14 failed / 594 passed, deterministic.
- **Root cause:** `app/manager.py:304` `self._spawn_queue: asyncio.Queue = asyncio.Queue()` is created on the singleton manager at construction, bound to whichever event loop existed then. A later test with a fresh loop hits `RuntimeError: <Queue> is bound to a different event loop`. Cross-test contamination, NOT a product bug.
- **Impact:** can't trust the raw full-suite count; run modules in isolation or compare deltas. Task #83 verified +14 passing / 0 new failures this way.
- **Fix idea:** lazy-init `_spawn_queue` inside the consumer coroutine (per-loop), or recreate it on spawn-worker startup. Needs its own task.

### 🟡 TG diff images not rendering
- **Reporter:** Orchestra-orchestrator (2026-06-08)
- Edit/Write/Read/Grep/Bash diff images (`app/diff_image.py`) code exists but images don't appear in TG
- Debug logging added (`c0d73fe`) but no logs appear — `_send_diff_image` may not be called
- Need to verify after restart with debug logging enabled

### 🟢 Codex review unreachable — FIXED
- **Reporter:** research-runtime (2026-06-05)
- **Fix:** `_CODEX_BIN` now points to `~/.local/bin/codex` wrapper with `HTTPS_PROXY=http://127.0.0.1:12340` (Ёжик tunnel)

## Closed (2026-06)

- ✅ **send_message 500 после рестарта** — Fixed: ensure_loaded_any fallback (2026-06-03)
- ✅ **DONE report to wrong parent** — Fixed: last_task_sender tracking + report-format prompt (2026-06-04)
- ✅ **Ambiguous task linking** — Fixed: project_id filter in link_commits_to_task (2026-06-04)
- ✅ **Prices in thousands** — Fixed: exact currency units, _fmt_amount, removed *1000 (2026-06-04)
- ✅ **Worker status stuck idle while running** — Fixed: turn timeout no longer resets status (2026-06-05)
- ✅ **TG files to wrong topic** — Fixed: _find_orch_for_scope by parent_name (2026-06-05)
- ✅ **change_model not persisted** — Fixed: immediate save_session in change_model (2026-06-09)
- ✅ **dev-lead malformed tool calls** — Root cause: Opus 4.8 bug. Switched to 4.6 + prompt rule added
- ✅ **Single tilde strikethrough** — Fixed: escape single ~ before marked.parse
- ✅ **Spawn bubble text wrapping** — Fixed: cut at newline boundary
- ✅ **Worker colors after refresh** — Fixed: await refreshSessions before connectSSE
- ✅ **Send errors hidden in dashboard** — Fixed: show red ❌ instead of null
- ✅ **System prompt lost on compact** — Fixed: always set system_prompt (2026-06-03)
- ✅ **switch_worker_branch blocked after squash** — Fixed: reset --hard from_ref (2026-06-03)
- ✅ **Cross-project send_message** — Fixed: ensure_loaded_any fallback (2026-06-03)

## Closed (2026-05)

- ✅ **codex_review output path** — Fixed: Codex через bash (cwd=worktree)
- ✅ **Codex Reconnecting через прокси** — Fixed: strip proxy env
- ✅ **Deepgram SSL BAD_RECORD_MAC** — Fixed: trust_env=False + certifi
- ✅ **send_file silent false-positive** — Fixed: validate TG response
- ✅ **kill_worker удаляет логи** — Fixed: archive_session
- ✅ **Zombie workers after restart** — Fixed: auto_resume_all filters archived
- ✅ **Merge конфликт после squash** — Fixed: auto-reset worktree (#38)

## [2026-06-14 04:35 UTC] codex_review резолвит не тот repo path в git worktree (игнорит cwd воркера)
- **Reporter:** combat-dev
- **Scope:** /mnt/data/Projects/Python/stargate-tactics
Воркер работал в git worktree /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-stargate-tactics/combat-dev. Дважды вызвал codex_review (mode=review и mode=exec). ОБА раза Codex запустился в /mnt/data/Projects/Python/stargate-tactics/ (канонический чекаут, другой проект — NEAT-обучение) вместо worktree воркера. Симптомы: (1) ревью ушло на чужие файлы (champion.json, client/game.js, training_log.json) вместо staged diff воркера; (2) запись output зафейлилась: "Failed to write ... docs/tasks/16/CODEX_REVIEW.md: No such file or directory" — т.к. Codex был в чужой папке где нет docs/tasks/16. Даже mode=exec с относительным target=docs/tasks/16/combat_diff.patch резолвился относительно чужого cwd. ОЖИДАЕМО: codex_review должен запускать codex CLI с cwd = текущая рабочая директория воркера (его worktree), а не искать "главный" чекаут проекта по имени. ВОРКЭРАУНД которого нет: пришлось коммитить без cross-LLM ревью. Чинить: пробрасывать cwd воркера в codex exec/review как рабочую директорию.

## [2026-06-15 10:35 UTC] Message disappears on agent switch in dashboard
- **Reporter:** Orchestra-orchestrator
- **Scope:** /mnt/data/Projects/Python/orchestra
When switching between agents in dashboard sidebar, the last sent message can disappear from chat. User has to reload the page to see it. Likely cause: SSE stream reconnects on agent switch and the message sent right before switch gets lost in the gap between old stream closing and new stream opening. Reproducible when sending a message and immediately clicking another agent.

## [2026-07-01 06:09 UTC] codex_review output пишется в main repo cwd вместо worktree агента
- **Reporter:** research-proxy
- **Scope:** /mnt/data/Projects/Python/orchestra
Симптом: MCP tool `codex_review` (mode=exec и mode=review) стабильно запускает `codex` с cwd = MAIN repo (/mnt/data/Projects/Python/orchestra), а НЕ в worktree воркера, который его вызвал (/mnt/data/Projects/Python/orchestra/worktrees/.../research-proxy).

Последствия:
1. Codex ревьюит git diff MAIN repo (чужие изменения других агентов), а НЕ файлы воркера в его worktree. Воркер получает ревью не своего кода.
2. Output-файл (параметр output=CODEX_REVIEW_final.md / docs/tasks/.../codex-review-impl.md) пишется относительно main repo cwd → воркер не находит его в своём worktree.

Воспроизведение: воркер в worktree вызывает codex_review(target="app/proxy_manager.py", mode="exec", output="docs/tasks/X/review.md"). Файл появляется в /mnt/data/Projects/Python/orchestra/docs/tasks/X/, а не в worktree. Codex exec-команды (git show HEAD:app/models.py и т.п.) выполняются в main repo — видно по логам "in /mnt/data/Projects/Python/orchestra".

За сессию воспроизвелось 4+ раз подряд (bg-ab450f48f1, bg-a2c0f584b5, bg-6c96231fb1) — на разных target/mode. Первый прогон ещё и падал по websocket (Codex-враппер без HTTP_PROXY, отдельно починено).

Ожидаемо: codex_review должен запускать codex с cwd = worktree вызвавшего воркера (или принимать cwd явно), чтобы ревьюить его diff и писать output в его дерево.

Фикс-гипотеза: в реализации codex_review взять cwd из session.cwd/worktree_path воркера, передать в subprocess cwd=. Сейчас, видимо, наследуется cwd оркестратора/main.

## 2026-07-03 open
- **status-desync** — session status shows idle while worker actually running (WAITING/persist/SSE race). session.py status transitions vs _persist timing. Deferred, needs research
- **test_default_pipeline 3 fails** — pre-existing, manifest has extra modules/skills tests expect old set. CI-blocking if strict. Not our diff
- **frontend readability** (frontend-opus fixing) — subagent modal: long bash commands as titles + transcript raw dumps; prompt/.md viewer no markdown render

## [2026-07-11 06:21 UTC] codex_review reports "done" but output file not written to worker worktree (CWD bug)
- **Reporter:** research-grok
- **Scope:** /mnt/data/Projects/Python/orchestra
research-grok worker: called codex_review(mode=exec, target=docs/tasks/grok-research/research.md, output=docs/tasks/grok-research/codex-review-research.md) TWICE (bg-ba20facbdb, then bg-7d477ec9c4 with resume=True). Both bg jobs reported "Codex exec done. Results in docs/tasks/grok-research/codex-review-research.md" but the file was NEVER created in the worker's worktree (/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-grok/). find across whole repo tree shows no codex-review-research.md modified in last 20min. This is the known codex_review CWD bug ("runs in main repo not worktree" — CLAUDE.md session notes 2026-07-06/07-09 claim a 2-line to_dict() cwd fix shipped, but it's still broken for worker worktrees as of 2026-07-11). Net effect: the mandatory Phase-1 Codex second-opinion step is impossible for full-cycle workers — the tool consumes a Codex run but the worker cannot read the result. Needs real fix: verify cwd/worktree_path is passed to the codex subprocess AND that the output path is resolved relative to that cwd.

## [2026-07-12 06:21 UTC] codex_review MCP tool fails (bg job "failed") while Codex CLI works fine
- **Reporter:** research-interaction-tax
- **Scope:** /mnt/data/Projects/Python/orchestra
Симптом: `mcp__orchestra__codex_review` запускает bg job, который завершается статусом **failed**, но с сообщением "Codex exec done. Results in docs/tasks/.../codex..." — при этом выходной .md файл НЕ создаётся. Воспроизвелось на 5 задачах подряд в bg_list (bg-3da08a15c0 interaction-tax, 2× research-cc-config, 2× research-grok) — все "failed".

Проверка: Codex CLI сам ЖИВ — `codex exec "reply CODEX_ALIVE"` вернул CODEX_ALIVE за ~2.4k токенов, проще некуда. HTTPS_PROXY=127.0.0.1:12343 активен. Т.е. проблема НЕ в прокси и НЕ в самом Codex, а в MCP-wrapper'е codex_review (парсинг/запись результата, или передача cwd/target в subprocess, или обработка exit-кода bg job).

Workaround который сработал: прогнал adversarial review напрямую через `codex exec "...read docs/.../research.md ... write findings to docs/.../codex-review-research.md"` — файл создался корректно (141 строка).

Место для копания: обёртка codex_review в app/ (та что формирует bg job type=run и потом должна прочитать/записать вывод). Похоже job помечается failed несмотря на успешный Codex-прогон, и результат теряется. Приоритет: mid — codex_review это mandatory-шаг Phase 1/2 full-cycle pipeline, сейчас он молча не пишет файл.

## [2026-07-12 13:15 UTC] codex_review fails consistently (7 jobs across 5 workers) — no output written
- **Reporter:** research-rag-orchestra
- **Scope:** /mnt/data/Projects/Python/orchestra
codex_review(mode=exec) jobs all return status=failed with no output file created. Observed 7 consecutive failures: bg-8a5d9b0512, bg-a6d5d9dd75 (research-rag-orchestra), bg-3da08a15c0 (interaction-tax), bg-bc4692a1ef, bg-5c6e0307e8 (cc-config), bg-7d477ec9c4, bg-ba20facbdb (grok). The job message says "Codex exec done. Results in docs/tasks/.../codex-review-*.md" but the file is never written (0 bytes / missing). Pattern spans multiple projects and both mode=exec and default → not query-specific. Likely: Codex CLI wrapper crashing, proxy (Ёжик 12340) down for the codex endpoint, or session/auth failure. Blocks the mandatory Phase-1/Phase-2 Codex second-opinion gate for all full-cycle workers right now.

## [2026-07-16 03:53 UTC] codex_review: output-файл не создан (CWD-баг) + last_output обрезан
- **Reporter:** legal-payment-researcher
- **Scope:** /home/maxim/Рабочий стол/Cursor/COG-second-brain
codex_review(mode=exec, target=block2-armenia.md, output=docs/tasks/payment-rails-2026/codex-review-armenia.md, project=legal-payment-researcher) завершился со статусом done, но: (1) output-файл codex-review-armenia.md НЕ создан ни в worktree агента, ни в main repo — известный CWD-баг (Codex пишет не в CWD агента). (2) bg_jobs.last_output обрезан до ~3.4KB, содержит только середину web_search-потока, финального agent_message с текстом ревью нет — вердикт Codex безвозвратно потерян. Пришлось верифицировать ключевой вывод (незачёт армянского turnover tax) вручную через WebSearch. Job id: bg-b6687fb86a.
