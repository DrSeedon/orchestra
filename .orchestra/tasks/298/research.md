# #298 — тотальное детерминированное дерево выбора worker-модели

## Вопрос и границы

**Контекст:** Orchestra создаёт worker через MCP `spawn_worker` → HTTP `/api/sessions` →
`SessionManager`; выбор модели сейчас приходит от caller. Для Ox есть отдельный `harness`
runtime → OpenRouter → собственный tool loop.

**Изменение под проверкой:** определить единое тотальное дерево, в котором Sol остаётся
выше для особенно сложных задач, Ox Alpha становится полноценным worker-листом и
предпочитается Luna там, где это безопасно, а Luna остаётся листом закрытых
детерминированных задач.

**Baseline:** текущий prompt-only блок `model-routing` рекомендует Luna/Sol/Opus, но код
валидирует уже выбранную модель и не выбирает её [S1]. OpenRouter free-путь имеет счётчик
попыток и retry-классификацию, но не имеет атомарного budget broker или worker admission
для harness [S2].

**Измеримый исход:** для любого входа `(scope, sensitivity, openness, complexity, oracle,
context, tools, vision, availability, quota, canary)` ровно один лист выбирается первой
совпавшей строкой; каждый лист имеет проверяемый fallback или явный отказ.

Для Sol вводится отдельный trusted `sol_authorized` receipt. Это не boolean из prompt и не
признак approval родительской задачи: receipt обязан быть server-issued или проверяемой
записью control-plane с `task_id`, `scope`, `requester`, `granted_at`, `expires_at`,
`reason` и `receipt_id`; router проверяет подпись/существование, срок и соответствие task
scope. Отсутствующий, просроченный или чужой receipt означает `sol_authorized=false`.
Каждый Sol-лист сначала имеет отказ `REFUSE_SOL_AUTH`/request-decision, и только затем
может вернуть Sol. Никакой fallback этого отказа в Ox или Luna нет.

**Ограничения:** только уже смерженные #229, #236, #283, KB и текущий код; без live
model/provider calls, eval/review calls и без изменения production/config/prompt-кода.
Личность Ox/GLM не выводится.

## Гипотезы и фальсификаторы

1. **H1:** централизованный server-side router до spawn устранит ручную интуицию, потому
   что сейчас `spawn_worker` требует непустой `model`, а manager принимает caller-selected
   значение. Фальсификатор: существующий исполняемый seam уже классифицирует задачу и
   выбирает модель до создания сессии. Проверка текущего кода не нашла такого seam [S1].
2. **H2:** Ox можно поставить перед Luna для узкого класса безопасных задач, но не сделать
   безусловным default: #283 дал 6/6 полезных production-shaped задач, тогда как #236
   зафиксировал 6 пустых no-effort ответов и unsuffixed zero-price TOCTOU. Фальсификатор:
   повторяемый canary с guard и oracle проваливается или появляется платный/неизвестный
   расход. Такого текущего измерения в этой Phase 1 нет; существующие результаты остаются
   границей применимости [S3][S4].
3. **H3:** prompt-only дерево достаточно. Фальсификатор: все реальные callers обязаны
   проходить один server-side decision function. Текущий `spawn_worker` пересылает
   caller-selected model, а наблюдение #229 показало 21 Bash scan до первого spawn при
   доставленном prompt, поэтому H3 refuted [S1].

## Уровни доказательств

- **Tier 1, measurement:** frozen #236 matrix и production-shaped #283 artifacts [S3][S4].
- **Tier 2, primary source:** текущие Python/YAML/prompt owners [S5–S14].
- **Tier 2, project research:** #229 routing matrix и #236 free-only policy [S1][S2].

## Current-state table

