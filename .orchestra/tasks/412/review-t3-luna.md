<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

Apparently a one-project manifest can still call itself an 18-project cutover—efficient bookkeeping 😏 The T3 test passes (`1 passed`), and Aperant’s ignored ledger verifies (`112` records), but the diff is not safe to merge.

## Findings

blocking: [P1] Validate the complete live project map before switching ownership  
**File:** `scripts/activate_project_knowledge.py:93-96` | **Confidence:** 0.99

Activation accepts any non-empty project list and never compares it with the authoritative 18-project scope map. A self-consistent one-project manifest succeeds and persists `project-local`; the real runtime then rejects the persisted map at startup, causing an outage. Validate the full normalized project-ID/root map before writing state.

---

blocking: [P1] Make receipt failure unable to commit the owner switch  
**File:** `scripts/activate_project_knowledge.py:154-161` | **Confidence:** 0.99

`activate()` persists `project-local` before creating the optional receipt. If the receipt already exists or cannot be written, the CLI exits 2 while the owner switch remains active; the runtime does not require the receipt. Stage the receipt first or roll back the state on receipt failure.

---

blocking: [P1] Validate record path and payload identity during activation  
**File:** `scripts/activate_project_knowledge.py:60-68` | **Confidence:** 0.98

The digest covers `stable_id` and bytes but not the destination path or decoded record identity. A record can be stored under the wrong UUID filename and still pass activation; later `_checked_record()` rejects it, making local queries fail after a successful cutover. Require the exact path and matching `project_id`/`stable_id` in the JSON payload.

---

blocking: [P1] Make record creation atomic  
**File:** `app/ia/project_knowledge.py:239-247` | **Confidence:** 0.99

The final record path is opened before writing. A process kill or ordinary write failure can leave partial JSON; retries then report a permanent conflict, and queries fail while scanning the damaged file. Write to a temporary file, fsync it, atomically replace the destination, and clean up on errors.

---

blocking: [P1] Make owner-state replacement crash-durable  
**File:** `app/ia/project_knowledge.py:49-56` | **Confidence:** 0.97

The temporary state file and containing directory are never fsynced before `os.replace()`. A power loss after a successful activation can lose the owner transition or leave startup with missing/corrupt state. fsync the temporary file and parent directory before reporting success.

---

suggestion: [P2] Route canonical fact records to the facts namespace  
**File:** `app/ia/project_knowledge.py:209-213` | **Confidence:** 0.99

The canonical record type is `knowledge.fact`, but `startswith("fact")` is false, so `write_record()` stores facts under `evidence`. Use an explicit `record_type == "knowledge.fact"` check.

## Verdict

**Overall Correctness:** ❌ Incorrect | **Confidence:** 0.99

The named oracle does not cover activation completeness, receipt ordering, crash durability, or malformed ledger identity. Merge is blocked by the five P1 findings.

Currently this is an 18-project cutover with a one-project safety harness and a receipt written after the fire alarm 🔥

## Round (2026-08-28T06:28:29Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

Round 2: the six prior blockers are addressed and the combined T3/review suite passes (`6 passed`). Unfortunately, the receipt can still celebrate a cutover that failed halfway 😏

## Findings (blocking/suggestion/question)

Prior findings:

- FIXED — complete distribution map is compared with the authoritative scope registry.
- FIXED — receipt is written before activation and removed on ordinary activation failure.
- FIXED — evidence path and JSON identity are validated.
- FIXED — record writes use a fsynced temporary file and atomic link.
- FIXED — owner state fsyncs both file and directory.
- FIXED — `knowledge.fact` routes to `facts`.

NEW BUG:

blocking: [P1] Roll back owner state after post-replace failure  
**File:** `scripts/activate_project_knowledge.py:235-244` | **Confidence:** 0.99

`router.activate()` replaces the owner state before directory fsync. If that fsync fails, activation raises, deletes the receipt, but leaves `active_owner=project-local` persisted. The CLI reports failure while the next runtime starts in local mode without a receipt. Restore the previous state atomically before returning the failure.

---

blocking: [P1] Write activation receipts atomically  
**File:** `scripts/activate_project_knowledge.py:66-75` | **Confidence:** 0.98

The receipt is written directly to its final path. A process crash during the write can leave a partial receipt; subsequent activation sees `FileExistsError` and cannot retry. Use a same-directory temporary file plus fsync, atomic rename, and directory fsync.

---

suggestion: [P2] Snapshot or lock the ledger during activation  
**File:** `scripts/activate_project_knowledge.py:189-198` | **Confidence:** 0.91

The ignored records are verified, then only Git `HEAD` is rechecked before activation. A concurrent write to `docs/kb` can therefore produce a receipt for bytes different from those later queried by runtime. Lock or revalidate the manifests and records immediately before persisting ownership.

## Verdict

**Overall Correctness:** ❌ Incorrect | **Confidence:** 0.98

The original findings are fixed, but the new P1 rollback and receipt-corruption paths still block approval. This cutover now has better paperwork—but the paperwork can still outlive the transaction.

## Round (2026-08-28T06:34:01Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

Round 3: all three Round-2 findings are FIXED, and the combined suite passes (`9 passed`). One new blocker remains: the receipt conflict path deletes the existing receipt—because apparently “no clobber” needed a tiny exception 🧨

## Findings (blocking/suggestion/question)

Round-2 status:

- FIXED — owner-state rollback after post-replace failure.
- FIXED — atomic receipt publication.
- FIXED — ledger revalidation immediately before activation.

Previous fixes remain intact: authoritative map validation, record identity checks, atomic record writes, durable owner state, and `knowledge.fact` namespace routing.

NEW BUG:

blocking: [P1] Preserve an existing receipt on publication conflict  
**File:** `scripts/activate_project_knowledge.py:79-86` | **Confidence:** 1.00

When `os.link()` raises `FileExistsError`, the handler re-raises but the outer `except` unconditionally executes `path.unlink()`, deleting the pre-existing receipt. A direct probe reproduces `KnowledgeOwnerError` with `exists=False`; the regression test misses this because it checks only owner state. Restrict cleanup to receipts successfully published by this invocation.

## Verdict

**Overall Correctness:** ❌ Incorrect | **Confidence:** 0.99

The Round-2 blockers are closed, but this new P1 destroys prior activation evidence on a normal receipt-conflict path. Not approved.

The receipt now has atomic delivery, rollback, and one-way ticket punching—like a fire escape that removes the previous evacuation map.
