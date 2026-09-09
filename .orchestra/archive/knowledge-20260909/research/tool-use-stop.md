# Root cause: `stop_reason=tool_use` from Claude SDK

**Date:** 2026-06-15
**Investigator:** exp-tool-use (empirical)
**Status:** ROOT CAUSE FOUND — task hypothesis REFUTED

---

## TL;DR

`stop_reason=tool_use` is **NOT** "the agent wanted another tool call but the SDK cut the turn short."
It is emitted by the **bundled CLI's terminal-state validator** (`RA4`) when a turn ends while the
**last message in the buffer is a `user` message that is not a clean all-`tool_result` array**.

Every single occurrence in our DB (37 cases over ~5 days) was caused by one of three things — never
by the model spontaneously deciding to stop mid-work:

| Trigger | Count | Mechanism |
|---|---|---|
| **`interrupt()`** (stop_worker / kill_worker / manual stop / orchestrator stop) | 31/37 | turn aborted mid-tool, buffer left in non-terminal state |
| **Permission denial** (`can_use_tool` → Deny, or user "don't proceed") | 4/37 | denial appends synthetic non-tool_result user msg |
| **Mid-turn message injection / branch-switch reset** | 2/37 | injected user msg lands after a `tool_use` block |

**The current `auto-continue on tool_use` fix (commit `ddfe023`) is a no-op** — it has fired **0 times**
for `tool_use` because all real cases carry `is_error=true` (`ok=False`) and the `and ok` guard excludes them.

---

## Evidence

### 1. `stop_reason=tool_use` is produced by the CLI, not the SDK Python layer

`ede_diagnostic` does not exist anywhere in the `claude_agent_sdk` Python source — only in the bundled
CLI binary (`_bundled/claude`, 4 hits). The exact template:

```js
`[ede_diagnostic] result_type=${V$} last_content_type=${k$} stop_reason=${D$}`
```

### 2. The terminal-state validator `RA4` (decoded from minified CLI)

```js
function RA4(H, $=null){
  if(!H) return false;
  if(H.type==="assistant"){
    let q = lastContentBlock(H.message.content);
    return q?.type==="text" || q?.type==="thinking" || q?.type==="redacted_thinking";
  }
  if(H.type==="user"){
    let q = H.message.content;
    if(Array.isArray(q) && q.length>0 && q.every(K => "type" in K && K.type==="tool_result"))
      return true;
  }
  return $ === "end_turn";   // $ = stop_reason
}
```

And the call site (the turn-finalization loop):

```js
let _$ = RH.findLast(m => m.type==="assistant" || m.type==="user");  // last assistant|user msg
let V$ = _$?.type ?? "undefined";                                     // result_type
let k$ = _$?.type==="assistant" ? lastBlock(_$.message.content)?.type ?? "none" : "n/a";  // last_content_type

if(!RA4(_$, D$)){                          // D$ = stop_reason
  yield {
    type:"result", subtype:"error_during_execution", is_error:true,
    stop_reason: D$,                        // ← this is where stop_reason=tool_use surfaces
    errors:[ `[ede_diagnostic] result_type=${V$} last_content_type=${k$} stop_reason=${D$}`, ... ]
  };
  return;
}
```

**Interpretation:** when the turn finalizes, the CLI looks at the last assistant/user message.
- If it's an `assistant` message ending in `text`/`thinking` → valid (`end_turn`).
- If it's a `user` message that is a clean array of `tool_result` blocks → valid (more tool output coming).
- **Otherwise** → `error_during_execution`, `is_error=true`, and `stop_reason` reflects the model's
  last intent — which is `tool_use` because the last *assistant* action was a tool call that never got
  its clean tool_result tail (it was interrupted / denied / displaced by an injected message).

`result_type=user, last_content_type=n/a` in our logs ⇒ the last message **was** a `user` message
(so `k$` = "n/a"), but it failed the "every block is tool_result" check ⇒ `RA4` returned false.

### 3. DB forensics — 100% correlation with interrupt/denial/inject

Query: every `turn ended (tool_use...)` log and its 8 preceding logs (`data/orchestra.db`).

- **37** total `tool_use` turn-ends.
- **31** immediately preceded by `status: interrupted`.
- **6** not preceded by interrupt — but each is a permission denial or a mid-turn inject:
  - `133681/133688/133694/133823` → tool_result = `"The user doesn't want to proceed with this tool use"`
    (the `sudo systemctl restart orchestra` permission deny).
  - `133821` → `switch_worker_branch` MCP (internally resets/interrupts the session).
  - `152330` → `[Background job completed]` message injected via `send()` landing right after a
    `bg_create` tool_use block.

Representative trace (the dominant pattern — worker reports DONE, then gets stopped):

```
139077  tool         mcp__orchestra__send_message → "DONE: ..."
139079  tool_result  Message sent to 'seedon-orchestrator'
139081  status       interrupted                       ← interrupt() called here
139082  status       turn ended (tool_use, 8 turns, ...)
139083  error        turn FAILED: [ede_diagnostic] result_type=user last_content_type=n/a stop_reason=tool_use
```

### 4. The current fix never fires

```sql
SELECT count(*) FROM logs WHERE type='status' AND content LIKE 'tool_use (%auto-continuing%';
-- → 0
```

