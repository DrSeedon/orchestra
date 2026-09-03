The research correctly identifies the broad `pkill` and numeric PGID risks, but its proposed contract leaves an SSH PID-reuse window and does not require coverage of process groups whose leader has already exited. Those gaps can carry directly into the implementation.

Full review comments:

- [P2] Use a stable identity for SSH tunnel signals — /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-memory/docs/tasks/120/research.md:243-245
  When an SSH child exits and its PID is reused between `Popen.send_signal()`'s final poll and `os.kill()`, the current `t.proc.terminate()`/`kill()` path can still signal the replacement process: `asyncio.subprocess.Process` is not a kernel-backed process handle, and CPython explicitly leaves this race in `Popen.send_signal()`. Therefore deleting `pkill` while keeping cleanup “по handle” does not meet the stated invariant that no foreign process receives a signal; the SSH lifecycle also needs stable identity or the guarantee must be narrowed.

- [P2] Test cleanup after the group leader exits — /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-memory/docs/tasks/120/research.md:260-263
  When a shell leader exits before cancellation or finalization while a child remains, such as `sh -c 'sleep 600 &'` with inherited stdout, current `_kill_proc()` returns immediately because `proc.returncode` is set, so merely retaining a leader pidfd does not cause the live group to be signaled. The listed leader-and-descendant test can pass with both initially alive and miss this known state; require a case where the leader is already reaped and verify the retained pidfd still drives group-wide TERM-to-KILL cleanup.

## Author resolution after Round 2

- **SSH handle finding — technically ACK, scope DISAGREE.** CPython source confirms
  the residual `poll() -> os.kill()` race. But the #120 request explicitly says not
  to change neighboring `terminate/kill`-by-live-handle sites because they are a
  different class. The research now narrows the SSH invariant to removal of broad
  command-line selection and records the remaining handle risk; implementation will
  not touch those signal paths without new authority.
- **Leader-already-exited finding — ACK and measured.** On kernel 6.17 a retained
  leader pidfd continued to signal the original process group after the leader was
  waited/reaped. With a TERM-ignoring child: group TERM rc=0/child alive, group KILL
  rc=0/child gone, unrelated process alive. The research and future AC now require
  this state and remove `_kill_proc()`'s current early return from the planned
  contract.

## Round (2026-08-01T10:59:08Z)

Well, the ticket now promises only the Unix magic it actually owns. 🙂

## Re-review status

- **RESOLVED — SSH stable identity:** [research.md](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-memory/docs/tasks/120/research.md) explicitly narrows the guarantee to removing `pkill -f` cross-process selection and records the residual `Process.terminate()/kill()` PID-reuse risk as out of scope. That conclusion is sound.

- **RESOLVED — exited group leader:** The research records the leader-already-reaped TERM→KILL result, requires retained-pidfd cleanup without the `returncode` early return, and includes this case in Phase 3 acceptance criteria.

## New findings

None.

## Verdict

**APPROVED FOR PHASE 2.** Both Round 2 findings are resolved with no remaining research blocker.

The gate now guards task #120, not the entire process table. 🚧
