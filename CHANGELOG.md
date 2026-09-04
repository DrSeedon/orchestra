# Changelog

> **Two environments merged, 04.08.2026.** Before this date, the laptop and VPS maintained
> their CHANGELOGs independently, so versions 2.31.0-2.33.0 were used TWICE for different
> content: the VPS block comes first below, followed by the laptop block. Task #52 fixes the format.

## v2.43.0 — 2026-09-04 — сторож памяти: один прожорливый процесс умирает вместо всего дерева

### Added
- 🛡 **`app/runaway_guard.py` — сторож, убивающий ОДИН процесс, вышедший за потолок RSS.** Каждые 20 с обходит `/sys/fs/cgroup/system.slice/orchestra.service/cgroup.procs`, читает `VmRSS` из `/proc/<pid>/status` и после ДВУХ подряд превышений шлёт `SIGKILL`, записывая в журнал pid, объём и полную командную строку. Потолок `RUNAWAY_GUARD_LIMIT_MB=2048`, интервал `RUNAWAY_GUARD_INTERVAL`, выключатель `RUNAWAY_GUARD_ENABLED=0`. Собственный pid Orchestra не трогается никогда: его смерть — отказ платформы, а не лечение.
- **Почему не хватало живого `MemoryHigh=8G` на юните:** cgroup-лимит наказывает ВСЁ дерево, а не нарушителя. 04.09 `awk` с вложенным квантификатором `([^|]*\|){8}`, написанный Luna в ходе `codex_review` воркера `ane-research` (comfy-image-pipeline, задача #96), вырос до **7.9 ГБ на файле в 21 КБ / 53 строки**. Cgroup упёрся в `MemoryHigh`, начал реклейм — и в своп уехали Orchestra, четыре агентских CLI и TG-мост разом: **iowait 68.7%, load 26 на 12 ядрах, свободной RAM 280 МБ, отклик `/api/sessions` не измерялся**. Виновник при этом продолжал работать в состоянии `D`. После `SIGKILL` вручную: RAM 280 МБ → 3.7 ГБ, load 26 → 10.3, отклик 57 мс.
- **Почему не `RLIMIT_AS` на агентских CLI** (первый напрашивающийся вариант, отвергнут замером): они резервируют адресное пространство десятками гигабайт при копеечном RSS — `claude` показывает `VmPeak` **9.27 ГиБ** против `VmRSS` **220 МБ**. Любой осмысленный потолок убил бы сам агент, а не его выродившегося внука. Потолок 2 ГиБ выбран как ~6× над всем легальным, что удалось намерить (максимум одного процесса в cgroup — 0.31 ГиБ, суммарный пик прогона шарда pytest — 0.50 ГиБ), и ~4× под аварией. **Known tradeoff:** замер на самых тяжёлых 40 файлах сьюта не доехал (таймаут на 49%), поэтому верхняя граница легального прогона намерена не полностью; потолок вынесен в переменную окружения именно из-за этого.
- Сторож поднимается в `lifespan` рядом с `portfolio_watchdog` (`app/main.py`). Оракул — `tests/test_runaway_memory_guard.py`, три шва (убийство нарушителя без соседей, требование двух страйков, неприкосновенность своего pid), каждый проверен отдельной мутацией; плюс живая проба на настоящем процессе в 2.26 ГиБ — первый проход молчит, второй убивает с кодом −9.

### Known issue
- **Сторож смотрит только на ПАМЯТЬ.** Осиротевший `chrome-headless-shell` от прерванного прогона Playwright крутил 458% CPU при 341 МБ RSS и под это правило не попадает. Ловится тем же обходом cgroup, но требует второго замера (CPU за интервал) и другого потолка — отдельная задача.

## v2.42.0 — 2026-09-03 — компакт: честная квитанция, дословный хвост, терминальный отказ

### Fixed
- **Строка успеха компакта врала во ВСЕХ 75 случаях из 75** (`app/session.py`, `compact()`). Печаталось `compact done: 100% → 100%`, хотя реально контекст падал до 23%. Причина: `after_pct` читался из `self._last_context` синхронно сразу после ack-хода, а свежая сессия отдаёт `DeferredContext`, чья ветка в `app/session_cost.py:116` процент НЕ ТРОГАЕТ — точное число прилетало фоновым `_refresh_context_from_api` уже после возврата. Теперь размер новой сессии считается по расходу самого ack-хода (`_context_token_total()`, разница снимков до и после), медиана ошибки 2 п.п. на 57 замеренных компактах против 200К-окна, где ошибка была бы 30 п.п. Квитанция получила `pre_tokens`, `post_tokens`, `dropped_tokens` — аналог `compactMetadata` у Claude Code. *Triggered case:* сравнение систем компакта показало медиану сжатия «1.0x» на 75 компактах, что физически невозможно.
- **Компакт сессии со снесённым worktree ретраился трижды с бэкоффом 30 и 60 секунд** (`app/session.py`, `_is_terminal_compact_error`). `Working directory does not exist` — 27 из 38 всех ошибок компакта в базе, то есть 9 воркеров × 3 бесполезные попытки по 90 секунд каждый. Отказ признан терминальным и возвращается с первой попытки. **Known tradeoff:** предикат по подстроке текста SDK, а не по предусловию на `self.cwd` — предусловие ломало два чужих теста #380, чьи фикстуры используют несуществующий `cwd` при замоканном бэкенде.

### Added
- 🧵 **Дословный хвост диалога рядом со сводкой** (`app/session.py`, `_preserved_tail`, `COMPACT_TAIL_CHARS=12000`). Сводка — пересказ, и самый свежий обмен терял в ней формулировки: Claude Code хранит последние сообщения сырыми (`preservedSegment` в `compactMetadata`), у Orchestra их не было ВОВСЕ — весь контекст проходил через горлышко пересказа. В преамбулу новой сессии теперь едет блок `[VERBATIM TAIL]` с последними репликами (`user_message` и `text`) в пределах бюджета символов. `tool_result` в хвост намеренно не берётся: это 442 МБ из 555 МБ всего содержимого логов, то есть ровно тот вес, ради которого компакт и затевается. **Reasoning:** берётся `self.id` (id сессии Orchestra), а НЕ `session_id` нативного CLI — `logs.session_id` ссылается на `sessions.id`; первая версия брала нативный и молча давала пустой хвост, поймано оракулом T2.

### Known issue
- **Микрокомпакт строить не нужно — он уже есть.** Orchestra поднимает тот же бинарник Claude Code (`cli_path = shutil.which("claude")`, `app/backend_claude.py:909`), а в нём 2.1.259 лежат `tengu_time_based_microcompact`, `compact_micro_keep_recent`, `tool_result_clear` и `microcompact_boundary`: выгрузка тел `tool_result` с сохранением через `persist(content, tool_use_id)` по серверному `context_hint`. Следов его СРАБАТЫВАНИЯ в наших транскриптах нет, но отсутствие события означает неизвестность, а не отсутствие механизма.

## v2.41.1 — 2026-09-02 — чат дашборда чинён: гейт происхождения отвергал КАЖДОЕ сообщение
### Fixed
- **`POST /api/sessions/{name}/send` без `sender` больше не отвечает `403 SOURCE_PROVENANCE_REQUIRED`** (`app/routes/sessions.py`). Гейт из #433 требовал авторизованного оператора, но `validate_session` возвращает False при пустых `DASHBOARD_USER`/`DASHBOARD_PASSWORD` (`app/auth.py:58-61`) — это наша штатная конфигурация, — а фронт шлёт в `/send` только `{message, scope}` (`app/static/js/chat.js`). Оператор был недоказуем В ПРИНЦИПЕ, поэтому чат дашборда не работал ЦЕЛИКОМ, а не иногда. Теперь недоказанное происхождение помечается `origin="unknown"` и сообщение доставляется. **Reasoning:** это правило самого #433 («отсутствующее происхождение рисуется как `unknown`, НИКОГДА как `user`») — отказ означал не «не соврать», а «не доставить». Ветка с доказанным кукой оператором по-прежнему даёт `user`, ветка с `sender` — `agent`. *Triggered case:* юзер написал агенту из дашборда и получил 403; ветка 403 не была покрыта ни одним тестом, поэтому оракулы #433 её падение не заметили.
- **Тот же класс дефекта пойман третий раз за двое суток** — операторский гейт на контуре с выключенной авторизацией отказывает ВСЕМ: 01.09 в `POST /api/message-deliveries/{id}/resolve` (снят вместе с эндпоинтом), 01.09 в `restart_preflight`, теперь здесь. **Проверка перед любым новым `require_operator_*` / `validate_session`: пройдёт ли этот путь на контуре БЕЗ `DASHBOARD_USER`?** Нет — значит гейт не сужает доступ, а выключает функцию.

## v2.41.0 — 2026-09-01 — codebase audit: 27 defects closed, 2 fixes reverted as regressions

Multi-agent audit (`docs/tasks/audit-0901/report.md`): 10 reviewers → 33 findings → adversarial
verification → three rounds of fixes, with every diff reviewed. Gate run: 915 passed, EXIT=0.

### Fixed
- **Canonical and legacy state in `app/tm.py` diverged in three places—one defect, one ticket (3×P0).** (1) `_api_update_task_if_current_unlocked`: a canonical CAS rejection fell through to `_candidate_receipts` and raised `KeyError: 'stable_id'` after legacy state had ALREADY been committed—a split brain. The shadow branch handled the same rejection explicitly; the canonical branch did not. The failure was systematic: legacy-only writers (`bind_task_to_session`, requeue/heir, `finalize_merge_outcome`) advance only legacy `sync_revision`, so every bound task permanently has `legacy_rev > canonical_rev`. (2) `discard_unbound_task` issued a raw DELETE only against `tm_tasks` (`TaskStore` has no deletion at all), making counters diverge so `IdentityConflictError` blocked EVERY subsequent task creation in the project. (3) `api_create_task` committed canonical state BEFORE fallible legacy validation, with no try/except or compensation. *Triggered case:* the TODO defect “`switch_worker_branch` is not atomic, `KeyError: 'stable_id'`” was symptom (1); the 28.08 comfy incident with jammed counters was symptom (2).
- **Permanent session-lock deadlock** (`app/session_hibernate.py`): three RUNNING→IDLE heartbeat transitions did not publish `publish_turn_finished`, while `wait_for_turn_completion` parked on that event with no timeout INSIDE `wait_for_session_lock`. `switch_worker_branch` hung forever, never released the lock, and every subsequent switch, merge, or delivery received LockBusy until restart—even though the dashboard showed the worker as `idle`. All three sites now publish the event, and the wait no longer trusts it blindly.
- **The restart button did nothing during an active mutation** (`app/routes/system.py`): `732d89cc` removed the gate from `_do_restart_service` and reduced the budget to zero, but `restart_server` first called `restart_preflight` with the old gate. With a 0.0 budget, any mutation returned 409 “still in flight after 0s.” The rule that restarts proceed without asking was not enforced in code; TG `/restart` used the same path.
- **The quota chart printed the WRONG threshold for Sol** (`app/static/js/quota-lines.js`, `app/routes/system.py`): every marker used the linear `bucket.limit_pct` label, including Sol's curved lane, although the curve itself was drawn correctly. At 50% window progress, the label said “threshold 55.5%” while the curve ran at 81.3%. The frontend now uses `lanes[].limit_pct`, which the server already sent.
- **Harness tokens grew quadratically** (`app/backend_harness.py`): `_cumulative_input/_output` were not reset between turns, and `_turn_end` returned them as per-turn `AggregateUsage`; `session_cost` then added them after every turn. Ten 50K turns produced ~2.75M rather than 500K. The implementation now follows the Codex scheme (`_usage_baseline`).
- **Control messages to the harness disappeared silently** (`app/harness/loop.py`, `app/backend_harness.py`): the `_injected` queue was drained only at the start of a tool round; on the final round or an interrupted turn, the next `clear()` destroyed the remainder even though delivery was already marked `SUBMITTED`. A carried-over message now arrives and is placed at the correct chronological position.
- **Voice messages whose transcription took over 30 seconds disappeared silently** (`app/tg_bridge.py`): after `MEDIA_WAIT_MAX`, `buf.epoch` rotated; late transcription failed the epoch check and returned without carry-over or notification. If the voice message was the only message, nothing at all was sent. The fix also closes double resolution of the same token, loss of the `important` flag in the mirror, collapse of distinct messages in one topic, and a synchronous `subprocess.run` in `_bot_api_health_loop` that froze the entire event loop and swallowed `sudo` failures.
- **MCP printed “accepted” for terminally failed deliveries** (`app/mcp_stdio.py`): `_message_delivery_receipt_text` special-cased only `DELIVERY_UNKNOWN`, so `FAILED_BEFORE_SUBMIT` (including non-retryable `TARGET_TASK_CHANGED`) was printed as acceptance; `_delivery_receipt_text` for `spawn_worker` had the same flaw. Merge recovery also discarded a CONFIRMED `FAILED` status and claimed “status could not be confirmed,” while the retry hint after a failed spawn lost the cross-repository warning.
- **Restart, not a person, clears the delivery barrier** (`app/message_deliveries.py`): `DELIVERY_UNKNOWN` at the FIFO head silenced a worker indefinitely (25 hours and six lost assignments), while the sender received a cheerful `QUEUED`. The barrier is justified while the outcome may still change—but after a restart, the process that could complete the delivery is dead and ordering can no longer change. `recover_message_deliveries` changes these records to `DELIVERY_UNKNOWN_ORPHANED`: the queue resumes, while uncertainty remains recorded as `DELIVERY_OUTCOME_UNRECONCILED` and is never treated as “delivered.” A sender behind a live barrier now sees `TARGET_QUEUE_BLOCKED` and its age.
- **SSE froze `agent_status` at connection time** (`app/routes/sessions.py`): `live_session` was resolved only once per connection, so a session not loaded when the stream opened stamped an active turn's events as `idle`, and the client overwrote the correct status.
- **The ×1000 money migration could run twice** for legitimately small prices (`app/db.py`). A durable marker now replaces value-based guessing, with a journal line whenever it runs.
- **A background job interrupted in the `triggering` phase remained stuck forever** (`app/db.py`). For a `run` job, users were told “interrupted by restart; the command was not rerun” even though the command HAD completed and its result was stored in the row. The result is now delivered through the normal trigger path (`app/bg_jobs.py`).
- **`resolve_base_branch` crashed `merge_worktree_to_main`** (`app/workspace.py`): target validation changes no refs, but ValueError escaped to the route's catch-all and became `partial/unknown`, retaining the task reservation. It now reports an honest `failed/not_reached`; the handling also covers `RuntimeError`, `OSError`, and a missing git binary.

### Removed
- Manual resolution of delivery barriers: the `POST /api/message-deliveries/{id}/resolve` endpoint, the `resolve_message_delivery` function, the manual-resolution state, and the operator gate. **Reasoning:** the gate depended on an operator session, but with authentication disabled (our default `.env` without `DASHBOARD_USER`), `require_operator_session` rejects EVERYONE, so the endpoint was dead on the laptop. Across 1,043 deliveries since 25.08, `DELIVERY_UNKNOWN` occurred ZERO times—an authenticated endpoint for such an event was overengineering. Restart-based automatic barrier clearing replaces it (see Fixed).

### Known tradeoff
- **Two fixes were reverted as regressions, and the defects returned to TODO.** (1) The `anthropic_fable` quota-gate bucket: the live `weekly_scoped` limit arrives with `resets_at: None`, so the bucket would have no parseable window, the diagonal would not apply, and Fable would be protected only by the hard 99% stop—a WEAKER gate than the current one. (2) Forced teardown in `AgentSession.interrupt()`: background `_disconnect_backend()` canceled the listener and heartbeat for an already NEW turn, leaving a `RUNNING` session without a watchdog—worse than the original false report. Rule #224 was applied literally: when the cure is worse than the disease, remove it entirely.
- **Contract #380 R7 was revised.** The earlier rule that “`DELIVERY_UNKNOWN` must never be bypassed” applies while the outcome can still change; after a restart, it cannot. Three `test_message_delivery_receipts_380.py` oracles failed ONLY on the state name—the behavioral checks (do not call the provider again, do not schedule the runner, `retryable: false`) were unchanged.

## v2.40.1 — 2026-09-01 — Claude no longer silently downgrades xhigh

### Fixed
- **`effort=xhigh` reaches the API as xhigh for Claude models.** Instead of silently downgrading to high, `backend_claude.py` enables `options.thinking = {"type": "adaptive"}` and passes through the requested effort. Technical cause: the 21.07 guard (`eff == "xhigh" → "high"`) protected against `400 output_config.effort 'xhigh' is not supported when thinking is disabled`; a two-arm live probe on Opus 5 on 01.09 showed that the SDK path accepts xhigh both with adaptive thinking and even without the flag—the guard had gone stale and silently stole the requested effort. **Triggered case:** the user hit the same 400 in interactive Claude Code (Opus 5 + ultracode + the thinking toggle off). Interactive mode explicitly sends `thinking: disabled`; Orchestra's SDK path does not. The `pipeline.yaml` defaults are unchanged (Opus remains high per #208); the branch activates only when xhigh is explicitly requested.

## v2.40.0 — 2026-08-19 — #343 one quota-admission rule; previous systems removed

### Added
- **The only worker-admission rule: a diagonal with shrinking tolerance plus a hard 99% stop** (`app/quota_gate.py` is the sole owner). Baseline = percentage of the window elapsed; tolerance = a linear `10` percentage points at the start of the window → `1` point near reset; threshold for a gated lane = `min(99, baseline + tolerance)` (`line_limit`, `tolerance_pp`). Sol and Claude workers are blocked STRICTLY above the line. Luna and Spark bypass the diagonal entirely; their only stop is `HARD_STOP_PCT`. Orchestrators never pass through the gate (the `is_orchestrator` check in `app/manager.py` and `app/session.py` precedes the gate call). A worker's pool is selected by model runtime; window start = `resets_at − window_minutes`; one formula covers Claude's fixed weekly window and Codex's rolling window (`window_progress`). The rule looks only at the current point and retains no history, so counter resets work without dedicated reset code. *Triggered case:* the old thresholds were flat percentages, so 40% usage looked equally normal on day seven and catastrophic on day one.
- **Spark uses its OWN `codex.spark.primary` counter, not the aggregate Codex counter** (`deciding_window`). *Triggered case:* on 19.08, Codex showed 100% while Spark showed 39%; one number cannot represent both pools, and the aggregate counter would have blocked the cheap executor alongside the expensive one.
- `GET /api/usage/quota-map` gives the panel a ready-made verdict and `limit_pct`/`tolerance_pp`/`progress` for every pool, plus the rule constants in `rule`. JavaScript does not duplicate the arithmetic: a second owner of the numbers would silently diverge from the gate. Contract: `docs/tasks/343/api-contract.md`.

### Fixed
- **Unknown quota PASSES, consistently at every call site** (`require_worker_admission` rejects only `state="blocked"`). The old fail-open behavior existed at one site only: spawn passed with `quota=unknown`, but the next mandatory `/send` returned 429 for the same condition. *Triggered case:* #227 produced a dead session that was unusable yet indistinguishable from a live one, which forced the gate to remain disabled. `unknown` now passes spawn, `/send`, queue draining, compaction, and `codex_review`.
- The stale `tests/test_mcp_quota_gate.py` fixture responded to `/send`, although spawn has long used `/api/sessions/{name}/initial-deliveries`; the test was red on `main`.

### Removed
- Removed in full, including tests, database fields, endpoints, and settings: `app/quota_controller.py` (shadow controller #291), `app/quota_runway.py` and `deficit_hours`/`min_work_hours` (the observational half of #314), `app/quota_alert.py`, `app/runtime_router.py` (inert audit path #187), `_quota_headroom` and the derived weekly block in `/limits`, `worker_model_policy` with `model_policy_override_reason` (gate #227), and the `quota_controller_*`, `quota_alert_state`, `quota_silence`, `runtime_routing_*`, and `usage_exchange_rate` tables.
- Removed nine endpoints: `/api/usage/quota-controller` (plus `/policy` GET/PUT, `/policy/rollback`, `/reserve` POST/DELETE), `/api/usage/routing-policy` (GET/PUT), and `/api/usage/routing-policy/explain`. `/api/usage` no longer returns `quota_headroom`; `/api/usage/analytics` no longer returns the `quota_controller` key. The legacy dual-wire readiness wrapper (`worker_readiness_envelope`, `wire_version`, `decision_state`) is gone: with fail-open for `unknown`, every branch reduced to “pass.”

### Reasoning
- The user selected this as the final rule, and it was implemented literally. `docs/tasks/314/quota-line-controller.html` shows its behavior on live data. Removal was preferable to coexistence because thresholds lived in four places at once (gate constants, hot `quota_controller_policy`, pipeline manifest, and router config); answering “why won't this worker spawn?” required reconciling all four.
- Thresholds are deliberately NOT operator-configurable: the hot policy was the second owner that made the numbers diverge. Changing the rule means changing the code.

## v2.39.4 — 2026-08-16 — #290 fail-closed cross-runtime handoff

### Changed
- **Runtime switching is now a verifiable transaction, not an optimistic transcript import.** Orchestra freezes one deterministic state packet from its own `logs`, computes the entire declared model-visible manifest up front, runs a separate tools-disabled ingress canary, verifies an independent capability receipt, and only then releases the source. The packet neither carries hidden reasoning nor elevates transcript/tool data to system/repository authority; an incomplete tool effect blocks the switch before a target is created.
- **Fallback is limited to one smaller packet candidate.** Network/auth/unknown errors are not disguised as incompatibility; a second compatibility failure ends the operation loudly. Two operation-ledger tables are added additively, while an ambiguous crash leaves the session in `recovery_required` rather than guessing ownership or redelivering a side effect.
- **All cross-runtime capabilities remain disabled.** Codex 0.146.0 and Grok 1.0.3 have not mechanically proven an empty ingress tool surface. Claude CLI 2.1.197 / `claude-agent-sdk==0.2.114` proved tools-disabled ingress, but the live semantic canary hit quota, and the complete provider-private normal surface cannot be serialized exactly before process launch. Before source release, Claude also verifies the attached normal-profile surface and provider-reported complete context, but this is a safety gate, not permission to enable the capability. Updating `claude-agent-sdk` deliberately breaks import/validation via a version tripwire and requires an isolated canary. The ledger remains; there is no return to silent summary/fresh-target switching.

### Compatibility gate
- A screenshot of an internal Codex benchmark dated 15.08 reports these results for a 741-turn / 231 MiB conversation: 27.62→1.66 s, 894→16 requests, 15,529→64 loaded transcript items, and −41.2% whole-app memory growth. The metric is named `conversation-renderer JavaScript heap`, so this is evidence about UI/lazy loading, not model context. As of 16.08 there is no official release note for the optimization, and the installed CLI remains 0.146.0.
- After an official release, one bounded A/B is allowed: native-resume latency/RSS/request count, plus a separate raw-history import payload/context-admission test. Packet/preflight ceilings stay in place until a separate token/context canary proves a change in model-visible behavior; a UI win alone is not that proof.

## v2.39.3 — 2026-08-15 — Grok chat: no double answer bubble

### Fixed
- **Grok's response is no longer drawn twice at the end of a turn** (`app/static/js/app.js`). `_log` is fire-and-forget: `turn ended` status sometimes received an id before `text`; defensive finalization on status closed streamBubble, and the following `text` created an identical second bubble. Finalization on `turn ended` is removed; `text` with the same body after live finalization is skipped (`_lastFinalizedStreamText`). *Triggered case:* “Nice. Another clean bubble” + Reasoning + the same text again.

## v2.39.2 — 2026-08-15 — Grok harness polish: resume flood + thinking

### Fixed
- **`session/load` no longer floods logs with old history as new events** (`_suppress_history_replay`, `_drain_history_replay_queue`). *Triggered case:* after compact/reconnect, a “hello” at 07:40:07 re-recorded dozens of tool/thinking/text events from the previous turn; user messages “disappeared” beneath the first-paint flood.
- **One reasoning card per turn, not 50+**—thinking flushes only on turn_end/fail/exit; tool/plan events flush only `text`. *Triggered case:* 54 thinking bubbles starting at 07:30.
- **MCP tool_result unwraps `OkayOutput`** (`_content_text` for `{type:MCP, output:{OkayOutput}}`). *Triggered case:* list_agents appeared as a JSON wrapper rather than a card.

### Known tradeoff
- Replay already written to the DB (07:36/07:40) remains; only new turns after restart are clean. Grok's 60-second compact acknowledgment timeout is unchanged.

## v2.39.1 — 2026-08-15 — Grok harness: connect + chat UI

### Fixed
- **Grok `session/new` no longer fails on HTTP/SSE MCP configurations without `headers`** (`app/backend_grok.py` `_mcp_server_configs`, `_headers_to_acp`). Bare `{type:http,url}` → Invalid params (measured on grok 0.2.112); the request now always includes `headers: []` or a list of pairs. *Triggered case:* COG-second-brain's `agentic-jobs` URL-based MCP broke switching to Grok, while Orchestra-orchestrator without HTTP MCP started normally.
- **Grok responses are stored in history and no longer merge across turns** (`_message_buf`/`_thought_buf` → final `text`/`thinking` on tool/plan/turn_end/fail). Previously only live `stream`/`thinking_stream` events were emitted, while the session persists only `text`/`thinking`: the DB held zero text events for an entire day after switching to Grok, and the frontend bubble stayed open. *Triggered case:* “messages merge into one,” reasoning appears in a separate live card above it, and responses vanish after reload.
- **Grok tool results are plain text, not a JSON grid** (`_content_text` unwraps `{type:content, content:{type:text,…}}`). *Triggered case:* the chat showed `type / content / text` instead of read/grep output.
- **Frontend: defensively close the stream on `turn ended` and show a `grok mcp ready` badge** (`app/static/js/app.js`).

### Known tradeoff
- The Python changes (`backend_grok.py`) take effect after an Orchestra restart or Grok-session reconnect. JS/CSS changes do not require a restart.

## v2.39.0 — 2026-08-13 — #245 dashboard voice input

### Added
- **Mobile voice input with a text preview was added to the message field** (`initVoiceInput`, `startVoiceInput`, `app/static/js/app.js`, `app/static/css/style.css`). A second tap stops recording; a separate `×` cancels it without a request; a timer and RMS indicator driven by `AnalyserNode` show live volume. Chrome selects Opus/WebM; Safari selects a supported MP4 format via `MediaRecorder.isTypeSupported`. The transcript is appended to the textarea and is never sent to the agent automatically. Permission, browser, network, and server errors appear beside the field. *Triggered case:* users had to type long messages on a phone even though Orchestra's Telegram path could already transcribe voice messages.
- **`POST /api/transcribe` accepts browser recordings and uses the shared Deepgram client** (`app/routes/tg.py`, `app/transcription.py`, `app/tg_bridge.py`). A single `transcribe_audio` serves both Telegram and the dashboard. Before the external request, the server validates MIME type, enforces a 10 MB ceiling and a real five-minute duration limit via `ffprobe`, then deletes the temporary file after the response. *Triggered case:* copying the Deepgram call into the frontend route would have created a second owner of retry/cache/cost logic and allowed unlimited uploads.

### Known tradeoff
- The new Python route appears in the running process only after a managed Orchestra restart. Shipping JS/CSS alone shows the button, but transcription returns 404 until restart.

## v2.38.3 — 2026-08-12 — #228 mandatory Bash payload guard

### Added
- **New and reconnected Claude sessions receive one `PreToolUse` guard for `Bash`, only when `CLAUDE_BASH_HOOK_ENABLED=1`** (`app/backend_claude.py`). The flag is off by default and read when the client is built, so a restart/reconnect applies the change without a code rollback. When enabled, the guard stops `run_in_background=true`, recursive `rm`, `chmod 777/0777`, and direct `curl | sh/bash`; the rejection text gives a safe next step (`bg_create(type=run)`, `trash`, least-privilege mode, or inspecting the file first). A normal newline is a command boundary; GNU forms such as `rm target -rf` and unambiguous `--r`/`--recu` abbreviations are covered too. Guard failure, internal timeout, or unknown outcome remains a loud `ERROR` but fails open. The matcher has no external deadline; the only time boundary in our code is the internal fail-open `wait_for(0.1)`.

### Known tradeoff
- This is a narrow mini-grammar, not a shell sandbox. Remaining historical misses are one quoted `rm -rf` inside a nested SSH shell, four `for …; do rm -rf …; done` bodies, and one `find -exec rm -rf`. Wrappers, shell keywords, expansion, command substitution, and nested shells are deliberately not claimed as covered. A heredoc body is data; commands after its terminator are analyzed again. Existing Claude clients do not receive the hook until a controlled reconnect; activation and the marker canary run in a separate operator window.

## v2.38.2 — 2026-08-12 — #222 narrow Spark admission

### Changed
- **Spark became a narrow fast/overflow route with an external oracle** (`pipelines/default/prompts/modules/model-routing.md`). Before spawn, the task must name no more than two files, fit within 100K of total initial context, specify every decision, and provide an independent mechanical check for every criterion. Semantic prose, review, and research are forbidden; any unsuccessful Spark run moves to another model without retry. The dedicated Spark bucket is explicitly described as small, and its unknown research-preview price makes cost totals incomplete. *Triggered case:* in blind replay, Spark silently invented a missing constant 2/2 times and failed the future oracle (19/42 and 18/42), while Luna stopped and asked 2/2 times. At ~164K, by contrast, Spark rejected both runs loudly before answering.

### Known tradeoff
- **Until #301, Spark has no reliable completion/accounting path in Orchestra.** `CODEX_TOKEN_PRICES["gpt-5.3-codex-spark"] = None`, and `_codex_cost()` fails before `turn_end` is created. Already streamed text may remain visible, but the completion event and dollar accounting are lost. We do not substitute a zero rate: any Codex-dollar total that may include Spark usage is understated by an unknown amount.

## v2.38.1 — 2026-08-12 — #212 `Read` images in chat history

### Fixed
- **Truncated `Read` results containing images are restored from the complete log row** (`_restoreToolResultImage`, `_toolResultImageSrc`, `app/static/js/app.js`). Chat still prefers the original file, then an inline thumbnail. If the temporary path is gone and the 16 KB history limit truncated base64, the frontend requests `/api/logs/{id}` and renders the full image with its actual media type. *Triggered case:* `/tmp/wedding-contact.jpg` had disappeared, `/api/files/raw` returned 404, and the dashboard left `🖼 [Image result]` even though the event log retained the complete image.

## v2.38.0 — 2026-08-11 — #174 native history import, Claude ↔ Codex

### Added
- **Codex→Claude transfers the complete conversation from `logs`, not a bounded summary** (`app/runtime_history.py`, `AgentSession._change_to_claude_with_history_locked`, `ClaudeBackend`). User/assistant records and completed tool call/result pairs are rendered into a target-native transcript through `SessionStore.load()`; reasoning is not synthesized. Tool history has a hard ceiling of 256,000 serialized model-visible characters, while payload and metadata are scrubbed of known secrets, including wrapped/URL-safe base64. An incompatible version or rejected schema explicitly activates the old summary fallback; reconnect releases the old SDK client even after version-preflight failure. *Triggered case:* during runtime switching, the production mechanism gave the new model at most 120 recent records / 32,000 characters and lost all tool results—in a measured long session, only 0.86% of the text survived. The first import implementation made the opposite error, reproducing 680,548 tool characters under a claimed 256,000-character budget.
- **Claude→Codex uses only `thread/resume.history`** (`render_codex_history`, `CodexBackend`, `AgentSession._change_to_codex_with_history_locked`). The experimental capability is enabled only for the import connection. The fresh thread ID in the response becomes the durable native ID, while ordinary resume still fails if the ID is substituted. Both adapters share one normalizer, sanitizer, and hard cap for tool history; historical tool calls are completed and marked as already executed. *Triggered case:* app-server 0.146.0 deliberately ignores a supplied seed ID during history import, so the old generic resume guard rejected a valid import as a foreign thread.

### Known tradeoff
- **`claude-agent-sdk` is deliberately pinned to `0.2.114`.** The native transcript contract was verified only with Claude CLI 2.1.197 / SDK 0.2.114. Updating `claude-agent-sdk` now deliberately breaks history import through a version tripwire and requires an isolated native canary; the pin must not be removed without that canary. The SDK accepts opaque provider entries, but its public type does not promise schema compatibility.
- **Codex history import is pinned to CLI `0.146.0` and an experimental API.** Any other version deliberately activates summary fallback before app-server starts; a CLI update requires an isolated native canary. Upstream marks `thread/resume.history` as unstable / cloud-only, so seamless import is not a guaranteed contract for the next version.

## v2.37.0 — 2026-08-11 — #185 chat navigation

### Added
- **Clickable event timeline and sequential navigation through your own messages** (`initChatTimeline`, `_jumpChatTimelineUser`, `app/static/js/app.js`). A narrow bar on the right distinguishes your messages, agent replies, workers, tools, statuses, and errors. The first `↑` jumps to your latest message, then cycles backward; `↓` moves forward. The timeline's `MutationObserver` processes only added and removed top-level nodes, avoiding a full-history scan on every render. *Triggered case:* in sessions with 7,338 records, finding your latest message manually meant scrolling through a mixed feed of messages, tools, and workers.

### Known tradeoff
- The timeline reflects only the loaded portion of chat and retains the existing `MAX_CHAT_NODES = 500` limit; unloaded pagination is not materialized as hidden markers. This keeps long live-session switching free of measured regression: median first paint was `78.0 → 61.8 ms` over five before/after runs. No speedup is claimed because the baseline ranged from `66.9–219.2 ms`.

## v2.36.1 — 2026-08-10 — #173 P0 prompt correctness

### Fixed
- **Reload no longer mixes personal memory with the custom/ownership overlay** (`app/manager.py`, `app/prompting.py`, `sessions.prompt_overlay`). A new nullable component distinguishes a legacy assembled prompt from an explicitly empty overlay. Reload removes every stale `<worker-memory>` block and inserts exactly one current block. Rename and manual replacement of the full prompt update the same persistence contract. *Triggered case:* audit #172 reproduced full-cycle prompt growth from `84,652 → 129,655 B` and stale memory appearing after an ordinary reload.
- **`codex_review` no longer labels every project `small team, MVP stage`** (`app/mcp_stdio.py`, `codex-debate.md`). The caller must provide its own `PROJECT CONTEXT`; an empty or context-free call fails before readiness/API, and both review modes receive one neutral rubric. *Triggered case:* high-load projects received understated severity calibration from an unconditional constant.
- **Codex guidance now matches the current runtime/config** (`CLAUDE.md`, `compact_worker`). It records the machine-local `project_doc_max_bytes = 131072` with a mandatory config recheck, native `.codex/skills`, and native same-thread compaction for automatic/manual Codex; Claude summary→fresh behavior is documented separately. *Triggered case:* #172 found three rules that already contradicted current code and configuration.


## v2.36.0 — 2026-08-06 — #127 prompts trimmed for Opus 5, #119 artifact skill rewritten

### Changed
- 🧹 **Removed self-review instructions that Opus 5 already performs on its own** (`Adversarial self-review` in `pipelines/default/roles/worker.md` and `roles/full-cycle.md`). Anthropic's official migration guide says to remove instructions where the review target is the agent's own output and no new observation is introduced. The “Checks and evidence” collection is UNCHANGED: it requires producing an artifact (run, mutation, command output), which the guide does not address.
  - *Triggered case:* the user received a summary of the guide claiming that “the main migration work is deletion.” The primary source contains four removal sections versus seven addition sections, while a grep for its own anti-patterns found two real matches in our 132,753-character collection. The correct cut was 330 bytes, not half the file.
- 🎚 **A delegation ceiling instead of “always spawn”** (`modules/orchestration.md`, Step 0.5 in `base.md`). Opus 5 delegates more readily than earlier models. A fresh spawn pays for ~90 KB of prompt again (≈$4 even for a one- or two-turn session, measured across 31 sessions). Queue mechanics and `check_conflict` are preserved verbatim; only the frame changed: parallelism is a means, not an end.
- 📏 **Length calibration for written artifacts** (`<communication-style>` in `base.md`). The threshold is new factual content, not file size: a measurement-heavy report is “correctly long,” while a section with no fact absent from the rest is padding at any length. *Triggered case:* the median file in our `docs/` was 10.3 KB, the maximum 61.8 KB, and five files exceeded 52 KB, yet there was no length rule at all.

### Added
- 🎨 **The `html-artifacts` skill was rewritten around design principles extracted from Codex** (`pipelines/default/prompts/skills/html-artifacts.md`). The hard-coded `#7c3aed` accent is gone; the palette derives from the artifact's subject, the type scale comes from one base, `@media print` is mandatory, and shadows are allowed only as state.
  - Measurement across 14 artifacts in independent sessions: purple 5/5 → 0/5, font-size scale 0/5 → 5/5, print support 0/5 → 5/5, focus states 1/4 → 3/3.
  - The honest limit of the effect is recorded in `docs/tasks/119/report.md`: there are two perceptually distinct tones, not five, and on everyday topics the old skill moved away from purple on its own. Some of the improvement belongs to the topic, not the change.

### Fixed
- 🌗 **The skill specified the arguments to `light-dark()` in reverse order** (`html-artifacts.md`). The specification puts the LIGHT-theme value first; an agent following the skill literally produced inverted themes. Nothing crashes or highlights the defect—the artifact simply renders backward. *Triggered case:* found in #123 by running one file under `color_scheme=light` and `dark` in the same execution.
- 🖱 **Image paths are inserted at the caret, not at the end of the field** (`_insertPathAtCaret`, `app/static/js/app.js`). Previously, `input.value += ...` moved the path to the end while restoring the caret to its old position, so the user continued typing before the path. A duplicate was removed at the same time: the ➜ button in the file tree called its own copy of the same logic.
- ⏱ **The drop test waits for every upload result instead of a fixed 100 ms** (`tests/test_frontend.py`). *Triggered case:* the flake occurred 3/9 times on code WITHOUT the #94 change and 1/9 times on current `main`. Alternating runs in two scratch worktrees proved the failure was unrelated to the change.

### Reasoning
- Prompt changes went into project files, not global `~/.claude/CLAUDE.md`: the `AGENTS.md` mirror is built byte-for-byte from `CLAUDE.md`, so every deletion automatically reaches Sol/Spark/Grok, where nobody has verified the claim that “the model checks itself.”
- The open question remains explicitly open: the distinction between self-review and producing an evidence artifact is inferred from the guide's examples, not stated in it. Only an A/B of `full-cycle` with and without the evidence section can close it; neither we nor Anthropic have that measurement.

## v2.35.5 — 2026-08-04 — #69 migration no longer confuses scope with repository

### Fixed
- 🧭 **`migrate_agent.py` asks git for the worker repository instead of deriving it from scope** (`worker_repo`, `target_worktree`, `slugify_repo`). `--from-scope`/`--to-scope` simultaneously acted as project directory and git repository: the bundle came from the root repository, while the directory slug came from scope, although the platform derives it from the **repository root** (`create_worktree`). In a project with nested repositories, this produced a bundle without the required branch and a path the platform would never inspect.
  - The repository is resolved exactly as the platform resolves it: `cd <worktree> && cd "$(git rev-parse --git-common-dir)/.." && pwd`. Failure falls back to scope, with an explicit warning that this is wrong for nested repositories.
  - The target path is computed **once per worker** (`target_worktree`) and reused by the transcript, worktree, and database row. Divergent copies of this formula caused the defect.
  - A missing target repository now fails loudly on the receiving host: silently moving a worker into another repository would give it unrelated history.
  - **Triggered case:** seedon contains `site/` and `infra/`, independent repositories with their own origins, both ignored by the parent. In #67 I declared their sessions unrecoverable precisely because I searched for repositories as name-based siblings instead of using `rev-parse --show-toplevel`.
  - Verified end to end: a worker from a nested repository migrates into ITS OWN repository (the copy contains `site.txt`, not files from the root repository) and commits. Mutating the repository source back to scope makes the test fail.
- 🌿 **`base_branch_strategy=parent` no longer blocks spawn across a repository boundary** (`app/manager.py::_resolve_base_branch`, `_crosses_repo_boundary`, `app/workspace.py::repo_root`). A parent on a feature branch in the root repository and a child in `site/` means the parent's branch does not exist there. Previously this raised `ValueError: local base branch does not exist`, which concealed the cause. Now, if the repositories are DIFFERENT (compared through git, not string prefixes), the base comes from the child's repository mainline and a WARNING names both repositories. If they are the SAME repository, the original error propagates unchanged because the missing branch is real. If repository identity cannot be determined, the code assumes no boundary: the original error is more honest than an invented explanation.

### Known tradeoff
- ⚠️ **The end-to-end nested-repository migration test requires passwordless sudo** (the `needs_two_users` marker from #55; the skip is explicit). Without it, only unit tests for the path formula remain.
- ⚠️ There is no silent base substitution, but the WARNING appears only in logs; the worker does not learn of the change from its prompt. For `strategy=parent` into another repository, this is a deliberate compromise; the alternative is refusing to spawn.

## v2.35.4 — 2026-08-04 — #62 test runs no longer erase other workers' worktrees

### Fixed
- 🛑 **Worktree cleanup does not run under pytest** (`app/manager.py::start_background_tasks`). `TestClient(app)` enters lifespan, which used to start `_periodic_worktree_cleanup`. A test that replaced `app.db.DB_PATH` with an empty temporary database but left the REAL `app.workspace.WORKTREE_ROOT` unchanged concluded there were “no live sessions” and deleted every project's clean worktree, including registrations in `.git/worktrees` and scope directories.
  - **Reproduced before the fix:** a green `pytest tests/test_build_signal.py` in a sandbox copy of the checkout erased both decoys and their registrations. **After the fix**, the same command preserves 2/2.
  - Seven files instantiate `TestClient` without isolating the root: `test_auth.py`, `test_bug_report_notify.py`, `test_build_signal.py`, `test_logs_sync.py`, `test_merge_operations.py`, `test_startup_bridge.py`, `conftest.py`. The safeguard for the next such file is the `_isolate_worktree_root` autouse fixture in `tests/conftest.py`.
  - **Triggered case:** at 14:19:56 UTC on 03.08, subagent `local_bash` ran “Verify template guard and run task 15 tests” in the MAIN checkout; at 14:20:37, `feat-instant` lost its working directory. Only four Orchestra directories were restored then. Seven seedon worktrees and the dnd-game-master directory remained deleted for two days, until the seedon orchestrator first tried to switch branches.
- 🚧 **An empty list of live sessions no longer means “delete everything”** (`app/workspace.py::cleanup_stale_worktrees`). An empty registry signals the wrong registry, not dead worktrees; the code now emits WARNING and aborts the pass. A second guard preserves any directory whose name belongs to a live (non-archived) session even if the stored path differs. A mismatch is a reason to inspect, not erase.
- 📢 **INFO from `app.*` modules is visible in journald again** (`app/main.py`). The handler was attached only to logger `"orchestra"`, while modules use `logging.getLogger(__name__)`; `app.workspace`, `app.session`, and the others are not descendants of `"orchestra"`, the root logger was empty, and `lastResort` filtered below WARNING. Consequently, worktree deletion left no journal entry: `journalctl -u orchestra --since 2026-08-03 | grep -c "stale worktree"` → **0**. The `app` package root is now configured, so new modules are visible by default. Worktree deletion itself is logged at WARNING; it is not routine.
- 🩹 **A worker whose worktree disappeared is shown as `broken`, not `idle`** (`app/session.py::_display_status`). Previously it looked healthy and failed only when assigned work; seven seedon workers remained “idle” for two days.

### Restored
- ♻️ **Seven seedon worktrees were restored** from `sessions.branch` at the paths stored in the database (`bizdev`, `designer`, `dev-lead`, `direct-research`, `marketer`, `payroll`, `sales`), with `.env` and `.mcp.json` copied as `create_worktree` does. The branches survived: cleanup deletes working trees, not refs.

### Known tradeoff
- ⚠️ **There is no source from which to restore `infra` and `seo-cro`.** Their `worktree_path` points to `…-seedon-infra` and `…-seedon-site` slugs, while the database scope is `/home/kesha/projects/seedon`; no `seedon-infra`/`seedon-site` repositories exist on the host, nor do seedon's `adhoc-748404/infra` / `task-1/seo-cro` branches. This data mismatch predates the incident; the orchestrator must decide whether to archive or rebind them.
- ⚠️ **`broken` is a new frontend status value.** `app/static/js/app.js` has its own status dictionaries and will show it as unknown; updating that dictionary belongs to the frontend owner (territory #33).
- ⚠️ The `test_api.py` race where “the monkeypatch is removed while the cleanup thread is still running” was not reproduced (three runs, 150 cleanup calls) and was not fixed separately; both guards in `cleanup_stale_worktrees` cover it as well.

## v2.35.3 — 2026-08-04 — #55 migrated workers can commit again

### Fixed
- 🔑 **Migration transfers the target repository's `.git` to the service user as well as the worktree** (`scripts/migrate_agent.py`). `git worktree add` and bundle `git fetch` run over SSH as the login user (usually root), leaving that user as owner of 17 target `.git` entries: `worktrees/<name>/*`, `refs/heads/<branch>/*`, `logs/refs/heads/*`, `objects/pack/*`, `FETCH_HEAD`. The old `chown` covered only the worktree, which was wholly insufficient.
  - **Two measured failures, not inferred ones.** (1) With a completely transferred worktree (0/0 foreign entries), git still reports `fatal: detected dubious ownership in repository at '<worktree>'`; for a linked worktree it also checks gitdir `.git/worktrees/<name>`. (2) After transferring gitdir too, `status` works but commit fails: `cannot lock ref 'HEAD': Unable to create '.git/refs/heads/<branch>.lock': Permission denied`.
  - **Triggered case:** the dnd-game-master orchestrator's 03.08 bug report—`kill_worker` and `worker_wip` failed with `dubious ownership`, leaving `force=true` as the only way to stop the worker, i.e. a kill WITHOUT checking unmerged work. The “check WIP before kill” gate silently vanished for every migrated agent. The other half was quieter and worse: under the rule “ALWAYS commit before reporting DONE,” a worker that can read but cannot commit appears healthy and loses its work.
- 🕵️ **The service user comes from the systemd unit, not the installation directory's owner** (`unit_service_user`, `target_service_user`, new `--to-unit`/`--from-unit`). Directory ownership is a guess: on 03.08, 3,021 files under `/home/kesha/orchestra` on this same VPS belonged to root while the unit had `User=kesha`. At that moment the script would have run `chown -R root` and **reported success**, preserving the defect it meant to fix. The `LoadState=loaded` gate is mandatory: `systemctl show <nonexistent-unit> -p User` prints nothing and exits 0, indistinguishable from a live unit without `User=` (the same class as the `OOMScoreAdjust` trap). If the unit does not exist, the code falls back to the directory owner with an explicit “this is a guess” label.
- 👁 **The chown check is no longer blind** (`_foreign_entries`, `_mode_snapshot`). Previously `find … 2>/dev/null | wc -c` returned `0` both when every entry had the right owner and when the path did not exist; the function reported a successful transfer without touching anything. Missing and unreadable paths now fail with different messages, and modes are compared after `chown` to ensure ownership, not permissions, changed.
- 🔊 **`git bundle create` and `git fetch` errors are no longer discarded** (`2>/dev/null || true` removed). The operator now receives the cause of lost worker commits; previously only the downstream symptom remained: `git worktree add: invalid reference`.

### Changed
- 🧹 **`git config --global --add safe.directory` on another host was replaced by one-shot `git -c safe.directory=…`** (`git_at`). The old approach permanently added an exception to the login user's gitconfig on a host we merely visit, while doing nothing for the service user—it treated the symptom for the wrong user.

### Reasoning
- We considered running target-side git through `runuser -u <service-user>`, which would prevent the defect structurally rather than cleaning up afterward. It was rejected on cost: every remote git call would have to be rewritten for a rare, human-operated migration. Revisit if migration becomes frequent.
- The original report's claim that `worker_wip` turned every git error into “no main or master branch exists” **required no change**: `4b722ba` (#7) fixed it at 09:31 UTC on 03.08, one hour after the report was filed at 08:28 UTC. A live run verified that `branch_wip_status` returns the actual git text for a foreign repository. The report sat for two days because nobody connected it to the fix already on `main`, motivating #56 (bug-report delivery).

### Known tradeoff
- ⚠️ **End-to-end migration tests require passwordless sudo** (`tests/test_migrate_agent.py`): ownership cannot be modeled with stubs; it requires two real users and real git. Without sudo, three tests are skipped—but those are precisely the tests that prove a migrated worktree can commit.

## v2.35.2 — 2026-08-04 — #53 orphaned `GET /api/report_bug/status` removed

### Removed
- 🧹 **`GET /api/report_bug/status`** (`app/routes/system.py`) and the `has_reports` and `version` fields in `_bug_snapshot()`—they existed only for this route (`version` was the dashboard banner's `localStorage` version; `has_reports` was computed only to populate it). The snapshot fingerprint's sha256 is gone too; nothing needs to compute it now.
  - **Triggered case:** #53 removed the “New bug reports” banner, which was this route's only caller.
  - Route surface: `tests/route_surface_snapshot.json` lost **exactly one** route, `("/api/report_bug/status", ("GET",))`, and gained none—verified by symmetric difference rather than visual inspection.

### Known tradeoff
- ⚠️ **`GET /api/report_bug` was NOT removed even though no code calls it either.** It is the only reader of the private `~/.local/state/orchestra/bug-inbox/records/` store, where `POST /api/report_bug` writes each report as a separate file outside git. At the time of the change, it held seven live reports from four agents (03.08, 28,371 B), and **none appeared in the repository's `BUGS.md`**, which had not been updated since 01.08. In addition, `POST` returns the literal string `Bug reported: … Read: /api/report_bug` to the agent (`app/mcp_stdio.py:1418`); removing GET would make the platform distribute a 404 link. The store needs a different entry point in a separate task.
- ⚠️ Nobody reads `snapshot["inbox"]` and nobody did before this change. It is someone else's dead code and was left untouched. — 2026-08-04 — #53 “New bug reports” banner removed

### Removed
- 🐛 **The new-bug-report banner and its polling** (`app/templates/dashboard.html`, `app/static/js/app.js`), removed at the user's direct request. This removed `#bug-report-banner`, 106 lines of client code (`_BUG_INBOX_SEEN_KEY`, `_bugSafeText`, `_hideBugReportBanner`, `_showBugReportError`, `_refreshBugReportStatus`, `initBugReportBanner`), the `orchestraBugInboxSeenVersion` localStorage key, and two banner tests.
  - `setInterval(_refreshBugReportStatus, 30000)` disappeared as a side effect: a 99 B response (112 B on the wire), two requests per minute, or **1,200 round trips and ~131 KB during a ten-hour day** for an element that no longer exists.
  - **Server-side behavior is unchanged:** MCP tool `report_bug` needs `POST /api/report_bug`. Neither `GET /api/report_bug` nor `GET /api/report_bug/status` has frontend consumers now; the orchestrator owns the routes' fate, so they were not removed without authorization.
  - Rendering of `mcp__orchestra__report_bug` tool calls in the chat feed remains; that is a different mechanism.

## v2.35.0 — 2026-08-04 — #49 self-hosted chart.js; the page no longer depends on third parties

### Changed
- 📦 **`chart.js` moved from `cdn.jsdelivr.net` to `app/static/css/vendor/chart.umd.min.js` and gained `defer`** (`app/templates/dashboard.html:29`). Version **Chart.js v4.5.1**, license **MIT** (c) 2025 Chart.js Contributors; the file header is preserved unchanged. It occupies 208,522 B on disk and 70,658 B gzip. It is served through `g.asset()`, with a versioned URL (#9) and nginx compression like the other six vendor files.
  - **It was the page's ONLY external dependency** and its only script tag without `defer`/`async`, so it stopped the parser and delayed `DOMContentLoaded`. Yet `Chart` is needed ONLY by the analytics modal (`analytics.js`, `_analyticsRenderChart`), not by first paint.
  - **What `defer` does NOT do:** by specification, deferred scripts execute BEFORE `DOMContentLoaded`, so DCL still waits for the file. The change removes parser blocking and a third party from the critical path. `async`, which would also free DCL, was deliberately rejected: `_analyticsRenderChart` silently returns without `Chart`, so opening the modal within the first few hundred milliseconds would show an unexplained blank area.
  - **No median improvement was measured or claimed.** Three paired runs through the domain produced −204, +77, and +207 ms with ±1.2 s spread; the measurement tool (intercepting `**/*` to replace the template) outweighed the effect. Post-merge measurement belongs to perf, where nginx serves the file and interception is unnecessary. The justification is the distribution tail, not the median (see triggered case).
  - **Triggered case:** perf measured dashboard opening through the domain and caught a run where jsdelivr took **16.8 s**. Everything else moved by the same amount: DCL 17.3 s, agent list 17.6 s, chat 17.9 s. From the VPS, the same CDN usually responds in 50–115 ms, so this was not “the CDN is down” but a tail event on the data center's direct route; the user's route to a foreign CDN is predictably worse. Ordinary measurements miss it because the browser caches the file—it hits first visits and cache misses.
  - The post-`defer` modal was verified by opening it, not by reasoning: `Chart` existed at load time, the canvas measured 1007×250, the chart object was created, and **80,328 pixels were painted**. There were zero jsdelivr requests.
## v2.34.0 — 2026-08-04 — #37 `HEAD /api/models` for heartbeat

### Added
- 🪶 **`HEAD /api/models` returns 200 with the same `X-Orchestra-Build` and an empty body** (`app/routes/system.py`). It uses a separate handler rather than adding `methods=["GET","HEAD"]` to the existing route; a shared route would still compute the complete GET body and let the transport discard it. GET, its keys, and its header are unchanged, preserving the live-client contract.
  - **Triggered case:** `_heartbeatProbe` calls `/api/models` every three seconds for status and the version header, then discards the body. `HEAD` returned 405, so the client had no alternative.
  - The test compares HEAD and GET headers **within one run** and requires an empty body. It verifies “the header is identical,” not merely “the method is allowed”: a green “405 is gone” could hide the silently disabled update banner from #15. Both mutations fail (no route → 405; route without header → mismatch with GET).
  - **Deployment order:** switch the client to HEAD only AFTER restart. Until then the live server returns 405, and the client change would break the version banner.

### Reasoning
- ⚖️ **Wire savings are ≈240 B/s per tab, not 1.5 KB/s** as the ticket estimated. 4,732 B is the uncompressed body; on the production path nginx sends `content-encoding: gzip` and **747 B** (+162 B of headers). This does not invalidate a three-line, strictly better change, but on a 15–80 KB/s link it saves 0.3–1.6% of bandwidth. `docs/tasks/37/report.md` analyzes the body and its two duplication sources (`capabilities`: three distinct blobs in 12 copies, 57% of the array; `backend`: a byte-for-byte copy of `runtime`). The response shape was not changed because that would break the live client before restart.

## v2.33.2 — 2026-08-04 — #34 role icons come from the manifest; frontmatter fallback removed

### Removed
- 🧹 **`role_can_spawn()` was removed** (`app/prompting.py`) along with its six unit tests (`tests/test_manager.py::TestCanSpawn`). The function read `can_spawn` from role YAML frontmatter and always returned `None` (“no restrictions”), but nobody consumed its result: `1bff39a` removed the import from `app/manager.py` together with the fallback itself. Only the manifest decides spawn permissions through `validate_spawn()` (`app/pipeline.py:483`), called at the single `create_session` site (`app/manager.py`) behind the sole agent-creation route, `POST /api/sessions`.
  - Evidence, not code reading: for identical inputs, `role_can_spawn('worker')` returned `None`, while `validate_spawn(default, worker→worker)` raised `ValueError: cannot spawn, allowed (none — terminal)`. The prohibition is observable, so the manifest controls it.
  - **Frontmatter data was not “lost during migration”; it never existed:** `git show 1bff39a^:app/prompts/roles/*.md | grep -c can_spawn` → `0,0,0,0`, and the `pipelines/` files were created without frontmatter from the start (`7ccaadb`). The #25 mechanism shipped with zero configured data and was replaced by the manifest. Without this check, we would have “restored” something that never existed.
  - The `app/manager.py` comment no longer mentions legacy fallback. It does not exist, and `FileNotFoundError` from a missing manifest is not caught (fail loud).

### Fixed
- 👑 **`get_role_icons()` reads `roles.<name>.tg.emoji` from the manifest** (`app/prompting.py`, `pipelines/default/pipeline.yaml`). Previously it scanned `pipelines/default/prompts/roles/*.md` for `icon:` frontmatter—but role bodies begin with `<role>` and contain no frontmatter, so the live server returned `{}` for every `GET /api/role-icons`. Emoji were added for three roles (`orchestrator 👑`, `worker ⚙️`, `full-cycle 🔄`; `sub-orchestrator 🎯` already had one). The deployment order was the reverse of removal—data first, then the source—or icons would disappear entirely between commits.
  - **Triggered case:** MCP `list_agents` rendered the orchestrator as `⚙️`, identical to workers, because the single `_icons.get(r, "⚙️")` default (`app/mcp_stdio.py`) applied to every role. The dashboard happened to look correct: `app/static/js/app.js:2100` maintains its own hard-coded dictionary for six roles and merges an empty response over it. This was observed in a live tool call, not in code.
  - Where the icon went during migration: `scripts/extract-manifest.py:120` maps frontmatter `icon` → `tg.emoji`. `PipelineConfig` parsed the field but NOBODY in `app/` read it; now it has a consumer. Only one role (`sub-orchestrator`) had an icon before migration, so restoring frontmatter would add no information.
  - As a side effect, blocking I/O left the event loop: cached `load_pipeline` replaces four file reads per request (lever C from `docs/tasks/3/research.md`).
  - `app/mcp_stdio.py` and `app/routes/system.py` required no changes: both consumers call the endpoint unchanged and simply began receiving a nonempty response.

### Reasoning
- The option to remove icons entirely and hard-code them in two places was rejected: it would create two source-of-truth dictionaries instead of one source, reproducing the exact drift already seen with `AGENTS.md` and status dictionaries.
- `parse_role_frontmatter()` was NOT removed: skills have real frontmatter, and `_read_skill_index_entry` needs it.

### Known tradeoff
- ⚠️ **The hard-coded dictionary in `app/static/js/app.js:2100` is now a second copy of truth.** Its values match the manifest, so the dashboard looks unchanged, but the frontend owner must remove the copy; this was handed off separately.
- ⚠️ `tg.emoji` now means two things: role icon and TG topic emoji. They were designed as one (`scripts/extract-manifest.py:15`), but if topics need their own icon, the fields must be separated.
- ⚠️ **`validate_spawn` remains fail-open:** an unknown parent or child role may spawn; the whitelist works only for known roles. This is a manifest boundary, not a frontmatter boundary, and removing `role_can_spawn` does not widen it (frontmatter allowed everything unconditionally and was strictly weaker). Tracked as #36.
## v2.33.1 — 2026-08-04 — #21 `/api/sessions` no longer reads the entire logs table

### Fixed
- 🗂 **Partial index `idx_logs_status` on `logs(session_id, ts) WHERE type='status'`** (`app/db.py`). Every `/api/sessions` call invokes `get_last_turn_map()`, which performed `SCAN logs USING INDEX idx_logs_session`. To apply `content LIKE 'turn ended%'`, SQLite read `content` from all 9,685 rows (14.4 MB of text) to retrieve 801 (8%). **16.0 → 0.6 ms**, with an identical 20-row result. Building the index on the live 23 MB database took 35 ms; no separate migration is needed (`IF NOT EXISTS` in the schema).
  - A partial index was chosen instead of `(type, session_id, ts)`: the speed is identical (0.6 ms), while only 8% of rows are indexed; `logs` is the hottest write table.
  - **Triggered case:** task #21 asked us to examine lever C: “`get_role_icons` reads disk on every request; `get_all_sessions` accesses SQLite on the event loop.” Re-measurement under raised limits (`MemoryHigh=8G` instead of the 2G used for earlier profiles) showed that **neither named function needed a fix**: `get_role_icons` had zero profile samples and took 3 ms; `get_all_sessions` took 1.9 ms. An unnamed third function accounted for 55% of the entire wall-clock profile. GIL profiling hid it (`sqlite3` releases the GIL during queries, understating everything that blocks the loop through SQLite); only ordinary wall-clock profiling exposed the number.
  - Measurements and conditions: `docs/tasks/21/report.md`. It also records that under six concurrent clients, a trivial endpoint degrades from 3 ms to p50 185 ms, so the `/api/sessions` handler monopolizes the loop; and why the overnight “dashboard loads slowly” complaint did not belong to the server (between 00:00 and 05:00, neither nginx nor the application received a dashboard request—only scanners).

### Reasoning
- The change deliberately leaves the functions named in the ticket untouched. “This function reads disk/DB on every request” is a cost hypothesis, not measured cost. Under a healthy limit it was false; the adjacent line in the same handler was the real cost.

## v2.33.0 — 2026-08-03 — #28 reindex returns control immediately

### Changed
- ⏳ **`POST /api/memory/reindex` queues indexing and responds immediately** (`app/routes/memory.py`, `app/rag_service.py`). Before: the route waited for `await backfill_scope(...)` to finish while the request field was named “fast per-agent reindex.” After: `schedule_backfill(scope, session_name)` → `{"ok", "status": accepted|coalesced, "index"}`, with progress visible in journald and `index_status`.
  - **Breaking:** the response no longer contains `{files, logs}` because they do not exist yet when it returns. The endpoint has no code or frontend consumers (searched across `app/`, `scripts/`, `tests/`, `pipelines/`); humans call it directly.
  - **Triggered case:** `perf` called it to measure a session with ~500 logs and timed out after 6.5 minutes. This path cannot be made fast in principle: embedding one log takes 1.3–2.9 seconds, so “fast” and “synchronous” are incompatible here; the label itself was false.
  - Session reindex now uses the same `_LOG_SLICE` chunks as the global run instead of one unbounded query. The scheduler key is composite (`scope::session`) so an explicitly requested reindex is not coalesced into a background scan of the entire scope.

## v2.32.0 — 2026-08-03 — #19 chart loads one period, not all history

### Changed
- 🪟 **The frontend requests `hours=168`—exactly one anchor window; earlier windows arrive when ◀ is clicked** (`app/routes/system.py`, `app/db.py`, `app/static/js/usage.js`). The route accepts `until` (exclusive right boundary) and returns `oldest_ts`, the timestamp of the first snapshot ever. It keeps ◀ active after loaded periods are exhausted and now drives the “Snapshots since …” label. Previously the label used the first LOADED snapshot, which would become false with lazy loading. Chunks merge into `_sparkData` and live until the tooltip closes.
  - Initial load: **860,039 B → 414,667 B** (760 points instead of 1,629), gzip through nginx ≈57 → ≈26 KB. One ◀ click: 152,497 B / ≈11 KB. More important than the numbers, the initial response **no longer grows**: the seven-day window is fixed regardless of accumulated history. It previously grew by 29 KB/day.
  - **Cache rather than refetch**—a data-driven decision: an ≈11 KB gzip chunk over a 15–80 KB/s link with TTFB 0.53–4.22 s costs 0.7–5 s, and merging is cheaper in code too (refetching would require discarding chunks on ▶). Browser verification: ◀ ◀ ▶ produced two requests; forward navigation came from memory.
  - **The navigation window follows data, not the calendar** (`usage_history_ts_before`): after a gap longer than a week, a calendar-based chunk would be empty and ◀ would remain stuck forever.
  - Verified that “frequent clicks through 5h windows” are impossible: navigation is anchored to the provider's longest window (`anchorSeries`), and no window exceeds seven days, so each click always moves one week.
  - This also measured what #13 had only calculated: nginx does compress this response (`content-encoding: gzip` on the production path), but **1.130×** less efficiently than Python's `gzip.compress(level=6)`. The “50.9 KB” claimed in #13 becomes ≈57.5 KB on the live path.

### Fixed
- 🎨 **Provider series order no longer depends on which chunk loaded first** (`app/static/js/usage.js`). Series are sorted by `window_minutes`; previously the first data row encountered set both order and palette color.
  - **Triggered case:** clicking ◀ to the “2w ago” frame swapped the 5h and 7d lines and colors because the older loaded chunk did not yet contain the 5h window. This never appeared before lazy loading because the complete history kept order stable. A visual run found it; neither tests nor code reading did.

### Known tradeoff
- ⚠️ **The first ◀ click always costs a request.** Deep navigation is linear: N periods back = N requests of ≈11 KB. Preloading the second period would surrender half the saved volume for an action that most tooltip openings never take.
- ⚠️ `_SPARK_VIEW_HOURS = 168` is hard-coded in the client. If a provider gains a window longer than a week, the initial chunk will be shorter than the period and the chart will appear truncated until the first ◀ click.

## v2.31.0 — 2026-08-03 — #13 usage history: range-based resolution and honest gaps

### Changed
- 📉 **`/api/usage/history` selects its own resolution and returns `{step_minutes, rows}`** (`app/routes/system.py`, `app/static/js/usage.js`). Database-layer thinning through `usage_get_history(hours, step_minutes)` existed from the start, but the route never exposed it. Now `hours ≤ HISTORY_FINE_HOURS` (48) returns the full five-minute grid; longer ranges use `HISTORY_COARSE_STEP` of 30 minutes plus a full-resolution 48-hour tail. One year over HTTP: **4.25 MB / 0.93 s → 857 KB / 0.33 s**, 8,479 → 1,628 points, gzip -6 (nginx compresses `application/json`) 203 → 51 KB.
  - **Breaking:** the response is no longer a bare array. The client needs grid spacing to distinguish missing data from sparse sampling; a second copy of the spacing ladder in `usage.js` would drift from the server (as already happened with `AGENTS.md` and status dictionaries). The endpoint has no other consumers. `_loadSparkline` reads `history.rows` and `_sparkStepMin`; tests were updated.
  - **Why 30 minutes rather than guesswork:** the SVG is fixed (`usage.js`, `W = 280, PL = 28`) at 252 px, and the chart draws one period rather than the entire range. The provider's longest window anchors the period, and none exceeds seven days (`anthropic five_hour 300`/`seven_day 10080`, `codex primary 10080`, `codex_spark primary 10080`). Seven days over 252 px = 40 minutes/pixel; a five-minute grid produced eight points per pixel.
  - **The 48-hour tail is not cosmetic:** the current period starts at the latest reset, so during the first hours after a weekly reset, a 30-minute grid would leave only 2–4 points. The decision to stop is made from the current 5h window.
  - Shape-degradation check across 252 pixel columns over the latest seven days: in the tail, the 5h line differs by ≥1 px in exactly **1 of 71 columns**, while the 7d line differs in 0. Before the 48-hour tail, 5h differs in 42 of 179 columns (16 are reset edges where a 30-minute horizontal shift equals 0.75 px), and 7d differs in 2. Screenshot of both grids over identical data: `docs/tasks/13/before-after.png`.

### Fixed
- 🕳 **Forward-fill no longer draws a flat line across snapshot gaps** (`app/db.py::usage_get_history`, `app/static/js/usage.js`). The grid extended the last known value indefinitely. Now no point is emitted if the latest snapshot is older than `stale_limit = step * 2`; on the client, a point marked `p.gap` (neighbors more than `1.5 × _sparkStepMin` apart) starts a new polyline segment. Both usage and the dotted ideal-pace line break.
  - Live database measurement (6,583 snapshots, 29 days): **45 gaps longer than 30 minutes; the longest was 9h 11m**. The inverse risk was checked on the same data: only four 10–12 minute intervals (exactly one missing snapshot, where a break would be excessive) occurred in a month. The collector either works or stays down for a long time.
  - Both new tests were mutation-checked: `stale_limit = step * 100000` fails `tests/test_usage_history_resolution.py`; removing `p.gap` fails the line-break test in `tests/test_usage_history_frontend.py`.
  - **Triggered case:** the chart did not render at all because the one-year response weighed 4.29 MB and exceeded `api()` timeout. Volume analysis revealed that during nights with no snapshots, the curve still displayed the old 97%, even though the 5h window had reset and filled again. “Time to stop” decisions were based on this picture.

### Known tradeoff
- ⚠️ **A provider-specific outage shorter than 45 minutes is still connected by a line.** The client derives the break threshold from declared `step_minutes`, while the response mixes two intervals: the 48-hour tail actually uses five minutes but declares 30. Service outages last hours, so this does not affect them. But a provider unavailable for half an hour (`status: unavailable`, empty windows, hence no series points) appears continuous. Knowing this is cheaper than re-measuring: `docs/tasks/13/report.md`.
- ⚠️ **Volume growth is slower, not stopped:** ~149 KB/day before, ~30 KB/day now; today's 4.25 MB returns in 114 days (the arithmetic in the first version of this entry was wrong by 8×). The cause is structural: the frontend loads all history while drawing one period, and the year is needed only for ◀ navigation. Addressed in #19.

## v2.33.0 — 2026-08-03 — #134/#133/#132 memory-search quality ceiling: three consecutive “do not build” decisions

This section consists entirely of **negative results**. Not one line of production code changed,
and that is the substance of the release: three consecutive tasks ended with “option rejected,”
each for a different reason. The next agent who comes to improve `search_memory` should start
here rather than repeat the work.

### Rejected
- 🚫 **A reranker on top of hybrid search was measured, works, and was rejected by the user because it costs money**
  (`docs/tasks/134/research.md`, measurements in `docs/tasks/134/bench/`, visual analysis in
  `docs/tasks/134/134-reranker.html`). `hybrid + cohere/rerank-v3.5` through OpenRouter yields
  **MRR 0.7321 versus production's 0.4893** at `t = +3.46` (threshold 2.052; 28 queries against
  a live corpus of 68k chunks), with 13 improvements and one regression. The measurement cost $0.040.
  - **The main finding is not the reranker but the ceiling: 86% top-three recall is the limit of
    retrieval itself on our corpus.** Remaining misses require better index content, not ranking.
  - **A local reranker was rejected for TWO independent reasons, either sufficient:** the gain is
    insignificant (`t = +2.01 < 2.052`), AND CPU inference takes 17–28 seconds per query versus
    1.6 seconds for the API. The premise that “we cannot run it locally” is technically false—the
    model runs—but it does not solve the task.
  - **The existing production hybrid of vec+FTS5+RRF is justified:** 0.4893 versus 0.4012 for pure
    vector search and 0.3458 for pure FTS5 (the latter is significantly worse, `t = −2.54`).
  - **The unresolved deployment issue is latency, not money:** +1.6 seconds on EVERY agent turn.
  - ⚠️ OpenRouter's `POST /api/v1/rerank` **exists but is absent from the `/models` catalog**—the
    same trap as embeddings in #133. Exactly one model is live; 16 other ids return 400.
    **Do not trust the catalog; verify with a request.**
  - **Triggered case:** the post-#133 hypothesis that we had hit the embedder ceiling. A reranker acts
    on another link (ordering, not representation), which is why it delivered what no model swap did.

- 🚫 **Migration to API embedders: superiority was not demonstrated, so local bge-m3-int8 remains**
  (`docs/tasks/133/research.md`). One script tested seven models in one pass against 14 triplets
  from **our** production corpus (`data/vec.db`: 28,723 log_chunks + 39,447 file_chunks).
  - Three candidates “beat” local, but `|t| < 2` and the confidence interval includes zero.
    **Only two LOSSES are significant:** gemini and ada-002. Paying money, adding a network
    dependency, and accepting ~100× latency for a gain indistinguishable from zero is a bad trade.
  - As a side finding, the current production configuration (CLS pooling, no prefixes) is the best
    of eight tested pooling × normalization × prefix combinations.
  - ⚠️ **The old RAG document's numbers are not reproducible and were archived:** the model and
    pipeline did not differ; the triplets themselves did. The document was rewritten AFTER the
    measurement and retained wording that could not produce its numbers. Diagnosis: a broken model
    would move all five triplets together, but only 2/5 moved.
  - **Triggered case:** suspicion that the local model was worse than paid alternatives. It was not.

- 🚫 **No shared embedder service for Orchestra and the Kesha bot** (`docs/tasks/132/research.md`;
  `plan.md` was never executed). Measurement CONFIRMED duplication and disproved the orchestrator's
  original hypothesis that “the model does not load on the VPS”: two processes hold
  `AlpEge/bge-m3-onnx-int8` simultaneously (bot: 1.20 GiB RSS, including 1,206,268 kB anonymous;
  Orchestra on VPS: 881 MB), with two hash-identical 561 MB copies on disk.
  - **Why the “model is absent” check returned a false negative—three independent reasons, each
    sufficient:** (1) the bot model lives in `/tmp/fastembed_cache`, not the HF cache, so `find`
    under `~/.cache/huggingface` misses it; (2) the bot lacks `RAG_ENABLED` not because RAG is off,
    but because **the flag does not exist in its code**—`bot.py:196` calls backfill unconditionally;
    (3) the second process is not our local Orchestra but a **separate Orchestra instance on the VPS**.
  - **ONNX Runtime reads weights into the heap:** searching `/proc/<pid>/maps` shows only runtime
    `.so` files and creates the false impression that the model is absent. Inspect anonymous RSS
    (`/proc/<pid>/smaps_rollup`) and the loading log instead.
  - **Triggered case:** a four-core / 8 GB VPS at load 31.7 with full swap; we were identifying the memory consumer.

## v2.32.0 — 2026-08-03 — #8 dashboard switches agents without the network

### Added
- ⚡ **IndexedDB log mirror—chat history no longer travels over the network** (`app/db.py`,
  `app/routes/sessions.py`, `app/static/js/app.js`, +180/−95). The browser keeps a local copy of
  the `logs` table, synchronizes every project in one request (`GET /api/logs/sync`: a cold slice
  of the latest N rows per session plus watermark-based increments, capped by BYTES), and renders
  chat locally. The SSE stream opens directly at the tail; its first event (`__session`) names the
  session authorized by the server.

  | | Before | After |
  |---|---|---|
  | network waits before content (cache hit) | 3 sequential round trips | **0** |
  | history requests per switch | 1 (uncompressed SSE) | **0** |
  | history on cache miss | ~90 KB uncompressed over SSE | **17.6 KB gzip** (4.0×) |
  | browser switch | 826 ms | **39–121 ms** |

  - **The #2 DOM cache was removed** and replaced by the mirror in the same change; otherwise the
    switching logic would exist twice.
  - Any row with a foreign `session_id` clears and reloads chat, leaving no way to mix in another
    session's history.
  - A truncated row never enters chat: **if the mirror contains even one truncated row, the complete
    history is fetched from the server** (three lines of code instead of a “load” button). The approach
    changed because 5/6 truncated rows were `tool_result`, which has **no DOM node of its own** and merges
    into the preceding tool row. With production `tail=20` / `cap=16 KB`, none of 419 rows in the live
    database is truncated.
  - Tests: `tests/test_logs_sync.py` (16), plus three browser runs of `docs/tasks/8/verify-*.py`
    (19/19, 12/12, 6/6). Numbers were measured in headless Chromium **on the server**, not on the user's machine.
  - **Requires an Orchestra restart.** Until then `/api/logs/sync` returns 404, `__session` does not arrive,
    and the dashboard behaves as before while noting it in the console.
  - **Known tradeoff:** history is stored as plaintext in the browser profile, a deliberate trade on a
    personal machine. The mirror depends on **`logs` immutability**; the first `UPDATE logs` would make it
    silently lie. A comment on `add_log` records the invariant; there is no test for it.
  - **Triggered case:** measurement #2 found agent switching took 826 ms, including 172–446 ms merely to render
    100 messages (`marked.parse` + `DOMPurify` + `hljs`), while the network delivered the batch in ~15 ms.

### Fixed
- 🔁 **Background polling no longer opens a second stream containing complete history** (`app.js`, `_chatLoading`).
  `refreshSessions` contains `if (!eventSource) connectSSE()`. While `_showChatFor` waited for IndexedDB,
  `eventSource` was null, so the three-second poll could open a stream with `after_id=0`; the server then sent
  the entire history over a second, uncompressed stream. A flag and `finally` prevent the recovery `connectSSE`
  from being blocked forever.
  - **Triggered case:** it did **not fail on every run**—12/12 passed, then three failed on the next run.

### Removed
- ♻️ **The #2 chat DOM cache lived for one day and was removed** (`bcb86b6` → replaced in #8). A `Map`
  of detached `DocumentFragment` objects (eight-agent LRU) reduced switching from 826 ms to 30 ms with zero
  messages redrawn, so it **worked**. It was removed not because it was bad, but because the IndexedDB mirror
  solves the same problem together with network and history; two switching implementations cannot coexist.
  - The lasting lessons from #2: **cache the rendered DOM, not the network response**—reparsing JSON is cheap,
    rendering is expensive—and retain **the complete invalidation list** (session recreated under the same name,
    scope change, compact/normal, navigation away mid-stream, unconfirmed own message). It applies to any client-side
    chat cache. Analysis: `docs/tasks/2/report.md`.
  - **Time-consuming trap:** live :8888 serves static files from the MAIN checkout, not the worker's worktree.
    JavaScript changes on a worker branch are invisible in the live frontend, with no error—the “fix simply does
    not work.” Test the frontend through `page.route('**/static/js/app.js', …)`.

## v2.31.0 — 2026-08-03 — #1/#4/#5/#6/#7/#10/#14 dashboard stops lying and losing input

A batch of seven parallel tasks with one shared trait: **the system knew the truth but remained silent
or displayed an invention**. Every change makes unknown state look unknown.

### Added
- 🔑 **`OWNER_MODE` decouples “our data in the dashboard” from “require login”** (`app/auth.py`,
  `is_owner_mode()`; `app/routes/proxy.py`, `app/routes/system.py`, `app/static/js/app.js`,
  `.env.example`). The usage bar, proxy panel, and Claude profiles are shown to the owner.
  - Default = old behavior: **without login, the machine is considered ours** (development laptop);
    **with login, it is considered a client's**. `OWNER_MODE=1` overrides both.
  - Tests: `tests/test_owner_mode.py` (+103).
  - **Triggered case:** login is enabled on our VPS because it has a public address, but the data are ours;
    the old logic hid the owner's own quotas.
- 💵 **`SUBSCRIPTION_COST` is the real subscription price as a free-form `.env` string** (`app/routes/system.py`,
  `app/static/js/usage.js`). It is free-form because a plan is not necessarily one number (`$200+$20/month`).
  **Unset → no row at all.**
  - **Triggered case:** the panel contained hard-coded `₽100+₽100/month`, the only REAL number among
    API-equivalent estimates, and it had already become wrong. An invented value among calculated values is
    indistinguishable from a real one, so blank is better.

### Fixed
- 📉 **Quota snapshots no longer lie when a provider is silent** (#4, `app/routes/system.py`).
  Before: `snapshot_codex = codex_data or _codex_usage_cache.get("data")` gave a silent provider's snapshot
  **the last known value with a new timestamp**, drawing a flat line where no data existed. After: three
  distinct states—key absent (not configured) / `{"windows": [], "status": "unavailable", "error": "..."}`
  (asked, no answer) / numbers (answered).
  - **Answer to the user's question, “where did July's Codex history go?”: it was never written and cannot
    be recovered.** Measurement on a read-only copy of the live database: from 05.07–02.08, 6,400 rows had
    empty `provider_usage` in **100%** of cases; from `2026-08-03T06:29:27Z` onward it is populated in 100%,
    and at `07:02:20Z` the `codex` key appears. Two sharp boundaries, not degradation. The hypothesis that
    “migration broke it” was **inverted**: migration did not stop recording; it started it. Every store was
    checked (`usage_snapshots`, `turn_usage`, `usage_cache.json`, journald); the data are nowhere, and the
    provider API does not expose history.
  - “Limit reached” ≠ “no data”: `utilization: 100` is a provider response, not silence.
  - **Known remainder:** `_renderSparklines` draws one `polyline` through every point, so a one-day gap still
    becomes a straight line. The data contain `status=unavailable`, but it does not break the line.
- 🖼 **Pasting an image no longer erases typed text** (#5, `app/static/js/app.js`).
  Before: `input.value = oldText + '\n' + data.path` after `fetch` returned overwrote everything typed during
  upload. After: the field is only **appended to**, and caret position is restored (`setSelectionRange`).
  - **Send waits for the image:** `sendChat` awaits any unfinished upload (`_trackUpload`, 60-second timeout),
    the button shows `⏳`, and the field remains editable. Previously the message was sent without the image,
    then its path was appended to the already-cleared field as an orphaned line for the next message.
  - **Upload failure is no longer silent:** the old `catch { input.value = oldText; }` restored stale text;
    a JSON response without `path` did not even enter catch, leaving `⏳ uploading image...` forever. All four
    branches were tested (nginx 413 with HTML body, application 400 with JSON, disconnect, 200 without `path`).
    The exception class is printed deliberately: `TimeoutError` and some network errors have an empty `message`.
  - **WebP q=0.9 instead of PNG for clipboard paste:** 683 KB → 354 KB (1.9×, PSNR 38.6 dB), reducing 8.3–12.9 s
    to 4.3–6.7 s on the user's 53–82 KB/s link. Two unexpected measurements: the browser PNG encoder **inflates**
    the file (667 → 898 KB), and lossless WebP in Chromium exceeds the source PNG. Guardrails: clipboard paste
    only; files under 100 KB remain unchanged; WebP no smaller than the original → send original; any encoding
    error → original.
  - **Known tradeoff:** the format is now `.webp`. Claude agents read it natively; other runtimes were not tested.
    The remedy is a one-line change from `image/webp` to `image/jpeg` in `_compressScreenshot`.
  - **Triggered case:** the user's complaint that “images take fucking forever to upload; can I keep typing while
    they do?” revealed two problems. The unreported one—lost text—was more severe: input was not blocked, it was
    overwritten, losing 15–30 seconds of typing.
- 🚧 **A false reboot overlay no longer blocks the dashboard** (#6, `app/static/js/app.js`,
  `_onFetchFail`, `_dismissRebootOverlay`). A request timeout means the server is **slow**, not dead:
  under disk load, `/api/models` can take over two seconds while the service remains fully operational.
  `TimeoutError`/`AbortError` no longer count as a crash. A genuinely dead server still raises the overlay
  (`TypeError` on connection refusal or 502+ through the proxy).
  - Added a “Close and continue working” button and an exit from `_pollReconnect`. If the overlay still appears
    incorrectly, it is no longer an inescapable trap (the `while (true)` loop reloaded the page even after closing).
- 🩺 **Git errors are no longer disguised as “branch missing”** (#7, `app/workspace.py`, `_inspect_branch_ref`).
  Git exits 128 both when a directory is not a repository and when it **refuses to work with it** (dubious ownership,
  unreadable `.git`). Asserting the first hid the second and sent callers looking for branches that existed. Every
  `show-ref --verify` in `resolve_base_branch` and `merge_worktree_to_main` now uses one helper: git failure → git's
  error text, not an invented diagnosis.
  - `scripts/migrate_agent.py` no longer swallows `sqlite3` errors, gained a binary preflight and automatic dubious-
    ownership fix, and no longer places migrated files outside the service user's ownership.
- 📊 **The usage panel no longer hides failure behind a placeholder** (#10, `app/static/js/usage.js`). `Collecting data...`
  appeared both before collection started and after a request failed, although these are different states.
  It now shows gray “No snapshots yet” versus yellow “History failed to load — `<class>: <text>`.”
  - The one-year history request has its own 30-second timeout (`AbortSignal.timeout`). The general `api()` timeout
    of five seconds was designed for small responses and fired **before the response arrived**, while an empty `catch`
    hid the failure. Measurement on 03.08: 8,403 rows, 4.29 MB.
  - Tests: `tests/test_usage_history_frontend.py` (+112).
- ⚙️ **Background jobs work on kernel 6.8** (#14, `app/pidfd_exec.py`). `PIDFD_SIGNAL_PROCESS_GROUP` exists only
  since Linux 6.9; older kernels reject the flag with `EINVAL`, killing **every** background job on such hosts.
  Added a pidfd-bound `_send_group_via_killpg` fallback: until the leader is reaped, its pid cannot be reused, so pgid
  still names OUR group. If `pidfd_pid()` returns 0, the group is considered gone rather than signaling a stranger.
  Capability is **probed through the syscall**, not inferred from the version (`group_signal_supported()`).
- 🧪 **Tests no longer depend on whose machine runs them** (#14, `tests/conftest.py`, `_hermetic_dashboard_env`
  autouse fixture). Two leak sources must both be stopped: the systemd unit supplies `EnvironmentFile=.env`, so
  `DASHBOARD_USER` already exists in `os.environ` even in a clean clone without `.env`; and `lifespan` calls
  `load_dotenv()`, restoring it after any prior cleanup. With auth enabled, every `/api/` request returned 401:
  **green on CI, red for the owner**. A test dependent on someone else's environment is worse than red—it cannot reproduce.
- 🎭 **CI installs the browser** (`.github/workflows/ci.yml`). `uv sync` installs the Playwright package but not browser
  binaries. Without `playwright install --with-deps chromium`, every browser test **silently skipped**, leaving CI green
  while proving nothing about the frontend.

### Changed
- 🗄 **Agent logs are never deleted** (`app/db.py`, `app/manager.py`). The retention timer is gone, and
  `cleanup_old_logs` now **fails when called** instead of silently cleaning—fail loudly rather than lose data
  irreversibly. The same append-only log property is the foundation of the #8 mirror.
- ⏳ **When status is RUNNING, `merge_worker` explains why and waits for the outcome** (`app/mcp_stdio.py`)
  instead of blindly retrying.
- 📌 **`uv.lock`: removed `exclude-newer`.** Local uv 0.11.28 deletes these lines on every run, so they
  generated diff noise without pinning anything.

## v2.30.2 — 2026-08-03 — rules and prompts: foreign machine, rollbacks, environment migration

No code changes, but every agent in every project reads this, so it belongs here.

### Changed
- 🧹 **The “Traps” section of `CLAUDE.md` was rewritten for meaning** (`docs/tasks/claude-md-cleanup/`):
  60 items in four groups → 56 in eight, ordered by frequency of use (evidence checks first, hardware last).
  The file deliberately **grew** by 1,174 bytes: three rules returned and wording that had been shortened past
  the point of meaning was expanded.
  - **Triggered case:** “Codex truncates `AGENTS.md` at 32 KiB” was correct as a DEFAULT but false for the active
    configuration (98,304 locally, 65,536 on VPS). Half a day was spent cutting live rules for a nonexistent limit.
    General rule: **before relying on a documentation claim, verify it against config with one command.**
  - Before each deletion, the mechanism was searched in code. Removed text remains verbatim in
    `docs/archive/sessions/2026-08.md` rather than being erased. The `.gitignore:9-10` workaround is LIVE, so the
    `!docs/workers/` rule was restored.
  - ⚠️ No external review (Codex quota unavailable until 08.08): the only change to a file shared by every agent
    that received no second opinion.
- 🧯 **Prompts: do not put large files in `/tmp`** (`pipelines/default/prompts/modules/research-method.md`,
  `roles/full-cycle.md`). “Run in /tmp” became “run in scratch scripts” plus an explicit `findmnt /tmp` check.
  - **Triggered case:** on the laptop `/tmp` is **tmpfs, i.e. RAM**. A worker placed 1.6 GB of “disk files” there,
    taking memory from agents competing for it at the same time. `CLAUDE.md` contained the right rule while the role
    prompt said the opposite—and **the worker follows the prompt**.
- 📦 **Rules from #129** (`CLAUDE.md`, `docs/archive/sessions/2026-08.md`): group B moved to the archive; new rules
  cover two-pass documentation of a period and validation of rollback SHAs (`--is-ancestor` proves reachability,
  not revertibility; run `git revert --no-commit` in a scratch checkout).

### Added
- 🚚 **Instructions for transferring the environment to the VPS** (`docs/HANDOFF-from-laptop.md`, `docs/tasks/131/`).
  The production environment is running at `https://orchestra.seedon.ru`: 4 GB swap with `swappiness=10`, memory
  priorities (`oom_score_adj` 800 for Orchestra, −900 for tinyproxy), updated code, and a migrated database schema
  (`turn_usage`, `tool_errors`, `merge_operations`, `improvement_rules`, `voice_costs`—all five created). The local
  environment was untouched (85 laptop sessions).
  - **`OOMScoreAdjust` applies only on restart, while memory limits apply live:** systemd changes the cgroup without
    restarting. Verify `/proc/<pid>/oom_score_adj`, not `systemctl show`, which always prints the configured value.
  - **`uv sync` without `--extra rag` silently removes RAG** while leaving `RAG_ENABLED=true` in `.env`, making the
    configuration contradict itself. Every deployment must use `uv sync --extra rag`.
  - **Found but unfixed defect:** bootstrap ignores `WORKSPACE_DIR` and tries the default `/workspace/project`
    (`Bootstrap: cannot create workspace ... exit status 1`). It does not affect operation; the service starts.
    The warning also appeared in the pre-update July journal.
  - **Triggered case:** `git stash`/`fetch` failed under the service user with
    `insufficient permission for adding an object to repository database .git/objects`. Half the directory belonged to root (295 `.git` files, 3,021 tree
    files) while the unit had `User=kesha`. Foreign owners do not prevent reading or startup; only WRITING `.git`
    fails, midway through deployment.

### Known issue
- ⚠️ **Do not replace the system-prompt preset with `type: "custom"`** (`docs/tasks/125/research.md`).
  The preset was inspected and is not a black box, but it carries live harness behavior (tool guidance, destructive-
  action safety, `file_path:line_number`) that we would not reproduce and would silently lose on replacement.
  `exclude_dynamic_sections` provides a cheap targeted gain instead.
  - A side finding from the same research was the post-compaction role bug fixed in v2.30.0 (#126).
  - Measured injection-turn cost: `input_tokens ≈ 271,722` versus `34` for an ordinary turn (n=30 versus n=1,359).
    The system slot is cached; the user slot arrives as fresh text.

## v2.30.1 — 2026-08-03 — #12 spawn no longer dirties the worker tree

### Fixed
- 🧹 **The platform never overwrites files tracked by the repository** (`app/workspace.py`, `app/prompting.py`).
  New `workspace.tracked_paths(worktree, rels)` is the only way to ask whether a path is in the index; if git cannot
  answer, it raises `RuntimeError` rather than guessing. `create_worktree` skips tracked `copies`,
  `inject_skills_to_worktree` skips tracked `.claude/skills/<n>/SKILL.md`, and `sync_agents_md` uses the same helper.
  `_exclude_claude_dir` became `_exclude_worktree_artifacts(wt, extra)`: copies actually created and symlink targets
  (`.env` and others) now add themselves to `info/exclude` as anchored `/<path>` entries, removing per-repository manual edits.
  - **`info/exclude` cannot protect tracked files:** ignore rules do not apply to the index. The `AGENTS.md` mirror had
    a safeguard while skill injection did not, so the symptom existed only where skills were indexed: seedon had 14
    `.claude/skills/*` files; Orchestra, dnd-game-master, and kesha-tg-bot had zero.
  - Behavior change: in a repository that versions its own skills, the agent reads the **repository version** (Claude
    CLI already loads native skills from this path, and `_project_skill_files` already treated them as truth for Codex).
    Parent fallback for `CLAUDE.md` applies only to untracked files.
  - Tests: `tests/test_workspace.py` (+3), `tests/test_manager.py` (+1). All four were mutation-checked and fail with
    the fix stashed. Analysis and decision cost: `docs/tasks/12/report.md`; no cross-LLM verdict due to subscription
    limits: `docs/tasks/12/codex-review.md`.
  - **Triggered case:** six consecutive seedon branches failed to merge. `merge_worker` returned
    `worker working tree is dirty (.claude/skills/codex-debate/SKILL.md, .env)` although the workers never touched
    those files; the orchestrator manually repaired `info/exclude` in each project.

## v2.30.0 — 2026-08-03 — #126 role survives context compaction

### Fixed
- 🧠 **The role returns to the prompt after compaction** (`app/session.py`, `compact()`). The successful compaction
  path now sets one flag, `self._prompt_injected = False`, adding seven production lines.
  - **The failure point is not “after compaction” but the first reconnect after compaction.** The wording matters
    for search: immediately after compaction the agent is still alive and remembers its role. The failure happens
    later: successful `compact()` moves the session to a new native `session_id`; the next startup is a **resume**,
    and resume receives no `system_prompt` (`backend_claude.py:165-168`). An hour may separate these events.
  - The flag resets ONLY on the successful branch. Failure branches (`compact()` retry, acknowledgment timeout,
    quota) restore the **previous** session whose prompt remains live. Resetting there would cost an extra ~270k
    input tokens on every failed compaction.
  - Tests: `tests/test_session.py` `TestCompactReArmsPromptInjection`, three cases (+160). The third is end to end:
    it verifies that the first turn on the resumed backend actually contains the role text after compaction, not
    merely that “the flag changed.”
  - **Triggered case:** after compaction, a worker stopped behaving like a worker—it lost pipeline phases and role
    rules. Diagnosis came from `~/.claude/projects/**/*.jsonl` (`compact_boundary` records plus the
    `PREVIOUS CONTEXT SUMMARY` preamble), with zero paid calls.

### Known issue
- ⚠️ **Native compaction with a custom prompt is unreachable** (`docs/tasks/125/research.md`, `docs/tasks/126/research.md`).
  We tested delegating compaction to the Claude runtime while supplying our own `COMPACT_PROMPT`, but the API exposes
  no such seam. This also disproved the argument that “at least the warm cache survives”: `cache_read=0.889` was measured
  on the **injection turn of the current path** (appending at the tail preserves the prefix), not on the proposed operation
  of sending `system_prompt` on every resume, which risks invalidating the entire prefix. The number measured what would
  be replaced, not what was proposed.

## v2.29.0 — 2026-08-02 — #106 new compaction prompt

### Changed
- 🗜 **`COMPACT_PROMPT` was replaced by the `hot_state_ledger` bundle** (`app/session.py`, around line 1184).
  Seven old sections (INTENT/DECISIONS/FILES/PENDING/RECENT/BUGS/IMPORTANT CONTEXT) became four typed sections
  (TASK STATE / DECISIONS / BLOCKER-NEXT / CONSTRAINTS), plus rules to never claim an action without evidence and
  never assert a negative (`no evidence of X`, not `X did not happen`). Codex sessions are unaffected; they use
  `_compact_codex_context()`.
  - Selection used four evaluation rounds with preregistered gates and judging, `docs/tasks/106/q6/`; 7/8 gates PASS.
  - **Rollback: `docs/tasks/106/rollback.md`:** `git revert --no-edit f796a08` plus restart. The prompt is reread on
    every `compact()`; no migration or data depend on it. The file contains a per-property “what regression looks like” table.
  - ⚠️ `rollback.md` itself names SHA `8b5392d`, a **pre-squash worker commit unreachable from `main`**;
    `git revert 8b5392d` will not work there. The actual squash commit on `main` is `f796a08`.
- 🗑 **Removed `_ORCH_PRESAVE`**, the block that ordered the orchestrator to update `CLAUDE.md`, `TODO.md`, and `BUGS.md`
  before EVERY compaction. This is an intentional behavior change, not a side effect: **orchestrators no longer auto-save
  notes during compaction**. Durable facts are now written explicitly as a session proceeds.

### Known tradeoff
- ⚠️ **The headline number is not confirmed in production.** The recent-recall gain (**+75.66 pp**) came from a
  harness where `run_evaluation.py` called postprocessor `compose_handoff()`, which mechanically appended the latest
  three user messages, tool ledger, and file diff AFTER model output. **The appender produced 100% recall, not the prompt.**
  Production has NO such postprocessor: `compact()` concatenates only the model's own text.
  - Therefore the candidate phrase “the runtime will append the tail and ledger” did not ship; it promised a block that
    would never arrive. It was replaced with “preserve the latest three user messages verbatim.” The model is instructed
    to do what the harness guaranteed structurally. Every other rule shipped byte for byte.
  - **Confirmed in production** (these rules shipped unchanged): unrelated file writes **218 → 0** across 63 measured
    outputs, false claims about file actions **8 → 0**, handoff size **−61.4%** (median ~2.0 KB, 38.6% of the old size).
  - **Not confirmed in production:** recent-recall gates G1 and the recent half of G8. An honest closure would port
    `compose_handoff()` into `compact()`; that exceeded the approved scope and **was not done**.
- ⚠️ Of six changed prompt rules, five are tied to a measured number. The sixth (`UNKNOWN — source gap`) shipped inside
  the bundle and was not isolated separately, so its specific contribution is unknown. This is recorded explicitly to
  avoid inventing a neat causal story (`docs/artifacts/compact-prompt-q6-106.html`).

## v2.28.0 — 2026-08-01 — #93/#111/#114 lifecycle, Codex hibernation, bug inbox

### Added
- 💤 **Codex worker hibernation** (`app/backend_codex.py`, `app/session_hibernate.py`, `app/runtime_registry.py`, #111).
  After normal idle time (300 seconds for a worker, 600 for an orchestrator), a Codex worker releases its complete
  app-server + MCP process scope and returns to **the same native Codex thread** on the next message. Manual route:
  `POST /api/sessions/{name}/hibernate`.
  - Processes start in a unique transient user scope. Before enabling hibernation, the system verifies `Linger=yes`,
    actual user-scope attachment, ownership of the unified cgroup, and readability of `cgroup.events` from inside a
    disposable scope. Failed verification → direct launch with `hibernate_safe=False` in the log.
  - Backend ownership is retained until successful teardown. A substituted thread id is rejected BEFORE sending a turn.
    Running/waiting/pending/compacting states return conflict rather than disconnecting.
  - Current capability matrix: `claude` and `codex` have `hibernate=True`; `grok` and `opencode` have `False`
    (`app/runtime_registry.py`).
- 🐞 **Bug-report inbox outside the working tree** (`app/routes/system.py` `_bug_state_root`/`_publish_bug_record`,
  `deploy/orchestra.service.template`, #114). Records are published to a private `bug-inbox/` (`0700`) inside the
  service state directory (`$STATE_DIRECTORY`), not checkout `BUGS.md`. One report = one immutable file in `records/`
  (`0600`); publication is an atomic rename after `fsync`, and readers ignore temporary files.
  - The entire candidate path is validated: `lstat` on every component; reject worktrees, `.git`, bare repositories,
    and symlinks inside them; recheck with `git rev-parse` in an environment without inherited `GIT_*`. An unsafe path
    is a service error, NOT a reason to write into the checkout. Blocking writes run in `asyncio.to_thread` so a long
    report or `fsync` cannot stall the event loop.
  - **Triggered case (this is Changed, not cosmetic):** `report_bug` wrote to checkout `BUGS.md` and left the tree dirty.
    After the fail-loud clean-target check (#90 T2), any incoming bug report **blocked EVERY merge** until a person
    committed someone else's file. It happened five times in one day.
- 🔔 **Unread bug-report banner in the dashboard** (`app/static/js/app.js`, `app/templates/dashboard.html`
  `#bug-report-banner`). A backend reader is insufficient; a person must notice the report without knowing its route.
  Read version is stored in `localStorage` (`orchestraBugInboxSeenVersion`); Markdown renders through `marked` + `DOMPurify`.

### Fixed
- 🔒 **Atomic spawn/switch/merge lifecycle** (`app/workspace.py`, `app/routes/sessions.py`, `app/manager.py`, `app/db.py`, `app/tm.py`, #93, four tickets).
  - **T1:** `create/merge/switch/remove` share one stable repository flock stored in the git common directory. Switch
    rollback uses CAS and fails closed. Merge returns typed commit-point snapshots and exact conflict paths.
  - **T2:** `execute_merge_session()` resolves id/name/scope/branch/head **once** and owns the chain
    `session → lifecycle → repo`; task lookup and CAS updates are project-scoped. A post-merge switch/task failure now
    returns as a partial result instead of disappearing.
  - **T3:** a worker remains invisible until worktree preparation and runtime startup finish. Repeated cancellation
    cannot break ownership of preparation, compensation, or finalization.
  - **T4:** HTTP, Telegram, background jobs, limit-wake, auto-reporting, and system routes converge on one
    `SessionManager.send()`. It rechecks `needs_switch` under the session lock, permits automatic switching only in
    IDLE, and preserves delivery to a RUNNING mid-turn session.
  - **Lock order is explicit** to prevent deadlock: manager session lock → `AgentSession._lifecycle_lock` → repository
    flock. There are no reverse edges.
  - Read-only verification on the **live** database: 383 sessions, 81 non-archived, nine active with
    `needs_switch=true`; all nine were IDLE with an existing worktree and resolvable base. Full run:
    **1,388 passed, 7 skipped**.
- 🛡 **Safe process termination** (`app/ssh_tunnel.py`, `app/bg_jobs.py`, new `app/pidfd_exec.py`, #120).
  - **Removed broad `pkill -f`** over a constructed pattern. It matched processes across the ENTIRE system, including
    the user's personal SSH sessions. **Measurement: three unrelated VPN-Service processes matched, versus zero useful
    matches in a month.** `grep pkill` under `app/` now returns zero matches.
  - **Removed `killpg` using a saved numeric PGID** after the leader exits. PGIDs are reused, so a signal could hit an
    unrelated new group. Replacement: pidfd identity (`app/pidfd_exec.py`).
  - Termination quality was retested rather than assumed: 100 shell-job iterations with a grandchild in the same group
    produced `grandchild killed with group: 100/100`, `unrelated process survived: 100/100`.
  - **Deliberately retained:** a narrow numeric TOCTOU inside `_kill_proc()` (the window exists only while
    `returncode is None`), moved to a separate task.
- 📋 **Task details appear consistently everywhere** (`app/mcp_stdio.py`, `app/static/js/app.js`, #113), and **chat
  restores at the last-read boundary** (`app/static/js/app.js`, `app/static/css/style.css`, #118); an anchor appears
  only when unread turns exist.
- 📊 **Stale statistics refresh on demand** (`app/static/js/usage.js`, #112).
- 🧰 **Typed MCP error contract** (`app/mcp_stdio.py`, #116 T5): a transport/domain failure becomes one envelope at
  the shared HTTP/MCP boundary. Partial success remains a domain result; optional failure becomes an explicit warning.
  Motivation: defects where the system knew the cause but remained silent (`Send failed: network error:` followed by
  empty text from stringifying `httpx.ReadTimeout`).
- 🔁 **RAG backfills are retained and coalesced** (`app/rag_service.py`, `app/routes/sessions.py`, #116 T7).

### Added (Telegram)
- 📱 **`/limits` command in the bot's private chat** (`app/tg_bridge.py`, #109). Shows independent remaining Claude 5h,
  Claude 7d, and Codex primary quotas, with each reset as absolute Krasnoyarsk time (UTC+7) and relative duration.
  - Access is limited to the configured group's `creator`; administrators and members receive `⛔ Access denied.`
    **before** data loading. Missing sender, missing group, or request failure all fail closed.
  - `extra_usage.spend_limit_reached` appears as a SEPARATE fact with a warning that base windows are independent—the
    exact case where a limit flag had already been misread as a provider verdict.

### Removed
- 🗑 **The entire private `tasks-pm` pipeline** (`pipelines/tasks-pm/`: 17 files, `app/pipeline.py`, #118), removed by
  owner decision. Basis: **zero sessions** used it and eight audit findings were solved by deletion rather than repair.
  Only `default` remains under `pipelines/`; no `tasks-pm` references remain in `app/`.

### Changed
- 🧭 **Worker default is Opus based on quota headroom** (`pipelines/default/pipeline.yaml`, `pipelines/default/prompts/`).
  Every role in the `default` pipeline currently uses `claude-opus-5[1m]`. The `<model-routing>` block in the system
  prompt is the sole routing source of truth; selecting models by worker names, old session models, or historical shares
  is explicitly forbidden.
- 🔐 **Restarts and deployments require explicit authorization** (`pipelines/default/prompts/base.md`,
  `git-workflow`/`orchestration`/`self-improvement` modules, `full-cycle` role, `vps-deploy`/`codex-debate` skills).
- 💵 **Prompt prices use exact units, not thousands** (`pipelines/default/prompts/modules/orchestration.md`): the phrase
  “in thousands” risked a 1,000× error.
- 🔎 **`search_memory` is a deterministic first action** (`pipelines/default/prompts/modules/memory-search.md`), not
  “remember to do this if you feel like it.”
- 🧱 **Worker lifecycle is stated before kill** (`app/manager.py`, `orchestration` module): a full-cycle agent at a gate
  is ALIVE and waiting for the next phase; only one-shot agents may be killed.

### Known issue
- ⚠️ The #113 orphan detector is a one-time process-age snapshot immediately after job completion, not continuous
  monitoring. It deliberately kills nothing (`orphan_tree=1 … observation_only=true`).
- ⚠️ #113 proposed three memory optimizations and **withdrew all three after measurement**: batch 64→16 changes
  embeddings deterministically (max `|Δ|=0.0296734`, min cosine `0.9718105`); a separate embedder process saves at most
  0.21 GiB time-weighted; an automatic reaper hits the same stale-PGID problem. The memory owner was still established:
  the bge-m3 ONNX embedder holds **0.8900 GiB PSS+SwapPss**, and unload+trim returns 91.90%.
- ⚠️ #121 (Agent Reach): the claim was tested and **disproved**; deployment is not recommended, and Orchestra code was
  unchanged (`docs/tasks/121/research.md`). Separately, launching Hiddify does not fix Reddit; every live proxy returns 403.

## v2.27.0 — 2026-07-31 — #108 overengineering audit: dead-code cleanup

The audit found a **healthy** foundation: overengineering was not a systemic style. Three suspects
were cleared—`backend_protocol.py` (a genuine protocol with four implementations plus fail-loud
validation in `build_backend`), `session_state.py` (breaks a real import cycle), and
`usage_analytics._provider_case` (already generated from one `PROVIDER_METADATA`). The real excess was not
architecture but **residue from removed features**. Result: 429 fewer production lines; full run
1,270 passed / 0 failed. Details: `docs/tasks/108/`.

### Fixed
- 🔇 **Prompt-block construction failure no longer pretends to be an empty list** (`app/manager.py`
  `_other_orchestrators_block`, `_workers_block`). Both were wrapped in `except Exception: return ""`, so any database
  error silently gave the orchestrator a system prompt WITHOUT its workers and other orchestrators.
  - An agent reads an empty block as “there are no workers” and **spawns duplicates** instead of reusing live ones.
    The failure is invisible and looks like “the agent is being stupid.”
  - Evidence: enclosing `ROLE_SYSTEM_PROMPT` says “Fail loud: … → ValueError” in its own docstring and does raise;
    the silent inner `except` contradicted the function's own contract.
  - Now: `logger.exception` with class and text, plus explicit `⚠️ … unavailable` and a workaround (`list_agents` /
    `list_orchestrators`) instead of `""`. The path does NOT fail: prompt construction is used by spawn/resume, so one
    corrupt row must not break recovery of every session. `except` is narrowed to `sqlite3.Error/KeyError/TypeError`.
- 🪵 **Nine silent fallbacks gained logging** (`app/tg_bridge.py`, `app/session_turns.py`). Control flow is unchanged;
  only logging changed (verified: removed diff lines contain only `except` headers, no `return` or `pass`).
  - Most important: `_md_entities` failure degrades **every** formatted TG message to plain text. It previously produced
    no log line and looked as if “Telegram decided to do that.”
  - Others: mirror-send ×2 (aligned with adjacent sites that already logged), tool-argument parsing ×4
    (Read/Grep/Bash/Glob), `spawn_worker` header, Local Bot API health probe (all ten attempts omitted WHY), and parsing
    `resets_at` in the quota line.

### Removed
- 🗑 **The entire spawn-queue subsystem** (`app/manager.py`, `app/db.py`, `app/routes/system.py`, `app/mcp_stdio.py`).
  It was a producer/consumer system without a producer: every startup made `start_background_tasks()` launch a coroutine
  that waited forever on `_spawn_queue.get()`, while nobody called `enqueue_worker_spawn`.
  - Archaeology: `e9b4e7f` (2026-06-02) moved `spawn_worker`/`kill_worker` from the queue to synchronous HTTP, but left
    the infrastructure behind. Tool `list_jobs` existed so an agent could learn the result of ITS OWN spawn; synchronous
    spawn leaves nothing to wait for.
  - Consequently, the only `update_job` calls lived INSIDE the dead loop and the only `INSERT INTO jobs` lived in dead
    `add_job`. A table without a writer, `list_jobs` always returned “No jobs,” and the production database had zero rows.
  - **There were seven copies of `list_jobs`, not two:** two tool registries, four in `app.js`, one `SKILL.md`, and
    **two prompt files** (`pipelines/default/prompts/`). Prompts were an unexpected third class of copy.
  - The dashboard is unaffected: its JOBS tab reads `/api/bg/jobs`, backed by a **different**, live `bg_jobs` table.
- 🗑 **The `inbox` table** had the same disease: `add_inbox` was dead, while `get_inbox`/`ack_inbox` were called by a
  live route guaranteed to return `[]` forever.
- 🗑 **Ten symbols with zero references** (−112): `db.kv_set`, `db.bg_get_active_for_scope` (duplicate of
  `bg_get_jobs(active_only=True)`), `db.usage_get_latest_provider_usage`, `models.register_provider_metadata`,
  `prompting.roles_catalog` (orphaned after `_roles_catalog_from_manifest`), `rag.apply_file_change`,
  `tm.get_project_prefix`, `tm.get_pending_syncs`, `tg_bridge._edit_expandable`, `tg_bridge._find_thread_for_scope`.
  Plus `manager.find_worker`/`find_session_id_by_name`/`unload`, fragments of the same `e9b4e7f` change.
- 🗑 **Three dead routes** (−111): `/api/open-file` (near-duplicate of `open_folder`), `/api/git-status` plus orphaned
  `_git_status_cache`/`_GIT_STATUS_TTL`/`_run_git`, and `/api/usage/daily{,/agents}` (superseded by
  `/api/usage/analytics`; `usage_daily_agents` contained the file's worst SQL—a manual `_conn()` and `c.close()` without
  a context manager).
- 🗑 **Runtime-registry plugin loader:** `load_runtime_plugins`, `_PLUGINS_LOADED`, `ORCHESTRA_RUNTIME_PLUGINS` were
  configured nowhere, yet `get_runtime()` called the loader on every resolution. The registry and four built-ins remain.
- 🗑 `db.rename_session` (shadowed by a same-named route that builds its own UPDATE), `db.usage_cleanup_old` (its only
  “reference” was a comment about its removal), and `TG_WORKER_TOPICS` from `.env.example`.

### Changed
- ♻️ **Shared JSON-RPC transport for Codex and Grok:** new `app/backend_jsonrpc.py` (`JsonRpcStdioTransport` plus
  canonical `bounded_tool_arguments`).
  - Basis: measured `difflib` similarity, not visual judgment—`_write` 0.97, `_request` 0.94, `_notify` 0.93,
    `is_alive` 1.00, `_drain_stderr` 0.86. Exactly two things differed and became `RUNTIME_LABEL` and
    `JSONRPC_ENVELOPE`. `_bounded_tool_arguments` and `_bounded` were one function with one docstring under two names.
  - **The boundary was deliberately not crossed:** `connect`, `send`, `_read_stdout`, `_turn_completed`, `_build_env`,
    and `_classify_error` are untouched; the same measurement gives 0.06–0.37, a legitimate semantic difference.
    Extract transport, not meaning.
  - Behavior was verified rather than assumed: error text remains runtime-specific; only Grok uses the
    `{"jsonrpc":"2.0"}` envelope; **JSON key order matches the original byte for byte** (some JSON-RPC servers care).
- 🎨 **JavaScript dictionaries have one source** (`app/static/js/app.js`). The background-job icon dictionary existed
  four times (three inline plus canonical `_JOB_ICONS`), and statuses twice. Inline copies now reference constants.
  TDZ safety was tested with a case under `node` rather than inferred. An inline copy of `_escHtml` was replaced by `_escHtml`
  itself because their bodies were byte-identical.
  - The canonical choice between `escHtml` (DOM-based, escapes quotes) and `_escHtml` (string replacement, does NOT
    escape quotes) was **left unchanged**. They are not equivalent; mechanical replacement could cause an XSS regression.

### Known issue
- ⚠️ **`_hydrate_row` and `_load_from_db` have diverged** (`app/manager.py`), two database-row-to-`AgentSession`
  mappers. The first sets `_last_context["max_tokens"] = 0`; the second reads `get_model_spec(...).context_length`.
  The same session receives a different context limit depending on its load path. Given the prior `ctx=100%` and three
  extra compactions, this is a plausible real defect. Tracked separately; not changed in #108.
- ⚠️ `jobs` and `inbox` remain empty orphan tables in existing installations. Their schemas were removed from `db.py`,
  but `CREATE TABLE IF NOT EXISTS` does not delete existing tables. No `DROP TABLE` migration was added because they hold no data.
- ⚠️ Production `.env` defines `KESHA_INBOX_URL`, but no line under `app/` reads it. The file is outside the repository;
  the owner must decide its fate.

## v2.26.8 — 2026-07-28 — #98 task numbers vs docs/tasks

### Fixed
- 🔢 **`task_create` no longer issues a number whose `docs/tasks/<n>/` directory already exists** (`app/tm.py`
  `_next_par`). It previously used only database `MAX(par_number)+1`; deleting a task returned its number to the pool
  while disk artifacts remained, so new research inherited someone else's `#96`.
  - After the database maximum: `while (scope/docs/tasks/<n>).is_dir(): n += 1`. The root comes from
    `tm_projects.scope`, like the project, not a hard-coded path.
  - Explicit `par_number=` for imports/migrations remains untouched.
  - **Triggered case:** `task_create` issued `#96` while `docs/tasks/96/` from OpenCodeBackend (`3031c42`) was live;
    the worker stopped before writing. Tests: `tests/test_tm.py` (RED→GREEN).

## v2.26.7 — 2026-07-28

### Fixed
- ⏱ **TG bridge tests no longer flake under load** (`tests/test_tg_bridge.py`). At 21 sites,
  `asyncio.wait_for(..., timeout=0.1)` imposed a wall-clock window rather than a contract requirement. On a busy machine
  (three workers plus parallel runs), 100 ms was insufficient even to start the coroutine, causing a random test in the
  file to fail. The symptom was order-dependent: 6/6 alone, failures in 2/3 combined runs, with a DIFFERENT test each time.
  - Timeouts increased to five seconds. Test semantics are unchanged—they still fail if the event never occurs—but the
    threshold no longer depends on machine load. The file contains no tests expecting `TimeoutError` (verified), so this
    adds no fixed delay: file runtime 4.4 → 7.1 seconds.
  - **Triggered case:** the T7 worker, whose diff changed documentation only, received a red full run and correctly reported
    that the failure was unrelated. Reproduced on a clean tree: 2/3 runs failed on untouched `main`.
- 📎 **`send_file` no longer fails with an empty `network error:`** (`app/mcp_stdio.py`). Delivery uses the reliable TG
  queue, which waits through flood control; Telegram routinely returns `429 Too Many Requests: retry after 24` for an active
  group. The MCP client cut the connection at its 30-second timeout in the middle of that retry.
  - This call's timeout alone increased to 180 seconds; the general `_api` default remains 30 seconds, appropriate for other tools.
  - Error text now includes the exception CLASS. `httpx.ReadTimeout` stringifies to an empty string, so the report previously
    read `Send failed: network error: ` with no cause. Silent diagnostics are worse than none.
  - **Triggered case:** two consecutive failures sending a PDF application from seedon. After the fix, the same file succeeded
    on the first attempt (`msg_id=104346`). No restart was needed because MCP processes start fresh for each call.

## v2.26.6 — 2026-07-28 — #95 Grok T7: documentation

### Added
- 📗 **`docs/grok-field-guide.md`:** a runtime field guide paired with `codex-field-guide.md` (same genre and location;
  no new directory). It covers bootstrapping a worker, why each worker needs its own `GROK_HOME`, differences from
  Claude/Codex, money and context with both traps ($0.30 cache and the prohibition on `TOKEN_PRICES`), a **“symptom →
  file to fix” map**, a rule for the next runtime, and a registry of unverified claims.
- 📄 **`docs/tasks/95/report.md`:** final task report with nine latent bugs found along the way and the method that found them.

### Reasoning
- **The unverified registry is consolidated in one place** (guide §7), not scattered through the CHANGELOG. Every entry
  states not only what is unknown but HOW to verify it: terminal quota-exhaustion shape (capture `Grok raw error payload:`
  from the first real limit hit and branch `rate_limit` on a field, not substring), `type:"http"` for URL MCP (only `stdio`
  verified; `mcpCapabilities` claims http/sse, but claimed ≠ verified), and cache TTL (binary-search delays between turns
  in one session, using a cron job rather than an agent background process that dies when the turn ends).
- **`CLAUDE.md` grew by 1,515 bytes rather than 2,339.** New traps were written in English because Cyrillic costs two
  bytes per character and little room remained below Codex's 32 KiB limit. Final size 30,095 bytes, 2,673 bytes headroom.
  The traps contain only what an agent will actually encounter; the full explanation belongs in the guide.
- **The shared-code contract lesson is a rule for the NEXT runtime**, not a narrative: catch the exception class, not one
  encountered instance; test new calls against REAL values from the live database, not fixtures; `ELSE claude` is always
  a bug; search for the second copy.

## v2.26.5 — 2026-07-28 — #95 Grok T6: dashboard, TG, consistency

### Fixed
- 📊 **Grok spending was charged to the Claude pool** (`app/usage_analytics.py`). Bucketing was binary:
  `CASE WHEN codex/gpt-% THEN 'codex' ELSE 'claude' END`, so the trailing `ELSE` swallowed every new runtime. SuperGrok
  usage would look like Claude quota usage, while cache hits used Claude's TTL—the dashboard hid the very reason Grok existed.
  - The expression was duplicated in TWO places (`_PROVIDER_SQL` and an inline CASE in the CTE), plus a THIRD copy of the
    same binary assumption in the cold-start threshold (`CASE WHEN provider='codex' THEN ? ELSE ?`). One `_PROVIDER_RULES`
    table now generates both SQL expressions and TTL parameters.
  - **Verified on a copy of the live database** (330 sessions; original untouched): existing buckets did not change
    (Claude 650 turns / Codex 328); a synthetic Grok turn creates a separate bucket with its own cost and `approx=True`.
- 🚫 **A Grok orchestrator could not start at all** (`app/backend_grok.py`). We passed `--no-subagents` when
  `is_orchestrator=True`, but `grok agent` has NO such flag (it belongs to the top-level command), producing
  `error: unexpected argument` before startup. The defect was latent because no orchestrator had used Grok. Replaced with
  documented `GROK_SUBAGENTS=0`; both modes were verified with live connections.
- 🎨 **Three binary ternaries in the provider card** (`app/static/js/analytics.js`). `isClaude ? … : …` meant “not Claude
  → render as Codex”: a third pool would inherit Codex's title, window shape, and—through `_analyticsCapacity`—**someone
  else's quota**. A `_PROVIDER_META` table plus explicit `_PROVIDER_CAPACITY_KEY` now generates provider lists in cards,
  cache grid, and agent filter instead of repeating four literals.
- ⏱ **`cache_policy_for_runtime()` no longer promises an exact Grok TTL** (`app/models.py`). The default “everything that
  is not Codex → 3600/exact” claimed precision nobody measured. Grok now has its own `approximate=True` branch, so the
  dashboard shows “≈”. xAI does not document cache TTL and the runtime does not report it; measurement would require hours
  of wall-clock time and did not fit the task.

### Verified (using REAL data from a read-only copy of the live database)
Audit after the empty-`pipeline` incident: the new runtime expanded the shared-code contract, and legacy sessions could
not satisfy it. Run against the actual values from 330 sessions:
- `pipeline` is empty in 27/330, `profile` in 316/330, `task_id` in 243/330, and `base_branch` in **all 330**;
  `role`/`scope`/`backend_type` are populated everywhere.
- `_grok_factory` builds successfully for every real combination: empty pipeline, empty profile, both, nonexistent
  pipeline name, and an orchestrator with an empty pipeline.
- No session has an empty `cwd`, but **248/330 directories have already been deleted**, normal for archived workers.
  Behavior was compared with Codex: both fail; only readability differs—`RuntimeError: worktree removed or relocated?`
  versus bare `FileNotFoundError`. There is no runtime discrepancy.

### Tests
`tests/test_backend_grok.py` (70): the Grok bucket matches before all others while the tail remains `ELSE 'claude'`;
TTL CASE covers every known provider with registry values; Grok cache policy is marked approximate; provider ids match runtime ids.

## v2.26.4 — 2026-07-27 — #95 Grok T5: errors, interruption, quota

### Fixed
- 🚨 **A Grok worker could not execute ANY shell command—the turn was canceled** (`app/backend_grok.py`). In response
  to `session/request_permission`, we sent `optionId: "allow"`, an id I **invented** in T1 from ACP convention. The
  agent's actual options are **`allow-once` / `reject-once`**. The mismatch meant “nothing selected,” so the agent
  canceled the entire turn: `tool_use` and `tool_result` existed, command output had arrived, yet `turn_end` reported
  `ok=False stop=interrupted`. Externally this would look like “the worker mysteriously abandons tasks,” with no error line.
  - Approval is now **selected from the offered list** (`_pick_allow_option`), preferring a durable choice over a one-time
    choice. If no allow option exists, the result is explicit `cancelled` plus a log containing every option; no invented id.
  - A second layer adds `--always-approve` for managed workers, preventing requests entirely (verified:
    `client requests: NONE`). Fallback was tested separately with the flag removed: it selects `allow-once` and finishes
    with `ok=True`.
- 🧪 **Eliminated the `test_sandbox_config_write_is_atomic` flake** (`tests/test_backend_grok.py`). The test started
  threads and required a reader to **happen to observe** new content, making the test itself a race that failed about one
  in four full-file runs. It is now deterministic: observation occurs exactly when the temporary file is written and
  checks that the destination still holds the old COMPLETE content, with separate tests for `rename` and write skipping.
  Verification: 40/40 green file runs; mutating back to ordinary writing fails both tests, so they catch the regression
  rather than merely pass.

### Verified (measurements using the live CLI)
- **Process death mid-stream** → exactly ONE `turn_end` (`ok=False`, `stop_reason=process_exit_-9`,
  `model_error=server_error`); `events()` returns immediately and **already received text is preserved**.
- **Error after streaming begins:** text is preserved and success is not reported (`stream` → `error` → `turn_end ok=False`).
- **`interrupt()` during a long turn with an active tool:** succeeds; the turn closes as `interrupted` with one `turn_end`.
- **Reconnect after process death:** `session/load` restores the same session and preserves its id.

### Known issue
- **The terminal quota-exhaustion shape remains UNKNOWN.** We could not exhaust SuperGrok, so no pattern was invented.
  An unrecognized failure remains `error` and fails loudly. Added: **the raw payload is logged verbatim** (`logger.error`,
  up to 4,000 characters) both in the error stream and on `session/prompt` failure, so the first real limit hit leaves its
  actual shape in the log rather than our summary. Classification comes after that, not before.
- `report_bug()` is deliberately not called from the backend: it is an agent MCP tool, not a tool for the Orchestra
  process, and under the project's then-current traps it wrote into checkout `BUGS.md` and blocked merges. The backend
  equivalent is a loud log + `error` + `turn_end(ok=False)` without silent retry.

### Tests
`tests/test_backend_grok.py` (66): approval comes from the offered options; durable beats one-time; no allow option returns
`None` instead of an invented id; raw payload reaches the log; process death emits one `turn_end` while preserving text;
an error after streaming is not reported as success.

## v2.26.3 — 2026-07-27 — #95 Grok T4: usage/cost locked down by tests

Almost no code changed; nearly everything already worked after T1. The value of this slice is that every assumption was
verified rather than trusted: incorrect cost does not crash; it lies in the dashboard for years.

### Verified (measured using the live CLI and locked down by tests)
- 📏 **The `context_pct` denominator comes from the RUNTIME, not our constant.** Verified by replacing
  `GROK_CONTEXT_LIMITS["grok-4.5"]` with a deliberately wrong 12,345; after connection the window became 500,000 and
  `context_pct` used it. Equal constant and runtime values (both 500,000) would conceal a broken mechanism, so tests
  deliberately separate them. This is the exact Opus failure where `CONTEXT_LIMITS` lied about the denominator and the
  agent compacted at the wrong time.
- 🧮 **`turn_completed.usage` is PER TURN, not cumulative.** This differs critically from Codex, which accumulates over
  the thread and requires a delta. Measurement across three turns in one session: `outputTokens` 49 / 22 / 23 (cumulative
  would be 49 / 71 / 94); input is almost entirely cached. The payload is consumed as-is, `cost_is_delta=True` is correct,
  and delta machinery is unnecessary. This had previously been my UNVERIFIED assumption.
- 🧠 **`reasoningTokens` are not billed in addition to output.** A test compares turns with and without them at equal
  `outputTokens`; cost must match.
- 💵 **Currency was already correct; no change was needed.** `MODEL_COST_CURRENCY = '$'` (`app/static/js/utils.js`) is
  used for `cost_usd` and model pricing. `data-currency` (rubles for tasks and payments) does not enter this path. Grok
  follows the same route as Claude/Codex.

### Known issue
- ⚠️ **Grok prices are deliberately NOT registered in shared `TOKEN_PRICES`.** `routes/system.py:_cost_cached_for()`
  recomputes history for every model in that dictionary using the Claude cache heuristic (cache_read = 10% of input).
  Grok cache costs $0.30 versus $2.00 input, or 15%; on a real measured turn the heuristic overstates cost by **+27.6%**.
  While absent from the dictionary, the function returns the stored value computed from `costUsdTicks`. A test locks this
  down: an attempt to “register prices like Claude while we're here” will fail.
- Consequence: Grok does not show `price_input`/`price_output` in the model dropdown, like all Codex models for the same
  reason. A deliberate compromise, not a defect.

### Tests
`tests/test_backend_grok.py` (58): runtime window overrides the constant from both `initialize._meta` and `session/new`;
foreign list model is ignored; `context_pct` uses the runtime window; cached tier is actually cheaper than fresh;
`cached > input` cannot produce negative tokens; unknown model costs zero rather than a guess; reasoning is not doubled;
usage does not accumulate across turns; Grok remains absent from `TOKEN_PRICES`, with the size of the error asserted.

## v2.26.2 — 2026-07-27 — #95 Grok T3: session resume

### Fixed
- 🔥 **Race on shared `GROK_HOME/config.toml` could disable MCP isolation by itself** (`app/backend_grok.py`).
  `ensure_grok_home()` rewrote the file on EVERY connection using ordinary `write_text`, i.e. truncate + write. A worker
  starting in that window read an **empty** config: without `mcps = false`, T2 isolation was off and foreign MCP servers
  started with their secrets.
  - **Measurement:** four writers + four readers for three seconds → **57.9% of reads saw an empty file** (17,626 of
    30,466). The same measurement after the fix: **0%**.
  - Fix: write through a unique temporary file plus atomic `rename`, and skip writing when content matches. This is the
    same technique as `workspace.sync_agents_md`, for the same reason.
- 🔁 **A stale `sessionId` no longer blocks a worker forever** (`app/backend_grok.py`). The store key is `(cwd, sessionId)`,
  so a moved or cleaned worktree made `session/load` fail forever and connection impossible. Now `session/load` failure →
  a new session plus a **loud** warning that history is unavailable. History is never lost silently.
- 📁 **Clear error for a missing worktree.** Previously process spawn produced a bare `FileNotFoundError` naming the path
  but not the cause.

### Known tradeoff
The failed-resume warning initially **never reached the user**: it carried the old `sessionId`, while `events()` discards
notifications with a foreign id, so the lost-history message filtered itself out. The key was renamed `staleSessionId`.
A live test caught this by requiring the warning to appear, not merely a successful connection.

### Reasoning
Measurements using the live CLI (risks specified by PM):
- **One shared `GROK_HOME` is session-safe for every worker.** Two workers connected simultaneously from different cwds
  received different ids and isolated turns (`ALPHA`/`BETA`). The session store is partitioned by URL-encoded cwd, so it
  cannot overlap by design. Only shared `config.toml` was dangerous; see above.
- **Resume SURVIVES a branch change in the same worktree.** After `main` → `feature/x`, `session/load` returned the same id
  and remembered the code word. Sessions bind to path, not branch, so the “survives restart” contract also holds after a
  post-merge branch switch.
- **Foreign cwd** with the same id → `Path not found` → fallback to a new session (verified: different id, history honestly unavailable).

### Tests
`tests/test_backend_grok.py` (48): atomic config writes under a concurrent reader, rewrite on content drift with no
temporary debris, resume warning not filtered by routing, and connection failure for a missing worktree.

## v2.26.1 — 2026-07-27 — #95 Grok T2: MCP isolation

This closes a leak channel, not a hygiene issue: the T1 artifact contained a live third-party service key because Grok
starts foreign MCP servers itself and relays their environment.

### Fixed
- 🔒 **A Grok worker starts with EXACTLY our MCP server set** (`app/backend_grok.py`). Two layers: an Orchestra-owned
  `GROK_HOME` (`data/grok-home`, in `.gitignore`) with `[compat.claude] mcps = false`, plus verification of the actual roster
  on connect. A foreign server raises `GrokMcpIsolationError`; the worker **does not start**, and the error lists offenders.
  - `auth.json` is a symlink to the user's file so token refresh does not go stale in a private copy. The directory is
    stable, not temporary: it also holds the session store required for resume (T3).
- ⚙️ **Environment `GROK_BIN` overrides PATH discovery** (`app/backend_grok.py`). Previously `shutil.which()` ran first,
  allowing an unrelated `grok` in PATH to silently beat explicit configuration.

### Reasoning
Measurements that determined the design (`docs/tasks/95`):
- **`session/new.mcpServers` MERGES with discovered servers rather than replacing them.** Supplying only `orchestra`
  produced `{orchestra, websearch, mcp-pandoc}`; supplying an empty list still produced two foreign servers.
- **The only working `[compat.claude] mcps = false` switch is read ONLY from user config.** The same key in project
  `.grok/config.toml` is ignored (`on (default)` versus `OFF (config)`). We cannot modify `~/.grok/config.toml`; it is the
  user's personal file and would break interactive Grok. Hence a dedicated `GROK_HOME`.
- **The plan rejected `GROK_HOME` as breaking authentication; measurement disproved that:** a sandbox with an `auth.json`
  symlink logs in normally (`logged in with grok.com`).
- **Discovery sources, exact list:** `~/.claude.json` (top-level plus 47 per-project records), project `.mcp.json`,
  `~/.grok/config.toml`, project `.grok/config.toml` files up to repository root, and plugins.
- **`.mcp.json` is suppressed by folder trust, not a switch:** the file itself removes trust from the directory, so the
  headless server does not start. We do not rely on this; the runtime check catches it independently.

### Known tradeoff
The connection check initially relied on `_x.ai/mcp/server_status`, producing a **false “clean”** result: our `orchestra`
reports `ready` only AFTER the first turn, while `mcp_initialized` arrives earlier, leaving the roster empty at verification.
The roster now comes from `_x.ai/mcp/servers_updated`, which arrives early and is itself the leak channel that relayed the
key. `server_status` remains a secondary signal.

### Tests
`tests/test_backend_grok.py` (43): connection rejection for a foreign server, roster limited to our sources, roster from
`servers_updated` (regression for false “clean”), `GROK_HOME` with Claude compatibility disabled and auth symlink, fail loud
without credentials, injected `GROK_HOME` overriding inherited state, and `GROK_BIN` priority. Live: no leak with the sandbox;
bypassing isolation makes the connection fail.

## v2.26.0 — 2026-07-27 — #95 Grok Build runtime (T1)

A fourth runtime alongside `claude`/`codex`/`opencode` (`docs/tasks/95/research.md`, `plan.md`). The motivation is a
separate SuperGrok quota pool. The research itself received no cross-review because the Codex pool was exhausted until
2 August. For now it is **registry-only**: the runtime must be selected explicitly; `pipeline.yaml` defaults are unchanged.

### Added
- 🤖 **`GrokBackend`: ACP (Agent Client Protocol) over `grok agent stdio`** (`app/backend_grok.py`). A long-lived process
  plus JSON-RPC 2.0 over stdio, analogous to `codex app-server`. Session resume uses `session/load`; interruption uses
  `session/cancel` (verified: immediate, `stopReason=cancelled`, stream stops). Model `grok-4.5`, context **500,000**
  (runtime value; articles claiming “256K” were disproved).
- 🧩 **Runtime and model registration** (`app/runtime_registry.py`, `app/models.py`). `_infer_backend()` sent everything
  outside `gpt-*`/`claude-*` to **`opencode`**, so an unregistered `grok-4.5` would silently reach the wrong runtime.
  Added `grok-*` → `grok` with provider `x-ai`; provider-qualified ids such as `x-ai/grok-4` deliberately remain on `opencode`.

### Reasoning
- **A separate backend, not a shared Codex layer.** Line-based measurement: of 1,105 method lines in
  `backend_codex.py`, only **220 (20%)** are shared JSON-RPC transport, while **826 (75%)** implement Codex's event
  vocabulary (`item/started`, `item/completed`, `collabAgentToolCall`), which Grok lacks entirely. ~80% divergence at
  a 30% threshold. Precedent: `backend_opencode.py` imports nothing from `backend_codex.py` either; the only shared layer
  is the 16-line `BackendLike`.
- **The system prompt travels ONLY through `--agent-profile`** (temporary `.md` with YAML frontmatter, deleted on
  `disconnect`). ACP fields `systemPrompt`/`_meta.systemPrompt`/`instructions` are accepted and **silently ignored**,
  leaving the worker without any prompt. A canary proved this before code was written.
- **`mid_turn_inject=False`.** A prompt sent during a turn does not steer it; it enters the native queue and runs as a
  SEPARATE turn, so N messages = N `turn_end` events. The event loop completes when the queue empties, not at the first
  `prompt_complete`, or queued turns would stream into nowhere.
- **Cost comes from the runtime.** `costUsdTicks` = **1e-10 USD**, not 1e-9—the first research version used the wrong
  units and was retracted. Four measured turns match `((in−cached)·$2 + cached·$0.30 + out·$6)/1e6` exactly. The real
  cache price is **$0.30/M**, not the $0.50 quoted by every article. Prices live in `backend_grok.py`, not `TOKEN_PRICES`,
  which has no `cached` tier.

### Known issue
- **The terminal quota-exhaustion shape is unknown:** we could not exhaust SuperGrok. `_classify_error` does not guess;
  an unrecognized failure remains `error` and fails loudly (`report_bug`, no silent retry). Classification will follow the
  first real limit hit, not precede it.
- **Foreign MCP servers are not yet suppressed** (T2). Grok discovers servers from `~/.claude.json`/`.mcp.json` and
  relays their environment; this exposed a live `OPENROUTER_API_KEY` during research. The factory already assembles an
  explicit set from our sources, but suppressing implicit discovery is a separate ticket.

### Tests
`tests/test_backend_grok.py` (33): event mapping from a real dump, idempotent `turn_end` under two completion signals,
`x-ai/grok-4` not intercepted, MCP-to-ACP translation (environment as a list of pairs, not a dictionary), and three
measured turns as cost fixtures. `grok` was also added to contract test `test_backend_classes_satisfy_structural_contract`.

## v2.25.1 — 2026-07-27

### Removed
- 🗑 **Opus 4.6 and 4.8 were removed from the model registry** (`app/models.py`, `app/tg_bridge.py`,
  `app/static/js/app.js`). They are gone from `MODELS`, `CONTEXT_LIMITS`, `BACKENDS`, `TOKEN_PRICES`, semantic aliases,
  short TG names, and the dashboard palette, leaving only current models in the dropdown.
  - Old ids (`claude-opus-4-8[1m]`, `claude-opus-4-6`, with and without suffixes) **remap to
    `claude-opus-5[1m]`**, using the same technique as `claude-sonnet-4-6` → Sonnet 5. A database session with an old
    model starts on Opus 5 rather than failing.
  - Also removed dead auto-bump `effort low/medium → high` for 4.8 from `backend_claude.py`. Claude's auto-downgrade
    `xhigh → high` remains because it addresses an API limitation, not a model.
  - The database contained no live 4.6/4.8 sessions (`sessions.model` measurement); the single 4.8 worker was moved to
    Opus 5 before the change.

## v2.25.0 — 2026-07-27 — #90 lifecycle T1–T3

Worktree/merge lifecycle audit (`docs/tasks/90/audit.md`, 12 confirmed defects, 19 experiments). Implementation proceeds
in vertical slices T1→T7; T4–T7 are frozen until the weekly Codex quota resets on 2 August.

### Added
- 🌿 **Persisted base-branch contract** (T1; `app/db.py`, `app/session.py`, `app/workspace.py`,
  `app/routes/sessions.py`, `app/mcp_stdio.py`). Columns `base_branch TEXT DEFAULT ''` and
  `needs_switch INTEGER DEFAULT 0`; the spawn base resolves ONCE (explicit → symbolic remote HEAD → sole local
  `main`/`master`) and is stored in the session. `merge`/`switch`/`wip`/`kill` read it instead of literal `main`.
  - **Why not “infer it from HEAD”:** after `checkout feature/x`, symbolic HEAD names the feature branch; mainline
    cannot be reconstructed retroactively. An ambiguous legacy row now fails loudly before any git operation instead
    of merging into a random branch.
  - **Triggered case:** primary branch ≠ `main`—Aperant uses `develop`; VPN-Service contains both `main` and `master`.

### Changed
- 🔒 **Merge runs in the checkout that owns the target and rejects a dirty target** (T2; `app/workspace.py`). A branch
  checked out in the parent worktree is merged there. Auto-stash was removed from the merge path; uncommitted changes
  are returned to the user as a path list, and neither target nor worker branch is touched. Prunable worktree metadata
  no longer produces 500 (found in Codex review).

### Fixed
- ♻️ **Squash commit is atomic: hook failure rolls back the target** (T3; `app/workspace.py`). Failed `git commit`
  (pre-commit hook, related or unrelated paths) now restores HEAD/index/worktree to original `old_head` and verifies
  the rollback; the worker branch is unchanged. Previously failure left cherry-picked commits in the target while
  reporting an error, a “half-merged” state.
- 🔗 **`merge_worker` no longer prints `FAILED — unknown` after successful linking** (T3; `app/tm.py`,
  `app/routes/sessions.py`, `app/mcp_stdio.py`). `link_commits_to_task()` returned a task row or `None`, while MCP read
  the same object as `{ok, added, error}`; success without an `ok` key rendered as an unnamed error. The function now
  returns stable DTO `{ok, added, task_id | error}`, and an unknown task has explicit text.
  - **Triggered case:** two consecutive merges reported failure after actually succeeding; task status was set manually.
  - **Tests**: `test_related_commit_failure_rolls_back_target_and_preserves_worker`, `test_unrelated_commit_failure_rolls_back_target_and_preserves_worker`, `test_merge_links_commits_with_normalized_sqlite_results`, `test_merge_worker_formats_normalized_and_legacy_link_results`.

### Known tradeoff
- Until Orchestra restarts, live FastAPI retains old `app/routes/` code while fresh MCP processes load new code, so
  `FAILED — unknown` and `target branch '' does not exist` remain reproducible. Workaround: explicitly call
  `merge_worker(name, target="main")`.

## v2.24.3 — 2026-07-27

### Changed
- 🔇 **Compact summary is no longer sent to TG** (`app/session.py:1201`). The full summary was logged as type `text`,
  and `text` means agent speech to the bridge, so it immediately forwarded several kilobytes into the topic with a user mention.
  - Restore old behavior with `LOG_COMPACT_SUMMARY=1` in `.env` (default `0`, documented in `.env.example`).
  - The summary is preserved in `session.last_summary`, the new context preamble (`user_message` log), and the
    `compact_worker` response. Chat now receives one line: `compact done: X% → Y% (summary N chars)`.
  - **Triggered case:** the user received a wall of text in TG after orchestrator compaction and requested a flag rather
    than permanently changing behavior.

## v2.24.2 — 2026-07-26

### Removed
- 🗑 **`_auto_commit_if_dirty`: spawn no longer commits the user's uncommitted work** (`app/manager.py`). Before creating
  a worktree, the function ran `git add -A` + `git commit` in the working checkout, justified by the claim that
  “worktrees inherit unstaged junk.”
  - **The justification was false**, verified experimentally in a clean repository: `git worktree add <path> HEAD`
    builds from the commit; source unstaged changes and untracked files never enter it. The function ran only under
    `use_worktree and repo_path`, exactly the one case where it was unnecessary.
  - **Triggered case:** the inscryption-ai orchestrator discovered that Orchestra committed someone else's `.serena/`
    directory to `main` before spawning a worker. This happened on every spawn from a dirty repository since `1e39c47`.
  - Removed two mocks from `tests/test_manager.py`; nobody tested the function itself.

### Fixed
- 📁 **Worktree directory and branch are named from repository root, not session `scope`** (`app/workspace.py:285-294`).
  Before: `wt_dir = WORKTREE_ROOT / _slugify(scope)`, while the repository came from `repo_path`: two independent,
  never-reconciled sources.
  - **Symptom:** workers `impl-deck-search`, `impl-inscryption`, and `feat-inscryption-ai` lived under
    `worktrees/home-maxim-cursor-cog-second-brain/` even though `git-common-dir` was
    `/mnt/data/Projects/Python/inscryption-ai/.git`. This appears when a parent in one project spawns a worker in another.
    Branches were also named `feat/home-maxim-cursor-cog-second-brain/<name>` inside the unrelated repository.
  - **Why it matters:** this produced a series of false “`repo_path` is ignored” bug reports. Orchestrators read the path
    instead of `git-common-dir` and inferred a miss. The earlier `fix-repo-path` investigation cleared `repo_path` but
    did not find the actual cause.
  - Removed `scope` from `create_worktree`; after the fix it was unused. Existing worktrees are unaffected because their
    paths are stored in the database.
  - **Tests:** `test_repo_namespaced_path`, `test_branch_namespaced_by_repo`, `test_worktree_belongs_to_requested_repo`,
    `test_different_repos_no_collision` (replaced `test_different_scopes_no_collision`; the property “different scopes
    → different paths” no longer exists). 152 green.

## v2.24.1 — 2026-07-01

### Added
- 🔀 **`POST /api/proxy/set-env`: switch proxy with a button, without editing `.env` manually.** The frontend sends
  `{"id": "contabo-de"}`; the endpoint finds the proxy in `PROXY_LIST` and rewrites ONLY `HTTPS_PROXY`/`HTTP_PROXY`
  lines in `.env` (line surgery via `(?m)^KEY=.*$`; TG/YouGile tokens untouched). `url=="direct"` → empty value for a
  direct connection. Response: `{"ok": true, "wrote": <url>, "need_restart": true}`.
  - **NOT a hot switch:** neither `os.environ` nor the database changes. `.env` remains the source of truth and applies
    after the user restarts. The old `select_proxy` behavior (mutate environment live → drift) is excluded by design.
  - **Implementation** (`app/routes/proxy.py`): `_set_env_proxy(url)` performs an atomic write (temporary file plus
    `os.replace`; a crash must not corrupt `.env` containing tokens). `ENV_FILE = Path(__file__).parent.parent.parent/.env`
    matches systemd `EnvironmentFile`/`WorkingDirectory`. `re.sub` uses lambda replacement so URL/password are written
    literally without backslash interpretation.
  - **Codex review:** zero bugs (checked regex anchor against `PROXY_LIST`, case sensitivity against `https_proxy`, path
    traversal through `body.id`, and direct→empty). Atomic writing was added from a residual comment.
  - **Tests**: `tests/test_proxy.py` — token preservation, direct→empty, append-when-missing (9 pass).
  - **Frontend:** the proxy-selection button implementing this contract belongs to frontend-opus.

## v2.24.0 — 2026-07-01

### Changed
- 🔌 **Proxy: `.env` `HTTPS_PROXY` is the sole source of truth; database/hot-switch removed.** The user asked to
  “cut all the unnecessary parts.” Proxy management now uses only `.env` plus `sudo systemctl restart orchestra`.
  Removing all live environment mutation makes drift impossible by design (`.env` showed 12343 while CLI agents retained
  12342 from the database).
  - **Root cause of drift:** database `kv.active_proxy` **overrode** `.env`; `load_saved_proxy()` rewrote `os.environ`
    from the database at startup. Live CLI agents then held DIFFERENT proxies because `backend_claude._make_client()`
    snapshots `os.environ["HTTPS_PROXY"]` at `connect()` into a persistent SDK client (verified: pid A→12334, pid B→12342).
  - **Removed from `proxy_manager.py`** (net −107 lines): `load_saved_proxy` (read database kv), `select_proxy` (mutated
    `os.environ` + `MCP_BASE_ENV`, wrote kv), `refresh_loop`, `_cache`/`CACHE_TTL`/`_ts` stamps, and `_active_id` state.
    The module is read-only now: `list_proxies()` derives `active` from `os.environ` via read-only `_active_id()`, while
    `check_all()`/`check_proxy()` perform on-demand health checks without cache.
  - **`routes/proxy.py`:** removed `POST /api/proxy/select/{proxy_id}` and live-agent interrupt logic. `list`, `check`, and
    `tunnel/status` remain. `route_surface_snapshot.json` updated.
  - **`main.py`:** removed `proxy_manager.load_saved_proxy()` and the `refresh_loop` task.
  - **Frontend** (`app.js`): removed the “select proxy” button (`.proxy-select-btn`) and handler. Check and active indicator remain.
  - **Database:** `DELETE FROM kv WHERE key='active_proxy'`. Migration/column untouched; they are dead and unread.
  - **#3 Direct id fix:** force `id="direct"` when `url=="direct"`. Previously the id came from the name, yielding
    `direct-(vpn/соту)` with Cyrillic and parentheses, so `select/direct` returned 404. The `.env` name is now simply `Direct`.
  - **#4 zombie backoff + health gate** (`ssh_tunnel.py`): dead VPS endpoints (timeweb/ezhik) reconnected SSH every five
    seconds forever (`kex_exchange_identification: Connection reset` in logs), creating zombies. A two-second TCP health
    gate on `:22` now precedes spawn, with exponential backoff 5→300 seconds and reset after uptime >60 seconds.
  - **`CLAUDE.md`:** “🔌 PROXY” section documents the source of truth, how to switch, and read-only dashboard behavior.
  - **Codex wrapper** (`~/.local/bin/codex`): added `HTTP_PROXY`; only HTTPS existed before and Codex WebSocket failed without it.
  - **Tests:** `tests/test_proxy.py` (six: direct id, active-from-env, no-mutation-methods, port probe, health gate). 48 green.
  - **Reverted from v2.23.0:** `CACHE_TTL`/`refresh_loop`/`_cache`, added in the prior iteration but unnecessary with
    on-demand dashboard checks.
  - **Docs**: `docs/tasks/proxy-fix/{best-practices,plan-simplify}.md`.

## v2.23.0 — 2026-07-01

### Fixed
- 🔌 **Proxy SSH tunnels depended on VPN and accumulated zombie processes (proxy-fix).** Every Orchestra proxy was an
  `ssh -L` tunnel to a VPS. After a network change or disabling Reality VPN, old SSH processes remained half-alive and
  held the local port; a new tunnel could not bind, and the proxy silently returned HTTP 000. Duplicates also accumulated:
  nine SSH processes for four tunnels.
  - **Root cause:** NOT Russian network blocking. Contabo (158.220.127.161) and Fornex (89.127.206.225) were directly
    reachable from Russian Wi-Fi without VPN (verified by SSH banner plus
    `curl -x :12343 https://api.anthropic.com/v1/messages` → HTTP 405). Problems: (1) with VPN ON, xray TUN mode
    (`ip rule 9001 lookup 2022`) routed VPS traffic through tun0; (2) stale SSH processes were never killed.
  - **`_kill_stale(t)`** (`app/ssh_tunnel.py:37`) runs
    `pkill -f "ssh -N -L {local}:127.0.0.1:{remote} .*root@{host}"` before each tunnel starts—once in `start_tunnel`,
    NOT in the reconnect loop. The pattern pins local and remote ports **and** host, killing only ITS tunnel definition,
    not another same-port forward. Tested against real SSH processes: kill own, preserve foreign.
  - **Hard kill:** `stop_tunnel` and its CancelledError handler now run `terminate()` → `wait_for(KILL_GRACE=3s)` →
    `kill()` (SIGKILL) if SSH hangs on a dead route. `KILL_GRACE=3` (`ssh_tunnel.py:18`).
  - **Dashboard TTL** (`app/proxy_manager.py`): `_cache` without a TTL showed a dead proxy as 🟢 forever. Results now
    receive monotonic `_ts` stamps under `CACHE_TTL=60s`; `list_proxies` drops stale data, making the frontend show ⚪
    (unknown, already supported at `app.js:4879`). `refresh_loop()` (background task at `main.py:56`) rechecks every
    60 seconds and self-heals.
  - **`.env`:** reordered `SSH_TUNNELS` with live contabo/fornex first and dead ezhik/timeweb last. `check-proxies.sh`
    candidates follow the same order.
  - **NM hook:** `scripts/99-orchestra-proxy` dispatcher for up/down/vpn-*/connectivity-change → `check-proxies.sh`.
    The user installs it manually as root; instructions are in the file header.
  - **Triggered case:** the user disabled Reality VPN on home Wi-Fi and Orchestra failed as its tunnels died. The goal is
    a proxy as a REPLACEMENT for VPN, not a dependency on it.
  - **Skipped:** `ip rule` split tunnel (#5). The user runs VPN **or** proxy, not both, so VPN-off leaves nothing to intercept.
  - **Codex review:** confirmed safe matching (12340≠123400) and correct `_kill_stale` placement in `start_tunnel`; accepted
    the suggestion to narrow the pkill match to host + remote (implemented).
  - **Research**: `docs/tasks/proxy-fix/research.md`.

## v2.22.0 — 2026-06-21

### Added
- 📡 **Real-time token streaming in dashboard (task #83)** — agent text now types out live in the chat bubble as the model generates it, instead of appearing all at once when the turn's text block completes. Latency drops from "whole block after completion" to ~5 chunks/sec (~80-100 chars/chunk — the Claude CLI batches deltas; not per-token).
  - **Backend**: `include_partial_messages=True` in `ClaudeAgentOptions` (`app/backend_claude.py:138`). `_convert` gained a `StreamEvent` branch (`backend_claude.py:242`) that emits `AgentEvent("stream", text)` — STRICTLY scoped to main-agent `text_delta`: `parent_tool_use_id is not None` (subagents), non-`content_block_delta` events, and `thinking_delta`/`input_json_delta`/`signature_delta` are all filtered out. The final `AssistantMessage` still emits `text`/`thinking`/`tool_use` and is persisted exactly as before.
  - **Pub/sub**: new `app/live_broker.py` — in-memory per-session broker (`broker.subscribe/publish/unsubscribe`). Bounded `asyncio.Queue(maxsize=256)` per viewer, drop-oldest on overflow (partials are ephemeral, never block the agent loop). Single-process/single-loop only (like the session manager). Sync `publish` — never awaits.
  - **Routing**: `session._handle_event` (`session.py:519`) routes `stream` events to `broker.publish(self.id, ...)` — NO DB write. Key is `self.id` (== `manager.get_session_id` == `logs.session_id`), NOT the Claude `session_id` (often `None` on first turn).
  - **SSE**: `stream_session_logs` generator (`app/routes/sessions.py:279`) now subscribes to the broker, drains live partials BEFORE polling the DB each tick (ordering: partials always precede their final `text` row → no orphan bubble), 0.1s poll while active / 0.5s idle, `unsubscribe` in `finally`.
  - **Frontend**: the `type:"stream"` bubble renderer existed since 2026-05-01 (`c82e725`) but was DEAD CODE — no backend ever emitted it. Now wired up. Fixes: final `text` replaces the bubble body with the DB-authoritative content (`app.js:2155`, handles dropped/truncated partials); `firstId`/`lastId` bookkeeping guarded with `Number.isFinite(l.id)` (`app.js:189` — partials carry no id).
  - **NOT touched**: DB schema, cost/usage accounting, TG bridge (stays final-only — partial spam would be insane), codex/opencode backends (emit no `StreamEvent`).
  - **Tests**: `tests/test_live_broker.py` (7 — fan-out, drop-oldest, unsubscribe cleanup, session isolation), `tests/test_backend_stream.py` (7 — scope filter: text_delta passes; thinking/input_json/signature/subagent/non-delta dropped). All 14 green.
  - **Codex review**: APPROVED, 0 blocking — verified no subscription leak, no broker race, no orphan bubble, correct scope filter.
  - **Research artifacts**: `docs/tasks/83/` (research.md, plan.md, capture_partial.py, partial_dump.jsonl).

## v2.21.1 — 2026-06-15

### Fixed
- 🐛 **OpenCode turn never ends → orchestrator stuck `running` (task #97, 11h in prod)** — the turn boundary relied on the fire-once SSE `session.idle` event (global bus, 30s heartbeats, frequently MISSED) plus a chat `POST /message` that could hang forever. When both failed, `events()` never yielded `turn_end`, the listen task never exited, status stayed `RUNNING` indefinitely.
  - **Technical core**: rewrote `OpenCodeBackend.events()` (`app/backend_opencode.py`) to detect completion by POLLING `GET /session/status` every `STATUS_POLL_INTERVAL=3s` — an authoritative daemon query that cannot be "missed" like an event. Idle ⟺ session absent from the status dict OR `type=="idle"`; `busy`/`retry` ⟶ keep waiting. SSE is kept ONLY for live streaming of `text`/`thinking`/`tool` parts (`_handle_sse` helper + `_SESSION_IDLE`/`_SESSION_ERR` sentinels — SSE idle just triggers an immediate status poll, never ends the turn on its own).
  - **Send path**: `send()` now submits via `POST /session/{id}/prompt_async` (returns `204` immediately) instead of a chat-POST task that could hang. Dropped `_chat_task`/`_post_chat`; per-turn state is a single `_turn_active` flag. Body uses NESTED `model:{providerID,modelID}` (the `prompt_async` schema differs from the old `/message`).
  - **turn_end** built from `GET /session/{id}/message` (last assistant message) via new `_fetch_last_message()` — cost/tokens independent of the submit. `_turn_end` normalizes both `{info,...}` and flat-`AssistantMessage` shapes (`info = msg.get("info") or msg`).
  - **No-stuck guarantees (all Codex-flagged)**: HARD deadline enforced INSIDE `events()` (`TURN_TIMEOUT`) — the `session.py` timeout only runs when `events()` yields, so a perma-`busy` daemon would've still hung; `_turn_active`/`_sse_response` reset in the `finally` (cancel-safe); status-poll tolerates transient failures (`STATUS_FAIL_THRESHOLD=3` consecutive OR `_proc_dead()` before declaring dead); message-fetch is total → exactly one `turn_end` on every exit path.
  - **`app/session.py:365`** — wrapped `await backend.send(message)` in try/except: a `send()` failure after `status=RUNNING` and before the listen task is created was a SECOND stuck-running path (any backend). Now resets to `IDLE` on failure.
  - **Removed**: all the prior debug-patch cruft — `INACTIVITY_TIMEOUT`, `wait_timeout`, the SSE-drain loop, the useless heartbeat daemon-poll.
  - **Tests**: `tests/test_backend_opencode.py` event-loop suite rewritten for the poll model (fake SSE + scripted `/session/status`). New cases: SSE-never-sends-idle (THE bug), perma-busy hits hard deadline, single vs repeated status failures, retry-not-premature, message-fetch empty/raises, flat-message shape, cancel resets `_turn_active`, submit-grace. 44 tests green.
  - **Triggered case**: orchestrator on opencode backend sat at `running` for 11h after a turn the daemon had actually finished — the `session.idle` SSE event was dropped and the chat POST response was lost.

## v2.21.0 — 2026-06-14

### Added
- 🔌 **OpenCodeBackend (`app/backend_opencode.py`)** — third `BackendLike` backend wrapping the `opencode serve` daemon (HTTP + global SSE bus), alongside Claude/Codex. Wired into `session.py:_make_backend` (`backend_type == "opencode"`) + `events.py` type-comment. Task #96, Codex-reviewed plan + impl (4 rounds → APPROVED). 39 unit tests, all green.
- 🧭 **Backend routing → opencode (`app/models.py`, Phase 2)** — `_infer_backend()` now: `gpt-*`→codex, `claude-*`→claude, **everything else** (deepseek, gemini, llama, mistral, …) → `opencode`. `backend_for_model()` infers from the ID prefix for UNregistered models instead of defaulting to claude — a never-seen `deepseek/deepseek-v4-flash` from the proxy routes correctly. No model IDs hardcoded; dynamic `fetch_models_from_proxy` populates `BACKENDS` via `_infer_backend`. Provider/model split (`OpenCodeBackend.__init__`) parses proxy `provider/model` IDs (`deepseek/deepseek-v4-flash` → provider `deepseek`, model `deepseek-v4-flash`; first slash only). `tests/test_backend_routing.py` (9 tests).
  - **Shape**: Codex-like managed subprocess (one turn per `send`, native `cost` from the chat response — NO `TOKEN_PRICES` table needed) but with Claude-like streaming richness (`text`/`thinking`/`tool_use`/`tool_result`) delivered over a SEPARATE global SSE stream (`GET /event`), not inline.
  - **Dual-source turn coordination**: `events()` does `asyncio.wait({next_sse_line, chat_task}, FIRST_COMPLETED, timeout=TURN_TIMEOUT)`. `session.idle` = turn boundary; the awaited chat POST (`{info:{cost,tokens}}`) supplies authoritative `turn_end` metadata. Exactly ONE `turn_end` on every exit path (idle / sse_failed / timeout / chat_failed / chat_cancelled / early-close).
  - **Transport**: plain `httpx` (not the `opencode-ai` SDK) — the SDK's pydantic event types silently drop `reasoning`/`message.part.delta`/unknown events; raw-dict parsing keeps full fidelity. No new dependency (httpx already present).
  - **MCP**: Orchestra stdio `{command,args,env}` → OpenCode `McpLocalConfig {type:"local",command:[...],environment,enabled}`, written into a per-worker `opencode.json` in the worktree (merged if one exists). `permission: {edit,bash,webfetch:"allow"}`.
  - **Daemon lifecycle**: one daemon per backend instance, free-port alloc with 3× retry, readiness via `GET /app` 200 poll, stdio → DEVNULL (no pipe back-pressure), teardown = abort → terminate → wait → kill → **reap** (verified: no zombies).
- **Reasoning**: re-derived the whole seam from a LIVE probe (opencode v1.17.6 + SDK 0.1.0a36) because the referenced `docs/research/RESEARCH-OPENCODE.md` never existed in the worktree. Captured real event shapes from a daemon turn — that's how the `reasoning` part (→ `thinking`) and cumulative-text streaming (suffix-only emit) were found.

### Fixed (caught during Codex review, in the new backend)
- 🐛 **SSE `aclose()` on a running generator** — `next_line.cancel()` must be `await`ed BEFORE `sse.aclose()`, else `RuntimeError: asynchronous generator is already running` silently swallows the close → HTTP-stream leak. Now: cancel → await → aclose.
- 🐛 **`CancelledError` leak on normal-end await** — `await wait_for(chat_task)` caught only `Exception`; an externally-cancelled task raises `CancelledError` (BaseException). Now a `chat_task.cancelled()` pre-check + explicit `except asyncio.CancelledError` → `turn_end(chat_cancelled)`.
- 🐛 **Concurrent `disconnect()` race** — snapshot `chat_task = self._chat_task` at the top of `events()`; a parallel `disconnect()` nulling the field no longer causes `AttributeError` mid-iteration.

## v2.20.0 — 2026-06-11

### Changed
- 🏗️ **Full architecture refactor P0–P4** (per `docs/reviews/arch-audit.md`, Codex-reviewed plan + impl, 5 commits `3a7b76a..57949c5`). Public API (HTTP/MCP/DB) byte-identical — guarded by `tests/test_routes_surface.py` snapshot (77 routes). 487 tests green.
  - **P0 fail-loud + async**: 24 silent `except: pass` → `logger.warning` with context; `tm_yougile.py`/`routes/tm.py` sync SQLite wrapped in `asyncio.to_thread` (connection-per-helper, transaction never crosses await); `tm.set_main_loop()` + `run_coroutine_threadsafe` fallback — YouGile sync fired from worker threads no longer silently no-ops; codex turn loop got `_on_task_done` callback; `_auto_continue` capped at 5 consecutive max_turns
  - **P1 union-type fix**: `manager.get_by_name()` always returns `AgentSession | None` — detached DB-hydrate via `_hydrate_row()` with `loaded=False` discriminator + `db_row` for legacy response shape; 34 `isinstance(found, dict)` sites killed; `manager.update_session_fields()` replaces handler-level `_persist()` triplets
  - **P2 main.py drain**: 1574 → 91 lines; 56 handlers → `routes/{sessions,system,tg}.py`; `templates` → `deps.py`; `/api/open-file` now passes `_is_safe_path` (was the one unguarded sibling)
  - **P3 cycles → wired callbacks**: session→tg_bridge via module hooks `on_scope_idle`/`on_scope_running`; manager→tg_bridge via `tg_topics_remover` slot; tm→tm_yougile via `on_task_synced`/`on_payment_changed` registered at import; `MCP_BASE_ENV` → `runtime_env.py` leaf; `_fire_sync`/`_fire_journal_sync` deduped
  - **P4 session split**: `session_cost.py` (CostTracker), `session_turns.py` (TurnManager), `session_hibernate.py` (HibernateManager), `session_state.py` (AgentStatus leaf). Systems-over-state: ALL fields stay on `AgentSession` dataclass, systems hold methods. Cost math delta-based AS-IS, locked by `tests/test_p4_cost.py` contract
- **Reasoning**: audit found 43% of codebase (4 files) carrying all architectural debt; import graph was a DAG only via ~75 lazy imports. Now: downward-only edges, one lookup type, thin transport layer.

### Fixed
- 🐛 **Test hot-loop starvation** — `_MockBackend.events()` re-yielded `turn_end` infinitely with zero suspension points after `finish()`; tests hung when default DB had `bg_jobs` table. Fix: re-arm `_finish_event` after yield. Triggered case: full-suite run started hanging mid-`test_session.py` after stale WAL cleanup
- 🐛 **stop_bridge stale globals** (Codex impl review) — `bot`/`_manager` now cleared on stop; a handler racing past the unhook sees inactive state

### Known tradeoff
- Pending `tm_sync_log` row dangles if sync fired in a CLI context with no event loop — byte-identical legacy behavior, kept for behavior-preservation (in TODO)


## v2.19.0 — 2026-06-04

### Added
- 🔧 **Pipeline-as-config (PR #2)** — opt-in YAML manifests for roles/pipelines. Each client gets isolated `pipelines/<name>/` with custom roles, prompts, workflow. Rebased from v2.16.0 onto v2.18+, all conflicts resolved. `app/pipeline.py`, `pipelines/`

### Fixed
- 🐛 **TG topic icons for sub-orchestrator workers** — running status wasn't propagated to sub-orchestrator's TG topic. Added `notify_scope_running()` + `_find_scope_orch_name()` dedup. `session.py`, `tg_bridge.py`
- 🐛 **Single tilde rendered as strikethrough** — agents writing `~5 min` got false strikethrough between two tildes. Fix: escape single `~` before marked.parse. `app.js`

## v2.18.0 — 2026-06-03

### Added
- 🔧 **`needs_switch` guard** — after `merge_worker`, session is flagged `needs_switch=True`. Sending tasks to a merged worker returns 400 error until `switch_worker_branch` is called. Eliminates LLM-dependent "remember to switch" failure mode. `session.py`, `main.py`
- 🔧 **`merge_worker(next_task_id=)` atomic merge+switch** — optional parameter auto-switches to new branch after merge. One tool call instead of two. `mcp_stdio.py`, `main.py`
- 🔧 **Auto-cleanup stale worktrees** — on startup + every 24h, scans `worktrees/` and removes directories without active DB sessions. Checks dirty tree before removal. `workspace.py`, `manager.py`
- 🔧 **Cross-project `send_message`** — fallback to `ensure_loaded_any(name)` when same-scope lookup fails. Orchestrators can now message agents in other projects. `main.py`

### Fixed
- 🐛 **System prompt lost on compact/resume** — `backend_claude.py` had mutually exclusive `if resume_id` / `else` branches: resuming a session skipped `system_prompt` entirely. Fix: always set `system_prompt`, then optionally set `resume`
- 🐛 **Compact summary invisible in dashboard** — `session.py` sent compact preamble via `backend.send()` without `_log()`. Fix: added `_log("user_message", ...)`
- 🐛 **`switch_worker_branch` blocked after squash merge** — overly strict `merge-base --is-ancestor` check rejected worktrees diverged by squash merge. Fix: `git reset --hard from_ref` before branch switch. `workspace.py`
- 🐛 **Send errors hidden in dashboard** — `mcp__orchestra__send_message` renderer returned `null` on failure, silently hiding errors. Fix: show red `❌` with error text. `app.js`
- 🐛 **Spawn bubble text wrapping** — `task.slice(0, 200)` cut markdown mid-line, breaking bullet lists. Fix: cut at newline boundary. `app.js`
- 🐛 **Merge didn't update session** — `merge_session` reset worktree files but left `session.branch` and `session.task_id` stale. Dashboard showed outdated branch info. Fix: update session fields after merge. `main.py`

## v2.17.0 — 2026-06-01

### Changed
- **Merged `codex-review` module into `codex-debate` skill** — one skill, two modes: **Quick Review** (one-shot `codex exec review`/`codex exec` for pipeline Phase 2/3, no session) and **Debate** (multi-round persistent sessions, existing). All Bash rules preserved: `timeout: 300000` on the Bash tool, `timeout 300` wrapper, `EXIT:$?` check, `HTTPS_PROXY= HTTP_PROXY=`, anti-hallucination, MCP `codex_review()` as legacy fallback. `app/prompts/skills/codex-debate.md`

### Removed
- **`app/prompts/modules/codex-review.md`** — folded into the codex-debate skill. Removed `codex-review` from `modules:` in full-cycle, worker, reviewer; full-cycle body refs now point to the codex-debate skill (Quick Review)

### Added
- **`codex-debate` skill on orchestrator** — `skills: [html-artifacts, vps-deploy, codex-debate]` so the orchestrator can invoke Codex review directly when needed

### Reasoning
Two overlapping Codex prompts (review module + debate skill, both added via separate tasks #43/#46) caused divergence and double maintenance. Consolidated: review is just debate's one-shot mode. Skill > module here because Codex review is invoked on demand (lazy-loaded native skill), not needed in every turn's system prompt.

## v2.16.0 — 2026-06-01

### Fixed
- 🐛 **Zombie workers after restart** — `auto_resume_all` flipped ALL non-idle rows to idle, including archived. Killed workers resurrected every restart. Fix: only flip `running`/`waiting` → `idle`, leave `archived` alone
- 🐛 **Deepgram SSL BAD_RECORD_MAC** — aiohttp 3.13+ defaults trust_env=True → picks up VLESS proxy → TLS record corruption. Fix: explicit trust_env=False + ssl=certifi
- 🐛 **Codex through proxy → Reconnecting 5/5** — Codex CLI inherited HTTPS_PROXY (VPS tunnel) → OpenAI API unreachable. Fix: strip proxy env from codex commands
- 🐛 **User message duplication** — pending bubble not cleaned after SSE delivers real message. Fix: track finalized bubble ref
- 🐛 **send_file silent false-positive** — returned "File sent to TG" on non-JSON TG response. Fix: validate response, explicit error on failure
- 🐛 **Tinyproxy MaxClients exhaustion** — old VPS Tunnel (12338) connections filled Tinyproxy pool. Fix: MaxClients 50→200, Timeout 600→120

### Added
- 🔧 **SSH tunnels in lifespan** — 3 SSH tunnel proxies (Ezhik/Timeweb/Fornex) start/auto-restart from Orchestra lifespan via SSH_TUNNELS env. No separate systemd services needed
- 📋 **Prompt best practices** — Codex bash-primary (not MCP), orchestrator merge/kill safety (worker_wip before kill, cherry-pick on conflict), codex-review module rewritten
- 🔧 **Modular prompts** — `_load_modules()` in manager.py, `modules:` frontmatter key in roles → git-workflow, codex-review, report-format auto-injected
- 📊 **Proxy dashboard** — 4 proxies (Hiddify, Ezhik, Timeweb NL, Fornex NL) configured and benchmarked
- 🔒 **Security** — passwords removed from git history (BFG), .gitignore for sensitive docs + artifacts

### Fixed (11 P2 bugs from review #35 — task #42)
- Reconnect backoff cap (5 failures → give up)
- Hibernate pending messages guard
- GC task protection (`_spawn_bg` for all create_task calls)
- Log retention + WAL checkpoint
- rawMaxTokens from SDK instead of CONTEXT_LIMITS
- ~95 lines dead code removed (backend.py, 3 DB funcs, _react_processing, aliases)

## v2.15.0 — 2026-06-01

### Fixed (13 P1 bugs from review #35 — task #40)
- 🐛 **SDK errors silent (worst bug)** — `_convert` hardcoded `"ok": True`; `ResultMessage.is_error`/`errors`/`permission_denials` and `AssistantMessage.error` never read → auth/billing/rate-limit failures ended the turn as a normal idle, fired auto-report as success. Fix (`backend_claude.py`): `ok = not is_error`, surface `errors` in `turn_end` meta + `AssistantMessage.error` as an `error` event; `permission_denials` logged (informational, does NOT flip `ok`). `session.py _handle_turn_end` logs `turn FAILED` and `_fire_auto_report` skips when `_last_turn_ok` is False
- 🐛 **ThinkingBlock dropped** — extended thinking silently discarded → looked like a hang. Fix: `ThinkingBlock` branch in `_convert` → `"thinking"` event, logged in `_handle_event`
- 🐛 **dead `usage["iterations"]` branch** — SDK never emits `iterations`; the `if iters:` cost loop was dead, `last = iters[-1] if iters else usage` was noise. Fix: deleted, cost from flat usage dict
- 🐛 **billing-derived context_pct wrong** — `_convert` computed ctx% from billing tokens (input+cache) against CONTEXT_LIMITS, overwritten ~1s later by `get_context_usage()` → transient wrong %, spurious "context corrected" jumps. Fix: stopped computing it (meta `context_pct=0`); `_handle_turn_end` keeps prev `_last_context` when incoming is 0; auto-compact triggers on `live_pct` from `_last_context`
- 🐛 **cost under-counts after reconnect/compact** — `total_cost_usd` is cumulative per session_id; on a new session_id it resets smaller → `max(0, new-last)` clamped to 0 → first turn after every compact contributed $0. Fix (`session.py:_handle_turn_end`): reset `_last_cost`/`_last_cost_cached`=0 when `session_id` changes (before the assignment)
- 🐛 **stale prompt on failed inject** — `_template_hash`/`_prompt_injected`/`system_prompt` set BEFORE `backend.send()` → a failed connect left a false "injected" flag, worker ran rest of life on old instructions. Fix: commit inject flags only AFTER `send()` succeeds
- 🐛 **auto-report empty stop_reason** — manager re-read live `worker._turn_logs` for `stop_reason=`, which `_turn_logs` never contains (it holds text/tool only) → always empty. Fix: `_fire_auto_report` captures `_last_stop_reason` at fire time, passes it to `on_idle(... , stop_reason)`; manager dropped the dead scan
- 🐛 **resume drops `waiting` bg-job state** — `auto_resume_all` excluded `waiting` from the resumable filter and flipped it to idle. Fix: capture `was_waiting`, include `waiting` in filter, restore WAITING post-load if `bg_manager.has_active_jobs` (both worker AND orchestrator loops — Codex)
- 🐛 **`_flush_pending` loses batch on error** — `msgs` extracted + cleared, not requeued on send failure. Fix: `_pending_messages[0:0] = msgs` in except
- 🐛 **squash stats first-ref-only** — `_parse_merged_commits` used `.search()` → multi-task squash commit attributed stats only to the first `#N`, co-refs got zero. Fix: `.finditer()`, attribute commit to ALL distinct refs
- 🐛 **`_log`/`_persist` choke the default thread-pool** — shared with git ops (`asyncio.to_thread`) → 10 agents streaming logs starved merge/spawn. Fix: dedicated `_db_executor()` (ThreadPoolExecutor max_workers=4) for DB writes
- 🐛 **blocking git/merge in the event loop** — `_load_from_db` ran `git rev-parse` sync at resume; `/merge` + `/switch-branch` ran `merge_worktree_to_main`/`switch_worktree_branch` (fcntl.flock + ~10 subprocess) SYNCHRONOUSLY in async endpoints → froze the whole loop. Fix: `asyncio.to_thread` for all three
- 🐛 **stream_logs DB connection churn** — `get_logs` opened a fresh `_conn()` (fd + 3 PRAGMAs) every 0.5–2s tick per SSE/TG poller. Fix: `get_logs(conn=...)` optional connection; SSE + TG loops reuse one connection (try/finally close) with adaptive backoff (0.5→3s / 2→5s when idle)
- 🐛 **split-brain DB (tm.py)** — `tm.py` hardcoded its own `DB_PATH`+`_conn()`, ignoring `ORCHESTRA_DB_PATH` → tasks in one file, sessions in another for tests/worktrees. Fix: deleted the dup, `from app.db import _conn` (one path resolution)

**Known tradeoff:** 2 items deferred to separate tasks — #15 (scope-level spawn lock, larger design change) and #17 (persist `_pending_messages` to inbox table, heavy feature for a rare edge).

**Triggered case:** review #35 found 19 P1s; #39 fixed the 7 P0s, this round fixes the P1s. The error-silence bug (#1) was the worst — an autonomous orchestrator can't see a rate-limited/billing-dead worker reporting "done" with empty output.

## v2.14.0 — 2026-06-01

### Fixed (7 P0 bugs from review #35 — task #39)
- 🐛 **compact() re-entry corruption** — no re-entrancy guard + `_compacting` cleared BEFORE the ack send. `_auto_compact()` (ctx>90%) and a manual `compact_worker` could enter `compact()` concurrently, racing on `session_id`/`_backend`/`_listen_task` → `RuntimeError: not connected`, dangling client, or permanent `session_id=None` (full context loss). Fix (`session.py` `compact()`): guard `if self._compacting: return {...}` set synchronously at entry; `_compacting` held True across the ack turn; ack sent via `backend.send()` directly (bypasses `send()`'s pending-queue gate)
- 🐛 **compact 60s blind poll → fabricated success** — `compact()` returned `{"ok": True}` after a 60s sleep-poll regardless of whether the ack turn completed. Fix: `_compact_ack_event` (asyncio.Event) bound to `_compact_ack_gen`; `_handle_turn_end` sets it only for the matching turn gen; `await wait_for(event, 60)` → `{"ok": False, "error": "ack turn did not complete"}` on timeout. A stray `_flush_pending`/heartbeat turn can no longer false-positive the ack (Codex finding #2)
- 🐛 **persist race resurrects stale state** — full-row `save_session(_to_db_dict())` fired from `_handle_turn_end` (438) and `_refresh_context_from_api` (704) on unordered executor threads → a stale `status=running` snapshot could overwrite a fresh `status=idle`. Fix: single-flight persist (`_persist_task` + `_persist_dirty` coalescing in `_persist_loop`). Last snapshot always wins; `get_running_loop()` fails loud off-loop; done-callback logs crashes; in-loop try/except so one DB error doesn't stop future writes
- 🐛 **merge vs remove worktree race** — `merge_worktree_to_main` held `.git/orchestra-merge.lock` but `remove_worktree` took NO lock → removing a worktree mid-merge could abort the merge / leave repo on wrong branch. Fix: `remove_worktree` now acquires the same `fcntl.flock(LOCK_EX)` on `orchestra-merge.lock`
- 🐛 **orphaned worktree on spawn crash** — `create_session` except block only called `delete_session`, leaking the worktree if `start()`/`_inject_skills`/`_safe_format_prompt` raised after creation. Plus `create_worktree` itself leaked if `git worktree add` succeeded but the PROJECT_FILES copy then raised (Codex #4). Fix: rollback inside `create_worktree` (post-add copy wrapped, removes worktree on failure) + `remove_worktree` in the manager except block
- 🐛 **zombie CLI on connect timeout** — `ClaudeBackend.connect()` left `_client` set (subprocess alive) on timeout/exception, never disconnected. `reconnect()` had the identical leak (used by heartbeat/listener recovery), and `except Exception` missed `CancelledError` (Codex #5). Fix: shared `_cleanup_failed_client()`, `except BaseException` → disconnect → re-raise, in both `connect()` and `reconnect()`
- 🐛 **restart_cli → 500** — `/api/sessions/{name}/restart-cli` called `session._disconnect_client()` which doesn't exist (`AttributeError`). Fix: `_disconnect_backend()` + imported `AgentStatus` for `AgentStatus.IDLE`

### Known tradeoff
- **P1-1 (session_id NULL window) fixed as a side-effect** — Codex review (#1) showed the ack turn needs a FRESH SDK session (no resume token) so compaction actually drops context, but the *persisted* `session_id` must NOT be nulled. New `force_fresh` param on `_make_backend`/`_ensure_backend`: ack runs on a fresh session while the old token stays in DB until the ack `turn_end` writes the new one → crash mid-compact now resumes old context instead of losing everything

### Fixed (2nd Codex round — diff review)
- 🐛 **compact COMPACT_PROMPT phase unlocked** — the summary turn (`backend.events()` loop) didn't hold `_lifecycle_lock`, so a `_flush_pending` already past its outer `_compacting` check could interleave a non-ack turn. Fix: wrap the COMPACT_PROMPT phase in `_lifecycle_lock` + recheck `_compacting` INSIDE the flush's lock body (requeues if compact won the race)
- 🐛 **ack-timeout left turn running** — on the 60s ack timeout `compact()` cleared `_compacting` while the ack turn could still be live. Fix: `_disconnect_backend()` + status IDLE before returning, so no stale turn interleaves with the next send
- 🐛 **force_fresh ignored if backend exists** — `_ensure_backend(force_fresh=True)` returned the existing backend. Now disconnects + rebuilds fresh (correctness, not just-happens-to-work in compact)
- 🐛 **spawn cleanup missed CancelledError** — `create_session` except was `except Exception` → cancellation skipped worktree cleanup. Now `except BaseException`

### Reasoning
Full research → plan → Codex review (×1 plan) → implement → Codex review (×1 diff) → fix → tests. Codex found 5 holes in the PLAN + 4 more in the DIFF (1 P0, 3 P1), all incorporated. 17 new tests (`test_session.py`, `test_backend_claude.py`, `test_workspace.py`), 86 passing (6 pre-existing failures on clean HEAD are unrelated — stale `AUTO_REPORT_IDLE_SEC`/`remove` tests). Docs: `docs/tasks/39/{research,plan,findings,codex-diff-review}.md`

## v2.13.0 — 2026-06-01

### Fixed
- 🐛 **[1m] suffix stripped — ALL agents on 200K instead of 1M** — `_make_client()` did `model.replace("[1m]", "")` before passing to CLI. CLI REQUIRES `[1m]` suffix to enable 1M context window (`claude-opus-4-6` = 200K, `claude-opus-4-6[1m]` = 1M). Every [1m] agent in Orchestra silently ran on 1/5 of their context. Fix: pass `self.model` as-is, no stripping
- 🐛 **compact_boundary invisible** — CLI `SystemMessage` with `subtype="compact_boundary"` was not caught by any branch in `_convert()`. Now emits status event "CLI auto-compacted (trigger): pre→post tokens"
- 🐛 **max_tokens from API** — `_refresh_context_from_api()` now updates `max_tokens` from SDK alongside percentage and total_tokens

### Reasoning
CLI changelog 2.1.75: "Added 1M for Opus 4.6 by default for Max plans" — but ONLY when model name includes `[1m]` suffix. Our `_make_client` stripped it → CLI saw `claude-opus-4-6` (200K). Betas approach (`context-1m-2025-08-07`) also doesn't work on subscription ("Custom betas are only available for API key users"). The ONLY way to get 1M on subscription is passing the full model name with `[1m]`.

## v2.12.0 — 2026-05-31

### Fixed
- 🐛 **Phantom context loss** — `context_pct` was reverse-engineered from `ResultMessage.usage` iterations (last iteration tokens / model limit), NOT actual context window size. Replaced with authoritative `get_context_usage()` SDK method. Fixes wildly swinging % after tool-heavy turns
- 🐛 **CLI silent autocompact invisible** — Claude CLI has its OWN internal autocompact that fires independently. We now log when authoritative % diverges >20% from estimate ("context corrected: X% → Y%")
- 🐛 **Compact crash window** — `compact()` NULLed `session_id` and persisted before starting fresh session. Server restart in that window → agent not resumed (auto_resume_all filters NULL). Removed premature persist
- 🐛 **Stale 0% after resume** — `_last_context` not refreshed until first turn_end after reconnect. Now `_refresh_context_from_api()` fires on backend connect
- 🐛 **`_compacting` double-managed** — both `_auto_compact()` and `compact()` set/cleared flag. Now `compact()` is sole owner
- 🐛 **Multiproject scope UNIQUE crash** — `ensure_project()` crashed on UNIQUE(scope) when same agent created tasks in 2+ projects. Now skips scope binding if already bound to different project

### Added
- 🎨 **Role icons from frontmatter** — `icon:` field in role MD files (`app/prompts/roles/*.md`). `/api/role-icons` endpoint serves role→emoji map. Frontend + MCP load dynamically instead of hardcoded maps
- 📁 **New role templates** — `sub-orchestrator.md` (🎯), `reviewer.md` (🔍), `watcher.md` (👁️) with frontmatter + minimal prompts
- ✅ **#34 tg_topic** — `tg_topic` bool parameter for per-agent TG topics. Root orchestrators get `tg_topic=True` automatically. API: `POST /api/sessions/{name}/tg_topic`

### Changed
- `backend_claude.py` — new `context_usage()` method wrapping `ClaudeSDKClient.get_context_usage()`
- `session.py` — `_refresh_context_from_api()` called on turn_end + backend connect; `_auto_compact` simplified to just delegate to `compact()`

### Reasoning
Context bug was a CLUSTER of 5 root causes (RC1-RC5), found by Opus research worker + Codex cross-review. Primary: per-iteration token estimate ≠ actual context window, and CLI internal autocompact runs invisibly. Fix A (authoritative API) + Fix C (no NULL persist) + Fix D (refresh on resume) + Fix E (single flag owner) applied. Full research in `docs/research-context-bug.md`.

## v2.11.0 — 2026-05-31

### Added
- 📁 **Change orchestrator scope/repo_path without losing session** — move an idle orchestrator to a new root folder while preserving its Claude `session_id` (context survives via resume). `POST /api/orchestrators/{name}/change-scope` `{old_scope, new_scope, new_cwd?}` + “Change folder” context-menu item in the dashboard. MVP scope: orchestrator-only, idle-only, no live workers in the old scope
- `db.change_scope()` (`app/db.py`) — single transaction: move `sessions.scope+cwd`, optional `tm_projects.scope` migration (skip on UNIQUE collision), active `bg_jobs.target_scope`, `test_lock.scope`. Gated on `WHERE id=? AND scope=old_scope` → aborts before any migration on a stale/concurrent retry (no partial move)
- `manager.change_orchestrator_scope()` (`app/manager.py`) — guards (orchestrator-only, `is_dir`, no live workers via `_live_workers_in_scope` scanning memory + DB), all under `session._lifecycle_lock` (idle race). Rebuilds `mcp_servers` via `_make_mcp_config` so the lazy reconnect gets the new `ORCHESTRA_SCOPE`; `session.id` (dict key) unchanged

### Changed
- **`_is_safe_path` containment** (`app/main.py`) — replaced `startswith(root)` with `os.path.commonpath` containment. Closes sibling-prefix escape (`/tmproot_escape` no longer passes as inside `/tmp`). Affects ALL path-guarded endpoints, not just change-scope
- **Persist drain fence** (`app/session.py`) — `_persist()` now tracks every `run_in_executor` save future in `_persist_futs` (set, auto-discarded on done); new `_drain_persist()` awaits all pending. change-scope drains in-flight persists after backend disconnect and before the DB transaction, so the transaction is the last writer of `scope+cwd` (prevents a stale `save_session(old_cwd)` clobbering cwd → wrong root after restart)

### Reasoning
`scope` is the orchestrator's identity key (UNIQUE(name,scope)), woven through 5 DB tables, the MCP subprocess env, CWD, and dashboard tabs. The hard part isn't renaming a path — it's keeping the move consistent under concurrent control-plane ops. Three Codex-flagged cross-layer races were closed: stale/partial DB migration, worker-spawn TOCTOU (in-lock re-check; full scope-level spawn lock deferred), and async-persist cwd-clobber (set-based drain). Session context is preserved because `session_id` is independent of scope.

### Known tradeoff
- Worker-spawn TOCTOU is mitigated (in-lock re-check) but not fully closed — a true close needs a scope-level lock shared with the spawn path. Acceptable for the "orchestrator with no live workers" MVP; flagged as follow-up

## v2.10.0 — 2026-05-31

### Added
- 🛡️ **Directory ownership at spawn** — `spawn_worker(..., owned_dirs='["app/api/"]')`. New `owned_dirs TEXT` JSON column in `sessions`. At spawn, overlapping dirs with a live worker (idle/running, same repo) → advisory warning to orchestrator (NOT blocked). Injected into worker prompt as off-limits siblings. `parse_owned_dirs()`/`dirs_overlap()` (prefix-aware) in `workspace.py`
- 🛡️ **Pre-dispatch conflict simulation** — `check_conflict(worker_a, worker_b)` MCP tool + `POST /api/sessions/check-conflict`. `simulate_conflict()` in `workspace.py` dry-runs `git merge-tree --write-tree`, reports conflicting paths (regex-parsed, handles content + modify/delete). Pick merge order before collisions happen
- 🛡️ **Worker WIP visibility** — `worker_wip(name, base_ref)` MCP tool + `GET /api/sessions/{name}/wip`. `branch_wip_status()` shows uncommitted files + unmerged commit subjects before resuming a worker. Returns `{error}` on git failure, never a false "clean"
- 🔒 **Block ScheduleWakeup + Cron\* tools** — removed from all agents via `disallowed_tools`. Orchestra manages scheduling via bg_jobs, agents don't need client-side scheduling

### Changed
- **Safer auto-commit** — `_auto_commit_if_dirty()` (`manager.py`) no longer silently commits dirty source-repo state before spawn. Loud labelled WIP commit (branch + file list), fail-loud on git `status`/`add`/`commit` returncodes, warning surfaced to orchestrator via `spawn_warning`
- **Worker WIP commit prompt** — `worker.md` now mandates descriptive WIP commits (`WIP: #49 — done X, Y; TODO: Z`) instead of bare `WIP`

### Reasoning
Parallel workers in isolated worktrees can silently collide (same files) or bury source-repo work (silent auto-commit). These three advisory tools surface collisions to the orchestrator at decision points (spawn, resume, pre-merge) without blocking — fits the small-team MVP "warn, don't gate" philosophy.

## v2.9.4 — 2026-05-31

### Added
- **Module `codex-review.md`** — single source for Codex review rules: when to call (`exec` for plans, `review` for diffs), `codex_review(target, output, mode)` syntax, iterate-to-consensus, MCP-only (not bash/skill), PROJECT CONTEXT via `context`. Wired into `worker` + `full-cycle` via `modules:`. `app/prompts/modules/codex-review.md`
- **Module `report-format.md`** — single source for report shapes: DONE / WIP-STOPPED / pipeline-gate messages via `send_message`. Wired into `worker` + `full-cycle`. `app/prompts/modules/report-format.md`

### Changed
- **Dedup across roles** — removed inline Codex rules and `<report-format>` block from `worker.md`; replaced inline Codex syntax + DONE format in `full-cycle.md` Phase 2/3 with module references. Roles now carry only role-specific workflow; shared rules live in modules. `app/prompts/roles/worker.md`, `app/prompts/roles/full-cycle.md`

### Reasoning
Follow-up to prompt audit. Codex review + report format were duplicated/divergent across worker and full-cycle (two different DONE formats) → consolidated so the orchestrator parses one shape and Codex usage is consistent.

## v2.9.3 — 2026-05-31

### Changed
- **Git-rule dedup** — removed the `<git>` block from `worker.md` body (duplicated `modules/git-workflow.md`, injected via `modules: [git-workflow]`). The one non-dup behavioral rule ("workers do NOT create/switch branches themselves") moved into the module so it reaches all roles. `app/prompts/roles/worker.md`, `app/prompts/modules/git-workflow.md`
- **AskUserQuestion/Monitor compressed** — two NEVER lines merged into one in `base.md` (both denied via permission hook; kept short in case the model sees the tool). `app/prompts/base.md`

### Added
- **Worker context-limit rule** — `worker.md`: on CONTEXT CRITICAL → finish current sub-task, commit, report progress, do NOT start new sub-tasks. Closes audit gap 5.1
- **Full-cycle gate-idle rule** — `full-cycle.md`: explicit "do NOT self-approve and start implementation before orchestrator approves". Closes audit gap 5.2

### Reasoning
P2 batch from prompt audit (docs/tasks/prompt-audit/). Determinism-focused: dedup keeps git rules single-source (the module), the two new rules close behavioral gaps where Opus might improvise (start new work near context limit / self-approve a plan).

## v2.9.2 — 2026-05-31

### Fixed
- **Stale Codex instruction in worker.md** — `Skill(skill="codex-review")` → `codex_review()` MCP tool. worker.md lagged behind the v2.9.0 migration to the native tool (full-cycle.md already correct) → generic workers asked for Codex review followed the obsolete path. `app/prompts/roles/worker.md`
- **report_bug scope conflict** — base.md said "platform bug only", project CLAUDE.md said "any error". Disambiguated in base.md: `report_bug` = Orchestra platform/MCP/SDK/harness failures; task-code bugs → `docs/tasks/<id>/` + orchestrator message. `app/prompts/base.md`
- **bg_create cron drift** — `<background-jobs>` listed only one-shot types and stated "Jobs are one-shot", but `cron` (recurring, added #26 in v2.9.0) was undocumented for agents. Added `cron` to the list, corrected the blanket one-shot claim. `app/prompts/base.md`

### Changed
- **orchestrator.md `<tools>` trimmed** — removed bare tool signatures that duplicate MCP tool descriptions; kept only non-obvious constraints (must be idle, do-not-retry, debugging-only) and the routing map. ~14 lines saved per orchestrator turn without losing one-path routing. `app/prompts/roles/orchestrator.md`

### Reasoning
Result of prompt audit (docs/tasks/prompt-audit/). Codex cross-review corrected 2 v1 errors (run_in_background IS enforced via permission hook; Agent/Task stripped only for orchestrators, load-bearing for workers) → mass NEVER-rule deletion was cancelled. Calibration: for MVP, determinism > token minimalism. P0 manager.py:391 (orchestrator custom prompt replaces role template) tracked separately as #28 (backend, not in this commit).

## v2.9.1 — 2026-05-31

### Fixed
- 🍒 **merge_worker unrelated histories** — `git merge-base` detects unrelated histories before merge attempt. Falls back to `_cherry_pick_branch()` which replays commits individually via `git cherry-pick --no-commit`. Clean linear history, no fake merge nodes. `workspace.py`

### Changed
- **merge precheck flow** — `git merge-base` check added before `merge-tree --write-tree`. Unrelated histories skip precheck entirely (it would fail anyway) and go straight to cherry-pick strategy
- **Prompt restructuring** — all role prompts migrated to XML tags (`<role>`, `<rules priority="critical">`, `<tools>`, etc). Critical rules deduplicated into `base.md`. English-only prompts
- **Native skills** — skills copied as `worktree/.claude/skills/{name}/SKILL.md` instead of system prompt injection. `_inject_skills_to_worktree()` in `manager.py`
- **Agent role in dashboard** — info panel shows role (worker/orchestrator/full-cycle) in purple
- **Cost precision** — `.toFixed(2)` instead of rounded integer
- **File preview** — Download button + Open in browser button for HTML files

### Added
- 🧠 **Opus 4.8** model option in all frontend model pickers

## v2.9.0 — 2026-05-29

### Added
- 🔁 **Cron agents** (#26) — `bg_create(type="cron", cron_expr="*/5 * * * *")` recurring background jobs. Fires on schedule via `croniter`, survives restart. Non-terminal trigger keeps job `active`. `no_expiry` via `timeout_seconds=0`. `bg_jobs.py`, `db.py`, `mcp_stdio.py`
- 🔌 **MCP per agent** (#24) — `spawn_worker(mcp_servers='{"playwright": {...}}')` attaches custom MCP servers to workers. Persisted in DB (`mcp_servers_custom` column), re-merged on restart. Guards `orchestra` key from override. `manager.py`, `main.py`, `mcp_stdio.py`, `session.py`, `db.py`
- 🛡️ **validate_spawn** (#25) — `can_spawn: [worker, full-cycle]` in role YAML frontmatter. Parent role whitelist enforced in `create_session`. Absent/empty = allow all. `manager.py`, `mcp_stdio.py`
- 🤖 **codex_review MCP tool** — native `codex_review(target, output, mode)` tool. Runs Codex CLI via `bg_create(type="run")`, notifies worker on completion. Replaces bash/skill workaround. `mcp_stdio.py`
- 🎨 **Pretty tool result rendering** — `get_worker_info`, `send_message`, `get_worker_logs` results rendered as styled cards instead of raw JSON. `app.js`
- 🔧 **Skills library** — `app/prompts/skills/` directory with YAML frontmatter. Roles select skills via `skills: [html-artifacts]` in frontmatter. Auto-injected into system prompt via `_load_role_skills()`. `manager.py`
- 📋 **Click-to-copy inline code** — click `<code>` in chat to copy text (like Telegram). URLs/IPs open in new tab instead. Toast notification on copy. `app.js`, `style.css`
- 🔗 **Autolink URLs/IPs** — bare URLs and IP addresses in markdown auto-wrapped in `<a>` tags. DOM walker skips `<a>`, `<pre>`, `<code>`. `app.js`
- 🏷️ **Full-cycle role** — 3-phase pipeline (Research → Plan+Codex → Implement+Codex) with 2 orchestrator approval gates. All artifacts to `docs/tasks/<id>/`. `app/prompts/roles/full-cycle.md`

### Changed
- **codex-review skill removed** — migrated to native `codex_review()` MCP tool. `full-cycle.md` updated to reference MCP tool. `app/prompts/skills/codex-review.md` deleted
- **Reviewer/Watcher roles removed** — vanilla Orchestra ships with orchestrator, worker, full-cycle. Custom roles via constructor

### Fixed
- 🔗 **URL in code copies instead of opening** — clicking URL inside backticks now navigates instead of copying to clipboard. `app.js`

### Known issue
- 🧪 **Pre-existing test failure** — `TestRemoveScope::test_passes_orch_names_to_tg_bridge_when_flag_set` (KeyError 'names'). Unrelated to v2.9 changes

## v2.8.0 — 2026-05-27

### Added
- 🚀 **Deploy script** — `deploy/install.sh root@IP` installs Orchestra on a clean VPS in five minutes: systemd + nginx + `.env` with random credentials. `deploy/`
- 🔐 **Test lock** — global lock for parallel tests. `acquire_test_lock`/`release_test_lock` MCP tools + API + database table (PR #1, Vadim)
- 🌿 **Base branch** — workers branch from any branch, not only `main`. `spawn_worker(base_branch="feature/x")`, `switch_worker_branch(from_ref=)`. Merge into any target (PR #1)
- 📊 **Progress bar** — `update_progress(percent, status)` shows an indigo bar in the agent card and info panels, plus polished rendering in the log feed. `app/static/js/app.js`, `app/session.py`
- 📈 **Usage sparkline** — seven-day chart with weekly navigation (◀ ▶), midnight separators, and splits at resets. Forward-fills data gaps. `app/db.py`, `app/static/js/app.js`
- 💰 **cost_usd_cached** — cost calculation including prompt cache (cache_read×0.1 + cache_create×1.25). `app/backend_claude.py`, `app/session.py`, `app/models.py`
- 🔔 **TG @mention** — `TG_USER_MENTION` environment variable for mentioning the user in agent speech, not agent-to-agent messages. (PR #1)
- 📱 **TG topic collision** — `_pick_unique_topic_name()`: pm-taksa → pm-taksa-2 on collision. Backward compatible. (PR #1)
- 🗑️ **TG topic cleanup** — “Delete TG topics” checkbox in the project deletion modal. (PR #1)
- ⏱️ **Jobs UI** — real-time timer (elapsed + expiry updated every second), click-to-expand details, persistent expanded state
- 💳 **Payment auto-resolve** — `payment_receive` without a client parameter; resolves the client automatically from project scope

### Changed
- **Codex token prices** — corrected from understated ($1.25/$10) to actual ($5/$30 per 1M). `backend_codex.py`
- **TG flood handling** — three-second minimum interval, important/unimportant prioritization, drop tool/status messages during floods. `tg_bridge.py`
- **TG long messages** — `_split_message()` splits into 4,096-character chunks instead of silently truncating
- **Worker prompt** — added `update_progress` to worker instructions

### Fixed
- 🔴 **cost_usd overcounting x85** — CLI returned cumulative cost, which we added as deltas. $24,609 → actual $302. Delta tracking + reconstruction from logs. `session.py`, `db.py`
- 🧟 **Codex zombie detection** — `_codex_turn_loop` did not set IDLE on timeout/error. Heartbeat checked backend=None and skipped. Now: a `finally` block plus zombie check before backend check. `session.py` (#11)
- 💥 **Compact running crash** — event loop accessed a None backend. Guard + disabled frontend button. `session.py`, `app.js` (#12)
- 📝 **report_bug permission denied** — workers wrote directly to a file from their worktree. Now routed through an API endpoint. `mcp_stdio.py`, `main.py` (#13)
- ⚡ **TG icon did not return** — `_handle_turn_end` did not log “turn ended,” so `stream_logs` could not update the icon. `session.py` (#14)
- 🔇 **TG reactions removed** — removed 👍/👂 from every message. `tg_bridge.py`
- 🔓 **Auth on /send** — POST /api/sessions/*/send was accessible without authorization. (PR #1)
- 🤖 **Disallowed sub-agents** — orchestrators spawned Claude sub-agents instead of MCP `spawn_worker`. (PR #1)
- 🗑️ **manager.remove() leak** — did not delete the session from the database, leaving an orphan. (PR #1)
- 🧪 **Test suite revival** — 128 passed, 5 skipped. `conftest.py` mocks, `ORCHESTRA_DB_PATH` isolation. (PR #1)
- 📁 **/tmp allowed** — `send_file` from `/tmp` returned “access denied”
- 🌐 **Global exception handler** — every 500 is now logged with a traceback
- 📊 **5h sparkline** — removed redundant midnight lines (14 over two weeks of data), clipped to the current week

## v2.7.0 — 2026-05-21

### Added
- 🔒 **Dashboard Auth** — cookie-session login/password from `.env` (`DASHBOARD_USER`/`DASHBOARD_PASSWORD`). Deterministic HMAC token survives restarts. 30-day cookie. Backward compatible: no variables means open access. `app/auth.py`, `login.html`
- 🔒 **Security hardening** — full Codex audit, six critical/high fixes: path-traversal deny-list (dotfiles, `.db`, `.key`), internal-token auth for MCP callbacks, upload-extension blocking, `safe_path` on `send_file`/session creation, SSE/log limit caps, rename validation
- 📊 **Task priorities** — 0=critical 🔴, 1=high 🟠, 2=medium 🟡, 3=low 🟢. CSS dots in task panel. Sorted by priority. MCP tools `task_create(priority=)`, `task_update(priority=)`
- 📦 **Worker description** — `description` field on spawn, `update_worker_description()` tool, shown in `list_agents`, info panel, and list_agents bubble
- 🔍 **get_worker_info** — MCP tool returns complete information including system_prompt (500 chars), description, and stats
- ✏️ **update_worker_prompt** — MCP tool updates the worker's system_prompt
- 🗄️ **Archive workers** — `kill_worker` now archives (`status=archived`) instead of deleting. Logs and statistics remain. Archived workers do not block respawn
- 📈 **Session statistics** — `total_turns`, `total_input_tokens`, `total_output_tokens`, `total_tool_calls` tracked per session. `/api/stats` endpoint
- 💰 **Payment journal** — automatic journal task in YouGile. Description updates after every `payment_receive`. Balance + deposits + allocations
- 📂 **File tree auto-refresh** — polls open folders every ten seconds, diff updates without flicker
- 📎 **File drag & drop** — dropping on the textarea uploads the file and inserts its path. Drop hint on dragover
- 🕐 **Message timestamps** — prepend `[HH:MM]` for the LLM; strip in dashboard and TG mirror
- 🔄 **Mid-turn inject restored** — Claude: try inject → fallback queue. Codex: always queue
- 🪞 **Mirror send_file** — files are mirrored to the agent's TG topic
- 📋 **Tab context menu** — right-click a tab to hide/delete it. Wheel scrolling. Hidden-tabs button
- ⚖️ **AGPL-3.0 license** — dual licensing: AGPL + commercial from Seedon LLC
- 🚀 **VPS deployment support** — complete deployment guide, systemd service, nginx config, auth, security audit

### Changed
- **Task prefixes removed** — `PAR-49` → `#49`. Plain numbers, legacy prefixes accepted. `format_task_ref()`, `resolve_task_ref()`, workspace branches `task-N/name`
- **Proxy parametrized** — `HTTPS_PROXY` from `os.environ`, not hard-coded. `cli_path` through `CLAUDE_CLI_PATH` environment variable
- **Merge auto-stash** — `merge_worker` automatically stashes/pops a dirty main repository
- **MCP scope passthrough** — `task_get`/`task_update` pass scope for disambiguation
- **Rename full** — updates system_prompt identity, git branch, and database
- **Compact blocks send()** — messages queue during compaction and arrive afterward
- **Auto in_progress** — `spawn_worker`/`switch_worker_branch` with task_id automatically set `in_progress`
- **bg_jobs cleanup** — triggered/expired/cancelled jobs older than 24 hours are automatically deleted
- **Scope MCP servers** — workers receive MCP configuration from the project's `.mcp.json` (Playwright, etc.)

### Fixed
- 🔴 **Crash loop sr/nt** — `_handle_turn_end` used removed variables, causing a listener reconnect loop
- 🔴 **Compact interrupted** — incoming messages during compaction → empty summary → cascading crash
- 💲 **Double “kk”** — price “8k” + frontend “k” = “8kk”. Backend already formats it
- 🏷️ **Universal prefix strip** — `replace('PAR-','')` → regex `/^[A-Z]+-/` for every prefix
- 🔐 **Internal token for every API** — MCP tools authorize with a Bearer token, not only `/send`
- 🍪 **Cookie auth on /send** — the frontend sent a cookie while middleware checked only the token
- 📋 **Ambiguous task numbers** — scope resolves identical numbers in different projects
- 📂 **Hidden files visible** — removed the `startswith('.')` filter from `/api/files`
- 🖱️ **Text selection restored** — document-level drag listeners prevented selecting text
- 📊 **Sync indicator removed** — useless sync indicator for projects without YouGile
- 🎯 **Task detail modal** — pretty commits display, scope passthrough, informative task_update bubble
- 🔄 **YouGile description sync** — description is pushed in `push_update`; previously only title and column were

## v2.6.0 — 2026-05-14

### Added
- 🔄 **Auto-resume ALL sessions on restart** — `auto_resume_all()` restores orchestrators AND workers from DB (was orchestrators-only). Sessions that were `running` at shutdown get a restart notice injected after 3s: `[system] Orchestra server restarted. Your session was restored — continue where you left off.`
  - `_inject_restart_notice()` in `manager.py` — delayed inject with error handling
  - `auto_resume_orchestrators()` kept as backward-compat wrapper
- 🤝 **Cross-orchestrator awareness** — `_other_orchestrators_block(scope)` dynamically generates a list of all other orchestrators with project names, injected into `ORCHESTRATOR_SYSTEM_PROMPT`. Each orchestrator knows who else exists and can `send_message` them. List updates on restart/compact
- 👤 **TG sender name** — all messages from TG now include `[from TG: Name]` prefix so agents know who's writing. Works for text, photos, files, video, audio, voice, video notes, stickers
- 🔒 **TG polling auto-restart** — `_safe_polling()` wraps `dp.start_polling` with crash recovery (auto-restart after 10s) + logging. No more silent polling deaths
- 📊 **Usage cache persistence** — `data/usage_cache.json` survives server restarts. No more empty usage bar after reboot caused by Anthropic rate limit + cold cache
- 🔀 **merge_worker MCP tool** — orchestrator can merge a worker's branch into main with one call. `git merge-tree` precheck detects conflicts before merging. fcntl lock serializes parallel merges. Auto-commits dirty worktree. `workspace.py`, `mcp_stdio.py`, `main.py`
- 🛑 **stop_worker MCP tool** — interrupt + idle without destroying session/worktree. Resumable via send_message. Separate from kill_worker (full delete)
- 📈 **Worker progress tracking** — `update_progress(percent, status)` MCP tool. Green glow progress bar in sidebar. Resets on new task. `session.py`, `db.py`, `mcp_stdio.py`, `app.js`
- 🖼️ **TG images as photos** — `send_file` auto-detects images (.jpg/.png/.gif/.webp/.bmp) → `send_photo()` for inline preview. `as_document=True` forces file attachment
- 🌿 **Git status in worker cards** — sidebar shows `branch+N 💾N "last commit"` per worker. `GET /api/git-status?scope=` with 10s server cache. Green/yellow/gray coloring
- 💓 **Persistent client heartbeat** — 60s heartbeat detects silent listener death, auto-reconnects with inject notice. Silence warning >300s. Full tracebacks on crash

### Changed
- **Usage cache TTL 120→300s** — backend and frontend polling aligned at 5min to reduce Anthropic API rate limit hits
- **TG logger** — `tg-bridge` logger now has `StreamHandler` + `DEBUG` level, all TG events visible in journalctl
- **SSE disconnect leak** — `stream_session_logs` generator now checks `request.is_disconnected()`, stops on tab close

### Fixed
- 🟢🟡 **TG topic status desynced from frontend** — single source of truth via `_any_running_in_scope(scope)`. When orchestrator finishes turn but workers still running → stays 🟢 (was: immediately 🟡). When ANY worker goes idle → `_notify_scope_idle()` checks scope → flips to 🟡 only when ALL idle
  - `check_scope_idle()` in `tg_bridge.py` — public function called from `session.py` and `stream_logs`
  - `_notify_scope_idle()` in `session.py` — fires on every worker IDLE transition, not just auto-report
- 🟢🟡 **TG topic status on startup** — `_sync_all_topic_statuses()` sets correct 🟢/🟡 on all topics when bridge starts
- 🪞 **TG mirror formatting** — mirror messages now receive `converted` text + `entities` from `md_convert()` (was: raw plain text without formatting). All 3 send paths: text/status, tool, tool_result

## v2.5.0 — 2026-05-11

### Added
- 🚀 **Persistent client + mid-turn message injection** — replaced "fresh client per turn" with persistent client per session. `send()` → `client.query()` directly via SDK stdin transport. No more pending queue, debounce, turn boundary waiting. Messages inject mid-turn as system-reminders
  - `_ensure_client()` — connects once, reuses across turns
  - `_persistent_listen()` — infinite loop over `receive_messages()`, does NOT disconnect on ResultMessage
  - `_disconnect_client()` — clean shutdown helper
  - Auto-reconnect: detects dead listener, retries `query()` on failure
  - Removed: `_pending`, `_debounce_task`, `_turn_task`, `_run_turn()`, `_arm_debounce()`, `_on_debounce()`, `debounce_sec`
- 📊 **Usage status bar** — global bar at top of dashboard. OAuth API (`/api/oauth/usage`) with 120s cache, shows 5h/7d utilization with HSL gradient color (green=under budget, yellow=on track, red=burning fast), reset progress % in parentheses. `/api/usage` endpoint combines Anthropic data + per-agent cost from DB
- 🎯 **Spawn worker bubble** — card with `🚀 Spawning name` + model badge pill (color-coded) + markdown task preview + system prompt + repo path. Single click expands all
- 🌐 **WebSearch result renderer** — bracket-counting JSON parser for Links format, Perplexity markdown with token/cost header, standalone detection when `lastTool` is null. Collapsible (5 lines preview)
- 🔍 **ToolSearch bubble** — `🔍 Loading: query` → `✅ Loaded: ToolName` on result
- 🐛 **report_bug bubble** — `🐛 Bug: title` with collapsible description
- 🖼️ **Base64 image rendering** — tool_results with image data render as `<img>`, not raw base64 text
- 📝 **Textarea resize upward** — drag handle above textarea, pull up to expand (bottom of screen = can't drag down)
- 🔄 **Auto-compact for orchestrators** — removed `not self.is_orchestrator` exclusion, orchestrators auto-compact at >90% context

### Changed
- **`interrupt()`** — uses `client.interrupt()` SDK method instead of asyncio task cancellation
- **`compact()`** — stops listener first (race condition fix), bracket-counted JSON parse, disconnects cleanly
- **Turn timeout** — tracked via `_turn_start` timestamp instead of `asyncio.wait_for()`
- **send_message bubble** — split by lines (5 preview), re-render full on expand. No more mid-word cuts
- **Tool result expand** — line-based preview (was char-based), single element with maxHeight (no gap/separator), universal click-to-expand on all bubble types
- **Model aliases** — `claude-opus-4-6` → `claude-opus-4-6[1m]` auto-resolve
- **Worker custom prompt** — `_safe_format_prompt()` replaces `str.format()`, only substitutes known placeholders. Resume correctly extracts custom portion
- **Load-more tool_result matching** — `_findLastBefore()` constrains querySelector to prepended batch only

### Fixed
- **WebSearch `isEdit` bug** — spawn_worker/WebSearch/ToolSearch bubbles had `dataset.isEdit='1'` which caused tool_result handler to early-return, silently swallowing results
- **WebSearch regex** — replaced fragile regex with bracket-counting parser for Links JSON arrays (handles truncated SDK output, multi-item arrays, special chars)
- **Load-more rendering** — old messages now use `addChatEntry()` with full custom bubbles
- **compact() race condition** — listener paused before iterating `receive_messages()`
- **Persistent client dead process** — `_ensure_client()` checks `_listen_task.done()`, `send()` retries with reconnect on `query()` failure
- **Universal click-to-expand** — audit of all handlers, WebSearch and Read .md fixed (were hint-only)

## v2.4.0 — 2026-05-10

### Added
- 🎤 **TG Voice** — Deepgram Nova-3 voice transcription in the TG bridge
- 📷 **TG Media** — complete support for photos, documents, video, video_note (ffmpeg), audio, stickers, and forwards with captions. File + transcription caches
- 🔄 **TG Debounce** — state machine IDLE→COLLECTING→WAITING_MEDIA. Five-second debounce + 30-second media timeout. Batches messages into one turn
- 📂 **File preview** — clicking a file opens a modal. Markdown renders through marked.js, images through `<img>`, code with horizontal scrolling. `/api/files/content` + `/api/files/raw` endpoints
- ✏️ **Diff view** — Google `diff-match-patch` for character-level inline highlighting. LCS line diff + inline highlighting for similar lines (>40% common). Five-line preview + expand
- 📖 **Read view** — code viewer with shimmer skeleton, five-line preview + expand. Images render as `<img>`
- ✍️ **Write view** — content displayed as a diff, all green
- 📨 **send_message bubble** — `📨 → target` + Markdown preview instead of raw JSON
- 📜 **Prompt viewer** — three sections (📦 Platform / 🎭 Role / ✨ Custom) with actual substituted names
- 📋 **Compact mode** — 📋/📄 toggle in the header. Tools collapse to one line and expand on click
- 🖼 **Images everywhere** — user messages, Read tool, and text images are clickable and open file preview
- 💰 **Sidebar price** — green `$X.XX` beside the model
- 🌐 **WebSearch rendering** — title link + snippet instead of JSON
- 🔧 **Autocommit** — `git add -A && commit "wip:"` before `spawn_worker`. Worktree starts from current code, avoiding conflicts
- ⚡ **Seamless turn** — after ResultMessage, pending input starts a new turn immediately (0 ms instead of 2.5-second debounce)
- 📊 **stop_reason logging** — every turn records `stop_reason=X, num_turns=N`
- 🎼 **Orchestra skill** — `/orchestra` Claude Code skill in `app/skills/orchestra/SKILL.md`
- 🔒 **XSS fixes** — 3 innerHTML→textContent fixes (Codex review)

### Changed
- **max_turns 25→50** — workers are no longer cut off on large tasks
- **kill_worker** — now `DELETE` for complete removal, not `POST /stop`; ghost workers no longer remain
- **Inject removed** — every message enters the pending queue; no losses or duplicates
- **Logs limit 200→5000** — older messages are visible in chat
- **MAX_CHAT_NODES 500→5000** — the DOM no longer truncates history
- **Deepgram Nova-2→Nova-3** — more accurate for Russian at the same price
- **Orchestrator prompt** — mandatory system_prompt for workers (template + examples), file conflict rule, CTO delegation
- **Worker prompt** — bash rules (no polling loops), identity placeholders

### Fixed
- **TG flood control** — retry with backoff instead of falling back to plain text
- **TG error logging** — explains why formatted send fails
- **HTML injection in tool_result** — escape `<>` before innerHTML
- **Paste preview** — preserved and restored when switching agents
- **Markdown everywhere** — user messages and [from:worker] messages all render through marked.js
- **chat-bot border** — `#1e293b`→`rgba(99,102,241,0.1)` (visible)
- **diff-code overflow** — `break-all`→`overflow-wrap: anywhere`
- **Read skeleton** — shimmer placeholder until tool_result arrives
- **Expand hint** — rHint moved; querySelector works
- **Restart without confirm** — removed the confirmation dialog
- **Prompt viewer identity** — actual names instead of the `{worker_name}` placeholder
- **Custom prompt after reboot** — custom section survives hot reload
- **streamBubble on orchestrator change** — reset during switching
- **initFilePanel drag listeners** — guard against accumulation
- **refreshSessions stale scope** — capturedScope check

## v2.3.1 — 2026-05-09

### Added
- 🗜 **compact_worker MCP tool** — orchestrator can compact a worker's context (summary → reset session → continue fresh). Tested: 81%→17%, 56%→16%, 20%→16%
- ⚠️ **Context warning >90%** — platform auto-appends `⚠️ CONTEXT CRITICAL` to worker messages
- 🚫 **AskUserQuestion + run_in_background denied** — blocked via `can_use_tool` deny
- 🔧 **Tool+result merged** — one bubble on frontend, one expandable on TG
- 🎨 **Tool icons** — 🖥 Bash, 📖 Read, 🎼 orchestra, 🔌 MCP
- 📝 **Draft per agent** — unsent text preserved when switching
- 🔗 **URL linkify** — clickable links in tool_result
- 💊 **Status badge** — pill with colored bg on idle/running text

### Fixed
- **compact_worker timeout** — was 30s, compact takes ~40s → empty error → double compact. Now 120s
- **Prompt placeholders** — `{orchestrator_name}` was literal in hot-reload for workers
- **Scroll on switch** — chat now scrolls to bottom when opening agent
- **Timestamps overlap** — inline block instead of absolute positioning

## v2.3.0 — 2026-05-09

### Added
- 📱 **TG Bridge** (`app/tg_bridge.py`) — mirrors orchestrators to Telegram group topics.
  Auto-creates topic per orchestrator, bidirectional messaging, real-time log streaming.
  Separate bot (`@orchestraClaude_bot`), config in `.env` / `data/tg_bridge.json`
- 📬 **Kesha inbox server** (`inbox_server.py` in kesha-tg-bot) — HTTP endpoint :18081,
  Orchestra → Kesha via `notify_kesha` MCP tool → shows in Telegram chat
- 🔄 **Auto-report** — workers that finish without `send_message` get force-reported to
  orchestrator with last 3 text outputs. `[from:worker] [auto-report]` format
- 💉 **Message inject** — messages to RUNNING agents injected via `client.query()` immediately,
  no waiting for turn end. Fallback to pending queue on failure
- 🔥 **Prompt hot-reload** — updated `app/prompts/*.md` injected on first turn after restart.
  `[Orchestra platform note]` tag avoids prompt injection detection
- 📊 **Context tracking** — `input + cache_creation + cache_read` from last iteration,
  per-model limits (Opus 1M, Sonnet 200k), cache hit % in agent info panel
- 📈 **Context bar** — colored progress bar per agent in sidebar (green/yellow/red)
- 🌐 **Cross-project messaging** — `list_orchestrators()` discovers all orchestrators,
  `send_message` fallback searches by name across all scopes (`ensure_loaded_any`)
- 🐛 **report_bug MCP tool** — agents file bugs to `BUGS.md` with timestamp/reporter/scope
- ⟳ **Restart button** — dashboard header, `sudo -n systemctl restart orchestra`
- 💊 **Orchestrator tabs** — pill buttons replace dropdown, recent-first, live status dots
- 🖼 **Image paste** — Ctrl+V upload with md5 dedup, preview under input, render in chat
- ⚡ **Status badges** — `⚡ interrupted`, `⚡ system prompt updated` as centered badges in chat
- 📐 **Shared prompts** — `app/prompts/base.md` + `orchestrator.md` + `worker.md`, shared platform knowledge

### Fixed
- **Stop deleted logs** — `POST /stop` now calls `unload()` (preserves DB), not `remove()` (cascade)
- **Scroll hijack** — `showWaitingIndicator` respects `wasAtBottom`, no re-creation in refresh loop
- **Context 0%** — usage is dict not object (`.get()` not `getattr()`), last iteration not sum
- **Context 227%** — top-level usage sums all API calls, context = last iteration only
- **Trailing slash** — scope normalized with `rstrip("/")` at creation and lookup
- **Ghost workers** — `kill_worker` for DB-only sessions deletes from DB directly
- **MCP not visible** — `.mcp.json` no longer copied to worktrees (was overriding Orchestra MCP);
  `mcp_stdio.py` invoked by absolute path (was failing with `-m` from non-orchestra CWD)
- **SendMessage vs send_message** — prompts explicitly say `mcp__orchestra__send_message`
- **Interrupt stuck** — now awaits task cancellation, drops client, sets IDLE + persist
- **Newlines lost** — tool input via `json.dumps(indent=2)`, `white-space: pre-wrap` on frontend
- **Lost messages** — SSE user_message replaces pending bubble instead of skipping
- **Prompt injection** — `[SYSTEM UPDATE]` tag softened to `[Orchestra platform note]`
- **Repeated prompt inject** — `system_prompt` synced after inject, no more every-turn spam

### Changed
- **spawn_worker scope** — uses orchestrator's ORCHESTRA_SCOPE, not repo_path (workers visible in list_agents)
- **Prompts split** — old `orchestrator_prompt.md` + `worker_prompt.md` → `prompts/base.md` + role-specific
- **SDK 0.1.74** — updated from 0.1.72

## v2.2.0 — 2026-05-05

### Added
- 🗑️ **Delete orchestrator** — `DELETE /api/orchestrators/{name}` removes orchestrator + all
  workers in scope (active sessions, worktrees, DB records). Dashboard button `✕ Delete` with
  confirm dialog. `manager.remove_scope(scope)` handles cleanup.
- 💾 **Remember last orchestrator** — `localStorage` saves `lastOrchScope`/`lastOrchName` on
  switch, restores on page load. No more "always opens first in list".

### Fixed
- **Stop deleted logs (critical)** — `POST /stop` called `manager.remove()` which ran
  `DELETE FROM sessions` → `ON DELETE CASCADE` wiped all logs. Now stop calls `unload()`
  (stops session, removes from memory, preserves DB). Only explicit Delete removes from DB.
  - Triggered case: kesha-tg-bot orchestrator stuck running after interrupt, used stop to
    unstick it → 2318 log entries deleted by cascade. User saw empty chat.
- **Scroll hijack on history read** — three sources of forced scroll-to-bottom:
  1. `showWaitingIndicator()` unconditionally set `scrollTop` — now checks `wasAtBottom`
  2. SSE handler had duplicate scroll check after `addChatEntry` (which already handles it)
  3. `refreshSessions` re-created waiting indicator every 3s (SSE removed it → refresh
     recreated → scroll). Removed re-creation from refresh loop.

## v2.1.0 — 2026-05-04

### Added
- 📡 **SSE realtime logs** — `GET /api/sessions/{name}/stream` replaces polling for chat
- 🏥 **Health check loop** — detects crashed worker tasks every 60s
- 🔌 **Systemd service** — `orchestra.service` with auto-restart and Hiddify proxy
- 🎨 **Smart color picker** — unique color per worker, least-used fallback
- 🏷️ **Auto sender tag** — server adds `[from:name]`, workers send plain text
- 📴 **Offline CSS** — Tailwind/marked/DOMPurify bundled locally

### Fixed
- **Auto-resume crash** — error sessions marked stopped on startup
- **cli_path** — dynamic via `shutil.which("claude")`
- **Worker logs** — filtered (text/tool/error only), no raw dumps
- **tool_result parsing** — unwraps `{"result":"..."}` wrapper
- **Proxy** — `HTTPS_PROXY` set in session.py, manager.py, service file

## v2.0.0 — 2026-05-03

### Changed
- **External stdio MCP server** — MCP tools now run as separate process (`app/mcp_stdio.py`)
  via FastMCP, communicating with Orchestra API over HTTP. Replaces in-process `create_sdk_mcp_server`
  which caused deadlocks (SDK issue #425). External process = no shared event loop = no hang.
- **Simplified session.py** — removed persistent client, locks, _is_connected, _cleanup_client.
  Each turn: create fresh ClaudeSDKClient → connect → query → receive → disconnect (in finally).
  Root cause of ALL hangs was accumulated state in persistent connection.
  Proven: direct SDK test = 5 MCP calls in 17s. Old session.py = hang on 3rd call.
  New session.py = 18 MCP calls in 85s, zero hangs. -328 lines, +166 lines.
- **Worker communication via HTTP** — workers send reports via `curl POST /api/sessions/{name}/send`.
  Orchestrator receives via debounce → new turn. No MCP inject needed.
- **System CLI** — uses system Claude CLI 2.1.126 via `cli_path` instead of bundled 2.1.117

### Added
- 📬 **Worker Inbox** — `inbox` DB table + `GET /api/sessions/{name}/inbox` endpoint.
  `send_to_worker` queues messages in inbox. Real delivery semantics.
- 📋 **Job Registry** — `jobs` DB table + `GET /api/jobs` endpoint + `list_jobs` MCP tool.
  spawn/kill create tracked jobs with status (queued/executing/succeeded/failed).
- ⏱️ **Turn timeout** — 300s hard deadline on `_listen()`, 60s on `connect()`.
  TimeoutError → ERROR status. No more infinite hangs.
- 🔒 **Scoped lookups** — `find_worker(name, scope)`, `find_session_id_by_name(name, scope)`.
- 🧪 **`.mcp.json`** — project-level MCP config for local testing from Claude Code
- `alwaysLoad: true` — MCP tools skip ToolSearch deferral (v2.1.121 feature)

### Removed
- `create_sdk_mcp_server` in-process MCP (deadlock source)
- Persistent client connection in session.py (accumulation source)
- `.env` copy to worktrees (security fix)
- Prompt rule "max 2 MCP calls" (no longer needed)
- SDK monkey-patches (buffer, stdin) — no longer needed

### Fixed
- **Duplicate user_message logs** — send() logs once, _run_turn no longer duplicates
- **Timestamps** always visible in white on dashboard
- **pytest discovery** — testpaths=["tests"], norecursedirs for worktrees

## v1.3.0 — 2026-05-02

### Fixed
- **SDK MCP tool hang — root cause found and workarounds applied** — in-process MCP tool calls
  (`create_sdk_mcp_server`) hung after 2-3 calls per turn. Root cause: SDK `Query._read_messages`
  single read task handles both control_request routing AND bounded message stream (`max_buffer_size=100`).
  When buffer fills, read task blocks on `send()` → control_requests never reach Python MCP handlers → CLI
  waits for control_response forever → deadlock. SDK issue #425 (open, no PR).
  - **SDK patch: buffer 100→10000** — `query.py` monkey-patch, prevents backpressure up to 10000 messages
  - **SDK patch: stdin kept open** — `wait_for_result_and_end_input()` no longer closes stdin when SDK MCP
    servers present. Needed for persistent connections with multiple query() calls
  - **Spawn queue** — `spawn_worker` MCP tool no longer does heavy work (git worktree + session start)
    inside the MCP handler. Jobs enqueued to `asyncio.Queue`, processed by background supervisor task
    with 0.5s delay to let control_response flush first (Codex review finding)
  - **git worktree via to_thread** — `create_worktree()` sync subprocess moved to `asyncio.to_thread()`
    to avoid blocking event loop during MCP response path
  - **Inject removed** — `session.send()` no longer calls `client.query()` inject on RUNNING sessions.
    Messages queue in `_pending`, processed as new turn when session goes IDLE. Inject caused transport
    deadlock (both directions: worker→orch and orch→worker)
  - **Worker HTTP callback** — workers send reports via `curl POST /api/sessions/{name}/send` instead of
    MCP `send_message` inject. Eliminates transport deadlock entirely for worker→orchestrator communication
  - **Async DB writes** — `_log()` and `_persist()` via `run_in_executor()` to avoid blocking event loop
  - **include_partial_messages=False** — reduces stream event volume in SDK bounded buffer
  - **Orchestrator prompt: max 2 MCP calls per response** — prevents hitting CLI tool call limit per turn
  - Triggered case: every test with orchestrator + worker — spawn→list_workers→get_worker_logs chain hung
    on 3rd MCP call every time. Single MCP calls worked fine (5s). Multiple calls = deadlock.

### Changed
- **SDK pinned** — `claude-agent-sdk>=0.1.72` in pyproject.toml. Was unpinned, any `uv sync` could
  break everything. v0.1.72 fixes silent MCP tool result loss (v0.1.70+)

### Added
- **Spawn queue** — `SessionManager.enqueue_worker_spawn()`, `_spawn_worker_loop()` background task
- **Session error callback** — `AgentSession.on_error` + `SessionManager._on_session_error()` moves
  errored sessions from active to archived automatically

## v1.2.0 — 2026-05-01

### Changed
- **Data layer refactor — single source of truth** — `SessionManager` is now the sole data gateway.
  `manager.archived: dict[str, dict]` holds stopped/error sessions in memory. `list_sessions()` reads
  purely from memory (active + archived), zero DB merges. `stop()` moves session from active → archived.
  `tools.py` has zero direct DB imports (except `get_logs`). `main.py` reduced from 4 DB fallback paths to 0.
  - `load_archived()` at startup populates archived dict from DB
  - `find_worker()`, `find_session_id_by_name()`, `archive_by_id()`, `get_session_id()` — new manager methods
  - `ensure_loaded()` skips archived sessions (no zombie resurrections)
  - `kill_worker` for DB-only sessions now properly archives via `archive_by_id()`
  - 10 new TDD tests for archived dict behavior (107 total)
  - **Before**: 8 code paths with direct DB access scattered across tools.py + main.py, different formats (AgentSession vs dict), merge logic, fallback reconnects
  - **After**: manager = memory cache, DB = write-through backup + logs storage. One path, one format

## v1.1.0 — 2026-05-01

### Added
- 📡 **Streaming text** — responses appear live as chunks, not after full generation. `StreamEvent` + `content_block_delta` handling
- 📎 **Tool results visible** — MCP tool outputs (`ToolResultBlock`) shown in chat with 📎 prefix
- 🪦 **Agent archive** — stopped/killed workers get hash suffix (e.g. `worker-1-abc123`), move to archive section. Name freed for reuse. Chat history preserved, read-only
- 🏷️ **Model registry** — `app/models.py` single source of truth. Aliases resolved (`sonnet` → `claude-sonnet-4-6`). API validates, dropdown loads from `/api/models`
- 🔄 **restart_worker** MCP tool — kill + respawn in one call
- 📊 **Context display** — `5% (12k/200k)` format, cached on agent switch

### Fixed
- **Worktree preserved on stop** — `stop()` no longer deletes worktree. Only explicit `kill/remove` does
- **Auto-resume rehydrate** — all fields restored from DB (worktree_path, branch, created_at)
- **`_run_turn()` exceptions** — done callback logs errors, sets ERROR status
- **Error UX** — no "waiting for response" after 404/error. Debounce cancelled on failure
- **Stopped agent resume** — writing to stopped agent auto-resumes it (fallback cwd if worktree missing)
- **Duplicate names** — stopped agents archived with hash, name freed for new workers
- **`list_workers`** — shows active + archived workers

### Changed
- `shutdown_all` — orchestrators stay `idle` (not stopped) for auto-resume. Workers get stopped with worktrees intact

## v1.0.0 — 2026-04-30

Complete rewrite from MVP v0.4. One class, one way, Apple-level simplicity.

### Added
- 🏗️ **`AgentSession`** — single SDK wrapper replacing both `Worker` and `Orchestrator` classes. One class for all agents, config-driven (model, system_prompt, mcp_servers)
- 🌿 **`workspace.py`** — isolated worktree management. Scope-namespaced paths (`worktrees/{scope_slug}/{name}`), fail loud, no silent fallbacks
- 🔧 **MCP tools for orchestrator** — `spawn_worker`, `send_to_worker`, `list_workers`, `get_worker_logs`, `kill_worker`. Orchestrator manages workers natively via MCP, not prompt hacking
- 🔧 **MCP tools for workers** — `send_message` (to any agent), `list_agents`. Workers can communicate with orchestrator and each other
- 📝 **System prompts** — `orchestrator_prompt.md` and `worker_prompt.md` in `app/`. Editable .md files, not hardcoded strings
- 🖥️ **Dashboard v2** — single-screen UI: chat with any agent (left), agent list + info (right). Click to switch between orchestrator and workers. Markdown rendering, debounce indicator, adaptive polling (500ms when waiting, 3s idle)
- 📊 **Message debounce** — multiple rapid messages batched into one (2s window, like Kesha). Visual ring timer on pending messages
- 💉 **Live inject** — messages sent while agent is RUNNING inject directly into current turn (no queue, no "session busy")
- 🧪 **97 TDD tests** — `test_db.py` (29), `test_workspace.py` (16), `test_session.py` (18), `test_manager.py` (14), `test_api.py` (20). Written before code (RED→GREEN)
- 🔑 **UUID primary keys** — `UNIQUE(name, scope)` for display, UUID internally. No collisions between scopes
- 📡 **Multi-orchestrator support** — one dashboard, multiple orchestrators (one per project). Picker in header, scope filtering
- 🔄 **Auto-resume** — orchestrators survive server restart (status stays `idle`, SDK resumes via `session_id`)
- 🛡️ **Permission fix** — `default` + `can_use_tool` auto-approve instead of `bypassPermissions` (known regression: Claude Code #36497, #37157, #36923)

### Removed
- `worker.py` — replaced by `AgentSession` in `session.py`
- `orchestrator.py` — replaced by `AgentSession` in `session.py`
- `callbacks` table — replaced by session logs with `type="notification"`
- 18 API endpoints → 9 (one resource `/api/sessions`)
- `max_turns` parameter — SDK manages this
- `data/orchestrator_session` file — session_id now in SQLite
- Separate notifications tab — everything in chat

### Changed
- **DB schema** — `sessions` + `logs` (was `workers` + `logs` + `callbacks`). UPSERT, CASCADE, `busy_timeout=5000`, `foreign_keys=ON`
- **API** — one resource `/api/sessions`. Pydantic validation, proper HTTP status codes (404/409/422), no `{"ok": false}`
- **Dashboard** — HTML/CSS/JS split into separate files. DOM API rendering (no innerHTML XSS). Cursor-based log pagination

### Architecture
```
app/
  main.py            — FastAPI, 9 endpoints
  session.py         — AgentSession (single SDK wrapper)
  manager.py         — SessionManager (registry + lifecycle)
  workspace.py       — git worktree create/remove
  db.py              — SQLite (sessions + logs)
  tools.py           — MCP tools for orchestrator + workers
  orchestrator_prompt.md
  worker_prompt.md
  static/css/style.css
  static/js/app.js
  templates/dashboard.html
```

### Process
- 4-round Codex (GPT-5.5) adversarial review of spec before implementation
- TDD for all modules: tests written first, then minimal code
- Codex code review (Round 5) caught 4 real bugs post-implementation
