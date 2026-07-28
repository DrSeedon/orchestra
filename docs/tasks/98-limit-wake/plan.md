# Task 98 — provider-capacity wake plan

## Goal

Make `Разбудить после сброса` schedule and execute from actual provider
capacity, not from the terminal label attached to an agent.

For this task Anthropic readiness is deliberately limited to the measured base
path:

```text
extra_available = false
available = complete_base_windows_open
```

`monthly` remains useful for explaining the previous stop, but it does not make
an agent manual-only when an exhausted base window has a known reset.

## Scope and assumptions

- The production evidence in `research.md` is the contract:
  monthly-classified agents executed after the 5h reset while
  `spend_limit_reached=true`.
- Both Anthropic base windows, `five_hour` and `seven_day`, must be present with
  numeric utilization before execution can be authorized.
- The unmeasured extra-usage clear state is not inferred. Extra usage cannot
  authorize a wake in this implementation.
- A known exhausted base window with a future reset is enough to create a
  one-shot timer only when every other exhausted required Anthropic window
  also has a valid future reset. The timer still performs a fresh fail-closed
  check before every send.
- No recurring watcher, polling job, database migration, or server restart is
  in scope.

## Design

### One readiness invariant

Add one flat helper in `app/limit_wake.py`, tentatively:

```python
provider_readiness(provider_envelope, provider, *, now=None) -> dict
```

Every planning and delivery path uses it:

1. `build_wake_plan()` asks whether the provider is open now, has a known
   future reset, has no timed recovery path, or has incomplete data.
2. `run_wake_job()` calls the same helper on a forced-fresh provider response
   immediately before each `session.send()`.

The provider-scoped envelope is explicit:

```text
fresh: bool
usage: only snapshot[provider], never a merged all-provider response
error: bounded fetch error or null
```

`current_provider_usage(provider=..., force_refresh=True)` raises when the
requested provider is not freshly fetched, but returns cached/fallback data for
other providers. The caller must therefore extract only
`response[requested_provider]`. A caught exception becomes
`fresh=false, usage=null, error=...` and is passed to the helper; freshness is
not inferred from normalized usage.

The helper returns one of:

- `available`: complete required windows are below 100%;
- `reset`: base capacity is exhausted and has a provider-valid future reset;
  `reset_at` is the latest such reset;
- `manual`: Anthropic base is exhausted but has no future reset;
- `unavailable`: required windows are missing, non-numeric, stale/fetch failed,
  or otherwise incomplete.

Anthropic requires exactly the two base IDs `five_hour` and `seven_day`. Every
exhausted required Anthropic window must have a valid future reset or the result
is `manual`.

Codex/Grok preserve their current reset behavior: at least one normalized
numeric window is required; `available` still requires all observed windows
below 100%; scheduling uses the latest valid future reset and continues to
ignore another exhausted window whose reset is absent/invalid. The fresh
pre-send check still prevents delivery while any observed window remains
exhausted.

There will be no sibling `provider_is_available()` logic. It is replaced by the
single readiness helper so planning and execution cannot drift.

### Fresh click and one-shot scheduling

`schedule_wake_after_reset()` will:

1. acquire one module-level `asyncio.Lock` that serializes the entire
   candidate-load → provider refresh → create/replace/cancel → response
   decision cycle for concurrent POSTs;
2. load current limit-stopped candidates;
3. force-refresh normalized usage per provider through
   `current_provider_usage(provider=..., force_refresh=True)`, extracting only
   the requested provider slice into a freshness envelope;
4. build one provider cohort containing all its candidates, regardless of
   `limit_kind`;
5. create/replace the existing persisted timer:
   - provider already available → `delay=0.1`, reason `available_now`;
   - provider blocked with a known reset → trigger at `reset_at`, reason
     `base_reset`;
6. preserve the exact existing provider job/config/trigger if the fresh fetch
   fails; do not call replace/cancel for that provider;
7. cancel an obsolete provider timer only when a successful fresh decision says
   there are no candidates or no schedulable timed path.

The immediate case still goes through the persisted timer and
`run_wake_job()`, so it shares delivery ledger, restart recovery, turn-id guard,
stagger, and pre-send readiness.

### Authoritative POST decision and persisted status

The POST decision snapshot is authoritative for immediate/manual/unavailable
feedback. `_analyticsScheduleWake()` must render that snapshot directly, not
discard it in favor of a later `wake_status()` query. This closes the race where
a `delay=0.1` job finishes before `state` is built.

