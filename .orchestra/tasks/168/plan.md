# #168 — centralized weekly quota hard gate: implementation plan (Phase 2)

Основание: `docs/tasks/168/research.md`. Код ещё не написан.

## Цель

Запретить любой **новый provider turn non-orchestrator worker**, если weekly quota bucket его
модели (`window_minutes == 10080`) использован на `>=95%`, либо trustworthy weekly observation
не удалось получить. Уже `RUNNING` turn не прерывается: steering и reconnect проходят. Stop,
model change и orchestrator turns не спрашивают quota gate.

## Зафиксированные решения

| Решение | Контракт |
|---|---|
| Threshold | `utilization >= 95` блокирует; `94.9` разрешает |
| Weekly selection | Только `window_minutes == 10080`; 5h/прочие окна не влияют |
| Buckets | Claude → `anthropic`; обычные Codex → `codex`; Spark → `codex_spark`; только positively resolved Grok → `not_applicable`; неизвестная/невалидная модель → `unknown` |
| Freshness | Observation содержит `observed_at`; age `<300s` fresh. При age `>=300s` — один bounded target-provider refresh; failure/missing/malformed → `unknown` и fail-closed |
| Exemption | `session.is_orchestrator`; не строка role/model |
| Уже идущий ход | `status == RUNNING`: steering/reconnect разрешены без admission |
| Новые ходы | idle/waiting send, internal retry, auto-continue, pending flush, каждый idle Claude compaction send, conservative native Codex compact, `codex_review` |
| Управление | `interrupt/stop` и `change_model` не вызывают admission; следующий turn проверяет новую модель |
| Alternatives | Только другой bucket с fresh weekly `<95` из того же observation; Grok не предлагается; model IDs не хардкодятся |
| Authority | Execution-boundary check обязателен; create/spawn check — ранний UX preflight и всегда перепроверяется при delivery |

## Архитектура

### 1. Один pure contract: `app/quota_gate.py`

Новый модуль не импортирует `session`, `manager` или FastAPI и содержит:

- `WEEKLY_WINDOW_MINUTES = 10080`, `WORKER_WEEKLY_LIMIT_PCT = 95`,
  `QUOTA_OBSERVATION_MAX_AGE = 300`;
- `quota_bucket_for_model(model)`:
  - resolve alias через `models.resolve_model()`, затем получить зарегистрированный runtime через
    `models.backend_for_model()`/`runtime_registry.get_runtime()`; ошибка resolve/registry не
    является exemption и даёт `unknown`;
  - Claude runtime → `anthropic`;
  - exact Spark model → `codex_spark`;
  - остальные Codex runtime models → `codex`;
  - только положительно распознанный runtime `grok` → `None`/`not_applicable`, без fallback в
    Codex; любой другой зарегистрированный, но не покрытый policy runtime и любая неизвестная
    модель → `unknown` и fail-closed для worker start;
- immutable `QuotaDecision` со следующими полями:
  `state` (`available|blocked|unknown|not_applicable`), resolved `model`, `provider`, provider
  label, `weekly_utilization`, `observed_at`, `valid_until`, `reset_at`, `alternatives`,
  `reason`;
- pure `evaluate_worker_admission(model, providers, observed_at_by_provider, now)`:
  - weekly window выбирается по 10080 минутам; если их несколько — любой `>=95` блокирует,
    reset для сообщения = максимальный будущий reset среди блокирующих weekly windows;
  - отсутствующее/нечисловое weekly, отсутствующий/naive/future/stale timestamp → `unknown`;
  - alternatives вычисляются тем же вызовом только из fresh buckets `<95` и исключают target;
- `QuotaGateError(RuntimeError)`, который строится из `blocked|unknown` decision и отдаёт
  canonical API envelope: `code=weekly_quota_blocked|weekly_quota_unknown`, ясный message,
  `retryable=false`, optional informational `retry_after_seconds`, details с provider,
  utilization, observed/reset timestamps и alternatives.

