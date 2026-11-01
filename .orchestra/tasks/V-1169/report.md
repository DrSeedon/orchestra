# V-1169: bounded post-fix cleanup events

Read-only evidence only. No cleanup, state write, service operation or test suite run.

## Events and durable outcomes

| Event | Timestamp UTC / PID | Durable merge result | Exception and current worktree state |
|---|---|---|---|
| E1 | 2026-10-30 03:30:04.092587Z / 1643396 | `SUCCEEDED`, `commit_point=REACHED`; finished 22.408 s before the cleanup log | `FileNotFoundError` at `app/worktree_cleanup.py:163`, `full.stat()` on a missing ignored bytecode/cache candidate. The matched V-647 triage interprets the root as present at the V-1072 root-verification check; it separately records the root absent during later triage and a verified archive deletion. The current root is absent; dirty state is unknown. |
| E2 | 2026-10-31 15:00:06.428148Z / 3102453 | `SUCCEEDED`, `commit_point=REACHED`; finished 3.646 s before the cleanup log | `FileNotFoundError` at the same `full.stat()` call on a missing task-private source candidate associated with V-1158. No secondary root-stat result is recorded in this context. The current root is absent; dirty state is unknown. |

Both exception paths name individual candidates beneath their worktree roots, not a missing root. Current absence does not establish root state at the time of either exception.

## Fix timing and detector calculation

The V-1072 record in the configured DB parent’s `error_watch.json` has `started_at=2026-10-24T16:20:02Z`, `window_hours=168`, and both recurrence/completion flags set. The record’s file mtime is 2026-10-31 17:08:31.777840Z. The V-1072 commit became the first first-parent main commit containing the fix at 2026-10-24 15:19:07Z. Service startup records show PID 1643396 started 2026-10-29 17:00:04.132281Z and application startup completed at 17:00:25.438901Z. The current MainPID 3102453 started 2026-10-31 07:01:31.220Z. Both process starts post-date the V-1072 mainline commit. A later mainline source update at 2026-10-30 08:24:40Z added a pre-cleanup branch while retaining the V-1072 root check.

The bounded exact-signature journal query returned four rows: a normal cleanup message and an ERROR logger presentation for each event. The exact main-source `deduplicate_events` and `post_fix_verdict` functions reduced these to two distinct records and returned `count=2`, `complete=true`. The saved V-647 journal matches E1 by operation identity; E2 is absent from that earlier bounded capture. The pre-existing TODO entry for E1 is the V-647 follow-up about an individual cache-candidate disappearance; it says implementation has not started. E2 points to V-1158’s preserved source collection. No new TODO or record-fix was added.

## Coverage and limits

The new journal query was bounded from the saved `started_at` through 2026-10-31 17:10Z: RC=0, empty stderr, four rows. Both same-PID contexts returned RC=0 with 52 and 54 rows. A read-only primary-key query returned both durable operation records. The prior V-647 journal had 21 headers and 11 contexts with `initial_rc=0`; it contains E1 exactly.

Both exact worktree roots were checked and are absent now. Git status could not be obtained for absent roots; no cleanup was run. Event-time root status is directly unavailable for E2 and is represented only by the prior V-647 triage interpretation for E1. One initial operation-extraction helper failed RC=1 on a relative context-file path; the corrected absolute-path run succeeded. Raw operation IDs, paths, context, operation rows, worktree checks, source timing and outputs are local-only under `.orchestra/private/V-1169/`.