| decision input | current source | executable/prompt-only | authoritative owner | gap |
|---|---|---|---|---|
| Caller must provide worker model | `app/mcp_stdio.py:893-926` | executable validation of non-empty value; selection is caller-side | `spawn_worker` MCP contract | No task classification, no default, no totality |
| HTTP omitted model | `app/routes/sessions.py:121-155` | executable default to `claude-sonnet-5[1m]` | Pydantic request model | Contradicts pipeline `defaults.model=opus`; not a worker policy |
| Canonical model/availability | `app/models.py:730-747`, `app/manager.py:643-652` | executable | model registry + manager | Validates selected model only; does not choose it |
| Role model/default | `pipelines/default/pipeline.yaml:4-20,36-123` | executable metadata consumed for role/effort; not spawn fallback | pipeline manifest | Role `model` and `defaults.model` look authoritative but are bypassed by explicit MCP model |
| Luna/Sol/Opus task class | `pipelines/default/prompts/modules/model-routing.md:3-20` | prompt-only | tracked prompt module | No trusted inputs for openness, complexity, oracle, sensitivity, or scope |
| Review model default | `app/mcp_stdio.py:798-852,2423-2445` | executable, review-only | `_CODEX_REVIEW_DEFAULT_MODEL` + resolver | Separate surface; must not silently become worker routing |
| Worker subscription quota | `app/quota_gate.py:238-269,501-534`; manager admission | executable | `app/quota_gate.py` | Harness returns `not_applicable`; no OpenRouter free budget admission |
| OpenRouter attempt count | `app/openrouter_counter.py:39-130` | executable observation | local SQLite counter | Counts local attempts, not whole account; no reserve/lease, unknown health currently tolerated by stream |
| OpenRouter retry class | `app/harness/llm.py:258-271,318-338` | executable | `_classify_rate_limit` + retry loop | Does not choose another worker model or close a shared pool |
| OpenRouter free proof | `app/models.py:120-145`; `app/model_catalog.py` behavior described in #236 | metadata/accounting, not admission | model registry/catalog | `ModelSpec` lacks full price/capability/privacy/free-proof fields; unsuffixed Ox has TOCTOU |
| Ox runtime wiring | `app/runtime_registry.py:324-339`, `app/backend_harness.py:175-245` | executable runtime | `harness` factory/backend | No task-level eligibility or explicit routed effort; `classify_effort()` is message heuristic |
| Ox effort | `app/backend_harness.py:50-79,238-247`; `app/harness/llm.py:153-168` | executable per-turn heuristic | `classify_effort` → request body | Not tied to server-selected task class; #283 confirms production path, not effort causality |
| Oracle/acceptance | task metadata and worker protocol; no trusted field in current TM [S2] | prompt/operational only | human/orchestrator | Router cannot prove that a task is safely automatable |
| Separate Sol authorization | `codex-debate` authorization text; no `sol_authorized` field in `spawn_worker`, session request, or manager | prompt-only; no trusted receipt | none | Parent-task approval is not an auxiliary Sol receipt; every Sol leaf could currently start without separate user approval |
| Sensitivity/secrets | `app/secret_mask.py` protects logs; no OpenRouter admission field [S2] | executable masking only; routing decision absent | no routing owner | Ox/NVIDIA retention warnings cannot be enforced at model selection |
| Context/tools/vision | `ModelSpec.context_length`; harness sends tools in `app/harness/llm.py:153-168`; no unified capability schema [S2] | partial executable metadata | model registry + harness | No complete task capability predicate; image/vision route is not proven |
| Spark strict contract | `pipelines/default/prompts/modules/model-routing.md:23` | prompt-only | no worker router | No executable ≤2-files/≤100K/text-only/oracle gate, no one-failure handoff state |
| Opus/Claude exception | `pipelines/default/prompts/modules/model-routing.md:5,23`; manifest role model/effort | prompt/manifest metadata; no task leaf | no worker router | Special creative/vision/ambiguity and Codex-exhaustion consequence fallback are not selected server-side |
| Fable/Terra disabled status | prompt says do not use; `app/models.py:39-145` still registers both selectable routes | prompt-only prohibition; registry accepts routes | model registry has selectable entries | Explicit disabled leaves/refusals are absent; caller can still request them |
| Fallback | OpenRouter sends exact `model`, no fallback list [S2] | executable no-cross-model provider fallback | none | Worker-level fallback is absent; each failure path can invent its own behavior |

**Conclusion from table:** only the server-side session admission path can make the tree
total and enforceable. Prompt text can explain the same tree but cannot prevent a caller from
passing `sol` for a trivial task or `ox-alpha` for a secret input.

## Proposed routing-tree table

The predicates below are evaluated in order. Inputs are normalized once by a server-owned
router; missing/invalid metadata is not coerced to a permissive value.

