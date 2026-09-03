# Review #35 — SDK/CLI Contract & Integration

Scope: `app/backend_claude.py`, `app/session.py`, `app/models.py`
SDK: `claude-agent-sdk==0.1.72` (source at `/mnt/data/Projects/Python/orchestra/.venv/.../claude_agent_sdk/`)

Severity: **P0** crash/data-loss · **P1** wrong behavior/value · **P2** missed feature or fragility · **P3** nit/cleanup

---

## Summary table

| # | Sev | File:line | Issue |
|---|-----|-----------|-------|
| 1 | P1 | backend_claude.py:248-275 | `usage.get("iterations")` — the SDK never produces an `iterations` key. Dead branch; cost calc relies entirely on the `else` flat path. |
| 2 | P1 | backend_claude.py:254-259 | `context_pct` from billing usage omits `output_tokens` and `cache_create` double-counts. Diverges from real `get_context_usage()`. |
| 3 | P1 | backend_claude.py:189-208 | `ThinkingBlock` never handled — extended thinking text is silently dropped from logs. |
| 4 | P1 | backend_claude.py:187-292 | `AssistantMessage.error` and `ResultMessage.is_error`/`errors` ignored — auth/billing/rate-limit failures look like normal idle turns. |
| 5 | P2 | backend_claude.py:31-38 | Blocked-tools list is stale vs SDK's real tool names (`Task` already the canonical subagent tool; `ScheduleWakeup`/`Cron*` may not exist). Verify against `get_server_info()`. |
| 6 | P2 | backend_claude.py:110-117 | `betas=["context-1m-2025-08-07"]` NOT passed — 1M context for `[1m]` models relies solely on the `[1m]` model-name suffix reaching the CLI. Fragile. |
| 7 | P2 | backend_claude.py:201-202 | `ServerToolResultBlock.content` is `dict`, but `_extract_tool_result` is tuned for `ToolResultBlock` (str/list). Web-search/fetch results render as `str(dict)`. |
| 8 | P2 | session.py:591-661 | `compact()` reinvents CLI compaction with a manual summary prompt instead of the SDK's real compact path; loses session continuity (drops `session_id`, starts fresh). |
| 9 | P2 | backend_claude.py:163-179 | `get_context_usage()` maxTokens already accounts for autocompact buffer; we store it but `context_usage()` never surfaces `rawMaxTokens`, causing pct mismatch vs CONTEXT_LIMITS. |
| 10 | P3 | models.py:14-23 | `CONTEXT_LIMITS`/`TOKEN_PRICES` hardcode 1M for `[1m]` but real ceiling depends on beta being active; no fallback if beta silently inactive. |
| 11 | P3 | backend_claude.py:294-303 | `compact_boundary` handled via `isinstance(SystemMessage)` + subtype string — correct, but brittle: relies on `case _` fallback in parser. Document it. |
| 12 | P2 | backend_claude.py:110-117 | Several useful options unused: `max_budget_usd`, `fallback_model`, `hooks` (PreCompact/Stop), `output_format`, `add_dirs`, `session_store`. |

---

## P1 findings (wrong values / silent data loss)

### 1. `usage["iterations"]` does not exist — dead code path
**`backend_claude.py:248-275`**

```python
iters = usage.get("iterations", [])      # always []
last = iters[-1] if iters else usage
...
if iters:                                # NEVER taken
    for it in iters: cost_cached += ...
else:                                     # always taken
    cost_cached = (input_tokens*p_in + ...)
```

The CLI result message carries a **flat** Anthropic-style `usage` dict (`input_tokens`, `output_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens`) — confirmed: the string `"iterations"` appears **nowhere** in the SDK (`grep -rn iterations claude_agent_sdk/*.py` → only an unrelated comment). The per-model breakdown that *would* play the role of `iterations` is **`ResultMessage.model_usage`** (`data["modelUsage"]`), which we never read.

**Impact:** `iters` is always empty, so the `if iters:` loop is dead. Functionally the `else` branch is correct, so cost isn't wrong — but the code is misleading and the `last = iters[-1] if iters else usage` line is pure noise.

