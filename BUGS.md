# Orchestra Bug Reports

## Open

### 🔴 `codex_review` нестабилен на крупных целях и при отказе транспорта

- **Reporters / dates:** polish-tg (2026-07-25 13:36, 13:47, 14:14 UTC).
- **Что сломано:** это не старый CWD/output-баг. На плане из 244 строк два запуска ушли вместо заданной цели в `BUGS.md`, README и Serena onboarding, истекли по 10-минутному timeout и не создали artifact. Отдельный review diff не стартовал: пять WebSocket-попыток получили `Connection refused`, затем пять раз отказал HTTPS fallback.
- **Как воспроизвести:** `codex_review(mode="exec", target="docs/tasks/polish-tg/plan.md", output="docs/tasks/polish-tg/codex-review-plan.md")` — jobs `bg-a7fa044d22` и `bg-6d2189ac4a`; transport failure — `bg-d8a75a53aa`.
- **Что мешает починить:** две причины пока не изолированы: runner теряет фокус на крупной цели, а транспорт отказывает независимо от target routing. Стабильного минимального repro нет; повторять длинные review вслепую нельзя, потому что каждый прогон расходует 10 минут и квоту. До диагностики — узкий prompt/target, максимум одна финальная повторная попытка и честный self-review при отказе.

### 🔴 `merge_worker` не может слить child в checked-out ветку parent

- **Reporter:** research-codex-abuse (2026-07-18).
- **Что сломано:** full-cycle parent спавнит child от своей feature branch, но `merge_worker(..., target="<parent feature>")` отклоняет merge: target branch уже checked out в worktree parent. Это неизбежно для документированного worker-spawns-worker workflow.
- **Как воспроизвести:** parent на feature branch спавнит child, child коммитит, затем parent вызывает merge в собственную branch. Подтверждено на parent `0898f32` и child commits `b7ec797`, `22a5366`.
- **Что мешает починить:** `app/workspace.py` всё ещё явно запрещает target, checked out в другом worktree. Нужен merge без checkout target в canonical repo либо безопасная parent-side операция; ручной Git обходит lifecycle и потому не считается исправлением.

### 🔴 auto-switch hardcodes `refs/heads/main`

- **Reporter:** Sensar-orchestrator (2026-07-18).
- **Что сломано:** после успешного merge в `master` автоматический switch сбрасывает worker от несуществующего `refs/heads/main`.
- **Как воспроизвести:** в master-only repo вызвать `merge_worker(..., target="master", next_task_id=...)`; merge проходит, auto-switch падает с unknown revision. Workaround: отдельный `switch_worker_branch(from_ref="refs/heads/master")`.
- **Что мешает починить:** defaults в `app/mcp_stdio.py` и `app/routes/sessions.py` по-прежнему зашиты на `refs/heads/main`; надо протянуть фактический merge target либо определить default branch, сохранив совместимость существующих main-репозиториев.

### 🔴 `auto_resume`/live server перезаписывает ручную смену модели в DB

- **Reporters / dates:** Orchestra-orchestrator (2026-07-21, повтор 2026-07-25).
- **Статус:** ⏳ **ждёт рестарта для проверки**.
- **Что сломано:** `UPDATE sessions SET model=...` для загруженной session сначала меняет строку, затем живой процесс сохраняет старую in-memory model обратно. Так откатились Sensar-orchestrator и часть bulk migration Opus 4.x → Opus 5.
- **Как воспроизвести:** при работающем Orchestra изменить `sessions.model` напрямую, дождаться persist или рестарта и повторить `SELECT`; значение возвращается к модели живой session.
- **Что мешает починить:** безопасная проверка требует maintenance restart, а сервер по условию этой задачи не перезапускается. До исправления менять модель через поддерживаемый endpoint; для offline migration — остановить сервис, обновить `model`, обнулить `session_id`, запустить и перепроверить.

### 🟡 TG expandable/tool bursts могут блокировать outbound delivery

- **Reporter:** Orchestra-orchestrator (2026-07-21).
- **Статус:** ⏳ **предположительно исправлено, ждёт рестарта для проверки**.
- **Что сломано:** прежний `_send_expandable(important=True)` при 10+ tool events/sec занимал общий lock/retry path и останавливал все исходящие TG-сообщения. Revert на `important=False` сохранял текст, но терял tool events.
- **Как воспроизвести:** после рестарта создать burst expandable/tool events одновременно с reliable text и проверить, что текст доставляется, очередь ограничена, а telemetry coalesces вместо starvation.
- **Что мешает закрыть:** commit `5fba15d` (`polish-tg`) реализовал ровно требуемый bounded/fair scheduler и coalesced tools: reliable FIFO 256, telemetry keys 128, не более трёх reliable slots до overdue telemetry, bounded deadlines. Детерминированные тесты прошли, но live Telegram и реальный restart не проверялись; до этого подтверждения баг остаётся открытым.

