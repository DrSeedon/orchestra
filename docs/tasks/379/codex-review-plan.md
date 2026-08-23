<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Summary

The plan is not ready for implementation. Both frozen commands are genuinely RED for missing behavior, not collection/import failures:

- T1: `5 failed`, exit `1`.
- T2: `1 failed`, exit `1`.
- Current test files exactly match commits `17ea95a6` and `39deefe0`; T2 is unchanged between them.
- Tickets are acyclic, though T2’s dependency on T1 is only an `app/main.py` integration-order dependency.
- No socket recycle, `FlushPending=yes`, waiter-specific fix, unit change, or live deployment is proposed.

The frozen tests do not mechanically enforce several blocking safety properties.

## Findings

1. `blocking:` [plan.md:105](/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-restart-socket/docs/tasks/379/plan.md:105) — `_shutdown_runtime()` executes inside ASGI lifespan teardown, so it cannot truthfully emit `cleanup_complete / asyncio.Runner.close`: Uvicorn closes its runner only after lifespan returns. The test manually injects that marker while a separate target is already stuck in `asyncio.run()`, which does not reproduce production placement. The implementation must either rename the boundary to the actual guarantee—application teardown complete after bg and manager—or introduce a real post-lifespan Uvicorn seam. Do not claim Runner cleanup has completed.

2. `blocking:` [test_restart_generation_liveness.py:154](/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-restart-socket/tests/test_restart_generation_liveness.py:154) — there is no negative oracle proving that the guard cannot signal before `cleanup_complete`. Both helper force-path tests send `cleanup_complete`; an implementation that starts its kill budget immediately and ignores phases can pass. Add a live target case that sends an earlier phase or no phase, waits beyond the budget, and proves the target remains alive.

3. `blocking:` [test_restart_generation_liveness.py:86](/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-restart-socket/tests/test_restart_generation_liveness.py:86) — PID identity is asserted only in the output schema. No test supplies a wrong `start_ticks`, exercises a dead/reused PID, or proves signaling uses the opened pidfd rather than `os.kill(pid, ...)`. An unsafe helper that ignores `start_ticks` and kills by numeric PID can pass. Freeze mismatch and target-exited controls that require a non-forced terminal outcome and leave the foreign process alive.

4. `blocking:` [plan.md:30](/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-restart-socket/docs/tasks/379/plan.md:30) — helper FD isolation is untested. `_start_guard()` only demonstrates its own progress pipe; no listener or agent-pipe FD is present for a `/proc/<guard>/fd` census. A production arm that omits `close_fds=True` or leaks an explicitly inherited descriptor can pass. Add a production-arm test containing both a listener and representative agent pipes and assert the helper owns only its progress FD plus normal stdio.

5. `blocking:` [test_restart_generation_liveness.py:213](/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-restart-socket/tests/test_restart_generation_liveness.py:213) — durable persistence is mocked at the route boundary. A no-op `_drain_restart_durable_state()` and no-op `SessionManager.drain_restart_persistence()` satisfy the ordering test. Nothing proves a snapshot of actual sessions invokes every `AgentSession._drain_handoff_log_writes()`, waits for them, propagates failure identity, or respects the 30-second budget. This permits durable session/log loss while all frozen tests pass.

6. `blocking:` [plan.md:85](/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-restart-socket/docs/tasks/379/plan.md:85) — the promised after-arm failure path is not tested. The only failure test fails before guard creation. There is no injected `broker.close_subscribers()` or `os.kill()` failure proving `abort_guard(reason)` completes before handover rollback/gate reopening and leaves no armed killer. This is specifically the path where a recovered old supervisor could later be killed.

7. `blocking:` [test_restart_fd_hygiene.py:190](/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-restart-socket/tests/test_restart_fd_hygiene.py:190) — T2 uses `LISTEN_FDS=1`, so an implementation sealing only fd 3 passes despite the plan requiring the entire activation range, including adopted agent pipes. Add multiple named activation FDs and assert every descriptor is non-inheritable, remains open, and retains its name→fd mapping.

8. `blocking:` [test_restart_fd_hygiene.py:43](/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-restart-socket/tests/test_restart_fd_hygiene.py:43) — importing `app.main` only proves sealing happened before the import returned, not before `app.deps.manager` or another import-time child spawn. Moving `seal_activation_fds()` below `from app.deps import manager` would still pass this test. Freeze the required import ordering mechanically, or arrange an import-time spawn seam that fails if it sees an inheritable activation FD.

