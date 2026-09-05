# #506 — Review policy yield, rounds, resume, and spend

## Question

- Context: completed `codex_review` receipts in Orchestra, their pinned Git subjects, review artifacts, Codex thread identities, and usage accounting.
- Change under test: skip review below an empirical size/file threshold, cap executable review at two rounds, and reserve review for the final task diff plus genuinely hard primary work.
- Baseline: the current policy can review intermediate artifacts and permits three executable rounds.
- Outcomes: blocking-finding yield by changed lines/files; blocker yield in round 3; resumed-session share among completed follow-ups; attributable review token/cost coverage; blockers produced by Luna over Sol/Opus-authored work.

Snapshot: `2026-09-05T08:06:20Z`; database maxima at extraction were review request `2026-09-05T07:53:43Z` and review usage `2026-09-05T07:54:44Z`. The live database continued changing during research, so all denominators below come from the frozen [summary][2], not a later ad-hoc query.

## Hypotheses considered

1. H1: blocking yield collapses below a compact diff-size boundary because small final subjects mostly encode closed, mechanically checked changes.
   - Falsifier: a verified blocking finding occurs below every proposed small-size/file boundary, or the no-blocker share does not differ below it.
2. H2: round 3 adds no blockers because useful review findings arrive in the first two rounds.
   - Falsifier: a verified blocker first appears in round 3; every such case must be named.
3. H3: rounds 2+ usually start fresh because the caller omits `resume=True` or loses the sidecar binding.
   - Falsifier: stored thread IDs show most completed follow-ups reuse the prior review thread.
4. H4: review spend is absent from `turn_usage` because standalone `codex exec` bypasses managed session-turn accounting.
   - Falsifier: review receipts join to `turn_usage` under the actual key contract, or the subprocess finalizer directly writes usage rows.
5. H5: Luna-over-Sol/Opus review has negligible blocking yield.
   - Falsifier: Luna blockers are followed by attributable code changes in multiple Sol/Opus-authored tasks.

## Method and population

The read-only extractor [1] selected `status='completed' AND receipt_id LIKE 'review-receipt:%'`, joined the current session row, reconstructed historical author model across recorded `model change:` events, and measured each typed implementation subject with `git diff --numstat <target_sha>...<worker_head>`. Review text was resolved first by the receipt-time SHA, including Git history recovery; severity was then manually checked because a later clean verdict can mention prior blockers and fool a regex. The synthesis [2] freezes those classifications.

The snapshot contains 109 completed review receipts. Of those, 49 are typed `mode='implementation'`; 43 have non-empty `production_paths_json` and a resolvable production numstat. The six empty-path implementation receipts are not zero-size subjects: their complete diffs range from 143 to 14,933 text lines and from 2 to 4,667 files, with as many as 339 binary files [1].

The owner's supplied 185-run/65-task latency corpus is retained as the broader baseline and was not recomputed. The receipt-level analyses below use the 109 completed rows whose current schema and artifacts make the requested reconstruction possible; historical review usage predates that receipt population. These denominators are subsets, not a competing recount of the supplied 185 runs. Likewise, the supplied 83 Luna-over-Sol/Opus runs include non-completed attempts, while the value analysis below uses 65 completed receipts.

This exposes a premise error in the requested method. `production_paths_json` is a merge-coverage projection limited by `production_snapshot(... -- app scripts)`, while the reviewer is instructed to review the complete `git diff --binary --full-index target...worker` [3][5]. Therefore it is safe to use `production_paths_json` for the requested production-risk frontier, but not to call it the complete review subject or use an empty list as zero size.

## Findings

### 1. Size threshold: the only observed zero-blocker frontier is small and weakly sampled

Across the 43 production-measurable completed implementation rounds, outcomes were 25 blocking, 8 suggestion-only, 9 nothing, and 1 unclassified because the purported review returned only “provide the complete diff” [2].

| Maximum production size | Classified rounds | Blocking | Suggestion-only | Nothing |
|---|---:|---:|---:|---:|
| 20 lines / 1 file | 1 | 0 | 0 | 1 |
| 40 lines / 3 files | 2 | 0 | 1 | 1 |
| 50 lines / 3 files | 4 | 1 | 1 | 2 |
| 75 lines / 3 files | 9 | 4 | 2 | 3 |
| 100 lines / 3 files | 10 | 4 | 2 | 4 |
| 150 lines / 3 files | 13 | 5 | 3 | 5 |
| 250 lines / 5 files | 18 | 8 | 4 | 6 |

