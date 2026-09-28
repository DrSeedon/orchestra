# V-647 — read-only detector for recurring errors

## Result

Added `app.error_watch`, a scheduled command with no model calls. It reads `journalctl -u orchestra` and selected errors from the live session log using SQLite URI `mode=ro`; it never writes to that database. Normalized signatures remove logger prefixes, session names, paths, IDs, and numbers. The default window is 168 hours and the repeat threshold is 10. Quota/rate limits, hook policy blocks, expected command termination, external timeouts, and normal listener completion in `IDLE`/`WAITING` are classified as noise. Journal lines for the same logger event are counted once using timestamp, session name, and status. A listener exit reported as `listen task exited unexpectedly while RUNNING` is actionable at threshold 1.

New signals include the signature, count, first and last occurrence, up to two sanitized examples, and any matched task/fix reference. The output is capped at 2,800 characters for `cron_command`. State is stored atomically in `data/error_watch.json`, beside the configured database; this file is git-ignored with `data/`. It stores alert deduplication and fix records. `--dry-run` neither reads nor writes this state file. Post-fix records track task, commit, process start time, and observation window; the detector reports the first recurrence and the final window result. A person closes the incident.

No code repair, task creation, branch, merge, or restart is automated.

## Read-only run against the live data

The live service is `kesha` (PID 2796283 at inspection); `/proc/2796283/environ` reported `ORCHESTRA_DB_PATH=/home/kesha/orchestra/data/orchestra.db`. The database was opened read-only. `journalctl` was readable as the service user. The dry run covered the rolling interval **2026-09-20 12:58 UTC through 2026-09-27 12:58 UTC**.

The scan selected 1,480 journal lines matching the error/warning markers and 1,246 `logs` rows with `tool_is_error=1` or `type='error'`. After signature normalization and journal-pair deduplication, 17 candidate signatures exceeded their threshold. Twelve noise signatures accounted for 802 occurrences: 532 normal per-turn listener completions (`IDLE`/`WAITING`), 161 quota/rate-limit events, 48 hook policy blocks, 32 external timeouts, and 29 expected command terminations. The 532 count is this run's rolling-window snapshot; V-648's 475-event count used its stated fixed interval and point-in-time cutoff.

The `_fire_sync` import failure produced **119** distinct events from 2026-09-21 02:07:07 UTC through 2026-09-25 15:30:56 UTC. It matched the existing V-636 fix, commit `9035836a`. This is the same historical issue V-646 counted as 118 + 80 logger lines; this detector collapses paired logger/root-handler lines. The currently running service entered active state at **2026-09-27 04:49:07 UTC**. A direct post-fix comparison found **0** `_fire_sync` recurrences through **2026-09-27 12:56 UTC**; the 168-hour observation window is still open, so the measured verdict is “not repeated so far”, not a completed-window success.

The V-648 listener case remained actionable: one `listen task exited unexpectedly while RUNNING` event at 2026-09-24 08:38:04 UTC. It predates the current process start and V-648 contains the investigation. The `IDLE`/`WAITING` messages were suppressed as normal completion noise. This preserves the one confirmed interrupted turn while removing the routine listener churn.

All emitted signatures and examples were normalized before review; no raw log rows or database contents were added to this report. The dry run left `/home/kesha/orchestra/data/error_watch.json` absent.

## Fix registry

Once deployed, register a fix using the normalized signature and the time the fixed process became active:

```sh
cd /home/kesha/orchestra
/opt/orchestra/runtimes/20260817-b0b72d65-py312-rag-v2/bin/python -m app.error_watch record-fix \
  --signature "task sync after publish failed: ImportError: cannot import name '_fire_sync' from 'app.tm' (<PATH>)" \
  --task V-636 --commit 9035836a --started-at 2026-09-27T04:49:07+00:00 --window-hours 168
```

This creates/updates only `data/error_watch.json`. Each later scan checks matching occurrences after `started-at`; it reports the first recurrence and reports the final count when the observation window closes. For the current process, the measured interim verdict above is 0 recurrences. The incident remains open until a person closes it.

## Enabling the schedule after merge

The current `bg_jobs` manager already supports `cron_command`; no service restart is needed. After merge, create a job targeting `Orchestra-orchestrator` with:

```text
type: cron_command
cron_expr: 0 * * * *
command: cd /home/kesha/orchestra && /opt/orchestra/runtimes/20260817-b0b72d65-py312-rag-v2/bin/python -m app.error_watch scan
pattern: ERROR-WATCH:
timeout_seconds: 0
```

`bg_create` takes those values plus a short message for the orchestrator. Cron expressions use UTC. The scanner process inherits the service environment, including `ORCHESTRA_DB_PATH`; it runs as the service user and writes its private registry next to that DB. A run without new findings prints no matching marker, so it does not wake the orchestrator. This schedule was not created as part of V-647.

## Verification

Command:

```sh
/opt/orchestra/runtimes/20260817-b0b72d65-py312-rag-v2/bin/python -m pytest tests/test_error_watch.py -q
```

Result: **11 passed**. Imported module: `/home/kesha/orchestra/worktrees/home-kesha-orchestra/impl-error-watch/app/error_watch.py`. Fixtures cover dynamic-value and credential normalization, preserving distinct causes, the repeat threshold, quota and listener noise, the threshold-1 RUNNING failure, paired logger deduplication without merging separate sessions, repeated scans without duplicate signals, fix registry persistence, and post-fix recurrence/absence verdicts, including deduplicated post-fix counts. The real-data command was `python -m app.error_watch scan --db /home/kesha/orchestra/data/orchestra.db --dry-run` under the same interpreter; it used the real journal and read-only DB path described above.
