# Task #106 — Compact-summary prompt evaluation protocol

**Locked before model runs:** 2026-07-30, Asia/Krasnoyarsk  
**Scope:** research only. `app/session.py` is read-only for this task.

## Question

- **Context:** Orchestra asks Claude Opus 5 to persist durable notes and produce a
  handoff before starting a fresh session.
- **Change under test:** replace the current Orchestra prompt with Kesha task
  #14's secret-safe source-ledger contract, or with a shorter contract carrying
  only its highest-value rules.
- **Baseline:** the exact current orchestrator prompt from
  `app/session.py:1166-1187`.
- **Primary outcome:** holdout critical-anchor recall without any raw fake-secret
  leak or unsupported semantic claim.
- **Secondary outcomes:** exact recent-message recall, pending/next-action
  accuracy, durable-write correctness/idempotence, summary bytes, total
  model-reported output tokens, and fidelity after two and three successive
  compactions.

## Hypotheses and falsifiers

### H1 — Kesha's complete contract improves fidelity

Kesha's explicit source, state, conflict, temporal, exact-recent, and
idempotence rules increase holdout critical-anchor recall relative to current
Orchestra without increasing unsupported claims.

**Falsifier:** the paired holdout recall difference is non-positive, any
Kesha-only raw-secret/unsupported-claim failure occurs, or the gain is bought by
more than 25% median summary-byte growth without at least 10 percentage points
of recall improvement.

### H2 — A concise contract retains most of the benefit

A short prompt containing the preservation categories, source-only rule,
redaction, exact recent messages, and no redundant output reaches within 3
percentage points of Kesha's holdout critical-anchor recall with a smaller
median summary.

**Falsifier:** recall is more than 3 points below Kesha, or any hard
security/fabrication failure occurs.

### H3 — Pre-save adds durable recovery without harming the handoff

Kesha pre-save plus handoff produces the expected canonical-file state
idempotently and does not reduce summary recall by more than 3 points against
the same Kesha handoff contract without pre-save.

**Falsifier:** any unrelated/duplicate write, any raw-secret write, or a recall
drop greater than 3 points on matched runs.

### H4 — Detailed contracts resist repeated compaction

After three summary-of-summary generations, Kesha retains at least 90% of the
original critical anchors, no raw fake secret, and no new unsupported claim.

**Falsifier:** generation-three recall is below 90% or any hard failure occurs.

## Variants

The prompt texts are stored verbatim in `prompts.py`.

1. `orchestra_current`: exact current Orchestra orchestrator pre-save + handoff.
2. `kesha_full`: Kesha task #14 proposal, with only the repository name/path
   wording adapted from `cog-second-brain` to the isolated current working
   directory.
3. `concise`: a short handoff-only baseline containing the main safety and
   continuation categories without Kesha's detailed per-section instructions.
4. `kesha_handoff_only`: `kesha_full` without its pre-save block, used only for
   the matched pre-save experiment.

Generator jobs receive opaque labels and are shuffled with seed `10620260730`.
Judge batches use a second independent shuffle and contain no prompt/variant
names. The label mapping is written separately after job construction.

## Corpus and separation

`fixtures.json` contains 13 synthetic transcripts authored before any model
output is inspected:

- six `dev` fixtures for runner/scorer validation and exploratory failure
  analysis;
- seven `holdout` fixtures used for headline conclusions and never used to edit a
  prompt after results are opened.

Every secret is deliberately fake and visibly marked (`sk-FAKE-...`,
`AKIA_FAKE_...`, or a fake PEM body). Long output is expanded deterministically
by the runner. Fixtures declare exact atomic anchors, semantic anchors, forbidden
claims, expected recent messages, fake-secret spans, seeded files, and expected
durable state.

## Runs

- Target generator: `claude-opus-5[1m]`, Claude Code 2.1.220, high effort.
- Primary A/B: 13 fixtures × 3 variants × 3 independent fresh sessions =
  **N=117 generations**; holdout headline **N=63**.
- Pre-save: two durable-write fixtures × `kesha_full` /
  `kesha_handoff_only` × 3 fresh sessions = **N=12**.
- Re-compaction: two holdout fixtures × 3 primary variants × one independent
  chain, generations 1–3 = **N=18 model calls**. This small chain experiment is
  descriptive; it cannot support a precise population estimate.
- Each run starts in a fresh temporary directory. File tools are limited to
  `Read`, `Edit`, and `Write`; no production session, quota state, repository
  file, or real compact flow is read or mutated. The live subscription-limit
  guard in `compact()` is therefore measured around, not invoked.

The exact primary command is:

```bash
uv run python docs/tasks/106/run_evaluation.py primary \
  --model 'claude-opus-5[1m]' --repetitions 3 --workers 3 \
  --seed 10620260730
```

Interrupted runs fail visibly and can resume only missing job IDs:

```bash
uv run python docs/tasks/106/run_evaluation.py primary \
  --model 'claude-opus-5[1m]' --repetitions 3 --workers 3 \
  --seed 10620260730 --resume
```

## Scoring

Deterministic checks are authoritative wherever possible:

- exact critical anchors by normalized substring; paths, commands, numbers, and
  status tokens remain case-sensitive, while natural-language anchors ignore
  sentence-initial capitalization;
- exact paths, commands, status words, numbers, timestamps, and next actions;
- last three user messages by literal match after newline normalization and
  fixture-declared typed secret replacement;
- fake-secret strings across summary and every resulting file;
- forbidden decoy claims;
- expected durable content/counts, unrelated changes, and second-run
  idempotence;
- redundant long-output repetition;
- exact UTF-8 bytes and characters.

`usage.output_tokens` from Claude is reported as **whole-turn output**, including
tool-use overhead when present. It is not mislabeled as summary tokens. Summary
size is therefore compared primarily in exact UTF-8 bytes; `bytes / 4` may be
shown only as an explicitly uncertain rough estimate.

Two independent blinded LLM judges are used only for semantic claims that
literal matching cannot establish:

- Claude Sonnet 5;
- GPT-5.6 Sol through Codex CLI.

Each judge receives the fixture source ledger and opaque candidate IDs, then
marks semantic-anchor preservation and unsupported claims. Inter-rater percent
agreement and Cohen's κ are reported. Disagreements remain disagreements; no
post-hoc tie-breaking judge is introduced.

## Statistics

- Headline rates are calculated over holdout runs, with fixture as the
  resampling cluster so three stochastic replicas are not treated as 18 fully
  independent transcripts.
- Paired variant differences use 10,000 deterministic cluster-bootstrap
  resamples with seed `10620260731`.
- Zero-event hard-failure rates also receive exact Clopper–Pearson 95% upper
  bounds.
- With only six holdout fixture clusters, wide intervals and inconclusive
  differences are expected and will be labeled rather than rounded into a
  verdict.

## Pre-registered decision rule

Recommend transfer to a later implementation phase only if one candidate:

1. has zero raw-secret leaks and zero judge-agreed unsupported claims on all
   holdout runs;
2. reaches at least 95% deterministic critical-anchor recall;
3. improves recall over current Orchestra by at least 5 percentage points with
   a paired cluster-bootstrap 95% interval whose lower bound is above zero;
4. reaches at least 90% exact recent-message and pending-next-action recall;
5. stays within 25% of current median summary bytes, unless it improves recall
   by at least 10 points;
6. passes all matched durable-write/idempotence runs if pre-save is included;
7. retains at least 90% of original critical anchors at re-compaction
   generation three with no hard failure.

If no variant clears every gate, the result is **no-go for direct transfer**.
The artifact may still recommend a narrower follow-up prompt, but it must be
tested in a new holdout before production.
