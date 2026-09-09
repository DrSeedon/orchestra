# Phantom Context Reset / Loss — Root Cause Research

**Date:** 2026-05-31
**Status:** Research complete. Multiple root causes found. Fixes proposed below.
**SDK:** claude-agent-sdk 0.1.72 (bundled CLI)

## TL;DR

The "context dropped to a very low %" symptom is **not one bug** — it's a cluster of
issues around how Orchestra *derives* `context_pct` and how the Claude CLI *internally*
compacts. The context number is **reverse-engineered** from `ResultMessage.usage`
instead of read from the authoritative `get_context_usage()` API. Combined with the
CLI's own auto-compaction (which we do not detect) and a reconnect path that loses the
last-known context, the displayed % jumps around and sometimes reads near-zero even
though no `compact_worker` ever ran.

**Primary fix:** read context from `client.get_context_usage()` (the same source as
the CLI `/context` command) instead of computing it from `usage` iterations.

---

## How context % is currently computed

`backend_claude.py:229-242`, inside `_convert()` on `ResultMessage`:

```python
if usage and isinstance(usage, dict):
    iters = usage.get("iterations", [])
    last = iters[-1] if iters else usage          # <-- LAST iteration only
    cache_create = last.get("cache_creation_input_tokens", 0) or 0
    cache_read   = last.get("cache_read_input_tokens", 0) or 0
    input_tokens = last.get("input_tokens", 0) or 0
    total = input_tokens + cache_create + cache_read
    max_tokens = CONTEXT_LIMITS.get(self.model, 200000)
    ctx_pct = int(total * 100 / max_tokens)
```

This value flows: `turn_end` event → `_handle_turn_end()` → `self._last_context` →
persisted to DB (`context_pct`) → dashboard + MCP tools + auto-report warnings.

**The problem:** `total` here is "tokens sent on the last API iteration of the turn",
NOT "tokens currently resident in the context window". These differ whenever:
- the turn had multiple internal iterations (tool loops),
- the CLI compacted mid-turn (post-compaction iteration is small),
- a cache boundary shifted what counts as `cache_read` vs `input`.

The SDK ships an authoritative method that returns exactly what `/context` shows:
`ClaudeSDKClient.get_context_usage()` → `ContextUsageResponse` with
`percentage`, `totalTokens`, `maxTokens` (effective, post-autocompact-buffer),
`isAutoCompactEnabled`, `autoCompactThreshold` (`types.py:706-768`, `client.py:505`).
**We never call it.**

---

## Root causes (ranked)

### RC1 — context % is estimated from `usage`, not read from the API  ⭐ PRIMARY
**Where:** `backend_claude.py:229-242`
**Why it causes the symptom:** the estimate is per-iteration, not whole-window. After a
tool-heavy turn or any cache reshuffle, `iters[-1].input_tokens` can be a small delta
while the true resident context is large (cache_read carries the bulk). Result: the %
swings turn-to-turn and can read far below reality — looks like "context was reset".
**Proof:** the field is hand-derived; the SDK's own `/context`-equivalent
(`get_context_usage`) is never invoked anywhere in the codebase (grep confirms only
`backend_claude.py` / `backend_codex.py` set `context_pct`, both by hand).

### RC2 — CLI internal auto-compaction is invisible to Orchestra  ⭐ PRIMARY
**Where:** not handled anywhere. SDK evidence: `sessions.py:283`, `933-936` —
`isCompactSummary` messages "replace earlier messages"; `compact_boundary` entries
carry `logicalParentUuid` which the SDK deliberately does NOT follow on resume.
**Why it causes the symptom:** Claude Code has its OWN autocompact (independent of our
`_auto_compact()` at `session.py:440`). When it fires, the CLI summarizes + truncates
the transcript. The very next `ResultMessage` legitimately reports a much lower token
count → `context_pct` plunges. To the operator this looks like "context reset for no
reason" — and indeed there is **no compact event in our logs**, because *we* didn't
compact, the CLI did. This exactly matches the PM report: "claims context was reset
when it shouldn't have been" + "no compact events in logs".
**Note:** our `_auto_compact()` fires at `ctx_pct > 90`. If the CLI's own
`autoCompactThreshold` is lower (and `isAutoCompactEnabled` true), the CLI compacts
first, our threshold never trips, and the drop is purely CLI-side.

