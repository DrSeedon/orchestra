# Task 98 — implementation report

## Outcome

`Разбудить после сброса` now decides from provider capacity rather than the
terminal `monthly`/`timed` label.

- Anthropic execution is authorized only when both measured base windows
  (`five_hour`, `seven_day`) are present and below 100%.
- An exhausted Anthropic cohort is scheduled only when every exhausted
  required base window has a future reset.
- `extra_usage` cannot authorize a wake in this task because its independent
  clear-state was not measured.
- Monthly-classified and timed-classified Anthropic agents share the same
  provider cohort. The three agents from the incident could therefore have
  been scheduled at the 5h reset even while
  `extra_usage.spend_limit_reached=true`.
- Every send repeats the same provider-scoped, forced-fresh readiness check.
- A click returns an authoritative decision naming who wakes now/later, who
  cannot wake automatically, and why. Empty decisions are explicit.
- No recurring watcher or new persisted state was added.

## Tickets

### T1 — schedule-now/schedule-later

Completed. `provider_readiness()` is the sole planning and pre-send capacity
invariant. Anthropic requires complete base data; Codex/Grok retain their
existing observed-window/reset behavior. Immediate delivery still uses the
persisted timer, ledger, replay, turn guard, and stagger path.

### T2 — failure/preserved/manual/empty feedback

Completed. One `asyncio.Lock` covers candidate load, provider refresh,
replace/cancel, and response construction. Failed refreshes preserve an
eligible old timer only after revalidating the exact job id; coverage is exact
on `(agent id, limit_turn_id)`. The frontend renders scheduled, manual,
unavailable, and warning groups together.

## Files

- `app/limit_wake.py` (+368/-113): shared readiness invariant, fresh
  provider-scoped planning, serialized replacement, exact preservation, and
  pre-send gating.
- `app/static/js/analytics.js` (+40/-12): authoritative POST rendering and
  exhaustive click feedback.
- `tests/test_limit_wake.py` (+664/-25): capacity, preservation, concurrency,
  freshness, delivery, and mutation regressions.
- `tests/test_usage_analytics_frontend.py` (+109/-12): names, simultaneous
  groups, action link, direct POST snapshot, and explicit no-op feedback.

## Verification evidence

Baseline on the old implementation:

- `/tmp/pytest-98-limit-wake-red.log`: 3/3 backend regressions failed
  (`monthly`, mixed cohort, missing invariant).
- `/tmp/pytest-98-limit-wake-ui-red.log`: 3/3 UI regressions failed (POST
  decision discarded, groups hidden, no-op silent).
- `/tmp/pytest-98-preserve-race-red.log`: false `preserved=true` reproduced
  when the old timer finished during refresh.
- `/tmp/pytest-98-missing-provider-red.log`: a response missing the requested
  provider cancelled the valid old timer.

Final checks:

- Focused: `42 passed` in
  `tests/test_limit_wake.py tests/test_usage_analytics_frontend.py`.
- Adjacent shared runtime: `246 passed` across session, usage, Claude, Codex,
  and Grok tests.
- Full suite: `/tmp/pytest-98-limit-wake-final.log` —
  `1139 passed, 20 skipped in 88.34s`.
- `git diff --check`: clean.
- `ruff` was unavailable in the environment (`No such file or directory`);
  pytest and Python import/collection covered syntax.

Temporary mutation verification, each restored immediately:

| Mutation | Expected failure |
|---|---:|
| partial Anthropic base reported available | 2 failed |
| permissive extra fields authorized exhausted base | 1 failed |
| monthly agents removed from provider cohort | 2 failed |
| frontend restored the old `result.state` reread | 2 failed |
| preserved coverage compared agent id only | 1 failed |

## Adversarial review

Codex found and the implementation fixed two P2 races:

1. a timer captured before refresh could finish during the await and still be
   reported as preserved;
2. a normalized response missing the requested provider was marked fresh and
   cancelled an eligible timer.

Round 3 reclassified both as fixed and returned **APPROVED** with no new
findings. Evidence: `docs/tasks/98-limit-wake/codex-review-impl.md`.

## Self-review and residual risk

- A preserved timer is only a snapshot: it can naturally trigger immediately
  after the response. Revalidation removes the stale-before-decision lie; the
  normal post-response passage of time is not locked.
- The extra-usage authorization branch remains deliberately disabled until a
  live state proves which field combination independently permits execution
  while base capacity is exhausted.
- No live database was mutated and the server was not restarted. This Python
  diff is not active until the orchestrator merges it and a later authorized
  restart loads it. It does not rely on task #91 or #97 behavior.

## Proposed reusable rule

Not persisted pending approval:

> 📝 RULE: When a provider limit field or terminal label appears to decide
> execution readiness → verify completed real turns under that field state and
> model base versus supplemental capacity separately, not treat the label as a
> provider-wide verdict.

Suggested location: project `CLAUDE.md`, limit-handling section.
