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

#### ✅ Спавн коммитил незакоммиченную работу юзера в исходный репозиторий

- **Reporter / date:** оркестратор inscryption-ai (2026-07-26) — Orchestra закоммитила чужую папку `.serena/` в `main` перед спавном воркера.
- **Что было сломано:** `AgentManager._auto_commit_if_dirty` делал `git add -A` + `git commit` в рабочем чекауте юзера, вызывался только при `use_worktree and repo_path`. Обоснование в комментарии («worktree наследует unstaged junk») **опровергнуто экспериментом**: `git worktree add <path> HEAD` строит дерево из коммита, unstaged-правки и untracked-файлы источника туда не попадают. Функция хоронила WIP юзера ради несуществующей проблемы. Введено `1e39c47`.
- **Исправление:** функция и её вызов удалены, 2 мока убраны из `tests/test_manager.py`. 152 теста зелёные.

#### ✅ Директория и ветка worktree именовались по `scope`, а не по `repo_path`

- **Reporter / date:** оркестратор inscryption-ai (2026-07-26).
- **Что было сломано:** `create_worktree` строил `wt_dir = WORKTREE_ROOT / _slugify(scope)` и ветку `feat/{scope_slug}/{name}`, тогда как репозиторий брался из `repo_path` — два несверяемых источника. Воркеры `impl-deck-search`, `impl-inscryption`, `feat-inscryption-ai` лежали в `worktrees/home-maxim-cursor-cog-second-brain/` при `git-common-dir` = `/mnt/data/Projects/Python/inscryption-ai/.git`.
- **Почему важно:** это и есть источник серии ложных репортов «`repo_path` игнорируется». Разбор `fix-repo-path` (см. запись ниже) заметил, что «COG присутствовал только в slug logical scope», но не признал это дефектом — оркестраторы продолжали читать путь вместо `git-common-dir` и заново «находили» несуществующий баг.
- **Исправление:** слаг для директории и fallback-ветки берётся от валидированного repo root; параметр `scope` удалён из `create_worktree` за ненадобностью. Существующие worktree не затронуты — их пути в БД.

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

## [2026-07-26 08:32 UTC] codex_review ignores target repository and runs in worker worktree
- **Reporter:** impl-inscryption
- **Scope:** /home/maxim/Рабочий стол/Cursor/COG-second-brain
From agent cwd `/mnt/data/Projects/Python/orchestra/worktrees/home-maxim-cursor-cog-second-brain/impl-inscryption`, the task explicitly targets `/mnt/data/Projects/Python/inscryption-ai`. All implementation commands used that workdir and the staged diff exists there. `mcp__orchestra.codex_review(mode=review, output=docs/tasks/inscryption-ai/codex-review-t3.md)` nevertheless ran git status in the Orchestra worker worktree branch `task-1/impl-inscryption`, reported a clean tree, and wrote output under that worktree instead of the target repo. There is no repo_path/cwd argument in codex_review, so cross-project reviews cannot inspect the authorized target repository.

## [2026-07-26 08:40 UTC] codex_review инспектирует worktree воркера, а не репозиторий, в котором он реально работает
- **Reporter:** COG-second-brain-orchestrator
- **Scope:** /home/maxim/Рабочий стол/Cursor/COG-second-brain
Третий сбой Codex-ревью подряд на задаче #1, третья разная причина.

Контекст: воркер impl-inscryption был заспавнен с repo_path=/mnt/data/Projects/Python/inscryption-ai, но Orchestra создала ему worktree в COG-second-brain (отдельный баг, уже зарепорчен). Воркеру выдано разрешение работать напрямую в целевом репозитории.

Симптом: воркер вызвал codex_review для diff'а тикета T3. Orchestra запустила Codex в его COG-worktree, который чист и не содержит ни строчки кода T3. Codex проинспектировал пустой diff и не увидел ничего. Ревью формально «прошло», фактически не состоялось. Воркер зафиксировал это честно в codex-review-t3.md, а не выдал за APPROVED.

Ожидаемое поведение: codex_review должен инспектировать репозиторий, в котором воркер реально ведёт работу, либо принимать явный путь/cwd, либо падать с ошибкой при пустом diff вместо молчаливого «ревью без находок».