| predicate/order | sensitivity | task openness/complexity | oracle | context/tools/vision | selected model/runtime/effort | fallback | quota/price/canary gate | acceptance evidence |
|---|---|---|---|---|---|---|---|---|
| 0. Any required input missing/invalid (`scope`, sensitivity, openness, complexity, capability, oracle, route version, or requested-model policy) | unknown | unknown | unknown | unknown | **REFUSE_METADATA**, no runtime | request classification; no model call | fail closed; no quota spend | structured refusal names missing field |
| 1. Explicit request for disabled `fable`/Fable or `terra`/Terra route | any | any | any | any | **REFUSE_DISABLED_MODEL**, no runtime | request a supported model decision; never silently substitute | registry/policy refusal before admission | refusal names disabled model and policy revision |
| 2. `secret_or_private=true AND special_creative_or_vision=true` | secret/private | special creative/vision/exceptional ambiguity | human or structured acceptance | Claude capability receipt required; no OpenRouter | `claude-opus-5[1m]` / claude / high | visible refusal if Opus capability/readiness is absent | subscription admission; no OpenRouter price/quota path | private artifact + human acceptance; no third-party request |
| 3. `secret_or_private=true AND closed=true AND deterministic=true` | secret/private | closed/deterministic | immutable/pre-existing oracle | text/tools supported by Luna | `gpt-5.6-luna` / codex / high | visible refusal; no Ox/OpenRouter | existing Codex admission; blocked denied, unknown allowed [S5] | named test/command green; no third-party request |
| 4. `secret_or_private=true AND sol_class=true AND sol_authorized=false` | secret/private | open/complex/security/unknown scope | oracle or explicit human acceptance | subscription runtime only | **REFUSE_SOL_AUTH**, request separate user decision | after receipt, re-run tree; never Ox/Luna downgrade | receipt is checked before any Sol spawn; no model call | refusal contains task/scope and missing/invalid receipt, not secret payload |
| 5. `secret_or_private=true AND sol_class=true AND sol_authorized=true` | secret/private | open/complex/security/unknown scope | oracle or explicit human acceptance | proven Codex capabilities | `gpt-5.6-sol` / codex / xhigh | if Codex is exhausted and explicit consequence fallback is allowed, Opus/Claude; otherwise visible refusal | existing Sol admission; no OpenRouter fallback | full-cycle artifact + sources/measurements or human acceptance |
| 6. `public=true AND special_creative_or_vision_or_exceptional_ambiguity=true` | public | special/exceptional | human or structured acceptance | Claude capability receipt; vision must be Claude-canary proven | `claude-opus-5[1m]` / claude / high | visible refusal if Opus unavailable; do not use Ox for vision | subscription admission; no OpenRouter fallback | artifact + human/structured acceptance |
| 7. `codex_pool_exhausted=true AND opus_fallback_allowed=true` and no prior row matched | public/non-secret | consequence fallback for a route that needs Codex | existing oracle or human acceptance | Claude capability receipt | `claude-opus-5[1m]` / claude / high | visible refusal if Opus unavailable; no Ox/Luna substitution | explicit Codex-exhaustion receipt/status; Opus is a consequence leaf, not a silent downgrade | route receipt records exhausted pool and fallback reason |
| 8. `sol_class=true AND oracle_or_human_acceptance=false` | public/non-secret | special/high-risk/open/complex/unknown scope | no mechanical oracle and no explicit human acceptance | any | **REFUSE_ORACLE**, no autonomous worker | request immutable oracle or explicit human-acceptance mode; no Ox/Luna downgrade | no provider call until acceptance mode exists | refusal names missing oracle/acceptance descriptor |
| 9. `sol_class=true AND oracle_or_human_acceptance=true AND sol_authorized=false` | public/non-secret | special/high-risk/open/complex/unknown scope | oracle or explicit human acceptance | any | **REFUSE_SOL_AUTH**, request separate user decision | after valid receipt, re-run tree; no Ox/Luna downgrade | no Sol spawn, review, eval, or resume without receipt | refusal + request-decision event; 0 Sol spawn |
| 10. `sol_class=true AND oracle_or_human_acceptance=true AND sol_authorized=true` | public/non-secret | special/high-risk/open/complex/unknown scope | oracle or explicit human acceptance | proven Codex capabilities; no unproven vision | `gpt-5.6-sol` / codex / xhigh | only explicit Opus consequence fallback from row 7; otherwise visible refusal; never Ox/Luna | subscription Sol admission; current blocked-only rule [S5] | full-cycle artifact + sources/measurements or human acceptance |
| 11. `closed=true AND deterministic=true AND public=true AND ox_eligible=true` | public | closed/deterministic | immutable/pre-existing oracle | text + required tools; context ≤ canary limit; no vision | `stealth/ox-alpha` / harness / routed class effort (initial map: high edit/trace, medium audit) | `gpt-5.3-codex-spark` only if row 12 strict contract holds; else `gpt-5.6-luna` / codex / high | exact Ox zero-spend guard, broker lease, healthy counter, quota headroom, green class canary; unsuffixed Ox requires numeric-zero pre-POST prices and present/zero post-response cost [S2][S4] | command/fixture oracle green; artifact exists; report matches artifact |
| 12. `closed=true AND deterministic=true AND public=true AND spark_eligible=true` | public | closed/deterministic, narrow overflow | immutable/pre-existing oracle; every correctness-critical value explicit | text-only; ≤2 named files; total initial context ≤100K; no vision | `gpt-5.3-codex-spark` / codex / high | exactly one failure hands off to Luna (closed) or Sol (only with receipt); never retry Spark | Codex pool is binding, Spark quota available, independent oracle; no research/review/security/vision; current measured contract [S15] | oracle command green; one attempt outcome and handoff receipt |
| 13. `closed=true AND deterministic=true` and rows 11–12 did not match | public/non-secret | closed/deterministic | immutable/pre-existing oracle | text/tools supported by Luna; context within Luna limit | `gpt-5.6-luna` / codex / high | visible refusal; no automatic Sol escalation and no Ox after its gate failed | existing Codex admission; blocked denied, unknown allowed [S5] | named test/command green and committed artifact |
| 14. `public=true AND open_or_complex=true AND sol_class=false` | public | inconsistent open/complex classification | any | any | **REFUSE_METADATA**, classification is inconsistent | request corrected trusted task metadata; never choose Ox/Luna | fail closed; no provider call | refusal names classification inconsistency |
| 15. All remaining normalized public/non-secret finite ordinary cases | public/non-secret | finite ordinary | required oracle | text/tools supported | row 11 if its Ox gate is green; else row 13 Luna | if no Luna/readiness/budget, visible refusal | same gates as selected leaf | same as Ox/Luna leaf |
| 16. Selected runtime/model unavailable after admission | any | any | any | any | **REFUSE_NO_ROUTE**, preserving task state | reclassify explicitly before a new spawn; no post-side-effect class change | readiness failure is terminal for this selection | refusal includes model/runtime and readiness cause |

