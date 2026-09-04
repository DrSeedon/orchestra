<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

The oracle was not entirely tuned away, but two assertions still lost coverage. 🧪

## Round 1

## Summary

Class A is genuinely independent for a foreign receipt snapshot: it recomputes from Git and does not reuse stored receipt digests. The malformed-oracle test safely omits the receipt because the metadata error is raised before coverage refusal is applied. No alternate database write is visible; calls occur after `DB_PATH` is patched to `tmp_path`.

## Findings

- `suggestion: tests/test_merge_target_oracle_386.py:935-937` — Excluding the entire `progress` object makes replay comparison blind to regressions in its stable schema, including a missing or malformed `elapsed_seconds`; only the wall-clock value is volatile. Assert the expected progress shape/stage separately, or exclude only the volatile field.

- `suggestion: tests/test_merge_target_oracle_386.py:1672` — `receipt_id` is compared with `result[...]` itself, so an empty or incorrect ID passes. Capture the helper’s generated receipt ID and pin it, or at least assert it is non-empty.

## Verdict

**ACK — no blocking findings.**

The shared `production_snapshot` expectation is not generally vacuous: required status and non-digest fields remain pinned. However, the receipt ID is a real self-comparison gap.

Verbatim changed line:

> `assert replay["progress"]["stage"], "живой прогресс операции пропал из ответа"`

Per the final “Do not edit files” instruction, I did not modify the output journal. The receipt currently checks its own ID like a guest list completed by the guest. 🪪
