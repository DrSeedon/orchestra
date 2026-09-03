The new research artifact contains several source-verifiable inaccuracies, including loss of the original Claude-only scope and overstated guarantees in Cline and Ouroboros. These should be corrected before its architectural recommendations are used.

Full review comments:

- [P2] Keep the comparison scoped to Claude handoff — /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-compact-prompt/docs/tasks/106/external-landscape.md:422-422
  For Codex/Sol sessions, `AgentSession.compact()` returns through `_compact_codex_context()` before `COMPACT_PROMPT` is used, and native Codex compaction reinserts raw user messages. Therefore “summary-only compact handoff” is false for the current Codex worker fleet and turns a Claude-only prompt problem into an Orchestra-wide architecture gap; scope this row to Claude or split the backends.

- [P2] Qualify Cline's latest-user invariant — /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-compact-prompt/docs/tasks/106/external-landscape.md:187-187
  In a Cline transcript containing one initial user task followed by a long tool loop, `findLastTurnStartIndex()` returns 0 and `findCutIndex()` intentionally uses the token-budget candidate, so the latest and only typed prompt is folded into the summary. The pinned source explicitly documents and tests this exception, making the absolute “never” claim inaccurate; restrict it to later typed turns.

- [P2] Stop calling the project workpad bounded — /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-compact-prompt/docs/tasks/106/external-landscape.md:373-373
  For project-scoped Ouroboros tasks with a large workpad, `build_knowledge_sections()` bounds only `journal_tail_digest()`; it reads `project_workpad_path()` and injects the entire workpad, explicitly refusing prefix slicing. Calling the combined journal/workpad bounded understates the prompt-footprint risk used later in the comparison; distinguish the bounded journal tail from the full workpad.

- [P3] Account for consolidation exceeding the scratchpad cap — /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-compact-prompt/docs/tasks/106/external-landscape.md:375-375
  When scratchpad appends occur during the slow `_consolidate_scratchpad_blocks()` LLM call, `_merge_survivors()` can re-read ten live blocks after the old snapshot blocks were evicted, then prepend the compressed block without reapplying the cap, persisting eleven blocks. Thus “at most ten” is not guaranteed under the concurrent behavior credited here; qualify the cap or record the upstream defect.

## Author resolution after round 1

All four findings were verified directly against the cited code and accepted:

1. The research and HTML now scope the measured prompt defect and proposed raw-tail repair to Orchestra's Claude backend. The Codex native compact path is explicitly separated.
2. The Cline claim now preserves its index-0/long-tool-loop exception in both artifacts.
3. Ouroboros now distinguishes a bounded project journal tail from the fully injected workpad.
4. The nominal ten-block scratchpad cap is qualified with the verified concurrent-consolidation path that can leave eleven blocks.

No production file was changed.

## Round (2026-08-01T09:09:02Z)

😏 The absolutes have finally learned to use qualifiers.

## Re-review status

- **FIXED — Claude vs Codex scope.** Claude is explicitly summary-only; Codex is separately described as native compaction with raw-user reinsertion. [external-landscape.md:436](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-compact-prompt/docs/tasks/106/external-landscape.md:436)
- **FIXED — Cline index-0 exception.** Both artifacts state that a lone initial prompt followed by a long tool loop may enter the summary. [external-landscape.md:202](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-compact-prompt/docs/tasks/106/external-landscape.md:202)
- **FIXED — Ouroboros workpad bounds.** The journal tail is bounded; the workpad is injected in full. [external-landscape.md:384](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-compact-prompt/docs/tasks/106/external-landscape.md:384)
- **FIXED — scratchpad cap.** Ten blocks is presented as the normal target, with the concurrent eleven-block case explicitly documented. [external-landscape.md:387](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-compact-prompt/docs/tasks/106/external-landscape.md:387)

## New findings

None. The HTML presentation matches all four qualifications.

## Verdict

**PASS — Confidence: 0.99.** No new contradiction introduced. Four absolutes went in; four properly scoped claims came out.
