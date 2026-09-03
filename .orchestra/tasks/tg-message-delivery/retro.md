# Retro — tg-message-delivery

## Metrics

- Tool calls: >40 | Retries: 4 (sudo diagnostics, two full-suite environment variants, one Codex session resume) | Turns: 1 | Files: 9
- Codex: 2 blocking findings in Round 1, both fixed; independent Round 2 APPROVED | Tests: 52 focused passed; full suite stopped twice on unrelated failures | User corrections: 0

## What went wrong (signal → root cause)

- **Signal:** Codex Round 1 found that ambiguous failures and entity fallback could bypass the restored interval. **Root cause:** the first implementation accounted for confirmed delivery rather than Bot API request attempts, and treated fallback as formatting internals instead of a second request. **Category:** correctness.
- **Signal:** the exact full-suite command failed after 418 passing tests because `PARENT_NAME` affected `test_list_agents_groups_by_parent`; the clean-environment retry then failed after 557 passing tests because the test DB lacked `bg_jobs`. **Root cause:** repository-wide tests are not hermetic with respect to Orchestra worker environment and background-job schema setup. **Category:** process.
- **Signal:** the shared test lock reports owner `test-sonnet5` since 2026-07-01. **Root cause:** test-lock cleanup does not reliably expire dead owners. **Category:** process.
- **Signal:** persistent Codex resume failed with `no rollout found`. **Root cause:** review-session state was unavailable despite a recorded session ID; an independent second review was required. **Category:** process.

## What went well (keep doing)

- Timing tests failed before each Round 1 fix and passed afterward, proving both rate-accounting findings rather than accepting them on authority.
- The independent Round 2 review reran the focused suite (`52 passed`) and found no remaining blocker.
- Read-only production measurements separated current proxy/topic health from historical sender failures without sending test messages or restarting services.

## Proposed changes (Tier-2 — NOT applied, awaiting approval)

| Target | Change | Evidence | Status |
|---|---|---|---|
| test fixtures | Clear `WORKER_NAME`, `WORKER_ROLE`, and `PARENT_NAME`; initialize the `bg_jobs` schema explicitly | two unrelated full-suite failures in one task, n=1 | logged, not promoted |
| test lock helper | Expire locks whose owner/session is no longer alive | lock held since 2026-07-01 | logged, not promoted |
| Codex review backend | Preserve/resume a recorded rollout or return an actionable recovery path | `thread/resume failed: no rollout found`, n=1 | logged, not promoted |

## Written to worker memory (Tier-1 — applied)

- none; each process signal is n=1 and not yet generalizable.
