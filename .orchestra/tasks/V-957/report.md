# V-957: false backup alarm while the laptop sleeps

Cause: `_laptop_tunnel_available()` only did `socket.create_connection(127.0.0.1:2222)`. That port is the VPS end of the reverse SSH
tunnel and stays LISTEN while the laptop sleeps (orchestrator checked: `ss` LISTEN, `ssh -p 2222` → banner timeout), so the probe passed
and the next ssh in `_sync_latest_laptop_backup` raised `BackupError step=laptop` (rc=1) every hour.

Fix: after the TCP check the probe runs `ssh -o BatchMode=yes -o ConnectTimeout=5 ... true` (subprocess timeout 10 s). rc 255 with
a connection-level message (timed out, banner exchange, kex_exchange_identification, refused, reset, closed, no route, unreachable), or
a hung probe → unavailable → step skipped, rc=0. Anything else (e.g. `Permission denied`) counts as reachable, so the following
steps surface it. Cost while asleep: ≤5 s (ConnectTimeout), 10 s hard cap. `--daily` and `--push-task-store` both go through
`_sync_latest_laptop_backup` → same probe.

Tests (`tests/test_orchestra_backup.py`, 17 passed): sleeping laptop behind a listening port (3 stderr variants) and hung probe →
False; reachable and auth failure → True; end-to-end `main()` with banner timeout for `--push-task-store` and `--daily` → rc 0, empty
stderr. Mutation: with the old function restored 6 of the new tests fail. Existing test
`test_incomplete_laptop_upload_emits_backup_failure` (real copy error with reachable laptop → `BACKUP_FAILURE step=laptop`) stays green.
Not run against the real sleeping laptop (no probe of the live tunnel from this task). No restart needed.