**Текст ошибки:** различает “Claude weekly 97% >= 95%” и “Claude weekly status unknown/stale”;
никогда не называет provider доступным без fresh `<95`. Если alternatives пусты — предлагает
дождаться reset/telemetry recovery, а не выдумывает Claude/Codex.

### 2. Observation + bounded refresh: `app/routes/system.py`

Существующие provider caches остаются единственным источником telemetry; DB/schema не меняются.

Добавить `current_quota_observation(required_provider="", refresh_if_stale=True, now=None)`:

1. Нормализует current data через существующий `_provider_usage_snapshot()`.
2. Возвращает `providers` + per-bucket timestamps:
   - `anthropic` ← `_usage_cache["ts"]`;
   - `codex` и `codex_spark` ← один `_codex_usage_cache["ts"]`.
3. Если target observation age `>=300s`, под `asyncio.timeout(12)` refresh-ит **только семейство
   target provider**; Spark делит refresh с Codex. Два явных per-family singleflight lock
   (`anthropic`, `codex`) не позволяют параллельным callers дублировать upstream fetch. После
   lock/wait caller обязательно повторно читает cache и не refresh-ит, если другой caller уже
   положил observation моложе 300 секунд.
4. Refresh failure не подставляет старое как fresh: timestamp остаётся старым, evaluator вернёт
   `unknown`. Error text сохраняет класс/причину refresh failure.

Для target-only refresh уточнить `_get_usage_data(force_refresh=True, required_provider=...)`:
при непустом `required_provider` остальные provider families берутся из caches, а не вызываются
последовательно. `required_provider=""` сохраняет прежний refresh-all dashboard contract.

Сохранить endpoint path `GET /api/usage/readiness?model=` (не вводить hot-MCP/old-route новый
путь), но заменить его содержимое на `QuotaDecision` с `policy="worker-weekly-v1"`. Direct
`limit_wake.provider_readiness()` остаётся без изменений: его 100%-семантика wake scheduling
отличается от worker admission.

### 3. Authoritative execution lease без блокировки stop: `app/session.py`

Добавить session-local async admission adapter (узкий callback/service; в тестах заменяется fake),
который получает `QuotaDecision`. Provider interpretation остаётся в `quota_gate.py`, cache access —
в `routes/system.py`; `session.py` не читает cache dicts.

Конкретная граница импортов: `quota_gate.get_worker_admission(model, observation_loader=None)`
при переданном loader полностью тестируема без routes; production default лениво импортирует
`routes.system.current_quota_observation` **внутри async-вызова**, когда модули приложения уже
загружены. Endpoint передаёт loader явно. Поэтому `routes.system` может импортировать pure evaluator,
а import-time цикла `routes → manager → session → routes` не возникает.

Quota I/O нельзя выполнять под `_lifecycle_lock`. Для каждого start path использовать двухфазный
паттерн:

```text
under lifecycle lock:
    RUNNING → steer/reconnect immediately (no gate)
    orchestrator → start immediately (no gate)
    snapshot model + stop_generation
release lock → obtain/refresh QuotaDecision
reacquire lifecycle lock:
    RUNNING → steer (another send started while checking)
    stop_generation changed → cancel this delayed start
    model changed or decision expired → release and evaluate again
    decision blocked/unknown → raise before logs/status/backend start
    decision available → perform existing start path
```

Добавить monotonic `_turn_start_cancel_gen`, увеличиваемый `interrupt()`. Это закрывает новую race:
stop во время telemetry refresh обязан отменить отложенный start, а не позволить ему ожить после
возврата provider I/O. `change_model()` не увеличивает stop generation: model mismatch инвалидирует
старый decision и запускает evaluation для нового bucket.

Decision считается authoritative только если под lock совпали resolved model и `now < valid_until`.
Quota error происходит до `_log("user_message")`, status `RUNNING`, `_ensure_backend()` и
`backend.send()` для idle delivery. Это не оставляет ложного “доставлено” и не будит provider.

