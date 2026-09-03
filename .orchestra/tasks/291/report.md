# #291 — Phase 3 report: adaptive quota controller Release A

## Result

T1–T4 are implemented and accepted as a strictly shadow/advisory Release A. The controller
normalizes independent provider constraints, records a transactional adaptive recommendation,
observes real dispatch and settlement seams, and produces deterministic causal replay/evidence.
It has no authority to hold, reroute, or allow a provider turn.

T5 is not implemented. There is no enforcement enable route or feature flag, and the existing
static `WORKER_WEEKLY_LIMIT_PCT = 95.0` gate remains unchanged. The schema accepts the reserved
value `mode='enforce'` only for the separately planned future migration/API contract; no T1–T4
runtime branch can select it. No service restart, deployment, or configuration mutation was made.

## Tickets delivered

### T1 — durable topology, telemetry normalization, and schema

- Anthropic exposes independent `five_hour` and `seven_day` constraints; Fable is a separate
  `weekly_scoped` constraint.
- Codex primary, Codex Spark primary, and Grok primary are independent buckets. Fast is a
  multiplier on Codex primary, never a synthetic bucket.
- Grok refresh state has its own lock and timestamp. Authentication/refresh failure produces
  absent/unknown telemetry, never a false zero.
- SQLite installs five controller tables, three explicit indexes, and nine immutability triggers
  transactionally. Existing compatible rows survive repeated initialization.
- Every open validates canonical normalized DDL for all tables, indexes, and triggers. Recognized
  compatible partial topology is repaired transactionally; incompatible or definition-corrupt
  topology fails loudly.

### T2 — transactional adaptive shadow gate

- Each active constraint evaluates the inclusive boundary
  `u + q95(next_turn) + guard <= 99 - reserve` independently.
- Fable's three constraints must all pass; the decision records the binding constraint.
- GPT-5.6/5.5 Fast uses Codex-primary multiplier 2.5, GPT-5.4 Fast uses 2.0, while Spark and Grok
  keep their independent buckets and multiplier 1.0.
- Stale telemetry, plan change, counter drop, corrupt values, insufficient confidence, or drift
  produce `recommendation=indeterminate`, `would_allow=null`, and `zone=FAIL_SAFE`.
- `BEGIN IMMEDIATE` covers reservation lookup, evaluation, immutable decision append, and allowed
  reservation creation, preventing concurrent dispatches from spending the same headroom.

### T3 — production shadow calibration at real delivery seams

- A new provider turn reserves shadow capacity after final worker admission and before the sole
  `backend.send`; successful submission and terminal settlement are recorded at the real
  `AgentSession`/`TurnManager` seams.
- Retry, auto-continue, queued flush, normal sends, and orchestrator sends carry explicit intent
  context. Mid-turn injection does not create a new dispatch decision.
- `(session_id, turn_gen)` deduplicates admission refresh/retry; terminal `event_id` makes outcome
  settlement idempotent; intervals retain submitted/ended timestamps for overlap analysis.
- Observer exceptions, including observer-originated cancellation, are logged/counted and cannot
  suppress or duplicate provider delivery. Genuine external cancellation before provider submit
  still cancels the send; bookkeeping cancellation after provider acceptance cannot turn success
  into a retryable failure.
- Settlement SQLite work is off the event loop and its task failure is observed.
- Production defaults to the active shadow observer so Release A actually collects calibration.
  `GET /api/usage/quota-controller` reports `mode=shadow` and
  `enforcement_active=false`; reserve mutation routes require the operator cookie.
- Route snapshot delta is exactly 18 lines for exactly three planned routes:
  `GET /api/usage/quota-controller`, `POST /api/usage/quota-controller/reserve`, and
  `DELETE /api/usage/quota-controller/reserve/{intent_id}`.

### T4 — causal replay and fail-closed evidence eligibility

