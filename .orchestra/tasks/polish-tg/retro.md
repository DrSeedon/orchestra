# Retro — polish-tg (Telegram delivery reliability)

## Metrics

- Tool calls: more than 50; task spanned Phase 1–3 and several background resumptions.
- Codex infrastructure failures: 4 (two plan timeouts, one implementation transport failure,
  one final implementation timeout).
- Implementation diff before final review artifacts: 5 files, +3163/−224.
- Codex: plan `APPROVED` after revision; implementation verdict unavailable.
- Tests: 6 original defect groups red before fixes; focused `97 passed`; repository
  `888 passed, 20 skipped`.
- User/orchestrator corrections: 1 process clarification (stop retrying after three equivalent
  infrastructure failures; self-review and preserve the deferred review obligation).

## What went wrong (signal → root cause)

- **Signal:** the first plan review found two blockers: a bounded queue with unbounded blocked
  producers and a media generation identity reusable after state reset. **Root cause:** the
  initial design bounded stored entries but did not model owners waiting outside the container,
  and treated a resettable counter/state object as a process-lifetime identity. **Category:**
  correctness.
- **Signal:** the pre-change focused suite reported 56 passing tests while all six production
  defects remained reproducible. **Root cause:** tests covered happy-path formatting and API
  retries but not scheduler fairness, queue saturation, lifecycle ownership, or cross-generation
  completion. **Category:** process.
- **Signal:** after the planned implementation reached `879 passed`, the final self-review still
  found nine edge cases, including ambiguous create cancellation, stop/rename races, stale
  coalesced fallback, and incomplete flood-loss accounting. **Root cause:** the ticket tests proved
  each primary defect but did not initially compose error classes with lifecycle transitions
  (network error × non-idempotent create, coalesce × entity rejection, stop × first admission).
  **Category:** correctness.
- **Signal:** lifecycle tests initially exercised the autouse-mocked `stop_bridge` instead of the
  production function. **Root cause:** a global test fixture replaced the public symbol, so tests
  written against the module attribute did not own the lifecycle code they claimed to verify.
  Importing `_real_stop_bridge` before fixture mutation corrected the harness. **Category:**
  process.
- **Signal:** three Codex jobs timed out without a verdict and one failed both transports; the
  final job spent its budget running tests after the caller had supplied focused and full-suite
  evidence. **Root cause:** the review runner did not reserve time to emit findings/verdict before
  optional repository-wide validation and did not fail fast on repeated infrastructure
  unavailability. **Category:** process.

## What went well (keep doing)

- Codex plan dissent was resolved before implementation; its two blockers directly became bounded
  admission and process-lifetime opaque media tokens.
- Every confirmed production defect and every final self-review finding received a failing test
  before its fix. The final nine tests raised the focused suite from 88 to 97.
- Per-slice commits preserved all completed work across background failures, and the final
  repository suite passed without restarting or contacting production Telegram.

## Proposed changes (Tier-2 — NOT applied, awaiting approval)

| Target | Change | Evidence | Status |
|---|---|---|---|
| `codex_review` runner/prompt | Emit code findings and a provisional verdict before running optional full-suite tests; honor caller-supplied test evidence unless a specific falsification requires rerun. | Three review timeouts in one task, including the final job starting the full suite after `88 passed` focused evidence. | promote |
| `pipelines/default/prompts/skills/codex-debate` | After three equivalent infrastructure failures, stop retries, record the missing verdict, run adversarial self-review, and retry only once on the materially different final artifact. | Orchestrator correction plus repeated plan/implementation failures. | promote |

## Written to worker memory (Tier-1 — applied)

- none; the actionable lessons are task-specific or proposed fleet-wide above.