Internal `_rate_limit_retry`, `_retry_after_server_error`, `_auto_continue` продолжают вызывать
`self.send()`: после `turn_end` они `IDLE/WAITING`, поэтому проходят тот же gate без special
continuation exemption.

### 4. Pending + compaction execution boundaries

`_flush_pending()`:

- не вынимать `_pending_messages` до available decision;
- получать decision на execution time, а не в момент queueing;
- после reacquire повторять compacting/status/model/stop-generation checks;
- при `blocked|unknown` оставить payload byte-for-byte, оставить session idle/waiting, записать
  один quota status/error и вызвать `on_turn_blocked` **после выхода из lifecycle lock**;
- не auto-retry и не создавать flush spin. Повтор разрешён после нового sender action, provider
  switch или свежего quota observation.

`SessionManager` связывает `on_turn_blocked` с parent notification:

- точный `parent_name` получает одно deduplicated сообщение на неизменный decision signature;
- текст содержит worker, retained message count, закрытый bucket и fresh alternatives;
- если parent отсутствует/не является доступным orchestrator, fallback — существующий
  `report_undelivered` корневому orchestrator scope; orchestrator exemption не даёт рекурсии;
- delivery failure оставляет log/fact по существующему undelivered contract.

`compact()`:

- worker admission перед native Codex compact;
- Claude: отдельная admission непосредственно перед summary `backend.send(COMPACT_PROMPT)` и
  отдельная перед acknowledgement `backend.send(preamble + ...)`;
- если summary уже получен, а acknowledgement admission стал `blocked|unknown`, compact считается
  **deferred, но не committed**: сохранить bounded summary в `last_summary` и structured result/log,
  восстановить `pre_compact_session_id`, вернуть status в `IDLE`, очистить `_compacting`/ack state,
  не append-ить `session_id_history`, не сбрасывать `_prompt_injected` и не запускать ack/flush
  автоматически. Следующий явный compact начинает с сохранённой старой session и может повторить
  idempotent summary request; ровно один успешный acknowledgement выполняет commit-переход и ровно
  один раз добавляет history/reset prompt state;
- blocked auto/manual compact возвращает structured quota result, не меняет session id/status,
  не теряет pending payload и не препятствует model change/stop;
- orchestrator compact проходит exemption.

### 5. Server/tool UX edges

`CreateSessionRequest`/`SessionManager.create_session` получают
`planned_initial_turn: bool = False`. Только `spawn_worker` выставляет его в `true`; обычное создание
idle session из dashboard остаётся управляющей операцией и не блокируется. При флаге manager
выполняет UX preflight после model/pipeline/role resolve и определения `is_orch`, но до
worktree/scaffold/publish side effects. Orchestrator roles проходят; worker `blocked|unknown`
возвращает `QuotaGateError`. Initial task delivery всё равно повторно проверяется authoritative
session gate — crossing между create и send не является обходом.

`app/routes/sessions.py` отдельно ловит `QuotaGateError` на create/send/compact и возвращает
canonical `{result, error}` с HTTP 429 и `retryable=false`. Dashboard/Telegram получают тот же
читаемый `str(error)`; frontend-файлы не меняются.

`app/mcp_stdio.py`:

- `_quota_refusal()` парсит `policy=worker-weekly-v1` и состояния `blocked|unknown`; malformed/
  transport/legacy policy fail-close для операций, которые сам MCP запускает;
- `codex_review` сохраняет authoritative preflight до создания bg job;
- `spawn_worker` передаёт `planned_initial_turn=true`, полагается на server create preflight
  (role-aware, до worktree) и на execution recheck при initial send; не держит третью model-only
  copy;
- удалить quota preflight из `change_worker_model`: это управляющее действие не расходует turn;
- `send_message` не получает отдельный preflight — server execution gate authoritative;
- убрать `_GATED_PROVIDERS` и hardcoded `_QUOTA_ALTERNATIVE`; error/envelope приходит из единого
  server decision.

