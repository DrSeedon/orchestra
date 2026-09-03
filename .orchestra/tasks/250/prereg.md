# #250 A/B preregistration

Frozen before any model invocation. The freeze commit and `freeze-manifest.sha256` bind the corpus, prompts, task fixtures, mutation definitions, runner, grader, order, and thresholds.

## Question and hypotheses

- Context: coding agents asked to add regression tests to small, correct Python components.
- Change under test: add the single instruction group in `candidate-prompt.md` to the common baseline.
- Baseline: `baseline-prompt.md` alone, with the same task text, model, effort/default runtime, repository, and command.
- Outcome: mechanical behavioral score and verification cost, not prose/style.

H1: the candidate group increases the number of tasks whose test catches the intended regression, accepts a valid alternate implementation, enters through the public path, and proves non-vacuity, without scope changes or whale behavior.

Falsifier for H1: candidate score does not exceed baseline, or any apparent gain requires a hanging/oversized test by the thresholds below.

H0/alternative: the task statements already contain enough incident detail, so the extra questions add test prose/tool calls without improving behavioral discrimination.

Falsifier for H0: candidate gains at least 3 criterion-points overall and wins on at least 2 tasks without triggering a whale threshold.

## Frozen tasks

Six fixtures are under `eval/fixtures/`. T01–T04 are reduced forms of rows in `corpus.md`; T05 ledger idempotency and T06 manifest parsing are distant-domain transfer cases.

Every subject edits only `tests/test_target.py`. Production files and task text are immutable. The hidden grader substitutes frozen valid alternatives and mutants after the subject finishes.

## Model and ordering

- Model: `gpt-5.6-luna`, one fresh ephemeral Codex CLI session per cell. These are eval subjects, not child researchers.
- Repetitions: one per task/arm (12 calls). This is a screening experiment, not a population reliability estimate.
- Order (frozen, paired and interleaved): T03 candidate→baseline; T01 baseline→candidate; T05 candidate→baseline; T04 baseline→candidate; T02 candidate→baseline; T06 baseline→candidate.
- The candidate differs from baseline by exactly one instruction group; task text is byte-identical within a pair.

## Frozen mechanical criteria (one point each per task)

1. Intended mutant caught: every variant tagged `target` exits non-zero for an assertion/behavior failure.
2. Valid alternate accepted: current implementation and every variant tagged `valid` exit zero with at least one passed test and no skips/xfails.
3. Production path exercised: the variant tagged `path` exits non-zero.
4. Non-vacuity/positive control: the variant tagged `positive_control` exits non-zero.
5. Scope integrity: only `tests/test_target.py` changed; production bytes, fixtures, config, and test selection are unchanged; no skip/xfail weakening.

Maximum: 30 points per arm. The grader does not read or score the six prose answers.

Expected outcomes for every variant, including decoys/compound fallback cases, are embedded in frozen `eval/grader.py` and printed by `--list-expectations`. A `valid`/decoy transformation is expected green even if its implementation differs; target/path/control mutations are expected red.

## Verification-whale guard

The candidate fails the experiment regardless of correctness score if any candidate cell:

- times out in a focused grader command at 10 seconds;
- writes more than 120 nonblank lines in `tests/test_target.py`;
- produces zero passing tests on the current implementation;
- changes anything outside `tests/test_target.py`; or
- has median tool calls greater than 2× baseline median while gaining fewer than 3 criterion-points overall.

Recorded but not directly scored: nonblank test LOC, test count, model tool calls from JSONL, model wall time, each grader command wall time, exit code, stdout, and stderr.

## Grader pilot before model calls

Before the 12 calls, `eval/grader.py --self-test` must demonstrate the complete path on frozen hand-written controls: a strong control gets all expected green/red outcomes; a vacuous control fails at least the target and positive-control criteria. A broken collection/import is not accepted as red.

## Limits

N=6 paired tasks and one sample per cell cannot establish universal reliability. The result may justify `LIKELY` for this runtime/corpus or `UNCERTAIN`; it cannot justify a blanket rule for every model, language, or repository.

