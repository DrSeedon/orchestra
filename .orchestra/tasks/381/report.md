# #381 Phase 3 report — structured initial-delivery outcome boundary

## Status

T1–T3 are implemented against the immutable RED freeze
`621891aa0d44425610c564ac72f4b6c0c8b72726`. No test, fixture, helper, test configuration,
marker, or selection setting changed after that freeze. No live delivery, service restart, deploy,
or historical-row rewrite was performed.

## Implementation

- `app/session.py`
  - binds and validates the backend `send` callable before the durable delivery boundary;
  - calls the existing no-yield `before_submit` hook immediately before the bound provider call;
  - rejects a backend candidate cleared/replaced during slow `connect()` and returns the validated
    local candidate rather than a mutable owner field.
- `app/initial_deliveries.py`
  - adds durable `FAILED_BEFORE_SUBMIT` with `DELIVERY_NOT_SUBMITTED`,
    `outcome_unknown=false`, `retryable=true`, and `phase=PRE_PROVIDER`;
  - labels ambiguous/orphan dispatch errors with `phase=PROVIDER_CALL_STARTED` without weakening
    `DELIVERY_UNKNOWN` quarantine;
  - atomically claims only same-key/same-payload `FAILED_BEFORE_SUBMIT -> PREPARING`, preserves
    `user_log_id`, clears the prior error, and wakes only the SQL winner after commit;
  - leaves `DISPATCHING`, `DELIVERY_UNKNOWN`, `SUBMITTED`, `QUEUED`, and `PREPARING` matching reads
    unscheduled;
  - returns exact machine-readable `next_action` fields for every supported state.

Implementation diff before report/review: `app/initial_deliveries.py +126/-33`,
`app/session.py +7/-2`.

## Tickets

- T1 complete — structural pre-provider/provider-call boundary and durable phase classification.
- T2 complete — atomic explicit retry, one winner, lost-wake startup recovery, one prompt/log/send.
- T3 complete — exact `code/tool/arguments/retryable/message` action contract.

## Test evidence

```text
uv run python -m pytest -q tests/test_initial_deliveries.py -k 'test_t381_'
5 passed, 15 deselected in 11.99s

uv run python -m pytest -q tests/test_initial_deliveries.py -k 'test_t2_'
10 passed, 10 deselected in 16.29s

uv run python -m pytest -q tests/test_mcp_stdio.py -k 'test_t3_'
9 passed, 91 deselected in 6.21s

uv run python -m pytest -q tests/test_initial_deliveries.py
20 passed in 26.01s

uv run python -m pytest -q tests/test_initial_delivery_review_regressions.py tests/test_session.py
216 passed in 53.80s

git diff --exit-code 621891aa0d44425610c564ac72f4b6c0c8b72726 -- tests/test_initial_deliveries.py
exit 0, empty

isolated unsupported historical-state probe
unsupported_status=readable matching_receipt=readable retryable=false wakes=0
```

The required full command ran under the global test lock and its log was read once:

```text
uv run python -m pytest -x -q > /tmp/pytest-381.log 2>&1
1 failed, 1025 passed, 42 skipped, 3 deselected in 402.53s
```

The sole failure was
`tests/test_frontend.py::test_split_history_page_pairs_results_with_calls_that_arrive_later[codex_item_id_in_body-compact]`:
the Playwright fixture timed out opening its local `http://127.0.0.1:60391/` server. The exact case
was rerun after releasing the lock:

```text
uv run python -m pytest -q 'tests/test_frontend.py::test_split_history_page_pairs_results_with_calls_that_arrive_later[codex_item_id_in_body-compact]'
1 passed in 23.10s
```

Neither changed file is a frontend/Playwright/fixture consumer; the isolated allowing control makes
the full-suite failure an unrelated transient fixture timeout rather than a #381 regression.

## Mutation evidence

### M1 — move the durable boundary before the session/provider seam

Temporary mutation inserted `await context.before_submit()` in `run_initial_delivery` before the
manager/session path. The same pre-provider failure was therefore classified after the boundary:

```text
O1 + O2: 3 failed, 17 deselected
before_marker=1 mutant_marker=1 after_marker=1 restored_mutant=0 pytest_exit=1
```

After restore plus `touch`, the exact selection returned `3 passed, 17 deselected`.

### M2 — permit matching replay from `DISPATCHING`/`DELIVERY_UNKNOWN`

Temporary compound mutation expanded the retry claim guard to the two quarantined states and made
the claim update unconditional. The quarantine oracle observed `PREPARING` instead of
`DISPATCHING`:

```text
O3: 1 failed, 19 deselected
before_condition=1 before_where=1 mutant_condition=1 mutant_where=1
after_condition=1 after_where=1 restored_mutant_condition=0 pytest_exit=1
```

After restore plus `touch`, O3 returned `1 passed, 19 deselected`.

## Pre-mortem: next-consumer regressions

1. **Slow connect is concurrently restarted** → `app/session.py:_ensure_backend` could return a
   cleared/stale backend; O1 covers returned `None`, the identity guard fails before dispatch, and
   the 216-test session regression covers normal construction/reconnect callers.
2. **Retry claim commits, runner wake is lost** → delivery could remain stuck; O2 injects a wake
   exception, observes committed `PREPARING`, startup-recovers it once, and finishes one real send.
3. **Caller repeats the same key while provider outcome is ambiguous** → duplicate paid turn; O3
   checks live `DISPATCHING`, fresh `DELIVERY_UNKNOWN`, and an independently seeded historical
   unknown, while M2 proves the oracle catches replay permission.
4. **Retry rebuilds history/current prompt twice** → worker sees duplicate task; O2 asserts one
   immutable `user_log_id`, one stored user message, one prompt preparation, and one provider call.
5. **MCP consumer cannot interpret the extended action object** → caller retries the wrong state;
   O4 asserts the complete mapping for six states, the unchanged #311 T3 command is green, and the
   reviewer-fix probe proves an unsupported historical state remains readable but quarantined.

## Review decision inputs

- Changed executable files: `app/session.py`, `app/initial_deliveries.py` only.
- Consumers: shared session delivery, backend connect/disconnect concurrency, SQLite delivery state,
  startup recovery, HTTP status resources, and MCP same-key retry/status.
- Author metadata: `gpt-5.6-sol`, Codex runtime, live session metadata; role `full-cycle`, pipeline
  `default`.
- Exact AC: immutable #381 command 5 green; legacy #311 T2 10 green; T3 9 green; full initial file
  20 green; both required mutations red then green after restore; no historical rewrite/live action.
- Named checks and observed outputs are recorded verbatim above. The surface is high-risk shared
  delivery/concurrency/persistence, so `codex-debate` routes directly to fresh Sol review.

## Compatibility and breaking behavior

- Intentional structured contract extension: `next_action` is now a non-null object for `SUBMITTED`
  and adds uniform `arguments` and `retryable` keys for all states. This is required so retry
  permission is machine-readable; the existing #311 MCP T3 suite remains green.
- Unsupported historical state strings are not rewritten and do not raise on status/receipt reads;
  they return `QUARANTINED_DELIVERY_STATE`, `tool=null`, `retryable=false`, and zero wake.
- No database schema migration, provider API change, automatic retry, new tool/route, or historical
  state rewrite.

## Implementation review

- Sol Round 1 produced one verified blocker but no formal verdict section: unsupported historical
  state strings raised from `_next_action`, regressing the previous readable fallback.
- The blocker was accepted and fixed with a non-retryable quarantine action; the isolated probe
  above covers both status and matching receipt paths without touching frozen tests.
- Sol Round 2: P2 **FIXED**, no new findings, substantive **APPROVED** verdict. Reviewer evidence:
  #381 `5 passed`, legacy T3 `9 passed`, unsupported-state probe readable/non-retryable/wakes=0/
  row unchanged, and frozen test diff empty.
- The review wrapper reported job failure only because the reviewer wrote
  `**Verdict: APPROVED**` instead of a `## Verdict` heading. The artifact contains the explicit
  verdict and completed-review test outputs; no third unchanged-artifact round was run.

## TODO

- None.