- `scripts/replay_quota_controller.py` replays JSON schema 2 or SQLite data without look-ahead.
  Decisions at time `t` see only outcomes whose settlement availability is strictly earlier than
  `t`; equal-timestamp and unsettled outcomes cannot enter their own or concurrent forecasts.
- Evidence is scoped per constraint and per stratum. A stratum must reference exactly its
  topology-derived constraint set; any foreign extra bucket yields `cross_bucket_evidence`.
- All evidence criteria fail closed independently. Release A requires at least three stable
  same-regime windows, adequate samples/blocks/ESS and safety calibration.
- The originally approved `>=80%` per-window telemetry coverage requirement is superseded by
  `>=90%`. This is the conservative immutable-oracle correction explicitly authorized on
  2026-08-16: Release A only evaluates shadow evidence eligibility, so the stricter threshold can
  delay eligibility but cannot block, route, or authorize live work.

## Migration and rollback evidence

- T1's frozen oracle proves repeated initialization preserves legacy data, constraints reject
  invalid rows, and an incompatible pre-existing object rolls back the controller migration as a
  unit.
- A partial compatible schema probe reopened with all five tables and required supporting
  objects. A corrupt partial schema failed loudly.
- Independent final-review probes replaced an immutability trigger with a no-op definition and
  changed an index definition. Both reopens failed with `incompatible quota controller object`.
- Audit decisions, outcomes, and evidence reject `UPDATE`, `DELETE`, and replacement writes.
- Release A runtime rollback is removal/disablement of observation only; dispatch remains owned by
  the unchanged static gate even if every shadow call fails. The future T5 hot rollback is not
  present and remains a separate authorization boundary.

## Acceptance evidence

### Frozen and relevant tests

The immutable RED baseline remains byte-identical to
`f1a5460b24eb91b7408d11b0ecaa93bbdbb2571b`.

```text
uv run python -m pytest -q \
  docs/tasks/291/oracles/test_t1_schema_and_topology.py \
  docs/tasks/291/oracles/test_t2_adaptive_gate.py \
  docs/tasks/291/oracles/test_t3_shadow_delivery.py \
  docs/tasks/291/oracles/test_t4_replay_evidence.py \
  tests/test_db.py tests/test_session.py tests/test_session_hibernate.py \
  tests/test_session_id_guard.py tests/test_mcp_quota_gate.py tests/test_quota_alert.py \
  tests/test_quota_alert_state.py tests/test_quota_gate.py tests/test_quota_headroom.py \
  tests/test_quota_runway.py tests/test_quota_runway_baseline.py tests/test_limit_wake.py \
  tests/test_antigravity_usage.py tests/test_codex_usage.py tests/test_runtime_router.py \
  tests/test_runtime_router_api.py tests/test_runtime_router_auth.py \
  tests/test_runtime_router_db.py tests/test_runtime_router_spark.py \
  tests/test_routes_surface.py tests/test_turn_ended_no_quota_suffix.py \
  tests/test_turn_usage.py tests/test_usage_analytics.py tests/test_usage_contract.py \
  tests/test_usage_history_resolution.py tests/test_usage_readiness.py \
  tests/test_usage_snapshot.py

769 passed, 12 skipped in 183.48s
```

The final Sol review independently ran the four frozen oracles, route surface, and two delivery
regressions: `25 passed in 6.16s`.

The required broad command
`uv run python -m pytest -x -q > /tmp/pytest-291.log 2>&1` stopped during collection before any
test executed:

```text
ImportError: cannot import name '_goto_dashboard_or_skip' from 'tests.test_frontend'
ERROR tests/test_system_chat_entry.py
1 error in 10.05s
```

This is a current-`main` baseline defect outside #291: `tests/test_system_chat_entry.py` imports
that symbol, `main:tests/test_frontend.py` does not define it, and the #291 diff changes neither
file. It is not reported as a green full suite; the 769-test relevant run above is the completion
evidence for this change.

