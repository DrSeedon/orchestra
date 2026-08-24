# #298 — implementation plan: server-owned total worker routing

## Outcome and ownership

Implement one server-owned, first-match router that runs before worker session creation.
The router consumes trusted task metadata plus server-derived runtime/quota/canary state and
returns either a typed model/runtime/effort decision or a typed refusal. Prompt text mirrors
the decision contract; it is not an authority.

Policy order:

1. Invalid metadata or disabled Fable/Terra request → visible refusal.
2. Private/sensitive work → Claude Opus for special creative/vision/ambiguity, Luna for
   closed deterministic, and authorized Sol for the remaining Sol-class branch.
3. Public special creative/vision/exceptional ambiguity → Claude Opus.
4. Positive Codex-exhaustion status plus explicit consequence permission → Claude Opus.
5. Every Sol-class branch checks a scope-bound trusted `sol_authorized` receipt first;
   absent/invalid/expired/mismatched receipt → `REFUSE_SOL_AUTH` + request-decision, never
   Ox/Luna downgrade.
6. Public closed deterministic → Ox when exact zero-spend, broker, capability, oracle and
   class-canary gates pass; otherwise Spark only under its strict measured contract; otherwise
   Luna. Spark gets one attempt and one handoff, never retry.
7. Public open/complex → authorized Sol; no receipt → `REFUSE_SOL_AUTH`.
8. No route/readiness → visible refusal preserving task state.

Exact leaves are `claude-opus-5[1m]`/claude/high for Opus exceptions and Codex-exhaustion
consequence, `gpt-5.3-codex-spark`/codex/high for the strict Spark leaf,
`stealth/ox-alpha`/harness with class-routed effort for Ox, `gpt-5.6-luna`/codex/high for
closed deterministic fallback, and `gpt-5.6-sol`/codex/xhigh only after a valid
`sol_authorized` receipt. Fable/Terra are explicit disabled refusals.

### Canonical owners

- `app/model_router.py` (new): `TaskRoutingMetadata`, `SolAuthorizationReceipt`, trusted
  `RoutingRuntimeState`, `RouteDecision`, and the pure total `evaluate_route()` first-match
  function. This is the only policy owner.
- `app/mcp_stdio.py`, `app/routes/sessions.py`, `app/manager.py`: ingress and pre-spawn
  enforcement. `mcp_stdio.route_worker()` is the explicit adapter/re-export seam: it accepts
  metadata and receipt, obtains `RoutingRuntimeState` only from the server state provider, and
  never accepts caller `route_state`. Caller model is an optional legacy override subject to
  router policy, never an authority; omitted/legacy requests are visible refusals, not implicit
  Sonnet. The same verified receipt gate is applied by `codex_review` before any explicit Sol
  review session; its previous non-goal is superseded for this authorization fix.
- `app/db.py`, `app/session.py`: durable metadata/receipt reference/route revision and
  backward-compatible loading.
- `app/models.py`, `app/runtime_registry.py`: model/runtime/capability metadata and exact
  effort propagation.
- `app/openrouter_broker.py` (new), `app/openrouter_counter.py`, `app/harness/llm.py`:
  atomic OpenRouter lease, zero-spend proof, unknown-cost fail-closed, platform/upstream
  distinction, and exact-model retry boundary.
- `app/backend_codex.py`, `app/session.py`, `app/manager.py`: explicit routed effort and Spark
  one-turn/send/handoff state on the production Codex path. Spark is runtime `codex`; it is not
  an OpenRouter/harness route. `app/backend_harness.py`, `app/harness/llm.py` remain Ox-only
  broker/cost owners.
- `app/prompting.py`, `pipelines/default/prompts/modules/model-routing.md`: generated
  explanatory mirror with anchors; no independent routing rules.
- `app/routes/system.py`, `app/db.py`, and existing usage surfaces: route decision, refusal,
  fallback, receipt id (not payload), canary revision, budget state and rollback telemetry.

## Data contract and migration

`TaskRoutingMetadata` is server-validated and contains `task_id`, `scope`, `sensitivity`,
`openness`, `complexity`, `oracle` descriptor, context estimate, required tools, vision flag,
named-file count, explicit-decision flag, and requested model override. `named_file_count` and
`all_decisions_explicit` are required fields; no unsafe default is inferred. Unknown openness,
complexity, capability or oracle is invalid metadata and returns `REFUSE_METADATA`, not a Sol
authorization request. `route_state` is never caller-supplied: quota, broker, model
availability, canary revision, Codex binding and Codex-exhaustion status are assembled by the
server state provider. The pure evaluator has a test-only injected `RoutingRuntimeState` seam;
the MCP adapter has no caller state parameter.