9. `question:` [plan.md:36](/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-restart-socket/docs/tasks/379/plan.md:36) — EOF before `cleanup_complete` is described alongside `aborted`, while the terminal schema also defines `progress_lost`; the exact mapping is unspecified. Define whether explicit parent abort produces `aborted` and unexpected EOF produces `progress_lost`, including their exact `phase`, `task_class`, and exit status.

## Verdict

Needs work — 8 blocking findings.

The current RED state is valid, and T2’s queue=350 plus explicit legacy holder and real Uvicorn arm is a useful handoff oracle. However, the frozen suite can become green with unsafe force ordering, numeric-PID signaling, missing durable drains, leaked helper/activation FDs, and incorrect production placement. Phase 3 should not begin until those oracle gaps and the impossible `asyncio.Runner.close` claim are resolved.

## Round (2026-08-23T16:33:40Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Summary

Re-review completed against immutable T1 `40177164` and T2 `97b0990a`; both current files match those commits, and T2 is unchanged at `40177164`.

Commands are genuinely behavioral RED:

- T1: exit `1`, `12 failed`; collection/import succeeded.
- T2: exit `1`, `2 failed`; collection/import succeeded.
- No test is already green.

Prior findings: **FIXED 1, 2, 4, 5, 6**; **STILL BROKEN 3, 7, 8**.

## Findings

1. `blocking:` [test_restart_generation_liveness.py:278](/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-restart-socket/tests/test_restart_generation_liveness.py:278) — **Round 1 #3 STILL BROKEN.** The AST test requires `signal.pidfd_send_signal` and forbids `os.kill`, but does not enforce the plan’s load-bearing order “open pidfd, then read/compare starttime.” An implementation can read a matching starttime, let that PID exit/recycle, then open a pidfd for the foreign process and signal it; the wrong-starttime test does not exercise that race. Add a mechanical order oracle or injectable identity seam proving the starttime belongs to the process referenced by the already-open pidfd.

2. `blocking:` [test_restart_generation_liveness.py:566](/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-restart-socket/tests/test_restart_generation_liveness.py:566) — **new production-wiring gap related to Round 1 #1.** The test invokes `_shutdown_runtime()` directly but never proves `lifespan()` calls it. A correct dead helper plus the existing inline teardown can pass all shutdown-order assertions while production never emits `application_teardown_complete`; the guard then reports `progress_lost` and never performs the intended fallback. Freeze the lifespan→`_shutdown_runtime` wiring mechanically or through the real lifespan path.

3. `blocking:` [test_restart_fd_hygiene.py:240](/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-restart-socket/tests/test_restart_fd_hygiene.py:240) — **Round 1 #7 STILL BROKEN.** Preservation of fd 4/5 is not actually asserted. The test records their original pipe targets, but only checks that the post-import targets are nonempty. Production could close both agent pipes and reopen unrelated CLOEXEC descriptors at 4/5; mapping and child census would still pass, causing handoff/data loss. Compare every post-import target exactly with `activation_targets[name]`, as already done indirectly for listener fd 3.

4. `blocking:` [test_restart_fd_hygiene.py:250](/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-restart-socket/tests/test_restart_fd_hygiene.py:250) — **Round 1 #8 STILL BROKEN.** `str.find()` is not mechanical call-order enforcement: a comment or string containing `_fdstore.seal_activation_fds()` before the manager import plus the real call afterward passes both tests. Use AST top-level statement ordering and require an actual `Expr(Call(Attribute(...)))` before the actual `ImportFrom app.deps`.

Status of the remaining prior findings:

- **#1 FIXED:** the plan now honestly defines the last application teardown boundary and explicitly excludes completed Runner close.
- **#2 FIXED:** the pre-boundary wait and EOF arm proves no early force.
- **#4 FIXED:** production arm is exercised with listener and agent pipes, followed by explicit abort verification.
- **#5 FIXED:** real `SessionManager` fan-out and real timeout/payload behavior are covered.
- **#6 FIXED:** after-arm signal failure requires guard abort before rollback and verifies both gates reopen.

## Verdict

Needs work — 4 blocking findings remain. The revised architecture is substantially clearer, but the frozen oracles can still pass with a PID-reuse hole, dead lifespan wiring, destroyed agent pipes, or late seal placement.
