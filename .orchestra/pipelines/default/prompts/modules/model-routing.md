<model-routing>
## Model routing

Choose a model for the task, then check that the running registry, role, provider settings,
quota and canonical admission guards permit that exact route. A recommendation is not
permission to override a disabled route. The manifest owns defaults and effort; the user's
explicit orchestrator selection takes precedence. Native `sol` and native Terra
orchestrators use the same operating rules; do not change their model merely to match a worker.

### Project quota boundary (owner decision 10.11.2026)

Claude routes are Multicast-only: project path components multicode, multicast, obelisk,
polus or empire-front (plus ORCHESTRA_MULTICAST_PATH_TOKENS). Personal D&D projects
Claude-Code-Game-Master and dnd-game-master are NOT Multicast. Orchestra, Seedon,
katya-work, University, VPN-Service and other personal projects use Codex:
hubsol (xhigh), hubastra (high) for escalation, hubluna (high) for bounded collection.
An unavailable route is a blocker, never permission for automatic fallback.
For escalation after an errored turn use a clean handoff: original task, branch,
git status/diff stat and deterministic failure; do not replay failed-model reasoning.

### Task fit

| Route | Use when admitted | Boundary |
|---|---|---|
| `luna` | Explicit local implementation, focused tests and deterministic collection | Local worker admission requires a non-empty model_reason naming the local-processing constraint |
| native Astra | Hard coding, debugging, architecture or difficult reasoning | Native manual-only admission currently prevents automatic worker selection |
| `hubopus` | Hard coding, architecture, multi-step debugging and refactors (owner stack 09.11.2026) | Multicast projects only; xhigh effort from the manifest, never max |
| `hubsonnet` | Routine implementation, reading, scripts and bounded collection (owner stack 09.11.2026) | Multicast projects only; high effort from the manifest |
| `hubastra` | Complex debugging, science and reasoning escalated from Sol | Registered Codex Hub route, high effort; choose explicitly |
| `hubsol` | General Hub implementation; deep read-only audits and synthesis when assigned that scope | Ordinary admitted Hub route; read-only assignments must remain read-only |
| unregistered Hub Terra route | Deep read-only audit or synthesis when exposed and admitted | Not in the current registry; do not invent an alias or dispatch an unknown route |
| `hubcarbon` | Frontier reasoning, cross-domain architecture, UI/Vision review and deep synthesis (owner 12.11.2026) | Admitted Hub worker and specialist route; medium effort default (low for instant zero-CoT drafting) |
| `hubhydrogen` | Fast agentic implementation, 1M-context document/code review, tests and bounded scripting (owner 12.11.2026) | Admitted Hub worker route; high effort default (250–449 tok/s; low for fast scouting; replaces Flash) |
| `hubargon` | Independent second opinion, bounded audit, frontend/UI design or document comparison | Ordinary Hub workers and specialists; medium effort, role and task boundaries still apply |
| `free` / `openrouter-free` | Zero-cost cloud worker pool with automatic failover across top free coding/agentic models | Preferred zero-cost route for routine collection, parsing, drafting and bounded checks |
| `local` / `local-heretic` | Disabled by owner decision (09.11.2026) | Blocked in `app/models.py`; never spawn `local`, `heretic` or `local-heretic` workers |
| `hubluna` | Legacy Hub collection when explicitly admitted | Prefer `hubsol` or `free` for new workers |

These are task-fit preferences, not new runtime permissions. The current guards in
app/models.py admit ordinary Hub workers on `hubsol` (xhigh), `hubastra` (high),
`hubcarbon` (medium), `hubhydrogen` (high), `hubluna` (high) and `hubargon` (medium); `hubopus` and `hubsonnet` additionally require a Multicast scope. Native `luna` is only for explicitly local work with
a non-empty model_reason naming the local-processing constraint. Company data and KB
are authorized Hub inputs and do not by themselves require this native route. If broader routing is not activated,
use an admitted route fitting the assignment or report the precise blocker. Never rename
a role, change catalog flags or retry aliases to evade admission.

### Hub model & effort benchmark guide (03–04.11.2026)

Historical task-fit evidence, not admission policy: one run on four tasks; differences
below about 5/40 are noise. See `.orchestra/kb/hub-model-benchmarks.md` for sources,
full results and conflicting measurements. Keep current role defaults and explicit choices.

- `hubargon`: default `medium`. ARC-AGI-1 98.5% equals high; ARC-AGI-2 is
  87.1% versus 91.3% high and 42.1% low. The four-task Hub trial scored 34/40
  at high (medium was not directly scored). Owner's 04.11 operational report:
  ~4.3s TTFT versus ~41s high, 2.5–3x lower weekly quota burn and avoidance of
  observed 60s response-header timeouts; high uses ~3 hidden thinking tokens per
  visible token. Use `high` only for heavy math, physics or architecture. `low`
  scored 5/10 on the 1430-line document audit and confuses open and closed issues.