**Fix:** Delete the `iterations` branch entirely. Either (a) trust `ResultMessage.total_cost_usd` (the SDK already computes real cost — we capture it as `cost_usd`), and drop the manual `cost_cached` recalculation, or (b) if multi-model turns matter, iterate `model_usage` (keyed by model name) instead of the phantom `iterations`.

```python
# usage is flat — no iterations
cache_create = usage.get("cache_creation_input_tokens", 0) or 0
cache_read   = usage.get("cache_read_input_tokens", 0) or 0
input_tokens = usage.get("input_tokens", 0) or 0
output_tokens= usage.get("output_tokens", 0) or 0
```

---

### 2. `context_pct` from billing usage is structurally wrong vs real context
**`backend_claude.py:254-259`**

```python
total = input_tokens + cache_create + cache_read
ctx_pct = int(total * 100 / max_tokens)
```

This is the **billing** token count for the *last assistant turn*, not the **context window occupancy**. Two divergences:

1. It sums `input + cache_create + cache_read` — but on a cache hit the *same* prompt prefix is counted as `cache_read`, and the live, uncached delta as `input`. That sum ≈ the full prompt size, so as a rough context proxy it's OK — **but** it omits `output_tokens` of accumulated history and does not reflect what the CLI's own `/context` reports.
2. The SDK exposes the **authoritative** value via `get_context_usage()` → `percentage` / `totalTokens` / `maxTokens`. We already call it in `_refresh_context_from_api()` (session.py:691) right after turn_end and overwrite `_last_context["percentage"]`. So the billing-derived `ctx_pct` is a throwaway that's shown for ~1s until the API refresh lands, then replaced.

**Impact:** transient wrong percentage on the dashboard right at turn end; confusing when they differ by >30% (session.py:702 logs a "context corrected" jump that is really just our bad estimate being fixed).

**Fix:** Stop computing `ctx_pct`/`ctx_tokens` from billing usage in `_convert`. Emit `turn_end` with cost only, and let `_refresh_context_from_api()` be the single source for context (it already is, on a 5s-timeout best-effort path). If you need an immediate value, prefer `model_usage`/`get_context_usage()` over the billing sum. Note the `maxTokens` from `get_context_usage()` is **post-autocompact-buffer**; `rawMaxTokens` is the true window — pick one consistently.

---

### 3. `ThinkingBlock` is dropped
**`backend_claude.py:189-208`**

`_convert` handles `TextBlock`, `ToolUseBlock`, `ToolResultBlock`, `ServerToolResultBlock` — but **not `ThinkingBlock`** (fields: `thinking: str`, `signature: str`). Opus with extended thinking emits these. They're silently discarded.

**Impact:** when an agent "thinks" for a long time (the heartbeat at session.py:553 even logs "possible long thinking"), the dashboard shows nothing — looks like a hang. Lost observability into the most expensive part of a turn.

**Fix:** add a branch:
```python
elif isinstance(block, ThinkingBlock) and block.thinking:
    events.append(AgentEvent("thinking", block.thinking))
```
(import `ThinkingBlock`; add a `thinking` event type or fold into `status`/`text` with a marker). Low risk, pure addition.

---

### 4. Error states ignored — failed turns look successful
**`backend_claude.py:187-292`**

- `AssistantMessage.error` (`AssistantMessageError` = `authentication_failed | billing_error | rate_limit | invalid_request | server_error | unknown`) — never read.
- `ResultMessage.is_error: bool` — never read; we hardcode `"ok": True` (line 279).
- `ResultMessage.errors: list[str]` and `permission_denials` — never read.

```python
events.append(AgentEvent("turn_end", ..., metadata={ "ok": True, ... }))  # always True
```

**Impact:** an auth/billing/rate-limit failure ends the turn; `_handle_turn_end` (session.py:392) reads `meta.get("ok", True)` → `True`, sets status IDLE, fires auto-report as if work completed. A rate-limited or billing-dead agent reports "done" with empty output. **This is the worst finding for an autonomous orchestrator** — silent failure is exactly the "fail loud" anti-pattern the project forbids.

