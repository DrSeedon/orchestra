# Task #106 — Which compact-summary prompt actually preserves handoff state?

**Date:** 2026-08-01
**Phase:** research only; no production prompt or compact-flow change
**Verdict:** **do not transfer Kesha's full prompt into Orchestra as-is.** It
measurably improves recent-message fidelity and reduces bloat on this synthetic
corpus, but it did not improve overall exact-anchor recall or clear the
pre-registered 95% recall and generation-three retention gates. It also had
outputs independently flagged by both semantic raters for unsupported content.
The best next experiment is the shorter evidence-informed candidate in
`recommended-prompt.txt`; it is deliberately
**UNTESTED and not approved for production**.

## Question

- **Context:** Orchestra's Claude compact flow asks the active full-context
  session to persist notes and write a handoff, then starts a fresh session with
  only that handoff. The exact current prompt is in `app/session.py:1166-1187`.
- **Change under test:** Kesha task #14's detailed secret-safe, source-ledger,
  exact-recent, idempotent pre-save contract.
- **Baselines:** the exact current Orchestra orchestrator prompt and a concise
  handoff-only contract.
- **Outcome:** holdout critical-anchor recall with zero fake-secret leakage and
  zero unsupported claims, plus recent wording, pending action, output size,
  durable-write idempotence, and three-generation retention.

The full pre-registered protocol, thresholds, commands, hashes, and falsifiers
are in `protocol.md`. It was locked before the first counted generation.

## Hypotheses considered

1. **H1: Kesha's full contract improves fidelity.** Falsified if its paired
   holdout exact-recall difference is non-positive, it introduces a hard
   security/factuality failure, or bloat grows without a commensurate gain.
2. **H2: a concise contract retains most of Kesha's benefit.** Falsified if it
   trails Kesha by more than three recall points or causes a hard failure.
3. **H3: pre-save adds durable recovery without harming the handoff.** Falsified
   by a duplicate/unrelated write, secret write, or more than three recall
   points of matched degradation.
4. **H4: a detailed contract resists repeated compaction.** Falsified if
   generation-three exact recall is below 90% or a hard failure appears.

Observed status under the locked rules: H1 and H4 were refuted; H2 was falsified
by its hard-failure clause under the implemented output-level co-flag rule even
though concise tied Kesha's exact recall at lower size; H3 is inconclusive after
one of its two file-state fixtures was excluded post hoc for an ambiguous oracle.

## Method

### Corpus and generation

- 13 synthetic fixtures: six dev and seven holdout, authored before model
  outputs were inspected.
- Three primary variants, three fresh `claude-opus-5[1m]` generations per
  fixture: **117/117 completed**, of which **63 holdout**.
- Opaque per-job labels and shuffled order used seed `10620260730`.
- Every secret is visibly fake (`sk-FAKE-...` or `AKIA_FAKE_...`). No live
  session, real secret, production path, or real `compact()` call was used.
- The experiment measured around `compact()` rather than invoking it, so the
  live subscription-limit guard could not change the result.
- Dedicated matched pre-save: two fixtures × two variants × three repetitions,
  two sequential passes per experimental unit. The unambiguous canonical-note
  fixture is the only one used for the durable-file verdict.
- Re-compaction: two holdout fixtures × three variants × generations 1–3. With
  only two chains per variant, this is descriptive, not a population estimate.

Exact commands:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run python docs/tasks/106/run_evaluation.py primary \
  --model 'claude-opus-5[1m]' --repetitions 3 --workers 3 \
  --seed 10620260730
UV_CACHE_DIR=/tmp/uv-cache uv run python docs/tasks/106/score_results.py primary
UV_CACHE_DIR=/tmp/uv-cache uv run python docs/tasks/106/analyze_results.py
```

The secondary experiments and final corrected judges are reproduced with:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run python docs/tasks/106/run_evaluation.py presave \
  --model 'claude-opus-5[1m]' --repetitions 3 --workers 3 \
  --seed 10620260730
UV_CACHE_DIR=/tmp/uv-cache uv run python docs/tasks/106/run_evaluation.py recompact \
  --model 'claude-opus-5[1m]' --workers 3 --seed 10620260730
UV_CACHE_DIR=/tmp/uv-cache uv run python docs/tasks/106/score_results.py presave
UV_CACHE_DIR=/tmp/uv-cache uv run python docs/tasks/106/score_results.py recompact
UV_CACHE_DIR=/tmp/uv-cache uv run python docs/tasks/106/run_judges.py claude \
  --workers 2 --seed 10620260732
UV_CACHE_DIR=/tmp/uv-cache uv run python docs/tasks/106/run_judges.py codex \
  --workers 2 --seed 10620260732
UV_CACHE_DIR=/tmp/uv-cache uv run python docs/tasks/106/analyze_results.py
UV_CACHE_DIR=/tmp/uv-cache uv run python docs/tasks/106/validate_artifacts.py
```

