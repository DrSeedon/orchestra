# #513 — who must own the implementation-review subject

## Question

- **Context:** the active `review-coverage-v1` merge gate accepts a production merge only when a qualifying receipt matches the worker session, task, target commit, and production snapshot.
- **Change under test:** let an orchestrator obtain a truthful qualifying receipt for a blocked worker without waking that worker or recording a false skip.
- **Baseline:** today `codex_review(mode="implementation")` always derives both the review subject and receipt identity from the caller; the operational fallback changes the worker to Luna and has the worker review itself.
- **Measurable outcome:** a real review of the exact target worker snapshot yields a receipt that satisfies that worker's merge admission, while the identical merge with no receipt still returns `REVIEW_COVERAGE_MISSING` and `RECORD_REVIEW_THEN_NEW_OPERATION`.

## Hypotheses considered

1. **H1 — the cause is at subject selection in `codex_review`.** The tool conflates the caller with the reviewed worker, so an orchestrator review certifies the wrong worktree and identity. **Falsifier:** a caller-owned receipt can qualify for another worker without rewriting its immutable provenance or weakening `coverage_decision`.
2. **H2 — the correct owner is a post-review transfer in `record_review_outcome`.** A completed receipt can be rebound safely after the reviewer returns. **Falsifier:** the source receipt does not prove that the reviewer saw the target worker's exact snapshot, or transfer requires a second provenance record whose relationship is not represented by the current schema.
3. **H3 — the cause is the quota gate on the worker wake-up.** A narrow receipt-only turn can preserve the existing self-review workflow. **Falsifier:** the exception must trust message intent, still requires a second agent turn, or leaves caller/subject coupling unchanged.

## Method and measurements

The investigation read the current `main`-derived branch and the introducing history before accepting the ticket's line references. `git log -S'RECORD_REVIEW_THEN_NEW_OPERATION' main -- app/merge_operations.py` identifies `1a86f403` (#462) as the enforcing change; `git log -S'record_review_outcome' main -- app/mcp_stdio.py app/review_coverage.py app/merge_operations.py` identifies `6461ec9a` (#436) as the receipt start and `1a86f403` as the coverage extension.[1][2]

The deterministic probe uses two linked worktrees, a temporary SQLite database, and a fake background-job API; it never invokes Codex or writes production state. Command:

```bash
/home/kesha/orchestra/.venv/bin/python .orchestra/tasks/513/probe_current_behavior.py
```

Observed current behavior:

```text
actor on main: same_target_sha=true, same_worker_head=false, same_snapshot=false,
               receipt_session_id=orchestrator-session, receipt_task_id="",
               receipt_production_paths_json="[]",
               worker_gate_status=blocked, worker_gate_reason=review_receipt_missing
actor detached to worker HEAD: same_target_sha=true, same_worker_head=true, same_snapshot=true,
                               receipt_session_id=orchestrator-session, receipt_task_id="",
                               worker_gate_status=blocked, worker_gate_reason=review_receipt_missing
```

The pre-existing focused control command remains green:

```text
/home/kesha/orchestra/.venv/bin/python -m pytest -q tests/test_review_coverage_gate_462.py \
  -k 'test_t1_implementation_review_receipt_tracks_exact_production_snapshot or test_t3_only_exact_review_skip_or_unavailable_receipt_authorizes or test_t3_blocked_review_snapshot_refuses_before_operation_insert'
............ [100%]
12 passed, 10 deselected in 12.54s
```

This control proves the existing exact-session/snapshot gate still distinguishes a matching reviewed receipt from foreign-session and missing-receipt cases; it does not prove the new cross-session authoring path, which must become the frozen Phase-2 RED oracle.[3]

## Findings

### F1 — current `codex_review` conflates actor, subject, artifact owner, usage owner, and wake target

`codex_review` fetches only `/api/sessions/{WORKER_NAME}`, stores that row's `id/name/task_id` in the receipt, uses its worktree both as the review `cwd` and as the base for relative `output`, and wakes `WORKER_NAME` when the job ends (`app/mcp_stdio.py:3628-3641, 3674-3725, 3778-3828, 3904-3910, 3979-4005`). `coverage_decision` independently requires the merge worker's `scope + session_id + task_id + target_sha + production_snapshot_sha256` (`app/review_coverage.py:94-129`), and merge admission supplies the worker session/task (`app/merge_operations.py:802-828`).[1]

**Confidence: CONFIRMED — Tier 1 linked-worktree measurement reproduced both the ordinary mismatch and the detached-HEAD identity mismatch; Tier 2 primary code explains every observed field.**

### F2 — the causal seam is pre-review subject selection in `codex_review`

