# Task #106 Q4 — Structural repair of fresh-action handoff fidelity

**Date:** 2026-08-01  
**Phase:** research only; no production prompt or compact-flow change  
**Decision under the locked protocol:** **NO-GO for all three candidates.**
`hot_state_ledger` is the only credible next iteration, but it missed the
pre-registered exact-recall non-inferiority bound by 1.81 percentage points:
its exact point estimate was higher than current by 8.45 pp, while the paired
95% fixture-cluster CI was **[-3.81, +20.19] pp** and the gate required a lower
bound above -2 pp [1]. It is promising evidence, not a production-proof result.

## Question

- **Context:** the current Orchestra Claude compact path replaces history with a
  generated handoff. The first #106 experiment measured strong general exact
  recall but poor exact retention of the last three user messages.
- **Change under test:** three new candidates that move progressively from
  prompt wording to structural preservation: exact-last-three wording; a
  deterministically redacted raw user tail; and a typed hot state plus raw tail,
  measured file diff, structured tool-event ledger, and narrowly targeted
  durable promotion.
- **Baseline:** the exact current Claude orchestrator prompt loaded from the
  original #106 `prompts.py`; production `app/session.py` was read but not
  edited.
- **Outcome:** on a holdout with zero exact ID/transcript overlap with original
  #106, materially repair last-three exact recall
  while retaining current critical-anchor and pending fidelity, avoiding fake
  secret leaks and unrelated writes, staying bounded, and surviving three
  compactions.

The full hypotheses, falsifiers, gates, seeds, cost estimate, and commands were
locked in `protocol.md` before the first Q4 call. The source lock is commit
`6dc830cace5fe456906896ce9ece8a9774d1f505`; file hashes are in
`results/preregistration-lock.json`. The source commit is timestamped
16:32:40 +07, the lock commit 16:33:42 +07, and the earliest recorded pilot job
started later; `audit_provenance.py` verifies the ordering and hashes against
the committed blobs [2].

## Candidates

| Variant | Generated content | Structural content | Write policy |
|---|---|---|---|
| `orchestra_current` | Existing detailed sections | None | Generic CLAUDE/TODO/BUGS/docs pre-save |
| `exact3_prompt` | Current prompt with only RECENT changed to exact last three | None | Same generic pre-save |
| `raw_tail` | Current sections, excluding recent-message duplication | Deterministically redacted last three user messages | Same generic pre-save |
| `hot_state_ledger` | Four short sections: task state, decisions, blocker/next, constraints | Redacted last three user messages + structured tool events + measured workspace diff | Only an explicitly named existing canonical note with an exact durable fact; otherwise no write |

The structural composer does not inspect exact anchors, semantic anchors,
pending answer keys, or forbidden claims. A test mutates all those oracles and
requires identical composed output [3].

## Method and reproducibility

### Exactly non-overlapping split

The Q4 corpus has five dev and eight holdout fixtures. A post-hoc provenance
audit finds zero ID overlap and zero byte-exact transcript overlap with the
original #106 corpus [2]. This proves non-reuse of exact fixtures, not semantic
independence from the design process. Holdout themes are decision
reversal, confusing paths/statuses, command/error order, secret-bearing recent
messages, a missing tool result, temporal conflict/ownership, targeted durable
promotion, and a long noisy output. Pilot outputs and all earlier #106 outputs
were excluded from headline statistics.

- Pilot: three new candidates × one dev fixture = **3 outputs**.
- Primary: four variants × eight holdout fixtures × three replicas = **96
  outputs**, 24 per variant, with eight independent resampling clusters.
- Matched idempotence: four variants × three replicas × two passes = **24
  calls**.
- Re-compaction: two locked holdout fixtures × four variants × three sequential
  generations = **24 calls**; this is a failure detector, not a population
  estimate.
- Semantic judges: eight fixture batches each for Claude Sonnet 5 and GPT-5.6
  Sol = **16 calls**, covering the same 96 opaque candidates.

