<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Summary

The pidfd signaling, activation-FD sealing, durable-state ordering, and terminal event classification are generally sound. However, three shutdown/abort races violate load-bearing guarantees.

## Findings

- blocking: `app/main.py:291` — `_shutdown_runtime()` cancels `restart_inbox_drain` and `snapshot_task` but never awaits their termination. Either task may still be running cancellation cleanup when `application_teardown_complete` is emitted at line 325; five seconds later the helper may SIGKILL the supervisor. That permits pre-cleanup force and potential persistence loss. Await both cancelled tasks with `asyncio.gather(..., return_exceptions=True)` before emitting the terminal phase.

- blocking: `app/restart_guard.py:121` — `arm_guard()` treats successful `Popen` as successful arming, but there is no child-to-parent readiness acknowledgement after `open_verified_pidfd()`. The helper can exit on identity verification, pidfd setup, selector registration, module startup, or another early failure; `_do_restart_service()` will still send SIGINT. If ordinary shutdown then hangs, no helper remains to force convergence, producing the total outage this change is intended to prevent. Add a dedicated readiness channel and do not return from `arm_guard()` until the helper confirms that the verified pidfd and progress selector are active; EOF/error must abort before SIGINT.

- blocking: `app/routes/system.py:2323` — `_abort_restart()` catches every failure from `abort_guard()` and proceeds to handover rollback and gate reopening. `abort_guard()` can raise after its second timed wait, during cancellation, or if helper termination fails. The old generation can therefore resume without proof that the helper can no longer signal it, directly violating the “every abort path disarms before rollback” requirement. Make helper death a prerequisite for rollback/gate reopening; use a bounded SIGKILL of the helper itself if graceful abort fails, verify `wait()` completion, and fail closed if disarming cannot be established.

## Verdict

Needs work — 3 blocking findings.

Evidence reviewed: committed `/tmp/379-impl.diff` plus only the permitted implementation and immutable test files; `git diff --check be6d5a7e HEAD` passed. The supplied focused test and mutation results do not exercise these failure seams.

## Round (2026-08-23T18:16:13Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Summary

- Prior blocker 1 — FIXED. `_shutdown_runtime()` awaits both cancelled startup tasks before the first teardown phase.
- Prior blocker 2 — FIXED. READY is sent only after verified pidfd acquisition and selector registration; failed readiness is reaped before SIGINT.
- Prior blocker 3 — STILL BROKEN under the production wrapper’s repeated-abort path.

## Findings

- blocking: `app/restart_guard.py:207` / `app/routes/system.py:2306` — `abort_guard()` clears `_active_guard` before `_reap_helper()` proves helper death. If reaping fails, `_abort_restart()` correctly raises without reopening gates, but `_restart_service_after_response()` catches that exception and calls `_abort_restart()` again. The second call sees no active guard, succeeds, then rolls back handover and reopens both gates while the original helper’s disarm remains unproven. This recreates the exact armed-helper-after-rollback failure. Keep `_active_guard` until `_reap_helper()` succeeds, or prevent the wrapper from retrying a failed disarm. Add a regression through `_restart_service_after_response()`, with the first reap failing, that proves the second abort cannot reach rollback or gate reopen.

## Verdict

Needs work — one blocking race remains. The cancellation and readiness fixes are substantively correct; fail-closed disarming is not yet preserved across the complete production call chain.

## Round (2026-08-23T18:19:37Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Summary

Prior Round-2 blocker — FIXED. `abort_guard()` now clears `_active_guard` only after `_reap_helper()` returns successfully, and `_restart_service_after_response()` does not re-enter its own `except` handler when `_abort_restart()` raises.

The readiness and pre-cleanup cancellation fixes also remain intact. One new FD-identity blocker remains.

## Findings

- blocking: `app/restart_guard.py:210` — after a failed reap, the retained `GuardHandle` contains a closed `progress_writer`. Before a later retry, that numeric FD can be reused by an unrelated listener, database, or agent pipe. The next `abort_guard()` or `arm_guard()` then calls `_write_progress()` and `os.close()` on that reused number, potentially writing into and closing an unrelated live FD. Retain the process handle but mark the writer permanently invalid after its first close, and skip all later writes/closes for it. Add a regression that forces failed reap, reuses the old FD number with `dup2`, retries abort, and proves the replacement FD remains untouched and open.

## Verdict

Needs work — prior blocker fixed, but one new blocking FD-reuse bug remains. This is the final review round; no further review is implied.