The proposed threshold is therefore **at most 40 changed production lines AND at most 3 production files**, subordinate to the already-decided “genuinely hard/high-risk primary work still gets review” rule. Below that boundary, review found **no blocker in 2 of 2 cases**; literally no finding occurred in 1/2, while the other produced two P2/non-blocking findings. The first observed blocker is only three lines above the boundary: task #502 round 1, **43 lines / 2 files**, where Luna found a malformed-JSON `AttributeError` in the merge path. Raising the boundary to 50/3 already gives a blocker in 1/4 cases; 75/3 gives blockers in 4/9 [2].

**Confidence: UNCERTAIN.** This is direct measurement (tier 1), but `n=2` below the proposed boundary is too small to claim a general safety law. It is a defensible observed frontier, not a statistical guarantee. The current high-risk corpus is also selection-biased upward: review receipts began around work on review/admission/lifecycle gates, exactly the surfaces most likely to produce blockers.

Implementation implication for Phase 2: measure the complete pinned diff and the production projection separately. A gate that treats empty `production_paths_json` as zero would skip non-Orchestra projects with enormous reviewed diffs. No `app/**` change is authorized in Phase 1.

### 2. Round 3 often produced blockers; reducing the ceiling is not free

There are 18 completed third-round receipts: **11 blocker-at-detection, 3 suggestion-only, 3 nothing, 1 unclassified**. Restricting to the 10 typed implementation third rounds: **6 blocker-at-detection, 3 suggestion-only, 1 nothing** [2]. Of those six typed blockers, five survived author verification and led to further work; #465's blocker was explicitly retracted in round 4 without a production code delta. The classification answers what the third round produced, not whether every reviewer claim was ultimately true.

| Task | Mode | Round-3 result | What appeared in round 3 |
|---:|---|---|---|
| 429 | review | nothing | all prior oracle findings fixed; no new bug |
| 90 | review | nothing | research claims downgraded; no new finding |
| 433 | exec | blocker | receipt validation occurred before a later trigger-mutating write |
| 93 | review | blocker | selected palette remained false durable metadata |
| 453 | exec | blocker | credential bypasses and normal Git-state false failures |
| 462 | exec | blocker | production trigger and unavailable-admission wording still disagreed |
| 465 | exec | blocker | post-mutation rollback crash path |
| 465 | implementation | blocker | promoted task allegedly left unbound; later re-review retracted this without a production code delta |
| 473 | implementation | blocker | SQLite/live-worker ownership could overlap or diverge |
| 474 | implementation | suggestion-only | legacy backslash path serialization |
| 102 | review | unclassified | reviewer said it could not verify the absent diff; no verdict |
| 480 | implementation | blocker | late legacy delivery could overwrite a turn-final report |
| 487 | implementation | blocker | unknown-call spend under-accounting and durable reason corruption |
| 493 | implementation | blocker | completion-order inversion let an older review supersede a newer one |
| 494 | implementation | blocker | repeated cancellation leaked worktrees/branches |
| 490 | implementation | suggestion-only | stale semantic-audit mappings |
| 500 | implementation | suggestion-only | angle-bracket Markdown destinations were not parsed |
| 499 | implementation | nothing | six prior blockers fixed; no new finding |

The existing KB facts are **extended, not contradicted or retracted**. `fact:review-design-three-round-miss` remains true for #409: three rounds can still miss a design defect. `fact:review-design-more-rounds-cure` also remains true: this observational sample does not prove that raising the generic round count is a reliable cure. New evidence does refute the stronger unstated claim “round 3 never emits blockers”: 6/10 typed implementation third rounds did, while 5/10 survived verification and one was retracted. The owner's fixed ceiling reduction from 3 to 2 therefore accepts a measurable loss; it is not free.

**Confidence: CONFIRMED** for the observed corpus (tier-1 receipt/artifact measurement); **UNCERTAIN** as a causal claim about future reviews because tasks reaching round 3 are a selected difficult subset.

### 3. Follow-up reviews usually resume; fresh re-ingestion is a minority defect