- `hubsol`: `xhigh` by owner decision 10.11.2026 for CTO and coding workers.
  Earlier benchmark settings are historical evidence, not current effort policy.
- `hubastra`: `high` for explicit escalation after Sol; use a clean handoff on failure.
- `hubsonnet`: `high` by the 09.11.2026 owner stack (source: owner model map 09.11.2026,
  Artificial Analysis: FrontierCode 2.0 26% versus 11% on medium); the earlier 35/40 reading
  score was measured in the separate Antigravity pool (source: `.orchestra/kb/hub-model-benchmarks.md`).
- `hubopus`: `xhigh` by the 09.11.2026 owner stack (source: owner model map 09.11.2026,
  Artificial Analysis: FrontierCode 2.0 44% versus 36% on high, Terminal-Bench 4.0 60%);
  `max` adds no Terminal-Bench gain at a far longer TTFT.
- `hubluna` / `luna`: fast mechanical collection, formatting and bounded checks.
  Open-ended multi-task scores were 7–11/40; require strict format/test verification.
  This recommendation does not change the manifest's high effort for admitted Luna workers.
- native Terra: `high` for orchestrators by owner choice; `low` for simple scripts
  and code (27/40, 1.5 min, fastest local run). Worker admission still applies.
- native Astra: `medium` for judge/advisor (32/40, about 6 min); `high` for hard
  science, math, economics and formulas. Historical research reports Terminal-Bench
  Science #1 at 68.1% and FrontierSWE v2 #1 at 65.5%; these were not medium-effort Hub tests.

### Simple subtasks and tool profiles

For bounded lookup, counting, extraction or formatting, prefer the `$0` worker pool
(`free` for cloud tasks; `local` / `local-heretic` / `heretic` is disabled and must not be used),
`hubsol` or `hubluna` when the exact route is admitted; do not spawn new `hubluna` or
`luna` workers unless an explicit legacy constraint requires them. Keep `hubopus`, `hubsol`
or `hubargon` for coding, architecture and debugging. The startup classifier is advisory: preserve the user's
explicit selection and always run the canonical admission and quota checks.
Role profiles show only relevant tool schemas; disabled tools and access policy remain
independent. Large tool previews provide an archive ID: read_tool_result_page reads
original ranges without rewriting previous results.

### Provider and capacity checks

- Select exact registered IDs or documented aliases, explicitly on spawn/model change.
- Never select a locally disabled provider, including claude when disabled. Do not infer
  availability from an old session, worker name, vendor announcement or catalog label.
- A selected Hub route's unavailability does not authorize another provider, native worker or API fallback.
  Preserve work and report the held route; do not clear recovery state or replay deliveries.
- Keep supported effort from the live manifest/catalog. Do not invent context size, prices,
  quota percentages, modalities or video/image/PDF support from vendor capability claims.
- Specialist audit is an assigned evidence-gathering task, not permission to restore a
  frozen model-review gate. Respect review freezes and project-specific checkpoints.
- New registry code on disk does not prove live activation. Follow the authorized idle
  restart/activation path; do not restart or migrate existing sessions and queues yourself.

### Project data and KB are authorized for Hub

Owner decision, 2026-11-04: transfer of any project tasks, data, internal company records,
documents, commercial offers, tenders and knowledge-base indexes (KB, including Seedon)
to `hubargon`, `hubsol`, `hubsonnet` and `hubluna` is fully authorized by the owner.
Do not block or postpone launching `hubargon` or any other admitted Hub worker because
its task, system prompt, source bundle or history contains a KB index or internal company
data. No separate data-transfer approval, safe-bundle review or local-only processing is
required for that material. `COMPANY-DATA.md` is ordinary authorized project input.

Set owned_dirs to the useful task scope; ordinary whole-worktree and persistent-project
contracts still apply. Credentials, tokens, passwords and credential files remain excluded.
An independently requested local task may use an admitted local `luna` worker with its
required model_reason; internal company data alone does not require local processing.

### Billing and workflow adapters

API-credit work requires explicit spending authorization for that task or stage.
A model preference, ordinary work approval or exhausted subscription is insufficient.
Use billing="api_credit" only for an authorized compatible task; no automatic paid fallback.
The current wf_run one-shot adapter does not dispatch Hub workers. Use ordinary admitted
Hub workers instead; its native defaults do not grant native subscription permission.
Routing never lifts deployment, deletion, privacy, spending or ownership boundaries.
</model-routing>
