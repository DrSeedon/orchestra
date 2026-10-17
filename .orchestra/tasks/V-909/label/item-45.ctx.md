# Context for item-45

## Diff reviewed (-U20, capped at 1500 lines)

diff --git a/.orchestra/pipelines/default/prompts/modules/background-jobs.md b/.orchestra/pipelines/default/prompts/modules/background-jobs.md
index 2fbbb8c04..ac142efcf 100644
--- a/.orchestra/pipelines/default/prompts/modules/background-jobs.md
+++ b/.orchestra/pipelines/default/prompts/modules/background-jobs.md
@@ -1,26 +1,21 @@
 ## Background jobs — what the tool description does not tell you
 
 Types, parameters and examples live in the `bg_create` tool description; it is the owner, and
 `base.md` already carries the "never sleep or poll" rule. Only these are yours:
 
 - **`message` must explain WHY, not WHAT to check.** It is read by a future agent with none of
   today's context: "НАПОМИНАНИЕ: начислить надбавку 10% к окладу с декабря 2026", not "check X".
 - **Never create a timer to retry a delivery.** A message or first task that the quota gate
   holds back is accepted into a durable queue (`WAITING_QUOTA`) and goes out by itself, in
   order, when the gate opens — also after a restart. The receipt gives an estimate; do not
   resend and do not wake yourself to "retry in N hours": each such wake is a paid turn.
   To withdraw a queued message use `cancel_message_delivery`; read its state with
   `message_delivery_status`.
 - **A job you created is yours to cancel.** A recurring job outlives the reason it was created;
   when that reason is gone, `bg_cancel` it instead of letting it wake agents forever.
