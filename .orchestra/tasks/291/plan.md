# #291 — adaptive quota controller: Phase 2 implementation plan

Основание: принятые `docs/tasks/285/research.md` и
`docs/tasks/285/limits-data.json` (`schema_version=2`). Этот документ планирует работу;
runtime/config в Phase 2 не меняются.

## Результат и граница первого релиза

Первый релиз — только **shadow/advisory**. Он:

1. видит отдельные ограничения Claude 5h, Claude 7d, scoped Fable, Codex primary,
   Codex Spark и Grok primary;
2. моделирует Codex Fast как режим расхода **того же** Codex primary с multiplier 2.5
   для GPT-5.6/5.5 и 2.0 для GPT-5.4, а не как новый bucket;
3. перед реальным новым provider turn вычисляет, что adaptive gate сделал бы, но не
   меняет выбранную модель, не задерживает turn и не заменяет действующий `quota_gate`;
4. сохраняет прогноз, причины fail-safe, незавершённые q95-reservations и фактический
   исход turn для последующей калибровки;
5. даёт offline replay/backtest и машинный evidence gate.

Adaptive enforcement — отдельный последующий T5. Даже одобрение Phase 3 для #291
разрешает реализовать только T1–T4. T5 требует нового явного разрешения после того, как
машинный gate укажет `eligible=true` на живом prospective evidence set.

Существующие статические ограничения остаются baseline и rollback path. Shadow-код не
получает права разрешить то, что запрещает текущий gate, и не получает права запретить то,
что текущий gate разрешил.

## Проверенная текущая база

- `app/routes/system.py:_provider_usage_snapshot` уже нормализует Claude 5h/7d, Codex,
  Spark и Grok, но отбрасывает `anthropic.limits[]`, где live API отдал scoped Fable.
- `app/routes/system.py:_quota_observation_from_cache` не публикует timestamp Grok, а
  `_quota_refresh_locks` не содержит Grok; Grok нельзя считать fresh для dispatch gate.
- `app/db.py` хранит сырой normalized `provider_usage` в `usage_snapshots` и terminal
  usage в `turn_usage`; отдельного durable shadow decision/outcome/evidence нет.
- `app/quota_gate.py:get_worker_admission` — текущий owner статического worker gate.
  Он используется до planned worker spawn и в `AgentSession` перед новыми worker turns;
  Grok сейчас `not_applicable`, orchestrator turns исключены.
- `app/runtime_router.py` и таблицы `runtime_routing_*` — инертный audit-контур #187:
  production workload callers `.admission()` не вызывают. #291 не активирует и не
  расширяет его, чтобы не получить второго owner маршрутизации.
- `app/session_turns.py:TurnManager.handle_turn_end` уже получает terminal `event_id`,
  model/runtime/tokens и fresh-or-unknown quota snapshot — это seam для settlement
  shadow dispatch, а не источник исходного pre-dispatch utilization.

## Неоднозначность #285, закрытая этим планом

В narrative #285 `q95(turn)` встречается и внутри `measurement_guard`, и отдельным
слагаемым dispatch gate. Для #291 единственный executable контракт — формула из задания:

```text
u_eff + q95(next_turn) + guard <= 99 - reserve
u_eff = reported_utilization + sum(q95(unsettled dispatches in the same bucket))
guard = max(0.5 pp integer-display guard,
            p95 unobserved telemetry-lag burn,
            residual/drift guard)
```

`q95(next_turn)` считается ровно один раз. Добавка unsettled dispatches закрывает риск
параллельного over-admission, отмеченный в #285, не меняя заданную формулу: для gate
`u` означает уже зарезервированный effective utilization.

## Contract и topology

### Bucket и constraint set

