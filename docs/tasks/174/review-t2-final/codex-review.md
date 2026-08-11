## Summary

The round-1 blocker remains: `_history_rejection()` still mistakes unrelated parameter errors for history-schema rejection whenever `"history"` appears incidentally.

The acceptance artifact does adequately bind the returned thread ID to the persisted rollout using literal request, response, path, hash, and payload evidence.

## Findings

**blocking:** `_history_rejection()` uses an unscoped substring check:

> `"history" in detail`

Executing the exact classifier from the diff produced:

```text
schema-history: NativeHistoryRejected
schema-response: NativeHistoryRejected
model: FAIL_LOUD
cwd-incidental: NativeHistoryRejected
model-incidental: NativeHistoryRejected
thread-incidental: NativeHistoryRejected
instruction-incidental: NativeHistoryRejected
approval: FAIL_LOUD
auth: FAIL_LOUD
network: FAIL_LOUD
```

Thus ordinary cwd, model, thread ID, and developer-instruction errors containing “history” silently activate summary fallback. The focused tests cover generic errors only when that incidental word is absent, so they do not catch the blocker.

The classifier needs evidence that `history`/`ResponseItem` is the rejected schema subject—not merely text anywhere in the full error.

## Verdict

**DO NOT MERGE**
