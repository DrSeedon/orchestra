# Research: Telegram Flood Control Fix

**Date**: 2026-05-11  
**Researcher**: usage-researcher agent

---

## 1. Root Cause Analysis

### How `stream_logs()` works (tg_bridge.py:451-536)

The `stream_logs()` function polls the DB every 2 seconds for new log entries and sends EACH log as a separate TG API call:

| Log type | TG action | Method |
|----------|-----------|--------|
| `user_message` | Send new message | `sendMessage` |
| `text` | Send new message (with markdown convert) | `sendMessage` |
| `tool` | Send expandable blockquote | `sendMessage` |
| `tool_result` | Edit last tool message to add result | `editMessageText` |
| `error` | Send new message | `sendMessage` |
| `status` | Send new message | `sendMessage` |

### Typical turn breakdown (orchestrator with 15 tool calls)

```
Tool calls:      15 × 2 (send + edit) = 30 API calls
Text messages:   ~3 (thinking, response)  =  3 API calls
Status messages: ~3 (running, idle, etc)  =  3 API calls
User message:    1 echo                   =  1 API call
─────────────────────────────────────────────────────────
TOTAL:                                     ~37 API calls in 30-60 sec
```

### Telegram rate limits (official + empiric)

| Limit | Value | Source |
|-------|-------|--------|
| **Group messages** | **20 messages/minute** | [Telegram Bot FAQ](https://core.telegram.org/bots/faq) |
| Per-chat send rate | ~1 message/second (burst OK briefly) | [Telegram Bot FAQ](https://core.telegram.org/bots/faq) |
| Bulk broadcast | ~30 messages/second across chats | [Telegram Bot FAQ](https://core.telegram.org/bots/faq) |
| `editMessageText` | ~5 edits/message/minute, ~20 edits/minute/group | [grammY docs](https://grammy.dev/advanced/flood) (empiric) |
| `getUpdates` | Can be flood-blocked by outgoing flood | [aiogram #1422](https://github.com/aiogram/aiogram/discussions/1422) |
| 429 response | Returns `retry_after` seconds (1-3600) | [Telegram Bot API](https://core.telegram.org/bots/api) |

**Critical**: `getUpdates` (polling for incoming messages) shares the same rate limit pool. When outgoing flood hits 429, incoming polling is ALSO blocked for `retry_after` seconds.

### Why 37 calls kills us

- Group limit: 20 messages/minute
- We send: ~37 in 30-60 seconds → **~2x over limit**
- After flood trigger: `retry_after` blocks ALL bot API calls (including `getUpdates`)
- Result: user messages in TG go undelivered for 30-300 seconds

---

## 2. Telegram Rate Limit Details

### Per-group message sending
- Hard limit: **20 messages per minute** to the same group
- This counts `sendMessage`, NOT `editMessageText` (edits have separate bucket)
- So our 30 `sendMessage` calls alone blow the limit

### Edit limits (empiric, not documented)
- ~5 edits per message per minute
- ~20 edits per group per minute
- Edits are cheaper than sends — key insight for the fix

### getUpdates interaction
- `getUpdates` (long polling) counts as an API call
- If flood 429 is active, `getUpdates` also returns 429
- aiogram's polling loop retries but user messages are delayed
- [Discussion: getUpdates rate limit](https://github.com/aiogram/aiogram/discussions/1422)

### 429 retry_after behavior
- Response includes `"retry_after": N` (seconds)
- Escalating: typically 1s → 5s → 30s → 60s → 300s
- ALL API methods blocked until timer expires
- Must respect `retry_after` — repeated violations increase the penalty

---

## 3. Proposed Fix: Turn-Based Message Batching

### Core idea
During an active turn, DON'T send per-event. Instead:
1. Send ONE "working" message at turn start
2. Accumulate tool calls and text into a buffer
3. Flush buffer to TG every **5 seconds** by EDITING the working message
4. On turn end, send a final summary message

### Architecture

```python
@dataclass
class _TurnBuffer:
    thread_id: int
    working_msg: types.Message | None = None   # the "🔄 Working..." message
    entries: list[str] = field(default_factory=list)
    last_flush_ts: float = 0.0
    flush_task: asyncio.Task | None = None
    tool_count: int = 0
    is_active: bool = False

_turn_buffers: dict[str, _TurnBuffer] = {}  # keyed by session_id
```

### Event handling (new logic)

```python
FLUSH_INTERVAL = 5.0  # seconds between TG edits
MAX_MSG_LEN = 4000    # TG message limit (leave room for entities)

async def _handle_log_event(session_id: str, thread_id: int, log_type: str, content: str):
    buf = _get_turn_buffer(session_id, thread_id)
    
    if log_type == "status" and "running" in content.lower():
        # Turn started — send working indicator
        if not buf.is_active:
            buf.is_active = True
            buf.working_msg = await bot.send_message(
                config["group_id"], "🔄 Working...",
                message_thread_id=thread_id,
            )
            buf.last_flush_ts = time.time()
            _schedule_flush(session_id)
        return
    
    if log_type == "status" and "idle" in content.lower():
        # Turn ended — final flush + summary
        await _final_flush(session_id)
        return
    
    if log_type == "tool":
        buf.tool_count += 1
        tool_name = content.split(":")[0].strip()
        icon = _tg_tool_icon(tool_name)
        short = _tg_tool_short(tool_name)
        buf.entries.append(f"{icon} {short}")
        # Don't send yet — will flush on interval
        return
    
    if log_type == "tool_result":
        # Just count, don't send individually
        preview = content[:60].replace("\n", " ")
        if buf.entries and buf.entries[-1].startswith(("🖥", "📖", "✏", "🔎", "🌐", "🤖", "🔧", "🔌")):
            buf.entries[-1] += f" → {preview}"
        return
    
    if log_type == "text":
        buf.entries.append(f"💬 {content[:200]}")
        return
    
    if log_type == "user_message":
        # User messages always send immediately (low volume)
        prefix = "📨" if content.startswith("[from:") else "👤"
        await bot.send_message(
            config["group_id"], f"{prefix} {content[:3000]}",
            message_thread_id=thread_id,
        )
        return
    
    if log_type == "error":
        # Errors always send immediately
        await bot.send_message(
            config["group_id"], f"❌ {content[:1000]}",
            message_thread_id=thread_id,
        )
        return


async def _flush_buffer(session_id: str):
    """Edit the working message with accumulated entries."""
    buf = _turn_buffers.get(session_id)
    if not buf or not buf.working_msg or not buf.entries:
        return
    
    lines = buf.entries[-20:]  # keep last 20 entries to stay under 4k
    text = f"🔄 Working... ({buf.tool_count} tools)\n\n" + "\n".join(lines)
    text = text[:MAX_MSG_LEN]
    
    try:
        await bot.edit_message_text(
            text, chat_id=config["group_id"],
            message_id=buf.working_msg.message_id,
        )
    except Exception as e:
        logger.warning(f"Flush edit failed: {e}")
    
    buf.last_flush_ts = time.time()


async def _final_flush(session_id: str):
    """End of turn — send final summary, clear buffer."""
    buf = _turn_buffers.get(session_id)
    if not buf:
        return
    
    # Final edit of working message
    if buf.working_msg and buf.entries:
        lines = buf.entries[-30:]
        text = f"✅ Done ({buf.tool_count} tools)\n\n" + "\n".join(lines)
        text = text[:MAX_MSG_LEN]
        try:
            await bot.edit_message_text(
                text, chat_id=config["group_id"],
                message_id=buf.working_msg.message_id,
            )
        except Exception:
            pass
    
    # Reset
    buf.entries.clear()
    buf.tool_count = 0
    buf.working_msg = None
    buf.is_active = False
    if buf.flush_task:
        buf.flush_task.cancel()
        buf.flush_task = None


def _schedule_flush(session_id: str):
    """Schedule periodic flushes every FLUSH_INTERVAL seconds."""
    async def _periodic():
        while True:
            await asyncio.sleep(FLUSH_INTERVAL)
            await _flush_buffer(session_id)
    
    buf = _turn_buffers[session_id]
    if buf.flush_task and not buf.flush_task.done():
        return
    buf.flush_task = asyncio.create_task(_periodic())
```

### API call reduction

| Scenario | Before | After | Reduction |
|----------|--------|-------|-----------|
| 15 tool calls | 30 sends + edits | ~6 edits (30s / 5s interval) | **80%** |
| 3 text blocks | 3 sends | 0 (folded into working msg) | **100%** |
| 3 status msgs | 3 sends | 1 send + 1 edit | **67%** |
| User message | 1 send | 1 send | 0% |
| **Total** | **~37 calls** | **~8 calls** | **~78%** |

For a 60-second turn with 15 tool calls:
- **Before**: ~37 API calls (20 sends + 17 edits) → flood
- **After**: ~8 API calls (2 sends + 6 edits) → well under 20/minute limit

---

## 4. Protecting Incoming Messages (getUpdates)

### Problem
aiogram's `dp.start_polling(bot)` uses the same `Bot` instance for `getUpdates`. If outgoing sends trigger 429, `getUpdates` is also blocked.

### Solution: Separate concerns

**Option A: Retry-after aware sending (recommended)**
Wrap all outgoing TG calls in a throttle that respects 429:

```python
import asyncio, time

_tg_send_lock = asyncio.Lock()
_tg_blocked_until = 0.0

async def _tg_safe_call(coro):
    """Execute a TG API call with flood protection. Skips if currently blocked."""
    global _tg_blocked_until
    now = time.time()
    if now < _tg_blocked_until:
        logger.debug(f"TG throttled, skipping (blocked for {_tg_blocked_until - now:.1f}s)")
        return None
    
    try:
        return await coro
    except TelegramRetryAfter as e:
        _tg_blocked_until = time.time() + e.retry_after
        logger.warning(f"TG flood: blocked for {e.retry_after}s")
        return None
    except Exception as e:
        logger.warning(f"TG call failed: {e}")
        return None
```

With this wrapper:
- Outgoing sends that hit 429 → silently skipped (buffer keeps accumulating, next flush will send)
- `getUpdates` runs on aiogram's own loop → NOT wrapped → continues working
- When flood clears → next flush succeeds

**Option B: Separate bot instance for polling (overkill)**
Use two `Bot` instances with the same token — one for polling, one for sending. Telegram tracks flood per-token (not per-connection), so this doesn't actually help. NOT recommended.

**Option C: Webhook instead of polling (architectural change)**
Replace `start_polling` with webhook. FastAPI handles incoming, outgoing is separate. But requires public URL + HTTPS. NOT recommended for local setup.

### Recommendation: Option A
Wrap all `bot.send_message` / `bot.edit_message_text` calls in `_tg_safe_call()`. Combined with the turn-based batching from section 3, we'll almost never hit 429 in the first place. The wrapper is just a safety net.

---

## 5. What Other Bots Do

### ChatGPT Telegram bots (community)
- Send ONE message, then `editMessageText` every 1-3 seconds with streaming chunks
- Only EDIT, never send multiple messages during a response
- Final message is the complete response

### Claude Telegram bots (community)  
- Similar pattern: single message + periodic edits
- Some batch tool calls into a collapsed "Tools used: Read, Bash, Edit" line
- Response streamed via edits at 2-5 second intervals

### Key pattern
All well-behaved streaming bots:
1. **1 send** at response start
2. **Edit-only** during response (edits don't count toward the 20/min send limit)
3. **1 send** for final response (or just leave the last edit as final)

This maps directly to our proposed fix.

---

## 6. Implementation Plan

### Phase 1: Turn-based buffering (critical)
1. Add `_TurnBuffer` dataclass and `_turn_buffers` dict
2. Replace per-event sending in `stream_logs()` with `_handle_log_event()`
3. Implement `_flush_buffer()` with 5-second interval edits
4. Implement `_final_flush()` on turn end

### Phase 2: Flood safety net
1. Add `_tg_safe_call()` wrapper with TelegramRetryAfter handling
2. Wrap ALL `bot.send_message` and `bot.edit_message_text` calls
3. Skip silently on flood — buffer continues accumulating

### Phase 3: Final response delivery
1. When `text` log with substantial content arrives after tools → send as NEW message (the actual response)
2. Keep expandable blockquotes for the final response (it's the important part)
3. Tool execution details stay in the "working" message (compressed)

### Files to modify
- `app/tg_bridge.py` — main changes (stream_logs rewrite, add buffer, add throttle)

### Estimated effort
- Phase 1: ~100 lines changed in `stream_logs()`
- Phase 2: ~30 lines (wrapper function)  
- Phase 3: ~20 lines (final response logic)

### What NOT to change
- Incoming message handlers (they work fine, low volume)
- Media handlers (debounce already works)
- Topic management (ensure_topics, topic_sync_loop)

---

## 7. Summary

| What | Current | Proposed |
|------|---------|----------|
| TG calls per turn | ~37 (flood) | ~8 (safe) |
| Tool calls | 1 send + 1 edit each | Batched into working msg edits |
| Text blocks | 1 send each | Folded into working msg |
| Status updates | 1 send each | Start/end only |
| Incoming messages | Blocked by flood | Protected by throttle wrapper |
| User experience | Messages disappear during flood | Compact, updating "working" view |

Sources:
- [Telegram Bot FAQ — Rate Limits](https://core.telegram.org/bots/faq)
- [grammY — Flood Limits Guide](https://grammy.dev/advanced/flood)
- [aiogram — getUpdates Rate Limit Discussion](https://github.com/aiogram/aiogram/discussions/1422)
- [aiogram — RetryAfter Strategy Discussion](https://github.com/aiogram/aiogram/discussions/1489)
- [python-telegram-bot — Avoiding Flood Limits Wiki](https://github.com/python-telegram-bot/python-telegram-bot/wiki/Avoiding-flood-limits)
