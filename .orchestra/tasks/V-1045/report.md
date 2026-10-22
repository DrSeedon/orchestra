# V-1045 — bounded startup failure-notice backfill

## Result

Changed `app/message_deliveries.py` in the supplied private copy. The platform
will import the changes into `task-V-1045/fix-notice-backfill`; no git commands,
service restart, deployment or external API calls were performed.

- `_backfill_failure_notices` uses the named constant
  `FAILURE_NOTICE_BACKFILL_MAX_AGE = timedelta(hours=24)`. Wake eligibility uses
  the failure's `updated_at`, inclusive of the lower boundary, and a single UTC
  clock snapshot per backfill. `created_at` of the notice is not used for age.
- A backfilled failure never wakes when its delivery target is archived or
  missing. Lookup uses the immutable session ID: `target_session_id` for direct
  messages and `session_id` for initial tasks.
- Suppressed rows still acquire the normal durable notice revision and event ID.
  In the same recovery transaction, `delivered_at` is set and the existing
  `error_json` gains `_notice_skipped_reason`: `outside_recent_window`,
  `target_archived`, `target_missing`, or `invalid_updated_at`. The original error
  remains intact. No schema migration or delivery-state change is needed.
- Malformed dates and future dates are acknowledged without waking. Legacy
  timezone-naive ISO dates are interpreted as UTC; explicit offsets work.
- The existing revision query excludes processed rows on later backfills. A
  genuinely new failure revision for the same delivery ID can still wake.

## Important scope finding

`recover_message_delivery_failure_notices` is shared by startup and the live
sweeper. Filtering every pending notice there would silently suppress live
archive-target failure notifications produced by `fail_deliveries_to_archived_targets`.
The new checks therefore apply only to rows the backfill creates, adopts from
the legacy format, or updates to a new revision. Existing revision-owned notices
and direct live `record_delivery_failure` / `notify_message_delivery_failure`
calls retain their original retry and wake behavior. Both paths are tested.
Already acknowledged legacy notices retain their acknowledgment timestamp.

## Validation actually run

Required runner attempted offline:

```sh
UV_OFFLINE=1 uv run --frozen python -m pytest tests/test_message_failure_backfill_1045.py tests/test_delivery_visible_1036.py tests/test_message_delivery_failure_notices_741.py -q
```

Exit **127**: the installed `uv` is a forwarding shim, with no actual executable
or mapped project. Output: `pytest-attempt.log`. This partial copy additionally
lacks `app/db`, `app/events`, `app/errtext`, `app/quota_queue`, the full test
configuration, and `scripts/run_tests.py`.

Under the task's explicit missing-runner fallback, used **system Python 3.12.3**
for separately labeled stdlib checks; these are not the required uv checks:

```sh
nice -n 15 python3 -B -W error::RuntimeWarning .orchestra/tasks/V-1045/check_offline.py
nice -n 15 python3 -B -W error::RuntimeWarning .orchestra/tasks/V-1045/check_offline.py --mutations
```

- **14 tests passed** (`offline-tests.log`). The complete current
  `app/message_deliveries.py` is imported, not extracted or reimplemented.
  Only unavailable imports are stubbed; the actual recording, backfill and async
  notice-drain functions execute against SQLite in memory, with `manager.send`
  replaced by an `AsyncMock`. Both delivery kinds and all four relevant terminal
  kind/state combinations are covered.
- Tests cover old rows, archived and missing targets, a fresh live sender waking
  once, a second recovery waking nobody, exact 24-hour boundary, future/malformed
  dates, UTC-naive/offset legacy dates, old pending legacy adoption, acknowledged
  legacy adoption, failed-wake retry, a new revision after suppression, and both
  immediate and queued live notice behavior remaining unchanged.
- **6/6 mutations detected**, all through assertion failures without test errors
  (`mutations.log` and individual mutation logs). Removing the age, archived-target
  or missing-target guard fails its regression test; omitting the durable skip
  acknowledgment fails; suppressing fresh notices fails; filtering already
  recorded live notices fails. Mutations execute in memory and never rewrite
  production source or tests.
- The offline harness caps address space at 2 GiB; runs used nice=15 and executed
  sequentially. SQLite was entirely in memory; no live database, credentials,
  provider CLI, Telegram or service environment was accessed.
- Final syntax, whitespace and secret-shape checks: `final-checks.log`.
  The canonical `app.secret_mask` is absent in this copy; the final scan uses
  explicit secret-shaped patterns and manual review of synthetic task output.

Absolute imported app directory:
`<hub-workspace>`.
Absolute imported module:
`<hub-workspace>`.

## Remaining checks and limits

The parent must run the prescribed focused pytest command above in the complete
uv environment before acceptance. The full suite, real schema integration,
provider wakes and actual startup timing were not run here. No claim is made
that this Python change is active in a running service.

Existing V-1036 sender resolution for initial deliveries remains name+scope.
When the sender no longer resolves, existing recording logic creates no notice;
this task does not invent sender identities or change that behavior. Existing
same-revision live pending notices remain eligible for normal recovery by design;
the history filters govern backfill candidates.