## Файлы

### Новые

- `app/quota_gate.py` — pure decision, bucket mapping, structured error.
- `tests/test_quota_gate.py` — boundary/freshness/bucket/alternatives contract.

### Изменяемые

- `app/routes/system.py` — observed timestamps, target-only bounded refresh, readiness endpoint.
- `app/session.py` — two-phase execution checks, stop generation, flush/compact boundaries.
- `app/manager.py` — role-aware create preflight, wiring/deduped parent notification.
- `app/routes/sessions.py` — structured 429 responses for create/send/compact.
- `app/mcp_stdio.py` — consume shared endpoint, codex_review gate, remove change-model/hardcoded copy.
- `tests/test_usage_readiness.py` — weekly95 endpoint + non-wall-clock timestamps.
- `tests/test_session.py` — lifecycle/race/retry/flush/compact behavior.
- `tests/test_manager.py` — create preflight/orchestrator exemption/parent notification.
- `tests/test_mcp_quota_gate.py` — spawn/review/model-change tool behavior.
- `tests/test_api.py` — canonical HTTP error and switch→send integration.

### Не трогать

- SQLite schema/history; `usage_snapshots` уже достаточно.
- `limit_wake.provider_readiness()` и wake-job 100% semantics.
- Frontend JS/CSS/templates.
- Provider credentials, API keys, model routing manifest.
- Grok quota behavior.
- systemd/prod/restart/deploy.

## Behavioral verification matrix

| Case | Expected observable result |
|---|---|
| Claude weekly `94.9`, fresh | worker idle send calls backend once |
| Claude weekly `95.0/97`, fresh | HTTP/MCP error names Claude, percent, threshold/reset; status/backend/log unchanged |
| Codex weekly `95`, Spark `1` | Sol blocked, Spark worker allowed; alternative says Codex Spark only if fresh |
| Spark `95`, Codex `2` | Spark blocked, Sol allowed; buckets not conflated |
| Claude 5h `100`, weekly `94` | allowed; short window irrelevant |
| Missing/malformed weekly or observed_at | worker start blocked as `weekly_quota_unknown` |
| age `299.9s` | no refresh, evaluate cache |
| age `300s` | exactly one bounded target refresh; concurrent callers reuse result |
| stale + refresh failure | blocked unknown; stale alternative omitted |
| Grok model + Codex blocked | not applicable; Grok not blocked/suggested as Codex |
| unknown/malformed model | `unknown`; worker start fails closed and does not reach backend |
| worker `RUNNING` at 97 | steering reaches current backend; quota loader not called |
| reconnect while `RUNNING` | existing reconnect tests remain green; no admission |
| idle retry/auto-continue at 97 | new backend send blocked |
| stop during slow refresh | stop completes before refresh release; delayed send never starts |
| model changes during refresh | old permit rejected; new model/bucket evaluated |
| `change_model` from Claude97→Codex2 | change succeeds; next send starts on Codex |
| `change_model` to blocked provider | change persists; next send blocks (no bypass) |
| worker pending flush crosses 94→95 | payload retained, backend untouched, parent notified once |
| parent notification | reaches exact exempt parent; no recursive quota failure |
| Claude compact summary/ack | each start admits separately; ack denial retains summary but commits no session/history/prompt transition; later success commits once |
| Codex native compact | blocked for worker, allowed for orchestrator |
| spawn worker at 97 | create endpoint fails before worktree/publish; no orphan |
| dashboard creates idle worker at 97 | session creation allowed (`planned_initial_turn=false`); first send blocks |
| 94 at spawn, 95 before initial delivery | session may exist, delivery blocked by authoritative recheck |
| `codex_review` at Codex95 | no bg job created; error suggests only fresh alternatives |
| orchestrator send/compact at provider97 | allowed; root chat remains operational |

