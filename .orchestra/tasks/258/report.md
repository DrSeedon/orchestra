# #258 — implementation report

## Outcome

T1 is complete. The first-restart orphan sweep no longer sends a signal to the current
occupant of a stale numeric PID. It reads the stored `(cli_pid, cli_started_at)` in one query,
opens a pidfd before reading `/proc`, verifies the stored lifetime and an exact managed-runtime
argv shape, and sends `SIGTERM` only through that pidfd. Unproven identity produces a PID-specific
ERROR and does not prevent the next orphan candidate from being checked.

No service was restarted and no production/system configuration was changed.

## Ticket

### T1 — Verified orphan cleanup through pidfd

Status: done.

- The frozen oracle remains byte-for-byte identical to commit `21ee9e33`.
- The production wiring exercised by the oracle is
  `orphan_pids -> sweep_orphan_fds -> terminate_orphan_process -> terminate_cli_process`.
- `backend_type` is not part of the persisted identity: it can change independently of the
  handover tuple.
- There is no numeric `os.kill` fallback in either changed production file.
- A missing pidfd, incomplete identity, stale start time, foreign argv, malformed `/proc`, or
  unavailable configured runtime fails closed for signalling and fails loud in the log.
- Verified Codex and Grok orphans, including their Node shebang wrappers, are still reaped.

## Files

- `app/manager.py:70,2004-2035,2308-2340` — frozen `OrphanProcessIdentity`, coherent DB mapping,
  and sweep wiring to the shared verifier.
- `app/backend_jsonrpc.py:341-486` — configured-path normalization, exact Codex/Grok argv
  predicates, pidfd-before-`/proc` verification, pidfd-only signal, local error containment and
  close-in-`finally`.
- `docs/tasks/258/codex-review-impl.md` — recovered two-round implementation review and attempt
  log.
- `docs/tasks/258/report.md` — this report.

Production diff: `+164/-59` across the two Python files. The code change is isolated in branch
commit `3f4ec459`; it can be reverted as one action. Orchestra's final task merge is squash-based.

## Verification

Phase-3 RED, before implementation:

```text
uv run python -m pytest tests/test_orphan_pid_identity.py tests/test_fd_adopt.py -k 'test_t1_' -q
4 failed, 1 passed, 28 deselected in 6.45s
AssertionError: the first-restart sweep signalled a foreign process through a stale/reused PID
```

Parent rerun after merging the executor commit:

```text
uv run python -m pytest tests/test_orphan_pid_identity.py tests/test_fd_adopt.py -k 'test_t1_' -q
5 passed, 28 deselected in 6.91s

uv run python -m pytest tests/test_orphan_pid_identity.py tests/test_fd_adopt.py -q
33 passed, 1 warning in 28.37s
```

The warning is the pre-existing un-awaited `AsyncMock` warning at `app/manager.py:2233` in
`test_impl_partial_handover_rolls_back_the_stored_descriptor`; the focused command exited 0.
The full repository suite was intentionally not run: the orchestrator forbade it without the
global test lock.

### Mutation evidence

Every mutation started from the green T1 command. Each command printed the unique source marker
as `1` before mutation and again as `1` after `mv` restore plus `touch`; the same T1 command then
returned `5 passed`.

| Broken safety property | Mutated behavior | Required failure |
|---|---|---|
| pidfd-only signal | `pidfd_send_signal` replaced by numeric `os.kill` | 3 failed; `numeric os.kill reopens the PID-reuse race` |
| production wiring | removed `terminate_orphan_process(identity)` call | 3 failed; helper/pidfd was never reached |
| lifetime equality | disabled `actual_start != started_at` refusal | 1 failed; reused PID was signalled |
| exact executable identity | replaced strict normalized equality with runtime substring | 1 failed; `notcodex-helper` was signalled |
| unknown stored start | re-measured a missing start time from the current PID | 1 failed; unknown identity was signalled |
| pidfd ordering | inserted a `/proc/cmdline` read before `pidfd_open` | 1 failed; `pidfd must pin the process before /proc identity is read` |

## Adversarial review

Codex ran two implementation rounds in the delegated Luna worktree. Round 1 found that resolving
both runtime configurations together could make a valid Codex process unverifiable when Grok was
missing; the implementation was changed to isolate resolution per allowed candidate runtime.
Round 2 returned `APPROVED`, quoted the executable line
`except (OSError, ValueError, TypeError): continue`, and found no new bug. The parent verified that
line in the merged file and made no production changes afterward. Full record:
`docs/tasks/258/codex-review-impl.md`.

## Pre-mortem

- **First restart meets a reused foreign PID.** Observable failure would be the real
  `/usr/bin/sleep` fixture exiting with `-15`; the production-path oracle proves it remains alive,
  the FD is swept, pidfd validation was reached, and an ERROR names the refused PID.
- **Safety fix disables legitimate cleanup.** Observable failure would be no signal for matching
  Codex/Grok wrappers; the positive arms prove both receive `SIGTERM` through their pidfds.
- **One corrupt `/proc` record aborts the sweep.** Observable failure would be the later valid
  orphan surviving; the containment arm proves both pidfds close and the later orphan is signalled.
- **A future refactor reopens PID reuse between validation and signal.** Observable failure is a
  `/proc` event before pidfd open or a numeric signal; the ordering and numeric-signal mutations
  both turn the frozen oracle red.
- **A runtime is installed while the other configured binary is absent.** Observable failure
  would be rejection of the installed runtime; the Codex finding was fixed by resolving only the
  candidate runtime inside the loop.

## Breaking changes and follow-up

Breaking changes: none for verified managed runtimes. Deliberate behavior change: an identity that
cannot be proven is logged and left alive instead of being killed by PID alone.

`#237` has no file overlap with the reserved seams and declared the merge order `#258` first,
then rebase/merge `#237`. Its first activation remains blocked on this task being merged and the
named stale/reused-PID oracle being green.
