# #236 — useful, free-only OpenRouter capacity in Orchestra

Date of unstable provider facts and measurements: **2026-08-23 UTC**.

## Question

- **Context:** Orchestra already has an in-process OpenRouter agent harness, a dynamic
  model catalog, model visibility flags, an HTTP-attempt counter, and three advertised
  harness models. The user wants the daily free allowance to become useful capacity,
  not synthetic traffic.
- **Change under test:** make genuinely free OpenRouter routes a preferred pool for
  task classes they can complete, while making a paid OpenRouter request impossible and
  exposing an honest UTC-day budget.
- **Baseline:** `HarnessBackend` sends the selected model directly; `llm.py` records
  attempts, but the counter is display-only; all harness models are `not_applicable` in
  `quota_gate.py`; the catalog can register paid OpenRouter models and a user can enable
  them for agents.
- **Outcome:** zero paid requests; no silent paid fallback; account-global request
  accounting that distinguishes platform and upstream 429; useful completed tasks per
  HTTP attempt; deterministic task-class boundaries; UTC reset; no junk traffic when no
  useful backlog/eval/review exists.

## Hypotheses considered

1. **H1:** the current harness is already the correct execution substrate, and the
   missing pieces are free-only admission, capability-aware routing, and atomic budget
   reservation. **Falsifier:** the production call path bypasses `OpenRouterClient`, or
   the controlled tasks fail because the harness cannot carry tool rounds.
2. **H2:** the three advertised models remain the best free defaults. **Falsifier:** a
   live route is absent/rate-limited, or another current free route completes more of the
   frozen tasks per request.
3. **H3:** a local SQLite counter can safely expose the account's remaining daily
   allowance. **Falsifier:** the platform cap spans keys/machines while today's provider
   count is unavailable, so external calls can consume the same allowance invisibly.
4. **H4:** Ox's first-day result is stable enough to make it the unconditional default.
   **Falsifier:** its identity/benchmark evidence remains undisclosed or the frozen
   current run produces no useful artifacts.

## Mandatory fact checks

### A. Tier: 1,000 free requests/day and 20/min — CONFIRMED; UTC reset — LIKELY

The current OpenRouter limits source defines `FREE_MODEL_RATE_LIMIT_RPM = 20`,
`FREE_MODEL_HAS_CREDITS_RPD = 1000`, and a lifetime-purchase threshold of 10 credits
[1]. A live, sanitized account query on Contabo returned `total_credits=97`,
`total_usage=76.756018651`, and `is_free_tier=false` [E2]. The account is therefore
above the 10-credit threshold today. `GET /api/v1/key` still reports dollar usage 0 for
free calls, so it is not a request counter; this agrees with #368.

The free-limit table says “per day” but does **not** explicitly state that this free
request window resets at midnight UTC. The same primary source defines `usage_daily` as
the “current UTC day” [1], and `/activity` accepts completed UTC dates, so UTC is the
best-supported local boundary; it remains an inference about the free-request reset,
not a directly documented fact.

Confidence: limits/tier **CONFIRMED** — current provider source plus current account
measurement (evidence tiers 2 and 1); reset timezone **LIKELY** — provider-wide daily
accounting convention, not an explicit free-cap statement.

### B. Scope: global allowance plus model/provider capacity — CONFIRMED, with one boundary

OpenRouter states that extra API keys/accounts do not change rate limits because
capacity is governed globally, then immediately states that different models have
different rate limits [1]. The platform's 1,000/day and 20/min free allowance is not a
fresh allowance per Orchestra session, key, model, or provider. Model/provider capacity
adds a second limit: in the frozen run, GLM returned 22 upstream 429 events in 24 HTTP
attempts while Nemotron Ultra returned 0 in 21 and Nemotron Super 0 in 37 [E3].

The exact word “account” is not attached to the table row in the rendered documentation;
“globally” plus the current account credit threshold proves shared capacity across keys,
but does not prove how OpenRouter links deliberately separate user accounts. Orchestra
must treat all known keys/machines for this account as one pool.

Confidence: **CONFIRMED** for keys/models/providers used by this account; **UNCERTAIN**
only for provider anti-abuse identity linkage across separate user accounts.

### C. Models that are genuinely free and listed now — CONFIRMED point-in-time

