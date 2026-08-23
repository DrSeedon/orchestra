# #234 — plan: stop quota refresh from timing out before it can run

## Objective

Implement the two bounded root-cause seams proven in `research.md`:

1. coalesce quota-map consumers and admit browser GET attempts before creating their timeout;
2. make `/api/usage/quota-map` render from the existing quota observation cache while
   `/api/usage` remains the refresh owner.

Separately restore #197 snapshot preservation because the exact user symptom includes
`⚠ Usage unavailable` and the named pre-existing oracle is red.

The 2,000 ms timeout, three attempts, and 0–800 ms jitter do not change.

## Evidence constraints carried into implementation

- Browser HTTP/1.1 has six per-origin slots in the measured runtime. One persistent SSE and one
  unmanaged request need headroom, so app-managed GET admission is capped at exactly four.
- Queue admission must happen before `AbortSignal.timeout(...)`; otherwise the same invisible
  browser wait still consumes the budget.
- Queue4 alone was insufficient in Phase 1. It is implemented only together with cache-only
  quota-map and duplicate-request coalescing.
- Quota-map may return stale/unknown cache state honestly (`fresh=false` / `data_available=false`);
  it must not turn a display read into provider I/O.
- A failed `/api/usage` refresh must not overwrite either in-memory last-good usage or its
  `localStorage` snapshot with `null`.

## Design

### Shared quota-map flight

Add `_quotaMapFetchPromise` and `_fetchQuotaMapShared()` beside `api()` in
`app/static/js/app.js`. The function creates one `api('/api/usage/quota-map',
{pollKey: 'quota-map'})` Promise, returns it to both `fetchUsage()` and
`fetchQuotaLines()`, and clears the reference in `finally` so the next 120-second phase can
refresh. Rejection is shared for that flight; neither consumer invents a second request.

`app/static/js/usage.js::fetchUsage` and `app/static/js/app.js::fetchQuotaLines` keep their
separate render state, but both consume this one flight. This avoids a new cross-file event bus and
keeps the existing two renderers intact.

### Cache-only server read

Remove the provider refresh call from `app/routes/system.py::build_quota_map`. The function already
reads `_quota_observation_from_cache()` and exposes timestamps/freshness. `/api/usage` remains the
single refresh owner used by the dashboard phase. Empty cache remains explicit unknown/no-data;
there is no fallback network call from quota-map.

### Browser GET admission

In `app/static/js/app.js`, add one FIFO admission queue with the literal
`_API_MAX_CONCURRENT_GETS = 4`.

- Each GET attempt acquires one permit before constructing `AbortSignal.timeout`.
- The permit covers `fetch`, status-body handling, and JSON parsing, then releases in `finally`.
- A retry releases its permit, waits existing jitter, and joins the tail of the queue.
- A caller signal aborted while queued removes that waiter and rejects with its Abort reason;
  `fetch` is never called.
- Non-GET requests bypass the queue completely. `_API_MUTATION_TIMEOUT_MS = 5000`, one attempt,
  and current mutation semantics remain byte-for-byte unchanged.

### Snapshot preservation

In `app/static/js/usage.js::fetchUsage`, update `_usageData`, `_usageLastSuccessAt`, and
`snapshotSave('usage', ...)` only when `/api/usage` fulfilled. On rejection:

- set `_usageError = true` and log the existing error detail;
- keep last-good `_usageData` and snapshot untouched;
- call `_restoreUsageSnapshot()` only if memory has no value;
- keep quota-map success/failure independent.

No prior data still produces the existing explicit `Usage unavailable` state.

## Files

- `app/static/js/app.js`
  - `_fetchQuotaMapShared`
  - GET admission acquire/release helpers
  - `api`
  - `fetchQuotaLines`
- `app/static/js/usage.js`
  - `fetchUsage`
  - snapshot update/preservation branches
- `app/routes/system.py`
  - `build_quota_map`
