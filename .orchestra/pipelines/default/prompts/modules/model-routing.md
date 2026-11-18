<model-routing>
## Model & route passport

Select worker models by task fit, subject to live admission in `app/models.py`, provider enablement and `app/quota_gate.py`. Manifest defaults own effort unless overridden by the user.

### Available route aliases
| Alias | Typical fit when admitted | Admission & scope boundary |
|---|---|---|
| `hubsol` | Default coding, refactors, deep read-only audits and synthesis | Admitted Hub worker route across all projects |
| `hubastra` | Hard debugging, math/science and escalations after `hubsol` | Admitted Hub Codex route; pass clean handoff state (diff + deterministic error) |
| `hubcarbon` | Frontier cross-domain reasoning, architecture and UI/vision review | Admitted Hub worker & specialist route |
| `hubhydrogen` | High-speed agentic coding, large-context review, scripting and tests | Admitted Hub worker route |
| `hubargon` | UI/frontend design, independent second opinions and document comparison | Admitted Hub worker & `specialist` route |
| `hubopus` | Complex architecture, multi-file coding and deep debugging | **Multicast projects only** (`multicode`, `multicast`, `obelisk`, `polus`, `empire-front`) |
| `hubsonnet` | Routine coding, scripting and bounded collection | **Multicast projects only** |
| `free` | Zero-cost cloud pool for bounded extraction, parsing and checks | Admitted zero-cost cloud route (`openrouter` free pool) |
| `hubluna` | Legacy bounded Hub collection when explicitly requested | Prefer `hubsol` or `free` for new spawns |
| `sol` / `codex` (GPT-6.2 Sol), `astra` (GPT-6.2 Astra), `luna` | Native local Codex routes (`luna` requires explicit `model_reason` naming a local-only constraint) | Subject to local provider & manual/local admission guards |

### Gemini passport: local VPS / Antigravity (g1-pro)
These routes execute and retain files/history on the VPS; **no Hub workspace copy**.
Inference still goes to Google. They are appropriate for private/internal projects when
that Google processing is authorized. Current local Gemini windows: **1,000,000 tokens**.

| Route / variants | Use it for |
|---|---|
| `agy-hydrogen` = `antigravity/gemini-4-hydrogen-high` | Fast agentic workhorse: large document/spec/tender/log batches, codebase research, scripting and bounded local changes. Uses Gemini quota, not the Codex weekly pool. |
| `agy-hydrogen-med` = `antigravity/gemini-4-hydrogen-medium` | The same long-context work when the task and acceptance criteria are clear; a lighter default than high. |
| `agy-hydrogen-xhigh` = `antigravity/gemini-4-hydrogen-xhigh` | Exceptionally tangled multi-file analysis; use explicitly rather than by default. |
| `antigravity/gemini-4-hydrogen-low` | Straightforward extraction/read-only passes with a clear contract. |
| `agy-argon` = `antigravity/gemini-4-argon-medium` | Deep analysis, architecture, complex commercial/document editing, long-regulation comparison and an independent Google second opinion alongside Codex. |
| `agy-argon-high` = `antigravity/gemini-4-argon-high` | Harder versions of those reasoning/review tasks. |
| `antigravity/gemini-4-argon-low` | Bounded Argon tasks where the reasoning path is already specified. |
| `antigravity/gemini-pro-orchestrator-g1-pro` | The profile's dedicated long-context orchestrator/analysis route; select only the exact advertised ID/configuration. |
| `agy-flash` = `antigravity/gemini-3.8-flash-medium` | Light classification, field extraction and short summaries. Earlier small-task observations were about 3–10 seconds, not an SLA. |
| `agy-flash-high` = `antigravity/gemini-3.8-flash-high` | Slightly harder bounded extraction/synthesis while retaining the lightweight model. |
| `antigravity/gemini-3.8-flash-low` | The simplest structured extraction/classification tasks. |

### Our local Claude 5.5: rare escalation, not the Hub pool
These Antigravity routes spend **our VPS g1-pro Claude/GPT third bucket**, not the
Hub's daily Claude allowance or direct Anthropic API credits. All VPS projects may use them.

| Route / variants | Use it for |
|---|---|
| `agy-opus` = `antigravity/claude-opus-5-5-medium`; `agy-opus-high` = `antigravity/claude-opus-5-5-high` | Rare escalation for exceptionally hard nontrivial work: architectural dead ends after Sol, precise UI/UX and difficult texts/commercial proposals. |
| `agy-sonnet` = `antigravity/claude-sonnet-5-5-medium`; `agy-sonnet-high` = `antigravity/claude-sonnet-5-5-high` | Economical local Claude escalation for a bounded complex task when Opus is unnecessary. |
| `antigravity/claude-opus-5-5-low`, `antigravity/claude-sonnet-5-5-low` | Explicit lower-effort variants within the same scarce third bucket; not a mass-processing/routine default. |

