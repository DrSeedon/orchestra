<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

Research is strong and reaches a defensible “do not proceed” recommendation. GitHub rows include pinned file links and commit dates, quota absence is well supported, and the Terms blocker is accurately identified.

Two load-bearing claims overreach their evidence: full technical compatibility is not established, and MCP recovery behavior is not proven for `agy` 1.1.25 on the relevant local-stdio path.

## Findings

### blocking

- blocking: `docs/tasks/506/research.md:71-74, 335-337` — `H1 CONFIRMED` and “Технически встроить `agy` можно” overstate the evidence while the contract table marks mid-turn injection unsupported, context/compact as a gap, subagents partial, interrupt/hibernation only likely, and omits an explicit retarget/liveness/disconnect mapping → downgrade the conclusion to “one-shot adapter is technically demonstrated; full BackendLike/runtime compatibility remains conditional on unresolved capabilities.”

- blocking: `docs/tasks/506/research.md:185-192, 368` — issue #623 does not establish current 1.1.25 behavior: the issue reports Antigravity `2.3.0` and a remote HTTP server behind `mcp-remote`, not 1.1.25 with Orchestra’s local stdio server; issue #657 is also a platform-/scenario-specific report. Both issues are currently open, but that only establishes an unresolved report, not a 1.1.25 regression. citeturn1view0turn1view1 → state this as historical/adjacent risk and mark current child recovery as unverified until a 1.1.25 local-stdio crash canary is run.

### suggestion

- suggestion: `docs/tasks/506/research.md:78-101` — the table does not map every named runtime capability to an agy result: `retarget`, process liveness, `disconnect`, and the exact `events.py` classification (`stream`, tool events, terminal `turn_end`, status/error) are missing or only described narratively → add explicit rows and mark each `CONFIRMED`, `GAP`, `PARTIAL`, or `UNTESTED`.

- suggestion: `docs/tasks/506/research.md:129-143` — the table correctly supplies commit dates and flags several stale adapters, but “Активный, current” is not established by recency alone, especially for commits predating the checked 1.1.25 release → reserve “current evidence” for rows whose pinned code demonstrably uses the 1.1.25-compatible interface; otherwise call them recent structured-wrapper evidence.

- suggestion: `docs/tasks/506/research.md:262-264` — the claim that repository fragments and MCP arguments/results “могут стать частью Interactions” is a reasonable inference, but the cited Terms establish broad data processing rather than proving which exact transcript fields are retained or sent in every path → label this paragraph explicitly as an inference and distinguish model transcript data from local MCP execution/state.

## Verdict

**Needs work before acceptance.** The overall no-go recommendation is sound, but the technical and MCP conclusions must be narrowed to match the evidence.

Independent Luna review was not run because `codex_review` would write a review artifact, conflicting with the explicit “Do not edit files” instruction.

Required exact quote from the artifact: “Достаточно одного из двух policy conditions:”.

## Round (2026-09-03T03:28:01Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Round 2

**Re-review status:** `git diff -- docs/tasks/506/research.md` is empty, so no uncommitted diff was available. I reviewed the current file contents directly; the stated fixes are present.

## Prior findings

- **FIXED** — Technical compatibility is now correctly narrowed: “One-shot adapter поверх `agy` технически доказан”, while full lifecycle is `PARTIAL / UNVERIFIED` (lines 54, 71–74, 363–364).
- **FIXED** — MCP recovery is explicitly unverified for 1.1.25 local stdio; #623/#657 are identified as adjacent historical scenarios (lines 59–62, 183–192, 368).
- **FIXED** — Contract coverage now explicitly includes disconnect, liveness, retarget, event mappings, terminal/status/error, and usage (lines 84–101).
- **FIXED** — GitHub entries now distinguish recent wrapper evidence from 1.1.25 canaries, while retaining pinned file links and commit dates (lines 123–138).
- **FIXED** — Data-transfer claims are explicitly marked as inference and distinguish transcript data from local MCP state (lines 255–264).

## New findings

None. No new blocking or suggestion-level findings identified.

## Verdict

**APPROVED for Phase 1 research review.** The document now gives an honest conditional technical assessment, preserves the Terms blocker, states quota uncertainty, and lists the missing live gates without authorizing implementation.

Exact revised sentence: “Полноценный production runtime пока условен;”