Existing result files must be archived first or the runners fail loud; `--resume`
is only for completing missing or failed jobs.

Generated evidence is under `results/`; `results/analysis.json` is the numeric
source of truth. `usage.output_tokens` is reported only as **whole-turn output**
(including tool use), never mislabeled as summary tokens. Exact summary bloat is
measured in UTF-8 bytes.

### Scoring and statistics

- Deterministic scoring handled exact anchors, paths, commands, numbers,
  timestamps, recent messages, next actions, secret strings, file diffs, and
  repeated long-output lines.
- Seven holdout fixtures are the resampling clusters. Rates and paired
  differences use 10,000 cluster-bootstrap samples, seed `10620260731`.
- Two independent blinded semantic raters saw opaque candidates, the original
  source ledger, and each candidate's measured workspace diff: Claude Sonnet 5
  and GPT-5.6 Sol.
- The LLM judge was restricted to semantic anchors, unsupported claims, and
  transcript dumping. Variant names and deterministic scores were absent.
- A literal forbidden-claim substring check was found invalid because it
  treated a negated/rejected phrase as an asserted claim. It is retained in raw
  scores for audit but excluded from the verdict; semantic judges preserve
  qualifiers instead. This is a declared post-hoc method correction, not a
  hidden threshold change.

## Headline holdout results

All point estimates below use 21 holdout outputs per variant.

| Metric | Current Orchestra | Kesha full | Concise |
|---|---:|---:|---:|
| Exact critical-anchor recall | **91.3%** (81.3–100.0) | 89.1% (79.7–99.0) | 89.1% (80.1–98.3) |
| Last-three-message exact recall | 39.7% (9.5–71.4) | **95.2%** (85.7–100.0) | 93.7% (84.1–100.0) |
| Pending/next-action recall | 81.0% (52.4–100.0) | 85.7% (57.1–100.0) | 85.7% (57.1–100.0) |
| Median summary UTF-8 bytes | 6,378 | 4,837 | **2,803** |
| Median whole-turn output tokens | 5,093 | 2,385 | **1,049** |
| Deterministic clean runs | 5/21 | **10/21** | 9/21 |
| Fake-secret leaks in exposed runs | 0/6 | 0/6 | 0/6 |

Parentheses are 95% fixture-cluster bootstrap intervals. The secret result is
not strong proof: zero leaks in six holdout exposures has a two-sided exact 95%
upper failure-rate bound of **45.9% per variant**. “Observed zero” must not be
rounded into “safe.”

### Paired differences

- **Kesha − current exact recall:** −2.19 percentage points, paired 95% CI
  **[−4.60, 0.00]**. Kesha did not improve the primary fidelity metric.
- **Kesha − current recent recall:** +55.56 points, **[+26.98, +82.54]**. This
  is the one clear, load-bearing improvement on this synthetic corpus.
- **Kesha − current pending recall:** +4.76 points, **[0.00, +14.29]**. The
  sample does not establish a positive population effect.
- **Concise − Kesha exact recall:** 0.00 points, **[−1.82, +1.49]**.
- **Concise − Kesha recent recall:** −1.59 points, **[−4.76, 0.00]**.
- **Concise − Kesha pending recall:** exactly 0.00 points in this corpus.

Kesha was 24.2% smaller than current by median summary bytes; concise was 56.1%
smaller than current and 42.1% smaller than Kesha. Whole-turn token reductions
were larger (53.2%, 79.4%, and 56.0% respectively). Current's much higher
measured file-write volume is a plausible mechanism, but output tokens were not
decomposed by tool-call phase, so this is not a causal attribution. These token
values are not summary-only.

## Which prompt changes actually helped?

### Confirmed

1. **The two bundles that require the last three user messages verbatim improve
   recent-message recall.** Kesha and concise both contain that instruction;
   both gained about 54–56 points over current, while differing greatly in
   length. Current's “last 5–10 exchanges in detail” is not an
   exact-preservation contract. **CONFIRMED at bundle level — paired holdout CI
   excludes zero.** The verbatim-last-three clause is the most plausible driver,
   but this experiment did not isolate it in a one-clause ablation, so a causal
   effect for that clause alone remains **LIKELY on this synthetic corpus**, not
   confirmed.