The effort values for Luna/Sol are current manifest values (`gpt-5.6-luna → high`,
`gpt-5.6-sol → xhigh`) [S6]. Ox effort is deliberately a routed policy value, not a claim
about identity: current harness computes effort from message text (`high` on complexity
keywords, `medium` for ordinary worker messages, `minimal` for trivial acknowledgements)
[S7]. Phase 2 must make the Ox class-to-effort map explicit and pass it as a server-owned
route value; leaving it as free-text classification would violate totality.

### Strict numbered decision tree (first-match semantics)

1. Validate route version, task scope, `sensitivity`, `openness`, `complexity`, required
   capabilities, oracle descriptor, and any explicit requested model. If invalid, return
   `REFUSE_METADATA`; if the request names Fable/Terra, return `REFUSE_DISABLED_MODEL`.
2. Validate the sensitive-input branch before any OpenRouter decision. Private special
   creative/vision/ambiguity goes to Claude Opus; private closed deterministic goes Luna.
3. For private Sol-class work, first inspect `sol_authorized`: absent/invalid/expired/
   mismatched receipt returns `REFUSE_SOL_AUTH` and a request-decision event; a valid receipt
   permits the Sol leaf. There is no Ox/Luna fallback for this refusal.
4. For public special creative/vision/exceptional ambiguity, choose Claude Opus. If its
   capability/readiness is unavailable, return refusal; do not guess Ox capability.
5. If Codex exhaustion is positively observed and an explicit Opus consequence fallback is
   allowed, choose Claude Opus. This is an explicit consequence leaf, not a silent downgrade.
6. For every remaining Sol-class predicate (special/high-risk/open/complex/unknown scope),
   inspect `sol_authorized` before model selection. Missing or invalid receipt is the first
   match `REFUSE_SOL_AUTH`; valid receipt selects Sol. No route may fall through to Ox/Luna.
7. For a public closed deterministic task, evaluate Spark's strict contract only when Codex
   is binding: text-only, ≤2 named files, ≤100K context, all decisions explicit, independent
   pre-existing oracle, no research/review/security/vision, and Spark quota available. One
   Spark failure hands off once; there is no Spark retry.
8. For a public closed deterministic task with oracle and text/tools capability, evaluate Ox:
   exact zero-spend proof, broker lease, healthy counter, quota headroom, context/canary and
   class canary must all pass. If they pass, choose Ox/harness with fixed route effort.
9. If Ox and Spark do not match, choose Luna/codex/high for closed deterministic work with
   an oracle. If Luna is unavailable, return refusal; do not silently escalate to Sol.
10. If no prior leaf matched but the task is public/open/complex while `sol_class=false`,
    return `REFUSE_METADATA` for inconsistent trusted classification; never infer a cheaper
    model from the inconsistency.
11. If no prior leaf matched for an ordinary finite public case, use Ox when its complete gate
    passes, otherwise Luna. This is the explicit ordinary catch-all.
12. If a selected runtime/model is unavailable after admission, return `REFUSE_NO_ROUTE` and
    preserve task state. A fallback may run only from the same row before side effects; never
    retry Ox as a paid OpenRouter route, retry Spark, or change task class silently.

### Fallback and escalation invariants

- `REFUSE_SOL_AUTH` is a terminal routing result plus a request-decision event. A separate
  user receipt causes a fresh router evaluation; parent-task approval, an old Sol session,
  prompt text, or a caller alias cannot satisfy it.
- An authorized Sol-class task that cannot start may use only the explicit Opus/Claude
  Codex-exhaustion consequence leaf when its exhaustion receipt and `opus_fallback_allowed`
  are true. Otherwise it returns `REFUSE_NO_ROUTE`. It never falls back to Ox or Luna.
- An Ox gate/provider failure falls back to Luna only for a closed deterministic task. For an
  open/complex task it escalates to Sol only when `sol_authorized` is valid; otherwise it
  returns `REFUSE_SOL_AUTH`. It never silently downgrades the task to Luna.
- A Spark attempt has one attempt only. Any failure hands off once to Luna for a closed leaf,
  or to authorized Sol for a Sol-class leaf; Spark is never retried.
