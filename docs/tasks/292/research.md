# #292 — change-capsule pilot: procedural REJECT

Date: 2026-08-16. Scope: approved pilot from #288. No OpenSpec package was
installed and no runtime, prompt, configuration, production DB, or production
file was changed.

## Question and preregistered estimand

Context: a provider-neutral Orchestra handoff crosses Claude/Codex/Grok
runtime boundaries while task/plan/test owners remain canonical.

Change under test: add one derived, `DERIVED — DO NOT EDIT` capsule containing
authoritative refs, 3–7 observable requirements, non-goals, and an exact AC.

Baseline: the current handoff brief without a capsule (A), compared with a
byte/position-matched deterministic padding control (P) and the semantic
capsule (B).

Outcome: intent recall, invented/contradictory facts, exact AC and next-action
correctness, pre-action read/tool calls, and input tokens. The preregistered
design planned 3 cases × 3 arms × 3 repetitions = 27 sequential agent runs,
then two blind scorers, control noise ranges, and fixed PASS/REJECT rules.

Hypotheses:

1. H2: B improves handoff retention over A and P. Falsifier: no gain beyond
   both controls/noise, or safety/overhead failure.
2. H3: B adds no value beyond the current handoff and formatting/length control.
   Falsifier: a preregistered, noise-clearing B improvement on at least 2/3
   cases.

## Frozen inputs

`prereg-lock.json` was created before the first model call. Its protocol SHA is
`454bf185cbcb2b29923ce92f07f585f884e8d95d99c822371a5978b35a678779`; it hashes
all seven protocol/runner/scorer/aggregation inputs. The selected cases and
baselines are in `protocol.json` and the exact capsules are in `capsules.md`.

The three capsules measured 795, 797, and 911 UTF-8 bytes (rough byte/4 upper
bounds 199, 200, and 228 tokens). The runner generated deterministic placebo
payloads with equal UTF-8 byte lengths and the same insertion position. The
planned target was Claude `claude-opus-5[1m]`, effort `high`, with Read/Glob/Grep
only and fresh no-persistence contexts.

Preflight created isolated seed repositories from each baseline and cloned each
with `git clone --no-local`. The named solution objects were unreachable in all
three sealed clones: #237, #241 (both named solution commits), and #248. This
was a positive object-reachability measurement, not a proof that no equivalent
solution text existed elsewhere; that limitation is retained below.

## Measured execution

The deterministic permutation made `t241/P/r1` the first cell. The exact command
was:

```text
claude -p --safe-mode --model claude-opus-5[1m] --effort high --permission-mode dontAsk --allowed-tools Read Glob Grep --no-session-persistence --output-format stream-json --json-schema <frozen SCHEMA>
```

The runner exited non-zero before recording a result:

```text
RuntimeError: stream-json contained no result event
```

Measured execution count: 0 completed runs, 1 aborted first cell, 26 planned
cells not started, 0 replacement runs, 0 scorer runs, and no runtime/config
mutation. The CLI response had no parseable result event, so exact provider
usage and turn count are **unavailable**, not zero. The runner raised before
writing raw stdout/stderr; `results/protocol-stop.json` records this omission
explicitly and does not invent a hash or usage value.

The frozen protocol treats a missing/aborted run as an immediate stop. I did not
retry, alter the permutation, fill the sample, change criteria, or start
scoring. Therefore there is no valid recall, noise floor, kappa, or causal
estimate.

## Independent review

The Codex review in `codex-review-pilot.md` agrees that the stop is procedurally
justified and the result is inconclusive. It also identifies protocol-audit
deficiencies that are not repaired post hoc: the lock does not materialize the
full permutation/prompt hashes, the two-blind-scorer procedure is not explicit
enough in `protocol.json`, named-object reachability is weaker than complete
solution-leakage exclusion, and the aborted raw stream was not persisted. These
are recorded findings, not reasons to continue or rewrite the frozen protocol.

## Verdict and limits

**REJECT — procedural stop / inconclusive pilot.** This rejects the attempted
pilot as unevaluable under its frozen execution contract. It does **not** reject
the capsule, H2, or H3, and it is not evidence that a capsule has or lacks causal
value. The only supported conclusion is that this run did not produce the
required dataset and must not be repaired by replacement runs.

Counter-evidence: preflight did establish case selection, baseline snapshots,
named solution-object non-reachability, equal capsule/placebo bytes, and a
frozen stop rule. Those controls support the procedural classification but do
not rescue the missing model result.

Sources / artifacts:

- [1] `docs/tasks/288/research.md`, §8 — approved 27-run A/P/B design and stop rules.
- [2] `docs/tasks/292/protocol.json` + `prereg-lock.json` — frozen protocol and hashes.
- [3] `docs/tasks/292/capsules.md` + `handoff_corpus.json` — derived interventions and handoff inputs.
- [4] `docs/tasks/292/evidence.json` + `results/protocol-stop.json` — machine-readable measurements.
- [5] `docs/tasks/292/codex-review-pilot.md` — independent adversarial review and verdict.
