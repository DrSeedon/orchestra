<model-routing>
## Model routing

**Owner decision, effective 2026-10-29 15:11 KRS:** local orchestrators use Codex;
all ordinary workers use the MultiCode hub, with the one protected-work exception under
"Keep protected work local". This replaces native-worker defaults,
native Sonnet/Opus fallback, the former Opus orchestrator route, and routing based
on old subscription-pool or Plus-versus-Pro ratios. The reason is to keep local
orchestration separate from worker capacity and use hub Claude for creative quality.
Routing policy belongs here, not in personal memory or project AGENTS files.

**Owner decision, 2026-10-31:** our native orchestrator roles default to GPT-6.1 Terra
with explicit `high` reasoning, to use the owner's chosen model for orchestration.
The pipeline manifest owns the exact model and effort; an explicit manual model choice
still takes precedence. This default does not migrate existing sessions or grant native
Terra worker admission. Apply a manifest containing a new model only after that host's
running Python registry recognizes it; an offline host must activate the registry with
the old manifest before receiving the new default.

### Choose a hub model

- Use `hubsol` as the general worker default, regardless of local quota headroom.
- Actively choose `hubsonnet` or `hubopus` for **any creative work**, including prose,
  visual direction, educational/explanatory video, images, and demanding synthesis.
  There is no "important creative work" or "known-heavy" threshold on hub Claude.
  The owner has lifted model-choice restrictions for creative work on the hub.
- Follow an owner's explicit hub-model choice. Use the pipeline's model effort;
  the creative permission does not authorize changing unrelated settings.
- Pass short aliases to `spawn_worker` and `change_worker_model`; the model manifest
  owns versioned ids. A spawn requires an explicit model. For `hubsonnet`, `hubopus`
  and `hubhaiku`, pass a non-empty `model_reason` describing the task. This remains
  required tool metadata under `hub_claude_reason_required`, not an importance test.

The existing hub configuration, credential, data and pool-admission guards remain
in force. A reason never bypasses admission. If the selected hub route is unavailable,
use another suitable permitted hub route or report the blocker. Do not fall back to
our own Claude subscription, native Codex workers (except the protected-work route
below), Grok, or Harness for ordinary work.
Do not wait for a native subscription to recover as a worker-routing strategy.

### Keep protected work local

Keep all protected personal, client and company data, credentials, secrets, and live
infrastructure local. Hub assignments receive only safe source bundles with sufficient
non-sensitive context. Treat the remote machine as foreign: automatic credential-file
exclusion does not establish that arbitrary source or conversation content is safe.

Use explicit `owned_dirs` to scope source bundles; repo-level files also accompany
worker copies and need the same safety check. Existing upload-size, sparse-checkout,
project and credential/data guards still apply. Empty `owned_dirs` is refused unless
the existing persistent-project contract permits a whole-worktree upload; that
permission never authorizes sending protected data. If a task cannot be safely
separated into a source-only assignment, report a blocker to the local orchestrator.
Local-only work is not permission to upload existing history or to start a native worker
other than the route below.

**Owner decision, 2026-10-31:** protected work that cannot safely go to the hub may be
delegated to a local native `luna` (GPT-6 Luna) worker, so the orchestrator talks to the
user and decides instead of repeating collection loops. The reason is to keep orchestrator
capacity for clarification and acceptance without moving protected data off the machine.
- Pass `model="luna"` and a non-empty `model_reason` naming the protection constraint that
  rules out the hub. The tool refuses without it; safe work still goes to the hub.
- This admits Luna only. It does not admit native Terra, Sol, Astra, Claude, Spark, Grok, Harness
  or API-credit work, and it is never an automatic fallback when the hub is unavailable or
  its quota is held; those cases are a blocker or a wait, not a reason to use Luna.
- Catalog flags, quota admission, role and ownership rules, and runtime readiness apply as
  for any worker. A Python guard change takes effect only after the owner's idle restart:
  if the tool still refuses `agent_workers_require_hub` for `luna` with a valid reason, the
  process predates the route. Report that blocker once; do not retry the spawn, do the work
  yourself, or pick another native route.
- Reuse a suitable idle local Luna worker through the existing lifecycle before spawning
  another; do not mass-spawn, retask or kill.

Preserve existing idle native threads and worktrees. Do not delete, migrate, upload,
or restart them merely to apply this routing decision. The default native orchestrator
model follows the pipeline; the owner may select another model manually. Agent tools do
not gain permission to start auxiliary native Terra, Astra, Sol, Claude, Spark, Grok or
Harness workers. Manual model selection and persisted-session recovery keep their existing
boundaries.

### Explicit API-credit tasks and workflows

API credits are opt-in per specifically authorized task, including approved evals.
Use `billing: "api_credit"` only for an explicitly authorized Claude task or stage;
a generic work approval, model preference, subscription failure or model_reason is
not API spending authorization. No automatic paid or native-subscription fallback.
Existing credit admission and refusal on exhausted/expired credits still apply.

Ordinary workflow work must follow the same hub route. The current `wf_run` one-shot
adapter does not support hub dispatch: use ordinary hub workers instead. Its native
model defaults do not authorize native subscription calls. Explicitly authorized
API-credit evals retain their existing path. Do not add a new hub workflow runtime
or change its public contract merely to work around this limitation.

This model-choice decision does not lift data protection, spending authorization,
restart, deletion, deployment, freeze, or other project boundaries.

### Historical quality evidence (not native-route permission)

V-667, V-670 and V-671 measured Sonnet 5.5 medium near Opus on tasks with an
understandable mechanism, with about half the output; those samples did not reliably
separate all model/effort combinations. Sonnet sometimes stopped at minimal checks:
state required checks explicitly. Opus did better on some concurrency/ownership bugs
(V-543) and cross-module restructuring (V-621, V-671). V-723 and V-731 found useful
Claude results on explanatory video and reinforced semantic viewing alongside tests.
These observations may inform hub Sonnet/Opus selection; they neither benchmark today's
hub deployment nor restore the former native routes. Historical price and pool-size
comparisons are not current routing rationale.
</model-routing>
