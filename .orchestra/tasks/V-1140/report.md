# V-1140 — flaky `test_graceful_restart_leaves_run_alive_...` (CI red on main)

## Cause: test race, not a production defect
`BgJobManager._adopt_run` order: wait for leader exit -> read rc/output -> `_finish_run` -> `_trigger`
(`bg_finish_trigger` persists status `triggered`, after delivery) -> `finally`: `_stop_progress`,
`await _reap_orphan_run(process)`, `_unlink_run_files(process)`.
Test helper `_settled` polls only `status != "active"`, so it can return after persistence/delivery but
before the awaited reap and unlink in `finally` -> `assert not Path(out).exists()` sees the file (`True`).
Persisting/delivering before cleanup is the data-loss-safe order (files are the recovery source until
the result is stored), so production ordering was left unchanged.

## Fix (test only): `tests/test_bg_run_adoption_919.py`
After `restore_from_db()` the test captures the adopting task (`new._tasks[job_id]`) and, after
`_settled`, awaits that task (`asyncio.wait({task}, timeout=30)` as a completion barrier with a hang
guard, then `await task`). The cleanup assertion is unchanged and now runs after the runner really finished.
No sleeps, retries, skips, or weakened assertions. No production, CHANGELOG, or new-test changes.

## Verification (uv 0.11.28, `--frozen`)
- `tests/test_bg_run_adoption_919.py`: 5 passed.
- Target test repeated 7 more times: all passed.
- Mutation: replaced `_unlink_run_files(process)` in `_adopt_run`'s `finally` with `pass` ->
  target test fails on `assert not Path(...["out"]).exists()`; production file restored afterwards.
- Not run: the 15-iteration CI-load stress and the full suite; I did not reproduce the original race
  before the fix (it is timing-dependent; the cause is from code ordering plus the CI assertion).

Files changed: `tests/test_bg_run_adoption_919.py` only.
