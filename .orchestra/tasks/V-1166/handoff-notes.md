# V-1166 native eval handoff — current 2026-11-02

Owner architecture decision, 02.11.2026 18:27 KRS, supplied by parent:
«нахуй эту изоляцию делай по простому как раньше».
This supersedes the old experiment sandbox/readOnlyAccess/bwrap blocker. Eval now
uses the existing CodexBackend managed auth/home and ordinary thread/start and
turn/start parameters. No alternate CLI/runtime/wrapper, OAuth copy, global CLI
config, AppArmor, service or ordinary-worker routing/catalog change is involved.
The separate evaluation_actor_id selects an ordinary managed worker home without
requiring an Orchestra MCP endpoint. Its stopped-state guard forbids local restart
following cancellation. No additional sandbox confirmation is requested. The
synthetic Git workspace only separates fixture files/output; it is not a security
sandbox and ordinary CLI filesystem/network authority is not claimed restricted.

## Coding stage and exact frozen contract

The parent-approved matrix (log1057106) covers four prepared coding fixtures and
all ACTUALLY supported efforts for Terra 6.1 and Sol 6.1, each once. Parent's
installed CLI0.166 listing reports low/medium/high/xhigh/max/ultra for BOTH models;
the current matrix is **4 × 2 × 6 = 48** one-shot task invocations, not40 and not
internal provider requests. The global original grant limit remains56 tasks/5400s,
with serial execution and the accepted observed 500000-generated-token stop.

Use frozen pack version=2, stage="coding", preserving the original four fixture
model_input_files hashes, hidden oracle/reference hashes and eight RED/GREEN
control assertions. Supply runtime_supported_efforts mapping exact model IDs to
the actual effort lists obtained by the authorized host executor.
`allowed_models_efforts` must cover that mapping exactly, without duplicates/extra conditions.
run-order.csv has one repeat (repeat=1), exactly every fixture/condition once; its
hash and the whole manifest hash must be refrozen for the changed matrix. Never
reuse an old manifest hash after changing rows. Model runtime listings are checked
per call against the frozen supported-effort set; drift or unsupported efforts
stop before generation. Source tests use synthetic fake metadata, not live reads.
ReasoningEffort is the model-advertised non-empty string, not the legacy ordinary
UI/worker enum. Eval preserves it byte-for-byte in CLI configuration and turn/start.
The fixed ordinary-worker normalization is deliberately unchanged; ultra is not
described as a client-only parallel mode. Non-empty future advertised labels are
supported within the same frozen/runtime check, without a new hardcoded enum.
Empty/non-string, duplicate, unadvertised or drifted values refuse. Open label
support cannot enlarge the approved56-task cap. The old40-cell frozen matrix is
now stale against the supplied six-effort listing and must be refrozen as48,
preserving fixture/oracle bytes and hashes; never mutate an issued grant in place.

Legacy version=1 frozen 56-cell grants remain readable for durable old-data
compatibility; they do not authorize ordinary workers or automatic extra runs.
The original fixture handoff hash
`64ac99c3f6ea62dbf6dfd72cddc0cddc15348b037ada6c73a702e01286ea7b3f`
is historical evidence of the old pack, not a source allowlist or the new matrix
hash. Hidden oracles/references remain coordinator-side; only seed/src and prompt
are materialized for the model. No history/account/credentials are model inputs.

The proved root issues through eval_grant_issue with concrete task_id, exact
manifest/expected_hash, public fixture_inputs, original frozen run_order_csv,
owner audit approval_ref, expiry within 90 min and the accepted token_policy.
The reference is audit text from the authenticated issuer, not cryptographic
proof of user message text. Ordinary agents cannot forge issuance via a flag.

Then dynamic_workflow omits tasks/stages, uses eval_grant_id/eval_manifest_hash,
budget_usd=0, max_calls=48 (or another bound covering the actual frozen cells but
at most56), max_concurrency=1. The server supplies immutable tasks. A too-small
runner max_calls queues nothing and leaves the single-use grant bound; no implicit
retry/reissue. Server reserve also rejects an index outside the smaller frozen
plan even when it is below56. Actual48-call client and full fake HTTP-ledger
execution are permanent repository tests.

The later 11-case Terra/Sol/Luna orchestration comparison stays a separate phase.
Its matrix approval is not questioned here, but this coding implementation does
not auto-issue a second grant or silently allocate a larger orchestration budget.
The root must associate it with its concrete approved call/token/deadline limits.

## Unchanged mandatory gates

Root proof/task identity/frozen manifest/single-use/expiry/atomic before-dispatch
ledger, visible/available model catalog, normal worker quota, real scheduler lease,
subscription-only auth, non-orchestrator task/run usage actor, no workflow retries
or API fallback, local stop on lease loss/caller cancellation/deadline, and late
task/project/ref identity checks remain. Serialized manual-only agents=False for
Sol/Terra is ordinary-worker policy, not a distinct eval revocation; ordinary
spawn/dynamic-workflow remains refused without a grant. Luna worker-disable is
unchanged. Unknown usage or unresolved reservation stops remaining dispatches and
never replays an ambiguous provider call. Final replay returns the saved result.

Generated budget counts output once including its reasoning subset, excluding
input/cache; model_calls remains nullable. Virtual USD is not subscription spend.
500k is an observed stop, not hard cap. No finite remote overshoot guarantee is
invented or imposed as a new prerequisite. Local interrupt/disconnect prevents
our continuation and does not prove remote cancellation.

## Acceptance/delivery

Local-ops V1170 owns host acceptance/activation after this source return. This
worker issued no real grant, metadata call or inference, and did not merge/restart/
push. Parent cites source/WIP a2d09f48 for this narrow effort delta; no .git/main
exists in this broker copy, so exact HEAD/integration must be verified on host.
Only the eval effort constructor branch/comment change in this backend delta;
other methods, including steer/recovery/usage/sleep, remain AST-identical to input.

Current source report is REPORT.md, concise closure is closure.md. Seven-file
public task allowlist remains. Parent's canonical LOCAL private raw preservation
stays authoritative; old remote evidence is not copied/republished/untracked.
New scoped testtmp is outside checkout; only final small logs/receipts may be
preserved privately. Ignore rules are publication policy, not a transport filter.
