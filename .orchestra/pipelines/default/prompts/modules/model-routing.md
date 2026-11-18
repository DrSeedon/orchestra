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

### Local 6.2 effort policy (owner decision 2026-11-18)
- Local Sol62 orchestrator/reviewer: high, standard tier. Local coding roles
  implementer/worker/full-cycle/specialist: medium; explicit low/high remain available.
- Local Astra62: high. Never default to xhigh or fast.
- sol61/gpt61sol select GPT-6.1 Sol; astra6/gpt6astra select GPT-6 Astra.
- Local manual-only/provider/quota guards still apply; a new alias is not permission to bypass them.

### Hard routing invariants
- **Project boundary** (owner decision, 2026-11-10): Claude routes (`hubopus`, `hubsonnet`) are restricted to Multicast scopes; personal/internal projects (`orchestra`, `Seedon`, `katya-work`, `University`, `VPN-Service`, D&D repos) use Codex/Gemini/free routes.
- **Hub data authorization** (owner decision, 2026-11-04): all project code, internal company documents, commercial offers, tenders and KB indexes (including Seedon) are fully authorized on admitted Hub routes (`hubcarbon`, `hubhydrogen`, `hubargon`, `hubsol`, `hubsonnet`, `hubluna`). Never block Hub dispatch over internal docs or KB; exclude only credentials, tokens and `.env` secrets.
- **Fail closed, no silent fallback**: never select disabled providers (`local`/`heretic` are permanently disabled; respect `disabled_providers.json`), invent aliases, mutate role/task metadata to evade refusal, or fall back to paid API credits without explicit task `billing="api_credit"` approval.
</model-routing>
