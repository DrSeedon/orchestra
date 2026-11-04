<model-routing>
## Model routing

Choose a model for the task, then check that the running registry, role, provider settings,
quota and canonical admission guards permit that exact route. A recommendation is not
permission to override a disabled route. The manifest owns defaults and effort; the user's
explicit orchestrator selection takes precedence. Native Sol and Terra
orchestrators use the same operating rules; do not change their model merely to match a worker.

### Task fit

| Route | Use when admitted | Boundary |
|---|---|---|
| Native Luna | Default fast local implementation, focused tests and deterministic collection | Local worker admission must permit the task; currently protected local work only |
| Native Astra | Hard coding, debugging, architecture or difficult reasoning | Native manual-only admission currently prevents automatic worker selection |
| Hub Sol (`hubsol`) | General Hub implementation; deep read-only audits and synthesis when assigned that scope | Ordinary admitted Hub route; read-only assignments must remain read-only |
| Hub Terra | Deep read-only audit or synthesis when exposed and admitted | Not in the current registry; do not invent an alias or dispatch an unknown route |
| hub-gemini-4-argon | Independent second opinion, bounded audit, frontend/UI design or document comparison | Dedicated specialist role with bound task/scope; no general repository coding or spawning |

Resolve family names to exact versioned IDs using the live manifest/catalog.
These are task-fit preferences, not new runtime permissions. The current guards in
app/models.py admit ordinary Hub workers on Hub Sol (`hubsol`), Argon only as a
bound default-pipeline specialist, and native Luna only for protected local work with
a non-empty model_reason naming the constraint. If broader routing is not activated,
use an admitted route fitting the assignment or report the precise blocker. Never rename
a role, change catalog flags or retry aliases to evade admission.

### Provider and capacity checks

- Select exact registered IDs or documented aliases, explicitly on spawn/model change.
- Never select a locally disabled provider, including claude when disabled. Do not infer
  availability from an old session, worker name, vendor announcement or catalog label.
- Hub Sol unavailability does not authorize another provider, native worker or API fallback.
  Preserve work and report the held route; do not clear recovery state or replay deliveries.
- Keep supported effort from the live manifest/catalog. Do not invent context size, prices,
  quota percentages, modalities or video/image/PDF support from vendor capability claims.
- Specialist audit is an assigned evidence-gathering task, not permission to restore a
  frozen model-review gate. Respect review freezes and project-specific checkpoints.
- New registry code on disk does not prove live activation. Follow the authorized idle
  restart/activation path; do not restart or migrate existing sessions and queues yourself.

### Keep protected work local

Hub receives safe source bundles only. Keep personal/client/company protected data,
credentials and live infrastructure local. Credential-file exclusion alone does not make
source, history or conversation content safe to upload. Set owned_dirs for source-bundle
scope and check accompanying repository-level files. Whole-worktree upload requires the
existing persistent-project contract and still cannot include protected material.

If safe separation is impossible, use an admitted local Luna worker with model_reason
identifying why Hub cannot receive the task. Reuse a suitable idle native worker under
worker-lifecycle. This is not a fallback for Hub quota failure. If the running process
rejects the route, report once and preserve WIP; do not select another native model or
move protected artifacts to Hub. Reports cite protected artifact paths, not their contents.

### Billing and workflow adapters

API-credit work requires explicit spending authorization for that task or stage.
A model preference, ordinary work approval or exhausted subscription is insufficient.
Use billing="api_credit" only for an authorized compatible task; no automatic paid fallback.
The current wf_run one-shot adapter does not dispatch Hub workers. Use ordinary admitted
Hub workers instead; its native defaults do not grant native subscription permission.
Routing never lifts deployment, deletion, privacy, spending or ownership boundaries.
</model-routing>
