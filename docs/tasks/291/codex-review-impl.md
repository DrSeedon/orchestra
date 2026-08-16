## Review route

- Attempt 1: completed Sol technical review against `/tmp/291-impl.diff`.
- `cross-family verdict unavailable` — Opus spawn was refused because Claude weekly quota was
  100% at the 95% admission threshold.

## Summary

The frozen oracle suite passes, but the implementation violates multiple Release A safety requirements. Most critically, the observer is enabled by default, remains on the delivery critical path, replay leaks future outcomes, and evidence evaluation accepts cross-bucket inputs.

Test evidence:

```text
$ uv run pytest -q docs/tasks/291/oracles/test_t1_schema_and_topology.py docs/tasks/291/oracles/test_t2_adaptive_gate.py docs/tasks/291/oracles/test_t3_shadow_delivery.py docs/tasks/291/oracles/test_t4_replay_evidence.py tests/test_routes_surface.py
.......................                                                  [100%]
23 passed in 7.37s
```

## Findings

- blocking: `app/session.py:724` — Every `AgentSession` replaces the `None` default with `get_quota_controller()`, activating SQLite observation in production. `disabled_observer()` is never selected. This contradicts the required disabled production default and makes rollback require a code change instead of configuration/default construction. Default to `disabled_observer()` and inject the production observer only through an explicit Release A observation setup that cannot enable enforcement.

- blocking: `app/session.py:995` — Shadow work is awaited inline before provider submission, and only `Exception` is caught. An observer raising `asyncio.CancelledError`—or cancellation while its `to_thread` call is pending—escapes `_shadow_reserve`, so `backend.send()` at line 1322 never runs. Likewise cancellation while awaiting `_shadow_mark_submitted` happens after provider acceptance but makes `send()` appear unsuccessful, allowing a retry to duplicate delivery. Shadow bookkeeping must not share cancellation/failure semantics with delivery; isolate it so every observer failure, including cancellation, is recorded without changing the provider-submit result.

- blocking: `app/db.py:251` — Schema installation treats the existence of only `quota_controller_decisions` as proof that the entire migration exists. A partial or corrupt database therefore opens successfully without the other four tables, indexes, or triggers. Concrete reproduction produced:

  ```text
  partial_tables_after_open= ['quota_controller_decisions']
  ```

  Validate the complete schema/version on every open, and fail loudly or transactionally repair only a recognized prior version.

- blocking: `scripts/replay_quota_controller.py:628` — SQLite replay selects `d.created_at` but not `o.ended_at`/`o.settled_at`, then attaches `actual_turn_pp` to the decision timestamp. At lines 337–341, that outcome becomes prior history for the next later dispatch even when the original turn had not settled yet. Concurrent dispatches therefore learn from future information. Order outcome availability by `ended_at` or `settled_at`, and expose an outcome only when that timestamp is strictly earlier than the replayed decision.

- blocking: `scripts/replay_quota_controller.py:255` — Cross-bucket validation merely checks that the bucket encoded in the stratum name appears somewhere in `constraints`; it permits arbitrary additional buckets. A Codex stratum referencing both Codex and Grok evidence was accepted:

  ```text
  cross_bucket= {'eligible': True, 'eligible_strata': ['codex:primary/sol/normal/worker'], 'reasons': []}
  ```

  Validate the exact topology-derived constraint set for each stratum. Extra foreign buckets must produce `cross_bucket_evidence` and make that stratum ineligible.

- suggestion: `app/session.py:1050` — Settlement performs synchronous SQLite work directly from `TurnManager.handle_turn_end`. WAL lock contention can block the event loop for the configured five-second busy timeout, delaying unrelated sessions. Use the same off-thread boundary as reserve/submitted operations, while preserving fire-and-observe failure isolation.

## Verdict

REJECT — five blocking findings remain. The implementation is not safe to merge as Release A despite the 23 passing frozen tests.

- Attempt 2: resumed Sol review after executable fixes in `cd999393`.

## Round (2026-08-16T18:39:36Z)

## Round 2

## Summary

Five prior findings are closed or withdrawn. The schema-corruption finding remains open: validation checks object names and table column names, but not trigger/index definitions or column constraints.

Exact verification:

```text
$ uv run python -m pytest -q docs/tasks/291/oracles/test_t1_schema_and_topology.py docs/tasks/291/oracles/test_t2_adaptive_gate.py docs/tasks/291/oracles/test_t3_shadow_delivery.py docs/tasks/291/oracles/test_t4_replay_evidence.py tests/test_routes_surface.py tests/test_session.py::TestQuotaGatedDeferredTurns::test_ack_quota_cross_retains_summary_then_later_commits_once tests/test_session.py::TestPrecompactTimer::test_codex_native_compact_queues_message_until_completion
.........................                                                [100%]
25 passed in 8.18s
```

Prior dispositions:

1. Production observer default — WITHDRAWN. The clarified owner requirement explicitly mandates active production calibration, and the controller has no dispatch authority.
2. Cancellation coupling — FIXED. Observer-originated cancellation is contained; genuine pre-submit external cancellation still prevents delivery, while post-submit bookkeeping cancellation cannot report the accepted send as failed.
3. Partial/corrupt schema — STILL BROKEN; details below.
4. Replay look-ahead — FIXED. Outcomes become visible strictly after `settled_at`.
5. Cross-bucket evidence — FIXED. Referenced constraints must equal the stratum bucket set.
6. Synchronous settlement suggestion — FIXED. Production settlement runs off-thread and failures are observed by tracked tasks.

## Findings

- blocking: `app/db.py:275` — `_quota_controller_schema_complete()` validates only object names and ordered table column names. A corrupt trigger or index with the expected name is accepted as healthy. Replacing `quota_controller_decisions_no_update` with a no-op trigger, reopening through `quota_controller_connection()`, and updating an immutable decision produced:

  ```text
  CORRUPT_SCHEMA_PROBE accepted= tampered
  ```

  Validate normalized `sqlite_master.sql` or a schema version/digest covering constraints, indexes, and triggers. Otherwise corrupt immutable audit storage silently becomes mutable.

No new blocking finding was found outside this unresolved schema case.

## Verdict

REJECT — prior finding 3 remains blocking.

- Attempt 3: final resumed Sol review after canonical SQL validation of every controller table,
  index and trigger.

## Round (2026-08-16T18:42:31Z)

## Round 3

## Summary

Remaining schema-corruption blocker is FIXED. Canonical normalized DDL comparison now rejects altered tables, indexes, and triggers before returning a controller connection. Previously closed findings show no regression.

Verification:

```text
$ uv run python -m pytest -q docs/tasks/291/oracles/test_t1_schema_and_topology.py docs/tasks/291/oracles/test_t2_adaptive_gate.py docs/tasks/291/oracles/test_t3_shadow_delivery.py docs/tasks/291/oracles/test_t4_replay_evidence.py tests/test_routes_surface.py tests/test_session.py::TestQuotaGatedDeferredTurns::test_ack_quota_cross_retains_summary_then_later_commits_once tests/test_session.py::TestPrecompactTimer::test_codex_native_compact_queues_message_until_completion
.........................                                                [100%]
25 passed in 6.16s
```

Additional corruption probes rejected both a no-op immutability trigger and an altered index definition.

## Findings

No blocking findings or regressions found.

## Verdict

APPROVE.
