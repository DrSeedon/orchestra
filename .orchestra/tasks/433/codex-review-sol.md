<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Summary

Nine blockers—because provenance apparently needed several ways to become confidently wrong. 🙃 Static review covered the five requested seams across all 23 production files. Backup alias protection and normal multi-agent sender aggregation look correct.

Read-evidence quote: `f"migration committed but {len(after_updates)} rows are still non-canonical"`.

## Findings (blocking/suggestion/question)

blocking: scripts/migrate_message_provenance_433.py:369 — A matching migration receipt does not short-circuit execution. Repeating the same command fails because the backup already exists; choosing a new backup reruns `_plan()` and can overwrite valid B1 messages created after the first migration based on their text. A matching receipt must return a no-op before backup or classification.

blocking: scripts/migrate_message_provenance_433.py:400 — Validation happens after `commit()`. A `BEFORE UPDATE ... RAISE(IGNORE)` trigger can skip one row without raising, allowing the remaining updates and migration receipt to commit; the later `after_updates` check reports failure after a partial migration is irreversible. Validate row counts and canonical state before committing.

blocking: scripts/migrate_message_provenance_433.py:234 — The migration upgrades only `logs`, leaving legacy delivery receipts at schema version 1 with default `unknown` provenance and their old payload hashes. Recovery then copies `unknown` from queued/preparing receipts, while retrying an existing receipt recomputes the new provenance-bearing hash and returns `IDEMPOTENCY_CONFLICT`. Both receipt tables must be upgraded in the same offline transaction.

blocking: scripts/migrate_message_provenance_433.py:185 — Timestamp detection precedes agent-prefix detection. The live non-keyed writer stores agent messages as `[HH:MM] [from:name] ...`, so the migration classifies them as `user`, after which they render as right-side human messages. Strip the timestamp before classification or recognize the combined agent form first.

blocking: app/routes/sessions.py:1103 — The non-keyed ingress derives `origin=user` solely from a missing or empty optional `sender`. An internal-token caller can omit `sender` and persist an authenticated-looking user bubble. Human origin must come from validated operator credentials; missing source provenance must fail.

blocking: app/session_turns.py:602 — Mailbox provenance is hardcoded to `agent`, although the enqueue paths store user messages with `sender=""`. Constructing `MessageProvenance` then raises before the surrounding `try`, leaving the claim leased and killing delivery; mixed user/agent batches are likewise not represented correctly. Mailbox entries need durable provenance before batching.

blocking: app/events.py:81 — `from_storage()` does not require `senders` to be a JSON array. For example, `{"senders":{"alice":true}}` is iterated as dictionary keys and normalized into `["alice"]`; with `origin=user`, malformed storage becomes a valid right-side bubble. Reject any non-array `senders` value before construction.

blocking: app/db.py:2473 — Missing or malformed stored provenance is silently replaced with explicit `unknown`. This erases the required distinction between “unknown was supplied” and “provenance is absent/corrupt,” allowing broken rows to pass every consumer as valid data. Missing or invalid provenance must surface a hard failure.

blocking: app/static/js/chat.js:3918 — Frontend validation checks only that `senders` is a non-empty string array. It accepts unsupported keys and malformed optional fields, so `{senders:["user"], unexpected:true}` or a non-string `subtype` with `origin=user` still renders on the right. Validate the complete allowed detail shape before selecting the user branch.

## Verdict

REJECT. The migration can partially commit, is not idempotent, and misclassifies historical agents; legacy recovery and two rendering paths can also manufacture user/unknown provenance. Right now the envelope has a sender field, but several sorting desks still fill it in themselves. 📬

## Round (2026-09-02T05:25:35Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Summary

All nine prior blockers are fixed; naturally, four new edge failures were hiding behind them. 🙃

Read evidence: `"a sender or authenticated operator is required"` from `app/routes/sessions.py`.

Prior findings:

