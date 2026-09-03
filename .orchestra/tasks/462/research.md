# #462 — negative control for a review-coverage merge gate

## Question

- **Context:** successful Orchestra merges after the merge that deployed #436 review receipts.
- **Change under test:** reject a review-relevant production diff unless the same session/task has a completed structural review receipt or a machine-verifiable skip.
- **Baseline:** the merges that actually landed under the current acceptance and mapped-test gates.
- **Measured outcome:** how many already merged diffs the predicate rejects, with exact task/worker and `target_before → target_after` diffstat.

## Hypotheses considered

1. **H1 — the existing changed-path signal plus receipts is a usable coverage gate.** A merge with at least one changed `app/**` path is accepted when a same-session/task completed receipt exists before merge; otherwise it stops. Existing `mapped_files` is measured as a control, not made the production classifier. **Falsifier:** the predicate rejects routine legal merges for reasons that the canonical `codex-debate` policy explicitly permits, or `mapped_files` alone classifies test-only changes as production.
2. **H2 — a receipt-completion predicate is sufficient proof of coverage.** **Falsifier:** current receipt provenance cannot prove that the reviewed diff equals the accepted merge snapshot.

## Predicate and measurement boundary

The backtest is one read-only run of `backtest_review_coverage.py`. It reads `data/orchestra.db` with SQLite `mode=ro` and Git objects from `/mnt/data/Projects/Python/orchestra`; it imports no application code and writes no production state.[1]

The cutoff is not a calendar guess. It is strictly after successful merge operation `babd8668-66d0-4fa5-9812-fb0bed8d6bce`, which deployed #436 receipts at `2026-09-02T03:22:48.137371+00:00`, target `6461ec9a`.[1]

The measured predicate is:

1. the already computed target-relative changed paths contain at least **1** `app/**` path;
2. a review receipt for the same immutable `session_id` and task has both `requested_at` and non-null `completed_at` no later than merge start, with `status=completed`, `return_code=0`, `artifact_exists=1`, `artifact_bytes>0`, and `jsonl_response_present=1`; or a structured skip exists.

