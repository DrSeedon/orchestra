# #106 Q6 — pre-run cost estimate (variant B)

Unit costs are **measured Q5 actuals**, not planning guesses.

| Unit | Measured cost | n |
|---|---|---|
| generation / output | $0.1176 | 132 |
| judge batch | $0.1733 | 22 |
| presave unit | $0.1245 | 6 |
| recompact chain | $0.3845 | 4 |

## Q6 projection (same design as Q5)

| Stage | Cost |
|---|---|
| pilot, 3 outputs | $0.35 |
| primary, 132 outputs | $15.52 |
| presave, 6 units | $0.75 |
| recompact, 4 chains | $1.54 |
| judge Claude, 22 batches | $3.81 |
| **Claude-pool subtotal** | **$21.97** |
| with +20% variance buffer | **$26.36** |
| judge Codex, 22 batches | $3.81 — separate Codex pool, $0 against this ceiling |

## The budget answer

**A new round does NOT fit in the $10.23 left from the $32 Q5 ceiling.**
Q6 needs a **fresh ceiling of ~$26.36** (Claude pool), or ~$30 to also cover the
Codex judge if you want it counted in one number.

Q5's own spend was $21.77 against $32, so this projection is consistent with
observed behaviour rather than optimistic.

## Cheaper option, if the ceiling is the constraint

The 132-output primary is 71% of the cost. The diagnosis in
`q5/g5-defect-diagnosis.md` shows the real candidate defect is narrow
(unsupported *negative* file-action assertions). A **targeted 3-fixture
confirmation** of just that defect costs roughly:

- 2 variants x 3 fixtures x 3 reps = 18 outputs = **$2.12**
- 3 judge batches = **$0.52**
- total **≈ $2.64**

That does not produce a preregistered verdict — it only proves the prompt fix
removes the unsupported-negative flags before you commit ~$26 to a full
confirmatory round. Recommended as a gate before Q6.

## Blocking issue for Q6 design

Per `q5/g5-defect-diagnosis.md`, 3 of the 5 G5 flags were **false positives**:
the model genuinely performed the fixture's assigned Read, but live tool calls
are never written into the judge's ledger, so a true action is unprovable.

Repeating Q5's design without fixing that will reproduce the same G5 FAIL
regardless of any prompt change. Q6 must either record live tool calls into the
ledger shown to judges, or drop the self-contradictory fixture
(`q5-confirm-file-unchanged-no-read` forbids claiming a read while assigning a
read as its pending action).