| Lane / mode | Независимый расход | Constraints одного dispatch |
|---|---|---|
| Claude non-Fable | `anthropic:five_hour`, `anthropic:seven_day` | проходят оба |
| Claude Fable | не отдельная добавочная ёмкость | 5h + 7d all + `anthropic_fable:weekly_scoped`; проходят все три |
| Codex Luna/Sol | `codex:primary` | primary |
| Codex Fast 5.6/5.5 | тот же `codex:primary` | primary, q95 умножен на 2.5 |
| Codex Fast 5.4 | тот же `codex:primary` | primary, q95 умножен на 2.0 |
| Spark | `codex_spark:primary` | только собственный bucket |
| Grok | `grok:primary` | только собственный bucket; auth health — отдельный signal |

Fast не создаёт synthetic utilization и не наследует Spark. `token_expired`, missing OAuth
и provider HTTP/auth errors переводят Grok telemetry в unknown; они не равны quota=100.

### Идентичность окна и режима

- `window_id = provider/bucket + canonical resets_at` только при устойчивом anchor.
- Нулевой Spark с `resets_at≈now+7d` не получает завершённого window id, пока anchor не
  стабилен минимум три samples или utilization не стал положительным.
- `regime_key` включает provider, bucket, plan type, window duration, reset semantics,
  model/rate-card version и для Grok credential-home identity **без token/path values**.
- Exact reset timestamp не входит в `regime_key`: он идентифицирует окно, а не режим.
- Fable all/scoped anchors, отличающиеся не больше чем на один observed cadence, считаются
  одним correlated constraint group, но их utilization и headroom не складываются.

### Confidence и drift

Статус каждого bucket:

- `cold`: <1 полного same-regime окна; только conservative upper proxy, без ACCELERATE;
- `pilot`: 1–2 полных окна; bootstrap виден, gate-advice использует верхнюю границу;
- `operational`: ≥3 полных стабильных окна, telemetry coverage ≥90%, ≥20
  non-overlapping blocks после thinning не короче correlation length, ESS ≥20;
- `fail_safe`: fresh usable value/anchor отсутствует, найден drift/corruption либо q95
  для candidate class неидентифицируем.

Новый regime начинается при любом из событий:

- `plan_type`/window duration/model rate-card изменились;
- reset anchor прыгнул больше одного фактического cadence вне scheduled reset;
- utilization упал вне reset/plan migration;
- два последовательных forecast residual вышли за 80% interval;
- telemetry gap >10 минут;
- Grok credential-home identity изменилась.

Старая абсолютная pp/window история после drift запрещена. Distribution tokens/turn можно
перенести только при неизменных model/rate card; перевод tokens→pp всё равно калибруется заново.

### q95(next turn)

Nearest-rank q95 строится только по settled outcomes того же regime. Приоритет strata:

1. `(constraint, plan/regime, model, fast_mode, server task class)` с ≥20 usable outcomes;
2. тот же model/mode на bucket с conservative upper bound;
3. token/credit proxy, если в том же regime доказана монотонная связь token/credits→pp;
4. иначе `unknown`, recommendation=`indeterminate`, zone=`FAIL_SAFE`.

Outcome считается exact только когда между pre-dispatch и first post-terminal fresh sample
не было другого submitted consumer того же bucket. При concurrency сохраняется interval
`[0, observed_delta]`; upper endpoint допускается для conservative q95, но не выдаётся за
exact sample. Counter drop, gap, plan change и stale endpoints дают `unscorable`, не zero.

### Reserve

Critical reserve — q95 суммы **operator-declared** ещё не dispatched critical intents до
reset. Он не выводится из `priority=0`, текста prompt или самообъявления агента. Declaration
содержит task/work id, candidate lane/class, count, deadline и reason; значения quota/token
выводит controller. В последние `max(2h, q95 critical lead time)` невостребованный reserve
выпускается ступенями, но nominal 1 pp target margin не выпускается.

Orchestrator/critical turns тоже попадают в shadow telemetry: exempt от текущего worker gate
не означает бесплатный расход. В T5 только owner-authenticated critical intent сможет тратить
reserve; обычный worker не сможет присвоить себе criticality.

