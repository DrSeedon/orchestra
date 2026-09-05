<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

😏 Naturally, the universal authorization gate still has three ways to trust the wrong delta.

## Summary

Reviewed the pinned `eb75808...dc434d6` diff across all six scoped files. The targeted suite passes: 45 tests. Three authorization bypasses remain.

## Findings

### [blocking] Compute the delta using the reviewed and current merge snapshots

**File:** `app/review_coverage.py:208-218`

`reviewed_head..worker_head` compares only the two worker trees, while admission evaluates `target...worker_head`. After review, the worker can merge a newer target and resolve a target file back to its old worker-tree contents. That file changes in the eventual merge result but is absent from the two-dot delta. A valid finding plus a freshly signed current digest then yields `status="satisfied"` without review of that production change. Attestation should either require the receipt’s target SHA to equal the current target SHA or compare the reviewed and current three-dot snapshots directly.

---

### [blocking] Restrict allowed paths to the declared closed findings

**File:** `app/review_coverage.py:201-219`

`closed_findings` is checked only for non-emptiness and membership, but `allowed` is built from every finding in the artifact. If the reviewer reported findings in `app/helper.py` and `app/widget.py`, the author can declare only the helper finding closed while changing widget; the gate still accepts it. Build `allowed` from the validated `closed` entries, otherwise one genuine anchor authorizes changes in every file mentioned during the round.

---

### [blocking] Do not normalize distinct finding paths into production paths

**File:** `app/review_coverage.py:218`

Passing finding paths through `production_paths()` applies `lstrip("./")` and backslash conversion. Consequently `.app/admin.py`, `../app/admin.py`, or `app\\admin.py` from the artifact becomes `app/admin.py`, allowing a production file the reviewer never named. Require exact repository-relative POSIX paths and reject backslashes and `.`/`..` components before constructing `allowed`.

## Verdict

**Reject.** The implementation fails closed in ordinary cases, but crafted Git history and path/finding inputs can still produce `status="satisfied"` for an unreviewed current production diff.

A universal gate with three spare keys under the mat is certainly universal. 🔑

## Round (2026-09-04T16:12:13Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

😏 Three old holes are closed; naturally, the new lock brought two fresh keys.

## Summary

Prior blockers:

- **FIXED** — delta now compares reviewed and current production snapshots.
- **FIXED** — `allowed` is derived only from declared `closed_findings`.
- **FIXED** — non-canonical finding paths are rejected instead of normalized.

`tests/test_review_authorship_493.py`: **17 passed**.

## Findings

### [blocking] Use unabbreviated object IDs in raw diff records

**File:** `app/review_coverage.py:154-156`

`--full-index` does not expand object IDs in `--raw` output. In this repository the helper receives only 8 hex characters per blob; `--no-abbrev` produces 40. An author can cheaply generate benign and malicious blob variants sharing a 32-bit prefix, keeping the mode, status, and path identical. Both snapshots then produce the same record despite different contents, so the gate misses the production change. The existing `production_snapshot()` command has the same weakness and must use unabbreviated IDs as well.

---

### [blocking] Do not let an older receipt override a newer review

**File:** `app/review_coverage.py:441-456`

`_attested_decision()` examines up to 20 receipts and returns the first one matching the single attestation file. An author can retain distinct artifacts for R1 and R2, receive a newer disputed or unresolved R2, then modify a file named by an accepted R1 finding and attest against R1. R2 merely produces `attestation_receipt_mismatch`; iteration continues until R1 returns `status="satisfied"`. Only the latest qualifying review receipt may authorize the current post-review delta.

---

### [suggestion] Distinguish an invalid attestation from an absent one

**File:** `app/review_coverage.py:213-218`

Malformed JSON, an unreadable existing file, and a non-object document are all reported as `attestation_missing`; `_attested_decision()` then suppresses that reason and returns `review_receipt_missing`. This gives the operator the wrong repair action—rerun review instead of repairing the committed attestation. Suppress only `FileNotFoundError`; existing but invalid or unreadable files need a distinct `attestation_invalid`/`attestation_unreadable` refusal.

## Verdict

**Reject.** All three round-1 findings are fixed, but abbreviated blob IDs and fallback to older receipts still permit `status="satisfied"` without coverage from the latest real review.

The old spare keys are gone; the locksmith simply numbered the new ones “R1” and “8 hex.” 🔑

## Round (2026-09-05T03:12:21Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

😏 The lock is stronger; the clock still decides which key is “latest.”

## Summary

Prior round-2 findings:

- **FIXED** — both raw-diff producers now use full object IDs.
- **STILL BROKEN** — only one receipt is considered, but completion-time ordering can still select an older round.
- **FIXED** — corrupt and absent attestations now have truthful, distinct reasons.

The targeted verification passed: **44 tests**. Raw R/C framing, mode/type/gitlink records, newline/surrogate paths, and empty production diffs did not reveal another satisfaction bypass.

## Findings

### [blocking] Select the latest review round, not the latest completion

**File:** `app/review_coverage.py:450-464`

Rows are ordered primarily by `completed_at`, so concurrent reviews can invert their semantic order: R1 starts first and runs slowly, R2 starts later and finishes disputed, then R1 finishes last. The code selects accepted R1 as `latest`, allowing its attestation to override newer R2. The receipt already carries the server-assigned `round`; select the highest qualifying round, with a deterministic tie-breaker, instead of completion time.

---

### [suggestion] Do not claim server restart atomically reloads MCP writers

**File:** `.orchestra/tasks/493/report.md:135-140`

`mcp_stdio.py` runs in a separate process created when an agent connects, and an already-running process can retain the old `review_coverage` module across an Orchestra server restart. It can therefore continue writing abbreviated-hash receipts while the restarted gate expects full hashes; another `codex_review` in that same process will not repair the mismatch. The deployment note should require reconnecting affected workers or otherwise reloading their MCP process.

## Verdict

**Reject — unresolved at the round ceiling.** Full object identity and truthful attestation errors are fixed, but an older review can still supersede a newer round through completion-order inversion.

Apparently “latest review” was outsourced to whichever stopwatch stops last. ⏱️