Thread identity is embedded in the actual `turn_usage.event_id`. Among 46 completed follow-up rounds with both a prior completed receipt on the same output and recoverable thread IDs, **42/46 (91.3%) resumed the same thread** and **4/46 (8.7%) started a new one** [2]. The four fresh cases were #489 plan round 2, #497 implementation round 2, and #500 implementation rounds 2 and 3. Their retained job commands did not contain `exec resume`, and no stale-session fallback marker appeared: the caller started fresh rather than a requested resume failing.

Wall time supports, but does not prove, the ingestion-cost hypothesis: resumed follow-ups had median **133.2 s**, p75 **181.6 s** (`n=42`); fresh follow-ups had median **293.3 s**, p75 **365.5 s** (`n=4`). Fresh was 2.20× slower at the medians, but `n=4` is too small for a stable latency estimate.

**Confidence: CONFIRMED** that most observed follow-ups resumed (provider thread identity, tier 1). **LIKELY** that fresh re-ingestion is slower (direct timing, but only four fresh observations). Resume enforcement is a useful cleanup for the 9% minority, not the broad explanation for the 228-second overall review median.

### 4. Review spend is already recorded; the zero-row result is an equality-join bug

The load-bearing “0 review rows in `turn_usage`” claim is **REFUTED**. `review_receipts.usage_event_id` stores a base key such as `codex-review:<uuid>`. `_record_usage()` deliberately writes `turn_usage.event_id = <base>:<thread_id>:<jsonl_line_number>` [4]. Therefore `turn_usage.event_id = review_receipts.usage_event_id` matches zero rows by construction; `turn_usage.event_id LIKE review_receipts.usage_event_id || ':%'` is the current relationship.

At the frozen snapshot:

- exact equality join: **0/109** completed receipts;
- prefix join: **103/109** completed receipts (94.5%); the six unmatched rows are all `mode='review'` rows with blank verdicts;
- those 103 linked rows contain **147,098,696 input**, **138,053,120 cached input**, **1,388,277 output** tokens and **$40.12794628** API-equivalent cost;
- the full historical `turn_usage` population contains **309** `codex-review:%` rows since 2026-08-13: **419,545,795 input**, **390,334,848 cached input**, **5,000,444 output**, **$86.88146508**;
- by reviewer: Luna **253 runs / $16.15985108**; Sol **56 runs / $70.721614** [2].

Accounting has existed since commit `503e71ec9` (`#215: account standalone Codex review usage`, 2026-08-12). The subprocess finalizer parses exactly one `turn.completed.usage`, calculates `_codex_cost`, and calls `turn_usage_add()` [4][6]. Thus the #505-style “outside session path, must compute by hand” explanation is stale for review. What is broken is discoverability/relation shape: the receipt stores a base ID while the usage table stores a composite ID without a separate foreign-key column. Phase 2 can either expose a dedicated receipt/base-event column or make the canonical reporting join prefix-aware; changing accounting itself is unnecessary.

**Confidence: CONFIRMED** (tier-1 database counts plus primary code and introducing commit).

### 5. Luna auditing Sol/Opus did change code often enough that removing it wholesale loses value

The frozen completed subset contains **65** Luna-over-Sol/Opus receipts. **8/65 (12.3%) review rounds across five tasks** have direct subsequent pinned Git deltas attributable to their blockers: #466, #474 (two rounds), #480 (two), #499 (two), and #502. A ninth round, #105, has weaker artifact-only evidence: its next review says all six prior code/harness findings were fixed and quotes the updated source, but the older receipt has no pinned `worker_head`. Including that supported case gives **9/65 (13.8%) across six tasks**. Within the newer typed-implementation subset, the direct lower bound is **8/24 (33.3%) rounds across five tasks** [2].

Concrete deltas after blockers include:

- #466: `app/merge_operations.py +14/-0`, `app/review_coverage.py +7/-2` after Luna found fail-open invalid legacy receipt handling;
- #474: `app/merge_operations.py +62/-23`, `app/merge_test_gate.py +6/-1`, `app/review_coverage.py +16/-6`, then another `app/db.py +7/-3`, `app/merge_operations.py +36/-1`, `app/review_coverage.py +7/-3` after the first two Luna rounds;
- #480: `app/fan_barrier.py +30/-12`, then `+5/-1` after two late-delivery blockers;
- #499: `app/ia/task_store.py +4/-4`, `app/routes/sessions.py +95/-45`, `app/tm.py +28/-0`, then another `app/routes/sessions.py +1/-1`, `app/tm.py +31/-26` after two rounds;
- #502: `app/merge_operations.py +6/-1` after the malformed-result crash finding;
- #105 (artifact-supported, not pinned): the next review explicitly marked all six gate/path findings fixed and quoted the now-canonical `REFERENCE_ROOT` source line [1][2].

