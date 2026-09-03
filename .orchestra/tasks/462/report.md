# #462 — final report

## Result

T1–T3 were checkpoint-merged as `1a86f403` and live-verified before prompt activation. T4 now adds the `review-coverage-v1` marker and the operational route to the canonical `codex-debate` skill; after this final merge, review coverage is active without any new `app/**` or `scripts/**` diff.

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

### T4 — done after live verification

- The canonical skill names `codex_review(mode="implementation")` for exact implementation-snapshot review and the orchestrator-only `record_review_outcome(..., outcome="skipped", ...)` route without copying the gate's skip conditions.
- The skill explicitly says that without the marker the calls remain optional and `status=not_active, required=false` means continue without a receipt.
- Machine-unavailable remains non-blocking; `interrupted`, generic `failed`, and `timed_out` remain non-qualifying.
- The reconnect-time `.codex/skills/codex-debate/SKILL.md` projection is byte-identical locally. It remains untracked by the current one-owner contract (`test_policy_has_one_tracked_source`).
- PROJECT CONTEXT, design-calibration prose, routing, and round ceilings are unchanged.

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

T4 is separated from that checkpoint: production (`app/**`, `scripts/**`) **0 files, +0/-0**; canonical policy **1 file, +20/-0**; task evidence consists only of this report and `review-t4-luna.md`.

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
- T4 check was RED before the edit on exactly `['review-coverage-v1', 'mode="implementation"', 'outcome="skipped"']`; after the edit it prints `review-coverage-v1 reaches canonical and native Codex skill`.
- Foreign-project inactive-policy scenario: `policy_active=false status=not_active required=false receipt_id='' action=continue_merge_without_receipt`.
- Canonical/native byte comparison: `skill_mirror=identical`; `skill-creator` validation: `Skill is valid!`.
- Sharded final tests: `tests/test_review_coverage_gate_462.py` — **22 passed**; `tests/test_default_pipeline.py` — **131 passed**; `tests/test_check_pipeline_manifest.py` — **15 passed**; focused legacy/manager/workspace skill delivery — **26 passed, 267 deselected**.
- Route-surface pre-update delta: added exactly `POST /api/merge-operations/review-skip`; removed routes: none. The same snapshot test on clean `main` `ccab874e` was green (`1 passed in 1.96s`); after the one-entry snapshot update the branch file is green (`2 passed in 2.19s`).

## Pre-mortem

1. **Old live #436 schema rejects the first new insert.** Check: frozen test starts from the exact old table and verifies all eight additive columns after `init_db`; green.
2. **Plan/research or stale implementation receipt authorizes later code.** Check: qualifying rows require `subject_kind=implementation`, exact target SHA and independent raw-diff hash; stale/foreign matrix is green.
3. **Worker self-issues skip.** Check: server route validates live MCP proof + orchestrator session; worker proof returns 403; target session/head/snapshot are asserted.
4. **Timeout or generic provider failure becomes unavailable.** Check: only two exact failure codes qualify; wrong code, interrupted, failed-reviewed, and timed-out-reviewed controls are green.
5. **Policy activates after operation admission.** Check: pending `not_active` operation revalidates and the executor mock is never awaited.
6. **A project sees inactive policy and treats the optional mechanism as mandatory.** Check: the production decision for a foreign scope with `active=False` returns `not_active`, `required=False`; the skill maps that exact result to `continue merge without receipt`.
7. **The operational block duplicates or weakens canonical routing.** Check: manifest/default-pipeline tests enforce one occurrence of route anchors; an initial duplicate `NO MODEL REVIEW` anchor failed both suites and was replaced by a reference to gate item 1.

## Review

### T1–T3 implementation

Luna implementation review timed out after 600 seconds with three intermediate messages and no final finding/verdict. The preserved evidence is `review-implementation-luna.md`. No unchanged-artifact retry was opened: **вердикта нет**.

### T4 policy delivery

Route: one fresh Luna pass; auxiliary Sol was not authorized. `review-t4-luna.md` contains no findings and verdict `Overall Correctness: Correct | Confidence: 0.96`. Reviewer evidence is the exact added line `Маркер активации политики: review-coverage-v1` (shown with Markdown code formatting in the artifact), verified once in the canonical skill. Receipt `review-receipt:0df49406-b23d-4a65-8a13-0e5bd161992e` is `completed`, has `verdict_present=1`, and the author outcome was recorded as `accepted` with this report as evidence.

## Live checkpoint proofs after merge/restart

These are live-owner checks against merged checkpoint `1a86f403`; T4 remained untouched. Two one-line branch-only `app/review_coverage.py` probes were committed and then reverted. Final app bytes equal `main`.

### 1. Real implementation-review receipt

Command: live MCP `codex_review(mode="implementation", model="gpt5.6luna", output=".orchestra/tasks/462/live-implementation-review.md")` on target `1a86f403` and worker head `f51b29f7`.

Reviewer command/output evidence:

```text
git diff --binary --full-index 1a86f403b3996137f216c14e3d3407b58c35a2d4...f51b29f70a004f218140ea4af1e408411e813cc4
diff --git a/app/review_coverage.py b/app/review_coverage.py
+# Live checkpoint probe: a committed app blob must produce a distinct receipt snapshot.
## Verdict
Correct. The change is intentionally branch-only and does not alter runtime behavior.
```

Live SQLite command selected the latest receipt for the exact artifact and printed:

```text
receipt_id=review-receipt:a2d8cc6f-484b-4d0f-9fe0-b9a8e05d9d3b
status=completed
coverage_outcome=reviewed
subject_kind=implementation
target_sha=1a86f403b3996137f216c14e3d3407b58c35a2d4
worker_head=f51b29f70a004f218140ea4af1e408411e813cc4
production_snapshot_sha256=0b393440a606fb57a9cc4b259fe810cedb053ef1b77c855fac1e69135c8d00b3
production_paths_json=["app/review_coverage.py"]
artifact_exists=1 artifact_bytes=726 jsonl_response_present=1 return_code=0 failure_code=''
```

`live-implementation-review.md` preserves the complete 19-line review. This `Correct` verdict applies only to the deliberate one-comment live probe. The T1–T3 implementation review above still has **вердикта нет**.

### 2. Real proof-bound structured skip receipt

The worker-side live call first returned the required negative control:

```text
review_skip_forbidden: review skip is orchestrator-only
```

`Orchestra-orchestrator` then called the same `record_review_outcome(outcome="skipped")` path with `decision_id=462-live-skip-20260903` against worker head `6b8bbea4`. A read-only live SQLite query printed:

```text
receipt_id='review-skip:10dc0424a2ddd3730afa9e12e0c6bd581907c03b2d43ef79b7fccfa94c888567'
mode='skip' status='completed' coverage_outcome='skipped'
subject_kind='implementation'
target_sha='1a86f403b3996137f216c14e3d3407b58c35a2d4'
worker_head='6b8bbea49daa5b30c6b4c8252f16adde644e5135'
production_snapshot_sha256='21665d5c8346d8f302ef0762916ffd0bf9eabc7071619a821c9c1be5631a8063'
production_paths_json='["app/review_coverage.py"]'
policy_ref='codex-debate@sha256:8c3d727ac6696ff25c1ce3da27a82d68f59ecc29ab68b3b7d764f32ff6f1d573'
decision_actor='Orchestra-orchestrator'
outcome_evidence_ref='.orchestra/tasks/462/live-implementation-review.md'
author_outcome='unknown' outcome_source='direct' reviewer_model='' runtime='none'
task_id='462' task_source='session_lookup'
requested_at=completed_at='2026-09-03T12:40:09.730300+00:00'
```

Field interpretation is intentional and bounded:

- `reviewer_model=''` and `runtime='none'`: no reviewer ran for a policy skip.
- `author_outcome='unknown'`: the trusted orchestrator made the skip decision; the implementation-review author did not accept/dispute a reviewer finding because none exists.
- The skip is proved by `coverage_outcome=skipped`, exact snapshot, `policy_ref`, `decision_actor`, and evidence ref. It does **not** close #436's missing author-outcome population (“0 из 40”); treating it as `author_outcome=accepted` would fabricate a reviewer response. That separate task-level prerequisite belongs to #466.

### 3. Live no-marker admission result

Command: a fresh `/mnt/data/Projects/Python/orchestra/.venv/bin/python` process loaded merged code, the live SQLite session row, actual worker Git identity, and called `_prepare_admission_snapshot` with target `main`. Output:

```json
{"review_coverage":{"coverage_outcome":"unknown","production_paths":["app/review_coverage.py"],"production_snapshot_sha256":"21665d5c8346d8f302ef0762916ffd0bf9eabc7071619a821c9c1be5631a8063","reason":"policy_not_active","receipt_id":"","required":false,"status":"not_active","target_sha":"1a86f403b3996137f216c14e3d3407b58c35a2d4","worker_head":"6b8bbea49daa5b30c6b4c8252f16adde644e5135"},"target":{"branch":"main","sha":"1a86f403b3996137f216c14e3d3407b58c35a2d4"}}
```

Assertions `status == 'not_active'` and `required is False` passed. The absent marker therefore does not block the production diff.

## Final rollout state

Required next steps are external to this branch checkpoint:

1. T1–T3 checkpoint merge/restart: done (`1a86f403`).
2. Real implementation review receipt: done.
3. Real structured skip receipt: done, including worker-forbidden negative control.
4. Live no-marker `not_active` admission: done.
5. T4 approval: done; canonical marker and operational syntax delivered.

Breaking behavior: active policy now rejects `app/**` or `scripts/**` merges that lack an exact implementation-snapshot review, authorized skip, or typed machine-unavailable receipt. Non-production merges remain outside this gate; inactive-policy response remains non-blocking.
