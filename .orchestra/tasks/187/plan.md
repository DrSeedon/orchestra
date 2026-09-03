# #187 — План quota-aware routing

## Результат

После реализации точную модель для обычного рабочего хода выбирает только сервер. На каждой
безопасной границе нового хода он получает **сервером выведенный** класс работы, читает свежие
квоты, применяет одну versioned policy и либо выбирает runtime/model, либо сохраняет вход в
durable queue с громким статусом. Аргумента `task_class` или обычного exact-model override у
модели не будет.

Решение обязано работать в трёх конфигурациях Codex-подписки:

- `all` — обычная работа Codex-first до пользовательских 90/95, Claude — fallback;
- `review_only` — Codex допустим только для server-class `review`, обычная работа идёт в Claude;
- `off` — Codex исключён, а тот же router продолжает защищать Claude 5h/7d и явно деградирует
  cross-runtime review до same-runtime.

До явной активации новый код работает в `manifest_default`: новый spawn берёт role manifest
model, существующая session остаётся на current model, а review сохраняет текущий Codex default;
quota balancing и automatic switch выключены. Поэтому merge и единственный обязательный restart
не меняют маршрутизацию сами по себе; финальные параметры #186 и решение #190 включаются потом
одной hot-update policy без второго restart.

## Зафиксированные решения

### Один owner и доверенные классы

Owner выбора runtime/model — `RuntimeRouter` в новом `app/runtime_router.py`. Старый
`app/quota_gate.py` после миграции callers перестаёт быть вторым decision-maker: его freshness,
readiness и error-envelope входят в router/observation service, а независимое правило
«проверить уже выбранную модель» удаляется.

`GET /api/usage/readiness?model=...` и MCP exact-model preflight удаляются вместе с gate: они
принимают модель до server decision и иначе остались бы вторым owner. Read-only диагностика —
только policy GET/explain с trusted class/provenance и active revision; operational
`limit_wake.provider_readiness` остаётся reset detector, но не выбирает runtime/model.

Каждый HTTP workload mutation (spawn, new turn/steering, review, retry/status transition) обязан
нести `X-Orchestra-Routing-Contract: routing-v1`; guard проверяется до DB/worktree/backend side
effect. Новый MCP сначала probe-ит policy endpoint и не вызывает старый server при 404/mismatch;
новый server отвечает 426 старому MCP/browser без header или с другой version. TG/bg internal
dispatch не пересекает process-version boundary и вызывает тот же typed service API с
`contract_version=ROUTING_CONTRACT_VERSION`. Legacy fallback нет.

Router не читает смысл prompt и не принимает `task_class` от агента. Минимальный enum выводится
по серверному entrypoint и сохранённому provenance:

| Class | Единственный источник | Семантика |
|---|---|---|
| `worker_general` | server path создания нового worker work item | новая обычная работа; текст/role не переклассифицируют её |
| `orchestrator_free_text` | новый idle turn orchestrator | новая неструктурированная работа |
| `review` | `review_artifact`, не поле запроса | assurance phase; сначала runtime, отличный от runtime автора/реализации |
| `continuation` | сохранённый `logical_work_id`/`task_id` или server-generated failover intent | продолжение уже начатой работы; допускает stickiness/reserve |

Неизвестный class fail-loud до создания worktree/backend. Spark не становится кандидатом:
trusted `spark_leaf` workflow в текущем коде отсутствует, а проверять его критерии по свободному
тексту запрещено. Редкий >258K контекст и принудительная модель остаются отдельным операторским
control plane, а не скрытым normal-routing override.

### Измерение #186 и параметры, не константы

#187 импортирует `weekly_runway()` из #186 (`app/quota_runway.py`) и не копирует формулу `D`,
рабочий календарь, baseline query, нормализацию окна или NULL-семантику. Baseline берётся готовым
`db.runway_window_start_pct(reset_at)` из #186; своего helper у #187 нет. Latch ключуется только
по возвращённому `RunwayVerdict.window_id`: сырой Anthropic `resets_at` гуляет между
`06:59:59` и `07:00:00` для одного окна и не является стабильным ключом. Общий baseline helper
выбирает snapshot только когда utilization `IS NOT NULL` **и**
`seven_day_resets_at != ''`; честный `0` не исключается. Семьдесят исторических строк с
`pct=0`/пустым reset — артефакт молчавшего источника, не честный baseline. Last-known из
прошлого/неполного окна не подставляется.

