## Summary

Four of five prior blockers are closed. The shared 256k tool-detail limit remains bypassable through generated omission and synthetic-completion text.

I ran 43 focused tests against immutable target `b978572`; all passed. A separate reproduction produced:

`budget 256000 reported 81000 actual_tool_text 352893 entries 6000`

Exact reviewed line: `remaining_tool_budget = TOOL_DETAIL_BUDGET`

## Findings

### blocking — `app/runtime_history.py:148`

The 256k budget counts only retained source payload characters. `_bounded_tool_text()` returns generated omission markers with a detailed count of zero, while `close_pending()` adds an unbudgeted synthetic result for every pending call.

Consequently, histories with many sanitized, truncated, or incomplete tool calls can expose substantially more than 256k model-visible tool text. My 3,000-call reproduction generated 352,893 characters despite the 256,000 limit; larger histories grow without a shared bound. This can exhaust the target context or make reconnect/import fail.

Budget the complete rendered tool representation, including truncation markers, synthetic calls/results, names, and wrapper metadata, or impose a bounded number of imported tool records.

Prior blocker 5: **STILL BROKEN**. Binary and URL-safe base64 plus tool names are sanitized individually, but the required shared model-visible budget is not enforced.

### suggestion — `app/backend_codex.py:286`

Deferred T2 Codex history-import implementation and its tests are accidentally included in the T1 target as commit `41f2ca4`. Per scope, I did not review them. Remove them from the T1 delivery so approval and rollback boundaries correspond to the reviewed Claude slice.

## Prior blocker status

1. **CLOSED** — Both listener and heartbeat reconnect use `AgentSession._reconnect_backend()`, which awaits durable log writes, reads a fresh snapshot, calls `replace_history_import()`, and only then reconnects.

2. **CLOSED** — Identified results consult only `pending_by_source[source_id]`; FIFO fallback is restricted to results with an empty ID and `pending_legacy`.

3. **CLOSED** — `close_pending()` emits synthetic tool results before user or assistant boundaries, preserving valid tool-call/result ordering.

4. **CLOSED** — Fallback-summary construction occurs before `_disconnect_backend()` and before mutations to model, runtime, session ID, marker, handoff, or prompt state. Failure therefore leaves the old live backend and state untouched and creates no target process.

5. **STILL BROKEN** — Sanitization works for tested binary/base64 and metadata cases, but generated tool-history text bypasses the shared 256k budget as described above.

## Verdict

**NEEDS WORK**