**Fix:**
```python
is_err = bool(getattr(msg, "is_error", False))
err_list = getattr(msg, "errors", None) or []
events.append(AgentEvent("turn_end", ..., metadata={
    "ok": not is_err,
    "is_error": is_err,
    "errors": err_list,
    ...
}))
```
And in `_convert` for `AssistantMessage`, surface `msg.error` as an `error` event so the heartbeat/auto-report logic can react (e.g. don't auto-report a billing failure as success; surface to orchestrator).

---

## P2 findings (missed features / fragility)

### 5. Blocked-tools names may be stale
**`backend_claude.py:31-38`**

`_ORCH_DISALLOWED_TOOLS = ["Task", "Agent"]` and `_ALWAYS_DISALLOWED = ["ScheduleWakeup", "CronCreate", "CronDelete", "CronList"]`.

The SDK's subagent tool is **`Task`** (confirmed: `parse_message` builds `TaskStartedMessage` from `type:"system", subtype:"task_started"`). `"Agent"` is hedged as a legacy alias — fine, CLI ignores unknown names. But `ScheduleWakeup`/`Cron*` are guesses; if those tool names changed, the disallow is a silent no-op and the agent *can* schedule.

**Fix:** call `client.get_server_info()` once after connect — it returns the live command/tool list — and assert the names you intend to block actually exist; log a warning if a blocked name is absent (so a renamed tool fails loud instead of silently re-enabling).

### 6. `betas` not passed — 1M context depends only on `[1m]` suffix
**`backend_claude.py:110-117`**

`ClaudeAgentOptions` has `betas: list[SdkBeta]` and the only valid value is `"context-1m-2025-08-07"`. We do **not** set it. Recent commit `8f6426e` "restores 1M context by passing model name with `[1m]` suffix to CLI" — meaning the whole 1M path hinges on the CLI parsing `[1m]` out of the model string. That's brittle and undocumented.

**Fix:** for `[1m]` models, also set `options.betas = ["context-1m-2025-08-07"]`. Belt-and-suspenders: if the suffix path ever breaks again, the beta still activates 1M. Verify via `get_context_usage().rawMaxTokens == 1_000_000`.

### 7. `ServerToolResultBlock` content is a dict, not str/list
**`backend_claude.py:64-79, 201-202`**

`ServerToolResultBlock.content: dict[str, Any]` (web_search/web_fetch/code_execution results). `_extract_tool_result` handles `list` and `dict`, but the `dict` branch only pulls `raw.get('text', str(raw))` — server-tool results don't carry a top-level `text`, so it falls to `str(dict)` → ugly blob in logs.

**Fix:** branch on block type, or detect server-tool result shape and render the relevant field. Low priority (cosmetic in logs).

### 8. `compact()` bypasses the SDK's real compaction
**`session.py:591-661`**

We manually send a `COMPACT_PROMPT`, capture the model's free-text summary, then **drop `session_id`** (line 648) and start a brand-new session seeded with a `PREAMBLE` summary. Meanwhile the SDK/CLI has *native* compaction: it emits `compact_boundary` SystemMessages (which we already detect at backend_claude.py:294) with `preTokens`/`postTokens`, and there's a `PreCompact` hook event. The CLI's auto-compact preserves the real session and tool-result history; our manual path throws away the session and reconstructs from a lossy text summary.

**Impact:** manual compact loses structured history, tool results, file context — only a prose summary survives. Also: at session.py:442, `ctx_pct > 90` triggers our manual `_auto_compact`, racing the CLI's own auto-compact (which fires at `autoCompactThreshold`). Two compaction mechanisms fighting.

**Fix:** prefer the CLI's native auto-compact (it's already enabled — `isAutoCompactEnabled`). Drop the manual `>90%` trigger, or gate it on `not isAutoCompactEnabled`. If a manual handoff summary is genuinely wanted, keep it but **don't null the session_id** — let the CLI compact in place. At minimum, stop racing the CLI.

### 9. `maxTokens` vs `rawMaxTokens` mismatch
**`backend_claude.py:163-179`, `session.py:701`**

`get_context_usage()` returns both `maxTokens` (reduced by autocompact buffer) and `rawMaxTokens` (true window). We read `maxTokens` and store it as the denominator. But `CONTEXT_LIMITS` (models.py) holds the **raw** 1M/200k. So `percentage` from the SDK (computed against reduced `maxTokens`) and our `ctx_pct` (computed against raw `CONTEXT_LIMITS`) use **different denominators** → they can't agree even when both are "right".