`RoutingPolicyV1` хранится одним JSON-документом в `kv` под versioned key и читается из DB на
каждом новом decision. Narrow authenticated GET/PUT API валидирует документ целиком и заменяет
его одной транзакцией. Evaluator не содержит числовых fallback-констант; тесты передают policy
fixture. Поля:

```text
schema_version, revision, mode = manifest_default | quota
codex_access = all | review_only | off
models = {claude: <validated Claude model>, codex: <validated Codex model>}
claude = {
  alert_deficit_hours,
  weekly_unavailable_pct,
  weekly_min_remaining_pp,
  five_hour_unavailable_pct
}
codex = {normal_below_pct, unavailable_at_pct}
```

Числа Codex 90/95 записываются как явно пользовательские policy values, не как результат
замера. Claude values подставляются только из финального #186. Даже экспортированный #186
`DEFAULT_ALERT_DEFICIT_HOURS` не является runtime fallback: activation явно сохраняет число,
а evaluator при его отсутствии отказывает. `mode=quota` нельзя сохранить,
пока обязательные поля выбранных runtime отсутствуют, нечисловые, неупорядочены или вне 0..100.
При `codex_access=off` Codex-поля могут отсутствовать; Claude-поля остаются обязательными — так
single-runtime не превращается в bypass.

`weekly_runway().no_data` делает только Claude candidate недоступным. `D` выше
`alert_deficit_hours` ставит durable latch `reserve_only` до **смены window id**; падение D внутри
той же недели не открывает пул обратно. Отдельные `unavailable` условия — weekly hard stop,
остаток меньше `weekly_min_remaining_pp`, фактический 5h hard stop, terminal provider limit или
stale/unknown observation. Для 5h нужен текущий `resets_at`; при его отсутствии candidate
unknown, а не «примерно свободен».

Policy пишет только узкий `replace_routing_policy_document`, общего `kv_set` не появляется.
`runtime_routing_latches` выражает храповик наличием `(provider, window_id)`: `CHECK` запрещает
иное состояние, а `BEFORE DELETE ... RAISE(ABORT)` закрывает настоящий rollback. Колонка
`first_decision_id` намеренно остаётся ссылкой на первое решение, взведшее окно; последующие
решения делают только `ON CONFLICT(provider, window_id) DO NOTHING`. Широкий `INSERT OR IGNORE`
запрещён, чтобы не проглотить CHECK и другие ошибки схемы.

### Одна матрица решения

Порядок constraints фиксирован и не меняется по entrypoint:

1. загрузить и провалидировать одну policy revision;
2. получить fresh observation только для разрешённых policy runtime;
3. исключить runtime по `codex_access`, capability и quota state;
4. применить continuation stickiness: текущий runtime сохраняется в `normal`, а в
   `reserve_only` — только для доказанной `continuation`;
5. для `review` сначала исключить runtime автора/реализации; если независимого eligible runtime
   нет, ослабить **только** independence и записать `degraded_review_independence`;
6. stable tie-break по policy order (`codex` затем `claude` для новой eligible работы);
7. если кандидата нет — `queued`, никогда silent wait или last-known fallback.

`reserve_authorized` не берётся из `priority=0` и не заявляется агентом. Его доказуемые причины:
server-linked continuation уже начатого logical work и отдельное human-authenticated emergency
действие. Неограниченная новая задача reserve не получает.

В `review_only` Codex участвует только на шаге 5. В `off` список кандидатов состоит из Claude;
Claude implementation review продолжается на Claude с warning, пока Claude quota-eligible. При
Claude `reserve_only` новая обычная работа стоит в очереди, continuation допускается; при
Claude `unavailable/no_data` очередь остаётся durable и сразу видима пользователю.

Local refresh → decision → admission сериализуются одним lock на bucket/window. Это убирает
гонку локальных readers, но 90/95 остаётся best-effort: без измеренной цены Codex turn и provider
reservation один ход или внешний consumer может пересечь границу. В audit это называется
`best_effort_threshold`, а не «гарантированный 5% резерв».

Policy PUT и admission дополнительно используют один process-wide lock с неизменным порядком
захвата: policy lock → bucket locks по provider id. Admission держит его от чтения revision до
durable decision и backend submit acceptance (`submitted`) либо durable `queued`; для spawn это
включает session/worktree/backend creation, но не окончание модельного хода. PUT ждёт уже начатые
admissions и только затем коммитит новую revision. После возврата PUT ни один backend **не начнёт** работу по старой revision; уже
`submitted/running` ход не прерывается. DB commit перед dispatch повторно сверяет revision, а
mismatch заставляет пересчитать решение.

### Решение и наблюдаемость

Каждое решение получает `decision_id` и сохраняет:

- policy revision/mode и `process_started_at`;
- class, logical work id, requesting runtime и immutable implementation runtime set;
- свежесть, utilization/window id и derived state каждого кандидата;
- выбранные runtime/model либо `queued` reason;
- reserve reason, `degraded_review_independence`, `best_effort_threshold`.

Runtime выполнения пишется в каждую submitted delivery и агрегируется как immutable set на
`logical_work_id`. При запуске review server создаёт subject snapshot
`(logical_work_id, target_digest, implementation_runtimes)` и дальше не читает current session
model. Один runtime исключается из независимого review; mixed `{claude,codex}` не имеет третьего
независимого кандидата и идёт по quota tie-break с `degraded_review_independence=mixed`. Для
pre-migration/unlinked artifact пустой set даёт `unknown_review_provenance`: router не обещает
independence, выбирает quota-eligible runtime детерминированно и пишет degraded audit.

`GET /api/usage/routing-policy` отдаёт активную revision, contract version, process start,
latched windows и последнее решение. `POST /api/usage/routing-policy/explain` прогоняет pure
decision над переданными **synthetic observations** без spawn/send/model switch; это единственный
rollout dry-run. PUT меняет policy hot. Policy mutation и emergency authorization принимают
только валидную dashboard session cookie; `INTERNAL_TOKEN` агента сам по себе получает 403.
При выключенной dashboard auth mutation fail-loud недоступна, а система остаётся в
`manifest_default`. Общего settings API, второго config-файла и agent-writable override не будет.

### Durable ingress: at-most-once вместо слепого replay

Новая таблица `work_deliveries` — один ingress для `intent_kind=spawn|turn|review_result` из
HTTP/MCP, TG, background wake и pending flush. Spawn intent хранит scope/name/session spec при
`target_session_id=NULL`, поэтому all-unavailable не создаёт worktree/session, но и не теряет
задачу. Источник создаёт stable `delivery_id` **до первого POST**:

- TG: детерминированно из chat/topic/update/message id;
- background job: job/fire id;
- dashboard/HTTP: client idempotency key;
- MCP: session id + FastMCP request identity; один operation id создаётся до HTTP и повторно
  используется его внутренним status resolution. Ответ/error всегда возвращает `delivery_id`,
  а после outcome-unknown агент вызывает status этого id, не новую отправку.

Повторный id с тем же target/payload возвращает существующую row; тот же id с другим digest —
409. Новая MCP tool invocation считается новым логическим действием; transport retry той же
invocation обязан сохранить request identity. В caller contract нет «повтори сообщение
вслепую»: status endpoint/tool либо подтверждает row, либо разрешает retry только доказанного
pre-submit state.

Состояния и допустимые переходы:

```text
queued -> claimed -> dispatching -> submitted -> completed
                     |              |
                     +-> delivery_unknown
queued/claimed -> failed   # только доказанный pre-submit terminal failure
```

- claim делается CAS; только просроченный `claimed` lease можно вернуть в `queued`;
- `dispatching` пишется непосредственно перед `backend.send`;
- только typed proof «backend submit не начинался» возвращает row в `queued`;
- exception/timeout/crash после `dispatching` без такого proof → `delivery_unknown`;
- `submitted`, `completed` и `delivery_unknown` никогда не replay автоматически;
- `delivery_unknown` создаёт громкое уведомление с id/status action; пользователь решает,
  проверять worktree/logs или создавать новый logical delivery;
- terminal quota после `submitted` создаёт **новый linked continuation intent**, но не повторяет
  исходный prompt.

`submitted` сохраняет `session_id`, `turn_gen` и native submission ref. На startup строки
`dispatching/submitted`, у которых нет доказанного terminal event, переходят в
`delivery_unknown` с уведомлением, но не replay.

`AgentSession._pending_messages` заменяется ссылками на delivery rows. Несколько queued messages
можно по-прежнему собрать в один backend turn, но batch получает собственный `attempt_id`, и все
его rows переходят `dispatching/submitted` атомарно как одна группа. Ошибка не вставляет строки
обратно в in-memory list.

Когда все runtime недоступны, ingress отвечает `202 queued` с `delivery_id`, причинами по каждому
runtime и известным reset time, пишет status в target + parent/user channel и показывает очередь
в routing-policy GET. При unknown telemetry reset не выдумывается. Восстановление квоты будит
queue dispatcher; отсутствие восстановления не скрывается повторным polling от агента.

Для настоящей аварии оператор может одним cookie-authenticated запросом авторизовать **уже
существующий queued `delivery_id`**. Разрешение single-use, содержит reason/author/time, не меняет
class и не может прийти через MCP/internal token. Это проверяемый вход в 90–95 reserve; общего
флага task priority или «все следующие ходы emergency» нет.

