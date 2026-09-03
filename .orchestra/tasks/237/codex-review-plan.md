## Summary

The plan is vertical and dependency ordering is acyclic: T1 → T2 → T3 → T4, with #258 explicitly preceding manager integration. The production seams are concrete and implementable.

The frozen suite is correctly RED at baseline. Command:

`uv run python -m pytest tests/test_seamless_restart.py -q`

Exact output:

`12 failed in 14.02s`

However, several acceptance oracles can pass plausible implementations that still interrupt turns or endanger the production unit.

## Findings

blocking: Reversed inherited FD order is not tested. [tests/test_seamless_restart.py:289](/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-hot-reload/tests/test_seamless_restart.py:289) rebuilds `acquire_fds()` using the original insertion order, even though the plan requires parsing independent of systemd return order. A parser that assigns the first descriptor to stdin and the second to stdout passes this test but crosses the pipes when systemd returns stdout first. Add a reversed-order control and assert the complete side-aware mapping in both `_inherited_agent_pipes()` and `_inherited_named_fds()`.

blocking: Fleet rollback explicitly permits the refusing session’s reader to remain paused. [tests/test_seamless_restart.py:512](/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-hot-reload/tests/test_seamless_restart.py:512) requires `second_backend.resume_after_aborted_handover` not to be called. A plausible `_hand_over_backend()` can quiesce the second backend, return `False`, and leave its reader stopped; `prepare_restart_handover()` then satisfies this oracle by restoring only the earlier success. This contradicts the plan’s “restores every paused reader/event stream.” The oracle must exercise a failure after the second backend is quiesced and prove both readers resume.

blocking: Signal failure rollback has no oracle. The plan requires scheduling or signalling failure to remove every stored FD, clear prepared markers, restore readers, and reopen both admissions. All successful-route tests use a non-raising `os.kill`; the generic exception path only establishes gate reopening. An implementation that prepares the fleet, leaves readers paused and FDs stored after `os.kill` raises would pass. Add a post-prepare failing-signal test covering the complete rollback state.

blocking: The final unsupported-runtime recheck is untested. [tests/test_seamless_restart.py:555](/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-hot-reload/tests/test_seamless_restart.py:555) starts with Claude already busy; it does not model Claude/Grok becoming busy after the initial drain but before the signal. An implementation with a single early snapshot passes while cutting a newly started unsupported turn. Add a stateful `_drain_sessions()` sequence where the unsupported runtime becomes busy during/after Codex preparation, and require no signal plus rollback.

blocking: T4’s “cannot target production” oracle is only a substring check. [tests/test_seamless_restart.py:586](/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-hot-reload/tests/test_seamless_restart.py:586) passes a runner that contains the required words as dead constants but accepts an arbitrary unit argument or constructs `orchestra.service` dynamically. Since this is a destructive delivery runner, invoke its command-building seam with an attempted override and assert the exact fixed unit/argv, or require a fixed constant with no unit input surface.

blocking: T1 does not prove complete ownership teardown. The fake duplicates the child descriptors, but the test never verifies that Orchestra closes its original child ends after spawn or that every parent-owned descriptor closes after final disconnect. A production implementation can pass the two-generation stream checks while leaking two pipe ends per connection; retained child stdin ends also prevent EOF-based teardown. Add FD snapshots or explicit `fstat`/EOF assertions after connect and after final disconnect for all four original pipe ends.

suggestion: NULL-session adoption has no negative control for an incomplete pair. [tests/test_seamless_restart.py:317](/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-hot-reload/tests/test_seamless_restart.py:317) proves that a complete pair admits a NULL `session_id` row, but not that an unrelated or half-inherited NULL row remains excluded. Add a second NULL-session row with one/no inherited end and assert it is neither loaded nor adopted; leave cleanup itself to #258 as planned.

## Verdict

Changes required. The plan itself is implementable, vertical, and acyclic, but the frozen delivery contract is not yet safe to implement against: six plausible wrong implementations can currently turn the suite green while violating zero-loss restart or rehearsal isolation.

## Round (2026-08-13T09:12:36Z)

## Summary

Round 2. All seven prior findings are fixed. `_inherited_named_fds()` is correctly side-free: its consumers only close each orphan FD and map each FD to a PID; neither operation needs stdin/stdout identity.

Baseline confirmed:

`14 failed in 18.84s`

Plan quote: “`NFileDescriptorStore=2`, сменившийся MainPID, отсутствие ошибок и пустая очередь отдельно успехом не считаются.”

## Findings

- FIXED — reversed inherited FD order.
- FIXED — refusing backend reader rollback.
- FIXED — rollback after signal failure.
- FIXED — late unsupported-runtime recheck.
- FIXED — runner CLI cannot select the production unit.
- FIXED — child/parent FD teardown coverage.
- FIXED — incomplete `session_id=NULL` pair rejection.

blocking: T1 still does not exercise the stdin/write direction across handover. It proves the CLI stdin remains open, but never writes a JSON-RPC request through generation 2 or 3 and verifies the child receives it exactly once. A plausible wrong implementation can preserve stdout events while adopting a broken/crossed/nonfunctional writer and pass T1. Add a uniquely identified request after adoption, read it from `spawned.proc.cli_stdin`, and assert one exact frame with no duplicate bytes.

blocking: T4 verifies only the dry-run command builder. A plausible runner can emit the required safe JSON under `--dry-run` but use a separately constructed production-unit command during destructive execution. Freeze one shared command-construction seam and test that both dry-run and execution consume that exact argv, with subprocess execution mocked so no service is touched.

## Verdict

STILL BROKEN. The plan remains vertical, implementable, and acyclic, but the frozen oracles do not yet prove bidirectional transport continuity or that the real rehearsal path uses the dry-run’s safe unit.

Round 2.

## Post-round oracle closure (not a Codex approval)

The round ceiling was reached with the verdict `STILL BROKEN`. By explicit orchestrator decision,
the two findings were then closed without a third Codex call; therefore this document **does not**
claim Codex approval. The acceptance test was refrozen as `bc5e639d`; every result measured from
`1057aaa7` is exploratory relative to the new freeze.

- Adopted stdin now has a production-path assertion in the two-generation T1 scenario plus a
  current-code reachability control. Control: `1 passed in 5.18s`. Mutation
  `adopt(cli_out_r, cli_in_w, ...)` printed marker count `1` before the run and failed with
  `ConnectionResetError: Connection lost`; after rollback marker count was `0`, and the same
  control returned `1 passed in 5.18s`.
- T4 now loads the versioned runner and invokes its real `main(["--execute"], run=<mock>)` path,
  asserting the exact `orchestra-237.service` argv. A temporary reachable runner gave
  `1 passed in 5.55s`; mutation of only the destructive branch to construct
  `orchestra.service` printed marker count `1` and failed with expected-vs-actual mock argv;
  after rollback marker count was `0`, and control returned `1 passed in 5.66s`. The temporary
  runner was then removed, returning T4 to its preregistered missing-behaviour RED.

Frozen full baseline: `uv run python -m pytest tests/test_seamless_restart.py -q` →
`14 failed, 1 passed in 17.67s`. These post-round changes were mutation-checked, not independently
reviewed by Codex.