### 🟡 TG diff images не отображаются

- **Reporter:** Orchestra-orchestrator (2026-06-08).
- **Статус:** ⏳ **ждёт рестарта для проверки**.
- **Что сломано:** код изображений для Edit/Write/Read/Grep/Bash в `app/diff_image.py` есть, но PNG не появляются в Telegram; debug logging из `c0d73fe` также не наблюдался, поэтому `_send_diff_image` мог не вызываться.
- **Как воспроизвести:** после рестарта выполнить поддерживаемый tool call из TG-topic и проверить наличие image, text fallback и debug trace `_send_diff_image`.
- **Что мешает починить:** без рестарта нельзя отличить неактивированный код/logging от ошибки dispatch/render/send. Детали после 8 июня не обновлялись; нужна проверка на текущем runtime.

### 🟡 Session status показывает `idle`, пока worker работает

- **Reporter:** Orchestra-orchestrator (2026-07-03).
- **Что сломано:** dashboard/listing иногда показывает `idle`, хотя turn ещё выполняется; предполагалась гонка WAITING/status persist/SSE.
- **Как воспроизвести:** запустить долгий turn с background-job wakeup и сопоставить status из API/dashboard с turn/log lifecycle. Стабильный сценарий и исходные job IDs не сохранились.
- **Что мешает починить:** **нужна проверка, детали утеряны**. Поздние lifecycle-фиксы закрывали противоположный stuck-running симптом, но доказательства для idle-while-running нет; сначала нужен новый trace с временными метками status transitions.

### 🟡 Session со старой ролью `researcher` не resume-ится

- **Reporter:** Orchestra-orchestrator (2026-07-25).
- **Что сломано:** каждый startup пишет `Failed to resume worker gamedesign-researcher: role 'researcher' not resolvable in pipeline 'default': KeyError('researcher')`; роль удалена при переходе на full-cycle.
- **Как воспроизвести:** оставить в `sessions` неархивированную запись с `role='researcher'`, затем запустить `auto_resume_all`.
- **Что мешает починить:** нужен явный выбор state migration (`researcher` → `full-cycle`) либо archival этой конкретной session; молчаливый fallback может поднять worker с неверным prompt/contract.

## Closed

### 2026-07

#### ✅ `codex_review` использовал неверный CWD, терял artifact и рапортовал false success

- **История:** девять инцидентов одного класса: 06-14 combat-dev; 07-01 research-proxy; 07-11 research-grok; 07-12 research-interaction-tax и research-rag-orchestra; 07-16 legal-payment-researcher; 07-18 research-self-improve и codex-limits-source; 07-19 sensar-client-offer. Симптомы: запуск из main checkout вместо caller worktree, review чужого diff, output в неверном месте либо отсутствует, обрезанный `last_output`, сообщение `done/Results in ...` при пустом artifact.
- **Исправление:** `d4c0719` добавил `cwd`/`worktree_path` в session payload и выбор caller worktree; `dfe0930` добавил atomic `.round` finalization, очистку stale temp state, проверку non-empty `success_file`/`## Verdict` и fail notification вместо false success.
- **Проверка:** свежие непустые artifacts успешно созданы в worktrees audit-fullcycle (`docs/tasks/fullcycle-audit/codex-review-research.md`) и feat-usage-analytics (`docs/tasks/usage-analytics/codex-review-impl.md`, 2026-07-26, с несколькими verdict rounds). Инциденты polish-tg от 25 июля имеют другой профиль и оставлены открытыми отдельно.

#### ✅ `spawn_worker` и `repo_path`: исходный диагноз опровергнут, реальные дефекты закрыты в #88

