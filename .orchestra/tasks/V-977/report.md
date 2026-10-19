# V-977: update the turn usage mock contract after V-975

Main CI run `39238319699` failed in shard 3 with 916 passed, 1 failed, and 1 skipped. Its full captured log is preserved in [`main-ci-39238319699.log`](main-ci-39238319699.log).

## Cause and fix

`V-975` added optional `provider_source_records` to `db.turn_usage_add` and `TurnManager.handle_turn_end` forwards `meta.get("provider_source_records")`. This test emits a Claude `turn_end` without that metadata, so the actual call correctly includes `provider_source_records=None`. The `MagicMock.assert_called_once_with` expected-call contract had not been updated. I added that keyword with the expected `None` value to `test_turn_end_persists_normalized_structured_usage`; production behavior is unchanged. Existing positive persistence coverage for non-empty OpenRouter source records remains in `tests/test_openrouter_usage.py`.

The captured failing CI run assigned `tests/test_session.py` to shard 3. V-976 added `tests/test_harness_vision.py` earlier in the sorted inventory; the current six-way workflow mapping now assigns `tests/test_session.py` to shard 4. I canceled an initial current-inventory shard-3 run at 34% when checking the mapping; its partial output is preserved in [`shard-3-after.log`](shard-3-after.log) and is not counted as a test result. The complete shard-4 run uses the current main inventory.

## Verification

- Before the test update, the exact target failed with an assertion mismatch: the actual mock call included `provider_source_records=None`; captured in [`focused-before.log`](focused-before.log).
- After the update, `uv run --frozen python -m pytest 'tests/test_session.py::TestRateLimitClassification::test_turn_end_persists_normalized_structured_usage' -q -n 0` — 1 passed; captured in [`focused-after.log`](focused-after.log).
- Current mapped unit shard 4 (52 files) — 756 passed, 4 skipped in 47.89 s; captured in [`shard-4-after.log`](shard-4-after.log). The four skips are ownership checks requiring passwordless sudo, unavailable in this environment.
- Absolute imported `app` path: `/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-dashboard/app/__init__.py`.
- All five captured log files were scanned for common API-key/token forms (`sk-…`, GitHub token prefixes, bearer tokens, and AWS access-key IDs); no matches.

This is a test-only update. No production service, live database, or provider CLI was used; no CHANGELOG entry was needed.