`wake_status()` remains authoritative only for currently persisted active jobs
and current candidate summary on a later GET/reload. Without a schema change,
manual/unavailable decisions from an old click are not promised to persist
after reload. Active persisted jobs do expose names/reasons.

On fresh-fetch failure:

- the old job is returned under `scheduled` with `preserved=true`,
  its original cohort/config/trigger unchanged;
- preservation covers a current candidate only when both its `id` and
  `limit_turn_id` match an entry in the old job config;
- a separate warning names every current `(id, limit_turn_id)` not covered by
  the preserved config and explains that refresh failed. The same session id
  with a newer limited turn is therefore uncovered, because the delivery
  turn-id guard would reject it;
- no candidate is simultaneously described as both unscheduled and safely
  covered by the old job.

### Exhaustive response contract

No candidate may disappear. The plan and POST response will expose four
non-exclusive groups:

```text
scheduled:
  provider, reason (available_now/base_reset), reset_at, agent names
manual:
  provider, reason, agent names, manual_action_url
unavailable:
  provider, reason, agent names
warnings:
  provider, reason, affected agent names
```

`wake_status()` will retain agent names and scheduling reason already stored in
each active job config, instead of projecting only `agent_count`. Legacy
aggregate counts may remain, but the UI will render the names.

The frontend must render all populated groups together. `monthly` may not hide
a valid schedule for the same or another provider.

Required messages:

- scheduled now: who will be messaged now;
- scheduled later: who and the local reset time;
- manual-only: who will not wake automatically, why, and the Claude Usage link;
- unavailable: who was not scheduled and which fresh data was missing;
- preserved timer: who remains covered by the old timer, its unchanged time,
  and which new candidates were not incorporated because refresh failed;
- no candidates/no actions: an explicit `Ничего не запланировано` acknowledgement.

### Fail-closed execution

Before every staggered send, `run_wake_job()`:

1. obtains a forced-fresh provider snapshot;
2. passes it through the one readiness helper;
3. sends only for `available`;
4. otherwise stops the cohort and persists the precise readiness reason.

For Anthropic, permissive-looking extra fields cannot override exhausted or
incomplete base windows. This is intentional until a live extra clear-state is
measured in a later task.

## Files

- `app/limit_wake.py`
  - replace `provider_is_available()` with the readiness helper;
  - make `build_wake_plan()` provider-capacity based and exhaustive;
  - serialize `schedule_wake_after_reset()` and use provider-scoped fresh data;
  - preserve exact timers on fetch failure;
  - make `wake_status()` expose names/reasons;
  - gate every send in `run_wake_job()` through the same helper.
- `app/static/js/analytics.js`
  - render scheduled/manual/unavailable groups together;
  - show exact names, local time, action link, and explicit zero-action result.
- `tests/test_limit_wake.py`
  - backend RED→GREEN regressions, non-Anthropic protection, mutations.
- `tests/test_usage_analytics_frontend.py`
  - mixed feedback and empty-result regressions.
- `app/routes/system.py`
  - no planned production change; its existing
    `current_provider_usage(provider, force_refresh)` is the internal fresh
    source. Touch only if an implementation test proves the existing contract
    cannot express freshness without weakening fail-closed behavior.

## What not to change

- `_subscription_limit_kind()` and terminal log classification;
- Claude, Codex, or Grok backend send/compact behavior;
- background-job schema, delivery ledger, replay, or stagger;
- public `/api/usage` privacy behavior;
- live database contents or running server.

## TDD and mutation protocol

Before production changes, add focused tests and record their failure on the
current code:

1. monthly-classified Anthropic candidate + 5h=100 with future reset is
   scheduled, not manual-only;
2. monthly-classified candidate + complete open 5h/7d is scheduled immediately
   even when extra fields look blocked;
3. mixed monthly/timed Anthropic candidates all appear in the same schedule;
4. missing either Anthropic base window is unavailable, never available;
5. no future base reset produces manual-only with names/action link;
6. a pre-send refresh that becomes incomplete/exhausted stops before the next
   agent;
7. exhausted/partial base plus maximally permissive-looking extra fields remains
   `reset`/`unavailable` and cannot authorize a pre-send;
8. Codex/Grok with two exhausted windows, one lacking a valid reset, preserves
   the current schedule-by-valid-reset behavior;