The smallest truthful change is an optional `target_worker` for `mode="implementation"` that separates two identities before reserving the receipt:

- **actor:** caller session, caller-relative output and `codex_sessions.json`, background-job `target_name/created_by`, and completion wake-up;
- **subject:** target worker worktree/base branch, receipt `session_id/worker_name/task_id`, pinned `target_sha/worker_head/production_snapshot_sha256/production_paths_json`, and the directory in which the generated `git diff target...worker_head` runs.

The receipt can record the caller in existing `decision_actor` while keeping the gate-owned identity fields equal to the reviewed worker. Keeping the artifact under the caller is necessary: writing a new review artifact into the blocked worker's clean worktree would itself make that worktree dirty, and the blocked worker could not wake to commit it. The target lookup is read-only (`GET /api/sessions/{name}` at `app/routes/sessions.py:323-329`) and does not require a worker turn. The target must resolve in the caller's exact scope and must be a worker rather than an orchestrator; Phase 2 must freeze both rejection cases.[1]

This seam leaves `coverage_decision` and both `REVIEW_COVERAGE_MISSING` refusal sites unchanged. A later production change still changes the snapshot hash; a target-branch advance still changes `target_sha`; a missing receipt still returns the current typed refusal.[1][3]

**Confidence: CONFIRMED as root-cause location — Tier 1 measurement shows that matching the exact subject snapshot is insufficient only because identity remains caller-owned; Tier 2 code shows subject identity is fixed before review reservation. The exact field split remains a Phase-2 design to freeze in tests.**

### F3 — post-review transfer is a larger and weaker seam

The current outcome path can only set `accepted | disputed | partial` (`app/db.py:2828-2830, 3013-3018`); it cannot mutate receipt start provenance because `review_receipt_finish` accepts only terminal execution fields (`app/db.py:2987-3010`). A safe transfer would therefore need an immutable derived receipt plus a durable source-receipt link and an exact source/target snapshot match. The schema has no dedicated source-receipt field.[2]

More importantly, the ordinary orchestrator receipt measured above contains the orchestrator's empty production snapshot, so it cannot truthfully be transferred to the worker snapshot. Transfer only becomes valid after the manual detached-HEAD workaround has already forced `codex_review` to inspect the right diff; even then it adds a second receipt and a second manual action. Rebinding without the hash equality would weaken the exact-snapshot gate and is rejected.

**Confidence: CONFIRMED — Tier 1 measurement shows the ordinary source receipt hashes the wrong subject; Tier 2 receipt APIs make start provenance immutable.**

### F4 — a quota exception treats the downstream blockage, not the ownership defect

Idle worker delivery is admitted before the turn and rejects a proven blocked decision (`app/session.py:1229-1269, 1295-1329`; `app/quota_gate.py:574-577`). A receipt-only exemption would have to classify or authorize a future agent turn before knowing which tools it will call, broaden a cross-cutting admission rule outside the receipt mechanism, and still spend a worker turn merely to make `codex_review` select itself. It does not let an orchestrator review the worker directly. The task also explicitly forbids changing quota admission as the solution.[4]

**Confidence: CONFIRMED — Tier 2 primary code locates the quota refusal upstream of arbitrary turn execution, while F1's caller/subject coupling remains unchanged.**

### F5 — README must change with the implementation

The ✅ comparison row currently states the exact live limitation: “the receipt is matched by the worker's own session id, so an orchestrator cannot certify a review on the worker's behalf” (`README.md:108`). Implementing H1 makes that sentence false. `README.md:179` also contradicts current production by saying review “is not yet enforced by the merge code”; Phase 3 must correct both statements and run `.orchestra/tasks/511/check_table.py`.[5]

The checker only asserts that `RECORD_REVIEW_THEN_NEW_OPERATION` remains present; it does not prove target-worker support or exercise the `REVIEW_COVERAGE_MISSING` behavior. Therefore the Phase-2 behavioral oracle, not the README checker, must protect both “targeted reviewed snapshot passes” and “no receipt still fails.”[3][5]

**Confidence: CONFIRMED — Tier 2 primary README and its executable checker directly name both claims.**

## Counter-evidence and limits

- A detached orchestrator worktree proves that a source receipt can have the correct snapshot hash despite the wrong session id. That keeps a narrowly validated derived-transfer design technically possible; it does not make transfer preferable because the detach and second operation remain manual, and the ordinary path still reviews the wrong diff.
- The existing schema has generic `model_source=derived`, `outcome_source=derived`, and `outcome_evidence_ref`; these fields could encode part of transfer provenance without a migration. They do not by themselves prove or enforce a source-receipt relationship, and `coverage_decision` currently does not validate such a relationship.
- The existing Luna model-change workaround remains a valid fallback and should stay untouched. This research does not measure its latency or frequency; it only shows that it requires a worker turn which the target-worker subject path avoids.
- The correct usage-attribution choice (caller session versus reviewed worker/task) has no pre-existing cross-session case. Phase 2 must make it explicit and test it rather than inheriting one of the two identities accidentally. Background-job `created_by` and receipt `decision_actor` can preserve the caller independently of coverage identity.