The numeric production-path threshold is **1**, the first non-zero value. A larger file or line-count threshold has no evidence: the history includes a real production-route diff at only one changed `app/**` file (#445), and review need does not disappear with line count. The `app/**` qualifier reuses the production prefix already used by `_prepare_admission_snapshot`/`select_tests`; it is not an `_id`/`key`/`email` classifier. `mapped_files>=1` is retained as a measured diagnostic: all 7 observed production candidates had it, but the code explicitly permits unmapped `app/**`, so it cannot be a necessary condition for future coverage.[1][2]

The current #436 schema cannot represent a skip: receipt `status` has requested/completed/failed/timed_out/interrupted, and `author_outcome` has accepted/disputed/partial/unknown. Therefore `structured_skip=false` for every historical row; report prose is deliberately not accepted as proof.[3]

## Result

The cutoff contains **12** successful Orchestra merges. Ten have `mapped_files >= 1`; three of those changed no `app/**` path, leaving **7 production-diff candidates**. The predicate accepts **3/7** and rejects **4/7 (57.1%)**.[1]

| Rejected merge | Worker | Mapped | Diffstat | Receipt/skip evidence |
|---|---|---:|---:|---|
| #441 | `fix-ratelimit-capture` | 2 | 3 files, **+142/-0** | no receipt; report has only prose `Review: none — Sol not authorized` |
| #445 | `fix-user-provenance` | 2 | 2 files, **+35/-33** | no receipt; no structured skip |
| #447 | `quota-headroom-bar` | 2 | 4 files, **+219/-5** | no receipt; no structured skip |
| #430 | `move-dot-orchestra` | 50 | 662 files, **+67,404/-818** | one interrupted receipt; no completed receipt or structured skip |

The three accepted candidates are #433 (**76 files, +5,210/-294**), #446 (**9, +154/-5**), and #452 (**4, +90/-17**); each has at least one completed receipt under the predicate.[1]

Raw `mapped_files >= 1` is not identical to “changed production code.” It also selects #442 (**1 test file, +4/-0**) and #448 (**4 test files, +4/-4**) although neither changed `app/**`. #453 likewise has a mapped test and a completed review receipt but changes no `app/**`; it changes an operational script/hook, showing that `app/**` is a conservative existing boundary rather than a complete universal definition of production.[1]

**H1 is REFUTED as a gate that can be enabled unchanged.** At least #441 is a canonical legal no-Sol-review outcome under `codex-debate`, yet the current data model provides no machine skip receipt, so the predicate rejects it. #445 and #447 are the intended coverage holes: they changed `app/**` and have neither a completed receipt nor a skip. #430 proves that an interrupted attempt is not the same fact as a completed review or a proven reviewer-unavailable skip.[1][4]

**H2 is REFUTED.** Existing receipts bind runtime/model/session/scope/task/artifact/mode/round/job/usage, but not `accepted_worker_head`, `target_sha`, or a reviewed-diff hash. Same session/task plus time is therefore only an upper-bound proxy: a stale plan review could satisfy the lookup while the implementation diff changes afterward. Phase 2 must extend the existing #436 receipt mechanism to bind the reviewed implementation snapshot; it must not create a second receipt store.[3]

## Constraints carried into Phase 2

1. **Production trigger:** start from the already computed `changed_paths`; do not add lexical topic triggers. The measured threshold is **1 changed `app/**` path**. Preserve `mapped_files` as evidence, not as the necessary trigger, because an unmapped `app/**` change must not bypass review. The plan must state explicitly whether operational `scripts/**` are in or out instead of silently relabeling them as `app/**`.
2. **Proven skip:** worker-authored report prose is not evidence. The skip decision must be a direct structured event in the existing #436 receipt path, and the canonical conditions remain owned only by `codex-debate`; the plan may reference/version that owner but may not copy its rule list.
3. **Reviewer unavailable:** canonical policy says `Codex unavailable → Review: none — Codex unavailable and continue`. A permanent fail-closed merge would contradict that policy. The gate must accept a server-produced unavailability/authorization receipt bound to the merge snapshot; an interrupted, timed-out, or failed review is not automatically equivalent to unavailable.
4. **Coverage binding:** a completed receipt must identify the exact implementation snapshot admitted for merge. Task/session identity alone is insufficient.

## Confidence and counter-evidence

- **CONFIRMED — tier 1 direct measurement:** the 12/10/7/4 counts, task list, receipt fields, and diffstats reproduce byte-for-byte in `history-backtest.json` from the named command.[1]
- **CONFIRMED — tier 2 primary code:** `mapped_files` contains selected test paths, while `changed_paths` supplies target-relative paths; current receipt enums have no skip representation and no reviewed-head/diff field.[2][3]
- **LIKELY, not measured as population rate:** 57.1% is the observed rejection rate in the short post-#436 window, not a forecast. Seven production candidates are too few for a stable rate.
- The backtest deliberately excludes pre-#436 merges because they could not have produced live #436 receipts. Counting them as receipt failures would measure rollout date, not gate behavior.
- `app/**` misses operational scripts/hooks (#453). Expanding the boundary requires an existing owner/registry in Phase 2; a new ad-hoc path vocabulary would violate the task.
- A completed receipt says a reviewer process returned an artifact, not that its verdict was correct. That is intentional: #462 closes coverage, not calibration.

## Affected files and risks for the later plan

- `app/merge_operations.py`: admission snapshot/finalization is the existing fail-closed merge seam; a new check must run before the irreversible target commit.
- `app/merge_test_gate.py`: owns `changed_paths`, selected tests, and `mapped_files`; raw `mapped_files` cannot distinguish test-only from `app/**` changes.
- `app/db.py`, `app/mcp_stdio.py`, `app/codex_review_artifact.py`: own #436 receipt creation/outcome/terminal provenance; extend these owners instead of introducing another receipt table/tool.
- `.codex/skills/codex-debate/SKILL.md` and its delivered pipeline owner: canonical review/skip policy. Do not touch PROJECT CONTEXT or add design-calibration prose.
- Main risks: stale receipt accepted for a later diff, quota/unavailability deadlocking all merges, test-only false triggers, operational scripts falling outside the `app/**` boundary, and a post-check mutation window before target commit.

## Review route

The conclusion affects a review/admission gate and has no independent implementation oracle, so the canonical route would be Sol. No auxiliary Sol run was explicitly authorized for this phase. One automatic Luna completeness/falsification pass timed out after ten minutes without a verdict, but its JSONL contained a substantive intermediate finding: the first draft's `mapped_files>=1` condition could let a future unmapped `app/**` change bypass the gate, and same-task/time receipt matching does not bind the reviewed diff. The first finding changed the predicate above; the second was already accepted as H2. The evidence-backed follow-up returned **ACCEPT WITH SUGGESTION** and reproduced the JSON exactly; its suggestion identified a missing `completed_at <= merge.created_at` filter. The filter is now applied and the artifact regenerated with unchanged 12/10/7/4 counts. The two-round prose ceiling is exhausted; no third review is opened.[4]

## Sources

1. **Tier 1, direct measurement:** `.orchestra/tasks/462/backtest_review_coverage.py`; `.orchestra/tasks/462/history-backtest.json`; command `/mnt/data/Projects/Python/orchestra/.venv/bin/python .orchestra/tasks/462/backtest_review_coverage.py --repo /mnt/data/Projects/Python/orchestra --database /mnt/data/Projects/Python/orchestra/data/orchestra.db`.
2. **Tier 2, primary code:** `app/merge_test_gate.py::changed_paths`, `select_tests`, `evaluate_test_gate`; `app/merge_operations.py::_prepare_admission_snapshot`, `_admission_evidence`; `app/diff_budget.py::measure_insertions`.
3. **Tier 2, primary code/artifact:** `app/db.py::_REVIEW_RECEIPT_COLUMNS`, `review_receipt_set_outcome`; `app/mcp_stdio.py::record_review_outcome`, `codex_review`; `.orchestra/tasks/436/research.md`; `.orchestra/tasks/436/report.md`.
4. **Tier 2, canonical policy and prior measurement:** `.codex/skills/codex-debate/SKILL.md`; `.orchestra/tasks/456/research.md`; `.orchestra/kb/review-design-defects.md`.
