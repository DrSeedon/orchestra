# #462 — plan: snapshot-bound review coverage before merge

## Outcome

Forward-only merge admission rejects a changed production implementation unless the existing #436 receipt mechanism contains one of three exact-snapshot outcomes: a completed review, an authorized structured skip, or a typed machine-unavailable receipt. The gate closes coverage only; it does not reinterpret reviewer verdict quality.

## Non-negotiable requirements from the approved research

1. **Триггер — минимум один изменённый путь `app/**`, `mapped_files` остаётся доказательством, но не необходимым условием.**
   **Resolved scripts boundary:** the same trigger applies to `scripts/**`; the authoritative production predicate for implementation is `app/** OR scripts/**`.
2. **Пропуск ревью — структурное событие в существующем механизме квитанций #436, проза отчёта доказательством не является; правила пропуска не копировать, владелец один — скилл `codex-debate`.**
3. **Недоступность ревьюера — отдельный машинный исход, который НЕ равен `interrupted`/`failed`/`timed_out`, и он мерж не блокирует.**
4. **Квитанция обязана привязываться к КОНКРЕТНОМУ снимку реализации, а не к задаче и сессии.**

## Production boundary

`scripts/**` **входит** в production boundary целиком, вместе с `app/**`.

Reason: #453 changed an operational commit hook under `scripts/**`; excluding the directory would preserve a known coverage hole. The trigger is therefore exactly one or more target-relative changed paths under either existing repository root `app/**` or `scripts/**`. Tests, task artifacts, worker memory, and docs do not trigger by themselves. `mapped_files` remains in admission/test-gate evidence but never suppresses the production trigger: an unmapped `app/**` or `scripts/**` change still requires a receipt.

No line-count threshold is added. The measured threshold is **1 production path**; a one-line identity/authorization change can carry the same consequence as a large diff.

## Design

### One production snapshot owner

Add `app/review_coverage.py` as the single executable owner of:

- `production_paths(changed_paths)`: filter `app/**` and `scripts/**`;
- `production_snapshot(worktree, target_sha, worker_head)`: exactly `sha256(b"review-coverage-v1\\0" + target_sha.encode() + b"\\0" + git_diff_raw)`, where `git_diff_raw` is the unmodified bytes of `git diff --raw --full-index -z target_sha...worker_head -- app scripts`;
- `current_policy_ref()`: exactly `codex-debate@sha256:<sha256 bytes of .orchestra/pipelines/default/prompts/skills/codex-debate.md>`, without copying its skip conditions;
- receipt selection for the same scope/session/task, `target_sha`, and `production_snapshot_sha256` before the merge boundary.

The review subject must be a clean committed worker HEAD. New `codex_review(mode="implementation")` resolves the session's target branch and HEAD itself, computes the snapshot, and generates the exact reviewer command `git diff --binary --full-index <target_sha>...<worker_head>` without a caller-supplied target. Caller-provided prose, task id, or an arbitrary `/tmp/*.diff` cannot create a qualifying implementation receipt.

The snapshot covers production paths only. Committing the review artifact/report afterward does not invalidate it; changing any `app/**` or `scripts/**` blob, mode, deletion, or path does. Existing target-head recheck still protects the baseline.

### Extend #436 receipts; no second store

Add additive columns to `review_receipts` and `_REVIEW_RECEIPT_COLUMNS`:

```text
subject_kind
target_sha
worker_head
production_snapshot_sha256
production_paths_json
coverage_outcome
policy_ref
decision_actor
```

Legacy rows receive explicit empty/`unknown` defaults and never qualify retroactively. `db.init_db()` performs an idempotent `PRAGMA table_info(review_receipts)` + additive `ALTER TABLE` migration for every new column before any extended insert; a frozen test starts from the exact pre-existing #436 schema. `scripts/migrate_review_receipts.py` emits the same defaults so its historical importer remains replay-safe. Add an index for the lookup key `(scope, session_id, task_id, target_sha, production_snapshot_sha256, coverage_outcome, completed_at)`.

`coverage_outcome` is application-validated as `unknown | reviewed | skipped | unavailable`; it is separate from existing execution `status`. This avoids pretending that an unavailable model returned a review and avoids conflating it with `interrupted`, `failed`, or `timed_out`.