2. **The two bundles with relevance filtering and no “no length limit” clause
   are smaller.** Kesha and concise say to omit redundant raw output and were
   respectively 24.2% and 56.1% smaller than current. **CONFIRMED at bundle
   level for this corpus — exact byte measurement.** Which individual wording
   change caused the reduction was not isolated.
3. **Targeted canonical-note pre-save can be idempotent.** On the unambiguous
   fixture, Kesha full produced the expected file state 3/3 on pass one, kept it
   correct 3/3 on pass two, and pass two had zero diff 3/3. Handoff-only
   produced the expected durable state 0/3. **CONFIRMED narrowly — direct file
   measurement, N=3.**

### Not confirmed or refuted

1. **The complete Kesha section taxonomy did not increase exact recall.** It
   tied concise and trailed current by 2.19 points. Holdout misses remained in
   files (9), commands (8), and objective/phase anchors (3). **REFUTED as an
   overall recall improvement in this corpus.**
2. **Kesha's additional detail beyond the concise contract did not buy
   measurable recall.** Exact and pending recall tied; recent recall differed by
   only 1.59 points, while concise was 42.1% smaller. **LIKELY unnecessary —
   holdout comparison, but the CI permits a small recent benefit.**
3. **The secret rule was not proven necessary by this sample.** All three
   variants leaked zero fake secrets, including current, and the exposure count
   is small. Keep a global redaction rule because the consequence is severe,
   but do not claim this experiment estimates its protection rate.
   **UNCERTAIN — zero events, wide exact upper bound.**
4. **The current bundle made far more generic-file writes.** In all 39 primary runs,
   current changed files 39/39 times and made 162 file changes; Kesha changed
   one targeted file in 30/39 runs (30 changes total); concise wrote nothing.
   This is a direct volume measurement, not proof that every current write was
   wrong. **CONFIRMED volume difference; correctness varies by fixture.**

## Semantic judge results and their limitation

Both raters marked all 351 semantic anchors present, a complete ceiling effect;
this rubric cannot discriminate the prompts.

On holdout unsupported-claim detection:

| Variant | Sonnet outputs flagged | Sol outputs flagged | Both flag output |
|---|---:|---:|---:|
| Current | 9/21 | 20/21 | 9/21 |
| Kesha full | 7/21 | 21/21 | 7/21 |
| Concise | 2/21 | 14/21 | 2/21 |

Final cross-model agreement for “any unsupported claim” was only **41.3%;
holdout Cohen's κ = 0.110**. The positive rates were 28.6% for Sonnet and 87.3%
for Sol. The invalid pre-correction judge run is not numerically compared because
it measured against an incomplete source ledger. Therefore neither rater's
fabrication count is a calibrated ground truth. The implemented intersection
means only that both raters independently flagged the same output; it does not
mean they identified the same claim. Under that output-level co-flag rule, no
variant met the zero-fabrication gate, and concise had fewer co-flagged outputs.
The full claim texts remain in the blinded judge artifacts.

For no-transcript-dump, holdout raw agreement was 93.7%, but κ is 0 because Sol
marked all 63 outputs positive (no negative variance). Sonnet passed current
18/21, Kesha 20/21, and concise 21/21. Treat this as corroboration of the exact
byte result, not an independent precise rate.

## Compaction of compaction

Two three-generation chains per variant produced:

| Variant | G1 exact | G2 exact | G3 exact | G3 recent |
|---|---:|---:|---:|---:|
| Current | 16/18 (88.9%) | 16/18 | 16/18 | 3/6 |
| Kesha full | 16/18 (88.9%) | 16/18 | 16/18 | **6/6** |
| Concise | 15/18 (83.3%) | 15/18 | 15/18 | **6/6** |

No variant reached the pre-registered 90% generation-three exact-recall gate.
Kesha preserved recent wording perfectly in these two chains, while current
preserved half. Current summaries grew from 5,779/8,267 bytes at G1 to
8,925/10,222 at G3; Kesha grew more modestly from 4,652/6,637 to 5,694/6,928;
concise stayed approximately flat. With N=2, these are failure examples, not
stable rate estimates.

## Pre-save versus handoff-only

The clear canonical-note fixture demonstrates that **targeted** pre-save can be
idempotent in a controlled case:

- Kesha full: expected durable state 3/3 after the first pass; still correct
  3/3 after retry; second-pass zero diff 3/3; zero fake-secret leaks.
- Kesha handoff-only: expected durable state 0/3; second pass naturally had no
  diff because it never wrote.

Across the matched first pass of both fixtures, pre-save + handoff retained
36/36 exact anchors (100.0%) versus 34/36 (94.4%) for handoff-only, a descriptive
+5.56-point difference. Recent recall tied at 15/18, pending recall tied at 3/6,
and median summaries were 5,444 versus 5,563.5 bytes. This establishes no
observed handoff degradation in these six paired outputs, but only two fixture
clusters are far too few for a useful confidence interval or a general benefit
claim.

The preference fixture is excluded from the file verdict because its fixture
expected `CLAUDE.md` to remain byte-identical while the transcript declared a
durable operating preference and the prompt reserves `CLAUDE.md` for stable
operating rules. Kesha wrote the preference idempotently 3/3. That is an
ambiguous oracle, not a model failure; the post-hoc exclusion is explicit.
Because locked H3 covered both fixtures and treated any unrelated write as a
falsifier, the overall pre-save comparison is **INCONCLUSIVE**, not a passed
target. It requires a new unambiguous holdout before any keep/remove decision.

## Failure taxonomy

1. **Exact evidence drops:** files and commands dominate all variants. More
   section names did not force exact retention.
2. **Current recent paraphrase:** “in detail” preserved topic, not wording.
3. **Unsupported environment state:** summaries sometimes asserted branch,
   clean-worktree, date, file-read, or diagnostic conclusions not established by
   transcript/tool evidence. Concise had fewer co-flagged outputs but did not
   eliminate this.
4. **Pre-save sprawl:** the current bundle's generic mandatory file list was
   associated with far more writes and whole-turn tokens than targeted
   canonical-note persistence; tool-phase tokens were not separately measured.
5. **Repeated-compaction bloat:** current grew substantially over three
   generations; Kesha grew less; concise stayed flat but began with lower exact
   recall.

## Pre-registered decision

No candidate passes all gates:

- exact recall was 91.3%, 89.1%, and 89.1%, all below 95%; neither challenger
  improved current by the required +5 points with a positive paired CI;
- zero-fabrication failed under the implemented output-level co-flag rule (9, 7,
  and 2 outputs), without establishing claim-level agreement;
- Kesha passed the recent target, but its preregistered pre-save comparison was
  inconclusive and generation-three exact recall was 88.9%, below 90%;
- the zero-leak observation is too sparse to certify safety.

**Verdict: NO-GO for direct transfer of Kesha full, concise, or the current
prompt unchanged as a newly “validated” contract.** Production should remain
unchanged until a new candidate clears a new holdout.

## Concrete recommendation

`recommended-prompt.txt` is the exact next candidate. It is an untested
composite of bundle-level signals, safety requirements, and failure-derived
hypotheses:

- exact last-three user messages;
- source-only claims with explicit prohibition on inferred repo/read/deploy
  state;
- global secret redaction;
- exact critical paths/commands/numbers/statuses;
- blocker/owner/next action;
- relevance filtering;
- targeted, idempotent pre-save only to an already established canonical path;
- no automatic creation of CLAUDE.md/TODO.md/BUGS.md/docs solely for compact.

It is shorter than Kesha full and adds an evidence-discipline clause motivated
by the co-flagged outputs and judge claim text. Redaction, targeted pre-save,
pending wording, and this new clause were not isolated wins. The candidate has
**not** been evaluated; editing it after holdout and declaring it a winner would
be overfitting. A later task must test it against a new holdout before
implementation approval.

## Methodological incidents and fixes

1. **Provider 529 during primary generation.** Five of 117 jobs returned
   `api_error_status=529 Overloaded` after 192.9–233.1 seconds. Verbatim errors
   identified provider overload; `--resume` later completed only those five.
2. **`--resume` silently treated failed job IDs as completed.** The original
   loader counted any recorded ID. It now counts only mode-specific successful
   terminal artifacts; scorers select the latest record per job. Synthetic
   regression checks proved 112 successes + five retry targets before rerun.
3. **Semantic judge hit the Claude window.** The first judge attempt returned
   13/13 terminal 429s with `duration_api_ms=0`, cost $0, and no partial ratings.
   `/api/usage` showed this was the exhausted 5h window with supplemental
   capacity disabled, not cash spend. The method waited for the base window
   rather than substituting same-model Sol agreement.
