# #407 — fan barrier without manual plumbing

## Verified cause

The live MCP `send_message` path accepts a caller-keyed receipt and dispatches it through
`message_deliveries.run_message_delivery → manager.send_message_delivery`.  The old fan gate
exists only in `routes.sessions.send_message` after durable acceptance has already returned,
so live child reports never reached it.

## Result

- Durable child reports are captured in the fan transaction before provider dispatch.
- Non-releasing report receipts move atomically from `PREPARING` to `SUBMITTED` without waking
  the parent.  The releasing receipt is rewritten to the manifest and supplies the one wake.
- Silent completion and child-turn failure use the same fan member state; failure is recorded
  as `failed`, not `done`.
- Known pre-submit failure rearms the completed fan; retrying the same receipt sends the stored
  manifest.  A restart after release also replays the manifest rather than the original report.
- `run_fan(tasks=[...], reuse=[...])` opens the durable barrier before it spawns new workers or
  messages validated live idle workers.  It does not archive workers.  Persisted deadline
  waiters recover at service startup and produce one partial manifest on timeout.
- Worker report ownership moved to `modules/report-format.md`; spawner prompts now use `run_fan`
  instead of manual `open_fan` plus repeated spawn calls.

## Acceptance evidence

- Frozen RED before production edits:
  `tests/test_fan_barrier_intercept.py::test_t1_three_durable_reports_create_exactly_one_parent_wake`
  failed with `manifest["complete"] is False`.
- Final three-child wake record (`--log-cli-level=INFO`): exactly one line,
  `fan parent wake submitted: fan=fan-407-red target=parent-407 delivery_id=...`; `1 passed`.
- Mixed explicit/silent/failed path: member states `done, done, failed`; the assertion immediately
  after the silent child observes zero wake records, and the final assertion observes one.
- Reuse mode: `test_t3_run_fan_reuses_live_idle_workers_after_opening_barrier` verifies both live
  rows are idle, the barrier-open event precedes both messages, spawn is never called, and no
  archive action exists.
- Final focused regression: `299 passed in 6.03s`.
- Mutation of the production interception call: `MUTATION_RC=1`; restored via patch + `touch`,
  marker count `1`, `RESTORED_RC=0`.

## Review

Luna round 1 found three blockers.  Follow-up accepted and fixed pre-submit wake loss and the
split buffered transition; the replay finding was rejected with receipt-idempotency evidence.
Final verdict: `APPROVED`.  Full transcript: `codex-review-impl.md`.

Sol is the technically preferred reviewer for shared message-delivery runtime, but no Sol review
was run because the task did not authorize an additional Sol call.
