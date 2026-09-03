# Report #226 — Codex turn completion survives unknown cost

## Outcome

An exception in Codex price calculation can no longer suppress the terminal event.
For an unpriced model the backend now emits, in order, a loud `warning` and the
authoritative `turn_end`; token metadata remains attached to that terminal event.
The consumer persists the completed turn with `cost_usd = NULL` and
`cost_unaccounted = 1`, rather than turning an unknown paid amount into `$0.00`.
Priced models retain their prior numeric cost path.

`turn_usage.cost_unaccounted` is an additive
`INTEGER NOT NULL DEFAULT 0` column. Existing rows are deliberately unchanged. Because
the old `cost_usd` column was `NOT NULL`, migration rebuilds only `turn_usage`, preserving
all columns, rows, IDs, unique identity, and its two secondary indexes while relaxing that
constraint.

The terminal status log no longer says `$0.00 turn` for this case. It says
`cost unaccounted for <model>`; the backend also writes
`Codex usage unaccounted: <exception class>: <detail>` to the application journal.

## Frozen RED oracles

The producer oracle was committed first as `fe4882ad`. Before implementation:

```text
FF.                                                                      [100%]
T1: AssertionError: конец хода потерян, пришло: []
T2: StopIteration
T3 priced control: passed
2 failed, 1 passed, 71 deselected
```

The durable consumer oracle was committed first as `4efcd152`. Before its
implementation:

```text
FFF                                                                      [100%]
T4: AssertionError: ожидался NULL, получено 0.0
T5: sqlite3.OperationalError: no such column: cost_unaccounted
T6: IndexError: No item with that key
3 failed, 74 deselected
```

T5 uses `COUNT(cost_usd)`, not only `SUM(cost_usd)`: SQLite gives the same sum for a
mixed sample containing `NULL` and one containing `0.0`. The count distinguishes one
priced observation from two. Its fixture executes exactly one query returning total rows,
priced observations, unaccounted rows, and the sum of known cost.

## Final verification

No full suite was run, per task constraint.

```text
uv run pytest tests/test_backend_codex.py tests/test_turn_usage.py \
  tests/test_codex_review_artifact.py tests/test_usage_analytics.py \
  tests/test_db.py -q
202 passed in 81.75s

uv run pytest tests/test_session.py -q -k 'turn_end or turn_telemetry_failure'
6 passed, 203 deselected in 5.98s
```

The final named producer + consumer oracle is `6 passed, 71 deselected`.

### Mutation checks

Each valid mutation began from green, used a fresh `cp`, printed the marker before the
test, restored with `mv`, ran `touch`, printed the marker after restore, and ended with a
green repeat.

- Throw again before `turn_end`: marker `1 -> 0`; T1/T2 red, priced T3 passed; restored
  `3 passed`.
- Persist `0.0` instead of `NULL`: marker `1 -> 0`; T4 and T5 red, priced T6 passed;
  restored `3 passed`.
- Stop writing `cost_unaccounted`: marker `1 -> 0`; T4 and T5 red, priced T6 passed;
  restored `3 passed`.
- Ignore the producer marker in `handle_turn_end`: marker `1 -> 0`; T4 and T5 red,
  priced T6 passed; restored `3 passed`.

### Migration rehearsal

A `sqlite3.Connection.backup` copy of the live database was migrated twice. Before:
`2,820` `turn_usage` rows, sum `$5,118.16225211`, `cost_usd NOT NULL = 1`. After:
the same `2,820` rows and exact sum, `cost_usd NOT NULL = 0`, historical
`SUM(cost_unaccounted) = 0`, and indexes `idx_turn_usage_session`,
`idx_turn_usage_ts`, and the unique event-id auto-index present. No live database or
service was modified.

### Streamed and final text

An isolated app-server notification probe produced
`['stream', 'text', 'warning', 'turn_end']`. The live delta remained available as
`stream`; the completed agent message remained a persistable `text` event; the unpriced
terminal retained `input_tokens = 1000`. The cost exception therefore does not erase
already streamed text or the final text item.

## Cost/write seam audit

- `app/backend_codex.py::_turn_completed`: fixed. Cost calculation is fail-soft around
  terminal-event construction, and both missing table entries and explicit `None` prices
  are loud configuration errors.
- `app/session_turns.py::handle_turn_end`: fixed. It consumes `cost_unaccounted`, writes
  nullable cost plus the marker, and avoids a false-zero terminal log.
- `app/db.py::turn_usage_add`: fixed. Unknown is stored as SQL `NULL`; priced callers
  retain the prior numeric/default call shape.
- `app/codex_review_artifact.py`: already preserves the paid review artifact before its
  accounting attempt and catches accounting failure with a loud
  `Codex usage unaccounted` warning. Thus this secondary path cannot discard the primary
  review result; its current production model is priced Sol.
- `/api/usage` and dashboard session totals read `sessions.cost_usd`, not nullable
  `turn_usage.cost_usd`. Those values remain numeric and do not crash or format `None`.

## Weekly Codex dollar shift

Historical rows were not rewritten. At the `2026-08-13T04:25Z` read-only snapshot, the
last seven days contained `616` Codex `turn_usage` rows, all `616` with numeric prices,
totaling `$1,077.32322996`; there were zero Spark sessions and zero Spark
`turn_usage` rows. Therefore the stored historical weekly number moves by exactly
**`$0.0000`** after this migration. Previously lost terminal events cannot be reconstructed,
so any historical understatement outside those rows remains unidentifiable. Future
unpriced turns preserve their tokens and explicit unknown state without inventing a dollar
amount.

## Transferred defect — #239

`app/usage_analytics.py` uses `float(row['cost_usd'] or 0)` after `SUM`, and endpoint
`/api/usage/analytics` exposes the result. In an isolated database containing one
unaccounted Spark row, it returned `observed_cost_usd = 0.0` and likewise `0.0` for the
provider, model, agent, and `cost_per_turn`. This is not a `None` formatting crash; it is an
unresolved aggregate-response contract: each grouping needs to distinguish zero priced
observations from a measured zero and decide the denominator for `cost_per_turn`.

That defect was handed off as **#239**. It is not a TODO hidden inside #226, and
`app/usage_analytics.py` was not changed here.

## Codex review

Round 1 was substantive and ran the frozen producer oracle (`3 passed`). Its verbatim
verdict was:

> CHANGES REQUESTED — one blocking false-zero accounting defect remains. Terminal
> delivery and token retention are preserved, but the unpriced turn is still persisted
> and summarized as costing zero.

The finding was accepted and led to the durable consumer oracle, nullable schema,
consumer handling, and migration above. Final re-review is recorded in
`codex-review-impl.md`.

Round 2 ran the complete backend test file (`77 passed in 7.52s`) and quoted an exact
reviewed implementation line that is present in both the supplied diff and `app/db.py`.
Its verbatim verdict was:

> APPROVED — no blockers.

## Breaking / operations

- Breaking API changes: none in #226.
- Existing priced rows and priced-model behavior are unchanged.
- Python code and the database migration take effect only on a later authorized service
  restart; no `systemctl` command was run.
- Full test suite was intentionally not taken.
