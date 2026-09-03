# #235 partial implementation report

## Implemented

`app/fan_barrier.py` fails open when either fan-barrier table is absent on the
three optional entry paths reached by primary operations:

- `peek_summary()` and `should_buffer()` before a message send;
- `on_child_killed()` before session removal;
- the same `should_buffer()` used before an automatic report.

Only `no such table` for `fan_barriers` or `fan_members` is neutralized. A direct
probe confirmed that `database is locked` still propagates.

## Verification

- Pre-change red: `uv run pytest -q
  tests/test_api.py::test_send_quota_refusal_is_canonical_429` → `1 failed`;
  response was 500 and the cause was `no such table: fan_barriers`.
- Post-change green with no pre-existing default DB: the same command → `1
  passed in 5.42s`.
- Barrier regressions: `uv run pytest -q tests/test_fan_barrier.py
  tests/test_fan_barrier_gates.py tests/test_fan_enable.py` → `38 passed in
  19.24s`.
- Direct probe on an empty-schema DB: `peek_summary() is None`,
  `should_buffer() is False`, `on_child_killed() is False`; unrelated
  `OperationalError("database is locked")` propagated.

### Mutation

After the target was green, `peek_summary()` was changed back to re-raise missing
schema. The mutation marker count was `1`; the target became red with `500 !=
429` and `no such table: fan_barriers`. The file was restored with `mv`, then
`touch`ed; the marker count was `0`, and the green repeat was `1 passed in 5.70s`.

## Review

Codex review produced this exact verdict:

> The guarded call paths fail open only for missing fan-barrier tables while
> re-raising unrelated OperationalError instances. Evidence from the reviewed
> diff: `import sqlite3`.

The quoted line exists in the reviewed diff, so the review meets the project's
evidence criterion. The artifact also records an accounting warning: the Codex
turn reported zero tokens.

## Test isolation follow-up

`tests/conftest.py` now gives every test a temporary Orchestra DB path and wraps
`sqlite3.connect` to reject the resolved production path before the real
connector is called. `tests/test_production_db_isolation.py` checks that the
fixture is autouse, rejects both plain and URI production paths without invoking
the delegate (including SQLite's valid `file://localhost/...` form), and still
delegates a temporary path.

The received target test remains byte-for-byte unchanged. This preserves the
immutable acceptance oracle while supplying its missing isolation globally; it
now passes without creating `data/orchestra.db`.

Additional verification:

- target plus guard tests: `3 passed in 5.14s`, with the default DB absent before
  and after;
- DB and guard subset: `94 passed in 54.04s`;
- three quota-route tests plus guard tests: `5 passed in 5.50s`.

Guard mutation: removing `autouse=True` produced marker count `1` and
`test_production_db_guard_is_autouse` failed on the unwrapped built-in connector;
after `mv` + `touch`, marker count `0` and the test passed. Isolation mutation:
removing the temporary `DB_PATH` assignment produced marker count `1` and the
unchanged target failed `500 != 429` on `test attempted to open production
database`; after `mv` + `touch`, marker count `0` and the target passed without
creating the file.

Codex's test-layer review found one blocking bypass: SQLite accepts
`file://localhost/<absolute path>` but the first URI normalizer treated
`localhost` as part of the filesystem path. The parser now accepts only SQLite's
empty or `localhost` authority and compares the decoded URI path. The new
localhost regression was green, then changing the authority branch back to the
bypass produced marker count `1` and `DID NOT RAISE`; after `mv` + `touch`, marker
count `0` and the test passed again.

Codex re-review verdict, verbatim: `Prior P1 FIXED.` / `New findings: None.` /
`Verdict: APPROVED.` Its evidence line, `assert calls == []`, is present in the
reviewed regression test.