- A Luna failure remains visible and terminal for a closed leaf unless an explicit new task
  decision reclassifies it as Sol. The router does not infer that reclassification from a
  failed test or from price.

### No-unmatched-case proof

After step 1, every normalized task has exactly one of disabled-request vs supported request,
private vs public, special Opus exception vs ordinary, Codex exhausted vs not, Sol-class vs
non-Sol, and closed deterministic vs open/ordinary. Within a Sol-class partition,
`sol_authorized` is a total three-state normalization (`valid`, `missing/invalid`, never
truthy prompt text); missing/invalid is always the first matching Sol outcome
`REFUSE_SOL_AUTH`. Spark and Ox are disjoint by their strict predicates; Luna is the explicit
closed catch-all; Opus leaves are disjoint by special-exception or exhaustion predicates;
Fable/Terra are a prior explicit refusal. Ordered precedence is therefore:
metadata/disabled refusal → private Opus/Luna/Sol-auth → public Opus → exhaustion Opus →
Sol-auth/refusal → Spark → Ox → Luna → public Sol-auth/refusal → ordinary catch-all →
no-route refusal. Every input returns exactly one model/refusal leaf; no branch relies on an
omitted model, prompt default, or provider guess.

## Failure matrix

| failure | observable trigger | mandatory response | allowed fallback | forbidden behavior / owner |
|---|---|---|---|---|
| Price TOCTOU | Ox metadata is unsuffixed, changes between metadata check and POST, or any declared price is unknown/positive | close Ox admission before POST; mark route unhealthy | Luna for closed deterministic; Sol for open/complex | Do not infer “free” from `TOKEN_PRICES=0`; final guard owner must be OpenRouter broker + `llm.py` [S2] |
| Missing `usage.cost` | response omits `usage.cost` | treat cost as unknown for Ox canary/accounting; stop Ox preferred route until policy receipt proves zero spend | Luna/Sol by task leaf | Do not convert missing to zero or reset cumulative cost; current backend preserves cumulative cost but cannot prove payment absence [S8] |
| Canary fail | immutable class canary misses artifact/oracle/quality threshold, empty response, or report/artifact mismatch | disable Ox for that task class and increment route revision | Luna closed; Sol open/complex | Do not widen eligibility or rewrite oracle after output [S3][S4] |
| Missing/invalid `sol_authorized` receipt | Sol-class predicate has no valid scope-matched, unexpired trusted receipt | return first-match `REFUSE_SOL_AUTH` and emit request-decision event | fresh user decision → rerun router; no Ox/Luna downgrade | Parent-task approval, prompt text, old Sol session, or model alias cannot authorize a new Sol spawn/review/eval |
| Sol spawn/readiness failure | valid Sol receipt exists but Codex model/runtime/admission is unavailable | use only explicit Opus consequence fallback when Codex exhaustion receipt + `opus_fallback_allowed` are true; otherwise `REFUSE_NO_ROUTE` | Opus/Claude consequence leaf only; never Ox/Luna | Do not silently downgrade a Sol-class task |
| Spark contract failure | any strict predicate fails, or the one Spark attempt fails/returns unusable artifact | mark Spark attempt failed and hand off once | Luna for closed; authorized Sol for Sol-class; no retry | No research/review/security/vision Spark use; no second Spark attempt [S15] |
| Upstream/provider 429 | 429 with no `X-RateLimit-*` headers | mark exact Ox route unhealthy; no paid fallback; retry only under broker policy | Luna/Sol by class; another exact `:free` route only after its own admission/canary | Do not call every 429 account exhaustion; current code distinguishes upstream vs platform [S8] |
| Platform/account 429 | 429 with `X-RateLimit-*` headers | close shared OpenRouter pool until returned reset; release leases safely | Luna/Sol by class | Do not continue retries from other contours or call paid OpenRouter [S2][S8] |
| Quota unknown | broker/counter unavailable, external usage unknown, stale reconciliation | fail closed for Ox/OpenRouter admission; expose unknown reason | Luna/Sol subscription route (current subscription unknown is allowed unless blocked) | Do not label local count as exact account remainder; local counter misses external calls [S2] |
| Quota exhausted | managed daily/rolling-minute lease unavailable or provider reset reached | refuse OpenRouter before POST | Luna closed; Sol open/complex | Do not “burn” requests or use provider random free router [S2] |
| Secret input | sensitivity scanner/task declaration says secret/private | never send to Ox/OpenRouter; record route refusal without payload | Luna closed; Sol complex | Log masking is not routing authorization; do not rely on prompt reminder |
| No oracle | no immutable command/acceptance evidence | pause autonomous Ox/Luna; request oracle | explicit human-accepted Sol research only | Do not call Ox because it is cheap or because model output sounds plausible |
| Model unavailable | registry disabled, runtime factory/readiness failure, or route disappears | refuse selected leaf and preserve task state | same-row Luna/Sol only before side effects; otherwise explicit reclassification | Do not let HTTP default Sonnet or pipeline `opus` decide implicitly [S1] |
| Disabled model requested | caller names Fable/Terra or another route disabled by policy | `REFUSE_DISABLED_MODEL` before model admission | request supported model decision; no silent substitution | Prompt prohibition alone is insufficient while registry still exposes the route |
| Task scope growth | new files/unknown external contract/complexity discovered after spawn | stop Ox/Luna work at safe boundary; reclassify before next turn | Sol for newly complex/open work | Do not continue Ox under stale eligibility or silently mutate acceptance scope |