-- **Для проверки после окончания работы используй переиспользуемый idle-сторож на себе:**
-  `bg_create(type="idle", timeout_seconds=0, message="Проверь результат задачи: собери доклады,
-  проверь ошибки доставки; если работа завершена — дай итог и отмени этот сторож.")`.
-  Он срабатывает, когда ты idle, никто из твоих потомков не выполняет ход и нет других
-  активных фоновых заданий в этом дереве. Сам сторож не удерживает статус waiting.
-  Повторный bg_create(type="idle") заменяет твой прежний сторож. Новая активность вновь
-  вооружает его; собственное пробуждение и ответ не создают бесконечный цикл.
-  Это сигнал проверить результат, а не доказательство, что работа успешна или стояла:
-  доклады могут не дойти из-за отказа доставки. Проверяй ошибки и фактические результаты.
-  Зависший running-воркер не считается idle; этот тип не заменяет диагностику зависаний.
-  Будить по таймеру каждые 30 минут по умолчанию больше не требуется.
+- **Отчёт воркера не нужно страховать сторожем.** Если ход воркера кончился, а он тебе
+  ничего не написал (ошибка, обрыв, смерть процесса, рестарт Orchestra), платформа сама,
+  durable и ровно один раз, присылает тебе сообщение `[auto-report]`: кто, чем кончился ход,
+  последний вывод. Нормальный DONE от воркера дубля не даёт. Не ставь для этого `bg_create`
+  и не жди по таймеру. Получив `[auto-report]`, проверь фактический результат, а не только
+  текст: он говорит о конце хода, а не об успехе работы.
diff --git a/CHANGELOG.md b/CHANGELOG.md
index ba1c08000..b2a700d60 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -1,34 +1,45 @@
 # Changelog
 
 > **Two environments merged, 04.08.2026.** Before this date, the laptop and VPS maintained
 > their CHANGELOGs independently, so versions 2.31.0-2.33.0 were used TWICE for different
 > content: the VPS block comes first below, followed by the laptop block. Task #52 fixes the format.
 
 ## Unreleased
 
 ### Added
 - **Доставка, отбитая гейтом квот, ждёт его снятия внутри платформы — таймер «повтори через N часов» больше не нужен** (`app/quota_queue.py`, состояние `WAITING_QUOTA` в `message_deliveries`/`initial_deliveries`). Раньше `send_message` и `spawn_worker` получали 429 `weekly_quota_blocked`, и оркестратор ставил себе bg-таймер: ~4 таких таймера в сутки с 23.09, каждое пробуждение — платный ход, часто впустую. Теперь отбитое сообщение принимается durable-доставкой (приёмка в `routes/sessions.py: _preflight_or_quota_wait`, отказ runner'а в `run_message_delivery` переводит в ожидание вместо `FAILED_BEFORE_SUBMIT`), отправитель сразу получает «принято в очередь» с оценкой времени (`next_action.eta_at`), а `quota_queue.release_waiting` возвращает строки в обычную очередь, когда гейт пропускает: циклом раз в минуту (`quota_release_loop`, стартует в lifespan) и немедленно при `POST /api/usage/quota-override` (в ответе `released_deliveries`). Порядок к одному адресату сохраняется (`accept_seq`, ждущая голова держит очередь), повтор с тем же `delivery_id` дубля не даёт, рестарт ничего не теряет (строки в SQLite, `recover_*` их не трогают). Первое задание нового воркера не обгоняется прямыми сообщениями ему. Сменил задачу/убит адресат к моменту выпуска — доставка падает громко (`TARGET_TASK_CHANGED`/`FAILED_BEFORE_SUBMIT`), отправителю уходит платформенное сообщение. Отмена: тул `cancel_message_delivery` и `POST /api/message-deliveries/{id}/cancel` (только ещё не ушедшее: `WAITING_QUOTA`/`QUEUED`), список ждущих: `GET /api/message-deliveries`. Промпт `modules/background-jobs.md` запрещает ставить таймеры повтора доставки. Тесты `tests/test_quota_wait_queue.py`.
 
 ### Changed
 - **`spawn_worker` при закрытом гейте квот больше не отказывает** (`SessionManager.create_session`): воркер создаётся, а его первое задание ждёт в `WAITING_QUOTA` и уходит само. Прежний отказ до создания (#227) нужен был, чтобы не плодить «мёртвые» сессии, но теперь первый `/send` не отбивается, и мёртвой сессия не бывает. Известный компромисс: пока гейт закрыт, простаивающий воркер с привязанной задачей и worktree существует; неотправленное задание видно в `delivery_status`.
 - Не затронут путь без `delivery_id` (HTTP `/send` от UI/TG): там по-прежнему работают сообщения в памяти сессии и уведомление `quota_blocked`; перенос их в durable-очередь — отдельная работа.
+- **Конец хода воркера без отчёта родителю теперь durable-сигнал платформы вместо idle-сторожа** (`app/turn_signals.py`, `_make_idle_callback` и `auto_resume_all` в `app/manager.py`, `TurnManager.report_abnormal_end` в `app/session_turns.py`). Раньше авто-отчёт жил в `asyncio`-задаче: отказ доставки (`DrainingRefused` при рестарте, `QuotaGateError`, `CLIConnectionError`) оставлял запись в журнале «автоматического повтора нет», смерть слушателя / обрыв потока / сбой автопродолжения вообще не вызывали отчёта, а ход, убитый рестартом, не сообщал родителю ничего. Оркестраторы страховались `bg_create(type="idle")`. Теперь факт пишется в таблицу `turn_signals` (UNIQUE по сессии+процессу+номеру хода → одно пробуждение на ход, сколько бы путей его ни заметило), доставляется сразу и повторяется sweeper'ом с backoff до принятия родителем; после рестарта pending-строки доезжают, а для ходов, оборванных рестартом, сигнал создаётся при старте (если воркер не успел написать родителю). Сигналы одного родителя, созревшие вместе (типично — после рестарта), уходят одним сообщением; перед повтором лог родителя проверяется на ссылку `turn_signal[id]`, чтобы падение между «принято» и «помечено» не дублировало. Явный DONE дубля не даёт (прежний гейт `_did_report`). Триггер: 8 недоставленных авто-отчётов с 13.08 (6 — дренаж рестарта) и 154 постановки idle-сторожа, 150 из них в сентябре. Тесты `tests/test_turn_signals.py`.
+- В промпте оркестратора (`background-jobs.md`) вместо рекомендации ставить idle-сторожа — описание этого сигнала.
+
+### Changed
+- `bump_turn_gen` больше не отменяет отложенный авто-отчёт прошлого хода: теперь это записанный факт, и начало следующего хода (до того, как задача успела записать строку) не должно его стирать.
+
+### Removed
+- `_record_undelivered_auto_report` и `_auto_report_key` (политика «ретраев нет», #30/#47/#50) вместе с тестами `test_auto_report_undelivered.py`: заменены повтором из `turn_signals`.
+
+### Known tradeoff
+- Для хода, оборванного рестартом, «воркер уже писал родителю» определяется по журналу родителя с момента последнего входящего воркера; сообщение, пришедшее воркеру посреди хода после его DONE, даст лишнее пробуждение, а не потерю.
 
 ### Fixed
 - **Иконка простоя TG-топика появлялась через 5 минут после конца хода** (`_TOPIC_STATUS_IDLE_FADE_DELAY_SECONDS` в `app/tg_bridge.py`: 300 → 60 с). Пауза из #99 защищает от мигания иконки между частыми ходами, но 5 минут владелец воспринимал как «иконки запаздывают». Успешная смена иконки теперь пишется в журнал (`TG topic_status <orch> -> running|idle (edit Ns)`); раньше логировались только отказы, и реальную задержку нельзя было измерить.
 - **Сжатие контекста (компакт) срывалось у агентов OpenRouter: ack-ход не укладывался в 60 с** (`_compact_ack_timeout`, `COMPACT_ACK_TIMEOUT_SECONDS`/`_HARNESS` в `app/session.py`). После сжатия платформа поднимает свежую сессию без префикс-кеша и шлёт «Acknowledge briefly», ожидая завершения хода `asyncio.wait_for(..., timeout=60)`. DeepSeek V4.1 Flash на OpenRouter (7–83 tps у разных провайдеров) не отвечал за минуту на полном перечитывании системного промпта → таймаут → откат к несжатой сессии, агент залипал у потолка контекста. Триггер: `openrouter-lab-orchestrator`, компакт с 59% контекста — «compact ack turn did not complete (60s)». Лимит для Claude/Codex оставлен 60 с, для Harness поднят до 240 с; переопределяется `COMPACT_ACK_TIMEOUT_SECONDS`. Тест `test_compact_ack_timeout_is_longer_for_harness`.
 
 ### Added
 - **Панель JOBS (фоновые задания агентов) стала читаемой и попала на временную ленту** (`app/static/js/jobs-timeline.js`, `renderJobsPanel`; стили `.job-*` в `style.css`; `switchLeftTab` расширяет панель до 380 px на вкладке). Раньше строка показывала `timer/cron/idle`, обрезанный на 50 символов текст и «ACTIVE». Теперь карточка: человеческий тип («Напоминание», «По расписанию», «Сторож простоя», «Команда в фоне»…), полный текст «зачем» (3 строки, раскрывается кликом), «поставил X → разбудит Y», когда сработает — «через 3 ч» и абсолютно в Красноярске, у cron следующий запуск считается по `cron_expr` (UTC, как в `bg_jobs`) плюс последний запуск и число срабатываний, статус и ошибка. Переключатель «По агентам / Лента»: лента — прошедшие и будущие события по времени с границей «СЕЙЧАС». Забытое бросается в глаза: активное не-таймерное задание старше 2 дней помечено «⚠ висит N дн» (красным с 7 дней), таймер с вышедшим сроком — «застряло»; в шапке счётчик забытых. Отмена — кнопка ✕ (с подтверждением) через существующий `DELETE /api/bg/jobs/{id}`. Тест `tests/test_jobs_view.py` (разбор cron, правило «забытого»).
 ### Changed
 - `bg_get_jobs`: лимит 50 → 200 и активные впереди завершённых, иначе самые старые (то есть забытые) активные задания выпадали из списка за новыми завершёнными. Требует рестарта Python. История завершённых по-прежнему стирается через сутки (`bg_cleanup_old`), поэтому прошлое на ленте — это последние 24 часа.
 - Из `app.js` удалены старые `renderJobsPanel`/`_createJobItem`/`cancelJob`/`_timeLeft`/`_elapsed` (заменены в `jobs-timeline.js`); `_JOB_ICONS` дополнен новыми типами.
 
 ### Added
 - **Закрепление провайдера OpenRouter по цене кеша** (`_provider_order` в `app/harness/llm.py`, поле `provider` в `_build_body`). Без пина OpenRouter сам маршрутизировал на дорогого Together ($0.006/1М чтения кеша, $1.20/1М выход). Теперь запрос несёт `provider.order = [DeepInfra, StreamLake, GMICloud]` с `allow_fallbacks: true`: порядок по стоимости чтения кеша (главная статья расхода при перечитывании контекста), откат не даёт агенту зависнуть, если провайдер не обслуживает модель (GLM у этих нет — уходит к дефолтным). Переопределяется `HARNESS_PROVIDER_ORDER` без правки кода; пустая строка возвращает авторутинг. На нашем профиле (99% кеша, ~1.7 млрд читаемых токенов/день) это ~$11/день против ~$19 на Together. Тест `test_provider_order_pins_cheap_providers_with_fallback`.
 
 ### Fixed
 - **Дашборд показывал «кеш 0.00%» у агентов OpenRouter, хотя провайдер кешировал до 99%** (`_cached_prompt_tokens`, `_cache_hit_pct` в `app/backend_harness.py`; `_accumulate`, `_turn_end`, `_error_turn_end`). OpenRouter возвращает `usage.prompt_tokens_details.cached_tokens`, но backend выбрасывал это число и жёстко писал `cache_hit: 0`, а весь `prompt_tokens` (включая кеш) шёл в `input_tokens`. Теперь кешированная часть вычитается из входа в `cache_read`, а `cache_hit` считается как её доля от промпта. Деньги не пересчитываются — стоимость берётся из ответа провайдера, где скидка за кеш уже применена. Триггер: `openrouter-lab-orchestrator` на DeepSeek V4.1 Flash, ход с 55 652 токенами промпта, 55 168 из них кеш (99.1%), в дашборде «кеш 0.00%». Тесты: `test_openrouter_cached_prompt_tokens_split_into_cache_read_and_hit_pct`, `test_turn_end_reports_cache_read_tokens_not_zero`.
 
 ### Added
 - **Агенты Harness (OpenRouter, GigaChat) видят правила проекта** (`project_instructions` в `app/harness/prompts.py`, `HarnessBackend._refresh_system_prompt`). Claude и Codex читают CLAUDE.md/AGENTS.md сами, а Harness до сих пор собирал системное сообщение только из промпта роли. Правила проекта до его агентов не доходили: в первом ходе `openrouter-lab-orchestrator` их не было. Теперь правила читаются так же, как в управляемом Codex: от корня git до cwd, по одному файлу на каталог (AGENTS.md, иначе CLAUDE.md), симлинк на тот же файл не дублируется, потолок 32 KiB как у Codex. Личные глобальные файлы не читаются, по решению V-570. Перечитываются на каждом ходу: правка доходит со следующего хода. Пока файл не меняется, системное сообщение остаётся тем же, и кеш провайдера не сбивается. Тесты: `test_project_rules_reach_the_harness_like_managed_codex`, `test_edited_project_rules_apply_on_the_next_turn`.
 - **Платные маршруты OpenRouter по белому списку владельца** (`PAID_HARNESS_ROUTES` и `harness_route_allowed` в `app/models.py`; допуск в `validate_harness_model_spec`, `normalize_catalog_model`, `OpenRouterClient._validate_route`). Раньше Harness пускал только точные `:free` маршруты, и оркестратор на DeepSeek V4.1 Flash (бесплатного варианта нет) создать было нельзя. В списке три маршрута: `deepseek/deepseek-v4.1-flash`, `z-ai/glm-5.3`, `z-ai/glm-5.3-flash` — владелец открыл их 01.10 для экспериментов с оркестраторами на OpenRouter (GLM-5.4 в каталоге нет, последняя GLM-5.3). Остальные платные маршруты по-прежнему отклоняются. Требование нулевой стоимости `usage.cost` сохранено для `:free`; у платного маршрута стоимость идёт в учёт сессии. Тесты: `test_owner_listed_paid_route_is_billed_and_others_stay_blocked`, `test_catalog_admits_only_free_or_owner_listed_paid_routes`.
diff --git a/app/main.py b/app/main.py
index efd4cc370..aa5b01680 100644
--- a/app/main.py
+++ b/app/main.py
@@ -316,40 +316,44 @@ async def drain_mutating_requests(budget_s: float = MUTATING_DRAIN_BUDGET_S) ->
     deadline = loop.time() + budget_s
     while loop.time() < deadline:
         if inflight_mutating_count() == 0:
             return True
         await asyncio.sleep(DRAIN_POLL_S)
     return inflight_mutating_count() == 0
 
 
 async def _shutdown_runtime(
     restart_inbox_drain: "asyncio.Task | None",
     snapshot_task: asyncio.Task,
     bridge_task: asyncio.Task,
 ) -> None:
     startup_tasks = {
         task for task in (
             restart_inbox_drain,
             snapshot_task,
         )
         if task is not None and not task.done()
     }
+    from app import turn_signals
+    sweeper = turn_signals.sweeper_task()
+    if sweeper is not None:
+        startup_tasks.add(sweeper)
     for task in startup_tasks:
         task.cancel()
     if startup_tasks:
         await asyncio.gather(*startup_tasks, return_exceptions=True)
 
     from app.merge_operations import shutdown_merge_operations
     restart_guard.note_shutdown_phase("merge_operations", "shutdown_merge_operations")
     await shutdown_merge_operations()
 
     from app.tg_file_deliveries import shutdown_file_delivery_service
     restart_guard.note_shutdown_phase(
         "tg_file_deliveries", "shutdown_file_delivery_service"
     )
     await shutdown_file_delivery_service()
 
     bridge_task.cancel()
     restart_guard.note_shutdown_phase("bridge_task", "asyncio.Task[bridge]")
     try:
         await bridge_task
     except (asyncio.CancelledError, Exception):
@@ -435,40 +439,42 @@ async def lifespan(app: FastAPI):
                 while not is_proxy_connected():
                     await asyncio.sleep(60)
                     await refresh_models()
                     if is_proxy_connected():
                         logger.info("Proxy reconnected, models loaded")
                         break
             asyncio.create_task(_proxy_retry_loop())
         await manager.auto_resume_all()
         from app.routes.tg import resume_dashboard_voice_transcriptions
         await resume_dashboard_voice_transcriptions()
         await recover_initial_deliveries()
         await recover_message_deliveries()
         from app.fan_barrier import recover_deadlines
         recover_deadlines()
         from app.bootstrap import ensure_bootstrap
         await ensure_bootstrap()
         manager.start_background_tasks()
         # #269: messages accepted while the previous process was restarting. In the background —
         # a delivery runs the agent's turn, and startup must not wait for it.
         schedule_restart_inbox_drain()
+        from app import turn_signals
+        turn_signals.start_sweeper(manager)
         from app.bg_jobs import bg_manager
         bg_manager.set_session_manager(manager)
         await bg_manager.restore_from_db()
         # TG-мост поднимаем фоном. Замер (.orchestra/tasks/15/research.md): один только импорт
         # app.tg_bridge стоит 4.05 с, из них 3.72 с — aiogram, и всё это время uvicorn не
         # принимает запросы, а nginx отдаёт 502. Старт сервиса был 4.3-13.9 с; для приёма
         # HTTP мост не нужен. Плата: polling TG стартует на несколько секунд позже, и команда
         # из TG в это окно выполнится с задержкой (Telegram её не теряет).
         bridge_task = asyncio.create_task(_start_bridge_background(manager))
         from app.routes.system import _usage_snapshot_loop
         snapshot_task = asyncio.create_task(_usage_snapshot_loop())
         from app.quota_queue import quota_release_loop
         quota_release_task = asyncio.create_task(quota_release_loop())
         from app.runaway_guard import ensure_task as ensure_runaway_guard
         ensure_runaway_guard(app)
         from app.merge_operations import restore_merge_operations
         await restore_merge_operations()
         if _fdstore.notify_ready():
             logger.info("systemd readiness published after application startup gates")
         yield
diff --git a/app/manager.py b/app/manager.py
index f8229d503..86c964ad3 100644
--- a/app/manager.py
+++ b/app/manager.py
@@ -131,54 +131,40 @@ async def wait_for_session_lock(lock, *, what: str, worker: str, limit: float |
     # Предел читается в момент вызова, а не как значение по умолчанию: значение по умолчанию
     # вычисляется при определении функции, и подмена константы в тесте молча не сработала бы.
     limit = LOCK_WAIT_LIMIT_SECONDS if limit is None else limit
     started = time.monotonic()
     try:
         await asyncio.wait_for(lock.acquire(), timeout=limit)
     except asyncio.TimeoutError:
         waited = time.monotonic() - started
         logger.warning("%s for %s gave up after %.1fs waiting for the session lock",
                        what, worker, waited)
         raise LockBusy(what, worker, waited) from None
     waited = time.monotonic() - started
     if waited > 0.5:
         logger.warning("%s for %s waited %.1fs for the session lock", what, worker, waited)
     try:
         yield waited
     finally:
         lock.release()
 
 
-def _auto_report_key(worker_session, worker_name: str) -> str:
-    """Ключ дедупликации автоотчёта (#50).
-
-    Стабильного id хода в системе нет: `_turn_gen` — счётчик в памяти сессии, он
-    обнуляется рестартом. Поэтому ключ строится из id сессии и номера хода, а когда
-    сессия недоступна — из имени и времени, и это ВИДНО в самом ключе (`notrack`).
-    Два быстрых автоотчёта тогда дадут две записи; это лучше, чем невидимо склеить
-    два разных события в одно.
-    """
-    if worker_session is not None:
-        return f"autoreport:{worker_session.id}:{getattr(worker_session, '_turn_gen', 0)}"
-    return f"autoreport:{worker_name}:notrack:{datetime.now(timezone.utc).isoformat()}"
-
-
 def next_adhoc_branch(worker_name: str) -> str:
     """Имя ветки для авто-переключения перед доставкой сообщения.
 
     Секунды эпохи БЕЗ усечения. Прежняя форма `str(int(time.time()))[-6:]` замыкала
     пространство имён каждые 10**6 с = 11.57 суток, а ветки `adhoc-*` не удаляются —
     столкновение было гарантировано временем, а не вероятностью, и приводило к тихому
     переселению воркера на чужую ветку 11-суточной давности (#27, E2).
 
     ВНИМАНИЕ, зависимость между слоями: порядковый номер живёт в ПРОЦЕССЕ и обнуляется
     рестартом, поэтому теоретически возможен повтор имени при рестарте внутри одной
     секунды. Это допустимо ТОЛЬКО потому, что второй слой — `expect_absent=True` в
     `switch_worktree_branch` — делает такой повтор громким отказом. Снимете второй слой
     как «лишнюю паранойю» — вернёте тихую порчу данных, а не просто упростите код.
     """
     return f"adhoc-{int(time.time())}-{next(_adhoc_serial)}/{worker_name}"
 
 from app.runtime_env import MCP_BASE_ENV, MCP_STDIO_CMD  # noqa: F401 — re-exported for callers
 
 COLOR_PALETTE = [
     "#818cf8", "#34d399", "#f97316", "#38bdf8", "#f472b6",
@@ -2073,73 +2059,65 @@ class SessionManager:
         if len(names) > 1:
             raise ValueError("multiple orchestrators in this project; specify the worker's parent")
         return names[0] if names else None
 
     def _context_warning(self, worker_name: str) -> str:
         session = next((s for s in self.sessions.values() if s.name == worker_name), None)
         if not session:
             return ""
         pct = session._last_context.get("percentage", 0)
         if pct >= 90:
             return f"\n⚠️ CONTEXT CRITICAL: {pct}% — do NOT send more tasks to this worker"
         return ""
 
     def _make_idle_callback(self, scope: str):
         async def _on_worker_idle(
                 worker_name: str,
                 worker_scope: str,
                 last_texts: list[str],
                 stop_reason: str = "",
                 turn_ok: bool = True):
+            """Record the unreported end of a turn durably, then try to deliver it now.
+
+            Delivery retries and restart recovery belong to `turn_signals`; nothing here
+            may drop the fact on a failed send.
+            """
+            from app import turn_signals
+
             worker_session = next((s for s in self.sessions.values() if s.name == worker_name), None)
-            parent = worker_session.parent_name if worker_session else None
-            orch = parent or self._find_orchestrator_name(scope)
-            if not orch:
-                return
-            orch_session = next((s for s in self.sessions.values() if s.name == orch), None)
-            if not orch_session:
+            worker_id = worker_session.id if worker_session else ""
+            if not worker_id:
+                row = get_session_by_name(worker_name, (worker_scope or scope).rstrip("/"))
+                worker_id = row["id"] if row else ""
+            if not worker_id:
                 return
-            summary = "\n".join(last_texts[-3:]) if last_texts else "(no output)"
-            ctx = self._context_warning(worker_name)
-            sr = f" (stop_reason={stop_reason})" if stop_reason else ""
-            outcome = (
-                "Finished without explicit report"
-                if turn_ok
-                else "Turn failed before an explicit report"
-            )
-            msg = (
-                f"[from:{worker_name}] [auto-report]{sr} {outcome}. "
-                f"Last output:\n{summary}{ctx}"
+            signal_id = turn_signals.record(
+                key=turn_signals.make_key(worker_session, worker_name),
+                worker_session_id=worker_id, worker_name=worker_name,
+                scope=(worker_scope or scope), turn_ok=turn_ok,
+                stop_reason=stop_reason,
+                summary="\n".join(last_texts[-3:]) if last_texts else "(no output)",
             )
-            logger.info(f"Auto-report: {worker_name} → {orch}")
-            try:
-                provenance = MessageProvenance(
-                    origin="agent", senders=(worker_name,), subtype="auto_report",
-                )
-                await self.send(
-                    orch_session.id, msg, provenance=provenance,
-                )
-            except Exception as error:
-                await self._record_undelivered_auto_report(
-                    worker_name, worker_scope or scope, worker_session,
-                    orch_session, error,
-                )
+            if signal_id is None:
+                return
+            logger.info(f"Auto-report: {worker_name} recorded as turn signal {signal_id}")
+            await turn_signals.deliver_due(self, [signal_id])
         return _on_worker_idle
 
     def _make_quota_blocked_callback(self, scope: str):
         async def _on_turn_blocked(worker, error, retained_count: int) -> None:
             message = (
                 f"[from:{worker.name}] New worker turn blocked by the quota line; "
                 f"{retained_count} queued message(s) retained. {error} "
                 "Luna and Spark are outside the line. "
                 "Stop and model change remain available."
             )
             parent = None
             if worker.parent_id:
                 parent = self.sessions.get(worker.parent_id)
             if parent is None and worker.parent_name:
                 parent = self.get_by_name(worker.parent_name, worker.scope)
             if parent is not None and parent.is_orchestrator:
                 try:
                     provenance = MessageProvenance(
                         origin="agent", senders=(worker.name,),
                         subtype="quota_blocked",
@@ -2149,88 +2127,40 @@ class SessionManager:
                     )
                     return
                 except Exception as delivery_error:
                     reason = f"{error}; parent delivery failed: {err_text(delivery_error)}"
             else:
                 reason = f"{error}; exact parent orchestrator is unavailable"
 
             from app.notify import report_undelivered
 
             await report_undelivered(
                 self,
                 scope=worker.scope or scope,
                 worker=worker.name,
                 what=f"quota-block notice ({retained_count} queued message(s))",
                 reason=reason,
                 dedupe_key=f"quota:{worker.id}:{error.decision.provider}",
             )
 
         return _on_turn_blocked
 
-    async def _record_undelivered_auto_report(
-        self, worker_name: str, worker_scope: str, worker_session,
-        orch_session, error: Exception,
-    ) -> None:
-        """Автоотчёт не дошёл — оставить след, не зависящий от сломанного канала (#47).
-
-        Автоотчёт существует ровно для того, чтобы ждущий оркестратор не остался без
-        сигнала. Поэтому запись идёт в историю ОБЕИХ сессий: в дашборде видно и со стороны
-        воркера («я отчитался, но не дошло»), и со стороны того, кто ждёт.
-
-        Попытка уведомить оркестратора отдельным сообщением делается, но её исход попадает
-        в ту же запись: тихая попытка была бы тем же дефектом, который мы чиним.
-        Повтора нет — по решению #30 ретраи не вводим.
-        """
-        from app.db import add_log
-        from app.notify import report_undelivered
-
-        detail = f"{type(error).__name__}: {error}"
-        attempt = await report_undelivered(
-            self,
-            scope=worker_scope,
-            worker=worker_name,
-            what="автоотчёт",
-            reason=detail,
-            dedupe_key=_auto_report_key(worker_session, worker_name),
-        )
-        # Причина не дублируется: в исходе попытки она чаще всего та же самая, и запись
-        # раздувается вдвое ровно там, где её будет читать человек.
-        if detail in attempt:
-            attempt = attempt.replace(detail, "та же причина")
-        text = (
-            f"[доставка] автоотчёт воркера «{worker_name}» не доставлен "
-            f"оркестратору «{orch_session.name}»: {detail}. "
-            f"Попытка уведомить отдельным сообщением: {attempt}. "
-            f"Автоматического повтора нет — воркер ждёт продолжения."
-        )
-        logger.warning(text)
-        now = datetime.now(timezone.utc)
-        # Сессия воркера может быть уже выгружена — тогда пишем только тому, кто ждёт.
-        for session in (s for s in (worker_session, orch_session) if s is not None):
-            try:
-                await asyncio.to_thread(add_log, session.id, now, "system", text)
-            except Exception as log_error:
-                logger.warning(
-                    "could not record undelivered auto-report for %s: %s: %s",
-                    session.name, type(log_error).__name__, log_error,
-                )
-
     # ── Listings ──
 
     # Поля, которые НЕ едут в списке сессий. Список опрашивается раз в 3 секунды, и его вес —
     # это не скорость, а ВЕРОЯТНОСТЬ ДОСТАВКИ: у юзера между нами и его машиной прозрачный
     # посредник, на котором ответы до ~15 КБ доходят 10 из 10, а крупные — 17 из 33 (#65,
     # замер perf). `system_prompt` — 86.4% веса ответа по проводу (46.9 КБ из 54.3),
     # `last_summary` — ещё 5.9%. Ни одно из двух в списке не читается:
     # промпт берётся отдельным роутом `GET /api/sessions/{name}/prompt` по кнопке 📜,
     # а `last_summary` нужен только серверу (`runtime_handoff`).
     # Понадобилось поле в списке — добавляй осознанно и перемеряй вес: tests/test_manager.py::TestListSessions
     # держит потолок.
     _LIST_OMIT = ("system_prompt", "prompt_overlay", "last_summary")
 
     def list_sessions(self, scope: str | None = None) -> list[dict]:
         from app.db import get_last_turn_map
         from app.message_deliveries import targets_with_uncertain_delivery
         result = []
         seen = set()
         for s in self.sessions.values():
             if scope is None or s.scope == scope:
@@ -2354,53 +2284,62 @@ class SessionManager:
             if color is None:
                 continue
             session.color = color
             if session.db_row is not None:
                 session.db_row["color"] = color
 
     def stats(self, scope: str | None = None) -> dict:
         return get_stats(scope)
 
     # ── Startup / Shutdown ──
 
 
     async def auto_resume_all(self) -> None:
         self.reconcile_live_colors()
         from app.db import _conn
         with _conn() as c:
             # 'interrupted' — graceful shutdown успел пометить оборванный ход;
             # 'running' — не успел (SIGKILL/OOM). Оба означают одно: ход прерван
             # рестартом. Читать только 'running' значило будить лишь тех, кого
             # застал аварийный путь (#160).
-            was_running = {r["id"] for r in c.execute(
-                "SELECT id FROM sessions WHERE status IN ('running', 'interrupted')"
-            ).fetchall()}
+            was_running_rows = [dict(r) for r in c.execute(
+                "SELECT * FROM sessions WHERE status IN ('running', 'interrupted')"
+            ).fetchall()]
+            was_running = {r["id"] for r in was_running_rows}
             was_waiting = {r["id"] for r in c.execute(
                 "SELECT id FROM sessions WHERE status = 'waiting'"
             ).fetchall()}
             resumable = [dict(r) for r in c.execute(
                 "SELECT * FROM sessions WHERE session_id IS NOT NULL "
                 "AND status IN ('running', 'interrupted', 'idle', 'waiting')"
             ).fetchall()]
             c.execute("UPDATE sessions SET status='idle' "
                       "WHERE status IN ('running', 'interrupted', 'waiting')")
 
+        # V-680: the parent learns that these turns ended, durably and before any load can fail.
+        from app import turn_signals
+        try:
+            turn_signals.record_interrupted_by_restart(was_running_rows)
+        except Exception as error:
+            logger.error("turn signals for restart-interrupted turns failed: %s: %s",
+                         type(error).__name__, error)
+
         # R1: load orchestrators first — workers need their parent_name resolved,
         # and the orchestrator's on_idle callback registered before workers resume
         orchs = [r for r in resumable if bool(r.get("is_orchestrator")) or is_orchestrator_role(r.get("role", "worker"))]
         workers = [r for r in resumable if not (bool(r.get("is_orchestrator")) or is_orchestrator_role(r.get("role", "worker")))]
         pending_handoffs = {
             row["session_id"]: row for row in list_latest_runtime_handoffs()
         }
 
         for kind, rows in (("orchestrator", orchs), ("worker", workers)):
             for row in rows:
                 if row["id"] in self.sessions:
                     continue
                 if not Path(row.get("cwd") or row["scope"]).is_dir():
                     continue
                 try:
                     session = await self._load_from_db(
                         row, recovery_handoff=pending_handoffs.get(row["id"]),
                     )
                     logger.info("Resumed %s: %s", kind, row["name"])
                     if row["id"] in was_waiting:
diff --git a/app/session.py b/app/session.py
index b71493848..f3818750b 100644
--- a/app/session.py
+++ b/app/session.py
@@ -2111,40 +2111,41 @@ class AgentSession:
         self.session_id = None
         self.runtime_handoff = handoff
         self.history_import_source = None
         self._last_context = empty_context()
         self._log(
             "warning",
             "Codex native thread retired after an oversized JSONL record; "
             "the next connection starts fresh with a bounded Orchestra handoff",
         )
         self._persist()
 
     def _finish_failed_running_turn(self, reason: str) -> None:
         """Never leave RUNNING behind when the backend lost its turn."""
         if self.status != AgentStatus.RUNNING:
             return
         self._turn_start = 0
         self.status = AgentStatus.IDLE
         self._log("error", reason)
         self._persist()
         self._turns.publish_turn_finished()
+        self._turns.report_abnormal_end(reason)
         if self._pending_messages:
             self._spawn_bg(self._flush_pending())
         else:
             self._hibernate.schedule()
 
     MAX_CONSECUTIVE_FAILURES = 5
 
     async def _reconnect_backend(self) -> None:
         backend = self._backend
         if backend is None:
             raise RuntimeError("backend is unavailable for reconnect")
         if (
             self.backend_type == "claude"
             and self.history_import_source == CLAUDE_HISTORY_SOURCE
         ):
             if not self.session_id:
                 raise RuntimeError("DB-backed Claude reconnect has no session id")
             history = await self._build_claude_history_import(
                 self.session_id,
                 self.model,
@@ -2231,79 +2232,83 @@ class AgentSession:
                         provenance=MessageProvenance(
                             origin="system", senders=("system",), subtype="runtime_reconnect",
                         ),
                         retry_generation=generation,
                     )
                 continue
             except Exception as re_err:
                 logger.error(f"[{self.name}] listener reconnect failed: {err_text(re_err)}")
                 self._log("error", f"listener reconnect failed: {err_text(re_err)}")
                 if generation != (self._turn_gen, self._turn_start_cancel_gen):
                     continue
                 self._backend = None
                 self._finish_failed_running_turn(
                     f"listener reconnect failed: {err_text(re_err)}"
                 )
                 return
 
     async def _turn_event_loop(self) -> None:
         logger.info(f"[{self.name}] {self.backend_type} turn started")
         backend = self._backend
+        cancelled = False
         try:
             async for event in backend.events():
                 self._last_msg_time = asyncio.get_event_loop().time()
                 self._last_event = describe_event(event)
                 # thread.started is emitted before turn.completed. Store it now so an
                 # interrupted long turn can resume instead of silently starting fresh.
                 early_session_id = event.metadata.get("session_id") if event.type == "status" else None
                 if early_session_id and early_session_id != self.session_id:
                     self.session_id = early_session_id
                     self._persist()
                 if (
                     event.type == "turn_end"
                     and event.metadata.get("reader_failure")
                     and getattr(backend, "oversized_reader_failure", False)
                 ):
                     await self._retire_codex_reader_failure(
                         backend,
                         RuntimeError(str(event.metadata["reader_failure"])),
                     )
                 self._handle_event(event)
         except asyncio.CancelledError:
+            cancelled = True
             return
         except Exception as e:
             logger.error(f"[{self.name}] {self.backend_type} turn error: {e}")
             self._log("error", f"{self.backend_type} turn error: {e}")
         finally:
             if self.status == AgentStatus.RUNNING:
                 backend = self._backend
                 if (
                     self.backend_type == "codex"
                     and hasattr(backend, "active_turn_id")
                     and not getattr(backend, "active_turn_id", None)
                 ):
                     self._finish_failed_running_turn(
                         "Codex listener ended without an active turn"
                     )
                 else:
                     self.status = AgentStatus.IDLE
                     self._persist()
+                    if not cancelled:
+                        self._turns.report_abnormal_end("event stream ended without turn end")
                     if self._pending_messages:
                         self._spawn_bg(self._flush_pending())
                     else:
                         self._hibernate.schedule()
             if not self._compacting:
                 self._wake_durable_message_deliveries()
 
     def _wake_durable_message_deliveries(self) -> None:
         try:
             from app.message_deliveries import ensure_target_runner
 
             ensure_target_runner(self.id)
         except Exception as error:
             logger.warning(
                 "[%s] durable message-delivery wake failed: %s",
                 self.name,
                 err_text(error),
             )
 
     # ── Unified event handler ──
@@ -3292,40 +3297,41 @@ class AgentSession:
         try:
             await on_scope_idle(self)
         except Exception as e:
             logger.warning(f"[{self.name}] TG scope-idle notify failed: {e}")
 
     async def _notify_scope_running(self) -> None:
         if on_scope_running is None:
             return
         try:
             await on_scope_running(self)
         except Exception as e:
             logger.warning(f"[{self.name}] TG scope-running notify failed: {e}")
 
     def _finish_failed_continuation(self, generation: tuple[int, int]) -> bool:
         """An old automatic attempt cannot finish a newer or manually stopped turn."""
         if generation != (self._turn_gen, self._turn_start_cancel_gen):
             return False
         self.status = AgentStatus.IDLE
         self._persist()
         self._turns.publish_turn_finished()
+        self._turns.report_abnormal_end("automatic continuation failed")
         return True
 
     async def _rate_limit_retry(self, delay: int, expected_turn_gen: int) -> None:
         generation = (expected_turn_gen, self._turn_start_cancel_gen)
         await asyncio.sleep(delay)
         if (self._manually_interrupted or self._turn_gen != expected_turn_gen
                 or self._session_limit_hit):
             return
         try:
             provenance = MessageProvenance(
                 origin="system", senders=("system",), subtype="rate_limit_retry",
             )
             await self.send(
                 "[system] Retrying after rate limit. Continue where you left off.",
                 provenance=provenance,
                 retry_generation=generation,
             )
         except DrainingRefused as refusal:
             if not self._finish_failed_continuation(generation):
                 return
diff --git a/app/session_turns.py b/app/session_turns.py
index 6fff9b52e..c41616dff 100644
--- a/app/session_turns.py
+++ b/app/session_turns.py
@@ -167,44 +167,44 @@ def _cached_quota_snapshot(
 def _cached_quota_state(
     runtime: str,
     model: str,
     *,
     now: float | None = None,
 ) -> dict:
     return _cached_quota_snapshot(runtime, model, now=now)["state"]
 
 
 class TurnManager:
     def __init__(self, s: "AgentSession") -> None:
         self.s = s
 
     def cancel_auto_report(self) -> None:
         s = self.s
         if s._auto_report_task and not s._auto_report_task.done():
             s._auto_report_task.cancel()
         s._auto_report_task = None
 
     def bump_turn_gen(self) -> None:
-        """Новый ход начался — инвалидируем отложенный авто-репорт прошлого хода."""
+        """Новый ход начался. Авто-отчёт прошлого хода НЕ отменяется: это уже факт, он
+        записывается и доставляется durable (`turn_signals`), новый ход его не стирает."""
         self.s._turn_gen += 1
         self.s._turn_finished_event.clear()
-        self.cancel_auto_report()
 
     def publish_turn_finished(self) -> None:
         self.s._turn_finished_event.set()
 
     def fire_auto_report(self) -> None:
         """Send auto-report to parent immediately when worker goes idle.
         Orchestrators don't auto-report — they reply to user directly.
         Skipped if worker already sent explicit send_message, has pending messages,
         completed a successful silent turn, or was interrupted/stopped by user.
 
         Without this, silent workers (those that don't call send_message) would
         leave the orchestrator waiting forever for a signal that never comes.
         """
         s = self.s
         if s.is_orchestrator or not s.on_idle or s._manually_interrupted:
             return
         if s._pending_messages or s._compacting:
             return
         if s._last_turn_ok and not s._turn_logs:
             return
@@ -263,40 +263,48 @@ class TurnManager:
         if s._did_report or silent_turn:
             return
 
         last_texts = s._turn_logs[-5:] if s._turn_logs else []
         stop_reason = s._last_stop_reason
 
         async def _do_report():
             try:
                 await s.on_idle(
                     s.name,
                     s.scope,
                     last_texts,
                     stop_reason,
                     s._last_turn_ok,
                 )
             except Exception as e:
                 logger.error(f"Auto-report failed for {s.name}: {e}")
 
         s._auto_report_task = asyncio.create_task(_do_report())
 
+    def report_abnormal_end(self, reason: str) -> None:
+        """Ход закончился не событием turn_end (умер слушатель, оборван поток): родитель
+        всё равно должен узнать, как и после обычного неуспешного хода."""
+        s = self.s
+        s._last_turn_ok = False
+        s._last_stop_reason = reason
+        self.fire_auto_report()
+
     def handle_turn_end(self, event: AgentEvent) -> None:
         s = self.s
         meta = event.metadata
         cost_unaccounted = meta.get("cost_unaccounted") is True
         s._turn_start = 0
         ok, sr, nt = s._cost.apply_turn_result(meta, event.usage)
         event_id = str(meta.get("event_id") or "")
         if not ok and event_id:
             from app import message_deliveries
 
             try:
                 recovered = message_deliveries.requeue_failed_turn(s.id, event_id)
             except Exception as error:
                 logger.warning(
                     f"[{s.name}] failed-turn steer recovery unavailable: "
                     f"{type(error).__name__}: {error}"
                 )
                 recovered = 0
             if recovered:
                 s._log(
diff --git a/app/turn_signals.py b/app/turn_signals.py
new file mode 100644
index 000000000..a6476ac55
--- /dev/null
+++ b/app/turn_signals.py
@@ -0,0 +1,304 @@
+"""Durable end-of-turn signal from a worker to its parent (V-680).
+
+A worker turn can end without the worker having told its parent anything: an explicit
+DONE never sent, a provider error, a dead listener, a restart of Orchestra. The parent
+used to cover that with a self-armed `idle` watcher. Instead the platform records the
+fact in the same place the turn ends and delivers it itself.
+
+One row per (worker session, turn): `signal_key` is UNIQUE, so however many code paths
+notice the same turn ending, the parent is woken for it once. The row survives restart;
+a sweeper delivers pending rows with backoff until the parent accepts them. Rows that
+fall due together for one parent go out as one message — a restart ends many turns at
+once and each wake-up of an orchestrator is a paid turn.
+
+Delivery is at-least-once with a probe of the parent's log for the row's ref before a
+resend, so a crash between "parent accepted" and "row marked" does not repeat the message.
+"""
+
+from __future__ import annotations
+
+import asyncio
+import logging
+import time
+import uuid
+
+from app import db
+from app.errtext import err_text
+from app.events import MessageProvenance
+
+logger = logging.getLogger("orchestra.turn_signals")
+
+#: Distinguishes this process's in-memory turn counters from a previous process's.
+BOOT_ID = uuid.uuid4().hex
+
+SWEEP_INTERVAL_S = 30.0
+RETRY_BASE_S = 30.0
+RETRY_MAX_S = 900.0
+SEND_TIMEOUT_S = 120.0
+
+_DDL = """
+CREATE TABLE IF NOT EXISTS turn_signals (
+    id INTEGER PRIMARY KEY AUTOINCREMENT,
+    signal_key TEXT NOT NULL UNIQUE,
+    worker_session_id TEXT NOT NULL,
+    worker_name TEXT NOT NULL,
+    scope TEXT NOT NULL,
+    turn_ok INTEGER NOT NULL,
+    stop_reason TEXT NOT NULL DEFAULT '',
+    summary TEXT NOT NULL DEFAULT '',
+    state TEXT NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','delivered','dropped')),
+    attempts INTEGER NOT NULL DEFAULT 0,
+    next_attempt_at REAL NOT NULL DEFAULT 0,
+    last_error TEXT NOT NULL DEFAULT '',
+    created_at REAL NOT NULL,
+    delivered_at REAL
+);
+CREATE INDEX IF NOT EXISTS idx_turn_signals_pending ON turn_signals(next_attempt_at)
+    WHERE state = 'pending';
+"""
+
+_inflight: set[int] = set()
+_sweeper: asyncio.Task | None = None
+
+
+def ensure_schema() -> None:
+    with db._conn() as connection:
+        connection.executescript(_DDL)
+
+
+def make_key(session, worker_name: str) -> str:
+    """Identity of the turn that just ended, stable across code paths, unique across boots."""
+    if session is not None:
+        return f"{session.id}:{BOOT_ID}:{getattr(session, '_turn_gen', 0)}"
+    return f"{worker_name}:{BOOT_ID}:notrack:{time.time_ns()}"
+
+
+def record(
+    *, key: str, worker_session_id: str, worker_name: str, scope: str,
+    turn_ok: bool, stop_reason: str, summary: str,
+) -> int | None:
+    """Persist the fact. Returns the row id, or None when this turn is already recorded."""
+    ensure_schema()
+    with db._conn() as connection:
+        cursor = connection.execute(
+            """INSERT OR IGNORE INTO turn_signals
+               (signal_key, worker_session_id, worker_name, scope, turn_ok,
+                stop_reason, summary, created_at)
+               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
+            (key, worker_session_id, worker_name, scope, int(bool(turn_ok)),
+             stop_reason or "", summary or "", time.time()),
+        )
+        return int(cursor.lastrowid) if cursor.rowcount else None
+
+
+def _backoff(attempts: int) -> float:
+    return min(RETRY_BASE_S * (2 ** max(0, attempts - 1)), RETRY_MAX_S)
+
+
+def _due(only_ids: list[int] | None) -> list[dict]:
+    ensure_schema()
+    with db._conn() as connection:
+        rows = connection.execute(
+            "SELECT * FROM turn_signals WHERE state='pending' AND next_attempt_at<=? "
+            "ORDER BY id", (time.time(),),
+        ).fetchall()
+    result = [dict(row) for row in rows if row["id"] not in _inflight]
+    if only_ids is not None:
+        result = [row for row in result if row["id"] in only_ids]
+    return result
+
+
+def _finish(ids: list[int], state: str, error: str = "") -> None:
+    marks = ",".join("?" for _ in ids)
+    with db._conn() as connection:
+        connection.execute(
+            f"UPDATE turn_signals SET state=?, last_error=?, delivered_at=? WHERE id IN ({marks})",
+            (state, error, time.time(), *ids),
+        )
+
+
+def _retry_later(ids: list[int], error: str) -> None:
+    with db._conn() as connection:
+        for signal_id in ids:
+            attempts = connection.execute(
+                "SELECT attempts FROM turn_signals WHERE id=?", (signal_id,),
+            ).fetchone()["attempts"] + 1
+            connection.execute(
+                "UPDATE turn_signals SET attempts=?, last_error=?, next_attempt_at=? WHERE id=?",
+                (attempts, error, time.time() + _backoff(attempts), signal_id),
+            )
+
+
+async def _resolve_parent(manager, row: dict):
+    worker = db.get_session(row["worker_session_id"]) or {}
+    parent = None
+    if worker.get("parent_id"):
+        parent = await manager.ensure_loaded_by_id(worker["parent_id"])
+    elif worker.get("parent_name"):
+        parent = await manager.ensure_loaded(worker["parent_name"], row["scope"])
+    else:
+        try:
+            name = manager._find_orchestrator_name(row["scope"])
+        except ValueError:
+            name = None
+        if name:
+            parent = await manager.ensure_loaded(name, row["scope"])
+    return parent
+
+
+def _compose(manager, row: dict) -> str:
+    sr = f" (stop_reason={row['stop_reason']})" if row["stop_reason"] else ""
+    outcome = (
+        "Finished without explicit report" if row["turn_ok"]
+        else "Turn failed before an explicit report"
+    )
+    context = manager._context_warning(row["worker_name"])
+    return (
+        f"[from:{row['worker_name']}] [auto-report]{sr} {outcome}. "
+        f"Last output:\n{row['summary'] or '(no output)'}{context}"
+    )
+
+
+def _ref(ids: list[int]) -> str:
+    return "turn_signal" + "".join(f"[{i}]" for i in ids)
+
+
+def _already_in_parent_log(parent_id: str, signal_id: int) -> bool:
+    with db._conn() as connection:
+        return connection.execute(
+            "SELECT 1 FROM logs WHERE session_id=? AND type='user_message' "
+            "AND origin_detail LIKE '%turn_signal%' AND origin_detail LIKE ? LIMIT 1",
+            (parent_id, f"%[{signal_id}]%"),
+        ).fetchone() is not None
+
+
+async def deliver_due(manager, only_ids: list[int] | None = None) -> int:
+    """Send every due pending signal; one message per parent. Returns rows delivered."""
+    rows = _due(only_ids)
+    if not rows:
+        return 0
+    claimed = {row["id"] for row in rows}
+    _inflight.update(claimed)
+    delivered = 0
+    try:
+        groups: dict[str, tuple[object, list[dict]]] = {}
+        for row in rows:
+            try:
+                parent = await _resolve_parent(manager, row)
+            except Exception as error:
+                _retry_later([row["id"]], f"parent lookup failed: {err_text(error)}")
+                continue
+            if parent is None:
+                _finish([row["id"]], "dropped", "no parent session to notify")
+                logger.warning("turn signal %s for %s dropped: no parent", row["id"], row["worker_name"])
+                continue
+            groups.setdefault(parent.id, (parent, []))[1].append(row)
+        for parent, group in groups.values():
+            ids = [row["id"] for row in group]
+            fresh = [row for row in group if not _already_in_parent_log(parent.id, row["id"])]
+            stale = [row["id"] for row in group if row not in fresh]
+            if stale:
+                _finish(stale, "delivered", "found in parent log")
+            if not fresh:
+                continue
+            fresh_ids = [row["id"] for row in fresh]
+            try:
+                await asyncio.wait_for(
+                    manager.send(
+                        parent.id,
+                        "\n\n".join(_compose(manager, row) for row in fresh),
+                        provenance=MessageProvenance(
+                            origin="agent",
+                            senders=tuple(dict.fromkeys(row["worker_name"] for row in fresh)),
+                            subtype="auto_report", ref=_ref(fresh_ids),
+                        ),
+                    ),
+                    timeout=SEND_TIMEOUT_S,
+                )
+            except Exception as error:
+                detail = f"{type(error).__name__}: {err_text(error)}"
+                logger.warning("turn signal %s not delivered to %s: %s", fresh_ids, parent.name, detail)
+                _retry_later(fresh_ids, detail)
+                continue
+            _finish(fresh_ids, "delivered")
+            delivered += len(fresh_ids)
+            logger.info("turn signal %s delivered to %s", fresh_ids, parent.name)
+    finally:
+        _inflight.difference_update(claimed)
+    return delivered
+
+
+def _turn_started_at(session_id: str) -> str:
+    with db._conn() as connection:
+        row = connection.execute(
+            "SELECT MAX(ts) AS ts FROM logs WHERE session_id=? AND type='user_message'",
+            (session_id,),
+        ).fetchone()
+    return (row["ts"] if row else None) or ""
+
+
+def _reported_to_parent_since(worker: dict, since: str) -> bool:
+    parent_id = worker.get("parent_id") or ""
+    if not parent_id and worker.get("parent_name"):
+        parent = db.get_session_by_name(worker["parent_name"], worker["scope"])
+        parent_id = parent["id"] if parent else ""
+    if not parent_id or not since:
+        return False
+    with db._conn() as connection:
+        return connection.execute(
+            "SELECT 1 FROM logs WHERE session_id=? AND type='user_message' AND origin='agent' "
+            "AND ts>=? AND origin_detail LIKE ? AND origin_detail NOT LIKE '%auto_report%' LIMIT 1",
+            (parent_id, since, f'%"senders":["{worker["name"]}"]%'),
+        ).fetchone() is not None
+
+
+def record_interrupted_by_restart(rows: list[dict]) -> int:
+    """Called once per boot with sessions that were mid-turn when the process went away.
+
+    The turn is already dead and the worker will resume with a restart notice; the parent
+    still has to hear that the turn ended, unless the worker had reported during it.
+    """
+    from app import fan_barrier
+
+    recorded = 0
+    for worker in rows:
+        if worker.get("is_orchestrator") or worker.get("role") == "orchestrator":
+            continue
+        if not (worker.get("parent_id") or worker.get("parent_name")):
+            continue
+        if fan_barrier.should_buffer(worker["name"]):
+            continue
+        if _reported_to_parent_since(worker, _turn_started_at(worker["id"])):
+            continue
+        if record(
+            key=f"{worker['id']}:{BOOT_ID}:restart",
+            worker_session_id=worker["id"], worker_name=worker["name"],
+            scope=worker["scope"], turn_ok=False, stop_reason="interrupted_by_orchestra_restart",
+            summary="The turn was cut off by an Orchestra restart; the worker resumes "
+                    "from its saved conversation.",
+        ):
+            recorded += 1
+    return recorded
+
+
+async def _sweep_forever(manager) -> None:
+    while True:
+        try:
+            await deliver_due(manager)
+        except asyncio.CancelledError:
+            raise
+        except Exception as error:
+            logger.warning("turn signal sweep failed: %s: %s", type(error).__name__, error)
+        await asyncio.sleep(SWEEP_INTERVAL_S)
+
+
+def start_sweeper(manager) -> asyncio.Task:
+    global _sweeper
+    if _sweeper is None or _sweeper.done():
+        _sweeper = asyncio.create_task(_sweep_forever(manager))
+    return _sweeper
+
+
+def sweeper_task() -> asyncio.Task | None:
+    return _sweeper if _sweeper is not None and not _sweeper.done() else None
+
diff --git a/tests/test_auto_report_undelivered.py b/tests/test_auto_report_undelivered.py
deleted file mode 100644
index 2630d2df9..000000000
--- a/tests/test_auto_report_undelivered.py
+++ /dev/null
@@ -1,171 +0,0 @@
-"""#47 — недоставленный автоотчёт оставляет след, не зависящий от сломанного канала.
-
-Стенд живой: настоящий репозиторий, настоящий отказ авто-switch у ОРКЕСТРАТОРА (то есть
-принять он не может), воркер уходит в idle и отчитывается.
-"""
-import asyncio
-import logging
-import subprocess
-import uuid
-from datetime import datetime, timezone
-from unittest.mock import patch
-
-import pytest
-
-
-@pytest.fixture
-def env(tmp_path, monkeypatch):
-    monkeypatch.setattr("app.db.DB_PATH", tmp_path / "t.db")
-    wt_root = tmp_path / "worktrees"
-    wt_root.mkdir()
-    monkeypatch.setattr("app.workspace.WORKTREE_ROOT", wt_root)
-    from app.db import init_db, save_session
-
-    init_db()
-    repo = tmp_path / "repo"
-    repo.mkdir()
-    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
-    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, capture_output=True)
-    subprocess.run(["git", "config", "user.name", "T"], cwd=repo, capture_output=True)
-    (repo / "README.md").write_text("# test")
-    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
-    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, capture_output=True, check=True)
-    subprocess.run(["git", "branch", "-M", "main"], cwd=repo, capture_output=True, check=True)
-
-    from app.workspace import create_worktree
-
-    def row(sid, name, worktree, branch, *, orch=False, needs_switch=0, parent=""):
-        return {
-            "id": sid, "name": name, "scope": str(repo), "cwd": str(repo),
-            "model": "claude-sonnet-5-5[1m]", "system_prompt": "", "status": "idle",
-            "session_id": None, "cost_usd": 0.0, "worktree_path": worktree,
-            "branch": branch, "base_branch": "main", "is_orchestrator": orch, "color": "",
-            "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
-            "task_id": "", "needs_switch": needs_switch, "parent_name": parent,
-        }
-
-    boss_wt = create_worktree(str(repo), "boss", "47", base_branch="main")
-    stolen = "adhoc-1785700000-1/boss"
-    subprocess.run(["git", "branch", stolen, "main"], cwd=repo, capture_output=True, check=True)
-    save_session(row("boss-1", "boss", boss_wt.path, boss_wt.branch, orch=True, needs_switch=1))
-
-    worker_wt = create_worktree(str(repo), "worker", "48", base_branch="main")
-    worker_id = str(uuid.uuid4())
-    save_session(row(worker_id, "worker", worker_wt.path, worker_wt.branch, parent="boss"))
-
-    import app.manager as mgr
-
-    monkeypatch.setattr(mgr, "next_adhoc_branch", lambda _n: stolen)
-    return {"repo": str(repo), "worker_id": worker_id, "boss_id": "boss-1"}
-
-
-async def _report(env):
-    from app.main import manager
-
-    manager.sessions.clear()
-    await manager.ensure_loaded_any("boss")
-    await manager.ensure_loaded_any("worker")
-    callback = manager._make_idle_callback(env["repo"])
-    await callback("worker", env["repo"], ["последний вывод воркера"], "", True)
-    return manager
-
-
-def _delivery_rows(session_id):
-    from app.db import get_logs
-
-    return [r for r in get_logs(session_id, limit=50)
-            if "[доставка]" in (r["content"] or "")]
-
-
-@pytest.mark.asyncio
-async def test_both_histories_get_the_record_and_no_exception_escapes(env, caplog):
-    from tests.conftest import make_backend_mock
-
-    with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
-        with caplog.at_level(logging.WARNING):
-            await _report(env)  # исключение наружу не всплывает — иначе тест упадёт здесь
-
-    worker_rows = _delivery_rows(env["worker_id"])
-    boss_rows = _delivery_rows(env["boss_id"])
-    print("\nВ ИСТОРИИ ОРКЕСТРАТОРА:\n   ", boss_rows[0]["content"] if boss_rows else "НЕТ")
-    assert worker_rows and boss_rows, "след обязан быть в обеих историях"
-    assert worker_rows[0]["content"] == boss_rows[0]["content"]
-    assert worker_rows[0]["type"] == "system"
-
-
-@pytest.mark.asyncio
-async def test_record_names_both_sides_reason_and_outcome_of_the_attempt(env):
-    from tests.conftest import make_backend_mock
-
-    with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
-        await _report(env)
-
-    text = _delivery_rows(env["boss_id"])[0]["content"]
-    assert "автоотчёт воркера «worker»" in text and "«boss»" in text
-    # исход попытки уведомить обязан быть виден: тихая попытка — тот же дефект
-    assert "Попытка уведомить отдельным сообщением:" in text
-    assert "уведомить boss не удалось" in text
-    assert "Автоматического повтора нет" in text
-    assert "RuntimeError" in text
-
-
-@pytest.mark.asyncio
-async def test_successful_auto_report_leaves_no_record(env, monkeypatch):
-    from tests.conftest import make_backend_mock
-
-    with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
-        from app.main import manager
-
-        manager.sessions.clear()
-        await manager.ensure_loaded_any("boss")
-        await manager.ensure_loaded_any("worker")
-
-        async def ok(*_a, **_k):
-            return None
-
-        monkeypatch.setattr(manager, "send", ok)
-        callback = manager._make_idle_callback(env["repo"])
-        await callback("worker", env["repo"], ["вывод"], "", True)
-
-    assert not _delivery_rows(env["boss_id"]), "удачная доставка не должна оставлять след"
-
-
-@pytest.mark.asyncio
-async def test_silent_marker_auto_report_leaves_no_record(env):
-    from tests.conftest import make_backend_mock
-
-    with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
-        from app.main import manager
-
-        manager.sessions.clear()
-        await manager.ensure_loaded_any("boss")
-        worker = await manager.ensure_loaded_any("worker")
-        worker.on_idle = manager._make_idle_callback(env["repo"])
-        worker.parent_name = "boss"
-        worker.last_task_sender = "boss"
-        worker._turn_logs = ["[tool] inspect", "[[ORCHESTRA:SILENT_TURN]]"]
-        worker._last_text_output = "[[ORCHESTRA:SILENT_TURN]]"
-        worker._last_turn_ok = True
-        worker._turns.fire_auto_report()
-        if worker._auto_report_task is not None:
-            await worker._auto_report_task
-
-    assert not _delivery_rows(env["boss_id"]), (
-        "семантически тихий ход не должен создавать запись недоставленного автоотчёта"
-    )
-
-
-@pytest.mark.asyncio
-async def test_attempt_does_not_recurse(env, caplog):
-    """Уведомление о недоставке не порождает уведомления о недоставке уведомления."""
-    from tests.conftest import make_backend_mock
-
-    with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
-        with caplog.at_level(logging.WARNING):
-            await _report(env)
-
-    attempts = [r.getMessage() for r in caplog.records
-                if "undelivered автоотчёт" in r.getMessage()]
-    print("\nПОПЫТОК УВЕДОМИТЬ:", len(attempts))
-    assert len(attempts) == 1, f"ожидалась одна попытка, было {len(attempts)}"
-    assert len(_delivery_rows(env["boss_id"])) == 1
diff --git a/tests/test_turn_signals.py b/tests/test_turn_signals.py
new file mode 100644
index 000000000..eff5f9f25
--- /dev/null
+++ b/tests/test_turn_signals.py
@@ -0,0 +1,258 @@
+"""V-680 — the parent is woken exactly once when a worker turn ends without a report.
+
+Real SQLite, real AgentSession turn-end paths, real manager callback; only the parent's
+inbox (`manager.send`) is a recording fake.
+"""
+import asyncio
+import uuid
+from datetime import datetime, timezone
+
+import pytest
+
+from app import turn_signals
+from app.events import MessageProvenance
+from app.session import AgentSession, AgentStatus
+
+SCOPE = "/proj"
+
+
+def _row(sid, name, *, parent_id="", parent_name="", orch=False, status="idle"):
+    return {
+        "id": sid, "name": name, "scope": SCOPE, "cwd": SCOPE, "model": "claude-sonnet-5-5",
+        "system_prompt": "", "status": status, "session_id": None, "cost_usd": 0.0,
+        "worktree_path": "", "branch": "", "base_branch": "main", "is_orchestrator": orch,
+        "color": "", "created_at": datetime.now(timezone.utc).isoformat(),
+        "finished_at": None, "task_id": "", "needs_switch": 0,
+        "parent_id": parent_id, "parent_name": parent_name,
+        "role": "orchestrator" if orch else "worker",
+    }
+
+
+class FakeManager:
+    """Parent inbox + the three lookups `turn_signals` uses."""
+
+    def __init__(self):
+        self.sessions = {}
+        self.sent = []
+        self.fail_with = None
+
+    async def send(self, session_id, message, *, provenance):
+        if self.fail_with is not None:
+            raise self.fail_with
+        self.sent.append((session_id, message, provenance))
+
+    async def ensure_loaded_by_id(self, session_id):
+        from app import db
+        row = db.get_session(session_id)
+        return type("S", (), {"id": row["id"], "name": row["name"]})() if row else None
+
+    async def ensure_loaded(self, name, scope):
+        from app import db
+        row = db.get_session_by_name(name, scope)
+        return type("S", (), {"id": row["id"], "name": row["name"]})() if row else None
+
+    def _context_warning(self, _name):
+        return ""
+
+    def _find_orchestrator_name(self, _scope):
+        return None
+
+
+@pytest.fixture
+def world(tmp_path, monkeypatch):
+    monkeypatch.setattr("app.db.DB_PATH", tmp_path / "t.db")
+    from app import db
+    db.init_db()
+    turn_signals._inflight.clear()
+    parent_id = str(uuid.uuid4())
+    db.save_session(_row(parent_id, "boss", orch=True))
+    w = {"parent_id": parent_id, "manager": FakeManager(), "workers": {}}
+
+    def add_worker(name):
+        sid = str(uuid.uuid4())
+        db.save_session(_row(sid, name, parent_id=parent_id, parent_name="boss"))
+        w["workers"][name] = sid
+        return sid
+
+    w["add_worker"] = add_worker
+    w["worker_id"] = add_worker("w1")
+    return w
+
+
+def _session(world, name="w1"):
+    """A real AgentSession whose end-of-turn callback is the real manager callback."""
+    from app.manager import SessionManager
+
+    s = AgentSession(id=world["workers"][name], name=name, scope=SCOPE, cwd=SCOPE)
+    s.parent_name = "boss"
+    s.parent_id = world["parent_id"]
+    s.status = AgentStatus.RUNNING
+    s._last_turn_ok = True
+    s._turn_logs = ["some work"]
+    s._persist = lambda *a, **k: None
+    s._log = lambda *a, **k: None
+    s._hibernate.schedule = lambda *a, **k: None
+    s._turn_gen = 7
+    s.on_idle = SessionManager._make_idle_callback(world["manager"], SCOPE)
+    world["manager"].sessions[s.id] = s
+    return s
+
+
+async def _settle(session):
+    if session._auto_report_task is not None:
+        await session._auto_report_task
+
+
+@pytest.mark.asyncio
+async def test_unreported_clean_end_wakes_parent_once_even_if_noticed_twice(world):
+    s = _session(world)
+    s._turns.fire_auto_report()
+    await _settle(s)
+    s._turns.fire_auto_report()  # a second code path noticing the same turn
+    await _settle(s)
+
+    sent = world["manager"].sent
+    assert [m[0] for m in sent] == [world["parent_id"]]
+    assert "[from:w1]" in sent[0][1]
+
+
+@pytest.mark.asyncio
+async def test_explicit_done_gives_no_extra_wake(world):
+    s = _session(world)
+    s._did_report = True
+    s._turns.fire_auto_report()
+    await _settle(s)
+
+    assert world["manager"].sent == []
+
+
+@pytest.mark.asyncio
+@pytest.mark.parametrize("ending", ["listener_died", "continuation_failed", "failed_turn_end"])
+async def test_every_abnormal_ending_wakes_parent_exactly_once(world, ending):
+    s = _session(world)
+    if ending == "listener_died":
+        s._finish_failed_running_turn("listen task exception: boom")
+    elif ending == "continuation_failed":
+        s._turn_start_cancel_gen = 0
+        assert s._finish_failed_continuation((s._turn_gen, s._turn_start_cancel_gen))
+    else:
+        s._last_turn_ok = False
+        s._turns.fire_auto_report()
+    await _settle(s)
+
+    sent = world["manager"].sent
+    assert len(sent) == 1 and sent[0][0] == world["parent_id"]
+    assert "Turn failed before an explicit report" in sent[0][1]
+
+
+@pytest.mark.asyncio
+async def test_new_turn_starting_does_not_swallow_previous_turns_signal(world):
+    s = _session(world)
+    s._turns.fire_auto_report()
+    s._turns.bump_turn_gen()  # next turn begins before the report task got to run
+    await asyncio.sleep(0.05)
+
+    assert len(world["manager"].sent) == 1
+
+
+@pytest.mark.asyncio
+async def test_failed_delivery_is_retried_until_accepted_then_never_repeated(world):
+    s = _session(world)
+    world["manager"].fail_with = RuntimeError("parent draining")
+    s._turns.fire_auto_report()
+    await _settle(s)
+    assert world["manager"].sent == []
+
+    from app import db
+    with db._conn() as c:
+        row = c.execute("SELECT state, attempts, next_attempt_at FROM turn_signals").fetchone()
+        assert (row["state"], row["attempts"]) == ("pending", 1)
+        assert row["next_attempt_at"] > 0
+        c.execute("UPDATE turn_signals SET next_attempt_at=0")
+
+    world["manager"].fail_with = None
+    assert await turn_signals.deliver_due(world["manager"]) == 1
+    assert await turn_signals.deliver_due(world["manager"]) == 0
+    assert len(world["manager"].sent) == 1
+
+
+@pytest.mark.asyncio
+async def test_pending_signal_survives_restart_and_is_delivered_once(world):
+    s = _session(world)
+    world["manager"].fail_with = RuntimeError("Orchestra restarting")
+    s._turns.fire_auto_report()
+    await _settle(s)
+
+    # "restart": a fresh process has an empty in-memory state and a new manager
+    turn_signals._inflight.clear()
+    from app import db
+    with db._conn() as c:
+        c.execute("UPDATE turn_signals SET next_attempt_at=0")
+    after = FakeManager()
+    assert await turn_signals.deliver_due(after) == 1
+    assert await turn_signals.deliver_due(after) == 0
+    assert len(after.sent) == 1
+
+
+@pytest.mark.asyncio
+async def test_crash_after_parent_accepted_does_not_resend(world):
+    from app import db
+
+    sid = world["worker_id"]
+    signal_id = turn_signals.record(
+        key="k1", worker_session_id=sid, worker_name="w1", scope=SCOPE,
+        turn_ok=True, stop_reason="", summary="x",
+    )
+    # the parent's log already holds the message: process died before the row was marked
+    db.add_log(
+        world["parent_id"], datetime.now(timezone.utc), "user_message", "[from:w1] ...",
+        provenance=MessageProvenance(
+            origin="agent", senders=("w1",), subtype="auto_report",
+            ref=turn_signals._ref([signal_id]),
+        ),
+    )
+    assert await turn_signals.deliver_due(world["manager"]) == 0
+    assert world["manager"].sent == []
+    with db._conn() as c:
+        assert c.execute("SELECT state FROM turn_signals").fetchone()["state"] == "delivered"
+
+
+@pytest.mark.asyncio
+async def test_restart_interrupted_turns_wake_each_parent_once_with_one_message(world):
+    from app import db
+
+    w2 = world["add_worker"]("w2")
+    w3 = world["add_worker"]("w3-reported")
+    # w3 had already told the parent during its interrupted turn
+    t0 = datetime.now(timezone.utc)
+    db.add_log(w3, t0, "user_message", "task", provenance=MessageProvenance(
+        origin="agent", senders=("boss",), subtype="direct_message"))
+    db.add_log(world["parent_id"], datetime.now(timezone.utc), "user_message", "DONE",
+               provenance=MessageProvenance(
+                   origin="agent", senders=("w3-reported",), subtype="direct_message"))
+    rows = [db.get_session(i) for i in (world["worker_id"], w2, w3)]
+    rows.append(db.get_session(world["parent_id"]))  # orchestrator: never signalled
+
+    assert turn_signals.record_interrupted_by_restart(rows) == 2
+    assert turn_signals.record_interrupted_by_restart(rows) == 0  # same boot, same turns
+
+    assert await turn_signals.deliver_due(world["manager"]) == 2
+    sent = world["manager"].sent
+    assert len(sent) == 1, "two interrupted workers of one parent must be one wake-up"
+    assert "[from:w1]" in sent[0][1] and "[from:w2]" in sent[0][1]
+    assert "w3-reported" not in sent[0][1]
+
+
+@pytest.mark.asyncio


## Later history of the touched files on main (after this commit)

143 later commits touch these paths; the first 40 (oldest first):
102fd30f2 2026-10-02 V-682: удалить тип bg-задания idle; старые idle-строки гасятся при старте
b09a8450e 2026-10-02 V-681: #V-681: MP4 в Telegram уходит видео с превью и откатом в документ
01eeb113a 2026-10-03 V-683: компакт по простою у katya-work-orchestrator только с 80% контекста
6883d3787 2026-10-03 V-684: #V-684: ролики ×1.5 по умолчанию, Manim вторым движком explainer-video, ролик «Оркестра не спит»
67b60528f 2026-10-03 V-685: #V-685: LaTeX (TinyTeX) для Manim с кириллицей, ролик «Почему агент сжимается на 55-й минуте»
6fc6a68ed 2026-10-03 V-684: CHANGELOG — темп по умолчанию 1.25, а не 1.5
dc881f5e5 2026-10-04 V-686: real-dashboard media for README (stand, GIF, narrated EN video) + English voice in explainer-video
8e150a46e 2026-10-04 V-689: rebuild README dashboard GIF
8155e9d1f 2026-10-04 V-688: add dashboard video playback and GIF previews
c6cc8a5dd 2026-10-04 V-692: keep live limits message updated
2db735dda 2026-10-04 V-695: spawn_worker resumes a cut-off spawn and delivers the initial task exactly once
bcd844068 2026-10-04 V-693: #V-693: record CI triage and confirmed CSS defect
1722bb82f 2026-10-04 V-696: #V-696: add RUAccent stress marking before Vosk TTS
7030f6ced 2026-10-05 V-697: WIP #V-697: translate core prompt layers
3e82520ec 2026-10-05 дашборд: кнопка «открыть в новой вкладке» для PDF и прочих файлов, PDF во фрейме просмотрщика
8dd91d5e1 2026-10-05 V-700: #V-700: fix dashboard CI and i18n issues
43455e2b7 2026-10-05 V-707: #V-707: preserve exact provider rate limits
7e49195e6 2026-10-05 V-705: #V-705: bind orchestrator tasks and supersede stale runs
f163b3fa5 2026-10-05 V-704: #V-704: fix layout migration and run cwd defects
98238cb42 2026-10-05 V-718: #V-718: remove project memory search
6057d1e11 2026-10-05 V-706: #V-706: fix session API and delivery lifecycle
5365e1ab4 2026-10-05 V-701: #V-701: fix Telegram media routing
ea58b7dbe 2026-10-05 V-702: #V-702: fix merge gate outcomes and recovery routes
038f06b7b 2026-10-05 V-720: #V-720: add one-call dynamic workflows
2ee5279f0 2026-10-05 V-722: #V-701: stop replying in unmapped Telegram topics
4bc0a84b5 2026-10-05 V-703: #V-703: fix Codex runtime recovery and quota errors
3582eea67 2026-10-05 V-699: WIP #V-699: measure worktree bottleneck and clarify retries
607d566ee 2026-10-05 V-726: #V-726: document blocked Codex CLI upgrade
4fb1311f3 2026-10-05 V-719: #V-719: enable offline RUAccent on laptop
6ba1141c9 2026-10-06 V-736: #V-736: restore CI on main
b1be3a1e5 2026-10-06 V-737: #V-737: honor force task switch contract
382660ab4 2026-10-06 V-738: #V-738: add staged dynamic workflow execution
25eb55af9 2026-10-06 V-739: #V-739: curate model catalog and preserve session compatibility
1bfcb256b 2026-10-06 V-740: #V-740: suppress owner turn auto-reports
a3d786653 2026-10-07 V-741: #V-741: notify senders when message delivery fails
75788329b 2026-10-07 V-743: #V-743: preserve historical quota line rules
cd2e62e72 2026-10-07 V-744: #V-744: shape Claude quota line by local day and night
af47aff79 2026-10-07 V-745: #V-745: isolate quota history writes from probes
5a5f21b6a 2026-10-07 V-748: #V-748: notify senders about failed file deliveries
5819f6d96 2026-10-07 V-747: #V-747: format usage and quota percentages

## Patches of the first 8 later commits, restricted to the touched paths (each capped at 150 lines)

### 102fd30f2 V-682: удалить тип bg-задания idle; старые idle-строки гасятся при старте

diff --git a/CHANGELOG.md b/CHANGELOG.md
index b2a700d60..91ef018c2 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -17,10 +17,12 @@
 
 ### Changed
 - `bump_turn_gen` больше не отменяет отложенный авто-отчёт прошлого хода: теперь это записанный факт, и начало следующего хода (до того, как задача успела записать строку) не должно его стирать.
 
 ### Removed
+- **Тип bg-задания `idle` удалён целиком** (`app/idle_watch.py`, `_run_idle` и ветки `idle` в `app/bg_jobs.py`, описание и проверка роли в `bg_create` в `app/mcp_stdio.py`, «Сторож простоя» в `jobs-timeline.js`, тесты). Его единственный сценарий — не потерять конец хода воркера — закрыт платформенным сигналом `turn_signals` (V-680); 154 постановки, по умолчанию бессрочные. `bg_create(type="idle")` теперь отвечает ошибкой «тип удалён, конец хода воркера родителю сообщает платформа». Старые строки `bg_jobs` с `type='idle'` при старте (`restore_from_db` → `bg_cancel_removed_idle`) переводятся в `cancelled` с причиной, историю не трогаем. `has_active_jobs` больше не исключает idle, потому что idle не существует. Тесты в `tests/test_bg_jobs.py`.
+
 - `_record_undelivered_auto_report` и `_auto_report_key` (политика «ретраев нет», #30/#47/#50) вместе с тестами `test_auto_report_undelivered.py`: заменены повтором из `turn_signals`.
 
 ### Known tradeoff
 - Для хода, оборванного рестартом, «воркер уже писал родителю» определяется по журналу родителя с момента последнего входящего воркера; сообщение, пришедшее воркеру посреди хода после его DONE, даст лишнее пробуждение, а не потерю.
 
### b09a8450e V-681: #V-681: MP4 в Telegram уходит видео с превью и откатом в документ

diff --git a/CHANGELOG.md b/CHANGELOG.md
index 91ef018c2..b1decd3e1 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -5,10 +5,15 @@
 > content: the VPS block comes first below, followed by the laptop block. Task #52 fixes the format.
 
 ## Unreleased
 
 ### Added
+- **Скилл `explainer-video`: объясняющий ролик с русской озвучкой** (`prompts/skills/explainer-video.md`, `scripts/explainer_video/make.py`, `tts_worker.py`, `video.css`, шрифты Manrope и JetBrains Mono (OFL) в `fonts/`; V-681). Запрос владельца 02.10: видео-объяснения «как 3Blue1Brown». Сцена — тот же каркас `html-motion`, у шага добавлена фраза `say`. Время задаёт озвучка: инструмент сначала синтезирует фразы локальным Vosk TTS (`vosk-model-tts-ru-0.9-multi`, Apache 2.0), потом ставит длительность шага = 0.35 с + фраза + 0.55 с и передаёт её сцене через `window.voice?.(STEPS)`. Поэтому начало фразы совпадает со сменой кадра по построению, а не подгонкой. Дальше покадровая запись `P.seek(k/30)` в 1920×1080 на тёмной теме кусками в параллельных Chromium (69 с ролика: 25 мин в один поток → 9.5 мин сборки целиком), дорожка голоса раскладывается по началам фраз, `loudnorm` −16 LUFS. Проверка: контакт-лист кадров конца шагов и распознавание итогового MP4 Deepgram nova-2 с дословностью каждой фразы плюс фактическое начало её звука по `silencedetect` (`*.check.json`; в примере сдвиг ≤ 0.03 с). Vosk падает с `KeyError` на латинице и цифрах, поэтому инструмент отказывает заранее и требует писать их словами; экранные субтитры берутся из `sub`. Пример — `.orchestra/tasks/V-681/video/cache-ttl.mp4` по замеру V-676. Окружение TTS (`~/.local/share/orchestra-tts/`) вне репозитория: прежняя копия в `~/.cache/v75-tts` оказалась пустой — каталоги без файлов.
+
+### Changed
+- **MP4 в Telegram приходит видео, а не документом** (`app/tg_video.py`; `send_as_video` в `app/upload_limits.py`; `_tg_send_file_safe`, `_submit_file_snapshot_once`, `_submit_file_group_once`, `_MirrorItem` в `app/tg_bridge.py`; вид `video` в `_batch_kind` у `app/tg_file_deliveries.py`; V-681). Владелец хотел, чтобы ролики играли в ленте, как фото. `.mp4/.m4v` (только MPEG4 Telegram проигрывает в клиентах) уходят `sendVideo` с `supports_streaming`, длительностью, размерами и JPEG-превью 320 px из середины ролика (`ffprobe`/`ffmpeg`; без них — видео без метаданных). Отказ Telegram (400/403: сообщения нет, исход известен) откатывается в `sendDocument`, альбом — в альбом документов. Таймаут и сетевая ошибка не откатываются: исход неизвестен, повтор задвоил бы файл. Зеркала идут тем же путём, `as_document` по-прежнему форсирует документ. Нужен рестарт Python.
+- Known tradeoff: отпечаток идемпотентности альбома включает вид файла, поэтому повтор `send_files` с тем же `event_id`, начатый до рестарта и повторённый после, для пакета с MP4 получит конфликт отпечатка (`document` → `video`).
 - **Доставка, отбитая гейтом квот, ждёт его снятия внутри платформы — таймер «повтори через N часов» больше не нужен** (`app/quota_queue.py`, состояние `WAITING_QUOTA` в `message_deliveries`/`initial_deliveries`). Раньше `send_message` и `spawn_worker` получали 429 `weekly_quota_blocked`, и оркестратор ставил себе bg-таймер: ~4 таких таймера в сутки с 23.09, каждое пробуждение — платный ход, часто впустую. Теперь отбитое сообщение принимается durable-доставкой (приёмка в `routes/sessions.py: _preflight_or_quota_wait`, отказ runner'а в `run_message_delivery` переводит в ожидание вместо `FAILED_BEFORE_SUBMIT`), отправитель сразу получает «принято в очередь» с оценкой времени (`next_action.eta_at`), а `quota_queue.release_waiting` возвращает строки в обычную очередь, когда гейт пропускает: циклом раз в минуту (`quota_release_loop`, стартует в lifespan) и немедленно при `POST /api/usage/quota-override` (в ответе `released_deliveries`). Порядок к одному адресату сохраняется (`accept_seq`, ждущая голова держит очередь), повтор с тем же `delivery_id` дубля не даёт, рестарт ничего не теряет (строки в SQLite, `recover_*` их не трогают). Первое задание нового воркера не обгоняется прямыми сообщениями ему. Сменил задачу/убит адресат к моменту выпуска — доставка падает громко (`TARGET_TASK_CHANGED`/`FAILED_BEFORE_SUBMIT`), отправителю уходит платформенное сообщение. Отмена: тул `cancel_message_delivery` и `POST /api/message-deliveries/{id}/cancel` (только ещё не ушедшее: `WAITING_QUOTA`/`QUEUED`), список ждущих: `GET /api/message-deliveries`. Промпт `modules/background-jobs.md` запрещает ставить таймеры повтора доставки. Тесты `tests/test_quota_wait_queue.py`.
 
 ### Changed
 - **`spawn_worker` при закрытом гейте квот больше не отказывает** (`SessionManager.create_session`): воркер создаётся, а его первое задание ждёт в `WAITING_QUOTA` и уходит само. Прежний отказ до создания (#227) нужен был, чтобы не плодить «мёртвые» сессии, но теперь первый `/send` не отбивается, и мёртвой сессия не бывает. Известный компромисс: пока гейт закрыт, простаивающий воркер с привязанной задачей и worktree существует; неотправленное задание видно в `delivery_status`.
 - Не затронут путь без `delivery_id` (HTTP `/send` от UI/TG): там по-прежнему работают сообщения в памяти сессии и уведомление `quota_blocked`; перенос их в durable-очередь — отдельная работа.
### 01eeb113a V-683: компакт по простою у katya-work-orchestrator только с 80% контекста

diff --git a/app/session.py b/app/session.py
index f3818750b..c17011fdb 100644
--- a/app/session.py
+++ b/app/session.py
@@ -549,10 +549,13 @@ class AgentSession:
     # Sessions come back from compact at 7-12% (prompt + handoff). Week to 25.09
     # (Claude, 1M window): 34 of 67 compacts started below 30% and cut only 35-38%,
     # while re-writing 90-150k tokens of cache; above 30% they cut 78-86%.
     # Codex uses the same floor by the owner's decision (25.09).
     PRECOMPACT_MIN_CONTEXT_PCT = 30
+    # Owner 03.10 (V-683): katya-work lost agreements to 2-5 idle compacts a day; there
+    # idle compaction waits for a nearly full context and the cold cache is accepted.
+    PRECOMPACT_MIN_CONTEXT_PCT_BY_SESSION = {"katya-work-orchestrator": 80}
     CLAUDE_CACHE_WINDOW_SECONDS = 60 * 60
     # ChatGPT-auth Codex publishes no contractual cache TTL. Keep a five-minute
     # safety margin before the observed/documented ~30-minute reference window.
     CODEX_CACHE_WINDOW_SECONDS = 30 * 60
     AUTO_COMPACT_WINDOW_START = _AUTO_COMPACT_WINDOW_START_DEFAULT
@@ -573,26 +576,28 @@ class AgentSession:
 
     def _precompact_payload(self, payload: dict) -> str:
         return json.dumps(payload, ensure_ascii=False)
 
     def _precompact_policy(self) -> dict | None:
+        min_pct = self.PRECOMPACT_MIN_CONTEXT_PCT_BY_SESSION.get(
+            self.name, self.PRECOMPACT_MIN_CONTEXT_PCT)
         if self.backend_type == "claude":
             return {
                 "delay_seconds": self.PRECOMPACT_DELAY_SECONDS,
                 "cache_window_seconds": self.CLAUDE_CACHE_WINDOW_SECONDS,
                 "context_threshold": self.PRECOMPACT_CONTEXT_THRESHOLD,
-                "arm_threshold": self.PRECOMPACT_MIN_CONTEXT_PCT,
-                "min_context_pct": self.PRECOMPACT_MIN_CONTEXT_PCT,
+                "arm_threshold": min_pct,
+                "min_context_pct": min_pct,
                 "compact_mode": "handoff",
             }
         if self.backend_type == "codex":
             return {
                 "delay_seconds": self.CODEX_PRECOMPACT_DELAY_SECONDS,
                 "cache_window_seconds": self.CODEX_CACHE_WINDOW_SECONDS,
                 "context_threshold": self.CODEX_PRECOMPACT_CONTEXT_THRESHOLD,
-                "arm_threshold": self.PRECOMPACT_MIN_CONTEXT_PCT,
-                "min_context_pct": self.PRECOMPACT_MIN_CONTEXT_PCT,
+                "arm_threshold": min_pct,
+                "min_context_pct": min_pct,
                 "compact_mode": "native",
             }
         return None
 
     def _auto_compact_window_state(
### 6883d3787 V-684: #V-684: ролики ×1.5 по умолчанию, Manim вторым движком explainer-video, ролик «Оркестра не спит»

diff --git a/CHANGELOG.md b/CHANGELOG.md
index b1decd3e1..7a83420d6 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -5,10 +5,17 @@
 > content: the VPS block comes first below, followed by the laptop block. Task #52 fixes the format.
 
 ## Unreleased
 
 ### Added
+- **Manim — второй движок сцен в `explainer-video`** (`scripts/explainer_video/manim_voice.py`, ветка `.py` в `make.py`: `manim_steps`, `render_manim`; V-684). Владелец 03.10 попросил графики «как у 3Blue1Brown». ManimCE 0.20.1 (MIT) стоит вне репозитория в `~/.local/share/orchestra-manim/` через micromamba и conda-forge — Cairo, Pango и ffmpeg приходят пакетами, apt и root не нужны (`ORCHESTRA_MANIM_HOME` меняет путь). Сцена — класс-наследник `VoiceScene` с тем же `STEPS`, что у html-motion; блок `with self.step(i)` растягивает шаг до длины фразы, а `self.left()` даёт анимациям долю оставшегося времени, перебор шага останавливает сборку. Длительности приходят от `make.py` через `EXPLAINER_VOICE`, Manim сам пишет 1920×1080, контакт-лист снимается из готового MP4. LaTeX не ставили, поэтому `MathTex` недоступен — формулы пишутся Unicode-текстом. Пример: `.orchestra/tasks/V-684/video/night-shift.mp4` — сутки Оркестры циферблатом по `logs` за месяц.
+
+### Changed
+- **Ролики по умолчанию в 1.5 раза быстрее** (`--rate 1.5` в `make.py`, паузы `LEAD`/`GAP` делятся на темп в `plan`; V-684). Владелец: «в полтора раза быстрее». Замер на фразах cache-ttl: Vosk `speech_rate` 1.5 сокращает речь в 1.48 раза при той же распознаваемости Deepgram (минимум по фразам 0.87 против 0.86 у 1.0), а `atempo=1.5` поверх обычной речи хуже (0.83). Без ускорения пауз ролик сократился бы только в 1.4 раза; `hold` последнего шага не трогается — это время досмотреть итог. cache-ttl: 68.8 → 47.4 с.
+
+### Fixed
+- Кадры контакт-листа пишутся в `frames/<имя>/`: две сцены, собранные в одну папку, раньше перезаписывали `frames/stepNN.png` друг друга, и контакт-лист второй мог захватить лишний кадр первой.
 - **Скилл `explainer-video`: объясняющий ролик с русской озвучкой** (`prompts/skills/explainer-video.md`, `scripts/explainer_video/make.py`, `tts_worker.py`, `video.css`, шрифты Manrope и JetBrains Mono (OFL) в `fonts/`; V-681). Запрос владельца 02.10: видео-объяснения «как 3Blue1Brown». Сцена — тот же каркас `html-motion`, у шага добавлена фраза `say`. Время задаёт озвучка: инструмент сначала синтезирует фразы локальным Vosk TTS (`vosk-model-tts-ru-0.9-multi`, Apache 2.0), потом ставит длительность шага = 0.35 с + фраза + 0.55 с и передаёт её сцене через `window.voice?.(STEPS)`. Поэтому начало фразы совпадает со сменой кадра по построению, а не подгонкой. Дальше покадровая запись `P.seek(k/30)` в 1920×1080 на тёмной теме кусками в параллельных Chromium (69 с ролика: 25 мин в один поток → 9.5 мин сборки целиком), дорожка голоса раскладывается по началам фраз, `loudnorm` −16 LUFS. Проверка: контакт-лист кадров конца шагов и распознавание итогового MP4 Deepgram nova-2 с дословностью каждой фразы плюс фактическое начало её звука по `silencedetect` (`*.check.json`; в примере сдвиг ≤ 0.03 с). Vosk падает с `KeyError` на латинице и цифрах, поэтому инструмент отказывает заранее и требует писать их словами; экранные субтитры берутся из `sub`. Пример — `.orchestra/tasks/V-681/video/cache-ttl.mp4` по замеру V-676. Окружение TTS (`~/.local/share/orchestra-tts/`) вне репозитория: прежняя копия в `~/.cache/v75-tts` оказалась пустой — каталоги без файлов.
 
 ### Changed
 - **MP4 в Telegram приходит видео, а не документом** (`app/tg_video.py`; `send_as_video` в `app/upload_limits.py`; `_tg_send_file_safe`, `_submit_file_snapshot_once`, `_submit_file_group_once`, `_MirrorItem` в `app/tg_bridge.py`; вид `video` в `_batch_kind` у `app/tg_file_deliveries.py`; V-681). Владелец хотел, чтобы ролики играли в ленте, как фото. `.mp4/.m4v` (только MPEG4 Telegram проигрывает в клиентах) уходят `sendVideo` с `supports_streaming`, длительностью, размерами и JPEG-превью 320 px из середины ролика (`ffprobe`/`ffmpeg`; без них — видео без метаданных). Отказ Telegram (400/403: сообщения нет, исход известен) откатывается в `sendDocument`, альбом — в альбом документов. Таймаут и сетевая ошибка не откатываются: исход неизвестен, повтор задвоил бы файл. Зеркала идут тем же путём, `as_document` по-прежнему форсирует документ. Нужен рестарт Python.
 - Known tradeoff: отпечаток идемпотентности альбома включает вид файла, поэтому повтор `send_files` с тем же `event_id`, начатый до рестарта и повторённый после, для пакета с MP4 получит конфликт отпечатка (`document` → `video`).
### 67b60528f V-685: #V-685: LaTeX (TinyTeX) для Manim с кириллицей, ролик «Почему агент сжимается на 55-й минуте»

diff --git a/CHANGELOG.md b/CHANGELOG.md
index 7a83420d6..132ffa919 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -5,10 +5,11 @@
 > content: the VPS block comes first below, followed by the laptop block. Task #52 fixes the format.
 
 ## Unreleased
 
 ### Added
+- **Формулы LaTeX в Manim-роликах** (`scripts/explainer_video/manim_voice.py`, скилл `explainer-video`; V-685). Владелец 03.10: «давай латекс тоже ставь, чтобы формулы тоже было всё чётко». TinyTeX (TeX Live 2026, 220 МБ) поставлен без apt и root в `~/.local/share/orchestra-manim/tex/` с пакетами, которые нужны шаблонам Manim, плюс `babel-russian`/`cyrillic`/`lh`. `manim_voice` при импорте добавляет его `bin` в PATH (папки нет → системный `latex`) и ставит `config.tex_template` с T2A и `babel[english,russian]`: шаблон Manim по умолчанию грузит только `babel[english]`, и `\text{кеш}` в `MathTex` падал с `Unicode character ц not set up`. Поправка к V-684: системный TeX Live 2023 на VPS стоял с 07.08 (apt), просто шаблон не умел кириллицу. В скилле — пример с подстановкой чисел (`TransformMatchingTex`), разбор ошибки `latex error converting to dvi` и команды установки. Ролик-пример: `.orchestra/tasks/V-685/video/compact55.mp4` — почему компакт по простою ждёт 55 минут, по формуле подписки V-660 и 70 компактам из `logs`.
 - **Manim — второй движок сцен в `explainer-video`** (`scripts/explainer_video/manim_voice.py`, ветка `.py` в `make.py`: `manim_steps`, `render_manim`; V-684). Владелец 03.10 попросил графики «как у 3Blue1Brown». ManimCE 0.20.1 (MIT) стоит вне репозитория в `~/.local/share/orchestra-manim/` через micromamba и conda-forge — Cairo, Pango и ffmpeg приходят пакетами, apt и root не нужны (`ORCHESTRA_MANIM_HOME` меняет путь). Сцена — класс-наследник `VoiceScene` с тем же `STEPS`, что у html-motion; блок `with self.step(i)` растягивает шаг до длины фразы, а `self.left()` даёт анимациям долю оставшегося времени, перебор шага останавливает сборку. Длительности приходят от `make.py` через `EXPLAINER_VOICE`, Manim сам пишет 1920×1080, контакт-лист снимается из готового MP4. LaTeX не ставили, поэтому `MathTex` недоступен — формулы пишутся Unicode-текстом. Пример: `.orchestra/tasks/V-684/video/night-shift.mp4` — сутки Оркестры циферблатом по `logs` за месяц.
 
 ### Changed
 - **Ролики по умолчанию в 1.5 раза быстрее** (`--rate 1.5` в `make.py`, паузы `LEAD`/`GAP` делятся на темп в `plan`; V-684). Владелец: «в полтора раза быстрее». Замер на фразах cache-ttl: Vosk `speech_rate` 1.5 сокращает речь в 1.48 раза при той же распознаваемости Deepgram (минимум по фразам 0.87 против 0.86 у 1.0), а `atempo=1.5` поверх обычной речи хуже (0.83). Без ускорения пауз ролик сократился бы только в 1.4 раза; `hold` последнего шага не трогается — это время досмотреть итог. cache-ttl: 68.8 → 47.4 с.
 
### 6fc6a68ed V-684: CHANGELOG — темп по умолчанию 1.25, а не 1.5

diff --git a/CHANGELOG.md b/CHANGELOG.md
index 132ffa919..4cf3f24ff 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -9,11 +9,11 @@
 ### Added
 - **Формулы LaTeX в Manim-роликах** (`scripts/explainer_video/manim_voice.py`, скилл `explainer-video`; V-685). Владелец 03.10: «давай латекс тоже ставь, чтобы формулы тоже было всё чётко». TinyTeX (TeX Live 2026, 220 МБ) поставлен без apt и root в `~/.local/share/orchestra-manim/tex/` с пакетами, которые нужны шаблонам Manim, плюс `babel-russian`/`cyrillic`/`lh`. `manim_voice` при импорте добавляет его `bin` в PATH (папки нет → системный `latex`) и ставит `config.tex_template` с T2A и `babel[english,russian]`: шаблон Manim по умолчанию грузит только `babel[english]`, и `\text{кеш}` в `MathTex` падал с `Unicode character ц not set up`. Поправка к V-684: системный TeX Live 2023 на VPS стоял с 07.08 (apt), просто шаблон не умел кириллицу. В скилле — пример с подстановкой чисел (`TransformMatchingTex`), разбор ошибки `latex error converting to dvi` и команды установки. Ролик-пример: `.orchestra/tasks/V-685/video/compact55.mp4` — почему компакт по простою ждёт 55 минут, по формуле подписки V-660 и 70 компактам из `logs`.
 - **Manim — второй движок сцен в `explainer-video`** (`scripts/explainer_video/manim_voice.py`, ветка `.py` в `make.py`: `manim_steps`, `render_manim`; V-684). Владелец 03.10 попросил графики «как у 3Blue1Brown». ManimCE 0.20.1 (MIT) стоит вне репозитория в `~/.local/share/orchestra-manim/` через micromamba и conda-forge — Cairo, Pango и ffmpeg приходят пакетами, apt и root не нужны (`ORCHESTRA_MANIM_HOME` меняет путь). Сцена — класс-наследник `VoiceScene` с тем же `STEPS`, что у html-motion; блок `with self.step(i)` растягивает шаг до длины фразы, а `self.left()` даёт анимациям долю оставшегося времени, перебор шага останавливает сборку. Длительности приходят от `make.py` через `EXPLAINER_VOICE`, Manim сам пишет 1920×1080, контакт-лист снимается из готового MP4. LaTeX не ставили, поэтому `MathTex` недоступен — формулы пишутся Unicode-текстом. Пример: `.orchestra/tasks/V-684/video/night-shift.mp4` — сутки Оркестры циферблатом по `logs` за месяц.
 
 ### Changed
-- **Ролики по умолчанию в 1.5 раза быстрее** (`--rate 1.5` в `make.py`, паузы `LEAD`/`GAP` делятся на темп в `plan`; V-684). Владелец: «в полтора раза быстрее». Замер на фразах cache-ttl: Vosk `speech_rate` 1.5 сокращает речь в 1.48 раза при той же распознаваемости Deepgram (минимум по фразам 0.87 против 0.86 у 1.0), а `atempo=1.5` поверх обычной речи хуже (0.83). Без ускорения пауз ролик сократился бы только в 1.4 раза; `hold` последнего шага не трогается — это время досмотреть итог. cache-ttl: 68.8 → 47.4 с.
+- **Ролики по умолчанию в 1.5 раза быстрее** (`--rate 1.5` в `make.py`, паузы `LEAD`/`GAP` делятся на темп в `plan`; V-684). Владелец: «в полтора раза быстрее». Замер на фразах cache-ttl: Vosk `speech_rate` 1.5 сокращает речь в 1.48 раза при той же распознаваемости Deepgram (минимум по фразам 0.87 против 0.86 у 1.0), а `atempo=1.5` поверх обычной речи хуже (0.83). Без ускорения пауз ролик сократился бы только в 1.4 раза; `hold` последнего шага не трогается — это время досмотреть итог. cache-ttl: 68.8 → 47.4 с. Поправка: владелец, послушав, решил «полтора слишком много, давай 1.25» — умолчание `--rate` стало 1.25 (тот же день).
 
 ### Fixed
 - Кадры контакт-листа пишутся в `frames/<имя>/`: две сцены, собранные в одну папку, раньше перезаписывали `frames/stepNN.png` друг друга, и контакт-лист второй мог захватить лишний кадр первой.
 - **Скилл `explainer-video`: объясняющий ролик с русской озвучкой** (`prompts/skills/explainer-video.md`, `scripts/explainer_video/make.py`, `tts_worker.py`, `video.css`, шрифты Manrope и JetBrains Mono (OFL) в `fonts/`; V-681). Запрос владельца 02.10: видео-объяснения «как 3Blue1Brown». Сцена — тот же каркас `html-motion`, у шага добавлена фраза `say`. Время задаёт озвучка: инструмент сначала синтезирует фразы локальным Vosk TTS (`vosk-model-tts-ru-0.9-multi`, Apache 2.0), потом ставит длительность шага = 0.35 с + фраза + 0.55 с и передаёт её сцене через `window.voice?.(STEPS)`. Поэтому начало фразы совпадает со сменой кадра по построению, а не подгонкой. Дальше покадровая запись `P.seek(k/30)` в 1920×1080 на тёмной теме кусками в параллельных Chromium (69 с ролика: 25 мин в один поток → 9.5 мин сборки целиком), дорожка голоса раскладывается по началам фраз, `loudnorm` −16 LUFS. Проверка: контакт-лист кадров конца шагов и распознавание итогового MP4 Deepgram nova-2 с дословностью каждой фразы плюс фактическое начало её звука по `silencedetect` (`*.check.json`; в примере сдвиг ≤ 0.03 с). Vosk падает с `KeyError` на латинице и цифрах, поэтому инструмент отказывает заранее и требует писать их словами; экранные субтитры берутся из `sub`. Пример — `.orchestra/tasks/V-681/video/cache-ttl.mp4` по замеру V-676. Окружение TTS (`~/.local/share/orchestra-tts/`) вне репозитория: прежняя копия в `~/.cache/v75-tts` оказалась пустой — каталоги без файлов.
 
### dc881f5e5 V-686: real-dashboard media for README (stand, GIF, narrated EN video) + English voice in explainer-video

diff --git a/CHANGELOG.md b/CHANGELOG.md
index 4cf3f24ff..c80587dfc 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -5,10 +5,11 @@
 > content: the VPS block comes first below, followed by the laptop block. Task #52 fixes the format.
 
 ## Unreleased
 
 ### Added
+- **Английская озвучка в `explainer-video`** (`make.py --lang en --voice <голос>`, `scripts/explainer_video/tts_worker_en.py`; V-686). Владелец 03.10 попросил ролик для README GitHub «с анимациями на английском». Vosk-модель только русская, а Silero и Piper ранее отвергнуты по лицензиям, поэтому английский голос — Kokoro-82M (веса Apache 2.0) через `kokoro-onnx` (MIT) в своём окружении `~/.local/share/orchestra-tts/en/` (`ORCHESTRA_TTS_EN_HOME`), без облака и платных API. `check_steps` для `en` отказывает только на кириллицу (цифры и названия Kokoro читает сам), кэш фраз различает движок и голос, Deepgram проверяет с `language=en`. Замер: пять голосов на одной фразе — дословное распознавание у всех; синтез 14 фраз ролика ~1 мин против ~2 мин одной загрузки Vosk. Пример: `.orchestra/tasks/V-686/media/orchestra-tour.mp4` — тур по настоящему дашборду на демо-стенде.
 - **Формулы LaTeX в Manim-роликах** (`scripts/explainer_video/manim_voice.py`, скилл `explainer-video`; V-685). Владелец 03.10: «давай латекс тоже ставь, чтобы формулы тоже было всё чётко». TinyTeX (TeX Live 2026, 220 МБ) поставлен без apt и root в `~/.local/share/orchestra-manim/tex/` с пакетами, которые нужны шаблонам Manim, плюс `babel-russian`/`cyrillic`/`lh`. `manim_voice` при импорте добавляет его `bin` в PATH (папки нет → системный `latex`) и ставит `config.tex_template` с T2A и `babel[english,russian]`: шаблон Manim по умолчанию грузит только `babel[english]`, и `\text{кеш}` в `MathTex` падал с `Unicode character ц not set up`. Поправка к V-684: системный TeX Live 2023 на VPS стоял с 07.08 (apt), просто шаблон не умел кириллицу. В скилле — пример с подстановкой чисел (`TransformMatchingTex`), разбор ошибки `latex error converting to dvi` и команды установки. Ролик-пример: `.orchestra/tasks/V-685/video/compact55.mp4` — почему компакт по простою ждёт 55 минут, по формуле подписки V-660 и 70 компактам из `logs`.
 - **Manim — второй движок сцен в `explainer-video`** (`scripts/explainer_video/manim_voice.py`, ветка `.py` в `make.py`: `manim_steps`, `render_manim`; V-684). Владелец 03.10 попросил графики «как у 3Blue1Brown». ManimCE 0.20.1 (MIT) стоит вне репозитория в `~/.local/share/orchestra-manim/` через micromamba и conda-forge — Cairo, Pango и ffmpeg приходят пакетами, apt и root не нужны (`ORCHESTRA_MANIM_HOME` меняет путь). Сцена — класс-наследник `VoiceScene` с тем же `STEPS`, что у html-motion; блок `with self.step(i)` растягивает шаг до длины фразы, а `self.left()` даёт анимациям долю оставшегося времени, перебор шага останавливает сборку. Длительности приходят от `make.py` через `EXPLAINER_VOICE`, Manim сам пишет 1920×1080, контакт-лист снимается из готового MP4. LaTeX не ставили, поэтому `MathTex` недоступен — формулы пишутся Unicode-текстом. Пример: `.orchestra/tasks/V-684/video/night-shift.mp4` — сутки Оркестры циферблатом по `logs` за месяц.
 
 ### Changed
 - **Ролики по умолчанию в 1.5 раза быстрее** (`--rate 1.5` в `make.py`, паузы `LEAD`/`GAP` делятся на темп в `plan`; V-684). Владелец: «в полтора раза быстрее». Замер на фразах cache-ttl: Vosk `speech_rate` 1.5 сокращает речь в 1.48 раза при той же распознаваемости Deepgram (минимум по фразам 0.87 против 0.86 у 1.0), а `atempo=1.5` поверх обычной речи хуже (0.83). Без ускорения пауз ролик сократился бы только в 1.4 раза; `hold` последнего шага не трогается — это время досмотреть итог. cache-ttl: 68.8 → 47.4 с. Поправка: владелец, послушав, решил «полтора слишком много, давай 1.25» — умолчание `--rate` стало 1.25 (тот же день).
### 8e150a46e V-689: rebuild README dashboard GIF

diff --git a/CHANGELOG.md b/CHANGELOG.md
index c80587dfc..edfbf9c8c 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -59,10 +59,11 @@
 ### Added
 - **Агенты Harness (OpenRouter, GigaChat) видят правила проекта** (`project_instructions` в `app/harness/prompts.py`, `HarnessBackend._refresh_system_prompt`). Claude и Codex читают CLAUDE.md/AGENTS.md сами, а Harness до сих пор собирал системное сообщение только из промпта роли. Правила проекта до его агентов не доходили: в первом ходе `openrouter-lab-orchestrator` их не было. Теперь правила читаются так же, как в управляемом Codex: от корня git до cwd, по одному файлу на каталог (AGENTS.md, иначе CLAUDE.md), симлинк на тот же файл не дублируется, потолок 32 KiB как у Codex. Личные глобальные файлы не читаются, по решению V-570. Перечитываются на каждом ходу: правка доходит со следующего хода. Пока файл не меняется, системное сообщение остаётся тем же, и кеш провайдера не сбивается. Тесты: `test_project_rules_reach_the_harness_like_managed_codex`, `test_edited_project_rules_apply_on_the_next_turn`.
 - **Платные маршруты OpenRouter по белому списку владельца** (`PAID_HARNESS_ROUTES` и `harness_route_allowed` в `app/models.py`; допуск в `validate_harness_model_spec`, `normalize_catalog_model`, `OpenRouterClient._validate_route`). Раньше Harness пускал только точные `:free` маршруты, и оркестратор на DeepSeek V4.1 Flash (бесплатного варианта нет) создать было нельзя. В списке три маршрута: `deepseek/deepseek-v4.1-flash`, `z-ai/glm-5.3`, `z-ai/glm-5.3-flash` — владелец открыл их 01.10 для экспериментов с оркестраторами на OpenRouter (GLM-5.4 в каталоге нет, последняя GLM-5.3). Остальные платные маршруты по-прежнему отклоняются. Требование нулевой стоимости `usage.cost` сохранено для `:free`; у платного маршрута стоимость идёт в учёт сессии. Тесты: `test_owner_listed_paid_route_is_billed_and_others_stay_blocked`, `test_catalog_admits_only_free_or_owner_listed_paid_routes`.
 
 ### Fixed
+- **GIF-превью README начинается с задачи и рассказывает весь цикл** (`docs/dashboard-live.gif`; V-689). После замечания владельца 04.10, что старый GIF начинался с середины ролика, превью пересобрано от пользовательской задачи через разбор, запуск и работу воркеров, DONE, ревью/тесты, мерж, доску и квоты. У GIF собственные английские подписи без номеров: 1100×618, 10 fps, 6.54 MB, с возвратом к первому кадру на стыке цикла.
 - **Долгие таймеры `bg_create(type="timer")` больше не умирают молча** (`app/bg_jobs.py`). Срок жизни таймера (`delay + 1 ч`) обрезался потолком 8 суток, поэтому таймер дольше ~8 суток принимался с «OK», но истекал раньше своего срабатывания (баг-репорт seedon 29.09: bg-a0c0992639, срабатывание 27.10, истечение 07.10). Потолок для таймеров снят по решению владельца («без ограничений»): срок всегда позже `trigger_at`. Тест `test_long_timer_expires_after_it_fires`.
 
 ### Removed
 - **Тень-гейт «DONE без проверки после последней правки» (V-614) удалён** (`app/done_gate.py`, вызов в `app/message_deliveries.py`, `scripts/done_gate_weekly_report.py`). Неделя в тени (23–30.09): отмечено 73 из 217 докладов DONE, ни один из отмеченных не упал на тест-гейте мержа, а 4 из 5 реальных провалов гейт не отметил; основная масса отметок — проекты без кода (презентации, тексты). Решение владельца 30.09 «убираем». Старые строки `done_gate_verdict` остаются в журнале; чат по-прежнему их не рисует.
 - **Скилл `vps-deploy` убран из продукта** (`prompts/skills/vps-deploy.md`, `pipeline.yaml` у оркестратора). Решение владельца 29.09: это было единственное место поставки с упоминанием хостинга, а перезапуск Orchestra и так инициирует только владелец.