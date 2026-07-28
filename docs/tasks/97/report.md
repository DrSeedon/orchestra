# Task #97 — implementation report

## Result

Fixed the Codex-only compact/listener race proven in `research.md`.

- `events()` snapshots the id returned by the preceding `turn/start`.
- One `_lifecycle_belongs_to_turn()` gate handles both `turn/started` and
  `turn/completed` before `_convert_notification()` can mutate state.
- Rejected lifecycle events emit a debug log with method, received turn id, and
  expected turn id.
- Native compact attaches a private notification queue before
  `thread/compact/start`.
- One `asyncio.timeout()` deadline covers the start RPC, compaction completion,
  and explicit `_drain_compact_lifecycle()` wait through the matching terminal.
- Cleanup detaches the private queue on success, timeout, cancellation, or
  request failure. A late compact event that arrives after timeout is still
  rejected by the listener ownership gate.

Claude handoff compaction, Grok prompt queuing, shared runtime capabilities,
`_pending_messages`, and `_flush_pending` were not changed.

## Tickets

### T1 — Codex turn ownership

Complete.

- Mismatched compact start cannot overwrite the RPC-returned current turn id.
- Mismatched compact terminal cannot clear the current id, emit `turn_end`, or
  terminate the listener.
- Matching current output is visible without a second send.
- Matching current terminal alone returns `AgentSession` to `IDLE`.
- Steering retains the RPC-returned id because stale starts cannot replace it.

### T2 — Explicit compact lifecycle drain

Complete.

- Compact notifications are isolated before the start RPC.
- `compact_context()` does not return between compaction completion and its
  terminal event.
- Missing terminal is bounded by the same 120-second operation deadline.
- The exact real-function compact → next-listener sequence no longer leaves
  stale lifecycle notifications in the ordinary queue.

## Changed files

- `app/backend_codex.py` — +62/-12 production lines.
- `tests/test_backend_codex.py` — +152/-16.
- `tests/test_session.py` — +197/-0.
- `docs/tasks/97/plan.md` and both Codex review artifacts.

No Claude or Grok production file changed.

## TDD evidence

Before production changes:

```text
test_events_reject_stale_lifecycle_without_losing_current_turn      FAILED
test_stale_compact_lifecycle_cannot_false_idle_current_turn         FAILED
2 failed
```

The failures were the measured defect: current output was absent and the
session listener had already exited after the stale compact terminal.

Before compact routing/drain:

```text
test_native_compact_drains_terminal_before_returning                FAILED
test_native_compact_missing_terminal_times_out_and_detaches         FAILED
test_native_compact_cannot_leak_lifecycle_into_next_listener        FAILED
3 failed
```

After implementation, all five regressions passed.

## Mutation evidence

Each protection was disabled independently and then restored:

| Mutation | Expected result |
|---|---|
| ownership helper accepts mismatched lifecycle | 2 regressions failed |
| `_drain_compact_lifecycle()` returns immediately | 2 regressions failed |
| `_read_stdout()` routes compact notifications to ordinary queue | 2 regressions failed |

After restoring all three protections, the five targeted regressions passed
again. The final diff contains no mutation.

## Verification

```text
tests/test_backend_codex.py + tests/test_session.py:
136 passed

tests/test_backend_claude.py + tests/test_backend_grok.py
+ tests/test_runtime_registry.py + tests/test_session_hibernate.py:
92 passed

full pytest:
exit 0
raw artifact: /tmp/pytest-97.log
```

`git diff --check` passed. The cross-runtime command exercised Claude, Grok,
runtime capability, and hibernate paths without modifying their implementations.

## Codex reviews

- Plan: two rounds; the first found an unbounded post-completion drain and two
  test-ordering gaps. The plan was corrected to use one deadline, attach the
  queue before the RPC, and separate mutation checks. Round 2: **APPROVED**.
- Implementation: the first infrastructure attempt timed out without a
  verdict after running extra tests. A narrowed retry returned **APPROVED** with
  no findings. Mandatory shared-runtime Round 2 separately challenged missing
  terminal, timeout/late events, cancellation, and stale lifecycle/steering:
  **APPROVED**, no new findings.

Artifacts:

- `docs/tasks/97/codex-review-plan.md`
- `docs/tasks/97/codex-review-impl.md`

## Deployment and remaining risk

- The server was not restarted and the live database was not opened or mutated
  during implementation.
- The running service still has the pre-fix, pre-#91 deployed application code
  identified during research; none of this implementation is active in
  production yet.
- The fix is confined to `CodexBackend` and does not depend on #91. Current-main
  tests cover #91's lifecycle completion signal, but the transport invariant
  works without it.
- Battle verification can begin only after the user-controlled service restart.
  Until then, old-log incidents remain evidence for the old runtime, not this
  fix.

## Breaking changes

None.