## Seam inventory: exact owners and enforceability

| seam | current owner | current behavior | prompt-only vs enforceable | required future owner |
|---|---|---|---|---|
| Task classification | none; prompt modules and orchestrator judgment | model reads prose and chooses | prompt-only | `app/model_router.py`-style pure decision function, fed trusted task metadata |
| Worker model selection | caller `spawn_worker` → `CreateSessionRequest.model` | explicit value forwarded and resolved | enforceable validation, not selection | server router invoked before `create_session`; caller model becomes request/override subject to policy |
| Sol authorization receipt | no current owner; auxiliary authorization exists only in `codex-debate` prose | no trusted receipt is accepted or checked | prompt-only today | control-plane/user-approval owner issues and verifies scope-bound `sol_authorized` receipt before router |
| Runtime construction | `app/runtime_registry.py` | model spec runtime selects factory | enforceable | retain registry; router must consume capability snapshot before spawn |
| Effort | `pipeline.resolve_effort` for Codex; `HarnessBackend.classify_effort` for harness | model-based manifest for Codex, message heuristic for harness | partly enforceable, Ox currently heuristic | router emits effort; backend consumes exact value; fallback to heuristic only in legacy mode |
| Subscription admission | `app/quota_gate.py` + manager/session | blocked denied; unknown allowed; harness not applicable | enforceable | keep owner for subscription; add separate OpenRouter broker owner |
| OpenRouter account admission | `app/openrouter_counter.py` + `app/harness/llm.py` | local attempt observation before POST; retry classification | enforceable but incomplete | single atomic broker/lease before every POST, called by `llm.py` |
| Spark admission/handoff | prompt module only | no strict contract, one-failure handoff, or no-retry state machine | prompt-only today | server router + attempt state owner; Spark must be isolated from review/research/security/vision |
| Free/price proof | `app/models.py`, catalog metadata, #236 policy | zero prices are metadata; no final free-only guard | not enforceable today | exact route metadata + broker guard immediately before POST |
| Capability/sensitivity | partial `ModelSpec.context_length`, log masker | no trusted task sensitivity/capability predicate | prompt-only/partial | server task contract + model capability registry; fail closed |
| Oracle/acceptance | task descriptions, tests, orchestrator | no trusted field/command required at spawn | prompt/operational only | task metadata with immutable oracle descriptor and post-run evidence |
| Provider retry/fallback | `app/harness/llm.py` | retries same exact model before first byte; no cross-model list | enforceable | preserve exact-model retry; hand failure to router fallback, never provider-paid fallback |
| Opus/Claude exceptions and disabled routes | `pipelines/default/pipeline.yaml`, `app/models.py`, prompt module | Opus/Fable/Terra facts exist, but no task leaves/disabled refusal | partly manifest, mostly prompt-only | router owns Opus special/exhaustion leaves and explicit Fable/Terra refusal |
| Review routing | `app/mcp_stdio.py:2423-2445` + codex-debate skill | review-only default/resolver; distinct from workers | enforceable/prompt for review policy | keep separate; do not reuse review default as worker default |
| Prompt mirror | `pipelines/default/prompts/modules/model-routing.md` | recommendations and aliases | prompt-only | generate/derive display from server tree; never make it owner |

## Minimal alternatives and rejection reasons

1. **Keep prompt-only routing.** Rejected by #229: prompt was delivered, yet first spawn
   followed 21 Bash scans; no server check binds model to task class [S1].
2. **Use pipeline role/default model as implicit worker default.** Rejected: MCP rejects
   omitted model, HTTP omission defaults Sonnet, while manifest says Opus; three different
   defaults cannot form one tree [S1].
3. **Let caller choose any registered model, then quota-gate it.** Rejected: quota admission
   answers whether a chosen model may start, not whether it is suitable for sensitivity,
   oracle, openness, or complexity [S1][S5].
4. **Make Ox global default or fallback from every task.** Rejected by privacy/retention
   boundary, #236 unsuffixed TOCTOU, six empty no-effort historical responses, and narrow
   #283 canary evidence. Ox must be preferred only after class-specific gates [S2–S4].
5. **Use `openrouter/free` or price ranking as router.** Rejected: free router randomly
   chooses eligible models, and price metadata alone cannot prove zero-spend at POST [S2].
6. **Fallback chain Ox → Luna → Sol for every failure.** Rejected: complexity must be
   decided before a cheap model starts; a failed Ox closed task may be safely Luna, while an
   open/special task must go Sol. One universal chain violates sensitivity and scope rules.