Counter-evidence: #465's typed implementation round-3 blocker produced **no production delta**, and the next review explicitly retracted it (“the task was not orphaned; my first conclusion was”). Review blockers are sensors, not truth. Even so, the observed changed-code cases refute “cheap-over-expensive never adds value.” The larger saving must therefore come from final-diff-only review, the two-round ceiling, and the small-size gate—not a blanket ban on Luna reviewing Sol/Opus.

**Confidence: CONFIRMED** for the 8/65 pinned lower bound; **LIKELY** for the additional #105 artifact-supported case. Exact population-wide causal attribution remains **UNCERTAIN** because older non-typed review artifacts lack pinned worker heads.

## Review outcome

Luna completed one prose review with **no blocking findings** (`.orchestra/tasks/506/review-research-luna.md`). Its arithmetic reproduced the summary. Two suggestions were accepted: round-3 counts now say `blocker-at-detection` and separate the five surviving typed blockers from #465's retracted blocker; cross-model value now separates eight pinned Git deltas from #105's weaker artifact-only confirmation. The reviewer's question about “git-history inspection despite the prompt prohibition” was rejected after checking scope: the prohibition constrained the reviewer pass, while the Phase-1 extractor had already been required to recover receipt-time artifacts and recorded that method in [1]. No second review round is authorized because no blocker was raised.

## Counter-evidence and limitations

- Threshold evidence below the proposed boundary is only `n=2`; the corpus cannot justify a higher threshold.
- Tasks that reach round 3 are selected for difficulty, so 11/18 is not an estimate for arbitrary tasks.
- Current `sessions.model` can rewrite history. The extractor used model-change events when available and labels current-session fallback explicitly; cross-model counts remain a lower-bound evidence statement, not an immutable billing ledger.
- A blocker followed by a code delta is not proof that every changed line was caused by that finding. The named cases were accepted only when the next artifact classified the finding fixed or the delta touched the finding's production path.
- Six completed review receipts lack usage despite prefix matching; all six also lack a verdict. They are a small real accounting gap, not 185 invisible reviews.
- The 309-row historical spend aggregate includes review usage predating review receipts, so it cannot be joined one-to-one to the 109-receipt snapshot.

## Affected files, risks, and Phase 2 inputs

- `.orchestra/pipelines/default/prompts/skills/codex-debate.md` (or the current canonical source selected after #490): encode final-diff/hard-primary routing and executable ceiling 2. Do not edit before #490 merges.
- `app/mcp_stdio.py`: if the owner chooses a server-enforced size gate, compute both complete pinned numstat and production-path projection; never treat empty `production_paths_json` as an empty subject.
- `app/codex_review_artifact.py` / reporting query owner: accounting already writes rows; fix relation visibility, not token parsing.
- Edge cases for Phase 2: binary files, renames, empty production projection in non-Orchestra repositories, unresolved Git refs, a tiny high-risk auth/admission change, and a fresh follow-up that overwrites the accumulated artifact.

No prompt, skill, `app/**`, or test file was changed in Phase 1.

## Sources

1. `.orchestra/tasks/506/analyze_reviews.py` and `.orchestra/tasks/506/reviews.json` — read-only receipt extraction, exact Git numstats, artifact/version recovery, thread IDs, usage rows, and receipt-time text.
2. `.orchestra/tasks/506/summarize_reviews.py` and `.orchestra/tasks/506/summary.json` — frozen manual severity ledger and all reported denominators.
3. `app/mcp_stdio.py:4018-4516` — primary source for full-diff review command, `resume`, sidecar lookup, and usage-event reservation.
4. `app/codex_review_artifact.py:125-178,272-292` — primary source for JSONL usage parsing, composite usage event ID, cost calculation, and `turn_usage_add()`.
5. `app/review_coverage.py:90-127` — primary source for the `app`/`scripts` production projection and pinned triple-dot subject.
6. Git commit `503e71ec98d9648666c97b4d46c04f524cf282ba` — introduction of standalone Codex review accounting (`#215`, 2026-08-12).
7. Receipt-linked artifacts named in `.orchestra/tasks/506/reviews.json` — primary review text for round-3 and code-change classifications.