## Schema и migration

T1 добавляет таблицы idempotent `CREATE TABLE IF NOT EXISTS`; существующие строки
`usage_snapshots`, `turn_usage` и `runtime_routing_*` не переписываются. Вся schema change
выполняется одной SQLite transaction с `foreign_keys=ON`: ошибка на любом DDL/trigger/index
откатывает весь controller schema set.

### `quota_controller_decisions`

Append-only pre-dispatch evaluation:

```text
decision_id TEXT PRIMARY KEY
created_at TEXT NOT NULL
mode TEXT NOT NULL CHECK(mode IN ('shadow','advisory','enforce'))
source TEXT NOT NULL CHECK(source IN ('snapshot','dispatch','replay'))
session_id TEXT NOT NULL DEFAULT ''
turn_gen INTEGER
task_id TEXT NOT NULL DEFAULT ''
task_class TEXT NOT NULL
model TEXT NOT NULL
fast_mode INTEGER NOT NULL CHECK(fast_mode IN (0,1))
critical_intent_id TEXT
policy_version INTEGER NOT NULL
regime_set_hash TEXT NOT NULL
observation_at TEXT
observation_json TEXT NOT NULL CHECK(json_valid(observation_json))
decision_json TEXT NOT NULL CHECK(json_valid(decision_json))
legacy_decision_json TEXT NOT NULL CHECK(json_valid(legacy_decision_json))
```

`mode='enforce'` допустим схемой для будущей миграции/совместимости, но T1–T4 не содержат
code path, который его пишет или читает как authority. Unique partial index на
`(session_id,turn_gen,source)` для `source='dispatch'` не даёт refresh/retry admission создать
две shadow-reservation одного logical turn.

### `quota_controller_outcomes`

Один settlement на decision:

```text
decision_id TEXT PRIMARY KEY REFERENCES quota_controller_decisions(decision_id)
terminal_event_id TEXT NOT NULL UNIQUE
submitted_at TEXT NOT NULL
ended_at TEXT NOT NULL
settled_at TEXT NOT NULL
status TEXT CHECK(status IN ('exact','interval','unscorable','submit_failed','cancelled'))
concurrent_dispatches INTEGER NOT NULL CHECK(concurrent_dispatches >= 0)
actual_json TEXT NOT NULL CHECK(json_valid(actual_json))
```

Original decision неизменяем; outcome — отдельный факт. Replay `terminal_event_id` идемпотентен.

### `quota_controller_inflight_reservations`

Нормализованный active q95 на constraint, чтобы parallel admission не суммировал JSON
eventually-consistently:

```text
decision_id TEXT NOT NULL REFERENCES quota_controller_decisions(decision_id)
bucket TEXT NOT NULL
window_id TEXT NOT NULL
reserved_pp REAL NOT NULL CHECK(reserved_pp >= 0)
state TEXT NOT NULL CHECK(state IN ('reserved','submitted','released','cancelled'))
created_at, updated_at TEXT NOT NULL
PRIMARY KEY(decision_id,bucket,window_id)
```

`reserve_shadow_dispatch()` исполняет `BEGIN IMMEDIATE`; внутри одной transaction читает
`SUM(reserved_pp)` active строк того же `(bucket,window_id)`, вычисляет все constraints,
вставляет decision и reservations. Поэтому два процесса/корутины не могут оба увидеть старый
headroom. Порядок bucket locks лексикографический; SQLite transaction остаётся последним owner
истины между процессами. Release/settlement — narrow CAS `reserved|submitted → released`, replay
не уменьшает сумму второй раз.

### `quota_controller_reserve_intents`

Owner-authored critical demand:

```text
intent_id TEXT PRIMARY KEY
created_at, deadline_at TEXT NOT NULL
task_id, logical_work_id, reason TEXT NOT NULL
lane, task_class, model TEXT NOT NULL
turn_count INTEGER NOT NULL CHECK(turn_count > 0)
state TEXT CHECK(state IN ('planned','consumed','released','cancelled'))
revision INTEGER NOT NULL
created_by TEXT NOT NULL
```