## Affected files, risks, and edge cases

- `app/mcp_stdio.py`: primary change; separate actor/subject resolution, command `cwd`, relative artifact location, receipt identity, job wake target, resume state, and usage attribution.
- `app/review_coverage.py`: no gate relaxation; likely unchanged production logic, but its resolver remains the single subject/snapshot owner and is part of the oracle surface.
- `app/merge_operations.py`: refusal behavior should remain unchanged; included only as an end-to-end assertion target.
- `tests/`: frozen RED must cover orchestrator-targeted exact review → satisfied, no receipt → typed refusal, wrong/stale target receipt → refusal, target not found, wrong-scope target, orchestrator-as-target, dirty target worktree, and caller artifact/wake ownership.
- `README.md`: replace the now-closed limitation at line 108 and the stale “not yet enforced” statement near line 179 while preserving the ✅ refusal claim; run `.orchestra/tasks/511/check_table.py`.
- Edge cases: target renamed between lookup and merge is safe because receipt selection uses immutable session id; target production commit after review is safe because the snapshot hash changes; evidence-only commits intentionally retain the same production hash; a dirty target must fail loud before review; `target_worker` on non-implementation modes should be rejected rather than silently ignored; requester output must not land in the target worktree.

## Review decision inputs

- **Changed files and consumers in this phase:** `.orchestra/tasks/513/research.md` and `probe_current_behavior.py`; later consumers named above. No production code changed.
- **Author metadata:** `gpt-5.6-sol`, Codex runtime, from live session `bfa9f5f2-57e0-46d5-a826-c5b7ec45a323`.
- **Exact research AC:** identify the causal seam, compare all three ticket options against exact-snapshot truth and no-review fail-closed behavior, and preserve the two explicit prohibitions.
- **Named checks and observed outputs:** the deterministic probe reports both worker gates `blocked/review_receipt_missing`; the focused #462 control reports `12 passed, 10 deselected in 12.54s`.
- **Risk floor and route:** causal design conclusion on a review/admission gate is high-risk. Canonical technical route would be Sol, but no auxiliary Sol run was explicitly authorized; per `codex-debate`, one Luna research review is used and cannot lower the risk floor.

## Review outcome

One Luna round found no blocking issue and raised four suggestions plus one scope question. The four suggestions were verified against current code and accepted above: corrected DB anchors, both stale README claims, the checker's narrower guarantee, and same-scope worker-only target validation. The scope question does not change the causal conclusion: `app/mcp_stdio.py`, `app/review_coverage.py`, `app/merge_operations.py`, `app/db.py`, `app/session.py`, and `app/quota_gate.py` independently establish F1-F4; the probe and tests are Tier-1 cross-checks, not the sole basis.

The artifact says `APPROVED`, but it contains neither a reviewer-run command plus output nor a verbatim line from the reviewed artifact that was absent from the prompt. Under `codex-debate`, the round is spent and substantive, but the formal result is **вердикта нет — review without completion evidence**. No second round is permitted for suggestions/question on a changed prose artifact without a blocking dispute.[6]

## Sources

1. **Tier 2, primary code:** `app/mcp_stdio.py::codex_review`; `app/review_coverage.py::{resolve_implementation_subject,coverage_decision}`; `app/merge_operations.py::{_review_coverage_for_snapshot,accept_merge_operation}`; `app/routes/sessions.py::get_session`.
2. **Tier 2, primary code/history:** `app/db.py::{_REVIEW_RECEIPT_COLUMNS,review_receipt_finish,review_receipt_set_outcome}`; commits `6461ec9a` (#436) and `1a86f403` (#462); `.orchestra/tasks/462/{research.md,plan.md}`.
3. **Tier 1, direct measurement:** `.orchestra/tasks/513/probe_current_behavior.py`; focused command against `tests/test_review_coverage_gate_462.py`, outputs recorded above.
4. **Tier 2, primary code and binding task:** `app/session.py::{preflight_delivery_admission,send}`; `app/quota_gate.py::require_worker_admission`; `task_get("513")` response fetched 2026-09-04.
5. **Tier 2, primary public contract/check:** `README.md:108`; `.orchestra/tasks/511/check_table.py`.
6. **Tier 2, independent model review without completed-verdict evidence:** `.orchestra/tasks/513/review-research-luna.md`.