### Replay and production-shaped probes

The final real #285 replay was executed twice after all review fixes. Both outputs had SHA-256
`c3ad36898206a794db61bdd3474166ca26a86429603b06c4af55323c89f30826` and reported:

```text
schema_version=2, input_schema_version=2
eligible=false, prospective=false, contours_merged=false
decision_count=2346
reasons=[not_prospective, live_regime_mismatch, no_enabled_strata,
         insufficient_stable_same_regime_windows]
```

Additional probes produced:

```text
decision_before_send=1 mode=shadow adaptive=null static=available delivery_calls=1
reserve_cancel_delivery=1 submitted_cancel_delivery=1
external_cancel: pre_submit_delivery=0 post_submit_delivery=1 post_submit_result=success
replay DB causal history outcomes=[0, 0, 1]
cross_bucket eligible=0 reason=cross_bucket_evidence
corrupt trigger fail_loud=1; corrupt index fail_loud=1
```

## Review gate

- Changed consumers: provider telemetry normalization, SQLite migration/audit storage,
  shared `AgentSession`/`TurnManager` delivery, authenticated system routes, and offline evidence
  replay. These trigger the mandatory high-risk Sol floor.
- Author metadata: accepted T4 and final integration/review fixes ran on Codex
  `gpt-5.6-sol`; delegated attempts used Codex Luna/Sol. The decision does not infer models from
  worker names.
- Exact AC: frozen T1–T4 commands green; real delivery remains unchanged under all observer
  failures; deterministic causal replay; no enforcement authority; static 95% gate unchanged.
- Named evidence: the 769-test command/output above plus the byte-identical frozen baseline and
  deterministic replay hash.

Sol review used three executable rounds, the maximum allowed by `codex-debate`:

1. Five blocking findings: cancellation coupling, partial schema acceptance, SQLite replay
   look-ahead, cross-bucket evidence leakage, and a disputed observer-default requirement; plus
   synchronous settlement. The owner requirement established that active shadow collection is
   intentional, so that default finding was withdrawn. The remaining issues were fixed.
2. The reviewer closed those items but reproduced same-name corruption of a trigger/index
   definition. Canonical normalized DDL validation was added.
3. The reviewer reran 25 tests, independently rejected corrupt trigger/index definitions, found no
   remaining blockers, and returned `APPROVE`.

Review artifact: `docs/tasks/291/codex-review-impl.md`.
`cross-family verdict unavailable`: an Opus reviewer could not be started because Claude weekly
quota was 100% at the 95% admission threshold.

## Pre-mortem and regression checks

1. Shadow failure blocks or duplicates delivery -> real T3 seam oracle plus exception and
   cancellation probes; exactly one provider send remains observable.
2. Concurrent reservations overspend final headroom -> two-connection `BEGIN IMMEDIATE` T2 oracle;
   one allow and one hold.
3. Partial/corrupt schema silently loses immutability -> T1 rollback tests plus canonical DDL
   trigger/index corruption probes.
4. Replay learns from future or sibling-bucket data -> paired-prefix/equal-timestamp causal tests,
   settled-at probe, and exact-topology cross-bucket probe.
5. New routes bypass owner authorization or drift from the API surface -> T3 auth oracle and exact
   route snapshot delta.
6. Shadow becomes an authority accidentally -> no adaptive enforcement branch, status remains
   `enforcement_active=false`, `app/quota_gate.py` is absent from the diff, and its threshold is
   still 95.0.

## Breaking changes and follow-up

Breaking changes: none. Release A adds append-only shadow data and three operator/status routes;
provider dispatch/routing behavior remains the existing static behavior.

T5 remains TODO in a separate feature-flagged ticket. It requires new explicit authorization,
prospective machine evidence for at least three stable same-regime windows with adequate sample
size and 90% window coverage, named-stratum enablement, and tested hot rollback. Nothing in this
release satisfies or bypasses that future authorization.
