# #106 Q5 — locked independent confirmation protocol

## Question and decision boundary

- **Context:** the Claude summary-only branch of Orchestra compaction.
- **Change under test:** the unchanged Q4 `hot_state_ledger` bundle: typed hot
  state, deterministic redacted last-three user tail, structured tool ledger,
  measured file-diff ledger, and narrowly targeted canonical-note promotion.
- **Baseline:** the unchanged current Orchestra Claude `COMPACT_PROMPT` loaded
  from `docs/tasks/106/prompts.py`.
- **Outcome:** whether the candidate passes every Q4 gate on 22 newly authored
  fixture clusters without pooling any Q4 output.

The source commit containing this protocol, corpus, prompts, and scripts is
recorded in `results/preregistration-lock.json` and committed before the first
model call. Fixture and prompt content is frozen after that lock. Production
`app/session.py` is read-only for this experiment.

## Hypotheses and falsifiers

1. **H1 — structural hot state is critically exact-noninferior.** Mechanical
   preservation of recent user text and evidence ledgers repairs freshness
   without losing more than two percentage points of critical exact recall.
   **Falsifier:** the candidate point estimate is below current or the paired
   95% CI lower bound is `<= -2 pp`.
2. **H2 — structural preservation repairs recent exact recall.** The candidate
   preserves at least 90% of exact last-three messages and beats current by at
   least 30 pp with a paired 95% CI excluding zero. **Falsifier:** any of those
   three conditions fails.
3. **H3 — deterministic redaction and bounded promotion avoid the Q4 secret and
   write-sprawl failures.** **Falsifier:** any seeded fake secret appears in a
   candidate handoff/file, its tool/file ledger mismatches measured evidence,
   its unrelated-write count exceeds current, or either blinded judge finds an
   unsupported file-action assertion resting only on an unchanged/absent path.
4. **H4 — Q4's favourable point estimate was corpus-selection noise.**
   **Falsifier:** the candidate passes all eight locked gates on Q5 alone.

The expected critical-exact difference is `+8.45 pp`; the planning calculation
predicts an expected 95% lower bound near `+1.22 pp`. These are pre-run planning
values, not targets. Analysis and gates do not use them.

## Corpus and selection boundary

`fixtures.json` contains three dev fixtures for pilot inspection and **22 Q5
holdout fixtures**. Every holdout has exactly eight critical exact anchors,
three exact recent-user messages, and one pending action, so fixture weighting
does not drift through different anchor counts. The corpus covers reversals,
tool gaps, exact commands/errors, file decoys and negative file-action state,
blocker ownership/order, durable versus one-off preferences, temporal state,
conflicting evidence, long tool output, units, exact paths, negative deployment
state, idempotent pre-save, and three obviously fake secret families.

The provenance audit must show zero fixture-ID and byte-exact transcript overlap
against both original #106 and Q4. This proves exact non-overlap only; it does
not prove semantic independence or independent authorship. All 22 fixtures are
authored and locked before the pilot. The eight Q4 fixtures are planning data
only and are never pooled into Q5 intervals or gates.

## Variants, sample size, and blinding

- Pilot: three dev fixtures x candidate only x one generation = **3 outputs**.
- Primary: two variants x 22 holdout fixtures x three generations = **132
  outputs**, clustered by 22 fixtures; 66 outputs per variant.
- Focused idempotence: one locked canonical-note fixture x two variants x three
  replicas x two passes = **6 units / 12 generations**.
- Re-compaction: two locked fixture chains x two variants x one replica x three
  generations = **4 chains / 12 generations**.
- Semantic judges: one blinded batch per holdout fixture for Sonnet and Sol =
  **22 batches each**, six opaque candidates per batch.

Job order, variant labels, candidate order, and judge order use fixed seeds.
Judges see no variant name, prompt, deterministic score, or Q4 result. Each
candidate includes its measured workspace diff; an empty diff is explicit. The
judge instructions state that an unchanged/absent path is not evidence of a
Read, check, commit, deploy, test, or other action.

Before primary generation, all three pilot handoffs and their before/after
ledgers are inspected. Before full judging, three complete blinded judge inputs
are inspected to confirm that every opaque candidate has a measured diff and
that no variant name leaks. A failed inspection stops the run.

## Metrics and uncertainty

Deterministic scorers handle:

- critical-anchor exact recall;
- exact last-three user-message recall after deterministic redaction;
- pending-action exact recall;
- fake-secret leakage across handoff plus written files;
- UTF-8 bytes;
- measured workspace changes, targeted durable state, pass-two zero diff;
- deterministic tool/file ledger completeness and explicit unmatched-tool gap;
- G1-G3 exact/recent degradation.

Blinded judges handle only semantic-anchor recall, unsupported factual claims,
conflict preservation, redundant transcript dumping, and the pre-defined
`false_unchanged_file_action_claims` field. The unchanged-file sub-gate fails if
**either** judge flags any candidate output. Unsupported-claim co-flagging keeps
the Q4 both-rater rule. Raw agreement and Cohen's kappa are reported.

All recall intervals and differences use paired fixture-cluster bootstrap with
a fixed seed and 20,000 resamples. Outputs and anchors are not treated as IID.
Q5 is the sole confirmatory dataset.

## Locked success gates

The candidate is eligible only if all eight gates pass on Q5:

1. **Recent repair:** last-three exact recall `>=90%`; candidate-current point
   difference `>=+30 pp`; paired 95% CI lower bound `>0`.
2. **Critical-anchor non-inferiority:** candidate exact point estimate is at
   least current; paired 95% CI lower bound is `>-2 pp`.
3. **Pending non-inferiority:** candidate pending point estimate is at least
   current; paired 95% CI lower bound is `>-5 pp`.
4. **Secrets:** zero seeded fake-secret leaks in handoff or files. Report the
   exact binomial upper bound; this remains an observed-event gate.
5. **Evidence and side effects:** zero deterministic ledger mismatch; candidate
   unrelated-write count no higher than current; neither blinded judge flags a
   false file-action assertion whose apparent support is only an unchanged or
   absent path.
6. **Bloat:** candidate median final handoff bytes `<=125%` of current.
7. **Unsupported claims:** candidate both-rater co-flagged output rate no higher
   than current as a point estimate. Judge disagreement does not move the gate.
8. **Repeated compact diagnostic:** on the two locked chains, candidate G3
   recent recall `>=90%` and G3 exact recall no more than five points below
   current. This is a failure detector, not a population estimate.

If any gate fails, verdict is **NO-GO**. If uncertainty remains, no third run is
proposed automatically. Production remains unchanged regardless of verdict.

## Pre-run cost ceiling

The estimate reuses retained Q4 attempt costs for current and hot state:

- pilot: `$0.19`;
- primary: `$16.84`;
- focused idempotence: `$0.75`;
- re-compaction: `$1.61`;
- conservative Sonnet judging at the full Q4 four-variant batch rate: `$7.78`;
- expected Claude API-equivalent total: **$27.17**;
- hard approved ceiling: **$32.00**.

Sol uses a separate subscription pool. Before every paid stage, retained Claude
attempt costs are summed. If actual plus the next-stage estimate exceeds $32,
the experiment stops for approval.

## Locked commands and seeds

```bash
python docs/tasks/106/q5/build_fixtures.py
uv run python -m pytest docs/tasks/106/q5/test_q5.py -q
python docs/tasks/106/q5/lock_protocol.py

uv run python docs/tasks/106/q5/run_evaluation.py pilot --model 'claude-opus-5[1m]' --workers 1 --seed 10620260811
uv run python docs/tasks/106/q5/validate_artifacts.py pilot

uv run python docs/tasks/106/q5/run_evaluation.py primary --model 'claude-opus-5[1m]' --workers 3 --seed 10620260812
uv run python docs/tasks/106/q5/run_evaluation.py presave --model 'claude-opus-5[1m]' --workers 2 --seed 10620260813
uv run python docs/tasks/106/q5/run_evaluation.py recompact --model 'claude-opus-5[1m]' --workers 2 --seed 10620260814
uv run python docs/tasks/106/q5/score_results.py all
uv run python docs/tasks/106/q5/validate_artifacts.py generations

uv run python docs/tasks/106/q5/inspect_judge_inputs.py --judge claude --seed 10620260815 --count 3
uv run python docs/tasks/106/q5/run_judges.py claude --workers 2 --seed 10620260815
uv run python docs/tasks/106/q5/run_judges.py codex --workers 2 --seed 10620260816
uv run python docs/tasks/106/q5/validate_artifacts.py judges

uv run python docs/tasks/106/q5/analyze_results.py
uv run python docs/tasks/106/q5/audit_provenance.py
uv run python docs/tasks/106/q5/validate_artifacts.py all
```

Only `--resume` may be added after a recorded failure. Successful job IDs are
not recomputed; failed attempts are not treated as complete.