`GET /api/v1/models?output_modalities=text` returned 422 rows. Twenty exact routes had a
`:free` suffix or were the explicitly free Ox/router routes, and every price field present
in those rows was numeric zero [E1]:

`stealth/ox-alpha`, `dots-studio/dots-3-note-preview:free`,
`liquid/lfm-2.5-2.6b:free`, `nvidia/nemotron-3.5-lightning:free`,
`thinkingmachines/inkling-small:free`, `poolside/laguna-s-2.1:free`,
`thinkingmachines/inkling:free`, `poolside/laguna-xs-2.1:free`,
`cohere/north-mini-code:free`, `z-ai/glm-5.2:free`,
`nvidia/nemotron-3.5-content-safety:free`,
`nvidia/nemotron-3-ultra-550b-a55b:free`,
`nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free`,
`google/gemma-4-26b-a4b-it:free`, `google/gemma-4-31b-it:free`,
`nvidia/nemotron-3-super-120b-a12b:free`, `openrouter/free`,
`nvidia/nemotron-3-nano-30b-a3b:free`,
`nvidia/nemotron-nano-12b-v2-vl:free`, and
`nvidia/nemotron-nano-9b-v2:free`.

Nineteen advertised `tools`; the content-safety route did not. The random
`openrouter/free` router is genuinely free but is not suitable for deterministic
first-class routing: it randomly chooses among eligible free models [2].

The complete 20-route screening snapshot is preserved in
`evidence/current-free-screening.md`. It exposes an important limitation of the frozen
candidate choice: current AA metadata ranks GLM, `thinkingmachines/inkling`, and
`thinkingmachines/inkling-small` above Ultra on agentic/coding indices. The frozen
matrix covered the three manifest incumbents plus Super and a cached Ling candidate; it
did **not** establish a best model across all nineteen tool-capable routes.

`inclusionai/ling-3.0-flash:free` appeared in a recently crawled provider page and has
an official model card, but it was absent from the live list and its exact model lookup
returned 404 before all six planned POSTs. It is **not currently available** under the
required fail-closed definition. Catalog presence is a point-in-time fact and must be
refreshed; it cannot become a permanent manifest claim.

Confidence: **CONFIRMED** at the captured API time (direct measurement); future
availability is deliberately **UNCERTAIN**.

### D. Ox identity and public comparable evidence — UNVERIFIABLE / UNKNOWN

OpenRouter says Ox is developed and operated by an anonymous third party and that
OpenRouter is not its developer, owner, or provider [3]. The current Models API row has
`benchmarks=null` [E1]. No official model card, disclosed identity, reproducible report,
or comparable independent leaderboard result was found. OpenRouter's 24-hour endpoint
availability (99.51%) is an operations metric, not a quality benchmark.

Ox still has direct Orchestra evidence: #366–#369 recorded four real tasks, 858 tool
calls with zero tool execution errors, and three report/artifact mismatches caught only
by acceptance [E4]. That is stronger evidence for this harness than a vendor claim, but
it does not identify the model and does not guarantee day-to-day behavior.

Confidence: identity **UNVERIFIABLE**; historical Orchestra capability **CONFIRMED** for
2026-08-22; current stability **REFUTED** as an unconditional assumption by the matrix.

### E. Tools, structured output, context, and the harness — CONFIRMED

OpenRouter's `supported_parameters` is the provider's current declaration of tool and
structured-output support [4]. The harness requires `tools`: `_build_body()` sends
`tools`, `tool_choice=auto`, streaming, and `parallel_tool_calls`; it can optionally send
`reasoning`, but it never sends `response_format`. Therefore structured-output support
is useful catalog metadata, not a current harness requirement. The harness replays
`reasoning_details` between tool rounds and uses the registry context limit [C1].

The exact production path is:

`Session._make_backend` → `build_backend(runtime)` → `_harness_factory` →
`HarnessBackend.connect` → `OpenRouterClient` → `AgentLoop._one_round` →
`OpenRouterClient.stream/_one_attempt` → `POST /chat/completions` [C2].

There is no second OpenRouter POST owner in `app/`; `backend_opencode.py` targets a local
daemon. This makes `llm.py` the necessary last-line free-only guard, while earlier spawn
and turn gates remain useful for actionable refusal.

Confidence: **CONFIRMED** — current source and an 88-attempt production-harness-shaped
measurement.

