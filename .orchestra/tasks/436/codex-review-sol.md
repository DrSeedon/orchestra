<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Summary

Naturally, the safety backup arrives after the first live mutation. 🧨 The provenance columns themselves remain non-NULL and cannot be silently promoted, and SQLite round allocation is atomic. However, four corruption risks block approval.

## Findings

### blocking — Create a durable backup before `init_db()`

[review436-sol-input.txt:99](/tmp/review436-sol-input.txt:99)

`init_db()` can create or migrate the live schema before `source.backup(snapshot)` runs. Additionally, the backup destination is `:memory:` and is destroyed in `finally`, leaving no recoverable pre-migration copy. Every successful `--apply --confirm-live` can therefore reach production data without a surviving prior backup.

### blocking — Require artifact hashes before accepting apply

[review436-sol-input.txt:46](/tmp/review436-sol-input.txt:46)

Both integrity fields are optional. A manifest without `sha256` and `size_bytes` passes `_check_drift()`, while omitting only `sha256` allows same-size changes through. Such an apply records stale or substituted artifact provenance instead of refusing drift.

### blocking — Refuse conflicting replays instead of silently ignoring them

[review436-sol-input.txt:54](/tmp/review436-sol-input.txt:54), [review436-sol-input.txt:109](/tmp/review436-sol-input.txt:109)

A bit-for-bit repeat is idempotent, but a changed manifest with the same path and round hits `ON CONFLICT(receipt_id) DO NOTHING`; the command exits successfully and prints the changed candidate receipt although the database retained the old values. For entries without a round, identity also depends on list ordinal, so reordering an equivalent manifest creates new duplicate receipts. Existing rows must be compared with the complete candidate payload and any mismatch must abort the transaction.

### blocking — Isolate scratch files by reserved round

[review436-sol-input.txt:418](/tmp/review436-sol-input.txt:418), [review436-sol-input.txt:470](/tmp/review436-sol-input.txt:470)

`BEGIN IMMEDIATE` correctly serializes `MAX(round) + INSERT`, but simultaneous jobs for the same worker and artifact reuse identical JSONL, prompt, return-code, and `.round` files. One job can overwrite or consume another job’s output, associating an atomically reserved receipt round with the wrong evidence. Include `receipt_id` or `receipt_round` in every per-execution scratch path.

## Verdict

**REJECT — 4 blocking findings.** Provenance values and database round numbering are guarded correctly, but backup ordering, replay validation, manifest integrity, and job-file isolation can still lose or corrupt provenance.

The receipts have unique round numbers, while the jobs are still writing on the same receipt paper. 🧾

## Round (2026-09-02T03:13:07Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Round 3

### Re-review status

Well, the receipts have separate desks now; the finalizer still uses one typewriter. 🧾

1. **FIXED — backup ordering:** durable `sqlite3.Connection.backup()` now runs before `init_db()`, and inserts share one rollback-capable transaction.
2. **FIXED — manifest integrity:** apply requires valid size and SHA-256 fields and verifies both.
3. **FIXED — replay/conflict:** stable IDs and complete-row comparison reject conflicting provenance.
4. **STILL BROKEN — simultaneous artifact rounds:** scratch files are UUID-scoped, but final persistence remains an unlocked read-modify-replace operation using shared temporary filenames.

MCP decorators remain intact, the outcome CAS still prevents overwriting a decided outcome, and historical `derived`/`unknown` provenance remains distinct.

### New findings

**blocking / STILL BROKEN:** [app/codex_review_artifact.py:206](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-review-receipts/app/codex_review_artifact.py:206) — simultaneous rounds read the same prior artifact and both write `output.name + ".tmp"` before replacing the durable output. The sessions manifest repeats the same race at [app/codex_review_artifact.py:225](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-review-receipts/app/codex_review_artifact.py:225). One finalizer can overwrite another’s round, lose a session update, fail after another process moves the shared temporary file, or record a receipt hash for the wrong output. Persistence must be serialized per artifact or use a transactional round store followed by ordered materialization.

**blocking / NEW BUG:** [scripts/migrate_review_receipts.py:109](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-review-receipts/scripts/migrate_review_receipts.py:109) — `_backup_database()` opens the destination without refusing an existing or aliased path. A repeated apply overwrites the default pre-migration backup with the already-migrated database; an explicit existing SQLite `--backup-path` can also be destroyed. Require a new, distinct backup path or generate an immutable unique path.

### Verdict

**NEEDS WORK.** Three prior blockers are fixed, but simultaneous rounds can still corrupt artifact/session provenance, and repeated apply can destroy the only original rollback image.

`git diff` and `git diff --cached` were both empty, so this re-review used the current target implementations rather than an uncommitted patch. The round tickets are unique; the baggage carousel still swaps the suitcases. 🧳
