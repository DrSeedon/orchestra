<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

Nothing says “pending research” like a verdict that already picked the winners 🙃

## Summary

The artifact covers most requested areas and explicitly blocks migration of 20,502 records until a local ≥10-question comparison. However, several high-consequence conclusions are under-gated: project isolation and full prompt delivery lack validation, the vector deletion criterion is undefined, and the `knowledge` tool comparison is not semantically equivalent.

## Findings

### blocking: Cross-project isolation has no acceptance test

**File:** [research.md:141](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-agent-memory/docs/tasks/417/research.md:141)

The document declares project isolation and restricted cross-project reads, but §11 never tests denied cross-project access, scope resolution, or per-project tool visibility. Add explicit positive and negative isolation cases before any shared prompt or projection rollout; otherwise a retrieval mistake can become cross-project data exposure.

### blocking: “All agents” delivery is evidenced only for the default pipeline

**File:** [research.md:106](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-agent-memory/docs/tasks/417/research.md:106)

The evidence covers four roles through `pipeline.yaml`, but does not enumerate project-specific prompts, overrides, or every active consumer. “Fresh and resumed agents of all roles” is not enough to substantiate “all projects”; the delivery check must cover the complete project/role matrix.

### blocking: Vector deletion has no falsifiable pass/fail rule

**File:** [research.md:263](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-agent-memory/docs/tasks/417/research.md:263)

“Unique,” “useful,” and “reproducible” wins are undefined, and no independent correctness oracle, threshold, or reproducibility rule is given. Therefore the same A/B output could justify either deletion or retention of the 808-MB projection. Define the scoring oracle and decision thresholds before presenting deletion as an available gate.

### blocking: The `knowledge` no-tool comparison is not equivalent

**File:** [research.md:232](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-agent-memory/docs/tasks/417/research.md:232)

The fallback uses raw `rg` over `docs/kb` and `docs/tasks`, while `knowledge` is described as accessing projection-backed and typed state. The document provides no task comparison showing that both paths answer the same questions; the 39 calls measure adoption, not utility. Add the current `knowledge` path as a control arm or narrow the removal claim to its opaque mutation interface.

### suggestion: A-MEM, Graphiti, and Mem0 evidence is over-generalized

**File:** [research.md:193](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-agent-memory/docs/tasks/417/research.md:193)

A-MEM’s in-place metadata update supports caution, but the Graphiti incident is not shown to have the same mechanism, and current Mem0 documentation is vendor-reported design guidance rather than independent safety evidence. The derived-only boundary is a reasonable risk policy, but “REFUTED,” “CONFIRMED,” and “independently corroborated” should be softened unless the causal mapping is demonstrated.

### suggestion: The link census excludes README and nested Markdown

**File:** [research.md:83](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-agent-memory/docs/tasks/417/research.md:83)

`root.glob('*.md')` excludes the README and any nested files, even though README is explicitly the hot topic map. Thus “2 links across 22 topics” is only a top-level lower bound, not a corpus-wide graph measurement. Either recurse/include README or scope the conclusion accordingly.

### suggestion: File-first error cost understates canonical corruption

**File:** [research.md:328](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-agent-memory/docs/tasks/417/research.md:328)

Manual append can commit a false or stale canonical claim; Git preserves auditability but does not prevent agents from reading the bad current state. The A branch’s error model should include false promotion, stale claims, and required review/validation assumptions.

### question: Are the top-level conclusions recommendations or decisions?

**File:** [research.md:275](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-agent-memory/docs/tasks/417/research.md:275)

The text says generic `knowledge` “should be removed” and that the 808-MB projection should not remain a target, while the alternatives are supposedly user-selectable and A/B-dependent. Clarify these as conditional recommendations requiring explicit user choice, not a hidden final architecture decision.

## Verdict

**Needs work.** The migration guard and broad research coverage are present, but the missing isolation/delivery checks and undefined destructive A/B gate block a safe architectural conclusion.

The artifact explicitly lists: “- Как сериализовать fact anchors так, чтобы human edits и line movement не ломали identity.”

Otherwise this is an A/B gate wearing a verdict badge before anyone defined what “win” means.

## Round (2026-08-30T06:14:04Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

Final round, and one conditional tool decision is still sneaking through an “unselected” branch 🙃

## Summary

All eight prior findings are fixed in the prose. One new blocking contradiction remains: Alternative A still unconditionally removes `knowledge`, despite the control-arm rule allowing its read semantics to remain if it wins A/B.

## Findings

### Prior findings

- **FIXED** — Isolation controls: positive and negative cases are now specified in [research.md:340](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-agent-memory/docs/tasks/417/research.md:340). Run-only, not yet measured.
- **FIXED** — Full project/pipeline/role prompt matrix and resumed-session checks in [research.md:305](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-agent-memory/docs/tasks/417/research.md:305). Run-only.
- **FIXED** — Vector gate now has `n=30`, per-row scoring, and explicit delete/keep/inconclusive rules in [research.md:271](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-agent-memory/docs/tasks/417/research.md:271).
- **FIXED** — Raw `rg` is explicitly not equivalent to `knowledge`; current `knowledge` remains a control arm in [research.md:238](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-agent-memory/docs/tasks/417/research.md:238).
- **FIXED** — A-MEM, Graphiti, and Mem0 evidence is now causally and epistemically scoped in [research.md:197](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-agent-memory/docs/tasks/417/research.md:197).
- **FIXED** — Link counts are explicitly a top-level lower bound in [research.md:104](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-agent-memory/docs/tasks/417/research.md:104).
- **FIXED** — File-first error cost includes false/stale canonical promotion in [research.md:363](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-agent-memory/docs/tasks/417/research.md:363).
- **FIXED** — Alternatives are explicitly unselected and user-dependent in [research.md:350](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-agent-memory/docs/tasks/417/research.md:350).

### New findings

**blocking:** [research.md:238](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-agent-memory/docs/tasks/417/research.md:238) vs [research.md:356](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-agent-memory/docs/tasks/417/research.md:356) — Alternative A still says `knowledge` leaves the prompt/tool surface unconditionally, but the gate says its read semantics must be retained if the control arm wins. Selecting A after a `knowledge` win would violate the document’s own decision rule and remove a proven retrieval path. Make Alternative A conditional on the control-arm result.

## Verdict

**Needs work.** The prior findings are addressed, but the Alternative A contradiction must be resolved before this prose is internally consistent.

“prompt от него не зависит, corpus расширяется. Порог задан до запуска: один случайный rescue не покупает постоянный 808-МБ/operations layer.”

Иначе A/B превращается в дегустацию, где победившее блюдо всё равно убирают из меню.

## Author resolution after prose ceiling

- Accepted the only round-2 blocker. `research.md` Alternative A now makes the read-path outcome
  conditional: a losing `knowledge(query)` path leaves the prompt/tool surface; a winning path
  keeps its read semantics under a narrow explicit query contract. The opaque mutation interface
  remains outside Alternative A.
- No third review was run: the prose ceiling is two rounds. The last reviewer verdict remains
  `Needs work`; this note records the post-verdict fix and does not relabel it `APPROVED`.