**Fix:** pick one denominator. Recommend: read `rawMaxTokens` from `get_context_usage()` and use the SDK's own `percentage` everywhere; delete the parallel `CONTEXT_LIMITS`-based pct in `_convert` (ties into finding #2).

### 12. Unused options worth adopting
**`backend_claude.py:110-117`**

`ClaudeAgentOptions` fields we don't use that map to real Orchestra needs:
- **`max_budget_usd`** — hard cost ceiling per session. Orchestra tracks cost manually; this enforces it at the CLI.
- **`fallback_model`** — auto-failover when primary model is rate-limited (directly mitigates finding #4's rate_limit case).
- **`hooks`** (`PreCompact`, `Stop`, `SubagentStart`/`Stop`) — server-side callbacks instead of polling message stream; cleaner than the current `TaskStarted/Progress/Notification` parsing for subagent lifecycle.
- **`add_dirs`** — grant a worker read access to sibling dirs without leaving its worktree.
- **`session_store`** — pluggable session persistence (we roll our own SQLite resume via `resume=`).

Not bugs — but `fallback_model` and `max_budget_usd` are cheap wins for an autonomous orchestrator.

---

## P3 / nits

### 10. `[1m]` limits assume beta is active
**`models.py:14-23`** — `CONTEXT_LIMITS["claude-opus-4-8[1m]"] = 1_000_000`. If the beta/suffix path silently fails (as it did pre-`8f6426e`), the real window is 200k but we'd compute pct against 1M → agent hits a wall at "20%". Mitigated by finding #6 (pass the beta) + #9 (read `rawMaxTokens` and trust it over the hardcoded table).

### 11. `compact_boundary` detection is fallback-dependent
**`backend_claude.py:294-303`** — works because the parser routes unknown subtypes to the bare `SystemMessage` `case _`. Correct today. Add a comment noting it depends on the SDK NOT promoting `compact_boundary` to a dedicated subclass (if it ever does, the `isinstance(SystemMessage) and not isinstance(Task*)` guard still holds, so low risk).

---

## What we DO use correctly (sanity check)
- Persistent `ClaudeSDKClient` + `query()` for mid-turn inject — matches SDK design (query writes to stdin, doesn't block). ✓
- `receive_messages()` infinite loop in the event loop — correct (we manage turn boundaries via `ResultMessage`). ✓
- `can_use_tool` permission callback + `disallowed_tools` split — correct: subagent launch bypasses the permission callback (arrives as `TaskStartedMessage`), so blocking it needs `disallowed_tools`, exactly as the comment at :33-36 explains. ✓
- `system_prompt` preset `{"type":"preset","preset":"claude_code","append":...}` — valid `SystemPromptPreset`. ✓
- `setting_sources=["user","project","local"]` — valid `SettingSource` list. ✓
- `compact_boundary` capture — correct (finding #11 is just documentation). ✓

---

## Priority recommendation
1. **#4** (error states) — P1, fix first; silent failure in an autonomous orchestrator is the highest-risk bug here.
2. **#3** (thinking blocks) — P1, trivial addition, big observability win.
3. **#1 + #2 + #9** (cost/context calc) — P1, fix together: delete the `iterations` branch, drop billing-derived `ctx_pct`, standardize on `get_context_usage()` + `rawMaxTokens`.
4. **#6** (betas) — P2, one line, de-risks the whole 1M story.
5. **#8** (compaction race) — P2, stop the manual `>90%` trigger fighting the CLI.

---

## Codex cross-review status
`codex_review(mode="exec")` was launched **twice** (bg jobs `bg-1a3847c59f`, `bg-abb94ed3bc`). Neither produced output — `docs/tasks/35/codex-sdk.md` was never written, no `codex` process running, `.codex` is 0 bytes. The MCP tool reports "started" but the GPT-5.5 backend does not complete/write. Filed as an Orchestra platform bug. Per "fail loud, not creative" I did not improvise a bash workaround (rules require Codex review via the `codex_review()` MCP tool only).

The findings above stand on direct SDK-source verification (grep + read of `claude_agent_sdk` 0.1.72): the phantom `iterations` key, `ContextUsageResponse` shape, `AssistantMessage.error`/`ResultMessage.is_error` fields, and the parser's `compact_boundary` routing were all confirmed against source, not assumed.
