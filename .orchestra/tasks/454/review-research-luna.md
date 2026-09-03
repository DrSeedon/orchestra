<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

Apparently the destructive predicate is hiding a missing pair of parentheses 😏 The inventory counts, prompt failure, `bg_jobs` conclusion, and single-writer fan direction are supported, but the storage gate and fan break-even claims contain blocking issues.

## Findings

### [blocking] Parenthesize the storage predicate

**File:** `.orchestra/tasks/454/research.md:96-104` | **Confidence:** 0.99

As written, normal Boolean precedence parses this as `owner_terminal OR (approval AND no_consumer AND receipt)`, allowing any terminal-owned file through without receipt or consumer checks. The intended expression must group `(owner_terminal OR human_approval)` before the remaining `AND` clauses.

### [blocking] The measured predicate omits human approval

**File:** `.orchestra/tasks/454/research.md:174-202` | **Confidence:** 0.98

`measure_inventory.py` computes `owner_terminal & recoverable - head_consumers`; it has no approval input or approval branch. Therefore the reported 368 files are not the result of the stated `STORAGE_DELETE_OK`, only its no-approval subset. This must be labelled explicitly or the executable predicate and measurement must be aligned.

### [blocking] Consumer coverage is narrower than the claimed safety condition

**File:** `.orchestra/tasks/454/research.md:96-124` | **Confidence:** 0.97

The formula claims no live consumer, but the measurement scans only tracked, readable files up to 5 MB and only relative task/worker path tokens. Untracked, absolute-path, dynamic, binary, and larger consumers are invisible, so the result cannot prove the stated deletion safety condition.

### [blocking] Monetary and latency break-even are conflated

**File:** `.orchestra/tasks/454/research.md:339-343` | **Confidence:** 0.98

`$0.62–1.24` versus `$0.13` supports roughly 5–10 *eliminated billable calls*. It does not support 5–10 calls merely hidden from the critical path: hidden calls still cost money. Consequently, “3–7 files per worker” is not a latency threshold, and the text must separate monetary elimination from unmeasured wall-clock speedup.

### [blocking] Source deletion order lacks an immutable sink-evidence rule

**File:** `.orchestra/tasks/454/research.md:250-263,423-426` | **Confidence:** 0.88

The proposed order commits sink facts before deleting raw source, while `STORAGE_DELETE_OK` rejects current-path consumers. The research does not specify whether newly committed evidence references use immutable commit/blob receipts or current source paths. A current-path reference blocks deletion; silently exempting it leaves dangling evidence. The release contract must resolve this before destructive deletion.

### [blocking] Part 3 approval is not sufficiently content-bound

**File:** `.orchestra/tasks/454/research.md:253-257` | **Confidence:** 0.91

Part 3 requires a target, trigger test, and human approval, but does not bind approval to an exact prompt owner, role/scope set, proposed diff or digest, and live-owner success before prompt rollout. Because `global rule` is an allowed target, an unscoped approval could mutate shared prompt surfaces across projects.

### [suggestion] Label corrected and preregistered metrics separately

**File:** `.orchestra/kb/knowledge-pipeline.md:6` | **Confidence:** 0.94

The KB line combines exploratory set-level recall with exact-evidence rates from the original candidate-level scorer; `eval-score-setlevel.json` does not contain exact-evidence metrics. State explicitly that G419 is excluded only from the exploratory recall denominator and identify the provenance of each evidence rate.

## Verdict

**Overall Correctness:** ❌ Incorrect | **Confidence:** 0.98

The research is directionally useful, and conclusions about the failed prompt, absent durable extraction queue, and single-writer fan are supported. The storage predicate, deletion proof, approval contract, and fan economics need correction before Phase 1 can be approved.

The cleanup gate currently resembles a seatbelt whose buckle exists only in the prose.

## Round (2026-09-03T10:01:06Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Re-review status

The Boolean expression survived the second round—someone finally made it wear parentheses 😏 `git diff` was run; the requested files are untracked, so statuses below are verified against their current contents.

1. **FIXED — predicate precedence.** Parentheses now group `(terminal OR exact approval)` before the `AND` checks ([research.md:96](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/knowledge-pipeline/.orchestra/tasks/454/research.md:96>)-104).

2. **FIXED — 368 classification.** It is explicitly labelled the observed no-approval diagnostic subset; full deletion remains 0 ([research.md:178](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/knowledge-pipeline/.orchestra/tasks/454/research.md:178>)-184, 210-216).

3. **FIXED — consumer safety scope.** The contract is now fail-closed over a registered consumer set; lexical scanning is only an incomplete adapter and unknown consumers retain the source ([research.md:116](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/knowledge-pipeline/.orchestra/tasks/454/research.md:116>)-118, 428-430).

4. **FIXED — fan arithmetic.** Billable-call elimination is separated from wall-clock parallelism, and the unsupported file threshold is removed ([research.md:362](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/knowledge-pipeline/.orchestra/tasks/454/research.md:362>)-367).

5. **FIXED — deletion evidence.** Sink facts must use immutable source commit/path/blob/SHA evidence; current-path references block deletion ([research.md:276](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/knowledge-pipeline/.orchestra/tasks/454/research.md:276>)-280, 448-450).

6. **FIXED — Part 3 approval.** Approval is bound to exact owner, HEAD/blob or diff digest, roles/scopes, rule keys, delivery output, and live-owner validation ([research.md:270](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/knowledge-pipeline/.orchestra/tasks/454/research.md:270>)-274).

7. **FIXED — KB metric provenance.** The KB now separates exploratory source-valid set-level recall from preregistered exact-evidence results and identifies G419 exclusion ([knowledge-pipeline.md:6](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/knowledge-pipeline/.orchestra/kb/knowledge-pipeline.md:6)).

## New findings

None.

## Verdict

**APPROVED for Phase 1 prose/research.** The #429-versus-after-close ordering conflict remains explicitly pending user decision, as required. No files were edited.

> “Для **latency** порог вообще не измерен: fan может сократить wall-clock при тех же calls и большей цене.”

Теперь единственный открытый шлагбаум честно называется решением пользователя, а не маскируется под зелёную галочку.
