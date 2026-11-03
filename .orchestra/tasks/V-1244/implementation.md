# V-1244 implemented retention contract

Owner approval: 2026-11-03 01:42 KRS, relayed by root. Ordinary Hub close preserves history/accounting and retained history occupies disk; deletion needs separate approval.

## Lifecycle owner and recovery

`archive_workspace` is separate from the existing destructive release operation. It checks retained privacy/recovery evidence, interrupts the known thread, confirms its termination with one bounded existing wait call, archives that same thread, and only then persists `archived=true` in the existing workspace record. No project/thread/provider-history/accounting object, workspace directory, input manifest or retained sync snapshot is removed. Missing transport, unknown/running/timed-out termination, pending sync or privacy failure leaves the record available for recovery and blocks Hub close. Native best-effort cleanup retains its existing boundary.

`archive_for_worktree` preflights every selected known record before archival and respects replacement/explicit clean-start scope exclusions. Loaded/stored Hub close uses it strictly before cancel/disconnect/local worktree teardown; native cleanup retains its prior best-effort refusal/logging behavior without discarding old Hub evidence. Task transitions check pending/privacy evidence before lifecycle publication; the changed branch/task closes its previous generation afterward. The existing text-tail Hub→native remediation remains allowed after a saved handoff even when archival is refused; it logs and retains the old evidence, as the prior privacy contract required.

Post-merge cleanup uses the same archival owner. Schema-v2 same-task continue retains its active workspace/history. Task transition archives the former generation. Optional post-merge cleanup defers when an explicit next task or a late attached assignment exists, and never authorizes parent kill while a next phase is assigned. Optional cleanup failure does not delete recovery evidence or proceed with local generated-output cleanup. The known worker's ordinary kill still uses existing WIP/privacy/ownership/lifecycle gates and retains local Orchestra session/log accounting through archive_session.

The existing orphan sweep now observes/retains records without remote mutation: old, incomplete, malformed, missing-process and unrecorded remote objects are never inferred disposable. This is intentionally not a new scheduler, TTL or inference of task acceptance. Ordinary backend replacement archives known old generations; pending recovery blocks replacement. A persisted archive marker prevents stale backend reuse; an unreadable known record refuses resume instead of launching work from an uncertain identity.

## Legacy records and activation

The only additional persistent field is a boolean default on the existing WorkspaceState JSON record. Old records load with `archived=false`; no bulk migration rewrites data or grants purge. Archived records retain the same IDs and provenance. Repeat/restart uses those same IDs; a lost archival response retries the existing thread and never creates a new provider turn.

All accepted lifecycle owners must be activated together through root's authorized idlewatch. Old running Python still implements destructive cleanup and must not be treated as upgraded because files on disk changed. The new field is a forward reader default for old data, not a promise that old Python understands the new retention policy. No deployment, restart or actual purge was performed by this worker.

## Parent instruction and equivalence

One trusted Hub action builder enriches existing explicit journal-backed reports and existing durable auto-report messages. It requests validation and acceptance of an exact full HEAD; a provider-completed/end_turn by itself never accepts a task. The backend never executes parent merge/kill tools.

The canonical terminal merge-result owner produces `ARCHIVE_COMPLETED_HUB_WORKER` only for successful finalized schema-v2 complete, no next task, same session/name/scope/branch, cleared task binding and exact accepted HEAD. The action carries the worker session and operation/HEAD, and requires rechecking that same session, completion, validation, preserved work, no later assigned phase and the shared kill gate. Compact/verbose MCP and the existing completion watch expose that one durable action. Failed/partial/unknown/continue/handoff/native cases keep their previous result/recovery routes. Replay does not start a duplicate merge/wake/provider turn.

Accepted Sol-only routing is reconciled from exact public main0bbb0b96eb9b50cacee41023542d1d25cb560310 using a clean three-way merge from base36bc. Existing model/role/quota/ownership/queue/native admission guards are preserved; no alternative model is introduced. Native lifecycle policy is unchanged. The one default-characterization test that still expected opus is aligned to main's owner-approved hubsol, without changing production routing or weakening admission tests.

Separate image-artifact cleanup is outside this worker-lifecycle retention contract and was left unchanged; root was notified. No artifact generation was invoked.

## Superseding ownership correction after rejected50d2

Any earlier wording implying optional post-merge Hub archival is superseded. The observer does not own Hub generation membership and never archives by worktree. Task transition/explicit close remain the existing archival owners. Optional cleanup holds Hub/unknown/history; native cleanup spans existing manager session/live lifecycle locks through every await and existing repository flock through identity check/deletion. See the unchanged supplied probe, later-await/flock tests and committed unsafe-function mutation in stage.md. No new runtime/store or hidden architecture branch was introduced.

## Superseding cancellation correction after rejectedb8fb

Holding async locks lexically was insufficient when a to_thread await was cancelled while its real thread/flock continued. The critical native future now preserves copied context and is shield-drained by the existing _wait_owned_task inside those locks, through repeated cancellation. Only after actual thread completion/error retrieval does the caller receive the saved cancellation. The actual transition_lifecycle/new Hub-record ordering matrix and committed rejected-function mutation are current proof; earlier green counts are historical.

## Current integrated-host correction
Supersedes current-delivery claims in earlier sections: five c38c19 host outcomes reproduced and resolved by the minimal backend optional-identity hunk plus input/native/fixture regression corrections. Production owners/guards outside backend completion block unchanged. Fresh manifests and exact patch are in host-outcomes-*; current report/checks are stage.md (106 two-worker +63 serial passes after three red mutations). Historical source/check hashes above are not the final delivery identity.