### RC3 — reconnect/resume can serve a stale-or-zero context  ⭐ SECONDARY
**Where:** `session.py:285,562` (`reconnect`), `manager.py:754-759` (`_load_from_db`).
- On `_load_from_db`, `_last_context` is rebuilt from the DB row, but **only if
  `pct or tokens`** is truthy (`manager.py:756`). A worker that never finished a turn,
  or whose last persisted `context_pct` was 0, comes back showing 0% — then the first
  post-resume turn re-derives a (possibly low) number via RC1.
- `reconnect()` (`backend_claude.py:163`) makes a brand-new client with `options.resume
  = session_id`. The resume itself preserves the CLI transcript, BUT the in-memory
  `_last_context` is not refreshed until the next `turn_end`. Any dashboard read in the
  gap shows the pre-disconnect number, which may already be wrong from RC1.

### RC4 — `compact()` mutates `session_id = None`, losing the thread on crash  ⭐ SECONDARY
**Where:** `session.py:645-650`
```python
self.session_id = None        # deliberately fork a fresh session
self._persist()               # <-- persisted with session_id = NULL
...
await self.send(preamble + "Acknowledge briefly.")
```
Between line 645 and the new turn completing, the persisted `session_id` is `NULL`.
If the server restarts in that window, `auto_resume_all()` (`manager.py:879`) filters
`WHERE session_id IS NOT NULL` → **the agent is not resumed at all**, and when it is
next touched it starts a fresh CLI session = full context loss. This is a real
crash-window data-loss path, though narrow.
Also: `_auto_compact()` (`session.py:689`) sets `_compacting=True`, then `compact()`
sets it again and clears it in its own path, while `_auto_compact`'s `finally` clears
it too — double ownership of the flag (see RC6).

### RC5 — race: mid-turn inject vs auto-report vs flush_pending
**Where:** `session.py:166-188` (mid-turn `send`), `369-387` (`_fire_auto_report`),
`453-481` (`_flush_pending`).
- `send()` while `RUNNING` (non-codex) injects via `backend.send()` WITHOUT taking
  `_lifecycle_lock` (`session.py:179-183`). It does NOT reset `_did_report`,
  `_turn_logs`, or bump `_turn_gen`. So a message injected mid-turn rides on the
  current turn's bookkeeping.
- `_fire_auto_report()` reads `_turn_logs[-5:]` and fires on idle. If an inject landed
  late, the turn it reports may be a merge of two logical messages → confusing but not
  a context *loss*.
- Not a direct context-reset cause, but it muddies the `_last_context`/report timing so
  operators mis-attribute drops. Lower priority.

### RC6 — `_compacting` flag double-managed; window where messages queue silently
**Where:** `session.py:166-170` + `689-697`.
While `_compacting` is True, all `send()` calls queue into `_pending_messages` and the
agent looks "stuck". `_auto_compact` sets the flag, calls `compact()` (which also
sets/clears it), then `_auto_compact.finally` clears it again. If `compact()` returns
early (empty summary / exception) it clears the flag, but `_auto_compact` still holds
its own `finally` — benign now, but fragile. Worth simplifying so only one owner.

---

## Why "no compact events in logs" yet context dropped

Two independent mechanisms produce a low % without an Orchestra-side compact:
1. **RC2** — the CLI compacted internally; we log nothing because we didn't act.
2. **RC1** — the % is an estimate; a normal tool-heavy turn can *estimate* low even
   with no compaction at all.

Both are consistent with the PM's exact wording. RC2 is the "real reset" case
(content genuinely summarized); RC1 is the "phantom" case (number wrong, content intact).

---

## Proposed fixes

### Fix A (PRIMARY) — read context from `get_context_usage()`
Replace the hand-derived `ctx_pct` with the authoritative API. After each turn (or on
demand for the dashboard), call the client method and store the real numbers.

In `backend_claude.py`, add:
```python
async def context_usage(self) -> dict | None:
    if not self._client:
        return None
    try:
        u = await self._client.get_context_usage()  # ContextUsageResponse
        return {
            "percentage": int(u.get("percentage", 0)),
            "total_tokens": u.get("totalTokens", 0),
            "max_tokens": u.get("maxTokens", 0),
            "auto_compact": u.get("isAutoCompactEnabled", False),
            "auto_compact_threshold": u.get("autoCompactThreshold", 0),
        }
    except Exception as e:
        logger.warning(f"get_context_usage failed: {e}")
        return None
```
Then in `session._handle_turn_end`, after the turn settles, refresh `_last_context`
from `await self._backend.context_usage()` (fall back to the old estimate if it returns
None, so codex/offline paths still work). This makes the displayed % match `/context`
exactly and removes the per-iteration estimation error (RC1).

