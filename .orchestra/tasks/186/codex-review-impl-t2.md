## Summary

Sighted review completed. I ran 59 targeted tests:

`59 passed in 10.17s`

The normal reset, gaps, rebound above the old value, first-row-low, window boundaries, honest zero handling, and `as_utc` import direction are sound. One edge case can still permanently suppress the warning.

## Findings

blocking: [app/db.py:1920](/home/kesha/orchestra/worktrees/home-kesha-orchestra/quota-policy/app/db.py:1920) — Reset detection only compares adjacent snapshots. A cumulative decline split into sub-5 pp steps is missed. For example, after a valid baseline of 40: `40 → 44 → 41 → 38`. Neither decline reaches 5 pp, so the query keeps 40 as the baseline; `weekly_runway(utilization=38, window_start_pct=40)` then returns `no_data`. Further sub-threshold decline keeps it there, silently disabling warnings indefinitely. Gaps do not inherently break detection because adjacent usable rows are still compared, and a detected reset followed by a rise above the old value remains correctly anchored. The dangerous case is cumulative decline relative to the segment’s high-water mark. Compare the current value with the running maximum, or otherwise explicitly detect cumulative decline. Add an end-to-end multi-poll test whose current utilization falls below the retained baseline through several individually sub-threshold drops.

suggestion: [app/db.py:1911](/home/kesha/orchestra/worktrees/home-kesha-orchestra/quota-policy/app/db.py:1911) — Rows sharing a timestamp have undefined relative order because the query orders only by `ts`. A mutation from `ORDER BY ts ASC` to `ORDER BY ts ASC, id DESC` survives the current suite, yet can reverse `60 → 0` into `0 → 60` and miss the reset. Use `ORDER BY ts ASC, id ASC` to preserve write order and add a test inserting two different percentages at the identical timestamp. This is the requested fourth surviving mutation.

## Verdict

Changes requested: one blocking correctness issue.

The seven-day boundary is appropriate for a nominal seven-day window; account-level re-anchoring is handled by the segment scan, subject to the cumulative-drop bug above. Production writes `ts` through `datetime.now(timezone.utc).isoformat()`, so they are UTC, but they are not guaranteed to be 32 characters—`isoformat()` omits fractional seconds when microseconds are zero. Omitted microseconds do not break ordering with the same `+00:00` offset; a different UTC offset would break the SQL string-order assumption.

Publishing `as_utc` is acceptable. `app.quota_runway` does not import `app.db`, and the local import avoids a cycle and adds no meaningful import-time cost.

## Round (2026-08-11T11:10:11Z)

## Re-review status

- FIXED — cumulative sub-threshold declines now cannot leave `window_start_pct` above the latest value; the running maximum detects accumulated drops, while the segment minimum closes the remaining `<5 pp` case.
- FIXED — `ORDER BY ts ASC, id ASC` makes equal-timestamp processing deterministic, and the revised fixture genuinely fails under `id DESC`.

## New findings

suggestion: [app/db.py:1940](/home/kesha/orchestra/worktrees/home-kesha-orchestra/quota-policy/app/db.py:1940) — `min(segment)` compares `(pct, ts)` tuples, so repeated minimum percentages select the earliest timestamp. Sequence `0@t0 → 4@t8 → 0@t9 → 10@t19` remains one segment because the drop is only 4 pp; the returned baseline is `0@t0`, producing `10/19` instead of `10/10` from the most recent zero and potentially missing an alert. This is the mirror risk requested: the percentage is safe, but its timestamp can make pace too low. The code needs an explicit policy backed by measurement: if a return to the same minimum represents erased usage, select the latest minimum; if sub-threshold declines are intentionally treated as noise, document that earliest-minimum averaging is accepted. Add a test with the same minimum occurring before and after positive utilization.

suggestion: [docs/tasks/186/plan.md:268](/home/kesha/orchestra/worktrees/home-kesha-orchestra/quota-policy/docs/tasks/186/plan.md:268) — T2 still says segment boundaries compare against the previous usable snapshot and never records the minimum-baseline rule. The implementation now has a materially different algorithm, so the ticket’s acceptance contract and code disagree.

## Verdict

The two round-one findings are fixed. No blocking defect found, but the equal-minimum timestamp policy should be resolved before wiring T4 because it can materially understate pace.

## Round 2

Targeted result: `62 passed in 10.53s`

Verbatim current line from `app/db.py`:

`#     невозможным главный отказ: окажись база выше текущего процента, `weekly_runway``