Mutation — CAS по revision; agent INTERNAL_TOKEN получает только read-only view, создать или
переименовать critical intent может только dashboard owner session.

### `quota_controller_evidence_sets`

Immutable machine gate artifact:

```text
evidence_id TEXT PRIMARY KEY
created_at, dataset_start, dataset_end TEXT NOT NULL
policy_version INTEGER NOT NULL
regime_set_hash, source_digest TEXT NOT NULL
prospective INTEGER NOT NULL CHECK(prospective IN (0,1))
metrics_json, reasons_json TEXT NOT NULL CHECK(json_valid(...))
eligible INTEGER NOT NULL CHECK(eligible IN (0,1))
```

`quota_controller_decisions`, `quota_controller_outcomes` и
`quota_controller_evidence_sets` защищены `BEFORE UPDATE` и `BEFORE DELETE` triggers;
`INSERT OR REPLACE` поверх существующего primary key запрещает отдельный `BEFORE INSERT` trigger.
Mutable reserve intents и inflight rows меняются только narrow CAS helpers с revision/state
precondition. T1 проверяет triggers, FK, CHECK и required indexes, а не только имена таблиц.

Ни один table не хранит prompt/message bodies, OAuth/token/path values или raw provider errors.

## Pure decision output

Для каждого constraint сохраняются **свои** q95/guard/reserve; scalar на весь dispatch
запрещён, потому что Fable расходует три процента с разными знаменателями. Пример:

```json
{
  "bucket": "codex:primary",
  "regime_key": "...",
  "window_id": "...",
  "utilization": 92,
  "inflight_reserved_pp": 1.5,
  "q95_next_turn_pp": 2.0,
  "guard_pp": 0.5,
  "reserve_pp": 2.0,
  "lhs_pp": 96.0,
  "rhs_pp": 97.0,
  "would_allow": true,
  "confidence": "pilot",
  "reasons": []
}
```

Composite `would_allow=true` только если все constraints истинны. Любой `null`, stale,
corrupt, drift или plan-change даёт `would_allow=null`, `recommendation=indeterminate`,
`zone=FAIL_SAFE`; shadow не превращает unknown в false hard-stop или true bypass.

Зоны сохраняются из #285: ACCELERATE, TRACK, THROTTLE, RESERVE, FAIL_SAFE. Они advisory;
gate truth и zone — разные поля, чтобы UI не интерпретировал THROTTLE как hard deny.

## Shadow wiring и observability

T3 создаёт server-owned `ShadowDispatchContext` перед каждым **новым logical provider turn**.
Mid-turn injection не создаёт второй dispatch. Нормальный send, queued flush, retry,
auto-continue и compaction получают явный `intent_kind`; orchestrator turns тоже наблюдаются.

Runtime seam фиксирован, чтобы helper нельзя было реализовать в отрыве от delivery:

- `AgentSession.__post_init__` получает process-owned `_quota_shadow_controller`;
- единственный new-turn path в `AgentSession.send` вызывает async
  `reserve_before_submit(context, static_decision)` после окончательного static admission refresh,
  но до `backend.send`; orchestrator передаёт `static_decision=None`;
- успешный возврат `backend.send` вызывает `mark_submitted(reservation)`; ошибка observer
  логируется и delivery продолжается ровно один раз;
- mid-turn inject не вызывает ни один shadow hook;
- `TurnManager.handle_turn_end` передаёт active reservation и terminal `event_id` в
  idempotent store settlement. Replay выводит concurrency из сохранённых start/end intervals,
  не переписывая immutable outcomes.

Порядок:

1. current static admission выполняется без изменений;
2. shadow controller читает тот же fresh provider family плюс Grok/Fable extensions;
3. `reserve_shadow_dispatch()` атомарно пишет decision+inflight reservations до
   `backend.send`;
