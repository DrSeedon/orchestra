## Summary

🧮 The arithmetic, heroically, is not the problem.

1. `_codex_item_id` reliably identifies Codex calls when present. However, the source adds it conditionally, so “no marker = Claude” needs one extra documented invariant.
2. All stated counts, rates, duration statistics, worker totals, and burst measurements recompute exactly from the supplied snapshot.
3. The `62 + 3 + 9 = 74` classification strongly supports external-state waiting as the mechanism and `codex_review` as the dominant trigger. It supports—but does not experimentally prove—the exact wording as the sole cause.
4. The proposed order is justified: fix the highest-leverage wording, cover every role through the shared prompt, remove the merge race, then consider a narrowly targeted hook based on telemetry.
5. No blocking factual, methodological, or safety error was found.

I recomputed the aggregate DB measurements. Per the bounded scope, I did not independently reclassify all 74 surrounding histories; I audited the classification method and the cited representative sequences.

## Findings (Conventional Comments)

[suggestion] **Qualify the marker-negative backend label** — [research.md:61](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-codex-sleep/docs/tasks/codex-sleep/research.md:61)

`CodexBackend._tool_use()` adds `_codex_item_id` only when `item_id` is truthy and the payload is a dictionary. Therefore marker presence is conclusive Codex provenance, but the cited code alone does not prove every unmarked call is Claude. State the nonempty-item-ID invariant or label the groups “Codex-marked” and “unmarked/Claude-shaped.” This does not invalidate the observed result: every sleep is in the positively identified Codex group.

[suggestion] **Calibrate the causal confidence** — [research.md:133](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-codex-sleep/docs/tasks/codex-sleep/research.md:133)

The timing, wording, prompt gap, sub-60-second durations, lifecycle implementation, and Claude comparison strongly support an instruction mismatch. They do not isolate “just wait” from Sol’s general external-state behavior through a controlled intervention. Describe the cause as “strongly supported” until post-change telemetry confirms the effect; the recommendation already supplies that test.

[question] **Preserve the 74-call annotation evidence** — [research.md:113](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-codex-sleep/docs/tasks/codex-sleep/research.md:113)

The `62/3/9` classification is internally complete and representative sequences agree with it, but the document provides no annotation table or reproducible classification query. Retaining `log_id → class` would make this load-bearing measurement independently auditable without rereading session histories.

## Verdict

**Approved with non-blocking qualifications.** The aggregate measurements are correct, the root-cause theory is well supported, and the remediation order is proportionate for an MVP. No blocking error exists.

Fixing “just wait” before deploying a command guard is sensible—change the sign telling agents to loiter before hiring security to confiscate their chairs. 🪑
