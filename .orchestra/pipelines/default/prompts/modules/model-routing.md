<model-routing>
## Model routing

**Owner decision, effective 2026-10-29 15:11 KRS:** local orchestrators use Codex;
all ordinary workers use the MultiCode hub. This replaces native-worker defaults,
native Sonnet/Opus fallback, the former Opus orchestrator route, and routing based
on old subscription-pool or Plus-versus-Pro ratios. The reason is to keep local
orchestration separate from worker capacity and use hub Claude for creative quality.
Routing policy belongs here, not in personal memory or project AGENTS files.

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
our own Claude subscription, native Codex workers, Grok, or Harness for ordinary work.
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
Local-only work is not permission to start a native worker or upload existing history.

Preserve existing idle native threads and worktrees. Do not delete, migrate, upload,
or restart them merely to apply this routing decision. The owner selects the local
Codex orchestrator manually; agent tools do not gain permission to start auxiliary
native Astra/Sol sessions. Manual model selection and persisted-session recovery keep
their existing boundaries.

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
