<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

The 42 green tests are impressively confident that messages never arrive at the wrong millisecond 😏 The pinned diff still has two blocking lifecycle/report-selection bugs.

## Summary

Reviewed exact diff `af592e67...870ee9dd`, only the specified files. Named check passes: `42 passed in 3.52s`. No files edited. Luna review was unavailable; Sol was not invoked.

## Findings

### blocking [P1] — Preserve terminal report/state consistency

**File:** [app/fan_barrier.py:225](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-fan-report/app/fan_barrier.py:225)

When a child is already terminal but another sibling is pending, `f.complete` remains false, so this block rewrites its report path before the idempotence check. A later `failed` or `done` delivery can therefore leave `state=done` while the stored report contains the later conflicting message. Restrict rewrites to the legacy candidate flow and make explicit terminal deliveries idempotent.

### blocking [P1] — Do not release before the final legacy candidate

**File:** [app/fan_barrier.py:225](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-fan-report/app/fan_barrier.py:225)

A legacy message still marks the child terminal immediately. In a one-child fan, or when siblings finish between `Prework` and `DONE`, the first message releases the fan; the subsequent `DONE` no longer finds an active fan and cannot replace the stored path. The manifest consequently stores `Prework`, violating AC1. Legacy candidate collection must remain open until turn completion or otherwise defer release.

## Verdict

❌ Needs work. The named oracle passes, but it does not cover late terminal deliveries or release races; both can produce incorrect durable reports.

## Round (2026-09-04T12:20:55Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

Round 2 earned its keep: one late legacy delivery can still rewrite a report already finalized at turn-end 😏 Both prior blockers are fixed; one new blocking regression remains.

## Summary

Reviewed the exact pinned diff `c444fec2...0f0e8f44`. The named check passes: `44 passed in 4.23s`. No files were edited.

Prior blockers:

- Legacy `Prework` prematurely releasing a one-child fan: **FIXED**.
- Late conflicting explicit terminal replacing the report: **FIXED**.

## Findings

### blocking [P1] — Freeze legacy candidates after turn-end

**File:** [app/fan_barrier.py:225-236](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-fan-report/app/fan_barrier.py:225)

After `record_terminal()` runs, the child has `member_state="done"` while the fan may still have pending siblings and `complete=False`. A late `message_kind=None` delivery enters this new branch, passes `not complete`, and overwrites `report_path` without checking `member_state`. The final manifest can therefore report `state=done` with a late, non-final message body. Candidate writes should be limited to the pre-terminal state.

## Verdict

❌ Needs work. The two Round 1 blockers are resolved, but this new legacy-delivery race can corrupt durable report selection while the fan waits for siblings.

“Durable until the next envelope arrives” is a surprisingly accurate name for the current report file.

## Round (2026-09-04T12:24:04Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

Round 3 finally behaves like a final round: the remaining late-legacy hole is closed 😏 No new bugs found.

## Summary

Reviewed the exact pinned diff `c444fec2...e78a6eb8`. Named suite passes: `45 passed in 5.46s`. No files edited.

Prior blockers:

- Legacy `Prework` releasing a one-child fan early: **FIXED**.
- Late conflicting explicit terminal replacing the report: **FIXED**.
- Late legacy delivery replacing the turn-end report: **FIXED**.

## Findings

None.

Evidence quote: `message if substantive else _report_body(message, state),` — [app/fan_barrier.py:230](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-fan-report/app/fan_barrier.py:230)

## Verdict

✅ Correct. The pinned implementation satisfies the tested legacy, explicit-terminal, final-text, no-report, and post-turn idempotence paths.

This time “final report” actually means final; the pending sibling no longer gets to rewrite its biography.