### Runtime-neutral review

Текущий Codex-only `codex_review` заменяется одним `review_artifact`. Его schema не принимает
model/class/implementation runtime: server class всегда `review`; requesting session определяет
linked logical work, а runtime provenance берётся только из immutable submitted deliveries, не
из её current model.

`app/review_runner.py` строит один bounded command для выбранного runtime:

- Codex — текущий `codex exec/resume` контракт;
- Claude — `claude -p` с pinned model, explicit allowed tools/permission mode и тем же target,
  output, context и resume metadata.

Router выбирает другой runtime, если он доступен; при `review_only` это нормальный путь дешёвой
Codex-подписки, при `off` — Claude fallback с degraded marker. Background job хранит
`decision_id`, runtime и native review session id; completion delivery использует общий durable
ingress. Skill/tool docs меняются вместе, legacy Codex-only entrypoint не остаётся вторым owner.

До запуска subprocess одной транзакцией создаются `review_attempt` и стабильный completion
`delivery_id`; attempt содержит subject snapshot, decision, command digest, target artifact и
временный output path. Review runner пишет полный output+exit metadata во временный файл и только
потом атомарно rename-ит его в attempt-specific finished artifact. Recovery никогда не запускает
review повторно:

- finished artifact с совпавшим attempt marker → тот же pre-created completion delivery
  переводится к dispatch;
- `planned` до фактического process start можно запустить один раз CAS-переходом;
- `running` без finished artifact после crash/restart → `delivery_unknown` и loud status;
- review использует отдельный `bg_jobs.type=review`, который делегирует только attempt state
  machine; generic `_run_exec` и `triggering -> active -> rerun command` для него запрещены.

Так verdict после process completion не теряется, а разрешённые reviewer tool side effects не
повторяются даже при crash между exit и сообщением агенту.

### Failover намеренно не «бесшовный»

Failover — отдельный durable post-turn control intent. Running turn не прерывается и не меняет
runtime. После `turn_end`/terminal limit server:

1. фиксирует текущий delivery как `submitted/completed` по фактическому исходу;
2. просит router решить linked `continuation`;
3. одной DB-транзакцией **до switch** создаёт linked continuation delivery и
   `runtime_failover(state=planned, from_model, to_model, decision_id)`;
4. только при persisted idle/waiting делает CAS `planned -> switching` и вызывает существующий
   `change_model()`;
5. сверяет persisted session model: target model означает idempotent success, после чего пишет
   `switched` и разрешает dispatch заранее созданной continuation;
6. сохраняет worktree, task/logical work id и delivery chain; новый runtime получает новый
   continuation message, не replay исходного prompt.

Recovery `switching` сначала читает persisted session model. Уже target → только помечает
`switched`; old model → повторяет idempotent `change_model(target)`. Crash до транзакции не начал
switch и следующий post-turn пересчитает intent; crash после неё всегда видит continuation row.
`switched/dispatching` восстанавливаются через общий delivery protocol, исходное сообщение не
создаётся заново.

До merge #174 transport — текущий `runtime_handoff`: native session id сбрасывается, tool/results
не переносятся, а в измеренной длинной сессии сохранилось 24/1284 semantic rows (1,87%) и
0,86% semantic chars. Каждый такой switch пишет
`history_transfer=summary_fallback`, `lossy=true` и user-visible warning. Это и есть явная цена:
контекст может потребовать восстановления из worktree/logs, незавершённая мысль модели теряется,
а уже совершённые external side effects нельзя повторять.

#174 не является dependency. #187 вызывает один существующий handoff interface; если к моменту
реализации #174 добавит native history transfer, тот же вызов запишет его фактический
`history_transfer` result. Если нет — тестируется и остаётся видимый summary fallback.

## Изменяемые файлы и функции

### Новые

- `app/runtime_router.py` — `RoutingPolicyV1`, state evaluator, serialized decision service,
  routing-contract guard, latches, audit envelope; импорт `weekly_runway` из #186.
- `app/delivery_queue.py` — stable identity, DB row/CAS transitions, dispatcher, status lookup,
  batch attempt contract.
- `app/review_runner.py` — runtime-neutral review command/session adapter.
- `tests/test_runtime_router.py`, `tests/test_delivery_queue.py`,
  `tests/test_review_runner.py` — pure matrices и crash/restart contracts.

### Существующие

