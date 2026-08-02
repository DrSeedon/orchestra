# #106 Q6 — protocol (pre-gate stage)

This file currently governs the **pre-gate only**. The full confirmatory Q6
protocol is not written yet, because it requires newly authored fixtures that do
not exist at the time of writing.

## Pre-gate question

- **Context:** the Claude summary-only branch of Orchestra compaction.
- **Change under test:** three fixes made after Q5 —
  1. prompt rule forbidding unsupported *negative* file-action assertions,
  2. harness capture of live tool events into the ledger shown to judges,
  3. removal of the two internally contradictory fixtures.
- **Baseline:** the unchanged Orchestra `COMPACT_PROMPT` (`orchestra_current`).
- **Outcome:** whether the two Q5 failure mechanisms are gone.

This stage tests **mechanism, not effect size.** It deliberately reuses the Q5
corpus, which is legitimate here precisely because no gate, interval, or verdict
is computed from it.

## Scope limits, stated up front

- The pre-gate produces **no verdict** and moves **no locked gate**.
- Its fixtures were already used for candidate selection, so it cannot and does
  not estimate any effect size.
- G7 remains **UNDECIDED** — the Codex judge is unavailable until 2026-08-08.
  Not closed single-handed.
- G5 remains **absolute**. Not softened.

## Design

3 fixtures x 2 variants x 3 repetitions = **18 outputs**, seed `10620260821`.

| Fixture | What it probes |
|---|---|
| `q6-confirm-reversal-canary` | did the prompt fix remove unsupported negatives? |
| `q6-confirm-targeted-promotion` | do live tool events reach the judge on a read+write path? |
| `q6-confirm-tool-gap-archive` | does the unmatched-tool GAP marker still fire? |

Judging: 3 blinded Claude batches, seed `10620260822`.

## Pass condition — fixed before the run, not to be relaxed

1. **Zero** false unchanged-file-action flags against the candidate across all 18
   outputs.
2. Non-empty live tool ledger on every output where the model actually used a
   tool (`num_turns > 1`).
3. GAP marker still present for the unmatched tool event in
   `q6-confirm-tool-gap-archive`.

Anything else means the defect is deeper than diagnosed and the full Q6 must not
be funded yet.

## Cost

18 x $0.1176 + 3 x $0.1733 = **$2.64** at measured Q5 unit rates. This is
additional to the $21.77 already spent on Q5, and separate from the $30 ceiling
approved for the full Q6.
