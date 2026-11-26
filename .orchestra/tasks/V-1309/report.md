# V-1309 / V-772

Suggested import commit title: `V-772 Fix hourly laptop backup catch-up after manifest interruption`.

The hourly lookup walks dated remote archives newest first and skips missing JSON sidecars. The first available manifest supplies the stale-check timestamp. Malformed JSON, invalid timestamps, and non-missing filesystem failures surface. The transfer implementation is unchanged.

The hourly regression runs the real CLI entry point, lookup payload and copy control flow on local fixtures. It verifies manifest-only upload and rename for a checksum-matched archive, both with no completed pair and with a stale older pair. SSH, rsync, archive integrity tools, retention, and the task-store push are simulated for this regression.

Offline run via the provisioned uv: `UV_OFFLINE=1 uv run --frozen python -m pytest tests/test_orchestra_backup.py -q`. Result: 37 passed and 2 failed. Both failures require the missing bundle file `scripts/secret_scan.py`. Repeating with those two tests deselected passed all remaining 37 tests.

The hub copy has no Git metadata. Orchestra must import the edited files and report the resulting commit SHA.