`SolAuthorizationReceipt` is a separate trusted input with `receipt_id`, `task_id`, `scope`,
requester, issued/expiry timestamps, reason, issuer/signature and status. Validation rejects
missing, expired, scope-mismatched, task-mismatched and unverifiable receipts. Parent-task
approval, prompt text, a model alias and an old Sol session are not receipts.

Persist a `routing_receipts` table and add nullable session fields for `routing_metadata`,
`sol_receipt_id`, `route_revision`, and `routing_status`. Existing rows load as
`legacy_unknown`; they resume unchanged, but a new spawn/change-model request without trusted
metadata is refused visibly. No migration may reinterpret old `claude-sonnet-5[1m]` as a new
router decision or silently promote an old model.

## Tickets

### T1 — trusted metadata ingress and total router seam

- Files: `app/model_router.py` (new), `app/mcp_stdio.py`, `app/routes/sessions.py`,
  `app/manager.py`, `app/db.py`, `app/session.py`.
- Test: `docs/tasks/298/acceptance/test_model_routing_tree.py::test_t1_route_worker_has_server_owned_total_contract`
  and `::test_t12_invalid_metadata_refuses_before_sol_authorization` — committed RED in
  `af1575df`; command below; first failures:
  `AssertionError: #298 route_worker server seam is missing`.
- AC: `mcp_stdio.route_worker(task_metadata=..., sol_authorized=...)` is the server adapter and
  `evaluate_route(..., runtime_state=...)` is the testable pure seam; the adapter has no
  caller-supplied `route_state` parameter and obtains state only from its server provider.
  The RED matrix monkeypatches only the private `_runtime_state_provider`; public signature
  excludes both `runtime_state` and `route_state`. Required metadata includes named-file count
  and explicit-decision flag; unknown values return `REFUSE_METADATA`. Existing sessions load
  with migration defaults; omitted legacy model is a visible refusal, not an implicit Sonnet.
- blocked-by: none

### T2 — scope-bound Sol authorization receipt and spawn/review gate

- Files: `app/model_router.py`, `app/mcp_stdio.py`, `app/routes/sessions.py`, `app/manager.py`,
  `app/db.py`, `app/session.py`, `pipelines/default/prompts/skills/codex-debate.md`.
- Test: `docs/tasks/298/acceptance/test_model_routing_tree.py::test_t2_sol_class_without_receipt_refuses_before_any_sol_call`
  `::test_t3_sol_class_valid_receipt_selects_sol_and_invalid_never_downgrades`, and
  `::test_t13_codex_review_sol_requires_the_same_trusted_receipt` — committed RED in
  `af1575df`; same command; first failure:
  `AssertionError: #298 route_worker server seam is missing`.
- AC: every Sol-class predicate with valid metadata and missing/expired/mismatched receipt
  returns `REFUSE_SOL_AUTH`, emits request-decision state, and performs 0 Sol spawn/review/eval
  calls; invalid metadata returns `REFUSE_METADATA` first. Valid scope-matched receipt selects
  `gpt-5.6-sol`/codex/xhigh. Both `spawn_worker` and explicit `codex_review(model=sol)` verify
  the same durable receipt before creating a Sol session; invalid receipt never selects Ox or
  Luna. Receipt data is auditable without storing secret payloads.
- blocked-by: T1

### T3 — explicit all-model first-match matrix

- Files: `app/model_router.py`, `app/models.py`, `app/runtime_registry.py`, `app/mcp_stdio.py`.
- Test: `docs/tasks/298/acceptance/test_model_routing_tree.py::test_t4_total_model_matrix_selects_explicit_leaf`
  and `::test_t5_disabled_fable_and_terra_are_explicit_refusals` — committed RED in `af1575df`;
  same command; first failure:
  `AssertionError: #298 route_worker server seam is missing`.
- AC: disjoint matrix returns exact leaves: Opus/Claude special exception, Spark strict
  overflow, Ox eligible public closed deterministic, Luna closed fallback, authorized Sol,
  `REFUSE_DISABLED_MODEL` for Fable/Terra, `REFUSE_ORACLE`, `REFUSE_METADATA`, and
  `REFUSE_NO_ROUTE`. Caller model override cannot bypass predicates. No leaf is selected by
  prompt default or HTTP Sonnet default.
- blocked-by: T2

### T4 — Spark strict one-attempt Codex handoff