7. **Route by runtime first (`harness`, `codex`, `claude`).** Rejected: runtime is a
   construction detail; it cannot decide whether the task is public, closed, oracle-backed,
   or special. The policy predicate must precede runtime construction [S1][S5].
8. **Use Spark as a general cheap fallback.** Rejected: the measured contract is deliberately
   narrow (Codex binding, text-only, ≤2 files, ≤100K, explicit decisions, independent oracle)
   and excludes research/review/security/vision; one failure hands off and Spark is never
   retried [S15].
9. **Leave Opus as prose-only fallback, or keep Fable/Terra as selectable safety valves.**
   Rejected: Opus special/vision/ambiguity and Codex-exhaustion consequence are distinct
   deterministic leaves; Fable/Terra are policy-disabled and must return explicit refusal,
   not silently replace a selected route [S9][S13].

## Measurable rollout and rollback criteria

These are proposed acceptance gates for Phase 2, not measurements performed in this Phase 1.

### Rollout stages

1. **Shadow stage:** server computes route but does not change the selected model. On a frozen
   corpus, compare router output with manually labeled class inputs. Pass requires 100% one
   leaf/refusal per case, 0 missing predicates, and 0 secret/private cases selecting Ox.
   The mandatory authorization oracle is a matrix test such as
   `uv run pytest -q tests/test_model_router.py -k sol_auth_without_receipt`: enumerate every
   Sol-class predicate with missing, expired, mismatched, and valid receipts; assert every
   missing/invalid case returns `REFUSE_SOL_AUTH`, emits request-decision state, and makes
   **0 Sol spawn/review/eval calls**. The same fixture must assert that invalid Sol auth never
   selects Ox or Luna.
2. **Ox canary stage:** only public, text/tool, immutable-oracle classes; no live production
   secrets. Use the #283 frozen shape and retain raw request/response/usage/artefact evidence.
   Required per class for two consecutive batches: closed edit/trace oracle = 1.0 in both
   repetitions; open audit ≥8/10 in both; 0 empty responses; 0 tool errors; 100% report ↔
   artifact agreement; 0 positive/unknown price fields; 0 nonzero `usage.cost`; 0 platform
   429; upstream 429 rate ≤5%.
3. **Preferred stage:** enable Ox only for classes passing the canary, with a route revision
   and broker lease on every attempt. Record Ox choice rate, fallback rate, request/task,
   p50/p95 latency, oracle pass rate, and scope-growth reclassification rate. No global
   Ox claim is made; eligibility is class-specific.
4. **Steady stage:** every route decision and fallback carries `route_revision`, selected
   model/runtime/effort, gate receipts, and acceptance result. Reconcile local counter with
   completed-day provider activity where available; expose external-usage uncertainty.

### Immediate rollback triggers

- any secret/private task sent to Ox/OpenRouter;
- any positive/unknown price field, missing zero-spend proof, nonzero `usage.cost`, or paid
  fallback;
- any platform 429, broker health failure, quota overshoot, or counter corruption;
- one empty Ox response or artifact/oracle mismatch in a production canary class;
- canary thresholds above missed in either of two consecutive batches;
- any scope-growth event continued under the old Ox route;
- any Sol spawn/review/eval observed without a scope-matched trusted `sol_authorized` receipt;
- registry/runtime readiness failure that is not surfaced as a visible refusal.

Rollback means disable the affected Ox class and increment route revision; closed work goes
to Luna, open/complex work to Sol, and in-flight task state is preserved. It does not delete
historical evidence or rewrite the oracle. Re-enable only after a new frozen canary and a
fresh zero-spend/capability receipt.

## Counter-evidence, risks, and confidence

- **Confirmed:** worker task-class routing is currently prompt-only; `spawn_worker` validates
  presence and manager validates/admit the passed model [S1][S5].
- **Confirmed:** harness is a registered runtime with OpenRouter POST/tool loop, local attempt
  counter, exact-model retry, and cumulative cost preservation [S2][S7][S8].
- **Confirmed:** #283's guarded remote continuation produced 6/6 useful tasks, 0 429, 0 tool
  errors, and 30 explicit zero costs plus one missing cost; #236's no-effort Ox matrix had
  6/6 empty turns. These are different experiments and do not prove a universal Ox default
  [S3][S4].
- **Confirmed:** current subscription quota rule allows unknown and denies only blocked;
  this cannot be copied to OpenRouter free budget, where unknown external usage can cause
  paid/over-limit risk [S5][S2].
- **Uncertain:** whether an unsuffixed Ox route can be made atomically zero-spend by provider
  configuration; #236 found no such proof. Until proven, the tree treats it as a guarded
  canary-only route.
- **Uncertain:** Ox vision/image capability and exact optimal effort; current harness accepts
  tool schemas and message bodies but no unified capability/vision policy exists. No identity
  inference is made.
