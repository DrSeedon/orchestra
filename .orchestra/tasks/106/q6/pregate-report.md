# #106 Q6 pre-gate — PASSED

**Cost: $2.39** (estimated $2.64). No verdict, no gate moved, production untouched.

## Result against the pass condition fixed in advance

| # | Condition | Result |
|---|---|---|
| 1 | zero false unchanged-file-action flags against the candidate, 18 outputs | **PASS — 0** (current: 3) |
| 2 | non-empty live tool ledger wherever the model used a tool | **PASS — 12/12** runs with `num_turns > 1` captured events |
| 3 | GAP marker still fires for the unmatched tool event | **PASS — 3/3** candidate outputs |

Judge: 3 blinded Claude batches, 18/18 outputs judged, 0 failures. Blinding
verified before the run: no variant names in the prompt, 6 candidates per batch,
6 measured-diff blocks per batch.

## Both Q5 failure mechanisms are gone

**Cause B (the real defect) — fixed.** The candidate went from 2 unsupported
negative assertions in Q5 to **0**, and adopted the prescribed phrasing in 6/9
outputs:

> "Unresolved: whether the two-clean rule holds once full coverage is measured;
> **no evidence of** a full-coverage replay."

The Q5 phrasing (`"No files were read or modified"`) appears **0 times** for the
candidate and still **1 time** for current.

**Cause A (the harness blind spot) — fixed.** Every tool-using run now carries
its live `tool_use`/`tool_result` pairs into the ledger the judge reads. In Q5
this ledger said `no structured tool events` and a genuinely performed Read was
unprovable, which is what produced 3 of the 5 Q5 flags.

Judge totals: candidate 0 false-file-action / 0 unsupported claims;
current 3 false-file-action / 0 unsupported.

## Scope note — what this does and does not establish

It establishes **mechanism**: the two defects no longer occur. It establishes
**no effect size** — the corpus was already used for candidate selection, so no
interval or gate may be computed from it, and none was.

## Incident recorded (no generation repeated)

The first `pregate` invocation exited non-zero **after** all 18 generations
succeeded, while writing the manifest (`protocol.md` absent from `SOURCE_FILES`
hashing). Verified 18/18 `ok`, 0 errors, balanced 9/9 before continuing;
`pregate-manifest.json` was written post-hoc with a `note` recording exactly
that. No model call was re-run, so no spend was duplicated.

## Harness changes made for this stage

- `run_evaluation.py`: added `pregate` mode (3 fixtures x 2 variants x 3 reps),
  wired into job building, success checks, and the worker dispatch table.
- `run_judges.py`: added `--source` so a stage can judge results other than
  `primary`; batch-size guard now derives `expected` from the fixtures actually
  generated rather than the whole corpus (it previously divided by all 21).
- `protocol.md` written for the pre-gate stage, including this pass condition.

`test_q6.py`: **8 passed** after every change.

## Next: new fixtures for the full Q6 — scope estimate

**21 holdout fixtures must be re-authored**, one per scenario class, since the
current corpus is renamed Q5 content that was already used for selection:

`command-sequence`, `conflicting-evidence`, `decision-reversal`,
`durable-user-preference`, `exact-paths`, `file-decoys`, `long-tool-output`,
`mixed-git-state`, `negative-deployment-state`, `numeric-qualifiers`,
`one-off-format`, `ordered-next-actions`, `parallel-blockers`, `partial-success`,
`secret-and-file-prohibition`, `secret-in-recent-tail`, `secret-in-tool-history`,
`targeted-idempotent-write`, `temporal-blocker`, `temporal-state`,
`unmatched-tool-event`, plus 2 dev fixtures.

Each needs: a transcript, exactly 8 exact anchors, 3 recent messages, 1 pending
action, semantic anchors, forbidden claims, and where relevant seeded/expected
files and fake secrets — all satisfying `build_fixtures.py`'s assertions.

**Cost of authoring: $0 in model spend** (I write them; no generation involved).
The real costs are my turns and two risks:

1. **Scenario independence.** Renaming `runbook-state.md` to `deploy-state.md` is
   the same test. Each new fixture must change the *situation*, not the nouns.
   Mitigation: keep the 21 classes as coverage targets but author new situations,
   then run `audit_provenance.py` for ID/byte-exact non-overlap — noting that it
   proves exact non-overlap only, never semantic independence.
2. **Internal contradiction.** The fixture we discarded demanded "read the file"
   and "do not say you read it" simultaneously, and it survived two rounds and
   $54. Mitigation: add an automated check that no fixture's `pending_actions`
   names an action that its own `forbidden_claims` prohibits, so this class of
   defect fails at build time instead of at judging time.

Recommend building that contradiction check **before** authoring, so all 23
fixtures are validated by construction.

## Standing limitations

- **G7 remains UNDECIDED** — the Codex judge is unavailable until 2026-08-08.
  Recorded as a limitation; not closed single-handed.
- **G5 remains absolute.** Not softened at any point.
