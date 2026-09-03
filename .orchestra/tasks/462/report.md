# #462 — T1–T3 checkpoint report

## Result

T1–T3 are implemented and committed. T4 is untouched. The new review-coverage code is physically present but inactive because the canonical `codex-debate` skill does not contain the `review-coverage-v1` marker.

Production scope is `app/** OR scripts/**`. A qualifying implementation review is bound to the exact target SHA and versioned raw Git production diff; task/session identity alone cannot authorize it. The same #436 receipt table now represents three coverage outcomes:

- `reviewed`: completed implementation review with artifact and JSONL response;
- `skipped`: server-authenticated orchestrator decision, idempotent by `decision_id`;
- `unavailable`: only machine-known `weekly_quota_blocked` or `codex_binary_missing` with execution `status=failed`.

`interrupted`, generic `failed`, `timed_out`, stale snapshot, foreign session, plan/research review, and worker-authored report prose do not qualify.

## Tickets

### T1 — done

- Added `app/review_coverage.py` production snapshot owner.
- Added `codex_review(mode="implementation")`; caller target is forbidden, server resolves clean committed target/head and sends the exact `git diff --binary --full-index <target>...<head>` command.
- Extended #436 receipt schema through idempotent live `PRAGMA table_info`/`ALTER TABLE` migration; legacy rows default to `unknown` and cannot qualify.
- Successful implementation finalization publishes `coverage_outcome=reviewed` only with artifact + terminal agent response.

### T2 — done

- Quota and missing-binary preflights durably finish a snapshot-bound receipt as `coverage_outcome=unavailable` before returning the typed refusal.
- `record_review_outcome(outcome="skipped")` delegates to server endpoint `/api/merge-operations/review-skip`; local `ORCHESTRA_ROLE` is not authority.
- Endpoint uses existing MCP proof/cookie privilege, resolves the target worker on the server, binds target/head/snapshot, and makes same-`decision_id` replay idempotent while rejecting payload drift.

### T3 — done

- Admission pins production paths, snapshot, outcome, and receipt id beside the existing target/oracle evidence.
- Missing coverage under an active policy returns `REVIEW_COVERAGE_MISSING` before operation insertion/runner/Git.
- A pending admission saved as `not_active` is re-evaluated at execution when the marker appears; a missing receipt stops before `execute_merge_session`.

### T4 — pending, not touched

Both skill files are byte-identical to `main` and the delivery check remains RED. Activation requires checkpoint merge, restart, and the two requested live calls first.

## Files

Checkpoint production/test diff from `95c5b8d6`: **8 files, +690/-16**.

- `app/review_coverage.py`
- `app/db.py`
- `app/mcp_stdio.py`
- `app/codex_review_artifact.py`
- `app/routes/merge_operations.py`
- `app/merge_operations.py`
- `scripts/migrate_review_receipts.py`
- `tests/route_surface_snapshot.json`

Frozen tests and T4 delivery check remain byte-identical to oracle commit `41456f2afbab`.

## Verification

- Phase-3 RED before T1: `3 failed`; after T1: `3 passed`.
- Phase-3 RED before T2: `4 failed`; after T2: `4 passed`.
- Phase-3 RED before T3: `9 failed / 6 controls passed`; after T3: `15 passed`.
- Full frozen #462 oracle: `22 passed in 3.18s`.
- Legacy #436 receipt/storage/outcome/migration safety: `6 passed in 2.39s` after T1.
- Affected common suite on branch: `306 passed, 2 failed in 25.17s`.
- The byte-identical command on clean pre-task main `f3c2eaaa`: `306 passed, 2 failed in 16.75s`; failing node IDs are identical parameterizations of `test_t386_t1_public_operation_pins_target_and_task_oracle_before_runner`, caused by the pre-existing live `progress` overlay mismatch. New failures: **0**.
- `py_compile` on all changed Python modules: exit 0.
- Inactive-policy probe: `policy_active() is False`; a production decision returns `status=not_active, required=False`.
- T4 check remains RED on the three absent anchors, proving the skill/prompt was not activated early.
- Route-surface pre-update delta: added exactly `POST /api/merge-operations/review-skip`; removed routes: none. The same snapshot test on clean `main` `ccab874e` was green (`1 passed in 1.96s`); after the one-entry snapshot update the branch file is green (`2 passed in 2.19s`).

## Pre-mortem

1. **Old live #436 schema rejects the first new insert.** Check: frozen test starts from the exact old table and verifies all eight additive columns after `init_db`; green.
2. **Plan/research or stale implementation receipt authorizes later code.** Check: qualifying rows require `subject_kind=implementation`, exact target SHA and independent raw-diff hash; stale/foreign matrix is green.
3. **Worker self-issues skip.** Check: server route validates live MCP proof + orchestrator session; worker proof returns 403; target session/head/snapshot are asserted.
4. **Timeout or generic provider failure becomes unavailable.** Check: only two exact failure codes qualify; wrong code, interrupted, failed-reviewed, and timed-out-reviewed controls are green.
5. **Policy activates after operation admission.** Check: pending `not_active` operation revalidates and the executor mock is never awaited.
6. **Prompt starts requiring unavailable code.** Check: canonical/native skill files unchanged and activation check remains RED; live calls are mandatory before T4.

## Review

Luna implementation review timed out after 600 seconds with three intermediate messages and no final finding/verdict. The preserved evidence is `review-implementation-luna.md`. No unchanged-artifact retry was opened: **вердикта нет**.

## Checkpoint / remaining work

Required next steps are external to this branch checkpoint:

1. Merge with `task_outcome=continue` and restart so Python/MCP owners load.
2. Run real `codex_review(mode="implementation")`; inspect the durable receipt.
3. Run real structured skip through `record_review_outcome`; inspect its target-bound receipt.
4. Confirm live no-marker admission reports `not_active` and does not block.
5. Only after those three live proofs may the orchestrator authorize T4.

Breaking behavior at this checkpoint: **none while marker absent**.
