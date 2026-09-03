<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Summary

NO-UPGRADE withstands adversarial review. Installed, live, npm `latest`, and GitHub stable all resolve to `0.149.0`; the release tag resolves to commit `758ef40`, so the stable delta is genuinely empty. The seven cited merged PR commits are ancestors of `rust-v0.149.0`. All cited issue states match the artifact.

All eight requested surfaces are covered, and the current Orchestra source supports the stated call-path classifications. Production arithmetic is consistent: mean CPU is 8.5%, and `1139.9 / 5 = 228.0 MiB/session`. No issue report is presented as maintainer-confirmed root cause.

## Findings

suggestion: [docs/tasks/377/research.md:133](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-codex-releases/docs/tasks/377/research.md:133) — The tagged app-server README supports preserving the thread ID, resuming it, appending subsequent turns, and reporting per-turn usage, but it does not explicitly promise that “persisted token usage” is restored during cold resume. Narrow this sentence or cite the precise upstream implementation/protocol field that establishes persistence of cumulative token usage. The resume conclusion itself remains supported by the documented [`thread/resume` contract](https://github.com/openai/codex/blob/rust-v0.149.0/codex-rs/app-server/README.md).

suggestion: [docs/tasks/377/research.md:181](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-codex-releases/docs/tasks/377/research.md:181) — “три согласующихся issue/experiments” slightly overstates the applicable evidence: the artifact itself correctly classifies #38269 as inapplicable because Orchestra does not send `additionalContext`. Describe the basis as two applicable fidelity reports plus one corroborating but currently inapplicable auto-compaction report. This does not change the open-risk or NO-UPGRADE conclusions. See [#37121](https://github.com/openai/codex/issues/37121), [#38269](https://github.com/openai/codex/issues/38269), and [#14589](https://github.com/openai/codex/issues/14589).

## Verdict

APPROVED with two non-blocking evidence-wording suggestions.

No newer stable target exists: npm `latest` and the [official GitHub latest release](https://github.com/openai/codex/releases/tag/rust-v0.149.0) remain `0.149.0`. The NO-UPGRADE verdict is not falsified.
