# #93 — atomic spawn/switch/task lifecycle

## Delivered

- **T1 — transactional Git mutations.** `create/merge/switch/remove` share one stable
  repo flock stored in the Git common directory. Switch rollback is CAS-based and
  fail-closed; merge results expose typed commit-point snapshots, exact conflict paths,
  and the public non-reentrant `repo_mutation_lock()` contract required by #115.
- **T2 — pinned merge/task identity.** `execute_merge_session()` resolves the exact
  session id/name/scope/branch/head once, owns `session → lifecycle → repo`, and reports
  post-merge switch/task failures as partial results. Task lookup and CAS updates are
  project-scoped.
- **T3 — atomic spawn publication.** A worker is invisible until worktree preparation and
  runtime start finish. Final DB publication atomically replaces archived history; task
  mutation follows publication. Repeated cancellation cannot penetrate owned preparation,
  compensation, or finalization tasks.
- **T4 — linearizable fresh delivery.** HTTP, Telegram, background-job, limit-wake,
  auto-report, restart-notice, and system-route deliveries converge on
  `SessionManager.send()`. It rechecks `needs_switch` under the session lock, permits only
  IDLE auto-switch, preserves RUNNING mid-turn delivery, and shields through backend
  acceptance. Git exceptions always carry a non-empty error and preserve quarantine.

## Lock order

The only acquisition order introduced by #93 is:

1. manager session lock;
2. loaded `AgentSession._lifecycle_lock`;
3. stable repository flock inside the synchronous workspace helper.

There is no reverse edge: workspace helpers never acquire manager/lifecycle locks,
`AgentSession` never acquires the manager lock, and `SessionManager.send()` releases the
lifecycle lock after auto-switch before calling `AgentSession.send()` (which may acquire it
again while the manager lock remains held). External reconcile code may acquire
`repo_mutation_lock()` for its own transaction but must never wrap a mutation helper.

## Verification

- Final full suite:
  `UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest -x -q` →
  **1388 passed, 7 skipped in 113.63s** (`/tmp/pytest-93-final.log`).
- T4 focused manager gate after the Codex diagnostic fix: **20 passed**.
- T4 integration set (manager/API/bg/limit/TG): **419 passed** before the final diagnostic
  normalization; the final full suite covers the updated code.
- Live DB was opened read-only: 383 sessions, 81 non-archived, 9 active
  `needs_switch=true`. All 9 were IDLE and had an existing Git worktree plus a resolvable
  persisted base; none were WAITING/RUNNING or missing a worktree.
- Codex implementation review ran in two rounds. Round 1 found only empty Git-exception
  diagnostics; the fix added exception-class fallback and actual-state quarantine. Round 2:
  **PASS, confidence 0.97**, no deadlock, cancellation, quarantine, or false-delivery finding.
  See `docs/tasks/93/codex-review-t4.md`.

The first final-suite attempt stopped on an independently changing pipeline ACL. The
accepted orphan-guard test fix from main was applied only for validation and removed from
the T4 diff before commit.

## Compatibility and remaining risk

- No MCP request/response value changed; `app/mcp_stdio.py` is untouched, so there is no
  rolling MCP↔route split-brain window.
- The Python server was not restarted. Runtime acceptance across the live fleet therefore
  waits for the later coordinated restart.
- `WAITING + needs_switch` now fails explicitly instead of starting Git or a backend turn.
  This is an intentional fail-closed behavior change.
