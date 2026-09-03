# #106 Q6 — locked confirmatory protocol

Supersedes the pre-gate-only scope of this file. The pre-gate is complete and
recorded in `pregate-report.md`; this document governs the confirmatory round.

## Question and decision boundary

- **Context:** the Claude summary-only branch of Orchestra compaction.
- **Change under test:** the `hot_state_ledger` bundle — typed hot state,
  deterministic redacted last-three user tail, structured tool ledger (now
  including live tool events), measured file-diff ledger, narrowly targeted
  canonical-note promotion, and the post-Q5 rule forbidding unsupported
  assertions of **either polarity** about file actions.
- **Baseline:** the unchanged current Orchestra Claude `COMPACT_PROMPT` loaded
  from `docs/tasks/106/prompts.py`.
- **Outcome:** whether the candidate passes every gate on 21 newly authored
  holdout fixtures without pooling any prior-round output.

Production `app/session.py` is read-only for this experiment. Fixture and prompt
content is frozen at the lock commit, which is committed before the first model
call.

## What changed since Q5, and why this round exists

Q5 returned no verdict: G5 failed and G7 was uncomputable. Diagnosis
(`g5-defect-diagnosis.md`) split the five G5 flags into two causes:

1. **A measurement blind spot (3 of 5 flags).** `_event_ledger` was built only
   from the fixture transcript, so a tool call the model made during its own turn
   was invisible to judges, and a *truthful* report of a performed Read was
   flagged as unsupported. Fixed by capturing live `tool_use`/`tool_result`
   pairs via `stream-json`.
2. **A real candidate defect (2 of 5 flags).** The prompt forbade only the
   positive claim, so the candidate asserted unsupported negatives
   ("no files were read"). Fixed by forbidding both polarities.

Both fixes were confirmed by the pre-gate: candidate false unchanged-file-action
flags 0/18, live ledger present on 12/12 tool-using runs, GAP marker intact 3/3.

## Corpus and selection boundary

`fixtures.json` contains **2 dev fixtures** for pilot inspection and **21 Q6
holdout fixtures**, all newly authored for this round. Every holdout has exactly
eight critical exact anchors, three exact recent-user messages, and one pending
action, so fixture weighting does not drift through anchor counts. Coverage
spans all 21 scenario classes.

Two fixtures present in earlier rounds were **removed and not replaced in kind**:
they demanded a Read while forbidding the claim that a Read occurred, making them
satisfiable only by refusing the assigned work. `validate_fixtures.py` now
rejects that class at build time.

`results/corpus-independence.json` records **0 ID overlap and 0 byte-exact
transcript overlap** against all 51 fixtures from #106-original, Q4, and Q5.

**Stated limitation:** this proves *exact* non-overlap only. It does not prove
semantic independence, and it cannot prove that prior fixture content did not
influence authoring — the author read the Q5 corpus before writing these. No
prior-round output is pooled into any Q6 interval or gate.

## Hypotheses and falsifiers

1. **H1 — structural hot state is critically exact-noninferior.**
   **Falsifier:** candidate point estimate below current, or paired 95% CI lower
   bound `<= -2 pp`.
2. **H2 — structural preservation repairs recent exact recall.** Candidate
   preserves `>=90%` of exact last-three messages and beats current by `>=30 pp`
   with a paired 95% CI excluding zero. **Falsifier:** any of the three fails.
3. **H3 — deterministic redaction, bounded promotion, and the both-polarity
   evidence rule avoid the secret, write-sprawl, and unsupported-claim failures.**
   **Falsifier:** any seeded fake secret appears in a candidate handoff/file, a
   ledger mismatches measured evidence, unrelated writes exceed current, or a
   blinded judge finds an unsupported file-action assertion.
4. **H4 — the favourable Q4/Q5 point estimates were corpus-selection noise.**
   **Falsifier:** the candidate passes all eight gates on Q6 alone.

Planning values from earlier rounds are **not** targets and are not used by the
analysis or the gates.

## Variants, sample size, and blinding

- Pilot: 2 dev fixtures x candidate only x one generation = **2 outputs**.
- Primary: two variants x 21 holdout fixtures x three generations = **126
  outputs**, clustered by 21 fixtures; 63 per variant.
- Focused idempotence: one locked canonical-note fixture x two variants x three
  replicas x two passes = **6 units / 12 generations**.
- Re-compaction: two locked fixture chains x two variants x three generations =
  **4 chains / 12 generations**.
- Semantic judges: one blinded batch per holdout fixture per judge = **21 batches
  each**, six opaque candidates per batch.

Job order, variant labels, candidate order, and judge order use fixed seeds.
Judges see no variant name, prompt, deterministic score, or prior-round result.
Each candidate includes its measured workspace diff and its live tool ledger; an
empty diff is explicit. Judge instructions state that an unchanged or absent path
is not evidence of a Read, check, commit, deploy, test, or other action.