- Files: `app/model_router.py`, `app/backend_codex.py`, `app/session.py`, `app/manager.py`,
  `app/mcp_stdio.py`, new `docs/tasks/298/acceptance/test_model_routing_execution.py`.
- Test: `docs/tasks/298/acceptance/test_model_routing_tree.py::test_t6_spark_contract_is_one_attempt_and_handoff_is_not_retry`
  and `docs/tasks/298/acceptance/test_model_routing_execution.py::test_t14_spark_codex_session_failure_handoffs_without_retry`
  — committed RED in `af1575df`; same command; first failures:
  `AssertionError: #298 route_worker server seam is missing`.
- AC: Spark is selectable only when Codex is binding, text-only, ≤2 named files, ≤100K initial
  context, all decisions explicit, independent pre-existing oracle, Spark quota available, and
  not research/review/security/vision. One failed/incomplete Spark attempt records handoff to
  Luna for closed work or authorized Sol for Sol-class work; a second Spark attempt is
  impossible. T14 uses a fake Codex backend through `AgentSession._turn_event_loop`, records
  exactly one fake-Codex `send`, asserts no automatic retry/handoff spawn for Spark, and requires
  durable/in-memory `routing_status='handoff_luna'`, preserved `task_id` and handoff model.
  Internal retry behavior inside the provider-owned Codex CLI is outside this contract and is
  not tested.
- blocked-by: T3

### T5 — Ox broker, zero-spend and unknown-cost guard

- Files: `app/openrouter_broker.py` (new), `app/openrouter_counter.py`, `app/db.py`,
  `app/harness/llm.py`, `app/backend_harness.py`, `app/model_router.py`,
  new `docs/tasks/298/acceptance/test_model_routing_execution.py`.
- Test: `docs/tasks/298/acceptance/test_model_routing_tree.py::test_t7_ox_guard_rejects_paid_or_unknown_cost_before_provider_post`
  and `docs/tasks/298/acceptance/test_model_routing_execution.py::test_t15_route_admission_serializes_last_lease`
  and `::test_t17_ox_unknown_price_is_rejected_before_http_lease` — committed RED in `af1575df`;
  command below; first failures. `price_proof` is passed to both T15 contenders and T17;
  T7 exercises missing/None/bool/string/positive/unknown fields and exact numeric zero:
  `AssertionError: #298 OpenRouter pre-POST admission seam is missing`.
- AC: every OpenRouter attempt obtains an atomic broker lease before POST; missing/positive/
  unknown price proof refuses before POST; missing `usage.cost` is unknown and fails the Ox
  preferred route rather than becoming zero; platform 429 closes the pool, upstream 429 marks
  only the exact route unhealthy; no paid fallback or random free router. `usage.cost` and
  route revision are persisted without breaking cumulative-cost monotonicity. Broker leases
  carry a generation/revision and interleaving two contenders for one remaining lease grants
  exactly one; stale canary/quota/route revisions cannot start a turn. T7/T17 negative
  controls cover missing, `None`, boolean `False`, string `'0'`, positive, and unknown declared
  price fields; both contenders in T15 provide exact numeric zero proof, and only exact numeric
  zeros can obtain a lease.
- blocked-by: T3

### T6 — scope-growth reclassification and fallback invariants

- Files: `app/model_router.py`, `app/session.py`, `app/manager.py`, `app/mcp_stdio.py`,
  `app/db.py`.
- Test: `docs/tasks/298/acceptance/test_model_routing_tree.py::test_t8_scope_growth_reclassifies_before_next_turn`
  — committed RED in `af1575df`; command below; first failure:
  `AssertionError: #298 route_worker server seam is missing`.
- AC: scope growth invalidates Ox/Luna eligibility before the next turn; open/complex growth
  reclassifies to authorized Sol or returns `REFUSE_SOL_AUTH`; closed work never silently
  escalates; every refusal/fallback preserves task state and records route revision/reason.
- blocked-by: T3

### T7 — routed effort and generated prompt mirror

- Files: `app/model_router.py`, `app/pipeline.py`, `app/runtime_registry.py`,
  `app/backend_harness.py`, `app/harness/loop.py`, `app/prompting.py`,
  `pipelines/default/prompts/modules/model-routing.md`.
- Test: `docs/tasks/298/acceptance/test_model_routing_tree.py::test_t9_prompt_is_generated_mirror_of_server_contract`
  — committed RED in `af1575df`; command below; first failure:
  `AssertionError: assert 'sol_authorized' in prompt`.
