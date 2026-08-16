# #289 — preregistration: Luna vs Sol blind review pilot

Frozen before any A/B model call on 2026-08-16. Phase 1 research only.

## Question and hypotheses

- **Context:** review of compact Sol-authored/shared-runtime work in Orchestra.
- **Change under test:** use one fresh `gpt-5.6-luna` review instead of one fresh
  `gpt-5.6-sol` review.
- **Baseline:** identical frozen corpus, prompt, order, tool scope, and `high`
  reasoning effort; only the model changes.
- **Outcome:** recall of precommitted crash/corruption/security/availability
  blockers and blocking false positives on clean controls.

H1: Luna is operationally no worse for default review because it detects every
precommitted blocker Sol detects without more blocking false positives. H1 is
falsified if Sol detects a precommitted blocker Luna misses, or Luna blocks a
clean control that Sol passes without identifying a demonstrable blocker.

H2: Both same-family reviewers can share a blind spot. H2 remains live if both
miss the same precommitted blocker; agreement is not treated as proof of safety.

## Frozen corpus and minimum N

`ab_workspace/frozen_corpus.md` contains four independent cases in fixed order:
two blocker-bearing historical mechanisms and two clean controls. N=4 is the
smallest useful operational falsifier here: one defect could expose a fatal
miss, but two reduce dependence on one mechanism; two clean controls make a
blocking false-positive observable. This pilot is not powered to establish
statistical equivalence and cannot prove Luna generally non-inferior.

The hidden canonical ground truth is committed by SHA-256:

`f728c37b19a26d33f4e48b8d124fe7d896170fca67f479ba7ff3b455599a06eb`

The commitment is over canonical JSON (`sort_keys=True`, separators `(',',
':')`, UTF-8) concatenated with a 128-bit nonce. Ground truth and nonce are
revealed only after both model outputs are frozen.

## Execution contract

- One fresh, ephemeral call per model; no resume and no retry.
- `--ignore-user-config --ignore-rules`, no MCP, current directory restricted to
  `ab_workspace`, exact same `review_prompt.txt`, sandbox and `high` effort.
- Raw JSONL is temporary and never committed or printed. Permanent evidence is
  the final response, usage totals, file-access aggregate, hashes, timestamps,
  and exit status.
- A response counts only if it includes all four case headings, a final verdict,
  and an exact corpus line. Otherwise that arm is unresolved.
- Grade blind by case ID before revealing the ground truth. A blocker counts as
  a hit only when its causal mechanism and observable consequence match the
  precommitted mechanism. Finding count by itself is not quality.

## Decision rule

- **Luna clearly worse:** Sol-only hit on either precommitted blocker, or a
  Luna-only blocking false positive on a clean control.
- **No observed difference in this pilot:** equal blocker recall and equal
  blocking false-positive count. This does not prove equivalence; high-risk
  shared runtime/security remains outside the evidence for a Luna default.
- **Both miss:** evidence for a common-family blind spot; cross-pool review gains
  priority on that risk class.
- Suggestions are reported as value but never substitute for blocker recall.

## Budget and stop rule

Before and after the pair, take WAL-safe snapshots of the live DB and record the
Codex main-provider integer utilization plus every foreign Codex turn in the
interval. Maximum provider delta is 1 percentage point. If the counter is stale,
crosses a reset, rises by more than 1 point, or foreign/background work makes the
pair non-decomposable, stop and mark the A/B unresolved. Do not add turns to fill
cells. Spark/Fast are excluded.

## Mechanical freeze

The freeze commit records this preregistration, corpus, and prompt. SHA-256 file
hashes are recorded immediately after the commit and must match at grading.

- `frozen_corpus.md`: `5ab469c76089dc124e849223b904eea449b36a8308e1e07621b4f863af43bf5d`
- `review_prompt.txt`: `4cd1ea1d3485ee351a34559768ab94c944960ce180ce631ae374191e654d3222`
