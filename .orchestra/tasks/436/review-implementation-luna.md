<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

Apparently the receipts are ready to audit history—provided history happens to be the previous round 🧾

## Summary

The DB round counter is serialized, but artifact handling and migration safety are not. Review is not merge-ready: 6 blocking findings and 2 suggestions. No tests run; review was limited to the supplied diff.

## Findings

### blocking: A failed round can record the previous round’s artifact

**File:** `app/codex_review_artifact.py:57-66`

`_record_terminal_receipt()` hashes `output` solely by path. Resume rounds reuse `output_abs`, so if Codex exits or finalization fails before writing the new round, the receipt records the prior round’s artifact, verdict, and hash as facts for the failed round. Record only artifacts produced by the current round or use per-round artifact paths.

### blocking: Historical receipt IDs collapse distinct rounds

**File:** `scripts/migrate_review_receipts.py:56-56`

The legacy ID hashes only `path`, excluding `round`, scope, and project root. Multiple historical rounds using one artifact path therefore receive the same primary key; `INSERT OR IGNORE` silently drops later records. The ID must include the full provenance identity, and collisions must fail loudly.

### blocking: Migration silently reports skipped rows as applied

**File:** `app/db.py:2706-2707`

`INSERT OR IGNORE` suppresses `CHECK`, `NOT NULL`, and uniqueness failures, while the migration ignores the returned boolean at `scripts/migrate_review_receipts.py:130-134` and prints every receipt as applied. A malformed or conflicting manifest row can disappear without an error. Use conflict-specific handling and fail on any non-idempotent insertion failure.

### blocking: Apply is neither atomic nor backed up

**File:** `scripts/migrate_review_receipts.py:92-100`

The SQLite snapshot is created inside `TemporaryDirectory` and deleted immediately, so it cannot restore anything. Receipts are then inserted through separate `_conn()` transactions with no transaction spanning the migration; a later failure can leave a partial import with no usable rollback.

### blocking: Reserved rounds do not isolate scratch files

**File:** `app/mcp_stdio.py:3760-3768`

The receipt round is unique in SQLite, but overlapping reviews for the same output still share `round_tmp`, `jsonl_file`, and the output path. One job can delete or overwrite another job’s JSONL/round data, causing receipts to contain the wrong review. Scratch paths need the receipt ID, or execution needs an explicit per-artifact lock.

### blocking: Killed jobs never finalize their receipts

**File:** `app/mcp_stdio.py:3784-3791`

All terminal updates run only after the Codex process returns. If the background runner terminates the shell for a timeout or interruption, none of these commands execute and the receipt remains `requested` indefinitely; the new `timed_out` and `interrupted` statuses are never used. Timeout/interruption handling must live in a runner-level hook or a signal-safe lifecycle path.

### suggestion: The outcome CAS can falsely report success

**File:** `app/db.py:2811-2818`

Two concurrent callers can both read `unknown`; one wins the conditional update, while the loser gets zero affected rows, reads the winner’s value, and returns it as if its own outcome was recorded. Check the update row count and reject a conflicting loser.

### suggestion: Dry-run skips the validation that apply performs

**File:** `scripts/migrate_review_receipts.py:118-125`

`--dry-run` does not call `_check_drift()`, so it succeeds for missing or changed artifacts even though the subsequent apply will fail. Dry-run should perform the same read-only existence and hash checks.

## Verdict

❌ Needs work. The implementation has multiple data-loss and provenance-confusion paths, especially around failed/resumed rounds and historical migration.

Right now this is less an audit trail than a filing cabinet that sometimes files yesterday’s folder under today’s date.