- `app/db.py` — migrations и narrow CRUD для versioned policy, window latches, decisions,
  work deliveries, review attempts/subjects и runtime failovers. Baseline helper импортируется
  из #186. Existing `bg_jobs` не переиспользуется как turn
  queue: его `triggering` recovery допускает replay.
- `app/routes/system.py` — существующий `current_quota_observation` остаётся единственным loader;
  router получает его как dependency; удалить exact-model `/api/usage/readiness`; добавить
  policy GET/PUT/explain и queue visibility.
- `app/auth.py` — один operator-cookie guard для policy/manual-model/emergency mutations;
  internal agent token не даёт эти права.
- `app/quota_gate.py` — удалить самостоятельный model admission после переноса readiness/error
  contract в router, затем удалить модуль; не оставлять две политики.
- `app/manager.py` — route before worktree/backend side effects, один delivery seam вокруг
  `_auto_switch_before_delivery`/`AgentSession.send`, post-turn switch coordinator.
- `app/session.py`, `app/session_turns.py` — убрать per-model quota choice и in-memory replay,
  связать backend submit/turn end с delivery state, запускать failover только после persisted
  idle/waiting.
- `app/routes/sessions.py` — normal spawn без обязательного model, idempotent send/status; exact
  model остаётся только явно помеченным operator control plane.
- `app/mcp_stdio.py` — `spawn_worker` без `model/task_class`; idempotent delivery contract;
  убрать exact-model readiness/preflight и `change_worker_model`; `review_artifact` вместо
  Codex-only review; mutating workload tools fail-closed при router contract mismatch.
- `app/tg_bridge.py`, `app/bg_jobs.py`, `app/limit_wake.py` — natural delivery ids и общий queue
  dispatcher; terminal wake больше не replay-ит original input.
- `app/static/js/app.js` — browser delivery id создаётся до first fetch и сохраняется на retry.
- `pipelines/default/prompts/base.md` — убрать ложный model-routing owner и объяснить, что runtime
  выбирает server; agent не читает quota и не делает override.
- `pipelines/default/prompts/skills/codex-debate.md` — один runtime-neutral tool name/session
  contract; generated `.codex/.claude` copies руками не править.
- текущие tests `test_quota_gate.py`, `test_usage_readiness.py`, `test_manager.py`,
  `test_session.py`, `test_api.py`, `test_mcp_stdio.py`, `test_tg_bridge.py`,
  `test_bg_jobs.py`, `test_limit_wake.py`, pipeline/prompt tests — мигрировать на один decision и
  delivery seam.
- `CHANGELOG.md` — вручную описать новый owner/state machine. `architecture.md` сейчас отсутствует,
  создавать его не нужно. Не генерировать public changelog из task docs.

Phase 3 потребует расширить текущий ownership за `docs/tasks/187/`; этот план сам исходники не
меняет.

## Что не делать

- Не инъектировать live quota в prompt/message и не добавлять quota tool агенту.
- Не принимать class/model/reserve authorization из свободного текста или MCP-аргумента.
- Не считать Codex runway по Claude formula и не использовать Spark как Sol fallback.
- Не тратить Codex reset credits автоматически.
- Не switch-ить running session и не обещать seamless history до доказанного результата #174.
- Не replay-ить `dispatching/submitted/delivery_unknown` после restart.
- Не оставлять `change_worker_model`/agent-authenticated HTTP model change обходом router.
- Не строить «опасность задачи» по тексту. #188 измерил 5–15× больше нарушений запретов Codex при
  одинаковых rules; без server-owned ex-ante risk marker router не может честно распознать
  destructive work. Hard prohibitions требуют механического guard отдельной задачей. Если позже
  появится trusted `irreversible`, он станет Claude-only eligibility input, а не classifier.
- Не рестартовать сервис, не переключать живые модели и не активировать quota mode в Phase 3.

## Tickets

### T1 — Hot policy и воспроизводимый single/dual-runtime decision

- Files: `app/runtime_router.py`, `app/db.py`, `app/routes/system.py`, `app/quota_gate.py`,
  `app/auth.py`, `tests/test_runtime_router.py`, `tests/test_quota_gate.py`,
  `tests/test_usage_readiness.py`, `tests/test_db.py`, API/auth tests.