`apply_turn_result` sets `ok = not is_error`. All real `tool_use` results have `is_error=true`
(`error_during_execution`), so `ok=False`, so the guard `if sr in (..., "tool_use") and ok` is never
satisfied. The fix is dead code for its stated purpose, and the comment ("agent wanted another tool
call but SDK ended the turn") is factually wrong.

Moreover, the entire auto-continue branch is dead: **`max_turns`/`error_max_turns` has also never
fired** (0 real turn-end events; the `--max-turns 200` ceiling is never reached in practice). The only
stop reasons that actually occur are `end_turn`, `stop_sequence`, and `tool_use`. So the branch
`if sr in ("error_max_turns", "max_turns", "tool_use") and ok` matches **nothing** that has ever
happened.

---

## Hypotheses — verdict

| # | Hypothesis | Verdict | Evidence |
|---|---|---|---|
| 1 | SDK `--max-turns 200` limit hit, returns tool_use instead of max_turns | **REFUTED** | max_turns has its own subtype `error_max_turns` with a distinct error string. tool_use cases had 3–58 turns, far below 200. **Zero real `max_turns`/`error_max_turns` turn-ends exist in the DB** — the 28 "matches" are agents *discussing* max_turns in text/tool logs, not actual stops. The `--max-turns 200` ceiling has never been hit. |
| 2 | Permission denial → stop | **PARTIALLY CONFIRMED** | 4/37 cases. Denial leaves buffer non-terminal → RA4 false → tool_use. Minor contributor. |
| 3 | Context limit / truncation | **REFUTED** | Context was 5–48% in all cases. No correlation. |
| 4 | SDK bug, `events()` returns turn_end early | **REFUTED** | turn_end is correct; the CLI deliberately emits `error_during_execution`. SDK faithfully relays it. |
| 5 | Network timeout | **REFUTED** | No timeout logs around these events; all have clean cost/usage data. |
| — | **interrupt() mid-tool** (not in original list) | **CONFIRMED — root cause** | 31/37, 100% correlation with `status: interrupted`. |

---

## Why this is mostly *benign*

`stop_reason=tool_use` is the CLI's honest way of saying *"this turn was terminated before it reached a
natural stopping point."* For an **interrupt** that is exactly correct and desired — the user/orchestrator
asked the worker to stop. Going IDLE is the right outcome. The only real problem is **cosmetic**: it's
logged as `turn FAILED` with a scary `[ede_diagnostic]` line, which looks like a crash but isn't.

The auto-continue fix tried to "rescue" these turns, but:
1. It can't (the `and ok` guard blocks all of them — by luck, not design).
2. If it *could*, it would be **harmful**: it would resurrect a worker the user deliberately stopped.

---

## The correct fix

Stop treating `tool_use` as a thing to rescue. Treat it as what it is: **an interrupted/displaced turn**,
which should go IDLE quietly (no `turn FAILED` noise, no auto-continue).

### Fix 1 (primary) — classify `tool_use` as interrupted, drop it from auto-continue

In `app/session_turns.py::handle_turn_end`:

```python
# stop_reason=tool_use is NOT "agent wanted to continue". The bundled CLI emits it
# (subtype=error_during_execution) whenever a turn is terminated with the buffer in a
# non-terminal state — i.e. interrupt(), permission denial, or a mid-turn injected message
# displacing a tool_use block. None of these should be auto-continued: an interrupt is a
# deliberate stop, and a denial/inject already has the model's attention next turn.
if sr in ("error_max_turns", "max_turns") and ok:
    # genuine turn-budget exhaustion — continue where it left off
    ...auto-continue...
```

i.e. **remove `"tool_use"` from the auto-continue set.** Keep auto-continue only for the genuine
`max_turns` case it was originally built for.

### Fix 2 (cosmetic but important) — silence the false `turn FAILED`

`tool_use` already gets `ok=False` and lands in the `if not ok:` branch, where the `[ede_diagnostic]`
string is the only "error" and gets logged as `turn FAILED`. Suppress it:

```python
if not ok:
    errors = [e for e in (meta.get("errors") or [])
              if not str(e).startswith("[ede_diagnostic]")]
    if sr == "tool_use":
        # interrupted / displaced turn — expected, not a failure
        s._log("status", "turn interrupted (tool_use)")
    elif errors:
        s._log("error", f"turn FAILED: {'; '.join(str(e) for e in errors)}")
    else:
        s._log("status", f"turn interrupted ({sr})")
```

(The `[ede_diagnostic]` filter already exists for the `errors` list; we just add an explicit
`tool_use` short-circuit so the leftover-diagnostic case doesn't fall through to `turn FAILED`.)

### Fix 3 (optional, root-cause for the 2 inject cases) — guard mid-turn inject

For the rare inject case (`152330`): when a `[Background job completed]` or queued message is injected
via `backend.send()` during an active turn, it can land between a `tool_use` and its `tool_result`,
producing a spurious `tool_use` stop. This is low-frequency (2/37) and self-healing (the next turn
processes the message). Not worth a structural fix now — document and move on. If it becomes frequent,
queue injects until the in-flight tool_result is observed rather than sending immediately.

### What NOT to do
- Do **not** keep the `tool_use` → auto-continue branch. It is wrong in principle (resurrects stopped
  workers) and inert in practice (never fires).
- Do **not** try to "fix" the CLI's `RA4` — it's correct. The buffer genuinely is non-terminal after
  an interrupt.

---

## One-line summary

> `stop_reason=tool_use` = "the turn was interrupted/displaced before a natural stop" (CLI `RA4`
> validator), 84% from `interrupt()`. It is benign; the right fix is to log it as *interrupted* and
> let the worker go IDLE — **not** auto-continue (which never fired anyway and would resurrect stopped
> workers).
