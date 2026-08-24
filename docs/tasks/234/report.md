# #234 — implementation report

## Result

The quota refresh now has one ordered ownership chain:

1. `/api/usage` refreshes provider state;
2. both UI consumers share one cache-only `/api/usage/quota-map` flight;
3. browser GET attempts enter a four-permit FIFO before their 2-second timeout starts;
4. a failed usage refresh preserves last-good memory and `localStorage` instead of saving `null`.

No timeout, attempt count, jitter, provider single-flight, IndexedDB, proxy, nginx, deployment, or
restart behavior changed.

## Files

- `app/routes/system.py` (`-1`): `build_quota_map()` no longer performs provider I/O.
- `app/static/js/app.js` (`+118/-36` from pre-implementation base): shared quota flight; FIFO GET
  admission; queued-abort handling; stale/no-data verdict handling; quota-lines joins the usage owner.
- `app/static/js/usage.js` (`+17/-6`): provider refresh settles before cache-only map; last-good
  usage/snapshot changes only on fulfilled usage.
- `tests/test_grok_usage_frontend.py` (`+18/-11`): only T3 contract/harness updates—last-good UI
  expectations and sequential usage→quota settlement; request-storm counts remain exact before and
  after each settle.
- `docs/tasks/234/acceptance/test_review_cache_only_order.py` (`+105`): reviewer-derived RED guard
  for refresh ordering and stale/unknown summary.
- `docs/tasks/234/plan.md` (`+4/-1`): mapped baseline re-closed after detecting two pre-existing
  #344 failures.

Frozen acceptance files from `ebbc531c` are byte-identical.

## Tickets

### T1 — shared cache-only quota map

- `build_quota_map()` consumes `_quota_observation_from_cache()` without `_get_usage_data()`.
- `_fetchQuotaMapShared()` shares only the active Promise and clears it after settlement.
- Back-to-back consumers make one request; the next wave makes one new request.
- T1 executor Luna stopped at an unrelated mapped AC discrepancy. Sol escalation was forbidden;
  parent reproduced the exact baseline, took T1 back, and implemented it directly.

### T2 — GET admission before timeout

- `_API_MAX_CONCURRENT_GETS = 4`.
- A permit covers `fetch`, error body, and JSON parsing; release occurs before retry jitter.
- Retry joins the FIFO tail; caller abort while queued never reaches `fetch`.
- Non-GET bypasses the queue and retains 5,000 ms / one attempt.

### T3 — snapshot preservation

- Fulfilled usage alone updates memory, last-success time, and snapshot.
- Rejected usage retains last-good data; missing data remains explicit `Usage unavailable` and no
  `{data:null}` snapshot is created.
- Quota-map settlement remains independent.

### Review-derived guard

The timed-out Luna review probed a stale cache and found `fresh=false`, `release_status=no_data`,
`model_state=unknown`. Before the follow-up fix, the badge said `нет данных` while the summary said
`работают`. A new RED guard was committed before the fix; quota-map now waits for `/api/usage`, and
stale/no-data lanes cannot enter the open summary.

## Test evidence

### Frozen and review-derived acceptance

- Frozen oracle integrity: `git diff --exit-code ebbc531c --` the three frozen files → exit 0.
- T1 named command: `2 passed` ×3 (1.11/1.03/1.06 s).
- T2 named command: `4 passed` ×3 (2.25/2.24/2.18 s).
- T3 named command: `2 passed` ×3 (1.19/1.22/1.24 s).
- Review cache-order/stale-summary guard: `2 passed` ×3 (1.22/1.19/1.22 s).
- All `docs/tasks/234/acceptance`: `10 passed` ×3 after final production changes
  (5.18/5.90/5.54 s).

### Focused consumers

- T2 timeout/caller-signal/jitter command: `3 passed` ×3, plus final `3 passed in 2.68s`.
- T3 lossy-snapshot/empty-cache command after final review fix: `2 passed` ×3
  (10.94/8.09/8.08 s).
- `tests/test_grok_usage_frontend.py`: `10 passed in 4.75s`.
- Sequential request-storm test: `1 passed` ×3 (3.38/2.30/2.16 s); counts remain
  usage-only before settle and usage+one-quota after settle.
- Stale API/UI focused pair: `2 passed in 2.78s`.

### Mapped baseline/current comparison

Command:

```text
python -m pytest -p no:cacheprovider \
  tests/test_quota_map_api.py tests/test_t344_quota_lines_browser.py \
  tests/test_grok_usage_frontend.py -q
```

- Before T1: `41 passed, 2 failed`.
- Final: `41 passed, 2 failed`.
- Exact unchanged failures:
  - `test_above_the_diagonal_stops_sol_but_not_luna_and_spark`
  - `test_hard_99_stops_everyone_and_orchestrator_still_works`
- Both #344 fixtures omit `release_status`, so `_qlReleaseText` returns `работает` while the old
  assertions expect `блок`. #234 did not add that out-of-scope compatibility fallback.

### Repository suite

Required full command was run through `uv run --no-sync` with the existing project venv and
`-x -q`. It stopped during collection before #234 tests:

```text
ERROR tests/test_process_guard.py
AttributeError: module 'os' has no attribute 'pidfd_open'
1 error in 4.90s
```

`uv.lock` was unchanged. This environment/import failure is unrelated to the diff; all mapped and
focused #234 consumers were run separately above.

## Pre-mortem

| scenario | consumer / symptom | check |
|---|---|---|
| permit leaks until polling freezes | every `api()` GET; fifth request never starts | T2 admission test: fifth starts after first JSON completes |
| queued scope change resurrects stale request | `refreshSessions`; aborted call reaches fetch | T2 queued-abort test: four fetches, fifth returns `AbortError` without fetch |
| retry monopolizes permit during jitter | all pollers; follower waits behind sleeping retry | T2 release-before-jitter guard |
| GET queue changes mutation semantics | spawn/send/restart; delayed or repeated POST | T2 non-GET guard: bypass, 5,000 ms, one attempt |
| shared quota Promise becomes permanent cache | usage and quota-lines never refresh again | T1 two-wave counts: 1 then 2 |
| cache-only map races its refresh owner | every third TTL phase shows stale result | review order guard: usage:end precedes quota |
| stale/unknown state is shown as working | quota summary contradicts lane/model state | stale-summary guard: `нет данных`, never `работают` |
| lossy refresh erases last-good usage | usage bar becomes `Usage unavailable` | T3 last-good + existing lossy-dashboard tests |
| empty cache silently looks current | first visit after loss shows fabricated data | T3 empty test: explicit unavailable, no null snapshot |

## Review

One authorized `gpt-5.6-luna` implementation review timed out after 10 minutes without a completed
verdict. Its partial analysis found no visible permit leak and surfaced the stale cache semantic
risk above. The risk was reproduced with a committed RED guard and fixed. Per task authorization,
no Luna retry and no Sol call were made.

Review: **Luna, вердикта нет — timeout after the single authorized attempt.** Evidence and
disposition: `docs/tasks/234/review-implementation-luna.md`.

## Breaking / deployment / TODO

- Breaking: none. Response schema and quota arithmetic are unchanged.
- Frontend changes require a hard browser refresh to bypass an old ETag.
- `app/routes/system.py` requires an authorized Orchestra restart before cache-only server behavior
  is live. No restart was performed.
- TODO outside #234: repair the two pre-existing #344 fixture expectations; fix the environment
  providing Python without `os.pidfd_open` if the full flat suite must collect there.
