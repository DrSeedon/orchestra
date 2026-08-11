## Summary

The durable alert latch is not fully schema-enforced, and the test advertised as concurrent never executes concurrent production calls. I ran all 17 targeted tests:

`17 passed in 8.33s`

## Findings

- **blocking: [app/db.py:367](/home/kesha/orchestra/worktrees/home-kesha-orchestra/quota-policy/app/db.py:367) — The schema does not prevent `alert → ok` via replacement or deletion.**

  The trigger covers only `UPDATE`. Both of these successfully unlatch an alerted window:

  ```sql
  INSERT OR REPLACE INTO quota_alert_state
      (window_id, state, changed_at)
  VALUES (?, 'ok', ?);

  DELETE FROM quota_alert_state WHERE window_id = ?;
  ```

  `INSERT OR REPLACE` deletes the old row before inserting the replacement, so the update trigger never runs. This contradicts the stated schema guarantee.

  Treating deletion as merely a “loud” failure is unsafe reasoning: the duplicate is only loud if delivery succeeds and somebody recognizes it as a duplicate. It can also make persisted state falsely claim the window never alerted. If deletion/replacement is within the threat model, add a `BEFORE DELETE` trigger. Administrative `DROP TABLE`, table rebuilds, and disabling constraints cannot realistically be defended against by this schema and should be explicitly excluded from the guarantee.

- **blocking: [tests/test_quota_alert_state.py:105](/home/kesha/orchestra/worktrees/home-kesha-orchestra/quota-policy/tests/test_quota_alert_state.py:105) — The concurrency test is sequential and duplicates the implementation instead of testing it.**

  Each connection completes and closes before the next begins. Worse, the test executes its own copied UPSERT; `alert_state_advance()` is called only after the row is already latched.

  Fifth surviving mutation: replace `alert_state_advance()` with a non-atomic `SELECT` followed by `INSERT`/`UPDATE`. All current tests, including this alleged concurrency test, can still pass.

  The missing test should start two threads or processes behind a barrier, have both call the public `alert_state_advance(WINDOW, ...)`, and assert exactly one `True`, one `False`, no exception, and one persisted row.

- **blocking: [app/db.py:2067](/home/kesha/orchestra/worktrees/home-kesha-orchestra/quota-policy/app/db.py:2067) — `silence_observe()` can return `True` twice for one silence episode.**

  The `SELECT notified_at` and unconditional `UPDATE` are separate statements. Two callers can both read `notified_at IS NULL`, then both update it and return `True`. The initial-row path has a related race where two callers can both observe no row and one receives a uniqueness error.

  Make notification acquisition a conditional write—such as `UPDATE ... WHERE notified_at IS NULL`—and return `cursor.rowcount == 1`; initialize the singleton with an atomic conflict-aware statement. Add a simultaneous-call test asserting exactly one notification winner.

- **suggestion: [app/db.py:2041](/home/kesha/orchestra/worktrees/home-kesha-orchestra/quota-policy/app/db.py:2041) — Stale selection and discard are not one atomic decision.**

  A delivery can be recorded between the `SELECT` and `executemany`. The function then sets both `delivered_at` and `discarded_at` and returns that window as abandoned even though it was delivered. This does not drop or resurrect an alert, but it makes the promised logging evidence false.

  Preserve the predicates in the `UPDATE` and derive returned IDs from rows actually changed, ideally with `UPDATE ... RETURNING window_id`.

## Verdict

Changes requested. The ordinary single-writer path works and the targeted suite passes, but the claimed schema ratchet has a replacement/delete bypass, while both concurrency guarantees lack genuine concurrent tests.

## Round (2026-08-11T11:28:52Z)

## Re-review status

- **FIXED** — Replacement/delete bypasses are covered for the tested `alert → ok` paths by the three triggers.
- **FIXED** — The concurrency test now races the public `alert_state_advance()` function and verifies persisted state.
- **FIXED** — Silence notification is acquired through conditional writes, producing one winner under the tested race.
- **FIXED** — Stale selection and marking are now one atomic `UPDATE ... RETURNING` statement.

## New findings

- **blocking: [app/db.py:367](/home/kesha/orchestra/worktrees/home-kesha-orchestra/quota-policy/app/db.py:367) — Updating `window_id` bypasses the ratchet and unlatches the original window.**

  This requires neither deletion nor a state downgrade:

  ```sql
  UPDATE quota_alert_state
  SET window_id = 'different-window'
  WHERE window_id = ? AND state = 'alert';
  ```

  The row remains `alert`, so none of the three triggers rejects it, but the original window is now unlatched and `alert_state_advance(original_window)` wins again. `UPDATE OR REPLACE` can additionally destroy a conflicting destination row while recursive delete triggers are disabled.

  Make `window_id` immutable once the row is alerted, and add a direct-SQL test that attempts to rename an alerted row.