- AC: router output carries exact model/runtime/effort; Codex uses manifest-compatible effort;
  harness receives the routed effort instead of reclassifying free-text messages; generated
  prompt mirror contains `sol_authorized`, `REFUSE_SOL_AUTH`, Spark and disabled-model anchors,
  while the server router remains authoritative.
- blocked-by: T3

### T8 — override protection, legacy refusal and shadow rollout

- Files: `app/routes/sessions.py`, `app/mcp_stdio.py`, `app/manager.py`, `app/model_router.py`,
  `app/routes/system.py`, `app/db.py`, `app/static/js/usage.js`, new focused router/migration
  acceptance tests. `docs/tasks/298/acceptance/test_model_routing_tree.py` is frozen and must not be edited after the final RED
  commit; CI verifies its blob matches that commit.
- Test: `docs/tasks/298/acceptance/test_model_routing_tree.py::test_t10_caller_model_override_cannot_bypass_server_router`
  and `::test_t11_legacy_omitted_model_is_refused_not_implicit_sonnet` — committed RED in final
  frozen RED commit `af1575df`; command below; first failures:
  `AssertionError: #298 route_worker server seam is missing` and
  `AssertionError: legacy omitted model must be a visible refusal, not Sonnet`.
- AC: caller overrides cannot choose Sol/Ox/Spark/Fable/Terra outside the router; legacy
  omitted-model calls return structured refusal instead of HTTP Sonnet; shadow mode logs
  route/refusal/fallback/receipt revision without provider calls; rollout can be disabled by
  route revision/feature gate; observability omits secret payloads. The frozen authorization
  matrix is the rollback oracle: 0 Sol spawn/review/eval calls without a valid receipt.
- blocked-by: T2, T3, T5, T6, T7

### T9 — frozen-oracle immutability and deterministic focused checks

- Files: `docs/tasks/298/acceptance/test_model_routing_execution.py`,
  `docs/tasks/298/acceptance/test_model_routing_migration.py`, CI/oracle check script only;
  never edit the frozen `docs/tasks/298/acceptance/test_model_routing_tree.py` after the final
  RED commit.
- Test: `docs/tasks/298/acceptance/test_model_routing_execution.py::test_t14_spark_codex_session_failure_handoffs_without_retry`,
  `::test_t15_route_admission_serializes_last_lease`, and
  `docs/tasks/298/acceptance/test_model_routing_migration.py::test_t16_legacy_schema_migrates_route_fields_and_receipt_table`
  — committed RED in `af1575df`; exact focused commands below.
- AC: fake Codex session proves one send, no Spark retry/handoff spawn, and exact handoff state;
  fake concurrent broker
  proves one lease wins; old-schema migration uses an explicit `tmp_path` DB_PATH monkeypatch and
  proves captured `LEGACY_SESSIONS_SQL` pre-routing schema → route columns/table → hydrate/save/
  active-worker next-turn compatibility without touching live/worktree DB. A blob/checksum check
  rejects any mutation
  of the frozen routing matrix after the RED commit.
- blocked-by: T1, T4, T5

## Cross-ticket migration, rollback and non-goals

Migration is additive and fail-closed: nullable routing columns/table, explicit legacy status,
and no reinterpretation of persisted sessions. Existing active workers keep their model and
session; new starts and model changes must obtain fresh trusted metadata. Any invalid receipt,
unknown budget/cost, provider platform 429, canary failure, secret-to-Ox attempt, Spark second
attempt, or Sol call without receipt disables the affected route revision and returns visible
refusal. Rollback disables enforcement for the affected route revision only; it does not
silently restore HTTP Sonnet or delete receipt/audit evidence.

Do not change `codex_review` routing/defaults except the mandatory Sol receipt gate, infer Ox
identity, launch any provider/model/eval call during this task, enable Fable/Terra, add paid
OpenRouter fallback, or make prompt text a security/admission control. No frontend redesign is
included; usage UI only receives the server-owned observability fields needed for diagnosis.

## Luna review resolution (round 1)

Review artifact: `docs/tasks/298/review-plan-luna.md`, reviewer `gpt5.6luna`, one fresh round,
verdict **Not ready**. The reviewer made no provider/model/eval calls. All blocking findings
were resolved in this plan and the RED oracle before the next review attempt:

1. **Trusted runtime state — FIXED:** public `mcp_stdio.route_worker` is now an adapter with
   neither `runtime_state` nor `route_state`; tests monkeypatch only the private
   `_runtime_state_provider`. Only pure `evaluate_route(..., runtime_state=...)` has an
   injected state seam. T1 AC and the test contract state this distinction.