- AC:
  - `manifest_default` и quota policy загружаются из одного versioned DB document; PUT атомарен,
    invalid/incomplete activation отвечает 422 и не меняет прежнюю revision.
  - В `manifest_default` existing session не switch-ится: current model сохраняется; manifest
    применяется только к новому spawn, current Codex default — к review.
  - Ни один numeric threshold не берётся из evaluator default; fixtures с другими значениями
    меняют решение без restart.
  - Claude weekly measurement и baseline helper импортируются из #186; тест мутацией verdict
    меняет decision, отдельной копии `D`/work calendar/window normalization/query в #187 нет.
    Честный baseline `pct=0` с непустым reset принимается, `pct=0` с пустым reset исключается.
  - `D > configured threshold` latch-ит `reserve_only` до смены window id; уменьшение D в том же
    окне не открывает пул; `no_data`, stale, 5h hard stop и weekly hard stop дают точные reason.
  - Матрица `codex_access=all|review_only|off` покрыта table tests. В `off` доступный Claude
    выбирается и по 5h, и по 7d; unavailable Claude даёт `queued`, не bypass.
  - Simultaneous local admissions проходят через один lock; тест не заявляет строгий reserve и
    audit содержит `best_effort_threshold`.
  - Explain endpoint не мутирует session/model/worktree и возвращает одинаковый result для
    одинаковых policy+observations.
  - Policy PUT с dashboard cookie проходит; тот же payload с `INTERNAL_TOKEN` получает 403.
  - PUT ждёт in-flight admission до `submitted|queued`; после его ответа ни один новый submit со
    старой revision невозможен. Revision mismatch перед decision commit вызывает recompute.
  - Latch upsert и decision insert коммитятся одной DB-транзакцией до side effect. Crash до
    commit оставляет их оба отсутствующими и следующий admission пересчитывает D; crash после
    commit видит durable latch. Process cache состояния нет.
  - T1 мержится инертно: существующие callers продолжают использовать старый quota gate, а
    новый router не подключён ни к одному workload path. Удаление старого owner переносится в
    атомарный T3, чтобы новый MCP из main не разошёлся со старым server process до rollout-окна.
- blocked-by: none.

External integration prerequisite для начала T1: merged final #186 с
`app/quota_runway.py::weekly_runway`, `RunwayVerdict.window_id` и
`app/db.py::runway_window_start_pct`. Формулу/query временно не копировать.

### T2 — Durable HTTP/MCP turn ingress с loud queue

- Files: `app/delivery_queue.py`, `app/db.py`, `app/manager.py`, `app/session.py`,
  `app/routes/sessions.py`, `app/mcp_stdio.py`, `app/static/js/app.js`,
  delivery/session/MCP/API/browser tests.
- AC:
  - Browser и MCP создают stable source delivery id до first POST; одинаковый id+digest даёт одну
    row/один backend submit, id+другой digest отвечает 409.
  - Workload HTTP request без exact routing contract header отвечает 426 до DB/backend side
    effect; MCP/browser отправляют header, internal TG/bg передают typed contract version.
  - CAS допускает одного claimant. Crash/restart в `claimed` возвращает row в queue после lease;
    `dispatching`, `submitted`, `completed`, `delivery_unknown` никогда не replay.
  - Timeout/exception после `dispatching` без typed pre-submit proof даёт
    `delivery_unknown` и user-visible status; typed pre-submit failure можно безопасно requeue.
  - `submitted` связан с `session_id/turn_gen/native ref`; restart без terminal event переводит
    его в `delivery_unknown`, не в queue.
  - Idle/waiting HTTP/MCP turn проходит T1. Все-runtime-unavailable возвращает `202 queued` с
    причинами/known reset, сразу уведомляет target+parent/operator и переживает restart. Unknown
    telemetry не получает invented retry time/last-known value.
  - Running steering не switch-ится и помечается как submit в текущий turn, а не новый routed
    work. Status tool разрешает только proof-safe retry существующего id.
  - Cookie-authenticated operator может single-use авторизовать существующий queued delivery в
    reserve; internal token, task priority и agent payload не могут. Повтор authorization
    идемпотентен и audit сохраняет автора/reason.
- blocked-by: T1.

### T3 — Server-owned spawn и остальные ingress без выбора модели агентом

- Files: `app/manager.py`, `app/session.py`, `app/routes/sessions.py`, `app/mcp_stdio.py`,
  `app/tg_bridge.py`, `app/bg_jobs.py`, `app/limit_wake.py`,
  `pipelines/default/prompts/base.md`, spawn/pipeline/TG/bg/pending tests.