## Frozen candidate matrix (not a global winner table)

Price notation lists every current OpenRouter price type. “Absent” means the exact API
row did not declare the field; it does not mean a general future promise. The frozen
runner allowed a request only for an exact `:free` ID or a row whose every currently
declared price was numeric zero, and used no fallback-model list [E5].

| Exact model ID | Price, all token/unit types | Free proof | Current availability | Context / output | Tools / structured output | Public benchmark values (source/date) | Harness compatibility | Controlled local task score (two reps) | Latency | HTTP requests / completed useful task; tool rounds | Failure / 429 | Privacy if declared | Verdict and boundary |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `stealth/ox-alpha` | prompt 0; completion 0; request/image/web-search/internal-reasoning/cache-read/cache-write absent | no suffix; exact metadata price object was `{prompt:0, completion:0}` before each of 6 attempts | lookup and POST transport available; 0/6 429; OpenRouter 24h 99.51%, but all six completions produced no text, tool call, or usage | 1,048,576 / 131,072 | tools + tool_choice; `response_format` JSON mode; no `structured_outputs` | **UNKNOWN**: Models API `benchmarks=null`; identity anonymous [3][E1] | wire-compatible; historical #366–#369 strong, current no-effort controlled run empty | edit 2×0.333 baseline; trace 2×0; audit 2×0; 0/6 useful | median 5.551s | 6 / none; 0 successful usage rounds, 0 tool calls | 0 transport 429; 6 empty successes | provider retains prompts/completions, says not used for training [3] | **excluded from production free-only pool**: unsuffixed zero-price snapshot cannot prevent price TOCTOU; retain only as historical/eval evidence until provider-side atomic zero-spend is proven |
| `z-ai/glm-5.2:free` | prompt 0; completion 0; all other current fields absent | exact `:free` suffix + zero current fields | listed and lookup works; 22 upstream 429 / 24 attempts (91.67%); provider page claimed 99.71% 24h [5] | 256,000 / 256,000 | tools + tool_choice + `structured_outputs` + response_format | provider: SWE-bench Pro 62.1, Terminal Bench 2.1 81.0, MCP-Atlas 76.8 [6]; independent API: AA agentic 45.7, coding 68.8 [E1] | schema-compatible; two partial rounds, no completed task | edit 2×0.333 baseline; trace 2×0; audit 2×0; 0/6 useful | median 16.971s | 24 / none; 2 successful rounds, 5 tool calls | 22/24 upstream 429; 0 platform 429 | no candidate-specific policy declared in inspected page; treat as UNKNOWN | strong paper/model-card candidate, currently unusable; canary/eval only until upstream error rate clears |
| `nvidia/nemotron-3-ultra-550b-a55b:free` | prompt 0; completion 0; all other current fields absent | exact `:free` suffix + zero current fields | listed; exact lookup works; 0/21 429; provider page 92.48% 24h [7] | 1,000,000 / 65,536 | tools + tool_choice; no response_format/structured_outputs | provider: Terminal Bench 2.1 56.4, SWE-Bench Verified 70.7 [8]; independent API: AA agentic 27.5, coding 49.3 [E1] | fully exercised tool loop; one semantically correct trace lost 0.25 for extra constructor steps under frozen exact grader | edit 1.0/0.333; trace 0/0.75; audit 9/10 and 10/10; 3/6 useful | median 33.367s | 21 / 3 = **7.0**; 19 successful rounds, 19 tool calls | 0/21 429 | free NVIDIA endpoint logs for security/product improvement; no confidential/personal data [7] | preferred free candidate only for public read-only audit/evidence extraction with artifact acceptance; not qualified for closed coding |
| `nvidia/nemotron-3-super-120b-a12b:free` | prompt 0; completion 0; all other current fields absent | exact `:free` suffix + zero current fields | listed; exact lookup works; 0/37 429; provider page 98.28% 24h [9] | 262,144 / 262,144 | tools + tool_choice + `structured_outputs` | independent API: AA agentic 8.8, coding 37.7 [E1]; provider claims agentic/coding strength but the local matrix is the decision evidence | full tool loop, high request demand | edit 1.0/1.0; trace 0/0; audit 0/8; 3/6 useful | median 52.888s | 37 / 3 = **12.333**; 34 successful rounds, 31 tool calls | 0/37 429 | same NVIDIA free-endpoint logging warning [9] | not a general fallback; useful only for further closed-edit evals with an immutable oracle until trace reliability improves |
| `inclusionai/ling-3.0-flash:free` | live price row unavailable; cached page said free | suffix would be sufficient, but exact lookup 404 prevented POST | absent from live 422-row catalog; 6/6 guards failed before inference | official card 262,144; OpenRouter output unknown today | official model supports tool parser; OpenRouter route capability unavailable today | official HF: SWE-bench Pro 56.6, SWE-bench Multilingual 72.4 [10] | not tested: fail-closed guard correctly stopped at first link | N/A (baseline fixtures remain unmodified) | guard failure median 0.177s | 0 POST / 0 completed | 6 lookup 404; 0 POST | no live route policy to assess | unavailable; remove/ignore cached advertisement until exact live metadata returns |