Async race tests above run **3 consecutive times** after their focused pass.

## Mutation verification matrix

Каждая mutation делается отдельно: unique-anchor `grep -c` → fresh `cp F F.bak` → mutation →
focused test must turn red → `mv F.bak F` → marker count confirms restore. Никаких git checkout/
stash для отката незакоммиченной реализации.

| Mutation | Test that must fail |
|---|---|
| `>= 95` → `> 95` | exact Claude/Codex/Spark 95 boundary |
| weekly filter `window_minutes == 10080` → accept any window | 5h100 + weekly94 stays allowed |
| Spark bucket → `codex` | opposite Codex/Spark utilization cases |
| unresolved/unsupported model → `not_applicable` | unknown model fails closed while positively resolved Grok remains allowed |
| stale/unknown `blocked` → `available` | age300, missing timestamp, malformed weekly |
| remove `observed_at` age check | age300 triggers refresh/fail-close |
| remove post-singleflight cache reread | concurrent same-family requests perform more than one upstream fetch |
| ignore `required_provider` target | Anthropic request unexpectedly invokes Codex fetch (and vice versa) |
| include stale alternative | dynamic alternatives freshness test |
| remove session idle admission | idle send backend-is-never-called test |
| move admission before RUNNING branch | active steering test (loader must remain uncalled) |
| remove stop-generation recheck | stop-during-refresh race |
| remove model/expiry recheck under lock | model-change/expired-decision race |
| remove `_flush_pending` admission | crossed-threshold pending test |
| clear pending on quota denial | byte-for-byte payload retention test |
| remove parent notification callback | exact-parent notification test |
| remove Claude summary admission | compact summary backend-not-called test |
| remove Claude ack admission | quota-cross-before-ack test |
| commit Claude session/history before successful ack | ack-denial + later-success test detects duplicate/premature transition |
| remove native Codex compact admission | native compact worker test |
| remove create preflight | no-worktree/no-published-session spawn test |
| remove `codex_review` preflight | no-bg-job test |
| restore change-model preflight | Claude97→Codex2 control action test |
| remove orchestrator exemption | orchestrator send/compact tests |
| add admission to reconnect | existing-running reconnect test |

Mutation log and exact red counts go into `docs/tasks/168/report.md`; a green mutation is a failed
test seam and must be strengthened before completion.

## Test commands for Phase 3

Focused after each ticket:

```bash
uv run python -m pytest -x -q tests/test_quota_gate.py tests/test_usage_readiness.py
uv run python -m pytest -x -q tests/test_session.py tests/test_manager.py
uv run python -m pytest -x -q tests/test_mcp_quota_gate.py tests/test_api.py
```

Then repeat the new async race subset three times. Final full suite per pipeline:

```bash
uv run python -m pytest -x -q > /tmp/pytest-168.log 2>&1
```

Read `/tmp/pytest-168.log` once. If `git status` shows `uv.lock`, stop and restore the dependency
barrier rather than commit lockfile churn.

## Tickets

### T1 — Weekly95 decision + fresh observation endpoint

- Files: `app/quota_gate.py`, `app/routes/system.py`, `tests/test_quota_gate.py`,
  `tests/test_usage_readiness.py`.
- AC:
  - `GET /api/usage/readiness` returns `policy=worker-weekly-v1` and the same pure decision used
    later by execution boundaries.
  - Claude/Codex/Spark exact `94.9/95` and 10080-minute selection pass the matrix; Grok is
    `not_applicable` without Codex fallback; an unknown/malformed model is `unknown` and denied.
  - `observed_at` age 300 triggers one bounded target-family refresh; missing/malformed/stale after
    refresh is `unknown`, not available.
  - Concurrent Anthropic admissions perform one Anthropic fetch and zero Codex fetches; concurrent
    Spark admissions perform one shared Codex-family fetch, then evaluate Codex and Spark as
    separate buckets. Removing the post-lock reread or ignoring `required_provider` turns these
    focused tests red.
  - Alternatives contain only fresh other quota buckets below 95; no model/provider hardcode.
  - Mutations: threshold, weekly filter, Spark/unknown mapping, freshness polarity, age check,
    singleflight reread, target isolation and stale alternative all make focused tests red.
