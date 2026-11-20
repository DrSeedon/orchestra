# Focused R3 delivery-receipt P1 correction
VERDICT: new receipt P1 fixed in mock tests; overall acceptance remains RED.
Base 1a247b24a434ee68c462ba899040516329c1d831; corrected commit in final reply.
Worktree /home/kesha/orchestra-worktrees/agy-acp-safe; branch agy-acp-safe.
Exact imported app: /home/kesha/orchestra-worktrees/agy-acp-safe/app.

## Submission contract (existing canonical states, no second state machine)
- QUEUED/PREPARING includes profile-lock wait, initialization, session/catalog/model
  validation. No prompt bytes have been submitted; failure is FAILED_BEFORE_SUBMIT.
- Existing delivery.before_submit executes under the ACP write lock just before
  stdin.write: durable DISPATCHING precedes the potentially ambiguous write.
- SUBMITTED means session/prompt bytes were written and stdio drain completed.
  This is local transport handoff, NOT remote model acceptance, success or completion.
  A subsequent correlated model refusal is a failed turn after a real submission;
  receipt does not authorize replay and duplicate ID does not resend.
- If the write began without local write/drain confirmation, existing DELIVERY_UNKNOWN
  remains at-most-once/quarantined. A crash between write proof and durable submitted
  remains conservatively unknown on canonical recovery. No prompt is replayed.
- Caller gets normal accepted HTTP202/resource/status URL, then the canonical truthful
  receipt/refusal. Explicit retry of a definitely unsent same ID uses existing policy;
  ambiguous/submitted duplicates return the existing receipt only.
- Backend send still starts an asynchronous per-turn stream. Receipt callers additionally
  await the transport future, not the model turn. Session starts the real reader and
  releases its lifecycle lock during that wait, so HTTP interrupt can cancel a queued
  profile-lock wait. Cancellation also bounds backpressured cancel-write to2s.
- message_deliveries.py / initial_deliveries.py are unchanged; their existing hooks,
  failure/unknown transitions, notifications and recovery own durable state.

## Exact checks
| Check | Result | Evidence |
|---|---|---|
| Before product fix on base | 2 failed: false SUBMITTED with prompt0 | before.log |
| Final narrow HTTP/real-session/mock-stdio tests | 10 passed, 0 skipped, 2 warnings,11.29s | targeted-final.log |
| One combined210 + new receipt + selected canonical receipt contracts | 225 passed,1 failed,2 warnings,31.79s | acceptance.log |
| Instruction / syntax / diff / staged secret scan | PASS | instructions.log, cleanup.json |

The single combined run used the8-receipt-case stage. Then only targeted coverage
was strengthened (local RPC refusal + healthy sibling; two real initial cases), with
no application-code change or second combined run. Final targeted result is10passed.

The combined failure is the unchanged frozen initial-delivery test named in verification.json:
its Claude model/scope hits claude_multicast_only before its mocked transport. This
policy/fixture gate was not modified, waived or repeatedly rerun. No global GREEN.
The10 narrow cases cover model absent/config contradiction prompt0 and truthful duplicate
failure, healthy sibling on same daemon, blocked inference already SUBMITTED once,
queued cancellation, preflight failure, post-write RPC refusal, lost write proof,
backpressure cancellation and both real initial-receipt outcomes. Fault injection changes
only real stdio confirmation/drain, not model ACKs, listeners or receipt states.

## Unchanged limits and cleanup
The old compact timeout was statically localized by Astra R3/parent on the earlier
snapshot: Claude + /test -> claude_multicast_only -> generic compact retries30/60s,
before ACK. This is baseline/fixture interaction, not a measured final-HEAD pass.
No timeout bundle or full frozen legacy rerun here; historical15failed/18passed/79errors
remain historical and open. Fixed-account restriction remains: same HOME account
switch/generation migration unsupported. No real CLI compatibility, eligibility,
consumer authorization or account-ban immunity claim; no activation.

All checks use existing kernel netns with lo only/external_routes0, fake-only subprocess,
synthetic HOME/SQLite and existing secret/filesystem guards. No real agy/version/help,
Google/OAuth/quota/model/credential reads/copies, main/provider/billing/proxy/T3 edits,
push/merge/deploy/restart or helpers. Owned mock/runner processes0, stand stopped;
production HEAD/dirty files/disabled switches unchanged (cleanup.json).

Source: app/antigravity_acp.py, app/backend_antigravity.py, app/session.py.
Tests: tests/test_antigravity_acp_submission.py; fake peer only adds synthetic catalog/
post-write rejection cases. verification.json records actual per-test RPC counts.