4. successful submit помечается только через outcome lifecycle; exception до submit даёт
   `submit_failed`, cancellation — `cancelled`;
5. terminal event связывается по `(session_id,turn_gen)` и `event_id`; первый fresh sample
   после terminal завершает exact/interval/unscorable outcome.

Любая ошибка shadow storage/forecast логируется с class+reason и увеличивает
`shadow_errors_total`, но не меняет результат static admission и не мешает `backend.send`.
Именно это доказывает T3 oracle.

`GET /api/usage/quota-controller` (owner read-only) отдаёт:

- `mode=shadow`, contract/policy versions;
- current advisory по всем bucket и binding constraint;
- confidence, regime/window ids, sample age, q95 source/sample size;
- p50/p90/p95 projected end и early-exhaust risk;
- reserve declared/held/released;
- последние decision/outcome counts, exact/interval/unscorable fractions;
- current evidence eligibility и дословные machine reasons;
- сравнение с current static gate (`agree`, `adaptive_would_allow`,
  `adaptive_would_hold`, `adaptive_indeterminate`).

Reserve mutation surfaces фиксированы: `POST /api/usage/quota-controller/reserve` и
`DELETE /api/usage/quota-controller/reserve/{intent_id}`. Оба сначала вызывают
`require_operator_session(request)`; INTERNAL_TOKEN без dashboard cookie получает 403.

Structured logs: `quota_shadow_decision`, `quota_shadow_fail_safe`,
`quota_shadow_settlement`, `quota_regime_drift`. High-cardinality ids не становятся metric
labels. Prometheus-style counters/gauges (через существующий telemetry surface либо JSON status):

- decisions by bucket/zone/recommendation;
- stale/corrupt/drift/unknown-q95 reasons;
- unsettled reserved pp and count;
- q95 empirical coverage, projection residual, unsafe-allow and false-hold candidates;
- final utilization, unused headroom, hours-at-100 before reset;
- shadow failure count (must not alter delivery count).

## Replay/backtest и evidence gate

`scripts/replay_quota_controller.py` принимает frozen JSON или WAL-safe DB copy, никогда live
DB. Для принятого источника:

```bash
uv run python scripts/replay_quota_controller.py \
  --input docs/tasks/285/limits-data.json \
  --output docs/tasks/291/backtest.json
```

Replay идёт по времени без look-ahead: q95/forecast на момент `t` видит только строки `<t`.
Plan transition `prolite→pro`, gaps >900 s, ambiguous legacy double-zero, unavailable provider,
sliding zero-Spark anchor и cross-contour Grok rows либо делят regime, либо исключаются с
machine reason. VPS и laptop series не объединяются.

Для каждого полного same-regime окна сравниваются:

- current static baseline (95 worker stop + фактическая routing policy);
- adaptive shadow gate;
- final utilization/unused headroom относительно target 99;
- early exhaustion hours и unsafe allows;
- false holds: adaptive hold, после которого observed eligible turn помещался в headroom;
- p50/p90/p95 end forecast coverage;
- q95 next-turn exceedances;
- telemetry coverage, correlation block length, non-overlapping blocks и ESS.

Evidence metrics keyed, а не scalar:

```text
constraints[bucket] = {stable_windows, coverage_by_window, blocks, ess,
                       unsafe_allows, drift_count, baseline comparison}
strata[bucket/model/mode/task_class] = {settled_outcomes, q95_coverage,
                                       q95_binomial_lower_95}
```

Evidence set получает `eligible=true` для конкретного `enabled_strata` только если
**одновременно для каждого referenced constraint и каждой named stratum**:

1. prospective=true и есть ≥3 полных стабильных same-regime окна для каждого enforcement
   bucket/constraint;
2. telemetry coverage каждого окна ≥90%; ≥20 non-overlapping blocks; ESS ≥20;
3. для каждого разрешаемого `(bucket,model,mode,task_class)` ≥20 settled usable outcomes;
4. empirical q95 coverage ≥95%, а односторонняя 95% binomial lower bound ≥80%;
5. `unsafe_allow_count=0`, `corrupt_authoritative_decision_count=0`, drift в qualified
   windows отсутствует;
