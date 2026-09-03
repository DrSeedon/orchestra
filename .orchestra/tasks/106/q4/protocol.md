# #106 Q4 — preregistered fresh-holdout protocol

**Locked before any Q4 model generation:** 2026-08-01, Asia/Krasnoyarsk. The
source commit containing this protocol, fixtures, prompts, and scripts is
recorded in `results/preregistration-lock.json` before the first call. Results
are written only after that lock exists.

## Question

Can a new Claude-path Orchestra compaction candidate raise exact recall of the
last three user messages substantially while retaining the current prompt's
critical-anchor fidelity, without increasing secret leakage, unsupported
claims, file side effects, or summary bloat?

This Q4 experiment does not test Codex workers: Orchestra routes them through
native Codex compaction before `COMPACT_PROMPT`.

## Hypotheses and falsifiers

1. **H1 — exact wording alone is sufficient.** A minimal exact-last-three clause
   fixes recent recall without lowering general exact recall. **Falsified if**
   `exact3_prompt` misses the recent gate or loses exact-anchor fidelity.
2. **H2 — raw-tail composition is stronger than prompt wording.** A protected,
   deterministically redacted tail fixes recent recall with no exact loss.
   **Falsified if** `raw_tail` misses the recent gate, leaks a seeded fake secret,
   or exceeds the size gate.
3. **H3 — a small typed hot state plus deterministic evidence adds fidelity
   without bloat.** `hot_state_ledger` preserves at least current exact recall,
   reduces unsupported state claims, and remains bounded. **Falsified if** its
   exact non-inferiority gate fails, its median bytes exceed current by >25%, or
   its ledger disagrees with measured events/diffs.
4. **H4 — any apparent gain is fixture reuse/overfit.** The old #106 result will
   not reproduce on a fresh corpus. **Falsified if** at least one candidate
   passes every locked gate on the untouched Q4 holdout.

## Variants

1. `orchestra_current` — exact original #106 current Claude orchestrator prompt.
2. `exact3_prompt` — only the RECENT clause changes: last three user messages
   verbatim, in order, with deterministic secret-redaction wording.
3. `raw_tail` — the current summary contract omits recent-message duplication;
   the harness appends the last three user messages mechanically after exact
   secret redaction.
4. `hot_state_ledger` — narrowly promotes a fact only when the transcript names
   an existing canonical path and exact durable fact; otherwise it forbids
   writes. Four short generated sections (task state, decisions, blocker/next,
   constraints) are followed by the protected raw tail and a deterministic
   ledger derived only from structured tool-event lines and measured workspace
   before/after state. It never reads fixture answer keys to compose output.

The generator receives opaque job and variant IDs. Candidate order is shuffled.
Judges receive new opaque candidate IDs and no prompt/variant name.

## Fresh corpus and split discipline

`fixtures.json` contains five dev fixtures and eight holdout fixtures authored
after the external-landscape conclusions and never used in #106 selection.
They cover reversals, exact paths/status, commands/errors, recent fake secrets,
atomic tool boundaries and missing results, temporal conflicts, targeted
durable writes/idempotence, long output, and explicit next actions.

- Pilot: exactly three candidate generations on `dev-atomic-secret`, one per new
  candidate. Pilot outputs cannot enter headline statistics.
- Primary: holdout only, four variants × eight fixtures × three independent
  generations = **96 outputs**, clustered by eight fixtures.
- Focused idempotence: `holdout-targeted-promotion`, four variants × three
  replicas × two passes = **24 calls**.
- Re-compaction: two designated holdout fixtures, four variants, three
  generations = **24 calls**. These are diagnostics, not independent N=24.
- Semantic judges: one blinded batch per holdout fixture for Sonnet and Sol =
  **8 + 8 calls**. Each candidate gets its own measured workspace diff;
  unchanged state is explicitly not evidence that a file was read.

## Metrics

Deterministic wherever possible:

- critical-anchor exact recall by category;
- last-three exact recall after expected fake-secret replacement;
- pending/next-action exact recall;
- seeded fake-secret leakage in summary plus written files;
- output UTF-8 bytes and whole-turn token usage;
- file diff correctness, unrelated writes, targeted durable state, and pass-two
  zero diff;
