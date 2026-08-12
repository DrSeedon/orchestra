# Codex review — #216 plan (Phase 2, проза, потолок 2 раунда)

- Attempt 1 started 2026-08-12: review of `docs/tasks/216/plan.md`.

## Attempt 1 — recovered from raw JSONL

Артефакт не записался: Codex отработал (`rc=0`), упал враппер `codex_review_artifact.py`.
Текст восстановлен из `/tmp/codex_review_quota-routing_codex-review-plan.jsonl`.

## Summary

The plan correctly identifies Spark as a separate quota bucket but does not yet define a coherent lane-aware routing contract. The largest risks are that Phase 3 would build an inert mechanism, mis-handle terminal limits and candidate ordering, and automatically undo pace-based degradation despite the research explicitly forbidding that behavior.

Sight-verification quote from the plan:

> “Параметризация непроверенного правила его не проверяет; включение — осознанное действие человека.”

## Findings

1. **blocking:** [docs/tasks/216/plan.md:216](/home/kesha/orchestra/worktrees/home-kesha-orchestra/quota-routing/docs/tasks/216/plan.md:216) — The phase explicitly defers the only production integration point. Current `RuntimeRouter` has no production caller, as the research also states, so T1–T4 cannot “make Orchestra route around” anything. They only extend an inert evaluator. T5 must either belong to this phase after #214 merges, or the plan/task outcome must explicitly be renamed to “prepare Spark routing policy”; otherwise Phase 3 can be declared complete while live routing remains unchanged.

2. **blocking:** [docs/tasks/216/plan.md:146](/home/kesha/orchestra/worktrees/home-kesha-orchestra/quota-routing/docs/tasks/216/plan.md:146) — Adding `lane` to `CandidateVerdict` is insufficient because selection remains runtime-keyed. `_choose_candidate()` accepts `Mapping[str, CandidateVerdict]`, obtains continuation via `candidates.get(current_runtime)`, and iterates the hard-coded `("codex", "claude")` tuple ([runtime_router.py:665](/home/kesha/orchestra/worktrees/home-kesha-orchestra/quota-routing/app/runtime_router.py:665)). The AC never specifies:

   - lane-keyed candidate storage;
   - stable lane ordering;
   - how multiple lanes with `runtime="codex"` are represented without overwriting;
   - whether selected lane is recorded separately from `selected_runtime`;
   - how continuation lookup behaves with two Codex lanes.

   Define candidates as lane-keyed, add `selected_lane`, and make every selection/filter step explicitly choose whether it operates on lane, runtime, or quota bucket.

3. **blocking:** [docs/tasks/216/plan.md:149](/home/kesha/orchestra/worktrees/home-kesha-orchestra/quota-routing/docs/tasks/216/plan.md:149) — Terminal quota state is still keyed by runtime, not lane or bucket. `terminal_limited_runtimes` accepts only `{"claude","codex"}` and `_codex_candidate()` receives `"codex" in terminal_limited_runtimes` ([runtime_router.py:534](/home/kesha/orchestra/worktrees/home-kesha-orchestra/quota-routing/app/runtime_router.py:534), [runtime_router.py:577](/home/kesha/orchestra/worktrees/home-kesha-orchestra/quota-routing/app/runtime_router.py:577)). With Spark, a terminal limit can belong to `codex` or `codex_spark` independently. Reusing the current signal either disables both lanes when one burns or leaves Spark unprotected. The plan must replace this with bucket/lane-keyed terminal limits and pin independent tests for both directions.

4. **blocking:** [docs/tasks/216/plan.md:95](/home/kesha/orchestra/worktrees/home-kesha-orchestra/quota-routing/docs/tasks/216/plan.md:95) — The pace formula treats provider-reported `resets_at − 10080m` as a trustworthy window start, but the research establishes that `resets_at` drifts substantially and that observed utilization drops define the actual reset events. The proposed guards only catch impossible elapsed shares; they do not catch a plausible-but-moving start inside `(0,1]`. Consequently the same utilization can change from `ok` to `alert` merely because `resets_at` moved, and the claimed replay of reconstructed windows does not validate the live formula unless those replays include every historical `resets_at` value.

   Missing or malformed `window_minutes` is computably fail-closed through `_quota_window()`, but the plan must specify that pace consumes the selected raw weekly window before `_codex_candidate()` discards `window_minutes`. More importantly, either derive a stable window identity/start from observed utilization resets or classify drifting/reset-inconsistent samples as `no_data`; the current formula does not support the stated deterministic decision.