**Preserve this small quota for rare difficult cases. Do not spend local Claude on routine
fixes, bulk tasks or ordinary extraction.** Prefer Sol/Gemini for those. Context availability
is the native advertised window; the Gemini 1M document guidance is not a universal Claude-input guarantee.

**Local execution rules for every orchestrator**
1. Use local `antigravity/*` workers for **one-shot, event-driven** tasks. Never attach cron,
   recurring timers, polling or 24/7 loops; kernel/runtime admission blocks scheduled wakes.
   The owner's messages, direct-child reports, own one-shot results and verified direct
   orchestrator messages keep their existing event-driven contract.
2. Launch at most **1–2 local workers together**. The shared profile has `Semaphore(3)`;
   leave room for the owner's interactive session. This does not guarantee vendor internal-call limits.
3. Hydrogen, Argon and Flash share the local **Gemini quota**. Flash does not create extra quota.
   Respect fresh 5h/weekly observations; unknown/stale observations are not invented capacity.
4. **Local Carbon is unavailable on this g1-pro VPS**: never spawn `agy-carbon`,
   `antigravity/gemini-4-carbon-*` or unsuffixed `antigravity/gemini-pro-orchestrator`.
   Legacy 3.1/3.5/3.6 (including `agy-pro`), old Claude/GPT-OSS routes and other unlisted IDs are not agent routes.
   Direct Anthropic and Hub-Claude keep their non-Multicast ban. Only the six exact local Antigravity Claude 5.5 variants above are exempt.
5. The 1M context window can accommodate very large (roughly 400k–900k-token) document work,
   subject to the remaining context and runtime limits. Read project files in bounded batches
   through native tools: the ACP JSON frame limit is **1 MiB**, not one million tokens per message.
   Adapter text/file transport is not a blanket guarantee of native image/audio/video input.

### Gemini passport: Hub routes
Only use these in projects explicitly admitted/bound in `hub-projects.json` and whose
policy allows Hub. A project-level Hub prohibition wins; native admission does not authorize Hub copy.

| Route | Use it for |
|---|---|
| `hubcarbon` = `hub-gemini-4-carbon` | Flagship Carbon through the Hub Ultra pool: cross-domain synthesis, difficult architecture, UI review and vision review when the actual media-input path is supported. Carbon is available here, not through this local g1-pro profile. |
| `hubhydrogen` = `hub-gemini-4-hydrogen` | Broker-hosted Hydrogen for fast coding/research/document work in permitted Hub projects. |
| `hubargon` = `hub-gemini-4-argon` | Broker-hosted Argon for analysis, document comparison and independent second opinions in permitted Hub projects. |

Hub capacity/subscription and workspace transfer are separate from this VPS's g1-pro quota.
Never silently fall back between local/Hub routes, copy forbidden projects or enable paid credits.

### Local 6.2 effort policy (owner decision 2026-11-18)
- Local Sol62 orchestrator/reviewer: high, standard tier. Local coding roles
  implementer/worker/full-cycle/specialist: medium; explicit low/high remain available.
- Local Astra62: high. Never default to xhigh or fast.
- sol61/gpt61sol select GPT-6.1 Sol; astra6/gpt6astra select GPT-6 Astra.
- Local manual-only/provider/quota guards still apply; a new alias is not permission to bypass them.

### Hard routing invariants
- **Project boundary**: Hub-Claude (`hubopus`, `hubsonnet`, `hub-claude-*`) and direct Anthropic (`claude-*`, runtime `claude`) remain Multicast-only. Owner exception 2026-11-18: our six local `antigravity/claude-{opus,sonnet}-5-5-{low,medium,high}` routes (`agy-opus*` / `agy-sonnet*`) may serve all VPS projects, sparingly and only for rare difficult work. They retain the same no-cron/timer/polling and shared `Semaphore(3)` rules.
- **Hub data authorization** (owner decision, 2026-11-04): all project code, internal company documents, commercial offers, tenders and KB indexes (including Seedon) are fully authorized on admitted Hub routes (`hubcarbon`, `hubhydrogen`, `hubargon`, `hubsol`, `hubsonnet`, `hubluna`). Never block Hub dispatch over internal docs or KB; exclude only credentials, tokens and `.env` secrets.
- **Fail closed, no silent fallback**: never select disabled providers (`local`/`heretic` are permanently disabled; respect `disabled_providers.json`), invent aliases, mutate role/task metadata to evade refusal, or fall back to paid API credits without explicit task `billing="api_credit"` approval.
</model-routing>