> Tradeoff: one extra control-request round-trip per turn. Cheap, and only for the
> claude backend. Can be gated to "only when status→idle" to avoid mid-turn cost.

### Fix B (PRIMARY) — detect & surface CLI internal auto-compaction (RC2)
Two parts:
1. **Surface the threshold.** With Fix A we now have `isAutoCompactEnabled` +
   `autoCompactThreshold`. Log/emit a `status` event when the CLI's own autocompact is
   enabled and we cross its threshold, so a drop right after is explainable, not
   "phantom".
2. **Stop fighting the CLI.** Our `_auto_compact()` at `ctx_pct > 90`
   (`session.py:440`) can race the CLI's own autocompact. Decide ONE owner:
   - **Recommended:** disable the CLI's autocompact for managed sessions if we want to
     own compaction (set the relevant option), OR
   - drop our `_auto_compact` and rely on the CLI's, just *reporting* the boundary.
   Owning it in one place removes the "context reset I didn't ask for" surprise.
   (Need to confirm the SDK option name to disable CLI autocompact — see Open Q1.)

### Fix C (SECONDARY) — don't NULL `session_id` across a crash window (RC4)
In `compact()` (`session.py:645`), do not persist `session_id=None`. Instead keep the
old `session_id` in the DB until the new compacted turn produces a fresh one, then swap.
Minimal change: drop the `self._persist()` on line 646, OR persist to a separate
`pending_session_id` and only overwrite `session_id` once the new turn's `turn_end`
returns a real id. This closes the "restart during compact → not resumed" hole.

### Fix D (SECONDARY) — refresh `_last_context` on resume/reconnect (RC3)
After `reconnect()` and after `_load_from_db()`, schedule a one-shot
`context_usage()` read (Fix A) so the dashboard shows the true current % instead of the
last persisted estimate (or 0). Guard the `if pct or tokens` at `manager.py:756` is
fine to keep, but the post-resume refresh makes the 0-case self-heal.

### Fix E (LOW) — single owner for `_compacting`; lock mid-turn inject bookkeeping
- Make `_auto_compact` NOT set/clear `_compacting` itself; let `compact()` be the sole
  owner (it already sets/clears in all return paths). Removes the double-management.
- Optional: when injecting mid-turn (`session.py:179`), this is fine to leave as-is for
  context purposes; only revisit if auto-report attribution becomes a real complaint.

---

## Recommended order
1. **Fix A** — biggest signal/noise win, makes the number trustworthy. Ship first.
2. **Fix B** — once A lands we have the data to surface CLI autocompact; pick one owner.
3. **Fix C** — small, closes a real (if narrow) data-loss window.
4. **Fix D** — depends on A.
5. **Fix E** — cleanup, no behavior change.

## Open questions (need confirmation before coding B/C)
- **Q1:** Exact `ClaudeAgentOptions` flag to disable CLI-internal autocompact (so
  Orchestra can own compaction). Not found in a quick grep of 0.1.72; may not be
  exposed → then Fix B part 2 becomes "report only, don't try to own it".
- **Q2:** Is `get_context_usage()` safe to call mid-turn, or only between turns? Default
  to between-turns (on `turn_end`/idle) to be safe.
- **Q3:** Confirm with real logs that the observed drops correlate with tool-heavy turns
  (RC1) vs genuine summary insertion (RC2) — `grep isCompactSummary` in the CLI session
  `.jsonl` transcript for the affected agent would prove RC2 conclusively.

## Files referenced
- `app/backend_claude.py:211-274` — ResultMessage → context_pct derivation (RC1)
- `app/session.py:389-451` — `_handle_turn_end`, `_last_context`, `_auto_compact` trigger
- `app/session.py:440` — our autocompact at >90% (RC2 race)
- `app/session.py:589-659` — `compact()` (RC4 session_id NULL window)
- `app/session.py:689-697` — `_auto_compact` (RC6 flag double-management)
- `app/manager.py:707-782` — `_load_from_db` resume (RC3)
- `app/manager.py:872-911` — `auto_resume_all` (RC4: filters session_id NOT NULL)
- SDK `claude_agent_sdk/client.py:505`, `types.py:706-768` — `get_context_usage` API
- SDK `claude_agent_sdk/_internal/sessions.py:283,933-936` — isCompactSummary semantics
