<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Summary

The core dispatch state machine, FIFO/HOL handling, and restart quarantine are coherent, but two idempotency durability defects can permit duplicate provider submissions.

## Findings

- **[blocking] Canonicalize UUIDs before persistence and lookup — `app/message_deliveries.py:30`**

  `_validate_id()` validates the UUID but returns the caller’s original spelling. Equivalent UUID representations—such as lowercase, uppercase, hyphenless, or braced forms—therefore become different SQLite keys. A caller can submit the same logical UUID twice under alternate valid representations, creating two receipts, two user rows, and two provider attempts. Return `str(uuid.UUID(value))` and use that canonical value consistently for POST, GET, hashing, and conflict detection.

- **[blocking] Do not cascade-delete durable idempotency records with the target session — `app/db.py:155`**

  `target_session_id ... ON DELETE CASCADE` removes every receipt when its target session is deleted. A subsequent status reconciliation returns 404, and the same `delivery_id` can then be accepted again—potentially against a replacement session—despite an earlier provider submission. This loses the durable outcome record and breaks at-most-one submission across lifecycle deletion. Preserve/tombstone receipt rows independently of `sessions`, retaining the immutable target identity.

## Verdict

CHANGES REQUESTED.

## Attempt 3 evidence

- Final executable-review round started 2026-08-24 after transactional old-schema rebuild and
  receipt-first authenticated HTTP reconciliation. Fresh target diff includes the uncommitted
  review fixes. Probes: old schema row/FKs survive target deletion; deleted-target alternate UUID
  retry returns one canonical `ALREADY_ACCEPTED/SUBMITTED` receipt; frozen `22 passed`; DB
  `93 passed`; compatibility nodes `2 passed`.

## Attempt log

- Attempt 2 started 2026-08-24 after canonical UUID persistence/MCP normalization and receipt
  independence from target-session/log deletion. Isolated deletion plus alternate-spelling retry
  produced one surviving `SUBMITTED` receipt and zero duplicate rows.

## Round (2026-08-24T02:28:58Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Summary

- Prior UUID canonicalization blocker: **FIXED**.
- Prior receipt-deletion blocker: **STILL BROKEN for databases initialized by the previous schema**, although fresh databases now use the correct FK behavior.

## Findings

- **[blocking] Add a schema migration for existing `message_deliveries` tables — `app/db.py:146`**

  `CREATE TABLE IF NOT EXISTS` does not alter an existing table. Any database initialized by the previous implementation retains `target_session_id ... ON DELETE CASCADE` and the old `user_log_id` FK, so deleting a target still erases its receipts. Rebuild/migrate the table transactionally and verify the resulting `PRAGMA foreign_key_list(message_deliveries)`.

- **[blocking] Reconcile an existing key before resolving the current target — `app/routes/sessions.py:650-739`**

  Keyed POST resolves the target session before calling `accept_message_delivery()`. After lifecycle deletion, retrying the same canonical ID returns `TARGET_NOT_FOUND` instead of its existing `ALREADY_ACCEPTED` receipt, even though the durable row survives. The reported probe exercises storage directly but does not cover the HTTP retry path. An authenticated same-key retry must reconcile the stored source/payload/immutable target binding before requiring the target session to still exist.

## Verdict

CHANGES REQUESTED.

## Round (2026-08-24T02:35:30Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Summary

- Round 2 migration blocker: **STILL BROKEN** because the rebuild is not actually transactional.
- Round 2 deleted-target retry blocker: **FIXED** for same-target retries.

## Findings

- **[blocking] Explicitly begin the rebuild transaction before renaming — `app/db.py:636`**

  The surrounding connection context commits or rolls back a transaction but does not start one. After the earlier `executescript`, `ALTER TABLE` and `CREATE TABLE` can execute in autocommit mode; the transaction begins only at the `INSERT`. If copying fails, the original table may remain renamed while an empty replacement remains active. Use an explicit transaction/savepoint covering rename, create, copy, drop, and index recreation.

- **[blocking] Include the caller-supplied target in existing-key conflict validation — `app/routes/sessions.py:688`**

  The existing-key path replaces the requested route target with stored `target_name` and related fields before hashing. Reusing an ID at `/api/sessions/other-agent/send` with the same message can therefore return `ALREADY_ACCEPTED` for the original recipient instead of `IDEMPOTENCY_CONFLICT`. This falsely reports delivery to the newly requested target. Verify the requested target identity against the stored binding before replaying the receipt.

## Verdict

CHANGES REQUESTED.

## Owner-approved post-ceiling resolution

The executable review ceiling was reached at the verdict above; it remains the last independent
verdict. The task giver authorized both verified local fixes without a fourth model round:

- the whole old-schema rename/create/copy/drop/index rebuild now runs inside savepoint
  `migrate_message_deliveries_380`, with `ROLLBACK TO` + `RELEASE` + re-raise on any failure and
  `RELEASE` on success;
- receipt-first keyed POST now compares the requested route name to stored `target_name` and returns
  known `409 IDEMPOTENCY_CONFLICT` before substituting stored target fields.

Mechanical evidence after the fixes:

```text
docs/tasks/380/test_review_regressions.py -> 2 passed
frozen #380 + review regressions -> 24 passed
mapped final gate -> 608 passed in 273.88s
old-schema injected copy failure -> original table/schema/row/indexes restored; clean rerun succeeds
same-id/same-message wrong route -> 409, no row mutation/wake; original route survives rename/delete
```

Review: Sol, 3 completed rounds. Final independent verdict: **CHANGES REQUESTED**. Owner-approved
post-ceiling fixes: mechanically green; no further review round run.