9. fresh-fetch failure preserves the exact prior job id/config/trigger, while a
   successful no-timed-path decision removes the obsolete job. Coverage is
   matched by `(agent id, limit_turn_id)`: the same id with a newer limited
   turn is warned as uncovered and is not claimed by the old timer;
10. two concurrent POSTs serialize refresh→replace/cancel and the later
    decision cannot be overwritten by an older snapshot;
11. an immediate job remains fully represented in the POST decision snapshot
    even if it completes before response rendering;
12. UI displays simultaneous scheduled/manual/unavailable groups and exact
   names; empty POST result is visibly acknowledged.

After GREEN, perform and record at least these temporary mutations, restoring
each immediately:

- force readiness to return `available` for a partial Anthropic snapshot →
  partial/per-send tests must fail;
- allow permissive extra fields to return `available` while base is exhausted →
  extra-disabled tests must fail;
- restore the old `monthly => manual` branch or drop monthly candidates from a
  provider cohort → monthly/mixed scheduling tests must fail;
- restore the frontend's exclusive monthly-first branch → mixed feedback test
  must fail.

## Tickets

### T1 — Schedule-now/schedule-later user path

- Files: `app/limit_wake.py`, `app/static/js/analytics.js`,
  `tests/test_limit_wake.py`, `tests/test_usage_analytics_frontend.py`;
  optionally `app/routes/system.py` only if the existing fresh contract is
  insufficient.
- AC:
  - focused backend regressions fail on the current implementation before code;
  - one readiness helper is the only planning/pre-send capacity decision;
  - helper receives a provider-scoped freshness/error envelope; data from
    another provider call cannot overwrite it;
  - `extra_available` cannot become true in this task;
  - monthly-classified agents schedule at a known base reset and wake
    immediately when complete base windows are already open;
  - mixed candidates are all accounted for;
  - partial/stale/fetch-failed data is fail-closed with a reason;
  - every staggered send rechecks the same helper;
  - Anthropic reset strictness and legacy Codex/Grok reset behavior have
    separate tests;
  - POST decision snapshot, not a racy active-job reread, shows exact names and
    `available_now`/`base_reset`;
  - backend readiness/cohort mutations produce the expected failures and are
    restored.
- blocked-by: none

### T2 — Failure/preserved/manual/empty user path

- Files: `app/limit_wake.py`, `app/static/js/analytics.js`,
  `tests/test_usage_analytics_frontend.py`, `tests/test_limit_wake.py`.
- AC:
  - one `asyncio.Lock` serializes the complete scheduling transaction;
  - concurrent POST regression proves an older refresh cannot overwrite a
    newer replace/cancel decision;
  - refresh failure preserves the exact old job/config/trigger and reports it
    as `scheduled, preserved=true`;
  - preserved coverage is exact on `(agent id, limit_turn_id)`; a regression
    with old turn A and current turn B for the same agent proves B is warned as
    uncovered, while an exact pair is not mislabeled unavailable;
  - a successful manual/no-path decision removes an obsolete timer;
  - the authoritative POST decision includes exact names and reasons for every
    scheduled, manual, unavailable, or warning group;
  - `wake_status()` includes exact names/reasons only for active persisted jobs
    plus its current candidate summary; it does not promise old
    manual/unavailable click decisions after reload;
  - scheduled/manual/unavailable groups render simultaneously;
  - scheduled reset is shown in local time and manual Anthropic output retains
    the Claude Usage link;
  - a zero-action click explicitly says `Ничего не запланировано`;
  - an immediate job remains visible from the authoritative POST snapshot even
    if the job finishes before response construction;
  - no candidate is absent from all response groups;
  - frontend exclusive-branch mutation fails and is restored.
- blocked-by: T1

## Verification

Focused during T1/T2:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest \
  tests/test_limit_wake.py tests/test_usage_analytics_frontend.py -q
```

Adjacent shared-runtime regressions:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest \
  tests/test_session.py tests/test_codex_usage.py \
  tests/test_backend_claude.py tests/test_backend_codex.py \
  tests/test_backend_grok.py -q
```

Required full suite:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest -x -q \
  > /tmp/pytest-98-limit-wake.log 2>&1
```

Then adversarial Codex implementation review, mandatory Round 2 for shared
runtime, `git diff --check`, report, and commit. The server stays untouched.