### Measurement protocol and raw outcome

Commit `9e814761` froze tasks, graders, candidates, interleaving, thresholds, request
cap, and guard before the first inference call. The runner executed outside the live
repo/worktrees under `/var/tmp/orchestra-236-eval-9e814761` on Contabo. It imported the
production harness read-only, disabled arbitrary bash, confined file tools to each
fixture, and used an isolated SQLite database. Two repetitions were reversed/interleaved
by task/model. Acceptance thresholds were fixed before results: both closed tasks must
be 1.0 in both reps; open audit must be at least 8/10 in both [E5].

Raw totals: 30 planned runs, 88 guarded HTTP POST attempts, 22 upstream 429, zero
platform 429, every guard allowed only zero-priced/current `:free` evidence, and no
reported non-zero `usage.cost`. Some successful Ox responses omitted usage entirely, so
the free guard—not absent cost telemetry—is the proof against paid routing. Secret-form
scan passed remotely and after copy [E3].

The `closed_trace` grader intentionally remained exact after Ultra wrote a semantically
more complete path containing constructors. Changing it after seeing output would be
p-hacking; the raw artifact is preserved and the 0.75 score stands.

Evidence provenance is self-contained: `protocol-provenance.json` records the full
commit SHA/time, hashes the exact frozen runner/README copies, and shows the commit
preceded the first guard by 43.399 seconds. `catalog-selection-transcript-2026-08-23.json`
preserves a 422-row deterministic decision transcript, source SHA-256, every raw pricing
object, and the exact 20 selected rows [E6].

## What is already implemented

1. **First-class harness runtime — CONFIRMED.** `runtime_registry.py` registers
   `harness`; `Session._make_backend()` selects it from `ModelSpec.runtime`; the backend
   supports steering, persistent conversation files, tools/MCP, streaming, reasoning
   replay, and usage accumulation [C1][C2].