Дополнительно, для той же задачи: два предыдущих раунда Codex умерли по 10-минутному таймауту инфраструктуры (T1 — до записи отчёта, успев найти 4 настоящих блокера в прогрессе; T2 — еле уложился). Похоже, лимит мал для ревью diff'ов среднего размера, либо нужна возможность его поднять для конкретного вызова.

Итог по задаче: три тикета реализованы, ни один не получил внешнего вердикта Codex. Все исправления author-verified.

## [2026-07-26 09:26 UTC] spawn_worker: malformed API response (missing repo_path, git_common_dir) — воркер создан, задача не доставлена
- **Reporter:** Orchestra-orchestrator
- **Scope:** /mnt/data/Projects/Python/orchestra
spawn_worker(name="feat-skill-index", repo_path="/mnt/data/Projects/Python/orchestra", model="gpt-5.6-sol", role="full-cycle", task_id="89") вернул ошибку: "malformed API response after session creation (missing: repo_path, git_common_dir); worker may have been created — inspect list_agents before retrying."

Фактически: воркер СОЗДАН (виден в list_agents, статус idle, task_id 89), но задача НЕ доставлена — get_worker_logs пуст. То есть частичный успех подан как ошибка, и оркестратор должен сам догадаться проверить и дослать task через send_message.

Контекст: случилось сразу после мержа #88 (fix-repo-path), который добавил строгую валидацию repo_path и preflight в manager. Вероятно, ответ теперь формируется до/без заполнения полей repo_path/git_common_dir, либо новый preflight меняет форму ответа. Regression-кандидат к ff6bb73.

Ожидаемо: либо spawn атомарен (не создался — значит не создался), либо ответ честно сообщает "worker created, task NOT sent, resend via send_message".

**Воспроизведён повторно 2026-07-26 ~21:55 UTC** — `spawn_worker(name="audit-worktree", task_id="90")`, тот же текст ошибки, тот же профиль: воркер в `list_agents` (idle, task_id 90), `get_worker_logs` пуст, задача дослана через `send_message`. Значит не разовая гонка, а стабильное поведение после #88. Воспроизводится с первой попытки — repro есть, чинить можно без раскопок.

## [2026-07-26 09:40 UTC] RAG-бэкфилл на merge_worker не успевает/не срабатывает — память отдаёт устаревший файл
- **Reporter:** Orchestra-orchestrator (найдено воркером audit-fullcycle при приёмке R1)
- **Scope:** /mnt/data/Projects/Python/orchestra
Сразу после `merge_worker` семантический индекс ещё СТАРЫЙ: `search_memory` возвращает предыдущую
версию файла как «текущую». В окне после мержа любой агент получает устаревшую картину и не узнаёт
об этом. Ручной `POST /api/memory/reindex` чинит за ~4 минуты.
Триггер переиндексации — fire-and-forget (`app/routes/sessions.py:678-687`), поэтому недоказуемо,
«не сработал» он или «не успел».
Воспроизведение: смержить ветку, изменившую CLAUDE.md, и сразу спросить `search_memory` про
перенесённый фрагмент — вернётся дореформенная версия.
Что мешает: неясно, нужна ли синхронная переиндексация (4 мин блокировки merge неприемлемы) или
достаточно статуса/повторной попытки. Нужен замер реального времени и надёжности триггера.

## [2026-07-26 09:45 UTC] `.claude/skills/` в Claude-worktree не обновляется после создания
- **Reporter:** Orchestra-orchestrator
- **Scope:** /mnt/data/Projects/Python/orchestra
Скиллы копируются в worktree воркера при СОЗДАНИИ и больше не синхронизируются. У воркера
`audit-fullcycle` в `.claude/skills/` до сих пор лежит `self-analysis`, удалённый из пайплайна
2026-07-26. Тот же класс, что был у зеркала `AGENTS.md` (снимок при рождении).
Воспроизведение: `ls worktrees/<scope>/<worker>/.claude/skills/` у давно созданного Claude-воркера.
Что мешает: осознанно вынесено за скоуп задачи #89 (там решался Codex-путь). Нужно решить, где
синхронизировать — по аналогии с `workspace.sync_agents_md()` на коннекте бэкенда.
