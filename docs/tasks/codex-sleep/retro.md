# Retro — codex-sleep

## Metrics

- Tool calls: 158 logged | Retries: 4 review retries/resumes; 1 corrected
  diagnostic SQL query | Turns/wake-ups: 14 | Files: 14 task-wide
- Codex: research approved with qualifications; plan approved after 3 rounds
  and 2 resolved blockers; implementation approved after 2 infrastructure
  failures and 1 bounded retry
- Tests: affected suite `95 passed`; full suite stopped at unrelated failures
  after `343 passed`, then `579 passed, 20 skipped` without frontend
- User corrections this task: 0

## What went wrong (signal → root cause)

- **Signal:** The first Codex research review timed out after 10 minutes, scanned
  unrelated historical logs, and wrote no output artifact. **Root cause:** The
  adversarial prompt allowed an open-ended independent investigation of a large
  live database instead of bounding review to the frozen snapshot, report, and
  five load-bearing claims. **Category:** process.
- **Signal:** A diagnostic query failed with `no such column: turn_count`.
  **Root cause:** The query assumed a session metric column instead of checking
  the local schema first; the actual column is `total_turns`. **Category:**
  correctness.
- **Signal:** Plan review Round 1 found that the per-session merge lock did not
  exclude a worker from starting a new turn. **Root cause:** The first design
  treated operation serialization and worker lifecycle exclusion as the same
  concern; `send()` uses `_lifecycle_lock`, not the merge/switch lock.
  **Category:** correctness.
- **Signal:** Plan review Round 2 found that the lifecycle critical section
  ended before the optional `next_task_id` switch. **Root cause:** The atomic
  operation was scoped as “merge” instead of the endpoint's full
  merge-persist-switch state transition. **Category:** correctness.
- **Signal:** The first implementation review failed on a refused ChatGPT
  websocket and the retry timed out after exploring unrelated session
  internals. **Root cause:** One external transport failure plus an over-broad
  diff review on a concurrency change; the bounded exact-hunk review completed.
  **Category:** process.
- **Signal:** Repository-wide tests reproduced a live-SSE frontend fixture
  failure and a missing-`bg_jobs` test-schema failure. **Root cause:** Both tests
  depend on mutable external/test-database state outside this diff; isolated
  reruns reproduced them. **Category:** scope.

## What went well (keep doing)

- The resumed Codex pass was explicitly bounded to five claims and completed;
  it independently recomputed every aggregate and exposed two real
  qualifications without finding a blocking error.
- Preserving the complete 74-row annotation converted a manual classification
  into a directly auditable artifact.
- Three-round plan debate caught both lifecycle boundaries before code was
  committed, and the resulting wake-exclusion endpoint test passed locally.
- The affected 95-test suite stayed green while the two repository failures
  were isolated and recorded rather than mistaken for regressions.

## Proposed changes (Tier-2 — NOT applied, awaiting approval)

| Target | Change | Evidence | Status |
|---|---|---|---|
| `codex-debate` skill | Bound research and concurrency reviews to named claims, exact files/hunks, and a word limit before allowing broad exploration. | Two separate 10-minute over-broad timeouts in one task; bounded retries completed | promote |

## Written to worker memory (Tier-1 — applied)

- none; the observation is useful but still n=1
