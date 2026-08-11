## Summary

The research correctly identifies the telemetry gap and selects one routing owner: a server-side quota router. It also properly separates measured Claude thresholds from the temporary Codex 90/95 product policy, rejects blind replay after terminal exhaustion, and acknowledges #174’s lossy handoff.

Sighted-review proof:

> “Модель не должна выбирать модель, а prompt/tool/message-инъекции квоты для маршрутизации не нужны.”

The proposal is not yet safe enough for Phase 2 because its durable blocked-delivery mechanism lacks replay protection.

## Findings

### Blocking

1. **The durable blocked queue has no idempotency or atomic-claim contract, creating a concrete duplicate-side-effect risk.**

   F7 requires storing the input before replying, then later waking and delivering it. It does not define:

   - a caller-supplied or server-issued idempotency key;
   - deduplication when the response is lost and HTTP/TG/orchestrator retries;
   - an atomic `queued → claimed → admitted/delivered` transition;
   - lease/recovery semantics if the process dies after backend submission but before marking delivery;
   - protection against concurrent wake and manual retry both submitting the same item.

   “One wake” does not prevent these races. A timeout after insertion can create two queue rows; a restart after backend admission can replay a row whose side effects already happened. This directly contradicts the research’s own prohibition on blind replay after terminal errors and can duplicate external tool side effects.

   The research must specify an idempotent enqueue identity and an atomic delivery/claim state machine, including the unavoidable ambiguous state where backend submission succeeded but acknowledgement was not persisted.

### Suggestion

1. **The independence rule and degraded single-runtime fallback contradict each other.**

   The ordered policy says independence excludes the implementation runtime, while F5 says work should continue on Opus with `degraded_review_independence` when Codex is exhausted. Under the stated eligibility algorithm, a Claude implementation awaiting review would exclude Claude and route to `all_runtimes_unavailable`, despite Claude being available.

   Define an explicit relaxation order, for example: enforce cross-runtime independence when possible; if no independent runtime exists, either require human authorization for degraded same-runtime review or deliberately admit it with a recorded degraded status. This must be part of the router, not an implicit exception elsewhere.

2. **“Atomic model selection” does not protect quota under concurrent admissions.**

   Several simultaneous spawns can read the same fresh observation below 90%, all select Codex, and collectively cross the reserve boundary. The research lists this as an edge case but does not decide whether the router serializes admissions, reserves estimated capacity, or accepts bounded overshoot as a product tradeoff.

   Since Codex cost per turn is not measured, the honest Phase 1 decision may be to serialize refresh-and-decision while acknowledging that external consumption between observation and admission still prevents a strict reserve guarantee.

3. **The structured `task_class` source is incomplete for persistent free-text entrypoints.**

   Known workflows can assign a class, but the proposal also routes every new idle orchestrator turn. Those turns currently receive free text, and the server is explicitly forbidden from inferring semantics. The research should define what happens when no trusted workflow supplies a class: reject loudly, use one conservative fixed class, or require the caller contract to change. Otherwise routing still depends on an unspecified second decision-maker.

## Verdict

**BLOCKED**

The server-side routing conclusion is sound, but the proposed durable queue can replay the same logical input and duplicate side effects. The delivery state machine needs an explicit idempotency and atomic-claim contract before implementation planning.

## Round (2026-08-11T10:18:11Z)

## Summary

All four prior findings are resolved or explicitly bounded as accepted limitations. The updated contract now has one routing owner, one durable ingress path, at-most-once delivery semantics, explicit independence degradation, serialized local admission, and deterministic handling of unclassified free text.

Sighted-review proof:

> “Только доказанный pre-submit failure возвращает row в `queued`; `submitted/completed/delivery_unknown` повторно не отправляются.”

## Findings

### Blocking

None.

### Suggestion

None.

### Prior findings

- **FIXED — durable queue replay risk.** Stable pre-retry `delivery_id`, unique DB identity, CAS claiming, persisted dispatch states, and fail-stopped `delivery_unknown` address retry, concurrency, and ambiguous-submit duplication.
- **FIXED — independence contradiction.** Independence is preferred first, then explicitly relaxed only when no independent eligible runtime exists, with mandatory `degraded_review_independence` reporting.
- **ACCEPTED LIMITATION — concurrent quota consumption.** Local refresh/decision/admission is serialized. Provider-side and per-turn overshoot are accurately described as unpreventable without reservation support or Codex pp/turn measurements; 90/95 is correctly labeled best-effort.
- **FIXED — free-text classification.** Unstructured orchestrator inputs receive the fixed server-owned `orchestrator_free_text` class; unknown classes fail loudly rather than restoring agent inference.

No new crash, corruption, data-loss, or security contradiction was found in the updated Phase 1 contract.

## Verdict

**APPROVED**