- `docs/tasks/234/acceptance/test_t1_quota_ownership.py` — frozen RED oracle
- `docs/tasks/234/acceptance/test_t2_get_admission.py` — frozen RED oracle
- `docs/tasks/234/acceptance/test_t3_snapshot_preservation.py` — frozen RED oracle

Existing tests under `tests/` are regression consumers; no rewrite is planned. Test-layer edits
are authorized if Phase 3 discovers a genuinely missing regression assertion, but the three frozen
acceptance files above are immutable.

## Review decision gate

- Changed Phase-2 files: `plan.md` and three frozen acceptance modules; Phase-3 consumers are the
  named JS/API symbols and existing regression suites above.
- Author runtime: `gpt-5.6-sol` from live session metadata.
- Exact AC and commands: recorded per ticket below with observed non-zero exits and assertions.
- Oracle strength: deterministic browser/server behavior with no wall-clock performance threshold;
  initial tests were committed before implementation in `471a94eb`; accepted Luna guardrails were
  re-run RED and re-frozen in `ebbc531c` before Phase 3.
- Risk floor: shared browser GET queue and externally consumed quota endpoint are high-risk
  concurrency/API surfaces. The task owner explicitly forbids further Sol sessions and permits one
  auxiliary Luna review; route is therefore one fresh Luna plan review, with any unresolved
  architecture blocker escalated to the task owner rather than Sol.

## Explicit non-goals

- No timeout increase and no change to retry count/jitter.
- No IndexedDB migration, deletion, version bump, service-worker, proxy, nginx, SSH, or deploy work.
- No provider single-flight in this task. Cache-only quota-map plus per-tab `_usageFetchPromise`
  removes the measured same-tab refresh multiplication. A remaining cross-tab `/api/usage`
  stampede has not been measured after this fix; adding a server lock now would expand scope and
  introduce cancellation/`required_provider` coupling without a closed oracle.
- No change to quota arithmetic, freshness thresholds, admission policy, response schema, or
  mutation request semantics.
- No service restart. Python code would require a later authorized restart to become live; Phase 3
  may verify it in a fresh test process but must not restart Orchestra.

## Dependency order

`T1 → {T2, T3}`. T2 and T3 are independent after T1: T2 owns `app.js::api`; T3 owns the
post-T1 `usage.js::fetchUsage` branch. T1 is first because both later tickets consume the shared
quota-map ownership contract.

## Tickets

### T1 — One quota-map flight backed only by cached observation

- Files: `app/static/js/app.js::_fetchQuotaMapShared`,
  `app/static/js/usage.js::fetchUsage`, `app/static/js/app.js::fetchQuotaLines`,
  `app/routes/system.py::build_quota_map`
- Test: `PYTHONDONTWRITEBYTECODE=1 /mnt/data/Projects/Python/orchestra/.venv/bin/python -m pytest -p no:cacheprovider docs/tasks/234/acceptance/test_t1_quota_ownership.py -q`
  — committed RED in `ebbc531c`
- RED: exit 1, `AssertionError: quota-map must not refresh providers`; shared-flight arm reports
  first/second-wave request counts `2/3` instead of `1/2`.
- AC: the named command is green; additionally
  `tests/test_quota_map_api.py tests/test_t344_quota_lines_browser.py tests/test_grok_usage_frontend.py`
  introduces no new failure versus the Phase-3 baseline: `41 passed, 2 failed`, exactly
  `test_above_the_diagonal_stops_sol_but_not_luna_and_spark` and
  `test_hard_99_stops_everyone_and_orchestrator_still_works`. Both pre-exist T1 because their
  fixtures omit `release_status`; #234 must not add the unrelated compatibility fallback.
- blocked-by: none

### T2 — Admit GET attempts before starting their timeout

- Files: `app/static/js/app.js::_API_MAX_CONCURRENT_GETS`, GET queue helpers, `api`
- Test: `PYTHONDONTWRITEBYTECODE=1 /mnt/data/Projects/Python/orchestra/.venv/bin/python -m pytest -p no:cacheprovider docs/tasks/234/acceptance/test_t2_get_admission.py -q`
  — committed RED in `ebbc531c`
