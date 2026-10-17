# item-33

Commit under review (in /home/kesha/orchestra, read-only): `d6155f9d4b4f01427c708e0ade542ab2fba7015b`
Subject / date:
#503: freeze Astra registry regression oracle
2026-09-05

The diff reviewed is `git -C /home/kesha/orchestra show d6155f9d4b4f01427c708e0ade542ab2fba7015b -- . ':(exclude).orchestra/tasks' ':(exclude).orchestra/kb'`.

## Reviewer output (verbatim)

## Summary

Reviewed the complete pinned diff. The Astra registry additions are present, and removing `minimal` from Codex’s accepted effort set matches the new contract. The CLI version bump conflicts with an existing pinned test and leaves the managed-state migration signature labeled with a version it was not captured from.

## Findings

### Blocking

- `tests/test_codex_managed_state.py::test_codex_01501_state_signature_is_pinned_exactly` still asserts `CODEX_CLI_HISTORY_VERSION == "0.150.1"`. This diff changes that constant to `"0.153.4"`, so the test fails. Update the test and pin the state migration signature for the new CLI version.

### Suggestion

- The new Astra test checks that its prices are positive, but does not pin the expected rates or context length. Since this task is to freeze a regression oracle, asserting the intended values would catch accidental changes to those registry entries.

## Verdict

NEEDS WORK