- **Risk:** centralized routing is itself an admission/authorization surface. It must be
  fail-closed on metadata, quota, price, secret, and capability uncertainty, and preserve a
  visible refusal rather than silently selecting a different class.

## Review route and mechanical self-check

The canonical review skill classifies this as open architecture/high-risk (routing/admission,
security/secrets, externally consumed model/provider behavior), which would normally require a
Sol technical pass. The user explicitly prohibited Sol, Ox, Opus, and all eval/review model
calls, so no model review was launched. This is recorded as **Review: none — user explicitly
forbade model/eval/review calls**. Mechanical self-check completed against the required
artifact schema: current-state table has all five requested columns; routing tree has all nine
requested columns and mutually exclusive first-match predicates for Opus/Claude, Spark, Ox,
Luna, Sol, disabled Fable/Terra, and refusal leaves; failure matrix contains all eleven
requested failures plus Sol authorization/Spark/disabled-model cases; seam inventory
distinguishes prompt-only from enforceable; numbered tree includes an explicit no-unmatched
proof and Sol-auth precedence; rollout has numeric pass/rollback gates plus the 0-Sol-without-
receipt oracle.

## Sources

[S1] `docs/tasks/229/research.md` and `docs/kb/model-routing-selection.md` — current
`codex_review`/`spawn_worker`/manager/prompt routing matrix; prompt delivery observed before
spawn but no executable ordering/model selector.

[S2] `docs/tasks/236/research.md` and `docs/kb/openrouter-quotas.md` — free-only guard
boundary, candidate matrix, account-global request limits, local-counter uncertainty,
upstream/platform 429 distinction, broker policy, no paid fallback.

[S3] `docs/tasks/283/research.md` and `docs/kb/ox-alpha-harness-verdict.md` — production-shaped
Ox evidence, corrected 6/6 useful completion, 0 429/tool errors, cost observation, and
report/artifact caveats.

[S4] `docs/tasks/236/evidence/matrix/summary.json` plus preserved Ox rows — six no-effort
empty Ox turns and candidate failure boundary.

[S5] `app/quota_gate.py:238-269,501-534`, `app/manager.py:643-714` — current subscription
quota mapping, blocked-only refusal, and manager admission.

[S6] `pipelines/default/pipeline.yaml:15-20,36-123`, `app/pipeline.py:524-538` — role/model
effort map and exact-model resolution.

[S7] `app/runtime_registry.py:324-339`, `app/backend_harness.py:50-79,175-247` — harness
registration, OpenRouter backend, adaptive effort, MCP/tool loop setup.

[S8] `app/harness/llm.py:153-175,258-338`, `app/backend_harness.py:428-486`,
`app/openrouter_counter.py:39-130` — exact model POST, retry classification, attempt
counter, and missing-cost cumulative handling.

[S9] `app/models.py:39-145,730-784` — selectable model specs, Ox runtime/context/price
metadata, aliases, and agent-visible model catalog.

[S10] `app/routes/sessions.py:121-155,244-280` — HTTP omitted-model default and validation.

[S11] `app/mcp_stdio.py:798-852,893-926,2423-2445` — review-only resolver and required
caller-selected worker model.

[S12] `app/secret_mask.py` and #236 sensitivity/retention findings — log masking is not
provider-routing authorization.

[S13] `pipelines/default/prompts/modules/model-routing.md:3-20` — current prompt-only
Luna/Sol/Opus policy and its non-enforceable boundaries.

[S14] `docs/kb/codex-runtime.md` — current model/quota consequences and review/runtime
constraints used as project context.

[S15] `pipelines/default/prompts/modules/model-routing.md:23-26` and
`docs/kb/codex-runtime.md` — measured Spark strict contract, one-failure handoff/no retry,
and policy-disabled Terra/Fable/Opus boundaries.

## Confidence

- **CONFIRMED:** the owner placement: server-side pre-spawn admission/router is the only
  enforceable owner; prompt is a mirror; runtime/backend is a downstream constructor.
- **LIKELY:** Ox should be a preferred leaf for a narrow public/oracle-backed class after
  zero-spend and canary gates, supported by #283 but limited by #236 counter-evidence.
- **CONFIRMED:** Sol must precede Ox/Luna for special/high-risk/uncertain scope; Luna is the
  closed deterministic fallback, per user direction and existing manifest/policy.
- **CONFIRMED policy correction:** every Sol leaf now requires a trusted, scope-bound
  `sol_authorized` receipt; missing/invalid auth is `REFUSE_SOL_AUTH` with request-decision,
  and never Ox/Luna downgrade. Opus/Claude, Spark, and disabled Fable/Terra are explicit
  leaves/refusals rather than prose fallbacks.
- **UNCERTAIN:** exact Ox effort constants, vision capability, provider-side atomic zero-spend
  for the unsuffixed id, and global class coverage. Phase 2 must close these with code-owned
  metadata/tests or keep the affected leaves refused.
