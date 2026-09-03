## Summary

Naturally, the omitted excerpt is the one the new classifier explicitly requires 🙃

Verified successfully:

- Counts: 33 entries, 32 candidates, 1 exclusion; 23 numeric and 9 owner-confirmed skips.
- 124 evidence records / 108 unique log IDs; all six new records match SQLite hashes, excerpts, timestamps, types, and sessions.
- 33 target refs and 1 source ref resolve exactly, with no missing or unexpected refs.
- Source/target stable patch-id matches: `6332a138486d9e4cbe8495de7a01ab8dddce699d`.
- `9ff4a7f…` is an ancestor of both current `main` and recorded frozen head `c5f1d0d…`.
- No manifest target appears in `tm_tasks.git_commits`.
- JSON SHA-256 matches `12668aafeed26ac00b04a7dd520e08e4eb53f82946c38f5f67bc85250f7a1f6d`.
- Documentation counts and dispositions are consistent; the uncertainty about unexpressed human intent remains preserved.

## Findings

### blocking — Retain proof that the cherry-pick branch was created from `main`

**File:** [recovery-input.json:2134](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-merge/docs/tasks/115/recovery-input.json:2134)

The stored excerpt contains only `git cherry-pick 35f0229`, while the new classifier explicitly requires a fresh branch created from the recorded target branch at [line 2210](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-merge/docs/tasks/115/recovery-input.json:2210). SQLite log `372616` currently supplies the missing commands—`git branch -f fix-pe-35f0229 main` and checkout—but its content hash cannot reconstruct them after log pruning. This leaves the authoritative snapshot dependent on disposable live evidence.

Exact fix: expand the retained excerpt to include branch creation, checkout, and cherry-pick. Because `git branch -f` suppressed errors and was not chained with `&&`, also persist the verified pre-integration `main` OID (`6926fea…`) or equivalent retained fast-forward evidence. Then update the JSON SHA in `report.md`.

## Verdict

**REQUEST_CHANGES**

The recovery entry itself matches Git and SQLite, but the immutable artifact does not preserve every fact required by its own post-cutoff classifier. No other extension-specific issue was found.

An immutable evidence file that needs the pruneable database to explain itself is, naturally, a very authoritative sticky note.

## Round (2026-08-01T10:31:01Z)

## Summary

Miraculously, evidence survives pruning once it is actually stored in the artifact 🙃

Prior blocking finding: **RESOLVED**.

- Retained excerpt now includes branch creation, checkout, and cherry-pick, and exactly matches hashed SQLite content.
- Recorded base OID equals `9ff4a7f…`’s sole parent.
- Patch IDs, protected refs, ancestry, counts, and dispositions remain correct.
- JSON SHA-256 matches the updated report.
- Round 1’s uncertainty about unexpressed human intent remains unaffected.

## Findings

No blocking, suggestion, or question findings.

## Verdict

**APPROVE**

The lineage is now self-contained and no longer needs pruneable SQLite state to establish the fresh-branch chain. This time the archive carries the receipt instead of pointing at a cashier who may disappear.
