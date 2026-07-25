# Plan — stop external-state `sleep` polling

## Scope

Implement the approved B → A → C sequence:

1. make `codex_review` require the caller to end its turn;
2. apply the same external-wait rule to every role through the shared base prompt;
3. absorb the short `RUNNING → IDLE` merge transition inside the server.

No command hook or global `sleep` ban will be added. Sleeps used by tests,
rate-limited scripts, and bounded restart verification remain legal.

## Design

- Keep the `codex_review` background-job lifecycle unchanged; only replace the
  ambiguous return instruction and lock its contract with a focused test.
- Put one concise rule in the existing `<background-jobs>` block in `base.md`;
  verify all four default roles receive it.
- When merge arrives during the worker's turn-end transition, wait
  asynchronously for up to 2 seconds, checking every 50 ms, before returning
  the existing running-worker error. After the grace wait, acquire the loaded
  worker's lifecycle lock, recheck status, and hold it through merge. The
  per-session lock still serializes merge/switch; the lifecycle lock prevents an
  idle worker from starting a new turn between the status check and completion
  of all loaded-session persistence plus the optional `next_task_id` branch
  switch. Long-running workers are still rejected after the grace period.

## Files

- `app/mcp_stdio.py`
- `pipelines/default/prompts/base.md`
- `app/routes/sessions.py`
- `tests/test_mcp_codex_review.py`
- `tests/test_default_pipeline.py`
- `tests/test_api.py`

## Tickets

### T1 — B: require end-turn after `codex_review`

- Files: `app/mcp_stdio.py`, `tests/test_mcp_codex_review.py`
- AC:
  - The successful start response says `END YOUR TURN NOW`.
  - It says Orchestra wakes the agent when the job completes.
  - It contains neither `do NOT poll` nor `just wait`.
  - Existing review job/session behavior is unchanged.
- blocked-by: none

### T2 — A: prohibit external waiting in every role

- Files: `pipelines/default/prompts/base.md`,
  `tests/test_default_pipeline.py`
- AC:
  - Every default role prompt forbids sleeping/polling for a background job,
    review, or another agent.
  - The rule requires ending the turn and states that Orchestra resumes it.
  - The rule preserves delays used by tests and bounded restart verification.
- blocked-by: T1

### T3 — C: absorb the merge turn-end race

- Files: `app/routes/sessions.py`, `tests/test_api.py`
- AC:
  - A merge requested while a loaded worker changes from running to idle during
    the grace period proceeds in the same request.
  - A worker that stays running is rejected after the bounded grace period.
  - Timeout and polling interval are module constants; tests replace the sleep
    function so they do not consume real wall-clock time.
  - The merge remains serialized by the existing per-session lock.
  - The loaded worker lifecycle lock is held from the final idle recheck through
    merge, loaded-session persistence, and the optional `next_task_id` switch,
    preventing a completion notification or other message from starting a new
    turn concurrently. The wake-up exclusion test uses `next_task_id`.
- blocked-by: T2

### T4 — Verify and review

- Files: `docs/tasks/codex-sleep/codex-review-impl.md`,
  `docs/tasks/codex-sleep/report.md`, `docs/tasks/codex-sleep/retro.md`
- AC:
  - Focused tests for all three slices pass with exact counts recorded.
  - The full suite passes.
  - Codex implementation review has no unresolved blocking findings.
- blocked-by: T3

The T4 files are required full-cycle pipeline artifacts, not runtime scope.

## Out of scope

- PreToolUse hooks or permission-level command blocking.
- Changes to legitimate sleeps in tests, deploy scripts, or runtime code.
- General redesign of session status signaling.