- **История:** batch4-food-services (2026-07-24) получил Orchestra worktree, потому что caller `sales` сам передал `repo_path=/mnt/data/Projects/Python/orchestra` при logical scope Seedon. У `impl-inscryption` (2026-07-26) Git common dir с самого начала был `/mnt/data/Projects/Python/inscryption-ai/.git`; COG присутствовал только в slug logical scope. Незарегистрированные репозитории уже поддерживались, fallback через project registry в spawn chain отсутствовал.
- **Реальные дефекты:** вложенный каталог Git-репозитория молча резолвился в родительский root; успешный ответ `spawn_worker` не показывал фактические worktree, repository, common dir и branch, поэтому неверный caller input и scope slug выглядели как игнорирование параметра.
- **Исправление:** #88 добавил exact-root preflight до spawn side effects с явными ошибками для nested/non-Git/bare/linked/external layouts и возвращает server-validated repository/common-dir mapping в success response. Исходное утверждение «незарегистрированный `repo_path` молча заменяется репозиторием scope» — **REFUTED**.

- ✅ **Cosmetic topic-status calls starved TG outbound pipeline** — `a566371`: topic metadata вынесены из message queue в best-effort вызов с одной попыткой/5s timeout; iteration races закрыты snapshot-ами. `tests/test_tg_bridge.py`: 56 passed.
- ✅ **Codex workers тратили wall-clock на `sleep` рядом с `codex_review`** — `d19ad34`: tool text теперь требует `END YOUR TURN NOW`, base prompt запрещает polling external state, RUNNING→IDLE retry race удалён. Evidence: `docs/tasks/codex-sleep/`.
- ✅ **Full suite event-loop pollution** — `cd3dce1` пересоздаёт `_spawn_queue` и очищает per-loop locks при shutdown/lifespan reuse. Контроль 2026-07-26: `tests/test_manager.py tests/test_frontend.py` — 111 passed вместе.
- ✅ **Frontend readability: длинные Bash titles/raw transcript и `.md` без render** — `6ba8ec2`: readable sub-agent modal и Markdown preview.
- ✅ **`test_default_pipeline` ожидал старый manifest/modules/skills** — expectations синхронизированы с pipeline evolution (в том числе `28dafb2`). Контроль 2026-07-26: 44 passed.

### 2026-06

- ✅ **Codex review unreachable** — `738eafc`: `codex_review` использует proxy wrapper вместо прямого binary, закрывая DNS/403 из России. Исходный report: research-runtime, 2026-06-05.
- ✅ **Message disappears on agent switch in dashboard** — `e121cdd`: SSE reconnect replay накопленного stream text. Исходный report: Orchestra-orchestrator, 2026-06-15.
- ✅ **send_message 500 после рестарта** — Fixed: ensure_loaded_any fallback (2026-06-03)
- ✅ **DONE report to wrong parent** — Fixed: last_task_sender tracking + report-format prompt (2026-06-04)
- ✅ **Ambiguous task linking** — Fixed: project_id filter in link_commits_to_task (2026-06-04)
- ✅ **Prices in thousands** — Fixed: exact currency units, `_fmt_amount`, removed `*1000` (2026-06-04)
- ✅ **Worker status stuck idle while running** — Fixed: turn timeout no longer resets status (2026-06-05)
- ✅ **TG files to wrong topic** — Fixed: `_find_orch_for_scope` by `parent_name` (2026-06-05)
- ✅ **change_model not persisted** — Fixed: immediate `save_session` in `change_model` (2026-06-09)
- ✅ **dev-lead malformed tool calls** — Root cause: Opus 4.8 bug. Switched to 4.6 + prompt rule added
- ✅ **Single tilde strikethrough** — Fixed: escape single `~` before `marked.parse`
- ✅ **Spawn bubble text wrapping** — Fixed: cut at newline boundary
- ✅ **Worker colors after refresh** — Fixed: await `refreshSessions` before `connectSSE`
- ✅ **Send errors hidden in dashboard** — Fixed: show red ❌ instead of null
- ✅ **System prompt lost on compact** — Fixed: always set `system_prompt` (2026-06-03)
- ✅ **switch_worker_branch blocked after squash** — Fixed: reset `--hard from_ref` (2026-06-03)
- ✅ **Cross-project send_message** — Fixed: `ensure_loaded_any` fallback (2026-06-03)

### 2026-05

- ✅ **codex_review output path** — Fixed: Codex через bash (`cwd=worktree`)
- ✅ **Codex Reconnecting через прокси** — Fixed: strip proxy env
- ✅ **Deepgram SSL BAD_RECORD_MAC** — Fixed: `trust_env=False` + certifi
- ✅ **send_file silent false-positive** — Fixed: validate TG response
- ✅ **kill_worker удаляет логи** — Fixed: `archive_session`
- ✅ **Zombie workers after restart** — Fixed: `auto_resume_all` filters archived
- ✅ **Merge конфликт после squash** — Fixed: auto-reset worktree (#38)