2. **Dynamic catalog and two availability levels — CONFIRMED.** `model_catalog.py`
   fetches/caches every OpenRouter model and `app/models.py` overlays dashboard/agent
   flags. Live sessions remain registered when flags turn off (#366).
3. **Local per-attempt counter and yesterday reconciliation — CONFIRMED.** `llm.py`
   records before each attempt; `openrouter_counter.py` stores UTC day/status; the usage
   route shows daily/minute counts; `/activity` reconciles completed days (#368).
4. **Bounded retry and 429 classification — CONFIRMED.** platform 429 is distinguished
   from upstream 429; retries and wait ceilings exist (#368).
5. **No automatic cross-model paid fallback today — CONFIRMED.** `_build_body()` sends
   one exact `model`; it does not send a `models` fallback list [C1]. Provider fallback
   can still choose another endpoint for that exact model.

## Missing or unsafe behavior in the current implementation

### Paid prevention is not enforced — CONFIRMED, high risk

- `refresh_catalog()` registers **all** OpenRouter models as `runtime="harness"`, paid
  and free. A user can enable a paid catalog row for agents.
- `HarnessBackend.connect()` and `OpenRouterClient._one_attempt()` do not validate a
  free suffix or live prices. `TOKEN_PRICES=0` is accounting metadata, not an admission
  guard.
- `normalize_catalog_model()` keeps only prompt/completion and discards request, image,
  web-search, internal-reasoning, cache prices, and pricing overrides. Its missing-field
  default is zero. The current “free” UI filter can therefore call a model free while a
  different unit is billable.
- `ModelSpec` carries no tool/structured/privacy/free-proof fields, so a catalog model
  enabled by mistake can lack the tools the harness requires.

### The counter observes but does not reserve — CONFIRMED

`quota_gate.py` intentionally returns `not_applicable` for every harness model. The
counter increments immediately before POST, but nothing atomically checks/reserves
daily or rolling-minute capacity first. Concurrent sessions can overshoot 20/min, and
the production SQLite count misses calls from any other process/machine. This matrix
alone consumed 88 account requests in an isolated counter, proving the production local
counter is not an account-total counter.

### Safe exact “remaining today” is unavailable — CONFIRMED

OpenRouter's successful responses have no remaining-request headers; `/key` exposes
dollar usage, not free request count; `/activity` exposes only completed UTC days
(#368). With account-global capacity and other callers, `1000 - local_count` is an
**upper bound**, not safe exact remaining. The API/UI must expose `local_remaining`,
`external_usage_unknown=true`, counter health, UTC reset, and yesterday's delta instead
of labeling the local upper bound “remaining”. A platform 429 is the only current-day
provider truth; it must stop the pool without paid fallback.

### There is no trusted task class or useful-work queue — CONFIRMED

The Task Manager has status, priority, assignee, and acceptance command, but no trusted
task class/model eligibility field [C3]. The model-routing prompt knows Luna/Sol/Opus,
not free candidates. An automatic end-of-day drain cannot mechanically distinguish a
real eligible backlog/eval/review from junk without new metadata. Prompt guidance alone
can choose useful work, but cannot prove it.

## Deterministic policy

### Code-enforced (harmful failure in either direction)

1. **Free-only request guard:** production inference permits **only exact IDs ending in
   `:free`**. Retain every current pricing field and override as defense-in-depth and
   reject stale/missing/malformed/positive/unknown metadata at enable, connect, and
   immediately before POST. Use exact IDs and forbid fallback-model lists. Unsuffixed
   zero-price previews such as Ox are excluded: a metadata GET followed by a POST is a
   time-of-check/time-of-use gap, and a `usage.cost` tripwire detects payment too late.
   Ox may enter only after a provider-side atomic zero-spend restriction is independently
   proven; no such mechanism is proven here.
2. **Capability/privacy guard:** require `tools` for harness agents; require the context
   needed by the task; refuse confidential/private inputs on Ox and NVIDIA free
   endpoints under their declared retention policies. `structured_outputs` is not a
   harness requirement until the body actually uses `response_format`.
3. **Single account admission broker:** all Orchestra contours call one fail-closed
   broker on Contabo before every HTTP attempt. The broker owns the only managed ledger;
   an atomic transaction checks health, UTC accounting day, a rolling 60-second window,
   and the 1,000/day managed ceiling, then grants a unique one-attempt lease and records
   it before POST. Broker unavailable → no OpenRouter call. Retries take a new lease.
   Platform 429 closes the account pool until the returned reset; upstream 429 updates
   the exact-model health score and may move only to another exact `:free`-suffixed
   eligible route.
   External non-broker clients remain explicitly unknown; they can make the provider
   wall arrive earlier, so no UI may call the managed remainder an exact account remainder.
4. **Honest exposure:** publish local used/reserved, local upper-bound remaining,
   minute headroom, UTC reset timestamp, counter health, external-usage uncertainty,
   last completed-day provider reconciliation, and per-model upstream failure rate.
5. **Trusted eligibility and candidate screen:** add server-owned task class,
   sensitivity, oracle command, and `max_http_requests`. At each catalog refresh select
   exact `:free`, `tools`, context >=128k, expiry >=48h; exclude random routers. Rank
   numeric AA agentic descending, then coding descending, then exact ID; missing scores
   follow scored routes. Run the same frozen canary on the top four before changing the
   preferred model. Today's untested Inkling routes mean no account-wide winner is proven.

6. **Deterministic end-of-day dispatcher:** one broker-elected leader ticks at 23:30 UTC.
   Until 23:55 it reserves 20 managed requests if any interactive harness turn is active,
   otherwise 5; at 23:55 the reserve becomes 0 only when no interactive turn is active.
   Eligible work must be public/non-confidential and carry an oracle plus an explicit
   `max_http_requests`. Order is real backlog (`priority`, then creation time, then task
   id), requested reviews (creation time/id), then frozen evals (id). The leader leases
   the whole declared task budget before spawn, runs one filler task at a time, and
   releases unused leases. Stop on: no eligible work; counter/broker unhealthy; platform
   429; next budget exceeds allocatable managed remainder; an active user instruction;
   or 23:58 UTC. No eligible row means no call.

### Prompt-guided (forgetting or over-applying is non-destructive under code guards)

1. **Among the frozen tested set only**, Nemotron Ultra is the provisional candidate for
   public read-only audit/evidence extraction with artifact acceptance. Luna remains the
   closed/simple default; Sol remains the especially-complex default. No free model
   passed the preregistered closed eligibility rule, and no account-wide free default is
   enabled until the complete top-four screen includes Inkling/Inkling Small.
2. Frozen-set canary order: Ultra → Super → GLM. Super stays in immutable-oracle evals;
   GLM stays last while upstream 429 is high. Ox is excluded from production free-only
   inference because it lacks `:free`; Ling is excluded until live metadata returns. Do
   not use `openrouter/free` for deterministic worker routing.
3. No paid OpenRouter fallback. If the proven free candidate is unavailable, return a
   visible refusal to the orchestrator; the orchestrator may deliberately choose Luna/
   Sol/Opus under the normal subscription policy, but OpenRouter itself never changes to
   a paid route.
4. Prompt text may explain the broker-owned end-of-day order and acceptance discipline,
   but it does not choose timing, reserve, concurrency, or stop conditions; those belong
   to the code algorithm above. “Burning” requests is never a fallback action.

## Counter-evidence and limitations

- Ox's 2026-08-22 real-work evidence is far broader than the tiny frozen matrix; the
  current empty results lower stability confidence but do not erase 858 successful tool
  calls. The matrix omitted the production `reasoning.effort` field to avoid relying on
  an absent internal-reasoning price; this may disadvantage a reasoning-first model.
- Ultra's open-audit result is only two repetitions on one synthetic fixture. It proves
  a narrow class, not general complex engineering. Its strict trace score was also
  sensitive to an equivalent extra-constructor representation.
- GLM's official and independent benchmark evidence is stronger than its local result;
  local failure was availability (upstream 429), not a clean capability loss.
- OpenRouter's web pages and API disagreed about Ling within the same day. Current API
  lookup won; cached pages are not admission evidence.
- A central Orchestra counter still cannot see unrelated external clients today. It can
  maximize safely by refusing paid fallbacks and stopping on platform 429, but cannot
  promise an exact pre-hit account remainder without provider support or exclusive use.
- The frozen candidate set omitted two current high-AA routes, Inkling and Inkling Small.
  The complete screen closes the catalog-accounting gap but not their empirical score;
  the implementation gate must run them before claiming a global preferred free model.

## Affected files and ownership risks for Phase 2

- `app/harness/llm.py`: final per-attempt guard, atomic reservation, cost tripwire, no
  platform retry.
- `app/backend_harness.py`: connect/task capability and sensitivity checks; surface
  budget refusal.
- `app/models.py`, `app/model_catalog.py`: full price/capability/free-proof metadata and
  free aliases. `app/model_catalog.py` is required but is outside this worker's current
  owned directories.
- `app/openrouter_counter.py`, possibly `app/db.py`: atomic reservation/account-status
  API. Both are outside current ownership.
- `app/quota_gate.py`, `app/routes/system.py`, `app/static/js/usage.js`: early admission
  and honest budget/UI exposure.
- `pipelines/default/prompts/modules/model-routing.md`: narrow preferred class and
  fallback rules.
- A deterministic end-of-day backlog drain would also require `app/tm.py` and scheduling
  consumers, outside current ownership and larger than a prompt edit. Phase 2 must either
  receive expanded territory or explicitly defer this automation while keeping prompt
  guidance.

## Review status

Targeted Sol round 1: **NEEDS WORK, 8 blocking**. All eight were checked and accepted:
unsuffixed TOCTOU; single-account broker; incomplete candidate screen; frozen provenance;
full catalog selection evidence; unproven UTC reset qualifier; call-path proof; and
deterministic end-of-day policy. The artifact and evidence were changed accordingly;
the Sol follow-up timed out without an agent-message/verdict and is recorded as a failed
attempt, not an approval. Under the user's corrected model policy, no further Sol call is
authorized. The permitted Luna closure audit verified all eight as **FIXED** and returned
**APPROVED** with evidence; its sole wording suggestion (`suffix-free` ambiguity) was
applied without another review round.

## Evidence artifacts

- **E1:** `docs/tasks/236/evidence/free-model-metadata-2026-08-23.json` — sanitized
  current 20-route free catalog subset, complete pricing objects, capabilities,
  contexts, expiry, and public benchmark metadata.
- **E2:** `docs/tasks/236/evidence/matrix/account-sanitized.json` — current account tier
  fields only; no label, key, or authorization header.
- **E3:** `docs/tasks/236/evidence/matrix/summary.json`, `guard.json`, `run.log`, and 30
  per-run JSON files — sanitized events, artifacts, graders, request/429/latency/load.
- **E4:** `docs/kb/ox-alpha-harness-verdict.md` and task #366–#369 artifacts.
- **E5:** `docs/tasks/236/eval/README.md` and `run_matrix.py`, frozen in `9e814761`
  before inference.
- **E6:** `docs/tasks/236/evidence/protocol-provenance.json`, frozen runner/README
  copies, `catalog-selection-transcript-2026-08-23.json`,
  `current-free-screening.md`, and `production-call-path.txt`.

## Sources

1. [OpenRouter limits source](https://openrouter.ai/docs/api-reference/limits.md) —
   primary provider source, fetched 2026-08-23; relevant raw lines preserved in
   `evidence/openrouter-limits-source-2026-08-23.txt`.
2. [OpenRouter Free Models Router](https://openrouter.ai/docs/guides/routing/routers/free-router)
   — primary provider documentation; random selection and capability filtering.
3. [OpenRouter Ox Alpha page](https://openrouter.ai/stealth/ox-alpha) — primary route
   metadata/privacy declaration, fetched 2026-08-23.
4. [OpenRouter Models API schema](https://openrouter.ai/docs/guides/overview/models) —
   primary provider documentation for pricing and supported parameters.
5. [OpenRouter GLM 5.2 free page](https://openrouter.ai/z-ai/glm-5.2%3Afree) — current
   route/context/availability declaration.
6. [Official GLM-5.2 model card](https://huggingface.co/zai-org/GLM-5.2) — provider
   benchmark claims, opened 2026-08-23.
7. [OpenRouter Nemotron 3 Ultra free page](https://openrouter.ai/nvidia/nemotron-3-ultra-550b-a55b%3Afree)
   — current route/context/tool/privacy/availability declaration.
8. [Official NVIDIA Nemotron 3 Ultra model card](https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B-BF16)
   — provider benchmark claims, opened 2026-08-23.
9. [OpenRouter Nemotron 3 Super free page](https://openrouter.ai/nvidia/nemotron-3-super-120b-a12b%3Afree)
   — current route/context/tool/privacy/availability declaration.
10. [Official Ling 3.0 Flash model card](https://huggingface.co/inclusionAI/Ling-3.0-flash)
    — provider/repository benchmark evidence, opened 2026-08-23.
11. [OpenRouter tool calling](https://openrouter.ai/docs/guides/features/tool-calling)
    and [structured outputs](https://openrouter.ai/docs/guides/features/structured-outputs)
    — primary provider feature contracts.
12. [OpenRouter API-key limits](https://openrouter.ai/docs/api/api-reference/api-keys/create-keys)
    — primary provider confirmation that daily accounting resets use midnight UTC;
    used only as supporting platform convention, not as direct proof of the free-cap reset.

### Code sources

- **C1:** `app/harness/llm.py:132-310`, `app/harness/loop.py:70-258`,
  `app/harness/prompts.py:1-46`.
- **C2:** `app/session.py:795-837`, `app/runtime_registry.py:324-403`,
  `app/backend_harness.py:165-214`; mechanically preserved in
  `evidence/production-call-path.txt`, whose repo-wide scan finds the sole direct
  OpenRouter `/chat/completions` POST in `app/harness/llm.py`.
- **C3:** `app/tm.py:19,221-269,490-503` and
  `pipelines/default/prompts/modules/model-routing.md`.
- Existing work: `docs/tasks/366/{research,plan,report}.md`,
  `docs/tasks/367/{research,plan,report}.md`,
  `docs/tasks/368/{research,plan,report}.md`, and `docs/tasks/369/*`.