- AC:
  - `spawn_worker` tool schema не содержит `model`, `task_class` или reserve flag; server class
    всегда `worker_general`.
  - Planned spawn получает decision до worktree/session/backend side effects. Unavailable
    сохраняет `intent_kind=spawn` с target spec, но не оставляет branch/worktree/session row;
    recovery создаёт их и submit-ит initial task ровно один раз.
  - В `manifest_default` server выбирает role manifest model; в quota mode та же request fixture
    выбирает Codex/Claude согласно T1 и сохраняет `decision_id`.
  - Exact model в public agent path отклоняется; dashboard/admin change-model требует operator
    cookie и audit-ится как operator override; MCP `change_worker_model` удалён.
  - `/api/usage/readiness?model=`, MCP exact-model preflight и самостоятельный `quota_gate`
    удаляются в этом же коммите после миграции всех callers; route/import snapshot доказывает,
    что второго owner не осталось. `limit_wake` не возвращает model decision.
  - TG, bg fire и pending flush используют T2 delivery rows/natural ids. Batch queued messages
    делает один backend submit и атомарно переводит все rows; старый `_pending_messages`
    reinsertion path удалён.
  - Provider recovery dispatches ровно один раз. Terminal limit создаёт linked continuation id,
    но исходный prompt повторно не посылается.
  - Prompt больше не требует агенту смотреть quota/передавать model и не остаётся вторым owner.
    Fresh-process MCP schema test видит новый контракт; mocked seam не вызывает real backend.
- blocked-by: T1, T2.

### T4 — Runtime-neutral independent review при `all|review_only|off`

- Files: `app/review_runner.py`, `app/db.py`, `app/mcp_stdio.py`, `app/bg_jobs.py`, delivery
  integration, `pipelines/default/prompts/skills/codex-debate.md`, review/MCP/bg tests.
- AC:
  - Единственный agent tool — `review_artifact`; его schema не принимает model/class/source
    runtime, class=`review` и provenance берутся сервером.
  - Review subject snapshot использует immutable runtime set из submitted deliveries, не current
    session model; single/mixed/unknown provenance дают соответственно independent/degraded
    mixed/degraded unknown reason.
  - При author=Claude + `all/review_only` доступный Codex выбирается; при author=Codex выбирается
    Claude; решение и native review session сохраняются.
  - При `off` review выполняется Claude runner и пишет `degraded_review_independence`; отсутствие
    Codex не делает tool заглушкой.
  - Если независимый runtime quota-unavailable, same-runtime review допускается только после
    явного relaxation step и warning; если и он unavailable — durable queued outcome T3.
  - Codex и Claude runners пишут один artifact/session envelope, поддерживают resume и bounded
    tool permissions; completion delivery at-most-once.
  - Attempt+completion id существуют до subprocess. Atomic finished artifact после crash
    доставляется тем же id без rerun; running без finished marker становится
    `delivery_unknown`; dedicated `type=review` restore читает attempt state и никогда не
    передаёт command в generic `_run_exec`/stale-trigger rerun.
  - Skill и MCP schema называют один новый tool; Codex-only hidden path отсутствует.
- blocked-by: T1, T2.

### T5 — Явно lossy post-turn failover без replay

- Files: `app/db.py`, `app/manager.py`, `app/session.py`, `app/session_turns.py`,
  `app/limit_wake.py`, `app/delivery_queue.py`, failover/session/restart tests.
- AC:
  - Quota decision/terminal limit никогда не вызывает `change_model()` при `RUNNING`; switch
    возможен только после persisted `IDLE|WAITING` и завершения текущего submit state.
  - Alternative runtime получает новый linked `continuation` delivery; original delivery id и
    prompt не переиспользуются.
  - Continuation row и `runtime_failover=planned` коммитятся до `change_model`; recovery
    `switching` сверяет persisted target model и не повторяет уже завершённый switch.
  - Worktree, task/logical work id и audit chain сохраняются; native session id меняется по
    текущему `change_model` contract.
  - Без #174 результат явно `history_transfer=summary_fallback`, `lossy=true` и содержит warning
    о неперенесённых tool/results/возможной потере мысли. Тест не утверждает seamless.
  - С merged #174 coordinator принимает его фактический transfer result через тот же interface;
    ни import, ни test fixture #174 не обязательны для работы fallback.
  - Crash в каждой точке `turn_end -> decision -> switch -> continuation submit` не повторяет
    external side effects; ambiguous submit остаётся `delivery_unknown`.
- blocked-by: T1, T2, T3.

### T6 — Инертный rollout, hot activation и доказательство нового процесса