6. adaptive replay не хуже static baseline одновременно по early-exhaustion hours и
   median unused headroom, а false holds не больше baseline;
7. current live regime_set_hash совпадает с evidence; plan/rate-card/auth-home drift сразу
   делает evidence ineligible.

Correction для Release A (2026-08-16): первоначально утверждённый порог telemetry coverage
≥80% заменён на ≥90% в соответствии с immutable T4 oracle. Более строгий порог действует только
на shadow evidence eligibility: он может лишь задержать квалификацию evidence, но не меняет
dispatch, routing или текущий static gate. Enforcement остаётся отдельным запрещённым в этом
релизе T5.

Missing constraint/stratum/field — named fail-closed reason, не default zero/pass. Evidence
одной Codex stratum не может авторизовать Claude, Spark или Grok.

Неполный спрос может помешать закончить у 99 и не является ложью контроллера: окно помечается
`demand_limited` и не доказывает target tracking. Оно остаётся в safety/calibration metrics,
но не закрывает criterion 6 про utilization.

## Rollout и rollback

### Release A — T1–T4, shadow only

1. Merge с hard-coded/validated `mode=shadow`; adaptive output не подключён к
   `require_worker_admission`.
2. Restart в согласованное окно нужен для Python/schema; после restart проверить DB migration,
   `mode=shadow`, один synthetic explain и один реальный turn с неизменным static decision.
3. Наблюдать минимум три полных same-regime окна; nightly/owner-run replay создаёт immutable
   evidence sets.
4. Drift или ошибки telemetry не требуют rollback delivery: controller advisory становится
   FAIL_SAFE, а current static gate продолжает владеть поведением.

Rollback Release A: выключить только вызов shadow observer одним `shadow_enabled=false` hot
policy value/операторским action, либо revert code+restart; decision tables append-only остаются
для аудита и не читаются текущим gate. Сбой migration до commit транзакции оставляет старую схему;
server не должен стартовать в наполовину созданной схеме.

### Release B — T5, отдельное разрешение

T5 добавит policy `mode=enforce` и feature flag. PUT `shadow→enforce` — owner-cookie only,
CAS revision и требует конкретный current prospective `evidence_id`, созданный не более 10 минут
назад; server сам повторяет все
machine criteria и regime hash. Env/manifest/agent prompt не могут обойти gate.

Rollback T5: один owner action `mode=enforce→shadow` hot, без restart и без удаления evidence.
При stale telemetry, plan/drift, evidence mismatch или controller exception отдельный bucket
атомарно перестаёт применять adaptive decision и возвращается к current static baseline; факт
auto-demotion видим и уведомляется. Уже submitted turn не прерывается. Повторное включение требует
новый evidence set текущего regime.

## Affected files

T1–T4 предполагают:

- new `app/quota_controller.py` — topology, pure evaluator, confidence/drift/q95/reserve;
- `app/routes/system.py` — Fable/Grok normalized fresh observation и read-only status;
- `app/db.py` — пять tables, immutability triggers и narrow transactional helpers;
- `app/session.py`, `app/session_turns.py` — dispatch identity и outcome settlement;
- new `scripts/replay_quota_controller.py` — frozen replay/evidence generation;
- production tests в `tests/test_quota_controller*.py` (Phase 3 implementation may add tests,
  но committed Phase 2 oracles below are immutable).

T5 дополнительно меняет только `app/quota_gate.py`, controller policy helpers/API и focused
tests. `app/runtime_router.py`, pipeline manifests, model routing prompts, TG bridge, provider
auth files и dashboard mutation UI не трогаются.

## Tickets

### T1 — Durable normalized shadow snapshot for every quota constraint

