The new Luna route overlaps with the existing Opus default, leaving two valid choices for closed implementation work. The effort rule also presents a single measured outcome as a general closed-task result.

Full review comments:

- [P2] Make Luna override the Opus default for closed tasks — /home/kesha/orchestra/worktrees/home-kesha-orchestra/prompt-engineer/pipelines/default/prompts/base.md:83-83
  A closed implementation or fix now matches both the unchanged `Opus 5 — DEFAULT worker: implementation, fixes...` rule and this Luna rule, while the quota preamble explicitly permits routing work suitable for either model to either pool. Therefore an agent can legitimately choose Opus instead of the intended Luna default; state explicitly that closed tasks take Luna over Opus before applying the Spark exception.

- [P2] Limit the xhigh claim to the measured Sol T1 case — /home/kesha/orchestra/worktrees/home-kesha-orchestra/prompt-engineer/pipelines/default/prompts/base.md:84-84
  The blanket claim that xhigh costs `×2.04` on “a closed task” over-generalizes one Sol T1 run: the other measured closed task was only ×1.13, and neither role selection nor Luna at xhigh was tested. This unsupported generalization drives the absolute `never to full-cycle` prescription, so narrow the statement to the observed Sol T1 result or omit the numeric justification.

- [P3] Remove benchmark details that do not affect routing — /home/kesha/orchestra/worktrees/home-kesha-orchestra/prompt-engineer/pipelines/default/prompts/base.md:83-83
  The Luna sentence beginning `Measured on 3...` and the numeric parentheticals `9/9 at 164K` and `vendor MRCR: ...` do not change any model choice: the surrounding CLOSED-task, extraction-only, and no-reference-resolution prescriptions already determine the route. Deleting those clauses preserves behavior while avoiding repeated prompt cost on every agent spawn.

## Round (2026-08-12T03:11:27Z)

Re-review status:

- P2 Opus/Luna fork: FIXED.
- P2 xhigh over-generalisation: FIXED.
- P3 benchmark detail: FIXED; no remaining actionable cut.

New finding:

- [suggestion] Closed empirical benchmarks and closed bulk/mechanical work still match both Luna and Sol. Luna says: “**Luna** … — CLOSED task,” while Sol says: “also empirical measurements/benchmarks and long mechanical protocols or bulk edits where exact tool execution matters.” Because “also” is not limited to open tasks, either bullet can legitimately win. Specify that these Sol overrides apply even when closed, or that closed variants remain on Luna.

Verdict:

1. No remaining sentence clearly claims more than the measurement supports. The scoped wording—“Measured on 3 closed single-turn tasks (N=1 per cell)” and “on the two closed tasks measured, xhigh cost ×2.04 and ×1.13 without changing the verdict”—states the measured boundaries.

2. Yes. A closed empirical benchmark or closed long mechanical/bulk-edit task still has two valid routes: Luna’s “CLOSED task” rule and Sol’s “also empirical measurements/benchmarks and long mechanical protocols or bulk edits” rule.
