<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

Apparently green focused tests are still not a transaction manager. 😏

## Summary

Reviewed only `/tmp/kb-409.diff`; no files were edited and no history, logs, or unrelated files were inspected. The supplied tests cover the intended happy paths, but the diff has 7 concrete issues around partial writes, retries, preflight proof, identity, and API semantics.

## Findings

### blocking: [P1] Make evidence linking and archive writes recoverable as one operation

**File:** `app/ia/knowledge.py:789-798` | **Confidence:** 0.97

The task evidence link is persisted before the canonical evidence record and archive index writes. A crash or filesystem error afterward leaves task state pointing at incomplete canonical evidence; if the record exists but the index write failed, retry reaches the existing-record consistency check and fails instead of repairing the import. Link/archive writes need transactional ordering or explicit rollback/recovery.

### blocking: [P1] Do not treat a fact filename as proof of completed import

**File:** `scripts/kb_promote_facts.py:172-181` | **Confidence:** 0.96

`_existing_ids()` considers any matching filename an existing fact, and `main()` excludes those facts from `pending`. If a previous run created the fact file but missed task evidence linking, a retry reports zero new work and never calls `import_evidence`; malformed or stale files are skipped the same way. Existing facts must be content-validated and their evidence link reconciled before being classified as complete.

### blocking: [P1] Validate the import request during preflight

**File:** `scripts/kb_promote_facts.py:357-362` | **Confidence:** 0.98

Preflight validates only the promotion payload, not the `import_evidence` payload or its source-path allowlist. A fact backed by `README.md` or `AGENTS.md` can therefore be reported as ready in dry-run when the service will reject it; apply may still commit earlier facts before reaching that failure. The script must mirror the import validator, including the new `CLAUDE.md` exception.

### blocking: [P1] Verify the selected canonical task’s stable identity

**File:** `scripts/kb_promote_facts.py:140-148` | **Confidence:** 0.91

Tasks are selected by `display_number`, but the loaded state’s `stable_id` and `project_id` are trusted without checking them against the canonical task directory and requested project. A corrupted or repaired state for task `#399` could therefore produce a URI for another valid task and attach evidence to the wrong owner. The live identity gate needs to validate the complete task identity before applying.

### suggestion: [P2] Reject conflicting facts that collapse to one stable ID

**File:** `scripts/kb_promote_facts.py:95-101` | **Confidence:** 0.88

The stable ID excludes `topic`, `status`, and other source metadata. Two input facts with the same source path, lines, and statement but different topics or evidence silently share one idempotency key; the first promotion wins and the others become no-ops. Detect duplicate stable IDs during preflight and reject conflicting payloads.

### suggestion: [P2] Preserve missing decision dates instead of fabricating one

**File:** `scripts/kb_promote_facts.py:228-231` | **Confidence:** 0.95

`decided_at: null` passes source validation but becomes `2026-08-26` in both `valid_from` and `observed_at`. That invents provenance and becomes stale on later runs. Reject a missing date or preserve it explicitly as unknown.

### suggestion: [P2] Honor `expected_head` in the runtime adapter

**File:** `app/ia/runtime.py:166-173` | **Confidence:** 0.92

The new method accepts `expected_head` but always forwards `self._store.canonical_head`. Any caller supplying a stale head therefore bypasses the intended optimistic-concurrency check. Forward the supplied value when present, or remove the parameter from the adapter contract.

## Verdict

**Overall Correctness:** ❌ Incorrect | **Confidence:** 0.96

The happy-path implementation is covered, but the persistence and batch gates are unsafe under partial failure, stale canonical state, and invalid input. The diff needs changes before the 764-fact apply.

The importer currently treats a filename like a birth certificate and a Git SHA like a calendar—until the first retry.

## Round (2026-08-26T10:05:10Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

Apparently the importer now checks the paperwork—but forgot to make the final signature legally binding. 😏

## Summary

Round 1 status:

- FIXED — recovery: `app/ia/knowledge.py:778-810`
- FIXED — existing-chain validation: `scripts/kb_promote_facts.py:189-300`, `610-622`
- FIXED — import preflight: `scripts/kb_promote_facts.py:490-496`
- FIXED — task identity: `scripts/kb_promote_facts.py:149-164`, `449-452`
- FIXED — duplicate stable IDs: `scripts/kb_promote_facts.py:433-441`
- FIXED — null decision date metadata: `scripts/kb_promote_facts.py:343-370`
- FIXED — unused runtime `expected_head`: `app/ia/runtime.py:166-173`

The supplied test and mutation results are consistent with these fixes. Two new blockers remain.

## Findings

### blocking: [P1] Gate success on canonical completion

**File:** `scripts/kb_promote_facts.py:695-704` | **Confidence:** 0.97

`canonical_complete_count` is only printed; the final return still checks only `failures` and resource inventory. If an idempotent API response leaves a fact chain incomplete—for example, a prior promotion receipt exists but its fact record is missing—the script can exit `0` while `canonical_batch_complete < len(ready)`. Apply must fail unless every ready fact is complete.

### blocking: [P1] Fail closed on malformed archive metadata

**File:** `scripts/kb_promote_facts.py:284-290` | **Confidence:** 0.96

`_completion_state()` calls `_json(index_path)` and iterates `evidence_refs` without catching malformed JSON, non-object entries, or an invalid container type. This runs after the preflight exception guard, so a damaged archive index crashes dry-run/apply instead of producing a controlled conflict or retryable incomplete state.

### blocking: [P1] Validate resource identity before sorting matches

**File:** `scripts/kb_promote_facts.py:469-475` | **Confidence:** 0.93

The match filter does not require `stable_id`, but the sort immediately indexes `item["stable_id"]` before the later identity check. A matching malformed resource record therefore raises `KeyError` and aborts the batch instead of being rejected as invalid canonical evidence.

## Verdict

**Overall Correctness:** ❌ Incorrect | **Confidence:** 0.97

Round 1 findings are addressed, but the apply path still permits a false-success batch and crashes on malformed canonical metadata.

A completion counter that doesn’t close the gate is just a scoreboard in a burning archive. 🔥

## Round (2026-08-26T10:09:51Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

Round 2 blockers are fixed; the archive still has one version-check hole. 😏

## Summary

- FIXED — completion-count gate: `scripts/kb_promote_facts.py:581-587`, `755-757`
- FIXED — malformed archive handling: `scripts/kb_promote_facts.py:297-310`
- FIXED — resource validation before sorting: `scripts/kb_promote_facts.py:215-225`, `489-496`

Supplied focused/regression results are consistent with the fixes.

## Findings

### blocking: [P1] Validate the archive index version during completion checks

**File:** `scripts/kb_promote_facts.py:297-305` | **Confidence:** 0.97

`_completion_state()` validates that `evidence_refs` is a list of objects but never checks `index_version`. An otherwise matching `archive-index.json` with an unsupported version is therefore classified as complete, allowing dry-run/apply to skip repair and return success while production `KnowledgeService` would reject the index. Mirror the production `index_version == 1` check.

## Verdict

**Overall Correctness:** ❌ Incorrect | **Confidence:** 0.97

One blocking proof-bound validation gap remains; final approval is not warranted.

The archive now checks whether the index is a list, but still forgets to ask which century it belongs to. 🗃️