- blocked-by: none

### T2 — Authoritative idle-turn admission without breaking control/current turns

- Files: `app/session.py`, `app/manager.py`, `app/routes/sessions.py`, `tests/test_session.py`,
  `tests/test_manager.py`, `tests/test_api.py`.
- AC:
  - Idle/waiting worker send, internal retry and auto-continue cannot set RUNNING/connect/send when
    decision is blocked/unknown; route returns canonical non-retryable 429.
  - `RUNNING` steering/reconnect and orchestrator send never call quota loader.
  - Stop and model change never call quota loader; Claude97→Codex2 then send succeeds, switching to
    a blocked provider then send fails.
  - Provider refresh happens outside lifecycle lock. Stop-during-refresh cancels delayed start;
    model/expiry races re-evaluate before start.
  - `planned_initial_turn=true` create UX preflight runs after role resolution but before
    worktree/publish; orchestrator creation passes; ordinary idle-session creation stays allowed;
    worker initial delivery rechecks execution state.
  - New async races pass three consecutive runs.
  - Mutations: idle gate, gate-before-steering, stop/model/expiry rechecks, create preflight,
    orchestrator exemption and change-model control all turn their tests red.
- blocked-by: T1

### T3 — Deferred messages and compaction cannot bypass the gate

- Files: `app/session.py`, `app/manager.py`, `tests/test_session.py`, `tests/test_manager.py`,
  optionally `app/routes/sessions.py` only for compact error envelope already established in T2.
- AC:
  - `_flush_pending` evaluates at execution time, retains exact payload/order/status on denial,
    performs no backend work and does not spin-retry.
  - Exact parent receives one deduplicated notice with retained count and fresh alternatives;
    fallback reaches root orchestrator if parent delivery is impossible.
  - Claude summary and acknowledgement starts each admit separately; native Codex compact admits;
    worker denial leaves session id/pending/status recoverable, orchestrator compaction passes.
    If quota crosses only before Claude acknowledgement, the generated summary is persisted and
    returned, no session/history/prompt transition is committed, compact is not stuck, and one later
    allowed compact commits that transition exactly once.
  - Async flush/compact races pass three consecutive runs.
  - Mutations: remove flush/summary/ack/native admissions, payload retention, parent notification,
    or prematurely commit Claude compaction before ack — each focused test turns red independently.
- blocked-by: T2

### T4 — MCP spawn/review UX uses the central policy without blocking model control

- Files: `app/mcp_stdio.py`, `tests/test_mcp_quota_gate.py`, affected MCP contract tests only if an
  existing shared error assertion requires the new canonical envelope.
- AC:
  - `spawn_worker` sends `planned_initial_turn=true`; blocked/unknown worker quota receives
    role-aware server preflight before worktree, while orchestrator-role spawn is exempt. Crossing
    after create is caught on initial send and reported as `created=true, delivery=failed` without
    automatic resend.
  - `codex_review` at Codex `>=95` or unknown creates no bg job; at `<95` it behaves unchanged.
  - `change_worker_model` has no quota preflight and can switch to an available provider; subsequent
    send remains authoritative.
  - `_GATED_PROVIDERS`, `_QUOTA_ALTERNATIVE` and independent 100%-only logic are removed; tool error
    uses server-provided alternatives/details.
  - Malformed/transport/legacy admission response does not start Codex review.
  - Mutations removing review/server spawn preflight or restoring change-model refusal turn focused
    tests red.
- blocked-by: T1, T2

## Completion boundary

Phase 3 ends only when T1→T4 AC, mutation matrix, repeated async races, full suite and mandatory
Codex implementation review are complete. No restart/deploy is part of #168 implementation.