4. **The initial judge ledger omitted generation-time file diffs.** Both judges
   then mislabeled real pre-save writes as fabrications. Those two full judge
   runs were invalidated and archived. The corrected ledger supplies each
   opaque candidate's exact measured before/after diff, states that an unchanged
   file does not prove Read, and preserves blindness. Coverage is 122/122 raw
   generation records and 117/117 latest successful jobs. A three-candidate
   Sonnet pilot visually confirmed the diff and zero variant-name leakage before
   the final two full judge runs.
5. **The locked protocol has two related narrative count typos.** Its statistics
   section says “six holdout fixture clusters” and “18 independent transcripts,”
   while its corpus and run sections say seven fixtures and the actual headline
   has 21 outputs per variant. Analysis used all seven clusters and 21 outputs,
   recorded in `analysis.json`; no prompt, gate, or threshold was changed after
   outputs were opened.

The final accepted Claude evidence cost was **$23.506 API-equivalent**
($16.099 primary success, $0.012 failed 529 attempts, $1.893 pre-save, $2.459
re-compaction, $3.043 final Sonnet judge). Including the invalid judge run and
two excluded pilots, all Claude calls totaled **$26.282 API-equivalent**. This
was subscription workload, not cash charged. Codex judge usage came from its
separate subscription pool and has no comparable per-call USD artifact.

## Counter-evidence and limitations

- Seven holdout fixture clusters make intervals wide. Three stochastic runs do
  not turn seven source traces into 21 independent trace types.
- Synthetic transcripts are controlled and scoreable but shorter and cleaner
  than a real near-limit Orchestra transcript. Long-output placeholders test
  noise pressure, not a 1M-token attention regime.
- The generation wrapper presents a rendered transcript in one request rather
  than replaying a native multi-turn SDK session. It tests summarization and
  tool behavior, not every runtime-context effect.
- The exact-anchor scorer can miss semantically correct paraphrases; that is why
  the semantic rubric existed. Conversely, both semantic raters saturated at
  100% anchor recall, so that rubric was too easy.
- LLM fabrication raters disagreed severely. Output-level co-flagging is
  conservative evidence that failures exist, not claim-level agreement or a
  calibrated failure-rate estimate.
- Secret exposure was deliberately sparse and fake. Zero observed leaks is not
  evidence that arbitrary secret forms are safe.
- Pre-save correctness is established only for one unambiguous canonical-note
  fixture with N=3.
- Re-compaction N=2 is useful counterexample evidence but not a stable estimate.

## Affected files and risks for any later implementation

Potential production scope is only `app/session.py:compact()` prompt assembly
plus prompt-specific tests/fixtures. Do not touch reset, acknowledgement,
session-ID transaction, quota guard, or Codex native compact based on this
research. Main risks are secret leakage before logging, invented file/repo
state, non-idempotent durable writes, exact command/path loss, and summary
bloat over repeated compaction.

## Sources

1. **Direct measurement (tier 1):** `results/primary.jsonl`,
   `primary-scores.json`, `presave*.json*`, `recompact*.json*`, final
   `judge-claude.jsonl`, final `judge-codex.jsonl`, and `analysis.json`; exact
   scripts and fixtures in this directory.
2. **Local primary code (tier 2):** `app/session.py:1162-1364`, current prompt,
   full-context summary turn, reset/preamble flow, and live quota guard.
3. **Local primary design (tier 2):** Kesha
   `/mnt/data/Projects/Python/kesha-tg-bot/docs/tasks/14/research.md:397-575` and
   `plan.md:330-411`.
4. **Official primary:** Anthropic, “Effective context engineering for AI
   agents,” 2025-09-29 —
   https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
   (maximize compaction recall first, then remove redundant tool output;
   persistent notes support long-horizon work).
5. **Official primary:** Claude Platform compaction documentation —
   https://platform.claude.com/docs/en/build-with-claude/compaction (custom
   instructions replace defaults; pausing can preserve recent messages
   separately; multiple compactions replace older content with the latest
   compaction block).
6. **Official primary:** Claude Code context-window documentation —
   https://code.claude.com/docs/en/context-window (root CLAUDE.md reloads;
   path-scoped/nested instructions may be lost until matching files are read).
7. **Official primary:** Claude Code session documentation —
   https://code.claude.com/docs/en/sessions (`/compact` replaces history with a
   summary; `claude -p --output-format json` exposes structured run evidence).