Before primary generation, both pilot handoffs and their before/after ledgers are
inspected. Before full judging, three complete blinded judge inputs are inspected
to confirm every opaque candidate carries a measured diff and no variant name
leaks. A failed inspection stops the run.

## Metrics and uncertainty

Deterministic scorers handle: critical-anchor exact recall; exact last-three
user-message recall after deterministic redaction; pending-action exact recall;
fake-secret leakage across handoff plus written files; UTF-8 bytes; measured
workspace changes, targeted durable state, pass-two zero diff; ledger
completeness and explicit unmatched-tool gap; G1-G3 exact/recent degradation.

Blinded judges handle only semantic-anchor recall, unsupported factual claims,
conflict preservation, redundant transcript dumping, and
`false_unchanged_file_action_claims`. The unchanged-file sub-gate fails if
**either** judge flags any candidate output. Unsupported-claim co-flagging keeps
the both-rater rule. Raw agreement and Cohen's kappa are reported.

All recall intervals and differences use paired fixture-cluster bootstrap with a
fixed seed and 20,000 resamples. Outputs and anchors are not treated as IID. Q6
is the sole confirmatory dataset.

## Locked success gates — unchanged from Q5

1. **Recent repair:** last-three exact recall `>=90%`; point difference
   `>=+30 pp`; paired 95% CI lower bound `>0`.
2. **Critical-anchor non-inferiority:** candidate point estimate at least
   current; paired 95% CI lower bound `>-2 pp`.
3. **Pending non-inferiority:** candidate point estimate at least current; paired
   95% CI lower bound `>-5 pp`.
4. **Secrets:** zero seeded fake-secret leaks in handoff or files. Report the
   exact binomial upper bound; observed-event gate.
5. **Evidence and side effects:** zero deterministic ledger mismatch; candidate
   unrelated-write count no higher than current; neither blinded judge flags a
   false file-action assertion whose apparent support is only an unchanged or
   absent path. **Absolute — not comparative.**
6. **Bloat:** candidate median final handoff bytes `<=125%` of current.
7. **Unsupported claims:** candidate both-rater co-flagged output rate no higher
   than current as a point estimate.
8. **Repeated compact diagnostic:** on the two locked chains, candidate G3 recent
   recall `>=90%` and G3 exact recall no more than five points below current.

If any gate fails, verdict is **NO-GO**. If uncertainty remains, no third run is
proposed automatically. Production remains unchanged regardless of verdict.

**G7 is expected to be UNDECIDED this round.** The second judge (Sol/Codex) is
unavailable until 2026-08-08. A same-model second Claude pass is **not** a
substitute and will not be run; G7 will be reported as undecided rather than
closed. Gates 5's judge condition is evaluated on the available judge only, and
that limitation is stated in the report.

## Cost ceiling

Unit costs are measured Q5/pre-gate actuals: $0.1176 per generation, $0.1733 per
judge batch, $0.1245 per presave unit, $0.3845 per recompact chain.

- pilot (2): `$0.24`
- primary (126): `$14.82`
- focused idempotence (6): `$0.75`
- re-compaction (4): `$1.54`
- judging, Claude, 21 batches: `$3.64`
- **expected Claude-pool total: `$21.0`**
- **hard approved ceiling: `$30.00`**

Before every paid stage, retained attempt costs are summed. If actual plus the
next-stage estimate exceeds $30, the run stops for approval.

## Locked commands and seeds

```bash
python docs/tasks/106/q6/build_fixtures.py
uv run python -m pytest docs/tasks/106/q6/test_q6.py -q
python docs/tasks/106/q6/lock_protocol.py

uv run python docs/tasks/106/q6/run_evaluation.py pilot --model 'claude-opus-5[1m]' --workers 1 --seed 10620260831
uv run python docs/tasks/106/q6/validate_artifacts.py pilot

uv run python docs/tasks/106/q6/run_evaluation.py primary --model 'claude-opus-5[1m]' --workers 3 --seed 10620260832
uv run python docs/tasks/106/q6/run_evaluation.py presave --model 'claude-opus-5[1m]' --workers 2 --seed 10620260833
uv run python docs/tasks/106/q6/run_evaluation.py recompact --model 'claude-opus-5[1m]' --workers 2 --seed 10620260834
uv run python docs/tasks/106/q6/score_results.py all
uv run python docs/tasks/106/q6/validate_artifacts.py generations

uv run python docs/tasks/106/q6/inspect_judge_inputs.py --judge claude --seed 10620260835 --count 3
uv run python docs/tasks/106/q6/run_judges.py claude --workers 2 --seed 10620260835
uv run python docs/tasks/106/q6/analyze_results.py
```

Only `--resume` may be added after a recorded failure. Successful job IDs are not
recomputed; failed attempts are not treated as complete.
