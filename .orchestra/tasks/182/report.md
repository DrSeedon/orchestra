# Task #182 — Codex review execution guard

## Regression

The #179 guard searched the complete Codex JSONL stream and the final response for
`bwrap`, `RTM_NEWADDR`, and related failure phrases. A successful reviewer can read
those strings from the artifact through a `command_execution` event, so repository
content was misclassified as the reviewer's own admission of failure.

The durable artifact is finalized before execution-failure classification. A failed
classification now returns exit 70 after appending a diagnostic note, preserving the
review for inspection.

## Fix

`app/mcp_stdio.py` now parses each JSONL row and tests only `agent_message.text`.
Tool results and command output remain evidence the reviewer read, but cannot trip the
guard themselves. The finalizer runs before the guard; a real failure keeps the review
and receives an explicit `Execution guard failed` annotation.

## Verification

- `uv run pytest -q tests/test_codex_review_sandbox.py tests/test_mcp_codex_review.py`
  — 14 passed.
- False-positive mutation widened matching back to whole tool-result events. The
  dedicated command-output test failed with exit 70.
- True-failure mutation stopped classifying assistant messages. The dedicated blind
  verdict test failed because the generated command returned 0 instead of 70.
- Scalar-event mutation removed the dictionary guard. The scalar JSONL test failed on
  `AttributeError` before reaching the genuine failure event.
- Resume-UUID mutation removed shell quoting. The regression test observed command
  substitution and failed because the value no longer remained one argv element.

## Live acceptance

The patched wrapper was imported in a fresh Python process and used to run a real Codex
review of this report. The JSONL command output contained the failure literals above,
but the reviewer messages did not. The wrapper returned exit 0 and preserved
`docs/tasks/182/live-review.md`.

The review supplied this exact sentence, which was absent from the prompt:

> The durable artifact is finalized before execution-failure classification.

Evidence check:

```text
$ grep -F 'The durable artifact is finalized before execution-failure classification.' docs/tasks/182/report.md
The durable artifact is finalized before execution-failure classification. A failed
```

The acceptance reviewer also requested a direct assertion that the original review
text survives a true failure. That assertion was added before final review.

## Implementation review

The first Codex implementation round ran 12 targeted tests and found an unquoted
`prev_uuid` in the exec-resume shell command plus the scalar-JSONL gap. Both were fixed.
The UUID fix is defense-in-depth: `codex_sessions.json` is written by Orchestra, and an
attacker able to rewrite it already has write access as the service user. It is not an
external critical RCE.

Round 2 ran 14 targeted tests and returned `PASS`, confirming the quoting regression,
scalar handling, and durable-artifact assertion. Full evidence is in
`docs/tasks/182/codex-review-impl.md`.

## Found issue outside scope

The fresh-process implementation review exposed that `mode="review"` currently gives
Codex CLI 0.146.0 both `--uncommitted` and a prompt, which exits 2 before a reviewer
starts. This was independently reproduced, reported through `report_bug`, and tracked
as #183. It was not changed in #182; the implementation review used scoped `mode="exec"`.