- Outcome: один normalized observation round-trip сохраняет Claude 5h/7d/Fable,
  Codex primary/Spark, Fast topology и Grok primary с честной freshness; пустой/sliding anchor
  не становится стабильным окном. Старые DB мигрируют без переписывания истории.
- Files: `app/routes/system.py`, `app/db.py`, new `app/quota_controller.py`, focused tests.
- Test: `uv run python -m pytest -q docs/tasks/291/oracles/test_t1_schema_and_topology.py`
  — committed RED in `f1a5460b24eb91b7408d11b0ecaa93bbdbb2571b`; first failing assertion:
  `assert "anthropic_fable" in providers`.
- AC: named command is green; `db.init_db()` twice on an old-schema fixture leaves all old rows
  value-equivalent and creates the five named tables/indexes/triggers atomically; UPDATE/DELETE/
  REPLACE immutable audit rows fail, FK/CHECK violations fail; normalized output contains exact
  constraint mapping in the table above; Grok freshness is absent/unknown on auth failure, never 0.
- blocked-by: none

### T2 — Multi-constraint advisory gate with confidence, drift and in-flight reservation

- Outcome: pure evaluation of one proposed dispatch returns per-constraint components, composite decision,
  zone and confidence for every lane/mode. It applies the exact inclusive gate, dynamic reserve,
  Fast multiplier and parallel in-flight q95; unknown/drift is indeterminate FAIL_SAFE.
- Files: `app/quota_controller.py`, focused tests.
- Test: `uv run python -m pytest -q docs/tasks/291/oracles/test_t2_adaptive_gate.py`
  — committed RED in `f1a5460b24eb91b7408d11b0ecaa93bbdbb2571b`; first failing assertion:
  `assert spec is not None, "app.quota_controller is not implemented"`.
- AC: named command is green; exact boundary `lhs == rhs` allows, `lhs > rhs` holds;
  Fable uses materially different q95/guard/reserve on its three constraints and fails when any
  fails; two simultaneous Codex `reserve_shadow_dispatch()` calls against one DB cannot both
  consume the same final headroom; stale/drop/plan-change/corrupt values yield `would_allow
  is None`; Fast 5.6/5.5 uses 2.5× on Codex primary and Spark/Grok never inherit it.
- blocked-by: T1

### T3 — Real dispatch shadow audit, settlement, reserve declarations and status API

- Outcome: normal worker, orchestrator, queued flush, retry/auto-continue and compaction turns
  produce exactly one pre-dispatch shadow decision and one terminal outcome. Mid-turn steering
  produces none. Shadow failure cannot block or duplicate delivery. Owner can declare/cancel a
  critical reserve intent; agents cannot self-authorize it. Status exposes calibration and static
  disagreement without message bodies/secrets.
- Files: `app/quota_gate.py`, `app/session.py`, `app/session_turns.py`, `app/db.py`,
  `app/routes/system.py`, `app/quota_controller.py`, focused tests.
- Test: `uv run python -m pytest -q docs/tasks/291/oracles/test_t3_shadow_delivery.py`
  — committed RED in `f1a5460b24eb91b7408d11b0ecaa93bbdbb2571b`; first failing assertion:
  `assert events == ["shadow_reserve", "backend_send", "shadow_submitted"]`.
- AC: named command is green; integration through actual `AgentSession.send` proves decision row
  precedes exactly one backend send; observer exception still calls backend once and leaves the
  original static `QuotaDecision` unchanged; orchestrator idle send is observed and mid-turn
  injection is not; repeated admission refresh for one turn yields one decision row; actual
  `TurnManager.handle_turn_end` replay with one `event_id` yields one outcome; concurrent consumers
  are marked interval; owner-cookie/internal-token reserve API tests return 2xx/403 respectively; API says
  `mode=shadow` and reports observer errors.
- blocked-by: T1, T2

### T4 — Time-causal replay and machine evidence gate