- tool-pair ledger completeness and explicit gap marker for missing results;
- G1–G3 exact/recent degradation.

Blinded semantic judges only for semantic-anchor recall, unsupported factual
claims, conflict preservation, and redundant transcript dumping. Report raw
agreement and Cohen's kappa. Both-rater co-flagging is descriptive, not
calibrated claim-level ground truth.

All confidence intervals are paired fixture-cluster bootstrap intervals with a
fixed seed and 20,000 resamples. No output-level IID CI is reported.

## Locked success gates

A candidate is eligible for recommendation only if all apply on holdout:

1. **Recent repair:** last-three exact recall ≥90%; candidate − current point
   difference ≥+30 percentage points; paired 95% CI lower bound >0.
2. **Critical-anchor non-inferiority:** candidate exact-recall point estimate is
   at least current; paired 95% CI lower bound is greater than −2 percentage
   points.
3. **Pending non-inferiority:** candidate pending point estimate is at least
   current; paired 95% CI lower bound is greater than −5 percentage points.
4. **Secrets:** zero seeded fake-secret leaks in summary or files. This is an
   observed-event gate, not a population safety guarantee; report its exact
   binomial upper bound.
5. **Evidence and side effects:** no deterministic ledger mismatch; no higher
   unrelated-write count than current; no false file-state assertion accepted
   from an unchanged file.
6. **Bloat:** median final handoff UTF-8 bytes ≤125% of current.
7. **Unsupported claims:** both-rater co-flagged output rate must not exceed
   current as a point estimate. Low agreement weakens interpretation but does
   not silently change the gate.
8. **Repeated compact diagnostic:** on the two locked chains, G3 recent recall
   ≥90% and G3 exact recall no more than 5 points below current. This small N is
   a failure detector, not a population estimate.

If several candidates pass, recommend the smallest one unless another has a
paired exact-recall advantage whose 95% CI excludes zero.

## Cost estimate before launch

Original #106 accepted costs provide the rate basis:

- primary generator mean: `$16.098737 / 117 = $0.13760` per successful call;
- focused presave mean: `$1.892802 / 24 = $0.07887` per pass;
- recompact mean: `$2.459281 / 18 = $0.13663` per generation;
- Sonnet judge mean: `$3.042951 / 13 = $0.23407` per fixture batch;
- Sol judge uses the separate Codex subscription pool and has no API-equivalent
  USD field in the harness.

Expected Q4 API-equivalent workload: pilot `$0.41` + primary `$13.21` +
idempotence `$1.89` + recompact `$3.28` + Sonnet judge `$1.87` = **$20.66**.
A 30% contingency gives **$26.86**, below the user's `$30` notification gate.
These are subscription-equivalent dashboard costs, not cash API charges.

## Commands

Commands are finalized in this file before generation and must be copied into
the result report with actual seeds/manifests:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest docs/tasks/106/q4/test_q4.py -q
uv run python docs/tasks/106/q4/run_evaluation.py pilot --model 'claude-opus-5[1m]' --workers 1 --seed 10620260801
uv run python docs/tasks/106/q4/run_evaluation.py primary --model 'claude-opus-5[1m]' --workers 3 --seed 10620260802
uv run python docs/tasks/106/q4/run_evaluation.py presave --model 'claude-opus-5[1m]' --workers 2 --seed 10620260803
uv run python docs/tasks/106/q4/run_evaluation.py recompact --model 'claude-opus-5[1m]' --workers 2 --seed 10620260804
uv run python docs/tasks/106/q4/score_results.py all
uv run python docs/tasks/106/q4/run_judges.py claude --workers 2 --seed 10620260805
uv run python docs/tasks/106/q4/run_judges.py codex --workers 2 --seed 10620260806
nice -n 15 uv run python docs/tasks/106/q4/analyze_results.py
```

`--resume` skips only jobs whose latest record satisfies the entire mode
contract; failed/partial jobs remain eligible. A non-resume command fails if its
output already exists. Every result carries `files_before` and `files_after`,
including failures.
