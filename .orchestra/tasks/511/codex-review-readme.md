<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

The diff contains several blocking factual and consistency issues. Markdown structure itself is valid.

## Findings

- blocking: README.md:103 — The 🚫 status says workers cannot spawn workers, but `spawn_worker` is exposed to agent sessions and passes `parent_name=WORKER_NAME`; `manager.py:656` explicitly gates agent-spawned workers. This is not “not built”; the code supports it.

- blocking: README.md:107 — This overstates enforcement. The frozen oracle is used only when an authoritative task oracle is marked required (`merge_operations.py:799-817`); otherwise merges can use no oracle or a legacy, non-frozen command. The mapped test gate is broader than the cited frozen-oracle path.

- blocking: README.md:111 — “4 ... CLI agents” contradicts the surviving Stack entry: the OpenRouter Harness is explicitly described as “in-process” at README.md:287. `runtime_registry.py:330` counts runtimes, not four CLI agents.

- blocking: README.md:122 — `app/transcription.py:72` supports Deepgram voice transcription only. It does not substantiate dashboard control, Telegram control, or image handling.

- blocking: README.md:124 — `app/routes/sessions.py:599` proves the server-side `no-store` header, not “both ends.” The client-side cache policy requires a separate client anchor.

- blocking: README.md:120 — The status legend defines 🚫 as “deliberately not built,” while the row says the vector implementation is still present and runs when enabled. This should not be labelled as not built without clarifying that only default use is deliberately disabled.

- blocking: README.md:145 — “a sub-agent is cheaper and better than anything we spawn” is an uncited superiority claim. The preceding duration measurements do not establish either cost or quality superiority.

## Verdict

Changes requested.

## Round (2026-09-03T12:22:29Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

Six prior findings are fixed. Finding 4 remains partially unresolved, and two new blocking issues were introduced.

## Findings

- suggestion: README.md:103 — FIXED finding 1. The status now correctly says this is prompt-enforced, not code-enforced.

- blocking: README.md:103 — NEW BUG. “A guaranteed merge conflict” is too strong: separate branches can merge cleanly when edits are disjoint.

- suggestion: README.md:107 — FIXED finding 2 substantively. The conditional oracle and universal mapped test gate are now described accurately.

- blocking: README.md:107 — NEW BUG. `app/merge_operations.py:1728` is only the import of `evaluate_test_gate`; the blocking logic is at lines 1737–1738, so the cited anchor does not support the claim.

- suggestion: README.md:111 — FIXED finding 3.

- suggestion: README.md:122 — STILL BROKEN finding 4. `app/tg_bridge.py` supports Telegram, but does not substantiate “Dashboard and Telegram control” as a combined claim.

- suggestion: README.md:124 — FIXED finding 5.

- suggestion: README.md:120 — FIXED finding 6.

- suggestion: README.md:145 — FIXED finding 7.

No Markdown table, pipe, or link errors found.

## Verdict

Changes requested. The remaining blocking issues are the inaccurate “guaranteed merge conflict” rationale and the incorrect acceptance-gate line anchor.

## Round 2

Read line: “Every worker gets its own git worktree — a full copy of the repo on its own branch.”
