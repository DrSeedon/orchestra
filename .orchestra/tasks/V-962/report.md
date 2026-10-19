# V-962: --daily exceeded the 600 s job limit

Cause: `_daily()` = archive creation (02:00→02:05, 2.28 GB) + `_sync_latest_laptop_backup` with an rsync slice `LAPTOP_TRANSFER_SLICE_SECONDS=450` → >600 s, wrapper killed (bg-789f036196, 19.10).

Fix (`scripts/orchestra_backup.py`):
- `_daily()` no longer touches the laptop; the hourly `--push-task-store` copies it (append-verify resume, existing `.partial` is picked up).
- Slice length = min(450, 600 − 90 reserve − elapsed since process start), passed into `_rsync_to_laptop`; under 20 s left → copy deferred silently to next run. Keeps the hourly run inside 600 s even after a slow task-store push.

Tests (`tests/test_orchestra_backup.py`, 23 passed with `-n 0`): `test_daily_never_touches_laptop_so_it_fits_the_job_limit` (red on the old combination: it fails if `--daily` reaches the laptop), `test_transfer_slice_is_cut_to_remaining_job_budget` (elapsed + slice + reserve ≤ 600), `test_copy_defers_when_budget_is_spent`. The old `--daily` incomplete-upload test moved to `--push-task-store`.

Limits: not run against the real laptop. Tradeoff: new archive reaches the laptop up to an hour later. A multi-slice transfer still emits `BACKUP_FAILURE ... incomplete` per slice (existing contract, unchanged). No restart needed.