Execution status stays inside the existing #436 enum: a real review is `status=completed`; an authorized policy skip is `status=completed`; a quota/binary refusal is `status=failed` plus `coverage_outcome=unavailable`. No row ever uses `status=skipped` or `status=unavailable`. Admission keys on the pair, so `status in {interrupted, failed, timed_out}` with `coverage_outcome=reviewed` never qualifies, while only the typed machine-unavailable pair does.

A qualifying completed review has:

- `subject_kind=implementation` and exact target/snapshot match;
- `coverage_outcome=reviewed`;
- existing #436 terminal proof: `status=completed`, `return_code=0`, non-empty artifact, and `jsonl_response_present=1`;
- both request and completion no later than merge admission.

The gate does not require `APPROVED`; #462 is review coverage, not reviewer calibration.

### Structured skip and unavailable outcomes

Keep `record_review_outcome` as the one MCP entrypoint. Its skip branch calls a new server-owned `POST /api/merge-operations/review-skip` adapter; the local `ORCHESTRA_ROLE` value is not an authority:

- its existing `accepted | disputed | partial` path remains unchanged for a real receipt;
- `outcome="skipped"` with an empty receipt id requires `target_worker`, non-empty evidence, and caller-supplied `decision_id`; the MCP adapter forwards those fields but does not authorize them;
- the HTTP endpoint uses existing `caller_may_use_orchestrator_privilege(request)` (cookie or matching `X-Orchestra-Session-Id` + `X-Orchestra-Mcp-Proof` + live orchestrator role), then resolves `target_worker` through `get_session_by_name(scope)` and creates the snapshot-bound receipt;
- receipt id is deterministically derived from `decision_id`; identical replay returns the same row, while the same id with another target/snapshot/evidence fails 409, including concurrent replay;
- the row records `status=completed`, `coverage_outcome=skipped`, `decision_actor`, and `policy_ref`;
- a worker cannot self-issue a skip;
- report prose is never parsed.

The tool records a reference/hash to the current `codex-debate` owner. It does not duplicate or enumerate the owner's skip rules in Python. The trusted orchestrator attests that the already-canonical policy selected skip and supplies the concrete AC/oracle evidence reference.

For machine-known Codex unavailability, `codex_review` validates/resolves the implementation subject and reserves the receipt **before** the quota/binary preflight. A known quota block or missing Codex binary finalizes it with `status=failed`, `coverage_outcome=unavailable`, and the typed failure code. The tool can still return its normal typed refusal; the durable receipt is the merge evidence. Transport errors, interrupted jobs, failed execution, and timeouts retain `coverage_outcome=unknown` and remain non-qualifying. An orchestrator may convert a separately verified outage into the explicit structured skip path; the gate never infers it from prose.

### Merge admission and activation

`app/merge_operations.py::_prepare_admission_snapshot` reuses `changed_paths`, pins production paths/snapshot and the matching receipt decision into `accepted_admission`, alongside the existing target/oracle. `accept_merge_operation` returns typed 409 `REVIEW_COVERAGE_MISSING` before inserting/starting an operation when an active policy requires review and the pinned decision is blocked. `_admission_evidence` exposes the receipt id/outcome/snapshot without copying review text.

Activation is also checked inside `_run_operation`, immediately before acceptance/tests and therefore before `execute_merge_session`/Git. A pending operation pinned as `not_active` is re-evaluated if the marker has since appeared; missing evidence makes that operation FAILED with `REVIEW_COVERAGE_MISSING`. A decision already pinned as `satisfied` is still protected by the normal target/worker snapshot recheck. Thus the activation boundary is the first execution-side check that sees the marker, not merely operation creation; no pre-activation queue needs a manual drain.

The code ships inactive first. `review_coverage_policy_active()` reads one literal activation marker, `review-coverage-v1`, from the canonical `.orchestra/pipelines/default/prompts/skills/codex-debate.md`. Absence means `status=not_active`, not failure. This is not a second rule set: the marker only says whether the canonical owner has started requiring the already-implemented workflow.

After T1–T3 merge and restart, a real agent contour must successfully call `codex_review(mode="implementation")` and the structured skip branch of `record_review_outcome`. Only then does T4 add the marker and operational call syntax to the canonical skill plus its byte-identical tracked Codex-native mirror. The marker both delivers the requirement and activates enforcement; no agent is required to call unavailable code.

## Files