The pilot completed 3/3. Manual inspection verified three measured before/after
ledgers, no variant-label exposure, and zero seeded fake-secret leaks. The
prompt-only candidate already scored recent 1/3 because the model changed the
redaction type from `token` to `bearer token`; all candidates nevertheless
continued to the pre-registered full run, and the pilot did not enter headline
statistics [4].

### Commands

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest docs/tasks/106/q4/test_q4.py -q
uv run python docs/tasks/106/q4/run_evaluation.py pilot --model 'claude-opus-5[1m]' --workers 1 --seed 10620260801
uv run python docs/tasks/106/q4/run_evaluation.py primary --model 'claude-opus-5[1m]' --workers 3 --seed 10620260802
uv run python docs/tasks/106/q4/run_evaluation.py presave --model 'claude-opus-5[1m]' --workers 2 --seed 10620260803
uv run python docs/tasks/106/q4/run_evaluation.py recompact --model 'claude-opus-5[1m]' --workers 2 --seed 10620260804
uv run python docs/tasks/106/q4/score_results.py all
uv run python docs/tasks/106/q4/run_judges.py claude --workers 2 --seed 10620260805
uv run python docs/tasks/106/q4/run_judges.py codex --workers 2 --seed 10620260806
uv run python docs/tasks/106/q4/validate_artifacts.py all
nice -n 15 uv run python docs/tasks/106/q4/analyze_results.py
nice -n 15 uv run python docs/tasks/106/q4/posthoc_diagnostics.py
```

The harness invoked isolated CLI generations, not live `compact()`, so the
subscription-limit guard could not conditionally skip compaction. Every call
ran in a fresh temporary workspace. Every result, pass, and generation carries
`files_before` and `files_after`; the judge received each opaque candidate's
own measured diff. An unchanged path was explicitly not accepted as evidence
of a Read, test, commit, or deployment [3][5].

`validate_artifacts.py all` passed: 96 unique primary score IDs exactly match
96 successful generation IDs; both judges contain eight successful batches and
96 unique candidate judgments; all presave units contain two passes; all
re-compaction units contain three generations [5].

## Headline exactly non-overlapping holdout results

All recall intervals are paired fixture-cluster bootstrap intervals with 20,000
fixed-seed resamples. The experimental unit for uncertainty is the fixture, not
an individual output or anchor [1].

| Variant | Critical exact | Last-three exact | Pending exact | Median bytes | Secret-leak outputs | Unrelated file changes |
|---|---:|---:|---:|---:|---:|---:|
| Current | 79.3% (70.3–88.7) | 31.9% (13.9–51.4) | 74.1% (47.2–100) | 5,862 | 3/3 exposed | 72 |
| Exact wording | 75.6% (69.6–81.9) | 91.7% (75.0–100) | 100% | 5,294 | 3/3 exposed | 80 |
| Raw user tail | 73.7% (65.7–81.3) | **100%** | 100% | 4,814 | 2/3 exposed | 80 |
| Typed hot state + ledgers | **87.8%** (81.5–94.1) | **100%** | **100%** | **2,371** | **0/3 exposed** | **0** |

“Secret-leak outputs” counts only the three replicas of the one secret-bearing
holdout fixture per variant. For `hot_state_ledger`, 0/3 gives a two-sided exact
95% upper bound of **70.8%** only for a conditional per-generation leak rate on
this one transcript under an IID assumption. The three replicas are not
independent secret fixtures, so the bound is not a general secret-risk estimate
[1]. All eight observed leaking outputs wrote the seeded fake
token to `CLAUDE.md`; one current and one raw-tail output also leaked it in the
handoff itself [6].

### Paired differences from current

| Candidate | Critical exact | Last-three exact | Pending exact |
|---|---:|---:|---:|
| Exact wording | -3.76 pp [-11.94, +3.92] | +59.72 pp [+41.67, +77.78] | +25.93 pp [0, +52.78] |
| Raw user tail | -5.63 pp [-14.71, +2.82] | +68.06 pp [+48.61, +86.11] | +25.93 pp [0, +52.78] |
| Typed hot state + ledgers | **+8.45 pp [-3.81, +20.19]** | **+68.06 pp [+48.61, +86.11]** | **+25.93 pp [0, +52.78]** |

The raw-tail mechanisms conclusively repaired recent recall on this corpus: the
paired recent intervals exclude zero by wide margins. Prompt wording alone also
cleared the recent gate, but it did not make redaction deterministic and did
not fix unsafe generic pre-save.

The hot-state point estimate is the highest critical exact recall and its
handoff is 59.6% smaller than current, but the exact paired interval still
includes losses larger than the registered -2 pp tolerance. The post-hoc
bootstrap fraction at or below -2 pp is 4.675%; this diagnostic was not a
registered decision rule and does not override the CI gate [6].

## Locked gate outcome

| Gate | Exact wording | Raw user tail | Typed hot state + ledgers |
|---|:---:|:---:|:---:|
| Recent ≥90%, gain ≥30 pp, CI lower >0 | Pass | Pass | Pass |
| Critical exact point ≥current and CI lower >-2 pp | **Fail** | **Fail** | **Fail** |
| Pending non-inferiority | Pass | Pass | Pass |
| Zero observed fake-secret leaks | **Fail** | **Fail** | Pass |
| Ledger/side effects no worse than current | **Not fully evaluated / fail** | **Not fully evaluated / fail** | **Not fully evaluated / fail** |
| Median bytes ≤125% current | Pass | Pass | Pass |
| Both-rater unsupported co-flags ≤current | **Fail** | Pass | Pass |
| Generation-three failure detector | Pass | Pass | Pass |
| **All gates** | **NO-GO** | **NO-GO** | **NO-GO (6/8)** |

The evidence/write gate had three registered conditions. Ledger consistency and
unrelated-write counts were scored, but the analyzer omitted the condition that
an unchanged file must not be accepted as evidence of a Read or other action.
The judge prompt stated that rule, yet no gate scorer consumed the relevant
judgments. After adversarial review the combined gate is conservatively marked
not evaluated/failed for every candidate; the pre-review `7/8` was overstated.
The correction strengthens NO-GO and is preserved in `codex-review.md` [1][8].

This outcome is deliberately strict. Calling the hot-state bundle “proved”
would replace the registered non-inferiority gate with a more convenient
post-hoc rule after seeing a favourable point estimate.

## What improved, and what still failed

### Structural raw preservation fixed the measured freshness defect

`raw_tail` and `hot_state_ledger` achieved 72/72 exact recent-message matches.
This is expected from their mechanism: recent user strings are selected and
redacted mechanically, then appended after generation. `exact3_prompt` reached
66/72; all six misses were on the secret-bearing fixture where the model chose
a different redaction placeholder. **CONFIRMED for this harness/corpus — direct
measurement and deterministic composition test.**

### Typed hot state recovered commands and decisions, not all file/user state

Post-hoc category analysis localizes the remaining uncertainty [6]:

| Category | Current | Typed hot state + ledgers |
|---|---:|---:|
| Commands | 75.6% | **100%** |
| Decisions | 88.9% | **100%** |
| Pending anchors inside critical ledger | 83.3% | **92.9%** |
| Temporal | 75.0% | **83.3%** |
| Objective/status | 66.7% | 66.7% |
| Files/status | **86.1%** | 66.7% |
| User facts/preferences | **100%** | 50.0% |

The largest hot-state deficit versus current occurred on
`holdout-recent-secret`: current retained 21/21 critical anchors while hot state
retained 15/21. The missing material was older durable preference and negative
file/action state that did not live in the last-three-user block or structured
tool ledger. This concentration explains why a high aggregate point estimate
still has a wide paired interval with only eight clusters; it does not prove a
general causal mechanism.

### The hot-state bundle had zero observed write sprawl

Across 24 primary outputs, current produced 72 unrelated file changes, exact
wording 80, raw tail 80, and hot state zero. On the targeted canonical-note fixture,
hot state still produced the expected note state in 3/3 primary outputs.
In the focused two-pass experiment, every variant reached expected state 3/3 on
pass one, remained correct 3/3 on pass two, and had zero pass-two diff 3/3 [1].
This establishes that the targeted write can work idempotently in this fixture;
it does not isolate narrow promotion from the bundle's simultaneous changes to
generated sections, write prohibition, raw tail, and ledgers. It also does not
establish that all generic pre-save is harmful.

### Re-compaction favoured the structural bundle

On two locked chains, generation-three results were:

| Variant | G3 critical exact | G3 recent exact | G3 median bytes |
|---|---:|---:|---:|
| Current | 68.4% | 0% | 8,776 |
| Exact wording | 84.2% | 100% | 7,079 |
| Raw user tail | 73.7% | 100% | 5,893 |
| Typed hot state + ledgers | **94.7%** | **100%** | **2,408** |

These two chains pass the registered failure detector for every candidate but
are too few for a population claim. The current chain grew from median 5,948 B
at G1 to 8,776 B at G3 while retaining none of the exact last-three messages;
hot state grew from 2,199 B to 2,408 B and retained all recent messages [1].

## Semantic judges and disagreement

Both blinded judges covered all 96 outputs and saw the measured diff. Semantic
anchor recall was 100% for both raters and every variant, so it provided no
discrimination beyond deterministic exact scoring [1].

- Unsupported-claim raw agreement: **51.0%**, Cohen's kappa **0.083**.
- No-transcript-dump raw agreement: **87.5%**, kappa **0.0** because one label
  was nearly constant.
- Both-rater unsupported co-flags: current 14/24, exact wording 15/24, raw tail
  13/24, hot state 0/24.

The unsupported-claim reliability is poor. Sol flagged unsupported content in
15/24 hot-state outputs while Sonnet flagged 2/24, with no output co-flagged.
Examples include inferred retry consequences, assertions that no tests/reads
occurred, and causal interpretations of version mismatches. Therefore the
co-flag gate can reject a conspicuous failure but cannot certify factuality.
**CONFIRMED disagreement; UNCERTAIN absolute unsupported-claim rate.**

## Cost and operational outcome

All recorded Claude attempt records sum to **$23.7488** of API-equivalent
subscription workload:

| Component | API-equivalent USD |
|---|---:|
| Pilot | $0.4295 |
| Primary | $15.0617 |
| Idempotence | $1.5455 |
| Re-compaction | $3.8815 |
| Sonnet judge | $2.8306 |
| **Total** | **$23.7488** |

The JSONL files contain exactly the registered attempt counts (3 pilot, 96
primary, 12 two-pass presave units, 8 three-generation chains, and 8 Sonnet
judge batches), with no duplicate attempt records; therefore no failed retry is
hidden by latest-job deduplication [1][5]. Sol used the separate Codex
subscription pool and exposes no compatible USD field. The recorded Claude total stayed below the pre-launch 30% contingency
estimate of $26.86 and below the user's $30 notification gate [1][2].

## Counter-evidence and limitations

1. **The hot-state point estimate is favourable.** It beats current exact by
   8.45 pp, recent by 68.06 pp, pending by 25.93 pp, has zero observed leaks and
   unrelated writes, and is 59.6% smaller. A less conservative decision rule
   would select it. Counterpoint: that would be a post-hoc relaxation, and the
   registered lower bound misses the tolerance.
2. **Eight synthetic clusters are a weak population sample.** The exact result
   is sensitive to fixture composition and has a wide interval. Three replicas
   reduce generation noise but do not create 24 independent transcripts.
3. **The structural candidates are runtime bundles, not prompt-only edits.** Raw
   tail and ledgers require composition code. Their results cannot be attributed
   to prompt wording alone.
4. **The secret sample is tiny.** One secret fixture × three replicas gives a
   conditional 70.8% upper bound after zero hot-state leaks. Generic redaction recognizes the
   seeded fake families; it is not a production secret scanner.
5. **Semantic judging was poorly calibrated.** Kappa near zero prevents strong
   claims from either judge's absolute unsupported rate.
6. **External validity remains task-specific.** No public benchmark was run;
   `external-landscape.md` explains why MEMTRACK/LongMemEval would be a secondary
   validity probe rather than the deployment gate [7].

## Recommendation

**Do not change production `COMPACT_PROMPT` or the compact flow from this
experiment.** No candidate passed every locked gate.

If another paid experiment is approved, iterate only the hot-state bundle:
retain its typed state, exact raw-user block, tool ledger, measured diff, and
targeted promotion, but replace the three-message-only freshness boundary with
a bounded, deterministically redacted suffix of recent **atomic events**. The
suffix should keep whole user/assistant/tool-use/tool-result units under a
fixed token budget. This directly targets the observed misses in older durable
preferences and negative action/file state without returning to an unbounded
generated summary. This `hot_state_atomic_tail_v2` is **UNTESTED** and not a
production recommendation.

## Confidence by finding

| Finding | Confidence | Evidence tier and reason |
|---|---|---|
| Current Claude handoff loses recent user wording on a non-overlapping corpus | **CONFIRMED** | Direct measurement: 23/72 = 31.9%; original #106 measured 39.7% on a corpus with zero exact ID/transcript overlap |
| Structural raw-user append repairs last-three exact recall | **CONFIRMED on this harness/corpus** | Direct deterministic composition + 144/144 matches across two candidates |
| Prompt-only exact wording is sufficient | **REFUTED** | It missed 6/72 recent items and failed exact, secret, side-effect, and co-flag gates |
| Hot state is production-safe and exact-noninferior | **UNCERTAIN / NO-GO** | Favourable point estimates, but locked exact CI lower -3.81 pp misses -2 pp tolerance; secret N=3 |
| Atomic recent-event suffix will close the remaining exact gap | **UNCERTAIN** | Mechanism follows failure localization and external harness precedent; not measured here |

## Affected files and implementation boundary

Research artifacts are confined to `docs/tasks/106/q4/` and
`docs/artifacts/compact-prompt-q4-106.html`. Production implementation, if ever
approved, would affect the Claude branch of `AgentSession.compact()` and tests;
Codex native compaction is a separate path and is outside this candidate's
scope. No production file was changed in Q4.

## Evidence

1. `results/analysis.json` — registered headline estimates, paired intervals,
   focused experiments, judges, costs, and gate booleans.
2. `protocol.md`; `results/preregistration-lock.json`;
   `results/provenance-audit.json`; `audit_provenance.py` — pre-registered
   method, thresholds, source-blob hashes, source/lock/pilot ordering, exact
   corpus-overlap audit, and expected cost.
3. `test_q4.py`; `validate_artifacts.py`; `results/judge-input-inspection.json`
   — corpus separation, answer-key isolation, job/score coverage, measured
   ledger, and judge blindness checks.
4. `results/pilot-inspection.json`; `results/pilot-scores.json` — three-candidate
   pilot and manual inspection record.
5. `results/*-manifest.json`; `results/*-run.log` — exact seeds, model/CLI
   version, job counts, and failure diagnostics.
6. `results/posthoc-diagnostics.json`; `posthoc_diagnostics.py` — explicitly
   post-hoc category, fixture, tail-probability, leak-location, and file-state
   diagnostics.
7. `../external-landscape.md` — source-backed external harness, benchmark, and
   Ouroboros comparison that motivated the structural candidates.
8. `codex-review.md` — adversarial review, including the corrected incomplete
   evidence/side-effect gate and scope qualifications.