- RED: exit 1 with `2 failed, 2 passed`: `{'fetchCalls': 6, 'timeoutCalls': 6}` instead of
  `{'fetchCalls': 4, 'timeoutCalls': 4}`; queued-abort arm reaches fetch five times instead of four.
  The release-before-jitter and non-GET guardrails already pass on current code and are frozen to
  catch regressions introduced by the queue.
- AC: the named command is green; the literal is `_API_MAX_CONCURRENT_GETS = 4`; caller abort
  while queued never reaches `fetch`; and
  `tests/test_usage_history_frontend.py::test_history_request_gets_its_own_timeout
  tests/test_usage_history_frontend.py::test_history_timeout_survives_a_caller_signal
  tests/test_frontend.py::test_api_retry_spaces_attempts_with_jitter` are green.
- AC not expressed by the frozen test, verbatim: non-GET calls never acquire a GET permit;
  `_API_MUTATION_TIMEOUT_MS = 5000`; non-GET attempts remain exactly one.
- blocked-by: T1

### T3 — Preserve last-good usage on a rejected refresh

- Files: `app/static/js/usage.js::fetchUsage`
- Test: `PYTHONDONTWRITEBYTECODE=1 /mnt/data/Projects/Python/orchestra/.venv/bin/python -m pytest -p no:cacheprovider docs/tasks/234/acceptance/test_t3_snapshot_preservation.py -q`
  — committed RED in `ebbc531c`
- RED: exit 1 with `2 failed`: last-good `memoryUtilization` and `savedUtilization` are `None`;
  no-cache failure incorrectly saves `{data: null}` instead of leaving snapshot absent.
- AC: the named command is green; the pre-existing
  `tests/test_frontend.py::test_dashboard_survives_lossy_channel_from_snapshot` and
  `tests/test_frontend.py::test_dashboard_shows_error_class_when_nothing_cached` are green.
- blocked-by: T1

## Luna review outcome

One fresh `gpt-5.6-luna` review returned **APPROVED, no blocking findings** and verified all
three original commands were genuinely RED, the graph was vertical/acyclic, cache-only state was
honest, and provider single-flight exclusion was bounded. Evidence quote from the plan:
“Queue admission must happen before `AbortSignal.timeout(...)`; otherwise the same invisible browser
wait still consumes the budget.” Artifact: `docs/tasks/234/review-plan-luna.md`.

All four suggestions were accepted without another review round:

- T1 now asserts a second refresh wave creates exactly one new request (promise is not permanent).
- T2 now freezes release-before-jitter ordering and non-GET bypass/5-second/one-attempt behavior.
- T3 now freezes the empty-state branch and forbids saving `null` as a snapshot.

The review wrapper incorrectly reported `FAILED ... review artifact is blind` because its raw-output
regex matched injected `bwrap:` instructions, despite a complete artifact, exit 0, verdict, and exact
quote. Platform bug was reported; no retry or Sol review was run.

## RED evidence — frozen before implementation

```text
T1 → exit 1: AssertionError: quota-map must not refresh providers
T1 shared-flight arm → exit 1: first/second-wave request counts are 2/3, expected 1/2
T2 → exit 1: {'fetchCalls': 6, 'timeoutCalls': 6} != {'fetchCalls': 4, 'timeoutCalls': 4}
T2 abort arm → exit 1: {'fetchCalls': 5, 'outcome': 'AbortError'} != {'fetchCalls': 4, 'outcome': 'AbortError'}
T2 guardrails → 2 passed: release-before-jitter; non-GET bypass/5000 ms/one attempt
T3 last-good → exit 1: memoryUtilization=None, savedUtilization=None, Usage unavailable
T3 empty → exit 1: snapshotLoad('usage') returned {data: null}, expected null/absent
```
