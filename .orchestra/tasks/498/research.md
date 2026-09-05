# #498 — GPT-6 Astra: what it gives us and what adopting it costs

Date of cut: 2026-09-05, laptop contour (`/mnt/data/Projects/Python/orchestra`), Codex CLI
`codex-cli 0.153.2`, ChatGPT auth, `planType: "pro"`.

## Question

- **Context.** Orchestra routes GPT workers through the Codex CLI app-server on a ChatGPT
  subscription. `gpt-6-astra` already answers there but is absent from Orchestra's model registry.
- **Change under test.** Registering `gpt-6-astra` as a routable Orchestra model.
- **Baseline.** `gpt-5.6-sol` (today's complex-task Codex model) and `gpt-5.6-luna` (default).
- **Measurable outcome.** (1) Does Astra draw on the same `codex` quota bucket as Sol/Luna;
  (2) what one unit of *our* work costs on Astra vs Sol in subscription credits;
  (3) which advertised capabilities our stack can reach without new plumbing.

## Hypotheses and their falsifiers

| # | Hypothesis | What would prove it wrong |
|---|---|---|
| H1 | Astra shares the `codex` pool with Sol/Luna | a distinct limit id for Astra appears in `rateLimitsByLimitId`, as `codex_bengalfox` does for Spark |
| H2 | Astra has its own bucket, so adopting it adds capacity | Astra usage lands in `codex` while a known-separate model (Spark) provably lands elsewhere |
| H3 | Astra is cheaper per finished task than Sol (vendor's "substantially fewer output tokens") | on our task shape the credit bill is dominated by input, where Astra costs 2.5× — output savings cannot pay for it |
| H4 | Adopting Astra needs new runtime plumbing | the live catalog shows Astra structurally identical to Sol on every field our backend consumes |

Outcome: **H1 LIKELY** (shared pool — converging evidence, but no direct attribution; see §3).
**H2 REFUTED as far as the evidence goes** — no separate Astra meter is exposed, so adopting it
almost certainly adds no capacity; that last step is an inference, not a measurement.
**H3 REFUTED on our measured task shape** — Astra cost 2.23× more per finished ticket, not less;
it remains open for long agentic tasks, which I did not measure. **H4 REFUTED** — no new plumbing
is needed. Detail and evidence below.

## Method

- Every probe ran **outside this repository**: `--skip-git-repo-check`, cwd under `/tmp/astra498`,
  never in a worktree. No file in `app/` was touched.
- A/B ticket runs used `--ignore-user-config` so both models ran on identical minimal config.
  This matters: the machine's `~/.codex/config.toml` sets `service_tier = "fast"`, and the vendor
  states *"Fast mode applies a 2.5x multiplier to Astra's Standard rate"* — leaving it on would
  have inflated Astra's cost by 2.5× and measured our config, not the model.
- Rate-limit snapshots replicate Orchestra's own uncached upstream call
  (`app/routes/system.py:831` → `account/rateLimits/read` over `codex app-server`) and print the
  **raw** result, so every key of `rateLimitsByLimitId` is visible. `/api/usage` was deliberately
  not used as the primary instrument: it caches for `_USAGE_CACHE_TTL = 300` s
  (`app/routes/system.py:562`) and normalizes away limit ids.

---

## The table

### 1. Exact model id(s) and aliases the Codex CLI accepts

Authoritative source is `codex debug models`, which renders the CLI's raw model catalog without
spending a model call. Nine models, one Astra entry:

```
slug            levels                              default  tool_mode       ctx     maxctx   vis
gpt-6-astra     low,medium,high,xhigh,max,ultra     medium   code_mode_only  272000  872000   list
gpt-5.6-sol     low,medium,high,xhigh,max,ultra     low      code_mode_only  272000  872000   list
gpt-5.6-terra   low,medium,high,xhigh,max,ultra     medium   code_mode_only  272000  872000   list
gpt-5.6-luna    low,medium,high,xhigh,max           medium   code_mode_only  272000  872000   list
gpt-5.5         low,medium,high,xhigh               medium   None            272000  272000   list
gpt-5.4-mini    low,medium,high,xhigh               medium   None            272000  272000   list
gpt-5.3-codex-spark  low,medium,high,xhigh          high     None            128000  128000   list
gpt-reserve     low,medium,high,xhigh,max           medium   code_mode_only  272000  872000   hide
codex-auto-review    low,medium,high,xhigh,max      medium   code_mode_only  272000  872000   hide
```

**Use the exact slug `gpt-6-astra`.** The catalog carries no alias field — a model is its `slug` —
and every variant tested was rejected before any model work, including the case variant. This is
four probes, not an exhaustive enumeration of the alias space; the defensible claim is "the CLI
exposes no alias and rejected every form we tried", not "no alias can exist":

| probe | result |
|---|---|
| `-m astra` | `400 invalid_request_error: The 'astra' model is not supported when using Codex w…` |
| `-m gpt-6` | `400 invalid_request_error: The 'gpt-6' model is not supported when using Codex w…` |
| `-m gpt-6-astra-latest` | `400 invalid_request_error: The 'gpt-6-astra-latest' model is not supported when …` |
| `-m GPT-6-Astra` | `400 invalid_request_error: The 'GPT-6-Astra' model is not supported when using C…` |

Side fact: `gpt-5.4` is **gone** from the live catalog (vendor: *"The `gpt-5.4` and `gpt-5.4-mini`
models retire from Codex with ChatGPT sign-in on August 31, 2026"*), while our
`app/models.py:110-113` still ships a `gpt-5.4` ModelSpec and a `gpt5.4` alias. That entry is dead.

### 2. Which reasoning efforts work

One live probe per level, `codex exec --json -c model_reasoning_effort=<e> -m gpt-6-astra`:

| effort | rc | evidence |
|---|---|---|
| `none` | **1** | server: `Unsupported value: 'none' is not supported with the 'gpt-6-astra' model. Supported values are: 'low', 'medium', 'high', 'xhigh', and 'max'.` (`code: unsupported_value`, `param: reasoning.effort`, status 400) |
| `minimal` | **1** | same error text with `'minimal'` |
| `low` | 0 | `usage.output_tokens: 6` |
| `medium` | 0 | `usage.output_tokens: 6` |
| `high` | 0 | `usage.output_tokens: 6` |
| `xhigh` | 0 | `usage.output_tokens: 7` |
| `max` | 0 | `usage.output_tokens: 6` |
| `ultra` | 0 | `usage.output_tokens: 7`, input 20,117 vs 20,069 — the CLI adds subagent instructions |
| `bogus` | 1 | `[invalid_enum_value] Invalid value: 'bogus'. Supported values are: 'none', 'minimal', 'low', 'medium', 'high', 'xhigh', and 'max'.` |

Two things the error texts settle that the catalog alone does not:
- `none` really fails, and it fails **server-side per model**, not by CLI validation.
- `ultra` is **not** a server `reasoning.effort` value — the global enum in the `bogus` error has no
  `ultra`. It is a client-side mode the CLI translates into subagent behaviour.

Consequence for us: `CODEX_REASONING_EFFORTS` (`app/backend_codex.py:82`) contains `minimal`, which
Astra rejects, and lacks `ultra`, which the CLI accepts.

### 3. Same `codex.primary` pool, or a separate counter

**Same pool — LIKELY, on four converging lines of evidence, none of which is a direct attribution.**
Stated at that strength deliberately: the burn measurement failed (see (e)), so what follows shows
that no separate Astra meter is *exposed* and that our own code charges it to `codex`. A provider
could in principle meter Astra separately without publishing an id; nothing here excludes that,
and the practical conclusion — adopting Astra adds no capacity — is an inference from these four,
not an observation.

**(a) Live bucket structure.** Raw `account/rateLimits/read` returns exactly two limit ids, before
and after every Astra call made in this task:

```json
"codex":           {"limitId":"codex","limitName":null,"planType":"pro",
                    "primary":{"usedPercent":34,"windowDurationMins":10080}}
"codex_bengalfox": {"limitId":"codex_bengalfox","limitName":"GPT-5.3-Codex-Spark","planType":"pro",
                    "primary":{"usedPercent":0,"windowDurationMins":300},
                    "secondary":{"usedPercent":0,"windowDurationMins":10080}}
```

No Astra limit id exists at any point.

**(b) Positive control — buckets are per-model and the instrument detects it.** Spark is the one
model the vendor documents as separately metered: *"GPT-5.3-Codex-Spark is in research preview …
runs on specialized low-latency hardware, usage is governed by a separate usage limit that may
adjust based on demand."* Two Spark calls, snapshots taken seconds after each:

| snapshot | `codex` | `codex_bengalfox` 5h | 7d |
|---|---:|---:|---:|
| `B_spark_before` | 36 | 0 | 0 |
| after Spark call 1 | 36 | **4** | **2** |
| after Spark call 2 | 36 | **8** | **3** |

So a single call *can* move its own bucket by several points within seconds, and Spark's usage
does **not** touch `codex`. The instrument attributes correctly when the target bucket is quiet.

**(c) Vendor's own allowance table.** Astra is listed in the *same* per-plan allowance table as
Sol/Terra/Luna — one allowance, different consumption rates, in local messages per five-hour period:

| Model | Plus | Pro 5x | Pro 20x |
|---|---:|---:|---:|
| GPT-6 Astra | 5-45 | 25-225 | 100-900 |
| GPT-5.6 Sol | 10-100 | 50-500 | 200-2,000 |
| GPT-5.6 Terra | 25-200 | 125-1,000 | 500-4,000 |
| GPT-5.6 Luna | 250-2,000 | 1,250-10,000 | 5,000-40,000 |

Astra yields ~half the messages Sol does from the same allowance — the signature of a shared pool
with a higher per-message rate, not of a separate counter.

**(d) Our own code already decides it.** `quota_bucket_for_model` →
`app/quota_gate.py:290-291`: `return resolved, "codex_spark" if resolved == SPARK_MODEL else "codex"`.
Every codex-runtime model that is not Spark is bucket `codex` by construction.

**(e) What the direct burn could NOT prove, measured rather than assumed.** The owner asked for
this to be measured, so it was run — and the run shows the method cannot discriminate on this
account today. Timeline, all snapshots taken seconds apart from the raw endpoint:

| window | duration | my calls | tokens I burned | `codex` | rate |
|---|---:|---|---:|---|---:|
| `A_quiet` — deliberately idle | 5.3 min | **none** | 0 | 35 → **36** | 0.19 pp/min |
| `B` — 3 Spark calls | 1.2 min | 3 (Spark) | 29,117 out | 36 → 36 (flat) | — |
| `B2` — 1 Astra call | 2.7 min | 1 (Astra) | 4,043 out | 36 → 36 (flat) | — |
| `C` round 0 — 4 concurrent Astra | 4.5 min | 4 (Astra) | 21,726 out / 80,484 in | 36 → **37** | 0.22 pp/min |
| `D_quiet` — idle again, burn cancelled | 1.9 min | **none** | 0 | 37 → **38**, then flat | ≥0.5 pp/min |

The burn window's rate (0.22 pp/min) is indistinguishable from the idle window's (0.19 pp/min) —
and the idle window *after* the burn was cancelled moved a further +1 pp inside 53 seconds with
nothing of mine running at all, which is faster than anything my burn produced.
The cause is not subtle: other Orchestra workers are live on the same account with turns of 1–6M
input tokens (45 codex turns in the preceding three hours, `turn_usage`), and calibrated against our
own history one percentage point of the weekly pool costs on the order of 30–54K non-cached output
tokens or 15–26M input tokens (three monotone segments: 29,635 / 39,705 / 54,080 output per pp).
`usedPercent` is integer-resolution on top of that.

**I stopped the burn after round 0 instead of running the planned four.** More rounds could not
have improved the ratio — the background accumulates with wall-clock time exactly as my burn does,
so three more rounds would have spent another ~65K output tokens (roughly 1–2 pp of the weekly
pool) to reproduce the same non-result. **Attribution: UNCERTAIN by this method; the shared-pool
conclusion rests on (a)–(d) and is stated as LIKELY, not CONFIRMED.** Closing it properly would
need a window with the fleet idle, which is not worth buying for a question the vendor's rate card
already answers in the same direction.

### 4. Token cost per unit of work vs Sol, same prompt

One closed, ticket-shaped prompt, byte-identical for both models, `effort=high`, fresh copy of the
scratch repo per run, 3 runs each, interleaved A/B/A/B. The ticket: fix `humanize_ranges` so an
immutable pytest oracle goes green (4 failed / 4 passed at start). Verified by *this harness*
running pytest itself, not by the model's claim, and the oracle file was hashed before/after.

| model | run | input | cached | fresh input | output | reasoning | credits |
|---|---|---:|---:|---:|---:|---:|---:|
| gpt-6-astra | 0 | 83,755 | 73,984 | 9,771 | 325 | 0 | 4.699 |
| gpt-6-astra | 1 | 63,213 | 53,504 | 9,709 | 407 | 0 | 4.274 |
| gpt-6-astra | 2 | 83,795 | 73,984 | 9,811 | 341 | 0 | 4.729 |
| gpt-5.6-sol | 0 | 80,736 | 70,656 | 10,080 | 567 | 57 | 1.998 |
| gpt-5.6-sol | 1 | 80,821 | 70,784 | 10,037 | 650 | 131 | 2.037 |
| gpt-5.6-sol | 2 | 80,782 | 70,784 | 9,998 | 787 | 298 | 2.101 |

Credits computed from the vendor's published rate card, quoted verbatim from
`developers.openai.com/codex/pricing.md`, "Credits per 1M tokens":

| model | input | cached input | output | vs Astra |
|---|---:|---:|---:|---|
| GPT-6 Astra | 250 | 25 | 1,250 | — |
| GPT-5.6 Sol | 100 | 10 | 500 | Astra is exactly **2.5×** on all three |
| GPT-5.6 Terra | 50 | 5 | 300 | 5× input, 4.17× output |
| GPT-5.6 Luna | 5 | 0.5 | 30 | **50×** input, 41.7× output |
| GPT-5.3-Codex-Spark | *research preview* | | | no published rate — consistent with its separate limit |

The same 2.5× ratio appears on the API dollar card ($10/$1/$12.50/$50 against Sol's
$4/$0.40/$5/$20, Standard tier), so the two cards agree.

- **Astra used 46% fewer output tokens** (mean 358 vs 668) — the vendor's efficiency claim holds
  in direction on our data.
- **Astra still cost 2.23× Sol per finished ticket** (mean 4.567 vs 2.045 credits; ranges
  4.274–4.729 and 1.998–2.101, non-overlapping).
- The reason is the mix, and it is the load-bearing number: **output is only 9.8% of Astra's credit
  bill** (Sol 16.3%). Input — the role prompt plus the 203KB `AGENTS.md` — is 90%. A 46% saving on
  a tenth of the bill cannot pay for a 2.5× rate on the other nine tenths.

### 5. Full capability list from the official guide

Source: `https://developers.openai.com/api/docs/guides/latest-model.md` — "Using GPT-6 Astra",
fetched raw as markdown this session. New in Astra:

- **Async tool calling** — *"GPT-6 Astra can continue reasoning, call other tools, or answer
  independent parts of a request while your application runs a tool. Set `async: true` on a
  function or custom tool and return its result when ready using the original `call_id`."*
- **Mid-turn steering** — *"Send additional user instructions while GPT-6 Astra is working…
  Over a WebSocket connection, the Responses API preserves completed work and includes the update
  in a continuation."*
- **Change reasoning mid-conversation while preserving cache** — *"Add a `configuration_update`
  input item to increase reasoning effort for difficult work or reduce it for routine follow-ups
  without rewriting the original prompt prefix."*
- **Misalignment monitoring** — *"our systems asynchronously monitor for misalignment and trigger
  alerts when necessary."*
- **Limitations** — *"GPT-6 Astra does not support the `none` reasoning effort. Fast mode is
  unavailable for GPT-6 Astra with EU data residency."*

Carried over from GPT-5.6, quoted: *"computer use, Structured Outputs, streaming, Programmatic Tool
Calling, multi-agent orchestration, prompt caching, persisted reasoning, compaction, and pro mode."*

CLI-side, from the live catalog: `max` and `ultra` power levels, `input_modalities: ["text","image"]`,
`supports_search_tool: true`, `web_search_tool_type: "text_and_image"`, `multi_agent_version: "v2"`
with `multi_agent_reasoning_effort: "xhigh"`, and opt-in experimental context management
(*"Astra keeps notes across context windows and can search earlier messages and tool results from
the same task"*, `features.context_management.experimental_mode`).

### 6. Which of those our stack can actually use today

Decisive architectural fact: **Orchestra is a Codex CLI client, not a Responses API client.**
`AgentSession._make_backend` → `CodexBackend` spawns `codex app-server --stdio`
(`app/backend_codex.py`). Anything defined at the Responses API level is reachable only if the CLI
exposes it.

| capability | reachable today | file that would have to change |
|---|---|---|
| `max` reasoning effort | **yes** | none — `CODEX_REASONING_EFFORTS` (`app/backend_codex.py:82`) already contains `max`; set per role in `.orchestra/pipelines/default/pipeline.yaml:44` |
| Mid-turn steering | **yes, already used** | none — `app/backend_codex.py:1200` already issues `turn/steer` while a turn is in flight |
| Vision — model reading an image from its workspace | **yes** | none — `app/backend_codex.py:2145,2285` translate the model's emitted `imageView` event into a `ViewImage` tool display |
| Image **input** — us sending an image to the model | **no** | `app/backend_codex.py:1198` builds `user_input = [{"type": "text", "text": message}]`; the input path is text-only, so the catalog's `input_modalities: ["text","image"]` is unreachable from our side |
| Prompt caching, persisted reasoning, compaction | **yes** | none — native to the CLI thread; compaction policy in `app/backend_codex.py` (`_precompact_policy`) |
| Web search tool | **yes** | none — live workers already run with `-c web_search="live"` |
| `ultra` power level / subagents | **no — blocked by us** | `app/backend_codex.py:2633` hard-codes `-c features.multi_agent=false`; `CODEX_REASONING_EFFORTS:82` has no `ultra`; also collides with the rule that a full-cycle worker must not spawn children |
| Experimental context management | **not enabled for workers** | `_CARRIED_BASE_KEYS` (`app/backend_codex.py:371-374`) carries only `project_doc_max_bytes`, `model_context_window`, `model_auto_compact_token_limit` into managed homes, so the flag never reaches a worker's config; the CLI additionally reports it as `context_management  under development  false` (`raw/codex_features_list.txt`) |
| Fast tier (2× speed) | **no, and undesirable** | same `_CARRIED_BASE_KEYS` — `service_tier` is not carried, so workers run Standard while standalone CLI runs Fast; the vendor's *"Fast mode applies a 2.5x multiplier to Astra's Standard rate"* makes it a bad trade anyway |
| Async tool calling (`async: true`) | **not reachable** | Responses-API-level; our tools go through the CLI's MCP transport, not our own Responses requests |
| `configuration_update` mid-conversation effort change | **not reachable** | Responses-API-level; effort is fixed per session at connect (`app/pipeline.py:276-282`) |
| Structured Outputs / `--output-schema` | not used | CLI flag exists; no Orchestra caller |
| Misalignment monitoring | n/a — server-side | nothing to change |

### 7. Migration-breaking parameters

Verbatim from the vendor's migration quickstart:

- **Tool calling:** *"Use the Responses API. GPT-6 Astra supports Chat Completions, but tool calling
  requires Responses."*
- **Unsupported parameters:** *"Remove `temperature`, `top_p`, and `top_logprobs`. For Chat
  Completions, also remove `logprobs`. For Responses, remove `message.output_text.logprobs` from
  `include`."*
- **Reasoning effort:** *"If you currently use `none` or `minimal`, start with `low` and compare
  results. Otherwise, preserve your current effective reasoning effort."* And in "What's new":
  *"GPT-6 Astra does not support the `none` reasoning effort."*
- **Prompt caching:** *"When migrating from GPT-5.5 or earlier, replace `prompt_cache_retention`
  with `prompt_cache_options.ttl` set to `\"30m\"`."*
- **Fast mode:** *"GPT-6 Astra does not support `service_tier: \"fast\"` or
  `service_tier: \"priority\"` with EU data residency. Fast mode for GPT-6 Astra does not include a
  latency SLA."*

**None of these break us**, because we send no Responses/Chat-Completions request ourselves — the
CLI owns the request shape. `grep` for the named parameters in `app/` returns no request-building
site for the Codex path. The one item that touches us is `none`/`minimal`: our
`CODEX_REASONING_EFFORTS` still admits `minimal`, so a role manifest set to `minimal` would fail at
the provider rather than at our validation.

### 8. Reaction to `AGENTS.md` / skills, and our exposure

Vendor, verbatim: *"GPT-6 Astra is stronger at general instruction following than our previous
models, giving you greater control over its behavior. It can be more sensitive to instructions
contained in skills and other files, such as `AGENTS.md`. We **strongly recommend** auditing skills
and other files accessible to your model for instructions that could influence its behavior."*
And: *"unclear or conflicting guidance in a skill file may cause the model to pause and block work
early."*

Our measured exposure:

| quantity | value | source |
|---|---:|---|
| `project_doc_max_bytes` | **262,144** | `~/.codex/config.toml:7` |
| our `AGENTS.md` | **203,311 B** | `wc -c` (byte-identical mirror of `CLAUDE.md`) |
| headroom | 58,833 B (22.4%) | derived |
| delivered to the model | **in full, verbatim** | `codex debug prompt-input` on a scratch copy: prompt item 3 is 224,147 B and contains the entire file as a substring (`src in txt` → `True`), including its last 200 bytes |

So **nothing is truncated today** — but the whole 203KB of imperative, Claude-oriented operating
rules reaches Astra, which the vendor says follows such files more strongly than Sol does. The file
grew from 104,615 B (#240, 2026-08-23) to 203,311 B, i.e. it has roughly doubled and now sits 22%
under a ceiling it will reach on the current trajectory.

One conflict is already visible in the runtime's own text. Astra's CLI `base_instructions` say:
*"The user's instruction, whether implied from the task or explicitly stated in the session, must
take precedence over any guidelines provided in skills or external files"* and *"The user gets very
frustrated when you stop and ask for confirmation or permission, so make sure to explicitly explain
why you need the confirmation (for example, a SKILL.md, AGENTS.md, memory, or approval auto-review
block) and where it came from."* For an Orchestra worker the "user" is the orchestrator's task
message — so a task message can outrank `AGENTS.md`, and the approval gates we keep there are
exactly the kind of instruction Astra is told to push back on and attribute.

### 9. Vendor's guidance for autonomous agents vs our prompts

The recommendation, verbatim (guide, "Initiative and follow-through"):

> *"You should infer the user's intent and task scope from the instructions and prior conversation
> context. Your job is to bias towards action and carry the user's intended task to completion."*

> *"When the user's prompt indicates a request for action, such as 'can you…', 'I want to…',
> 'help me…' and similar expressions, treat these as instructions to do the work and take action.
> Do not stop at acknowledging capability… Do not settle for a partial or 'helpful enough' solution."*

> *"Before asking the user clarifying questions, you should complete the work that is already
> authorized from context and necessary to make the proposed action concrete and reviewable. The
> user should be approving a concrete, reviewable result."*

**Do our prompts satisfy it? Only in part — and the runtime already does most of the work for us.**

Two separate answers, because there are two prompt layers:

1. **The Codex CLI layer already satisfies it.** All three recommended blocks appear near-verbatim
   inside Astra's `base_instructions` shipped in the catalog (sections `# When to ask the user for
   permission` and `# Autonomy and persistence`) — e.g. *"Your job is to bias towards action and
   carry the user's intended task to completion"* and *"You MUST complete the work that is already
   authorized and necessary to make the proposed action concrete and reviewable before asking the
   user for permission as a final step."* Sol's `base_instructions` have no
   `# When to ask the user for permission` section at all and are 17,766 B against Astra's 21,269 B
   (UTF-8 bytes, matching the files saved in `raw/`; the character counts are 17,730 and 21,261).
   Nothing is required of us to obtain this behaviour.

2. **Our own pipeline prompts pull the other way, deliberately.** Grep over
   `.orchestra/pipelines/default/prompts/` for the three vendor themes:

| vendor theme | our prompts |
|---|---|
| bias to action / persist to completion | 1 partial match — `base.md:85` *"Every task you took on gets carried to an outcome — do not let it hang."* |
| treat a request as an instruction to act | **0 matches** |
| finish authorized work before asking | **0 matches** |
| counter-pressure (stop / ask / await approval) | **8 matches**, incl. `roles/full-cycle.md:185` *"NEVER proceed without approval after Phase 1 and 2 — STOP and wait"*, `modules/orchestration.md:47` *"ASK clarifying questions FIRST"*, `roles/worker.md:26` *"ask the orchestrator; do not guess"* |

This is not a defect to fix blindly: the gates encode the owner's standing rule that implementation
starts on his word. It is a compounding risk to be aware of — Astra is already the model most likely
to stop and ask, and our prompts add eight more reasons to stop. The vendor's own remedy happens to
match the owner's preference exactly ("approve a concrete, reviewable result" rather than "approve
a plan"), so the tension is resolvable, but it is a prompt decision, not a routing decision.

### 10. Behaviour difference on our kind of work

Same three interleaved runs as row 4, closed ticket, oracle immutable and independently verified:

| | gpt-6-astra | gpt-5.6-sol |
|---|---:|---:|
| ticket solved (verified by us) | **3/3** | **3/3** |
| oracle file untouched | **3/3** | **3/3** |
| stopped to ask instead of finishing | **0/3** | **0/3** |
| shell commands per run (mean) | **3.3** | 2.0 |
| assistant messages per run | 2 | 3 |
| final message length (mean chars) | 235 | 198 |
| wall time (mean) | 28.3 s | 26.7 s |
| output tokens (mean) | 358 | 668 |
| reasoning tokens reported | **0 in 3/3** | 57 / 131 / 298 |

Neither model asked a question; neither weakened the test. The visible differences are small and
in Astra's favour on verification effort (3.3 commands vs 2.0 — consistent with the vendor's
*"the model tends to be thorough in testing before considering a task complete"*) and against it on
nothing measurable here. **This ticket was too easy to separate them on capability** — both finished
in under 32 seconds — so it should be read as "Astra is not worse on our closed-ticket shape and
costs 2.23× more", not as a capability verdict.

---

## Counter-evidence and things that argue against the above

- **The external benchmark points the other way, on other work.** The prior in-repo report
  (`.orchestra/tasks/astra-routing-2026-09-04/report.md`) cites the Artificial Analysis Coding Agent
  Index: Astra `medium` ≈65 index at ≈1.1M tokens/task against Sol `medium` 62 at 5.8M tokens/task —
  a 5.3× token reduction that *would* make Astra cheaper per task despite the 2.5× rate. My
  measurement disagrees only because of scale: my ticket is ~80K input and a few hundred output
  tokens, where the fixed prompt overhead dominates and does not shrink. Both can be true. Which one
  applies depends on the ratio of model-generated tokens to fixed prompt overhead in the task.
- **A hidden-token objection to the 2.23×, raised and then killed.** Astra reported
  `reasoning_output_tokens: 0` in 3/3 ticket runs and 8/8 effort probes while Sol reported non-zero
  every time, which would mean either that Astra genuinely did not reason or that the CLI hides its
  reasoning tokens — and under the second reading the cost ratio would be worse than measured.
  Settled by a direct probe: on a hard reasoning task at the same `effort=high`, the same CLI
  returned `reasoning_output_tokens: 2588` with `output_tokens: 4043` over 157 s of wall time.
  **The reporting channel works, so the zeros are real** — Astra emitted no reasoning on the easy
  ticket while Sol spent 57–298 tokens on it. 2.23× is the actual number, not an underestimate.
- **My pool-attribution burn failed to attribute.** Stated plainly in row 3 rather than dressed up:
  background drift on the shared account was +1pp per 3 minutes with zero calls from me, which
  exceeds anything I could afford to burn. The shared-pool conclusion rests on bucket structure,
  the Spark positive control, the vendor allowance table and our own code — not on that burn.
- **One prior fact is now stale and is retracted here.** The 04.09 report states *"Свежий
  `~/.codex/models_cache.json`: 2026-09-04T12:09:37Z, девять моделей, Astra отсутствует"* and
  *"Production-конфигурация Orchestra не содержит `gpt-6-astra` ни в … pipeline effort map"*. Both
  changed within a day: the live catalog now lists Astra with `visibility: "list"`, and
  `.orchestra/pipelines/default/pipeline.yaml:44` already contains `gpt-6-astra: medium` (commit
  `7b4d03f3` "routing: Sol high, Astra medium"). Availability moved, so any "Astra is not reachable"
  statement older than 2026-09-05 must be re-checked before use.

## Confidence per finding

| finding | confidence | why |
|---|---|---|
| Only `gpt-6-astra` is accepted; no aliases; case-sensitive | **CONFIRMED** | 4 live probes + raw catalog (tier 1 measurement + tier 2 primary) |
| `none` and `minimal` rejected; `low…max` and `ultra` accepted | **CONFIRMED** | 9 live probes with verbatim server errors (tier 1) |
| No Astra-specific quota bucket is exposed, while Spark's is | **CONFIRMED** | raw `rateLimitsByLimitId` before and after every Astra call; Spark control moved its own bucket 0→11% while `codex` stayed flat (tier 1) |
| In Orchestra, Astra resolves to bucket `codex`, lane `sol` | **CONFIRMED** | `app/quota_gate.py:290-291,301-308` — our own code, independent of the provider |
| Astra draws on the *same upstream allowance* as Sol/Luna | **LIKELY** | vendor lists Astra in the same per-plan allowance table, and no separate bucket is exposed — but I never attributed a counter move to Astra, and a provider could meter it separately without exposing an id. Downgraded after review |
| "Adopting Astra adds no capacity" | **inference**, not measurement | follows from the row above; if that row is wrong, this one is too |
| Astra costs 2.23× Sol per closed ticket | **OBSERVED for this exact ticket shape** | 3+3 interleaved runs, non-overlapping ranges, vendor rate card. A sample mean on one small synthetic ticket, not a population cost (tier 1 + tier 2) |
| Output is ~10% of Astra's credit bill on our work | **CONFIRMED for this task shape** | direct computation from measured usage |
| Astra generalizes as cheaper on long agentic tasks | **UNCERTAIN** | not measured here; external single-harness benchmark only, opposite direction |
| Astra needs no new transport or runtime protocol — same rails as Sol | **CONFIRMED** | 24 catalog fields identical, diffed field-by-field. "Drop-in" only in that sense: the registration still needs a `CODEX_TOKEN_PRICES` row and an effort decision, listed under Affected files |
| `AGENTS.md` reaches Astra uncut at 203,311 B | **CONFIRMED** | `codex debug prompt-input`, whole-file substring match |
| Astra is more likely to stop and ask on our prompts | **UNCERTAIN** | vendor says so; our own ticket showed 0/3 stops, but the ticket was closed and easy |
| Astra's `reasoning_output_tokens: 0` on the ticket is real, not a reporting gap | **CONFIRMED** | control probe on a hard task returned 2,588 reasoning tokens through the same field (tier 1) |

## Affected files, if adoption is later approved

- `app/models.py:90-149` — one `ModelSpec(id="gpt-6-astra", runtime="codex", provider="openai",
  context_length=…)`; `ALIASES:159-198` — `"astra"`, `"gpt6astra"`.
- `app/backend_codex.py:65-76` — `CODEX_TOKEN_PRICES["gpt-6-astra"] =
  {"input": 10.0, "cached": 1.0, "write": 12.5, "output": 50.0}` (Standard card). Without this row
  `_codex_cost` raises and the turn is recorded **cost-unaccounted** — caught fail-soft at
  `app/backend_codex.py:2450` (`cost = 0.0`, `logger.error("Codex usage unaccounted: …")`), so it
  degrades silently into wrong dashboard numbers rather than crashing.
- `app/backend_codex.py:82` — decide `minimal` (rejected by Astra) and `ultra` (accepted by CLI).
- **No change needed** in `app/quota_gate.py`: `lane_for_model` sends any non-Spark, non-Luna codex
  model to lane `sol` (`quota_gate.py:301-308`), which is already the parabolic `CURVED_LANES` lane.
- `.orchestra/pipelines/default/pipeline.yaml:44` — already carries `gpt-6-astra: medium`.
- Prompt-side, if adopted: `.orchestra/pipelines/default/prompts/modules/model-routing.md` is the
  single owner of routing text.

## Risks and edge cases

- Registering Astra automatically makes it a legal `codex_review` model (the review tool accepts
  registered codex-runtime models whose bucket is `codex` and rejects only Spark) — reviewer
  routing would change without anyone editing routing text.
- Astra in lane `sol` shares the parabolic admission curve, so Astra and Sol workers compete for the
  same admission threshold — adding Astra adds no capacity, it splits existing capacity.
- The >272K input surcharge (2× input, 1.5× output for the whole request) is documented for the API;
  its application to subscription credits is not published. Our effective CLI window is far above
  272K (`max_context_window: 872000`), so a long thread can cross it silently.

---

## Verdict

### (a) Can Astra be added to our registry today, and what breaks if we do

**Yes, technically — it is a small, low-risk change, and part of it is already in the tree.**
Astra is reachable on our existing ChatGPT auth right now, and the live catalog shows it identical
to Sol on all 24 structural fields our backend consumes (`tool_mode: code_mode_only`,
`shell_type: unified_exec`, same 272K/872K context, same `multi_agent_version: v2`, same
`supported_in_api`). Nothing in our runtime plumbing has to be invented; `pipeline.yaml:44` already
has its effort.

What breaks if we add only the `ModelSpec` and forget the rest:

1. **Cost accounting goes silently wrong.** No `CODEX_TOKEN_PRICES` row → `_codex_cost` raises →
   caught → `cost = 0.0` and an error line in the log. Astra turns would show as free in the
   dashboard. This is the one that fails quietly and therefore matters most.
2. **`minimal` effort becomes a provider-side 400** for any role manifest that uses it, instead of
   failing our own validation.
3. **Reviewer routing changes by side effect** — Astra becomes an accepted `codex_review` model the
   moment it is registered.
4. **No new capacity — in our accounting for certain, upstream by inference.** It lands in bucket
   `codex`, lane `sol` (`app/quota_gate.py:290-291,301-308`) and competes with Sol under the same
   parabolic threshold; that part is our own code. Whether the *provider* also meters it in one
   pool is LIKELY rather than proven — see §3.

Nothing breaks in the request layer: every migration-breaking parameter the vendor lists
(`temperature`, `top_p`, `top_logprobs`, Responses-for-tools, `prompt_cache_retention`) belongs to
callers who build their own API requests. We do not; the CLI does.

**The flip side of that same fact, and it is the answer to "what does Astra actually give us":
no new capability reaches our stack.** Of the five things the guide lists as new, three
(async tool calling, mid-turn steering over WebSocket, `configuration_update`) live at the
Responses API level we never touch — and we already have steering through the CLI's `turn/steer`.
One (misalignment monitoring) is server-side and arrives whether we register the model or not. The
fifth is a limitation. The CLI-side extras — `ultra`/subagents and experimental context management —
are blocked by our own `features.multi_agent=false` and by `_CARRIED_BASE_KEYS`, both our decisions.
So adopting Astra buys **a different quality-per-token point on rails we already run**, not a new
capability. That is the honest frame for any decision about it.

### (b) Where it beats Sol, with the number

**On our measured task shape it does not beat Sol — it costs 2.23× more for the same result.**
Three interleaved runs each: 4.567 vs 2.045 credits per finished ticket, ranges non-overlapping,
both 3/3 green with the oracle untouched and neither stopping to ask. Astra did use **46% fewer
output tokens** (358 vs 668), exactly as advertised — but output is only **9.8%** of its credit
bill on our work. Our turns carry ~80K of input (role prompt + a 203KB `AGENTS.md`) against a few
hundred output tokens, and input is where Astra charges 2.5×.

The class where it could still win is the one I did not measure: long, multi-step agentic work where
model-generated tokens dominate fixed prompt overhead. The external benchmark in the prior report
(Astra ≈1.1M tokens/task vs Sol 5.8M at `medium`) points that way, and if that 5.3× token reduction
held on our work it would flip the 2.5× rate into a net win. **That is a hypothesis with a number
attached, not a result.**

Concrete implication for routing: Astra is not a Luna replacement (Luna is 50× cheaper per input
token) and not a general Sol replacement. The only defensible candidate class is the top of today's
Sol work — long end-to-end tasks with heavy tool use — and only after it is measured there.

### (c) What we do not know, and what it would cost to find out

| open question | why it is open | cost to close |
|---|---|---|
| Does Astra win on **long** agentic tasks, where its token efficiency can pay for the 2.5× rate? | my ticket was 28 s and input-dominated; the only evidence in the other direction is one external harness | the real experiment: 3+3 interleaved runs of a genuine multi-hour Orchestra task with a frozen oracle, measuring credits per accepted result. Roughly 6 full task runs — the single most valuable thing to buy next |
| ~~Are Astra's reasoning tokens billed but not reported?~~ | **closed during this task** — a hard-task probe returned 2,588 reasoning tokens, so the zeros on the ticket are genuine | — |
| Does Astra actually stop and ask more often **under our prompts**? | vendor says yes; our closed ticket showed 0/3, but a closed ticket cannot trigger it | one deliberately under-specified task, 3 runs per model, counting turns that end in a question. Cheap, and it directly tests the row-8/row-9 interaction |
| How many percentage points of the weekly pool does one Astra task actually cost? | integer counter plus +1pp/3min background from other live workers made attribution impossible today | either a quiet window with the fleet idle, or accept the credit-rate arithmetic as the answer. Not worth buying a fleet-idle window on its own |
| Does the >272K surcharge apply to subscription credits? | vendor publishes it for the API only | unknown; would need a controlled long-context run plus a counter reading — currently not measurable at integer resolution |
| Is `ultra`/subagents useful to us? | blocked by our own `features.multi_agent=false`, and it collides with the rule that workers must not spawn children | a design decision first, not a measurement |

## Review

Route: **one Luna completeness pass** (`codex_review`, `gpt-5.6-luna`), chosen by the decision gate
rule 5 — this is prose whose conclusions feed a spend decision, so mechanical checks alone were not
the final gate. Sol was not used: an additional Sol run needs explicit user authorization, which was
not given. One round; artifact: `.orchestra/tasks/498/review-research-luna.md`.

Verdict counted as completed — the reviewer quoted a verbatim line from `raw/quiet_after_burn.jsonl`
that appears nowhere in my request. **0 blocking, 4 suggestion, 3 question, 1 nit.** Its verdict:
*"Revise before using this document for routing or spend decisions."*

What I did with each, after checking against the code and the raw files:

| # | finding | outcome |
|---|---|---|
| 1 | quota conclusion should not be `CONFIRMED` — `quota_gate.py` is only our local mapping, and a provider could aggregate without exposing an id | **ACK.** Downgraded to LIKELY and split into what is measured (no Astra bucket exposed; our code charges it to `codex`) versus what is inferred (upstream single pool, "no added capacity"). §3, H1, confidence table, Verdict (a). |
| 2 | `n=3` on one tiny synthetic ticket is a sample mean, not a confirmed per-ticket cost | **ACK.** Relabelled `OBSERVED for this exact ticket shape`. Verdict (b) already carried the bounded wording and is unchanged. |
| 3 | "Image input / vision: yes" is not supported by the cited lines — those translate emitted `imageView` events, and the input path is text-only | **ACK — this was a real error.** Verified: `app/backend_codex.py:1198` builds `user_input = [{"type": "text", "text": message}]`. Split into two rows: model-side `ViewImage` reachable, image *input* from us **not** reachable. |
| 4 | `_CARRIED_BASE_KEYS` only proves the flag is not copied; the CLI status was not in the evidence | **ACK.** Reworded to "not enabled for workers" and preserved the live output as `raw/codex_features_list.txt`. |
| 5 | "structurally drop-in" is too strong given the differing fields and the missing price row | **PARTIAL.** The differing fields and the missing `CODEX_TOKEN_PRICES` row were already documented; the claim is now narrowed to "no new transport or runtime protocol". |
| 6 | the `AGENTS.md` measurement was not reproducible from the supplied artifacts | **ACK.** Added `raw/agents_md_delivery.json`: file bytes, sha256, cap, headroom, prompt-item sizes and the three substring checks. |
| 7 | four rejected aliases do not prove "no aliases" | **ACK.** Reworded to "the CLI exposes no alias and rejected every form tested", with the non-enumeration stated. |
| 8 | base-instruction sizes are characters, labelled as bytes | **ACK.** Corrected to 21,269 B / 17,766 B with the character counts kept alongside. |

No finding was rejected and none was recorded-and-ignored. One round only: the gate allows a second
round on prose solely if a verified *blocking* finding forced an artifact change, and there were no
blocking findings.

## Sources

Every URL below was fetched in this session; the raw copies are under `raw/`.

1. `https://developers.openai.com/api/docs/guides/latest-model.md` — "Using GPT-6 Astra": what's new,
   prompting best practices, migration quickstart. Saved as `raw/vendor_latest-model_guide.md`.
2. `https://developers.openai.com/codex/models` — model line-up, `codex -m gpt-6-astra`, power
   levels, GPT-5.4 retirement.
3. `https://developers.openai.com/codex/pricing.md` — per-plan allowance table, credits rate card,
   Spark's separate usage limit, Fast-mode 2.5× multiplier for Astra.
4. `https://developers.openai.com/api/docs/pricing.md` — Standard/Batch/Flex/Fast token prices.
5. `codex debug models` (CLI 0.153.2, ChatGPT auth) — raw catalog. Distilled to
   `raw/catalog_summary.json`; full `base_instructions` for Astra and Sol saved alongside.
6. `codex debug prompt-input` — proof that `AGENTS.md` reaches the model uncut.
7. `account/rateLimits/read` via `codex app-server` — raw bucket snapshots,
   `raw/ratelimits_baseline.json`.
8. `.orchestra/tasks/astra-routing-2026-09-04/report.md` — prior in-repo Astra economics/effort
   research (external benchmarks); two of its availability facts are retracted above.
9. Harness and ticket sources: `raw/run_ab.py`, `raw/run_pool.py`, `raw/ratelimits.py`,
   `raw/efforts.sh`, `raw/ticket/`.