- FIXED #1 — `scripts/migrate_message_provenance_433.py:477`: matching receipts return before backup or classification.
- FIXED #2 — `scripts/migrate_message_provenance_433.py:517`: update counts and canonical state are validated before commit.
- FIXED #3 — `scripts/migrate_message_provenance_433.py:333`: both legacy receipt tables receive schema 2 provenance and recomputed hashes.
- FIXED #4 — `scripts/migrate_message_provenance_433.py:207`: timestamped `[from:name]` is classified before timestamp-user.
- FIXED #5 — `app/routes/sessions.py:903`: senderless ingress requires an authenticated operator.
- FIXED #6 — `app/mailbox.py:9`, `app/session_turns.py:602`: provenance is durable, decoded before leasing, and mixed batches preserve senders under `unknown`.
- FIXED #7 — `app/events.py:81`: stored `senders` must be a JSON array.
- FIXED #8 — `app/db.py:2503`: missing or corrupt provenance raises instead of synthesizing `unknown`.
- FIXED #9 — `app/static/js/chat.js:3918`: keys, sender arrays, and optional field types are validated before user rendering.

## Findings (blocking/suggestion/question)

blocking: app/db.py:1153 — Legacy mailbox rows with an empty sender have no trusted provenance, but the automatic backfill assigns them `origin=user`. The old ingress allowed senderless internal requests, so an untrusted historical row can become a human/right-side message after upgrade. Empty-sender legacy rows must migrate to explicit `unknown`.

blocking: app/rag.py:594 — Corrupt `origin_detail` is replaced independently while the original `origin` is retained. Thus malformed JSON, a non-object detail, or missing senders combined with `origin=user` is still indexed as `user_msg`. Decode origin and detail atomically through `MessageProvenance.from_storage`; corruption must fail or become wholly non-user.

blocking: scripts/migrate_message_provenance_433.py:499 — Manifest receipt checking occurs before `BEGIN IMMEDIATE` and is not repeated after acquiring the lock. Two concurrent script revisions can both observe “not applied”; the second then applies drifted rules while `ON CONFLICT DO NOTHING` preserves the first digest. Recheck the receipt under the write lock before backup or mutation.

blocking: scripts/migrate_message_provenance_433.py:531 — Pre-commit receipt validation checks only that no schema-version-1 rows remain. An `AFTER UPDATE` trigger can rewrite `payload_hash` while leaving `rowcount=1` and `schema_version=2`; `_plan()` never validates receipt hashes, so the corrupt receipt commits and all retries conflict. Reload and recompute every upgraded receipt before recording the migration.

## Verdict

NEEDS WORK. All Round 1 blockers are resolved, but four correctness-critical gaps remain in legacy mailbox attribution, corrupt read projection, manifest-race refusal, and migrated-receipt validation.

The envelopes are structured now; unfortunately, two migrations and one projection still moonlight as the post office. 📬

## Round (2026-09-02T05:32:32Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Summary

A–C are fixed. D remains vulnerable because receipt validation runs before later trigger-capable writes. Naturally, the final integrity check checks integrity before the transaction is finished. 🙃

Read evidence: `"Classify a log from stored provenance; content is never authority."`

## Findings (blocking/suggestion/question)

- FIXED A — `app/db.py:1153`: empty-sender legacy mailbox rows now become explicit `unknown`.
- FIXED B — `app/rag.py:263`: origin and raw detail are decoded atomically through `MessageProvenance.from_storage`.
- FIXED C — `scripts/migrate_message_provenance_433.py:532`: manifest receipt is rechecked under `BEGIN IMMEDIATE`, before backup or mutation.
- STILL BROKEN D — `scripts/migrate_message_provenance_433.py:564`: receipt hashes are validated before log updates and migration-receipt insertion. An `AFTER UPDATE ON logs` or receipt-insert trigger can subsequently alter a receipt hash; `_plan()` does not validate hashes, so the corrupted receipt reaches commit and later retries conflict.

blocking: scripts/migrate_message_provenance_433.py:564 — Repeat or move `_validate_receipt_hashes()` after every trigger-capable write, including the migration-receipt insertion, immediately before `commit()`.

No additional findings.

## Verdict

NEEDS WORK. Three Round 2 blockers are closed; receipt validation ordering leaves one correctness-critical migration hole.

The seal is valid—the envelope just goes through another stamping machine afterward. 📬