2. **Required metadata — FIXED:** named-file count and explicit-decision fields are required;
   the fixture supplies them, and T12 covers invalid/unknown metadata as `REFUSE_METADATA`.
3. **Unknown ordering — FIXED:** unknown required metadata is invalid and refuses before Sol
   auth; valid Sol-class cases in T2 use complete metadata. Policy and tests now agree.
4. **Sol review bypass — FIXED:** T2 now gates both `spawn_worker` and explicit
   `codex_review(model=sol)` through the same durable receipt; `test_t13` freezes the resolver
   requirement. The earlier non-goal was narrowed to “no review-default change except the
   mandatory Sol receipt gate.”
5. **Spark retries — FIXED:** Spark is runtime `codex`, not harness/OpenRouter. T4 now owns
   `app/backend_codex.py`/`app/session.py`; T14 uses a fake Codex backend through the production
   session event loop, records one send and asserts no automatic retry/handoff spawn. Provider-
   internal Codex CLI retries are explicitly outside this contract.
6. **Admission TOCTOU — FIXED:** T5 requires generation/revision-bound leases and an
   interleaving test (`test_t15`) proving one winner for one remaining lease; stale quota,
   canary and route revisions cannot start.
7. **Oracle immutability — FIXED:** the final RED commit is `af1575df`; earlier defective
   `954d2233` and `2ae4f8aa` are superseded/excluded, and `f54690cd` is superseded/excluded
   solely because its `tests/` placement entered the mapped merge gate. The frozen matrix is
   read-only thereafter and T9 requires a CI blob/checksum check.
8. **Ox AC coverage — FIXED:** T5 adds `test_t17` for unknown price rejection before lease,
   both T15 contenders pass exact numeric-zero proof, and T7 covers missing/bool/string/positive/
   unknown price negatives plus exact-zero positive control; provider behavior remains fake-only.
9. **Migration/backcompat — FIXED:** T9 adds `test_t16` with explicit tmp_path DB_PATH
   monkeypatch, pre-routing schema fixture, route columns/table and hydrate/save coverage;
   active-worker next-turn compatibility remains an implementation AC.
10. **Public seam — FIXED:** T1 explicitly requires the `mcp_stdio.route_worker` adapter and
    pure evaluator split, so implementation cannot create only the new owner and leave the
    frozen public seam absent.

The review's minority concern that a caller could forge state is preserved in finding 1's
resolution: the pure seam is test-only; production ingress obtains runtime state internally.

Positive controls are frozen alongside the negatives: matrix leaves must select Opus/Spark/Ox/
Luna when the private provider is monkeypatched with matching trusted state; T7 exact numeric
zero price proof must allow Ox while malformed/positive/unknown proofs refuse; T14's fake Codex
receives exactly one send; and T16's `tmp_path` DB_PATH is the only database opened.

## Review route

This is a high-risk admission/security/schema plan. One fresh Luna plan review is authorized;
no Sol, Ox, Opus, provider, eval, or additional reviewer call is authorized. Review must inspect
`docs/tasks/298/plan.md` and the frozen RED commit `af1575df`, and must report concrete findings
with a quote or command/output evidence. The plan cannot be reported ready without reading the
review artifact.

## Mapped-gate placement evidence

`uv run python -m pytest --collect-only -q` returned `collect_rc=2` from an unrelated existing
`tests/test_process_guard.py` collection error (`os.pidfd_open` unavailable), but the exact
acceptance path count was `acceptance_nodes=0`. The intentional RED files are therefore no
longer collected by the normal mapped `tests/` gate.

## Frozen RED evidence (last section; do not append prose after this)

Command:

```text
uv run python -m pytest docs/tasks/298/acceptance/test_model_routing_tree.py docs/tasks/298/acceptance/test_model_routing_execution.py docs/tasks/298/acceptance/test_model_routing_migration.py -q
```

Exit: `1` (`22 failed`).

First missing-behavior assertion:

```text
docs/tasks/298/acceptance/test_model_routing_tree.py:19: AssertionError
assert callable(route), "#298 route_worker server seam is missing"
```

Additional deterministic RED assertions include `test_t14` (current Codex session schedules
`_rate_limit_retry` before handoff state), `test_t15`/`test_t17` (missing broker module), and
`test_t16` (missing route columns/table after explicit legacy fixture). Frozen acceptance commit:
`af1575df`; earlier
`ca2fdce7`/`6ff9718b` are superseded pre-gate oracle drafts.
