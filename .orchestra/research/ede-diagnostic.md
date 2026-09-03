# ede_diagnostic Turn Failure — Root Cause Analysis

**Date**: 2026-06-11
**Reporter**: 85 occurrences across 27 sessions
**Severity**: Low (cosmetic — no data loss, no work loss)

## TL;DR

`ede_diagnostic` is a **Claude CLI internal diagnostic string** — NOT an Orchestra or SDK error. It fires when a turn ends in an unexpected state (e.g., interrupted mid-tool-use). The error log is cosmetic: the agent's work (commits, messages) is always preserved.

## What Happens

### Sequence (from DB logs)
```
04:17:49 [tool]        mcp__orchestra__send_message(DONE)
04:17:49 [tool_result]  "Message sent to 'stargate-orchestrator'"
04:17:54 [status]       interrupted                          ← orchestrator stop_worker()
04:17:54 [error]        turn FAILED: [ede_diagnostic] ...    ← CLI diagnostic in result.errors
04:17:54 [status]       turn ended (tool_use, 19 turns, $0.00 ...)
```

### Root Cause: Race Between Worker and Orchestrator

1. **Worker** calls `send_message(DONE)` → MCP tool returns "Message sent"
2. **Worker** is still RUNNING — CLI expects the agent to decide next action
3. **Orchestrator** receives DONE instantly, calls `stop_worker("fable")` within 5 seconds
4. `stop_worker` → `session.interrupt()` → `client.interrupt()` → SIGTERM to CLI
5. CLI is mid-turn (stop_reason=tool_use — agent was about to emit more content)
6. CLI creates `result` event with `is_error=True`, `errors=["[ede_diagnostic] result_type=user last_content_type=n/a stop_reason=tool_use"]`
7. Our `_handle_turn_end` sees `ok=False` → logs `"turn FAILED: [ede_diagnostic] ..."`

### Why `$0.00 turn`?
The interrupted turn had no new API calls after the previous turn_end. The agent was in "thinking" phase (deciding what to do after send_message succeeded). No tokens consumed = $0.00.

## Where `ede_diagnostic` Lives

### Claude CLI (binary, compiled JS)
```javascript
// In result event handler (xFA function):
let $ = H.errors.filter((q) => !q.startsWith("[ede_diagnostic]"));
if ($.length === 0) return null;  // ← CLI UI filters these out!
```

The CLI **generates** `ede_diagnostic` strings for internal telemetry and **filters them out** in the UI. But the SDK passes `result.errors` through verbatim.

### Claude Agent SDK (Python)
```python
# types.py:1162
class ResultMessage:
    errors: list[str] | None = None  # ← raw from CLI, includes [ede_diagnostic]

# query.py:304-306
if message.get("is_error"):
    errors = message.get("errors") or []
    self._last_error_result_text = "; ".join(errors)  # ← NOT filtered
```

### Orchestra (our code)
```python
# backend_claude.py:331-333 — correctly propagates is_error and errors
"ok": not is_err,
"errors": err_list,

# session.py:550-553 — logs ALL errors including [ede_diagnostic]
if not ok:
    errors = meta.get("errors") or []
    err_txt = "; ".join(str(e) for e in errors) if errors else sr
    self._log("error", f"turn FAILED: {err_txt}")
```

## Fix Options

### Option 1: Filter `[ede_diagnostic]` in session.py (Recommended)
```python
# session.py _handle_turn_end
if not ok:
    errors = meta.get("errors") or []
    real_errors = [e for e in errors if not str(e).startswith("[ede_diagnostic]")]
    if real_errors:
        self._log("error", f"turn FAILED: {'; '.join(str(e) for e in real_errors)}")
    else:
        self._log("status", f"turn interrupted ({sr})")
```

**Pros**: Matches CLI behavior (they filter it too). Reduces noise from 85+ false error logs.
**Cons**: May hide future real errors that start with `[ede_diagnostic]` (unlikely — it's internal).

### Option 2: Don't treat interrupted turns as errors
```python
# When interrupt() was called explicitly, the result's is_error=True is expected
# Could track _interrupt_requested flag
```
**Pros**: Semantically correct — interrupt is not an error.
**Cons**: More complex, flag management.

### Option 3: Both (Belt + Suspenders)
Filter ede_diagnostic AND track interrupt state. Log interrupt results as "status" not "error".

## Impact Assessment

- **Work loss**: NONE. All 85 cases show commits preserved, messages delivered
- **Agent confusion**: NONE. Agent is already IDLE after interrupt, new turn starts clean
- **Dashboard noise**: HIGH. 85 red error entries that are actually normal operation
- **Cost impact**: NONE. $0.00 turns — no wasted tokens

## Recommendation

**Option 1** — filter `[ede_diagnostic]` from errors, matching CLI behavior. Simple, targeted, no side effects. The orchestrator calling `stop_worker` after receiving DONE is correct behavior — the "error" is just CLI diagnostics leaking through.
