# #506 — Plan: final-diff review with a fail-safe size skip

## Fixed owner decisions

1. Model review runs on the final task diff only, except genuinely hard/high-risk primary work. It does not run after intermediate edits or ordinary tickets.
2. A final implementation diff may skip model review only when the complete pinned diff is at most 40 changed text lines AND at most 3 changed files.
3. Executable review ceiling remains 3 rounds. Phase 3 does not change that number.
4. Luna-over-Sol/Opus remains a valid review route. Phase 3 does not remove or weaken it.

Required weakness statement, verbatim: `n=2`, and the first observed blocker sits three lines above it (#502 round 1, 43 lines / 2 files).

## Does the threshold complicate the tool?

The line/file threshold itself does not materially complicate `codex_review`: implementation mode already resolves immutable `target_sha` and `worker_head`, so one complete `git diff --numstat -z target_sha...worker_head` supplies the two numbers. The implementation adds no database table, migration, cache, or second owner of the threshold.

The high-risk override was not already executable. Current code has no authoritative classifier for authorization/merge/quota/credential risk; `production_snapshot()` only projects `app/**` and `scripts/**`. Automatic path keywords are rejected because they would create a second, incomplete project-dependent risk vocabulary.

The approved minimal contract keeps the existing decision gate as the sole risk owner and makes forgetting fail safe:

- `codex_review(..., required=True)` means the decision gate requires review regardless of size.
- Only the literal JSON boolean `required=false` is an explicit low-risk assertion and may enter the arithmetic skip.
- Omitted input defaults to review. `null`, strings such as `"false"`, numbers such as `0`, and every other malformed value review rather than skip. Implementation checks identity (`required is False`), not truthiness/coercion.
- `mode='exec'` and `mode='review'` never use the size skip; hard primary research/design review remains available.

This adds one fail-safe input and one branch, not a risk classifier.

## Runtime design

### Complete-diff measurement

Add in `app/mcp_stdio.py`:

```python
_REVIEW_SKIP_MAX_LINES = 40
_REVIEW_SKIP_MAX_FILES = 3

def _implementation_review_size_decision(
    worktree: str,
    target_sha: str,
    worker_head: str,
    *,
    required: Any = True,
) -> dict[str, object]: ...

def _parse_review_numstat(raw: bytes) -> tuple[int, int, int]: ...
```

The helper runs `git diff --numstat -z <target_sha>...<worker_head>` with no path filter. It returns exactly:

- `status`: `skip` or `review`;
- `reason`: `size_threshold`, `required`, `size_exceeded`, `binary_diff`, or `measurement_failed`;
- `changed_lines`, `changed_files`, `binary_files`;
- `threshold_lines=40`, `threshold_files=3`;
- original `required` value;
- a human-readable `evidence` string.

Rules:

- Skip iff `required is False`, changed text lines `<=40`, changed files `<=3`, binary files `==0`, and numstat completed successfully.
- Any binary entry (`-\t-`), malformed numstat, unresolved ref, or Git failure runs review. It never guesses binary line count.
- File count comes from the complete numstat records. Renames and paths containing tabs/newlines must remain parseable through `-z` framing.
- `production_paths_json` is never an input to the size decision. The RED foreign-project case has an empty production projection and a 100-line complete diff; it must review.

### Auditable skip

In `codex_review(mode='implementation')`, call the helper immediately after `resolve_implementation_subject()` and before project-context ingestion, quota checks, Codex process construction, or background-job creation.

When the helper returns `skip`:

1. Create an idempotent `review-size-skip:<sha256>` identity from session, task, target SHA, worker head, policy ref, and the two threshold constants.
2. Reuse `review_receipt_record_skip()` and the existing `review_receipts` schema. Store a completed receipt with `subject_kind='implementation'`, `mode='skip'`, `coverage_outcome='skipped'`, the full pinned subject fields, `decision_actor=WORKER_NAME`, and `outcome_evidence_ref=<decision evidence>`.
3. Return `kind='review_skipped_by_size'`, receipt ID, target/head, measured lines/files/binary count, threshold, and the same evidence. The text names both measurements and the threshold verbatim.
4. Do not reserve a review round, create an artifact, query quota, ingest project context, or create a background job.

The existing merge coverage reader already accepts a completed pinned `coverage_outcome='skipped'` receipt. No merge-gate, database, or route change is planned.

When the helper returns `review`, existing behavior remains byte-for-byte in control flow after the new decision: project context, receipt round reservation, quota, resume, job, artifact, and usage accounting are unchanged.

## Prompt/skill delivery

After #490 merges and after T1 is merged, restarted by the owner, and proven through one real agent `codex_review` call, update the canonical `.orchestra/pipelines/default/prompts/skills/codex-debate.md` source. This ordering obeys the repository rule that a prompt may require a capability only after its live owner has answered successfully on the real path.

The policy must say exactly that:

- implementation model review runs only on the final committed task diff after all tickets complete;
- intermediate edits and ordinary tickets do not trigger review;
- the complete pinned diff threshold is 40 lines AND 3 files;
- only literal `required=false` asserts low risk; every missing/unknown/malformed value reviews;
- the size decision never uses `production_paths_json`;
- a size skip writes an auditable completed receipt and must be named in DONE;
- the evidence weakness is stated with the required `n=2` sentence;
- executable ceiling stays 3 and Luna-over-Sol/Opus remains available.

The delivery oracle injects the same canonical bytes into both `.codex/skills/codex-debate/SKILL.md` and `.claude/skills/codex-debate/SKILL.md` in scratch repositories. No tracked native skill copy is created.

## Files

- `app/mcp_stdio.py` — complete-diff numstat decision, fail-safe `required` input, durable size-skip receipt, structured response. **Do not touch until the orchestrator hands over this file.**
- `.orchestra/pipelines/default/prompts/skills/codex-debate.md` — final-diff-only and fail-safe size-skip policy. **Do not touch until #490 merges, ownership is handed over, and the T1 live-owner gate succeeds.**
- `.orchestra/tasks/506/test_t1_review_size_gate.py` — immutable T1 behavioral oracle.
- `.orchestra/tasks/506/test_t1_review_size_gate_edges.py` — immutable T1 binary/error/idempotency oracle.
- `.orchestra/tasks/506/test_t2_review_policy_delivery.py` — immutable T2 delivery oracle.
- `.orchestra/tasks/506/report.md` — Phase 3 evidence only.

No changes planned in `app/review_coverage.py`, `app/db.py`, `app/routes/merge_operations.py`, the round-ceiling table, reviewer routing, or usage accounting.

## Migration and compatibility

- No schema/data migration.
- Existing callers omit `required`; omission reviews, preserving current behavior and failing safe.
- Existing `exec`/`review` calls and all implementation calls above the threshold continue unchanged.
- Old review receipts remain valid. The new deterministic skip receipt uses fields already accepted by `coverage_decision()`.
- The MCP schema intentionally accepts an unconstrained JSON value for `required`, because strict pre-validation would reject malformed input before the fail-safe review branch could run. Only Python identity with `False` unlocks the skip.
- Python code requires owner-initiated service restart. MCP clients holding an old imported `app/mcp_stdio.py` must reconnect before the live T1 probe.
- Superseded oracle command: `uv run pytest ...` imported `/mnt/data/Projects/Python/orchestra/app/mcp_stdio.py` from the main checkout because the service exports `PYTHONPATH=/mnt/data/Projects/Python/orchestra`; `uv run python -m pytest ...` puts the worktree CWD first and imports `/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/review-policy/app/mcp_stdio.py`.

## Tickets

### T1 — Gate a final implementation review by complete diff size, fail safe, and record the skip

- Files: `app/mcp_stdio.py`, `.orchestra/tasks/506/test_t1_review_size_gate.py`, `.orchestra/tasks/506/test_t1_review_size_gate_edges.py`
- Test: `uv run python -m pytest -q .orchestra/tasks/506/test_t1_review_size_gate.py .orchestra/tasks/506/test_t1_review_size_gate_edges.py` — core RED committed in `25c3b4f8`; edge RED committed in `c25e6632`; command corrected in Phase 3 without changing test bytes
- RED: exit 1; first missing-behavior assertion: `AssertionError: T1 missing complete-diff review size gate`
- AC: `uv run python -m pytest -q .orchestra/tasks/506/test_t1_review_size_gate.py .orchestra/tasks/506/test_t1_review_size_gate_edges.py` is green.
- AC: the ordinary 20-line/1-file diff with literal `required=False` returns `review_skipped_by_size`, names `20`, `1`, `40`, and `3`, writes a completed pinned `coverage_outcome='skipped'` receipt, and starts no background job.
- AC: the same tiny diff with `required=True`, omitted, `None`, string `"false"`, or integer `0` starts review; only the literal boolean `False` may skip.
- AC: a 100-line foreign-project diff with no `app/**`/`scripts/**` paths reviews; a 4-line/4-file diff reviews; any binary or measurement failure reviews.
- AC: malformed `--numstat -z` framing raises at the parser seam and becomes `measurement_failed` at the decision seam; an unresolved ref reviews without exposing raw Git failure text.
- AC: replaying the same explicit-low-risk call returns the same receipt ID and leaves exactly one `coverage_outcome='skipped'` row.
- AC: focused regressions stay green: `uv run python -m pytest -q tests/test_mcp_codex_review.py tests/test_review_coverage_gate_462.py tests/test_review_receipt_storage_436.py`.
- AC: after merge and owner restart/reconnect, one real agent call on a scratch final diff returns the expected structured skip receipt, and a read-only receipt query finds its exact measurements. This live success is the gate for T2.
- blocked-by: none
- External prerequisite: explicit handover of `app/mcp_stdio.py` ownership before Phase 3 writes.

### T2 — Deliver final-diff-only review policy without changing ceiling or cross-model routing

- Files: `.orchestra/pipelines/default/prompts/skills/codex-debate.md`, `.orchestra/tasks/506/test_t2_review_policy_delivery.py`
- Test: `uv run python -m pytest -q .orchestra/tasks/506/test_t2_review_policy_delivery.py` — committed RED in `25c3b4f8`; command corrected in Phase 3 without changing test bytes
- RED: exit 1; first missing-delivery assertion: `AssertionError: T2 missing delivered policy anchor: Implementation model review runs only on the final committed task diff after all tickets are complete.`
- AC: `uv run python -m pytest -q .orchestra/tasks/506/test_t2_review_policy_delivery.py` is green.
- AC: both Codex and Claude injected skill homes contain every frozen anchor exactly once.
- AC: the executable ceiling remains `3 раунда`; direct Luna review remains present; no automatic path-keyword risk classifier is described.
- AC: canonical policy includes verbatim: `n=2`, and the first observed blocker sits three lines above it (#502 round 1, 43 lines / 2 files).
- AC: canonical policy says a size skip is auditable and DONE names the receipt/measurements.
- AC: `uv run python -m pytest -q tests/test_default_pipeline.py tests/test_manager.py -k 'codex_debate or CodexSkillHome or RiskBasedReviewRouting'` is green.
- blocked-by: T1
- External prerequisites: #490 merged; prompt-tree ownership handed over; T1 merged; owner-initiated restart; MCP reconnect; successful real-path T1 probe.

## Implementation order and stopping points

1. Receive `app/mcp_stdio.py` ownership.
2. Run T1 command and confirm the frozen missing-behavior RED.
3. Implement T1 only and run its focused regressions.
4. Commit the complete T1 implementation so `mode='implementation'` has a clean pinned subject; then perform the selected high-risk review route on that committed diff. Any accepted review fix is a new commit followed by a legal resumed round.
5. Hand the reviewed T1 commit set to the orchestrator for merge. Do not edit the prompt source yet.
6. Owner restarts; the worker reconnects; run the real-path size-skip probe and verify its durable receipt.
7. After #490 and prompt ownership, run T2 RED, edit the canonical skill, and make the delivery check green.
8. Run focused regressions and review the final remaining task diff once. Do not buy review rounds for intermediate prompt wording.

## What is deliberately not changed

- No round-ceiling reduction.
- No removal of Luna-over-Sol/Opus review.
- No path-keyword risk detection.
- No threshold derived from `production_paths_json`.
- No review-spend accounting work; #506 proved accounting exists and only the reporting join was misleading.
- No full unsharded pytest run; this repository's one-process full suite is a known OOM path.

## Plan review inputs

- Changed files/consumers: plan and frozen task-local tests only in Phase 2; planned runtime consumer is `codex_review(mode='implementation')`, planned policy consumers are injected Codex/Claude skills.
- Author model/runtime: current full-cycle Codex session; model name is not used to lower risk.
- Exact AC: ticket AC above.
- Named checks and observed output:
  - `uv run python -m pytest -q .orchestra/tasks/506/test_t1_review_size_gate.py .orchestra/tasks/506/test_t1_review_size_gate_edges.py` → `8 failed`; first line `AssertionError: T1 missing complete-diff review size gate`.
  - `uv run python -m pytest -q .orchestra/tasks/506/test_t2_review_policy_delivery.py` → `1 failed`; first line `AssertionError: T2 missing delivered policy anchor: Implementation model review runs only on the final committed task diff after all tickets are complete.`
- Risk floor: high. T1 creates an authorization-bearing review skip on the merge path; T2 changes fleet-wide agent policy.

## Plan review outcome

- Route: Luna because the technical floor points to Sol but no separate auxiliary Sol authorization was granted.
- Round 1: `Incorrect`; blocking finding that implementation review was ordered before the clean commit required by `mode='implementation'`; suggestion that binary, measurement-error, and idempotent-retry edges lacked frozen coverage.
- Resolution: implementation order now commits T1 before pinned review; new immutable edge oracle committed at `c25e6632` covers binary diff, malformed numstat, unresolved ref/measurement failure, and retry identity.
- Round 2 used the same resumed thread and returned `PASS`: prior blocker **FIXED**, prior suggestion **FIXED**, no new findings. Evidence: `.orchestra/tasks/506/review-plan-luna.md`.
