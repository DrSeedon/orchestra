<model-routing>
## Model routing

Choose a model for the task, then check that the running registry, role, provider settings,
quota and canonical admission guards permit that exact route. A recommendation is not
permission to override a disabled route. The manifest owns defaults and effort; the user's
explicit orchestrator selection takes precedence. Native `sol` and native Terra
orchestrators use the same operating rules; do not change their model merely to match a worker.

### Task fit

| Route | Use when admitted | Boundary |
|---|---|---|
| `luna` | Explicit local implementation, focused tests and deterministic collection | Local worker admission requires a non-empty model_reason naming the local-processing constraint |
| native Astra | Hard coding, debugging, architecture or difficult reasoning | Native manual-only admission currently prevents automatic worker selection |
| `hubsol` | General Hub implementation; deep read-only audits and synthesis when assigned that scope | Ordinary admitted Hub route; read-only assignments must remain read-only |
| unregistered Hub Terra route | Deep read-only audit or synthesis when exposed and admitted | Not in the current registry; do not invent an alias or dispatch an unknown route |
| `hubargon` | Independent second opinion, bounded audit, frontend/UI design or document comparison | Ordinary Hub workers and specialists; high effort, role and task boundaries still apply |
| `hubsonnet` | Hub implementation, reading and analysis | Ordinary Hub workers; medium effort |
| `hubluna` | Fast Hub implementation, focused checks and deterministic collection | Ordinary Hub workers; high effort |

These are task-fit preferences, not new runtime permissions. The current guards in
app/models.py admit ordinary Hub workers on `hubsol`,
`hubargon` (high effort), `hubsonnet` and
`hubluna`. Native `luna` is only for explicitly local work with
a non-empty model_reason naming the local-processing constraint. Company data and KB
are authorized Hub inputs and do not by themselves require this native route. If broader routing is not activated,
use an admitted route fitting the assignment or report the precise blocker. Never rename
a role, change catalog flags or retry aliases to evade admission.

### Simple subtasks and tool profiles

For bounded lookup, counting, extraction or formatting, prefer `hubluna`, then
`hubsonnet`, when the exact route is admitted. Explicitly local tasks may use `luna`
only under the existing local-work rule. Keep `hubsol`, `sol` or `hubargon` for coding,
architecture and debugging. The startup classifier is advisory: preserve the user's
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
