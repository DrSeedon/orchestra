<model-routing>
## Model routing

**Owner decision, effective 2026-10-29 15:11 KRS:** local orchestrators use Codex;
all ordinary workers use the MultiCode hub, with the one protected-work exception under
"Keep protected work local". This replaces native-worker defaults,
native Sonnet/Opus fallback, the former Opus orchestrator route, and routing based
on old subscription-pool or Plus-versus-Pro ratios. The reason is to keep local
orchestration separate from worker capacity. The later Sol-only decision below supersedes
the former hub Claude creative permission.
Routing policy belongs here, not in personal memory or project AGENTS files.

**Owner decision, 2026-10-31:** our native orchestrator roles default to GPT-6.1 Terra
with explicit `high` reasoning, to use the owner's chosen model for orchestration.
The pipeline manifest owns the exact model and effort; an explicit manual model choice
still takes precedence. This default does not migrate existing sessions or grant native
Terra worker admission. Apply a manifest containing a new model only after that host's
running Python registry recognizes it; an offline host must activate the registry with
the old manifest before receiving the new default.

### Hub workers: Sol and the bounded Argon specialist

**Permanent owner decision, 2026-11-02 17:27 UTC (2026-11-03 00:27 KRS), clarified
at 17:29 UTC:** ordinary hub workers in every scope must use `hubsol` (GPT-6.1 Sol).
The owner requires this enforced in Orchestra to prevent hub Opus creation and keep
all hub work on Sol. This includes creative work, research and existing workers on
send, queued delivery, resume and recovery, subject only to the narrow design exception below. It supersedes all earlier hub Claude
creative permissions and other hub-model choices.

- Pass `model="hubsol"` explicitly to `spawn_worker` or `change_worker_model`.
  Aliases, direct/versioned IDs, stored flags and `model_reason` cannot permit hub
  Opus, Sonnet, Haiku, Luna, Grok or any non-Sol model outside that exception.
- Keep the pipeline's existing effort. This decision does not change effort defaults,
  native orchestrator defaults or the owner's manual native orchestrator choice.
- The canonical routing guard in `app/models.py` refuses with
  `hub_workers_require_sol` before provider submission; it never resets a worker's
  model, clears a recovery latch, replays a delivery or discards WIP/history.
- Hub configuration, company/privacy, ownership, quota and provider-capacity guards
  still apply. If Sol is at capacity or unavailable, report the blocker or wait.
  Do not choose another hub model, native worker or API fallback.
- Do not migrate live workers, remote workspaces or held queues to apply this rule.
  Activation follows the owner's idle watcher; code on disk is not live activation.

**Owner decisions 2026-11-03, V-1257:** 14:52 approved the separately funded
Hub designer; 15:31 expanded the SAME integration to bounded specialist work.
A separate `specialist` role in the `default` pipeline uses the model configured
by that role in the pipeline manifest. Its Gemini route maps only to Hub provider
`antigravity` and wire model `gemini-4-argon` (Gemini 4 Argon). Use the existing paid Hub pool with no extra
charges to us. All other roles stay on Sol; this is not permission for Google
APIs, DostupAI, Carbon, purchased overages, auxiliary image models (including Nano Banana),
other paid tools or a model/API fallback.

- The specialist does bounded design, long-document synthesis/comparison, and
  financial/legal reasoning over safe public or synthetic material. Video analysis
  is within the intended scope only after required Hub input support is proven.
  Use text prompts and safe textual source bundles now. Public transcripts can be
  analyzed as text, without claiming to have watched video. Preserve source coverage
  and name unread material. Small HTML/CSS/SVG design-artifact edits are allowed;
  general terminal/repository coding stays on Sol and native Codex orchestration
  is unchanged. No agent spawning, protected data or live-infrastructure access.
- Google publishes a [model card](https://deepmind.google/models/model-cards/gemini-4-argon/)
  and [API model documentation](https://ai.google.dev/gemini-api/docs/models/gemini-4-argon).
  Their long-context, multimodal, finance/legal and long-decode descriptions are
  maker-reported API/model capabilities, not our Hub measurements. Hub video,
  image/audio/PDF ingestion, large context, long-decode and Google-app integration
  remain explicitly unverified. Do not expose those inputs/features, copy vendor
  benchmark percentages or prices into platform guarantees, or invent registry metadata.
- Admission uses existing persisted role, pipeline, bound task and project scope.
  Empty/unknown/old roles or task identity refuse. A name, tag, task description,
  `model_reason` or catalog toggle cannot grant Gemini. Every send/connect/change,
  queued delivery and recovery rechecks the same canonical rule; missing context
  fails closed. Never change identity to evade a refusal.
- Use `high` effort, supported by the live Hub catalog. Do not invent a context
  window, modality, price or quota percentage. Antigravity goes through Hub
  provider-capacity admission and the shared turn limit. Exhaustion holds work;
  absent telemetry is visibly `unknown` under the existing canonical quota policy,
  not proof of spare capacity. Preserve privacy, ownership, history and recovery.
- Activation is staged: Phase A installs code/rules and stages the role with a
  known Sol model in the live manifest. This is not a working Gemini specialist.
  Root first verifies the registry after the normal owner idle watcher, then
  applies Phase B selecting Gemini. Never hot-load an unknown model in the manifest,
  restart manually, launch early, or migrate existing workers/queues.
- After accepted code and authorized activation, verify one tiny safe file-writing
  smoke through the normal admitted specialist. No real infrastructure, protected
  inputs, image models or extra paid tools. A model listing or offline mock is not
  that operational verification; specialist quality needs separate actual samples.

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
Harness workers. Manual native model selection keeps its existing boundaries; persisted hub-session
recovery must pass the canonical context-aware Hub guard before another provider submission.

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
These historical observations do not authorize hub Claude selection, benchmark today's
hub deployment or restore former native routes. Historical price and pool-size
comparisons are not current routing rationale.
</model-routing>