- `app/review_coverage.py` — production paths, versioned Git snapshot, policy reference, decision selection.
- `app/db.py` — additive receipt columns/index, create/reserve/finish validation, exact coverage lookup.
- `app/mcp_stdio.py` — `implementation` review mode, preflight unavailable receipt, orchestrator-only structured skip via `record_review_outcome`.
- `app/routes/merge_operations.py` — proof-bound/idempotent structured-skip HTTP owner; target worker is resolved server-side.
- `app/codex_review_artifact.py` — terminal `coverage_outcome=reviewed` publication for a successful current round.
- `scripts/migrate_review_receipts.py` — explicit legacy defaults for new receipt fields.
- `app/merge_operations.py` — pin decision at admission, typed pre-operation refusal, evidence output, activation check.
- `tests/test_review_coverage_gate_462.py` — frozen behavioral RED checks.
- `.orchestra/pipelines/default/prompts/skills/codex-debate.md` — canonical forward-only operational workflow and activation marker, T4 only.
- `.codex/skills/codex-debate/SKILL.md` — required byte-identical tracked native mirror, T4 only.
- `.orchestra/tasks/462/check_review_policy_delivery.py` — T4 delivery check.
- `.orchestra/tasks/462/report.md` — final evidence and staged rollout result.

`app/acceptance.py` is not changed: its frozen task oracle remains an independent gate. PROJECT CONTEXT, generic design-review prose, and the unmeasured identity/ownership receipt hypothesis are not touched.

## Rollout / migration

1. Implement T1–T3 with the policy marker absent; all behavioral tests pass while live enforcement remains `not_active`.
2. Commit T1–T3 and ask the orchestrator to checkpoint-merge with `task_outcome=continue`; restart normally so the MCP/runtime owners load the code. Any operation still pending across later activation is revalidated in `_run_operation` before the executor/Git path.
3. From a real agent contour, run both new calls and inspect their stored receipts. Failure stops rollout; do not add the marker.
4. Refresh this worker from `main`, implement T4 only, run the delivery check, then final-merge. The activation merge itself changes no `app/**` or `scripts/**` path; before its commit the marker is absent, after it all later production merges are enforced.
5. No historical receipt backfill. Old rows lack a snapshot and remain non-qualifying by construction.

## What not to touch

- PROJECT CONTEXT block or its delivery.
- Generic identity/ownership/design-calibration prompts.
- Review round ceilings, reviewer model routing, or verdict interpretation.
- `mapped_files` selection/test execution semantics.
- A second receipt table, skip report parser, or duplicated Python list of canonical skip conditions.

## Tickets

### T1 — Snapshot-bound implementation review receipt

- Files: `app/review_coverage.py`, `app/db.py`, `app/mcp_stdio.py`, `app/codex_review_artifact.py`, `scripts/migrate_review_receipts.py`.
- Test: `/mnt/data/Projects/Python/orchestra/.venv/bin/python -m pytest -q tests/test_review_coverage_gate_462.py -k 'test_t1_'` — committed RED in final oracle commit `41456f2afbab` (strengthening history `39ad502d57c9`, `b4712a67db0b`).
- RED: `AssertionError: T1 missing behavior: codex_review has no snapshot-bound implementation mode`; independent seams: `init_db does not upgrade the existing #436 receipt schema`, `successful finalization does not publish reviewed coverage`.
- AC: named command is green (currently 3 distinct failures); generated Codex command names the exact target/head; evidence-only commit preserves the production hash, app change alters it; legacy #436 receipt/migration tests remain green.
- blocked-by: none.

### T2 — Structured policy skip and machine unavailable receipt

- Files: `app/review_coverage.py`, `app/db.py`, `app/mcp_stdio.py`, `app/routes/merge_operations.py`.
- Test: `/mnt/data/Projects/Python/orchestra/.venv/bin/python -m pytest -q tests/test_review_coverage_gate_462.py -k 'test_t2_'` — committed RED in final oracle commit `41456f2afbab` (strengthening history `39ad502d57c9`, `b4712a67db0b`).
- RED: `AssertionError: T2 missing behavior: quota refusal produced no structured receipt`; independent seams: absent binary has no unavailable receipt, existing outcome tool cannot record skip, no proof-bound server endpoint owns skip receipts.
- AC: named command is green (currently 4 distinct failures); quota/missing-binary rows have `status=failed/coverage_outcome=unavailable` with exact typed code; endpoint requires live MCP proof + server-resolved orchestrator, stored receipt names target session/worker/head/snapshot, same `decision_id` concurrent replay is one row, payload drift is 409, worker proof is 403; policy conditions remain only in `codex-debate`.
- blocked-by: T1.