- Files: policy/status routes and tests from T1, `CHANGELOG.md`, `docs/tasks/187/report.md`.
- AC:
  - Migration seed/default оставляет `mode=manifest_default`; первый start нового code quota
    balancing сам не включает.
  - Worker branch не merge-ится в live main до operator window. Новый MCP против старого server
    получает `routing_contract_mismatch` на mutating workload tools и не использует legacy
    exact-model path.
  - Новый server до side effect отвергает workload request старого MCP/browser без
    `routing-v1`; tests покрывают new-client/old-server и old-client/new-server.
  - Policy GET показывает `router_contract_version`, `process_started_at`, revision/mode и queue
    counts; новый endpoint, а не static `X-Orchestra-Build`, доказывает загрузку Python-кода.
  - Hot PUT final #186 values и выбранного #190 `codex_access` включает quota mode без restart;
    обратный PUT `manifest_default` — документированный hot rollback.
  - Focused tests проходят, затем полный `uv run python -m pytest -x -q`; `uv.lock` неизменён.
  - Report содержит результаты dry-run для `all`, `review_only`, `off`, single-Claude 5h/7d,
    all-unavailable и lossy failover, но Phase 3 не мутирует live service/sessions.
- blocked-by: T1, T2, T3, T4, T5.

## Порядок выкладки (выполняет оператор отдельным разрешённым окном)

### До restart

1. Phase 3 оставляет #187 в committed worker branch; merge в main не делать заранее. Prompt и
   новый `mcp_stdio.py` читаются с диска новыми connect даже при старом FastAPI в памяти, поэтому
   «merge сейчас, restart потом» создаёт несовместимое окно.
2. Снять consistent backup live SQLite через `sqlite3.Connection.backup`.
3. `GET /api/sessions` без scope: дождаться нуля `running` во всех проектах. `GET /api/bg/jobs`:
   дождаться отсутствия active/triggering `run|review` jobs; persistent timers/cron только учесть.
4. Пользователь подтверждает одно окно и **останавливает Orchestra до изменения checkout**.
   После `systemctl stop orchestra` проверить отсутствие процесса/слушающего `:8888`, затем по
   остановленной DB повторно убедиться, что не появился `running` turn или running review между
   шагами 3–4. Если появился — checkout не менять, поднять прежний commit и повторить позже.
5. Пока ingress физически остановлен, оператор применяет заранее подготовленные commits: сначала
   #186 code contract (`quota_runway.py` + общий baseline helper), затем #187. Если #186 code не в
   deployed tree, start запрещён. Orchestra-агент сам stop/merge/start не выполняет.

### Один stop/start и проверка

6. Пользователь делает `systemctl start orchestra`; это единственный coordinated restart cycle.
   Migration создаёт policy/delivery tables, но mode остаётся `manifest_default`.
7. Проверить `GET /api/usage/routing-policy`: новый contract version, новый
   `process_started_at`, manifest mode, пустая queue/валидная migration.
8. Переподключить/создать disposable session и прочитать его `tools/list`: `spawn_worker` без
   model/task_class, `review_artifact` присутствует. Старый уже подключённый MCP не считается
   проверкой нового schema.
9. На explain endpoint прогнать synthetic fixtures `all`, `review_only`, `off`, Claude 5h/7d,
   stale/all-unavailable. Никаких live spawn/switch.

### Hot activation и rollback

10. Записать финальные измеренные значения #186 (его code уже загружен шагом 6); после решения
   #190 поставить `codex_access`. PUT `mode=quota` — единственная активация.
11. Проверить policy revision и один новый disposable idle delivery: выбранный runtime/reason и
    `decision_id` совпадают с explain; живые running sessions не переключать.
12. При аномалии PUT `mode=manifest_default` немедленно останавливает quota balancing без
    restart. Откат самого Python-кода требует нового согласованного restart и не смешивается с
    hot policy rollback.

Mixed-version guards остаются defense-in-depth, не заменой остановленного ingress: новый MCP
против старого server fail-closed по probe, новый server отвергает старый workload request без
`routing-v1`. Поддерживаемого live mixed-version режима нет.

## Проверка риска и edge cases

Обязательные focused сценарии: разные ages Claude/Codex observations; reset между read/admit;
`D` упал после latch; Claude 5h `resets_at=NULL`; Codex `review_only/off`; один runtime; один ход
пересёк 90/95; provider external consumption; root orchestrator post-turn switch; caller потерял
enqueue response; duplicate id с другим digest; lease expiry; crash до/после `dispatching`;
terminal error после side effect; queue recovery; review author provenance; #174 отсутствует;
same-runtime review degradation; Spark ошибочно предложен как Sol; reset credit появился, но не
потрачен.

Async crash/restart/concurrency tests прогоняются не менее трёх раз. Delivery transitions
проверяются мутациями: разрешённый replay `claimed -> queued` и запрет replay для
`dispatching/submitted/delivery_unknown` должны независимо краснить тест.