5. **blocking:** [docs/tasks/216/plan.md:193](/home/kesha/orchestra/worktrees/home-kesha-orchestra/quota-routing/docs/tasks/216/plan.md:193) — T3 contradicts the research’s required hysteresis. Research F5 says that after degradation, return to normal must occur only after an observed window reset, not when the ratio becomes good again. The plan describes a stateless `ok | alert | no_data` calculation and immediate degradation, with no pace latch or stable reset identity. It would therefore reopen the expensive lane automatically after metric drift or a lower ratio. Add a durable lane/window-keyed degradation latch and an AC proving that falling ratio does not clear it, while an observed utilization reset does.

6. **blocking:** [docs/tasks/216/plan.md:183](/home/kesha/orchestra/worktrees/home-kesha-orchestra/quota-routing/docs/tasks/216/plan.md:183) — `PacePolicyV1` is defined with only `ratio_alert`, `warm_up_hours`, `min_utilization_pp`, and `action`, but the AC later requires degradation “to the lane specified by policy.” No such target field or validation rule exists. This leaves Phase 3 free to invent a fallback, which conflicts with deterministic routing and the AC forbidding “choose anything.” Add an explicit validated `degrade_to_lane`, define self-target/missing-target behavior, and state whether the target must also be quota-eligible.

7. **blocking:** [docs/tasks/216/plan.md:147](/home/kesha/orchestra/worktrees/home-kesha-orchestra/quota-routing/docs/tasks/216/plan.md:147) — “Behavior unchanged when `models.spark` is unset” is not satisfied by the current AC. `RoutingDecision.to_dict()` recursively serializes every dataclass field ([runtime_router.py:189](/home/kesha/orchestra/worktrees/home-kesha-orchestra/quota-routing/app/runtime_router.py:189)); adding `lane` changes both persisted `decision_json` and the `/explain` API even without Spark configuration. The plan acknowledges the added field but does not define contract migration, compatibility for old audit rows, or whether `ROUTING_CONTRACT_VERSION` must change. “No semantic changes” is too weak for an existing serialized contract. Pin exact old-policy JSON compatibility or explicitly version and migrate the decision schema and consumers.

8. **suggestion:** [docs/tasks/216/plan.md:75](/home/kesha/orchestra/worktrees/home-kesha-orchestra/quota-routing/docs/tasks/216/plan.md:75) — The code-versus-policy boundary is only partially pinned. A hard-coded continuation prohibition is justified by the runtime capability `resume_across_models=False`. Review handling is less complete: the plan forbids Spark only when implementation provenance contains `codex`, while research F8 says review should not be moved to a cheaper tier because measured review quality was insufficient. With Claude implementation, `eligible_classes=["review"]` could still select Spark as “independent.” Decide explicitly whether Spark review is forbidden globally or allowed for Claude-authored work; encode that single decision in validation/eligibility and add ACs for Claude, Codex, mixed, and unknown provenance.

## Verdict

**NEEDS WORK — 7 blocking findings.**

The lane concept is directionally correct, but the plan currently leaves selection identity, terminal-limit identity, serialization, pace hysteresis, and production integration unresolved. Implementing it as written would not yet route live work and could make quota decisions non-reproducible under reset drift.
- Attempt 2 started 2026-08-12: re-review after rewriting the plan for all 7 blocking findings.
  Round-1 session was NOT recorded in codex_sessions.json (wrapper died first), so round 2 runs a
  fresh session and carries the round-1 findings in its request context.

## Attempt 2 — recovered from raw JSONL (same wrapper failure)

## Summary

Все прежние замечания исправлены:

- F1 — FIXED
- F2 — FIXED
- F3 — FIXED
- F4 — FIXED
- F5 — FIXED
- F6 — FIXED
- F7 — FIXED
- F8 — FIXED

Подтверждающая строка из текущего плана:

> «Если #214 не смержится в разумный срок, правильный исход — сказать это оркестратору, а не закрыть фазу четырьмя инертными тикетами.»

## Findings (blocking/suggestion/question)

### blocking — T5 создаёт второго владельца admission-решения и нарушает границу #187 T3

T5 ставит `RuntimeRouter` перед существующим admission:

> «Подмена стоит строго после `validate_spawn` (:631) и до admission (:636)»

