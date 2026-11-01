# V-1183 — Codex reset weekly threshold

## Change

`scripts/codex_reset.py` now uses `WEEKLY_RESET_THRESHOLD = 99`; the weekly branch remains inclusive (`used >= threshold`). The independently approved expiry branch remains strict (`expiresAt - now() < 9 minutes`). Credit availability/order, weekly-window identification, stable `orchestra-<creditid>` idempotency key, RPC sequence, failure behavior, and the five-minute recurring schedule are unchanged.

## Offline verification

`tests/test_codex_reset.py` drives the imported script with a synthetic fake RPC. For both primary and secondary weekly-window layouts, it asserts no consume at 95% and 98%, and a consume at 99% and 100%. Existing synthetic cases still assert redemption just under nine minutes before expiry, and no redemption at exactly nine minutes or later. The fake only records the consume request in memory; tests do not launch Codex, read account data, contact the provider, call a live consume endpoint, or spend a credit.

Command and result: `uv run --frozen python -m pytest tests/test_codex_reset.py -q` — **68 passed**. The first run had 11 failures because several existing synthetic success fixtures implicitly defaulted to the old 95% threshold; those defaults now model 99%, and the second run passed. No tests were skipped.

## Active automation and activation

Read-only Orchestra job listing identified active job `bg-7d176f2fd9`, type `cron_command`, schedule `*/5 * * * *` UTC. It invokes:

```text
cd /tmp && timeout 60 python3 -I /home/kesha/.cache/canary-scripts/codex_reset.py 2>&1
```

The tracked source is `/home/kesha/orchestra/scripts/codex_reset.py`; the job executes the separate live copy `/home/kesha/.cache/canary-scripts/codex_reset.py`. The two files had identical SHA-256 before this change (`9cb70a774a8205945f0a3ae71c8ed82ca7a10ba36f431c9f48591e38d82f70c0`), confirming the active copy is not a symlink and will not automatically inherit a source edit. No cron job, live copy, Orchestra process, or other job was changed.

After this branch is merged into `main`, activate as user `kesha` by atomically replacing the live copy from the merged source on the same filesystem. This leaves `bg-7d176f2fd9` and its schedule untouched:

```sh
python3 - <<'PY'
from pathlib import Path
import os
import stat
import tempfile

source = Path('/home/kesha/orchestra/scripts/codex_reset.py')
live = Path('/home/kesha/.cache/canary-scripts/codex_reset.py')
payload = source.read_bytes()
mode = stat.S_IMODE(live.stat().st_mode)
fd, temporary = tempfile.mkstemp(prefix=f'.{live.name}.', dir=live.parent)
try:
    with os.fdopen(fd, 'wb') as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(temporary, mode)
    os.replace(temporary, live)
    directory_fd = os.open(live.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
finally:
    if os.path.exists(temporary):
        os.unlink(temporary)
PY
sha256sum /home/kesha/orchestra/scripts/codex_reset.py /home/kesha/.cache/canary-scripts/codex_reset.py
```

Require identical post-copy hashes, then confirm the live file contains `WEEKLY_RESET_THRESHOLD = 99`. The copy operation does not run Codex or consume a credit.

## Activation result — 2026-11-01 07:38 UTC

After merge, verified `/home/kesha/orchestra` was clean `main` at `aceae9016c8585972eeae0eb24459848cb6126a5`. Its source hash was `d0edd16f0b0e3dd2ff2dc8d29517b909a8c81bd291b08aa2f2df50a5f0e3e200`. Before replacement, the live file was owned by `kesha:kesha`, mode `0644`, and had the expected old hash `9cb70a774a8205945f0a3ae71c8ed82ca7a10ba36f431c9f48591e38d82f70c0`. The atomic same-directory replacement succeeded. Afterwards, the source and live-copy hashes both equal `d0edd16f0b0e3dd2ff2dc8d29517b909a8c81bd291b08aa2f2df50a5f0e3e200`; the live file remains `kesha:kesha`, mode `0644`, and contains `WEEKLY_RESET_THRESHOLD = 99` and `used >= WEEKLY_RESET_THRESHOLD`.

Read-only job listing after activation still showed `bg-7d176f2fd9` active at `*/5 * * * *` UTC, with the same command path `/home/kesha/.cache/canary-scripts/codex_reset.py`. No job or schedule was changed. The script was not run: no consume, inference, account read, or credit spend occurred. Orchestra was not restarted.

## Limitations

The tests establish policy behavior through the script's fake RPC, not against Codex app-server or a real account. Activation confirms file contents and job command configuration; no live RPC was used to test the new threshold. No inference or credit consumption was performed.
