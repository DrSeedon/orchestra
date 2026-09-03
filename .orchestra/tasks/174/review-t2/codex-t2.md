<!-- Attempt 1 outcome: completed, round spent, verdict valid by verified exact diff quote. -->

## Summary

The import path generally satisfies the structural contracts: `thread/resume.history` is used without rollout/path forgery, experimental API is import-only, fresh IDs are accepted only during import, ordinary resume retains its mismatch guard, and T1 normalization/sanitization/tool completion/capping are shared.

One blocking fallback-classification defect remains. The probe document also has a material evidentiary gap.

## Findings

**blocking:** `app/backend_codex.py:388-401` — Restrict schema fallback classification to errors explicitly tied to `history`.

`_history_rejection()` treats any `thread/resume` protocol message containing generic markers such as `invalid params`, `failed to parse`, or `missing field` as a history-schema rejection. Those errors can instead concern `model`, `cwd`, `threadId`, approval policy, or another resume parameter. They are consequently converted into `NativeHistoryRejected`, causing a silent one-time summary fallback instead of the required fail-loud behavior.

A deterministic check against commit `865e8107` produced:

```text
invalid params: unknown model gpt-bad => NativeHistoryRejected
invalid params: cwd does not exist => NativeHistoryRejected
invalid params: invalid threadId => NativeHistoryRejected
```

Only errors explicitly identifying `history` or its response-item schema should be summary-eligible. Generic `-32602`/parse errors must propagate unchanged.

**suggestion:** `docs/tasks/174/t2-tool-history-probe.md:3-13` — Preserve reproducible evidence from the isolated probe.

The document contains only asserted booleans and a type list. It provides no exact command/script, JSON-RPC request and response, disposable `CODEX_HOME`, returned thread ID, rollout location/hash, or verbatim persisted records. Because the disposable home was trashed, an independent reviewer cannot establish that these values came from a real Codex 0.146.0 run or that the inspected rollout belonged to the returned fresh ID.

Therefore it does not independently prove acceptance and persistence of:

```text
message → custom_tool_call → custom_tool_call_output → message
```

The probe should retain a redacted raw transcript or reproducible script plus the returned ID and matching persisted rollout excerpt.

## Probe assessment

Material evidentiary gap. The claimed result is plausible and consistent with the implementation, but the current 13-line document is a conclusion, not auditable evidence.

## Evidence

Exact-commit focused tests:

```text
uv run pytest -q \
  tests/test_backend_codex.py::test_history_protocol_rejections_are_typed \
  tests/test_backend_codex.py::test_history_initialize_protocol_error_is_not_summary_eligible \
  tests/test_backend_codex.py::test_resume_rejects_substituted_thread_before_turn \
  tests/test_session.py::test_codex_history_capability_failure_uses_visible_summary_fallback

......                                                                   [100%]
6 passed in 8.25s
```

A verbatim diff line confirming import-only history transport:

```python
params["history"] = list(history_import.history)
```

The passing tests cover selected expected messages but do not test whether generic non-history `thread/resume` parameter failures remain fail-loud.

## Verdict

**Changes requested.** The broad rejection classifier violates acceptance contract 5 and can hide ordinary configuration/connect failures behind summary fallback. The probe should also be upgraded before its acceptance-and-persistence claim is treated as proven.