### T3 — Fail-closed merge admission for `app/**` and `scripts/**`

- Files: `app/merge_operations.py`, `app/review_coverage.py`.
- Test: `/mnt/data/Projects/Python/orchestra/.venv/bin/python -m pytest -q tests/test_review_coverage_gate_462.py -k 'test_t3_'` — committed RED in final oracle commit `41456f2afbab` (initial seam in `f00ea8b5ae4e`).
- RED: `AssertionError: T3 missing behavior: review trigger is not pinned from changed_paths`; independent seams: exact reviewed/skip/unavailable selection absent, blocked coverage still creates an operation, pre-activation pending operation still reaches executor.
- AC: named command is green (currently 9 failures / 6 negative controls already green); app and scripts positives block without evidence, tests-only remains `not_required`; exact reviewed, authorized skip, and only `weekly_quota_blocked|codex_binary_missing` unavailable receipts allow; wrong unavailable code, interrupted/failed/timed_out reviewed rows, foreign session, and stale snapshot block; pre-admission block inserts no row and activation-race recheck never calls executor/Git.
- blocked-by: T1, T2.

### T4 — Live-verified canonical policy delivery and activation

- Files: `.orchestra/pipelines/default/prompts/skills/codex-debate.md`, `.codex/skills/codex-debate/SKILL.md`.
- Test: delivery check `/mnt/data/Projects/Python/orchestra/.venv/bin/python .orchestra/tasks/462/check_review_policy_delivery.py` — committed RED in `f00ea8b5ae4e`.
- RED: `AssertionError: T4 delivery: review coverage anchors missing: ['review-coverage-v1', 'mode="implementation"', 'outcome="skipped"']`.
- AC: T1–T3 checkpoint is merged/restarted; real `codex_review(mode="implementation")` and structured skip calls have successful receipts; delivery command prints `review-coverage-v1 reaches canonical and native Codex skill`; the two skill files are byte-identical; no PROJECT CONTEXT/design-calibration text changes.
- blocked-by: T1, T2, T3, successful live checkpoint probe.

## Plan review inputs

- Changed consumers planned: review receipt writers/readers, Codex review MCP tool, merge admission before operation creation, canonical/native `codex-debate` delivery.
- Author metadata: current full-cycle session is `gpt-5.6-sol` / Codex runtime (session metadata, not agent name).
- Exact AC: the four ticket commands above plus staged live receipts before activation.
- Frozen oracle history: initial commit `f00ea8b5ae4e`; reviewer-driven strengthening in `39ad502d57c9` and `b4712a67db0b`; final immutable behavior oracle `41456f2afbab`, all before implementation. Current RED: T1 = 3 failed, T2 = 4 failed, T3 = 9 failed / 6 negative controls green, T4 delivery = exit 1, across the named independent seams.
- Risk floor: review/admission/authorization gate and persistent receipt schema are high-risk. Canonical route would be Sol, but no auxiliary Sol reviewer was explicitly authorized; Luna reviewed within its executable-artifact ceiling, with no claim that it lowers the floor.

## Plan review outcome

- Route: Luna, 3 rounds; executable-artifact ceiling exhausted.
- Round 1: 7 blocking + 1 suggestion. Schema migration, finalizer/exact subject, proof authority, unavailable classification, positive allow cases, activation recheck, and skip idempotency were added to the plan and frozen oracle.
- Round 2: 3 blocking. The oracle was corrected to separate execution status from `coverage_outcome`, require exact outage codes, and assert server-resolved target session/head/snapshot.
- Round 3 verdict: **Incorrect**, 2 blocking wording contradictions. Both are fixed above after the ceiling: the authoritative trigger now says `app/** OR scripts/**`, and machine-unavailable is the third top-level qualifying outcome.
- No fourth review is allowed. There is no reviewer verdict on those two final wording fixes; the orchestrator/user must evaluate them at the Phase-2 approval gate. The exact Round-3 quote and findings remain in `review-plan-luna.md`.