При этом план явно запрещает трогать `app/quota_gate.py`, а `docs/tasks/187/plan.md` T3 требует атомарной миграции всех callers и удаления самостоятельного `quota_gate` в одном коммите. Получается последовательность из двух владельцев решения:

`RuntimeRouter → legacy quota_gate → spawn`

Они имеют разные policy, thresholds и состояния. Кроме того, `RuntimeRouter` уже может вернуть `queued`, но T5 не определяет durable обработку этого результата; durable ingress принадлежит #187 T2 и ещё не указан как dependency T5.

Это может привести к противоречащим решениям или недолговечной/потерянной очереди. T5 должен либо:

- стать частью атомарного cutover #187 T2/T3 с удалением legacy admission; либо
- оставаться инертным и не объявляться production integration.

### blocking — T4 не включает ratchet в атомарную decision-транзакцию

Текущий `RuntimeRouter.admission()` атомарно коммитит audit decision и существующие latches через `commit_runtime_routing_decision()`. T4 требует отдельную immutable-таблицу и `ON CONFLICT DO NOTHING`, но не требует:

- читать snapshot ratchet до evaluation;
- проверять его неизменность через CAS;
- вставлять новый ratchet вместе с `decision_json` в одной транзакции;
- повторно вычислять решение при проигранной гонке;
- тестировать crash до и после общего commit.

Одного `ON CONFLICT DO NOTHING` недостаточно: конкурентный evaluator может закоммитить решение без уже появившегося понижения, а отдельный commit ratchet может пережить решение или потеряться после него. Следует расширить единый `RoutingStore.commit_decision()` и его DB-транзакцию, аналогично существующим `runtime_routing_latches`.

### question — не определена полоса, к которой применяется глобальный `pace`

`PacePolicyV1` описан как один policy-блок, но T3 говорит о «состоянии полосы», а T4 валидирует `degrade_to_lane` относительно «понижаемой» полосы, не задавая source lane.

Если pace применяется ко всем полосам, один `degrade_to_lane` становится самоссылкой для целевой полосы. Если только к `codex`, это должно быть частью контракта и AC. Если конфигурация должна быть per-lane, policy необходимо ключевать полосой.

До реализации нужно однозначно определить owner/source lane, иначе Phase 3 может построить разные механизмы из одного текста.

## Verdict

CHANGES REQUESTED — два блокирующих дефекта: двойной admission owner в T5 и неатомарный durable ratchet в T4.
## Round 2 outcome and post-ceiling fixes (author note)

Round 2 marked all eight round-1 findings FIXED and raised two new blocking plus one question.
All three were verified against the source and accepted:

1. **T5 создавал второго владельца admission.** Подтверждено: `manager.py:636` — это существующий
   `require_worker_admission`, а `docs/tasks/187/plan.md:432` (#187 T3) уже требует атомарной
   миграции всех вызывающих с удалением легаси одним коммитом, и `pipelines/default/prompts/base.md`
   стоит в его же списке файлов. То есть мои T5 и T6 дублировали чужой тикет. Исправлено: #216
   больше не заводит тикетов на подключение, а передаёт требования в #187 T3; прежний T6 растворён
   там же.
2. **Храповик темпа был вне атомарной транзакции решения.** Подтверждено: `commit_decision` уже
   держит `BEGIN IMMEDIATE` с CAS по revision и по множеству latch-строк (`runtime_router.py:402`).
   Исправлено: snapshot храповика читается до вычисления, входит в тот же CAS и пишется тем же
   commit'ом; добавлены AC на два crash-окна.
3. **question про полосу `pace`.** Отвечено решением: `pace` конфигурируется по полосе и
   применяется только к семейству Codex; для `claude` отвергается при валидации, потому что
   владелец суждения о темпе Claude — метрика `D` из #186.

Потолок раундов для прозы (2) исчерпан, третий раунд не запускался. Исправления внесены после
потолка.

**Verdict of record: CHANGES REQUESTED (round 2).** Артефакт намеренно не помечен APPROVED.

## Infrastructure note

Оба раунда: Codex отработал (`rc=0`), но артефакт не записался — после merge #215 (08:21:48)
`app/codex_review_artifact.py` требует `--usage-*`, которых не передаёт MCP-процесс, поднятый
до мержа (мой стартовал 05:58:23). Тексты обоих раундов восстановлены из
`/tmp/codex_review_quota-routing_codex-review-plan.jsonl`. Подан `report_bug`; в 08:22 то же
самое поймали `impl-effort-model` и `fix-grep-guard`.
