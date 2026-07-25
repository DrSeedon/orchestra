# Retro — codex-sleep (Phase 1 research)

## Metrics

- Tool calls: 89 logged | Retries: 1 Codex review after timeout; 1 corrected
  diagnostic SQL query | Turns: 3 | Files: 4 research artifacts
- Codex: first pass timed out at 10 minutes with no artifact; bounded resumed pass
  approved with non-blocking qualifications
- Tests: research-data checks passed (`74` rows, `1,953` seconds,
  `62 + 3 + 9`; `git diff --check`)
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

## What went well (keep doing)

- The resumed Codex pass was explicitly bounded to five claims and completed;
  it independently recomputed every aggregate and exposed two real
  qualifications without finding a blocking error.
- Preserving the complete 74-row annotation converted a manual classification
  into a directly auditable artifact.

## Proposed changes (Tier-2 — NOT applied, awaiting approval)

| Target | Change | Evidence | Status |
|---|---|---|---|
| `codex-debate` skill | For database-heavy research, bound the first review to named claims, a frozen dataset, and a word limit unless independent re-analysis is explicitly required. | One 10-minute timeout followed by one successful bounded retry; n=1 | logged, not promoted |

## Written to worker memory (Tier-1 — applied)

- none; the observation is useful but still n=1