- **blocking: [app/db.py:367](/home/kesha/orchestra/worktrees/home-kesha-orchestra/quota-policy/app/db.py:367) — Delivery state remains freely reversible through ordinary UPDATE/UPSERT paths.**

  The documented residual hole is broader than `INSERT OR REPLACE ... 'alert'`:

  ```sql
  UPDATE quota_alert_state
  SET delivered_at = NULL, discarded_at = NULL
  WHERE window_id = ?;
  ```

  An UPSERT whose conflict branch performs the same update also works. `alert_pending()` then resurrects a delivered or discarded alert and permits a duplicate message. Since delivery durability is part of this table’s purpose, protect non-NULL `delivered_at` and `discarded_at` from returning to NULL and test both reversals directly.

- **suggestion: [app/db.py:2110](/home/kesha/orchestra/worktrees/home-kesha-orchestra/quota-policy/app/db.py:2110) — The exact grace boundary relies on floating-point Julian-day subtraction.**

  SQLite correctly parsed the supplied ISO format and offsets in my probe, including fractional seconds. For the stated timestamp, an exact 1800-second interval evaluated as `1800.00001341105`, so it fired. The calculation nevertheless has small date-dependent floating error and could evaluate just below the threshold, delaying notification by one poll.

  Add the missing exact-boundary test. Comparing Julian times against `grace_seconds / 86400.0` still uses floating point; integer Unix seconds via `unixepoch(..., 'subsec')`, or an explicitly tolerated epsilon, makes the intended inclusive boundary clearer.

## Verdict

Changes requested: concurrency and atomic discard are fixed, and `julianday` reliably parses the actual ISO representation. The schema guarantee still has two ordinary SQL bypasses that can unlatch a window or resurrect delivery.

## Round 2

I ran the current suite: `21 passed in 8.74s`.

Verbatim current line:

> `-- `INSERT OR REPLACE ... 'alert'` пройдёт и обнулит `delivered_at`, то есть

## Round (2026-08-11T11:36:05Z)

## Re-review status

- **PARTIALLY FIXED** — Direct `UPDATE→ok`, `DELETE`, and `INSERT OR REPLACE→ok` are blocked, but `UPDATE OR REPLACE` still bypasses the ratchet.
- **FIXED** — Concurrent advance now races the public function and verifies one persisted winner.
- **FIXED** — Silence acquisition uses atomic conditional writes and concurrent tests.
- **FIXED** — Stale discard is one atomic `UPDATE ... RETURNING`.
- **PARTIALLY FIXED** — Direct renaming of an alerted row is blocked, but renaming an `ok` row with `UPDATE OR REPLACE` can replace an alerted destination.
- **FIXED** — Non-NULL delivery/discard markers cannot be reset through ordinary UPDATE or UPSERT conflict updates.
- **FIXED** — UTC normalization plus exact ISO comparison handles inclusive boundaries, fractions, and mixed offsets without floating-point arithmetic.

## New findings

- **blocking: [app/db.py:393](/home/kesha/orchestra/worktrees/home-kesha-orchestra/quota-policy/app/db.py:393) — The stated guarantee is still false: `UPDATE OR REPLACE` can replace an alerted row with an `ok` row.**

  I reproduced this exact sequence with `recursive_triggers=0`:

  ```sql
  INSERT INTO quota_alert_state
      VALUES ('A', 'alert', 't', 'delivered', NULL);
  INSERT INTO quota_alert_state
      VALUES ('B', 'ok', 't', NULL, NULL);

  UPDATE OR REPLACE quota_alert_state
  SET window_id = 'A'
  WHERE window_id = 'B';
  ```

  Result:

  ```text
  [('A', 'ok', None)]
  ```

  The source row is `ok`, so the immutable-window trigger does not fire. Conflict resolution silently deletes alerted row `A`, including its delivery record, then renames `B` to `A`. Neither the delete trigger nor the BEFORE INSERT trigger runs.

  Therefore the comment’s exclusions are incomplete: ordinary SQL can still downgrade, replace, and clear the delivery record without using `INSERT OR REPLACE ... 'alert'`.

## Verdict

Changes requested. The concurrency, silence, boundary, direct rename, and direct delivery-reset fixes hold, and `29 passed in 12.73s`. The remaining `UPDATE OR REPLACE` path contradicts the schema guarantee.

## Round 3

Verbatim current line:

> `# доставка могла состояться, и тогда мы пометили бы её же как отброшенную и написали`
