# Retro — codex-cache-research (cache indicator and compact architecture)

## Metrics

- Tool calls: 43 before report/commit | Retries: 4 (targeted boundary 1, test-environment isolation 3) | Turns: 1 implementation turn | Files: 13
- Codex: ACK, no high-confidence regressions | Tests: 756 passed, 20 skipped on initialized temp DB | User corrections this phase: 0

## What went wrong (signal → root cause)

- **Signal:** the Claude frontend threshold test returned `warm` instead of expected `cooling` at exactly 48 minutes elapsed. **Root cause:** the test sampled the `12m` boundary, where sub-millisecond timing and `Math.floor` legitimately select either adjacent state. Moving the sample to 49 minutes tests the intended interior state. **Category:** correctness.
- **Signal:** `test_list_agents_groups_by_parent` omitted the orchestrator under the worker's inherited `ORCHESTRA_ROLE=full-cycle`. **Root cause:** the existing test isolated `SCOPE` and `WORKER_NAME` but not the module-level `ROLE` environment input. The test now sets the role explicitly. **Category:** process.
- **Signal:** the default full suite failed in two `tests/test_session.py` turn-end tests with `sqlite3.OperationalError: no such table: bg_jobs`. **Root cause:** those tests mock session persistence but let `bg_manager` query the worktree's stale/uninitialized default DB. A freshly initialized `/tmp` DB produced a complete green run, confirming the cache feature was unrelated. **Category:** process.

## What went well (keep doing)

- Contract-first tests exposed both the missing runtime policy and an exact threshold ambiguity before review.
- A clean temporary DB separated a test-environment failure from feature behavior without changing unrelated production code.
- Codex review found no high-confidence regression after the targeted and full-suite evidence was supplied.

## Proposed changes (Tier-2 — NOT applied, awaiting approval)

None. The stale test DB is a local fixture-isolation issue, not evidence for a fleet-wide prompt or pipeline change.

## Written to worker memory (Tier-1 — applied)

None; the observed failures are task-local and do not justify a persistent worker rule.