- Outcome: a deterministic CLI replays #285 or a WAL-safe copy without look-ahead, separates
  regimes/contours, compares adaptive with static baseline, writes immutable evidence and exposes
  precise eligibility reasons. Current #285 must remain ineligible (not prospective, plan break,
  insufficient current-regime windows).
- Files: new `scripts/replay_quota_controller.py`, `app/quota_controller.py`, `app/db.py`,
  `app/routes/system.py`, focused tests.
- Test: `uv run python -m pytest -q docs/tasks/291/oracles/test_t4_replay_evidence.py`
  — committed RED in `f1a5460b24eb91b7408d11b0ecaa93bbdbb2571b`; first failing assertion:
  `assert spec is not None, "scripts/replay_quota_controller.py is not implemented"`.
- AC: named command is green; paired fixtures that differ only after time `t` produce
  byte-identical decisions through `t`; exact replay command above exits 0 and writes JSON with
  `eligible=false`; `prolite→pro`, unavailable Grok, zero-Spark sliding anchor and laptop/VPS
  boundary appear as exclusions/splits, not resets or zero usage; a synthetic qualifying corpus
  with multiple constraints/strata passes all seven machine criteria, and removing/missing any
  single global, constraint or stratum criterion flips only the affected authorization false with
  its exact reason.
- blocked-by: T1, T2, T3

### T5 — Deferred feature-flagged enforcement with hot rollback (not authorized by #291 Phase 3)

- Outcome: only after new approval, adaptive result replaces current static decision for a
  qualified bucket. Enable requires owner cookie, CAS revision, current prospective evidence id
  and exact live regime hash. Disable is immediate; drift/stale/corruption auto-demotes to static
  baseline. Already submitted turns are untouched.
- Files: `app/quota_controller.py`, `app/quota_gate.py`, `app/db.py`, `app/routes/system.py`,
  focused tests. No pipeline/prompt enforcement.
- Test: `uv run python -m pytest -q docs/tasks/291/oracles/test_t5_enforcement_rollback.py`
  — committed RED in `f1a5460b24eb91b7408d11b0ecaa93bbdbb2571b`; first failing assertion:
  `assert spec is not None, "app.quota_controller is not implemented"`.
- AC: named command is green; default and missing evidence stay shadow; stale/non-prospective/
  wrong-regime evidence cannot enable; a positive current evidence path selects adaptive only for
  named strata; revision CAS rejects stale writer; one hot disable restores object-identical current
  static decisions; controller exception and drift auto-demote atomically with visible reason; direct
  agent/internal-token API attempts get 403.
- blocked-by: T4; additionally barred until a post-T4 prospective evidence set satisfies the
  seven criteria and the orchestrator receives new explicit implementation approval.

## What not to touch

- Do not enable or repurpose the inert #187 router.
- Do not relax the current 95% gate during shadow calibration.
- Do not infer criticality from task priority, prompt text, role name or agent-supplied fields.
- Do not merge laptop and VPS Grok telemetry or treat auth failure as quota exhaustion.
- Do not promise exact 99% from integer counters; report target, guard and uncertainty.
- Do not add a second Fast bucket or price Spark as zero.
- Do not run replay on the live SQLite file; use `Connection.backup` or frozen JSON.

## Codex round 1 resolution

First-round architecture dissent remains verbatim in `codex-review-plan.md`. Findings 1–7 are
ACK: the v1 oracles allowed non-atomic parallel reservations, scalar Fable inputs,
cross-bucket evidence leakage, omitted gate mutations, look-ahead replay, disconnected delivery
helpers and always-refuse enforcement. The revised RED freeze closes each with executable tests.
Suggestion 8 is also accepted because later enforcement would make mutable evidence a safety bug;
DB triggers/FK/CHECK/index assertions are now part of T1.

Oracle freeze v1 commit `973432df` is superseded and excluded from Phase 3 replay. Commit
`f1a5460b24eb91b7408d11b0ecaa93bbdbb2571b` is the only immutable RED baseline for T1–T5.
