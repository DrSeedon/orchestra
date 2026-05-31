# Telegram Bot Streaming Research

> Date: 2026-05-11
> Context: Orchestra TG bridge — streaming tool calls & text responses in group chat with topics

---

## 1. Can We Stream in Groups?

**YES, but via `editMessageText` (not native streaming).**

### Two Mechanisms Exist

| Method | Where | How |
|--------|-------|-----|
| `sendMessageDraft` (Bot API 9.3+) | **Private chats ONLY** | Native streaming — ephemeral 30s preview, animated text appearance, finalize with `sendMessage` |
| `sendMessage` + `editMessageText` | **Everywhere** (groups, topics, DMs) | Classic approach — send placeholder, edit repeatedly as content arrives |

### sendMessageDraft Details (for reference)

```python
SendMessageDraft(
    chat_id: int,        # PRIVATE chat only
    draft_id: int,       # non-zero, same ID = animated transitions
    text: str | None,    # 0-4096 chars; empty = "Thinking…" placeholder
    message_thread_id: int | None,
    parse_mode: str | None,
    entities: list | None,
) -> bool
```

- Ephemeral 30-second preview — MUST call `sendMessage` to persist
- No rate limit concerns (purpose-built for streaming)
- Available to all bots since Bot API 9.5 (March 1, 2026)
- aiogram 3.27+ has full support: `bot.send_message_draft(...)`

### For Our Case: Groups with Topics

**We MUST use `sendMessage` + `editMessageText`.**

`sendMessageDraft` explicitly requires `chat_id` to be a "private chat". In groups/supergroups with topics, the only option is the edit-based approach. This is confirmed by OpenClaw's implementation which falls back to editMessageText for non-private chats.

---

## 2. Rate Limits

### Official (from Telegram FAQ + community consensus)

| Limit | Value | Source |
|-------|-------|--------|
| Messages per second per chat | ~1/sec | Telegram FAQ |
| Messages per minute per group | **20/min** | Telegram FAQ |
| Bulk notifications (different chats) | ~30/sec | Telegram FAQ |
| `editMessageText` per group | **~20/min** (shares quota with sends) | grammY docs, community empiric |
| `editMessageText` per single message | ~5/min (undocumented, empiric) | Community testing |

### Critical: edits share the same quota as sends

Telegram does NOT have separate quotas for sends vs edits. Both count toward the **20 messages/minute/group** limit. This is the key constraint.

### What Happens When You Exceed

- HTTP 429 response with `retry_after` field (seconds to wait)
- During `retry_after` period, **ALL** bot API calls to that chat are blocked
- "Hitting rate limits does not lead to bans. Ignoring them does." — grammY docs

### Rate Limit Math for Streaming

```
Group limit: 20 operations/minute = 1 operation every 3 seconds

Scenario A: Edit every 3 seconds
  60s turn = 20 edits → EXACTLY at the limit (dangerous)
  No room for send_message calls

Scenario B: Edit every 4 seconds  
  60s turn = 15 edits → safe margin
  Leaves ~5 slots for sends (reactions, new messages)

Scenario C: Edit every 5 seconds
  60s turn = 12 edits → comfortable
  Leaves 8 slots for other operations

RECOMMENDED: 3-second minimum spacing for ALL TG operations in a group
```

---

## 3. How Existing Bots Handle This

### claude-telegram-bot-bridge (terranc)
- DraftState tracks live messages being edited
- **Dual threshold**: edit fires when EITHER 30+ new chars OR 1.0s elapsed
- Message split at 4000 chars (paragraph break → line break → hard cut)
- Fallback: if placeholder send fails, collect all chunks, send once at end

### Iris Blog Implementation
- Sends `"..."` placeholder, captures `message_id`
- **1.5-second interval** between edits
- **20-char minimum delta** before edit fires
- Split at 4000 chars (safety buffer from 4096 limit)
- Queue-based: `ProcessConversationQueueEntry` for deferred responses

### CCBot (six-ddc)
- Per-user message queue + worker (merge, rate limit) in `message_queue.py`
- `safe_reply` / `safe_edit` / `safe_send` helpers
- Polls session JSONL every 2 seconds
- Formats tool_use, thinking blocks into TG HTML

### OpenClaw
- `DEFAULT_THROTTLE_MS = 1000` (1 edit/sec) for standard streaming
- Falls back to editMessageText for groups (sendMessageDraft only for DMs)
- Message split at 4000 chars

### Common Pattern Across All

1. Send placeholder message → capture `message_id`
2. Accumulate chunks in buffer
3. Periodically flush buffer via `editMessageText` (1-3 second interval)
4. Track `last_text` to avoid "message is not modified" error
5. Split at 4000 chars → new message for overflow

---

## 4. Error Handling

### "Message is not modified" (TelegramBadRequest)

Telegram rejects edits when new content equals current content. In aiogram 3:

```python
from aiogram.exceptions import TelegramBadRequest

try:
    await bot.edit_message_text(text=new_text, chat_id=chat_id, message_id=msg_id)
except TelegramBadRequest as e:
    if "message is not modified" in str(e):
        pass  # silently skip — content hasn't changed
    else:
        raise
```

### TelegramRetryAfter (flood control)

```python
from aiogram.exceptions import TelegramRetryAfter

try:
    await bot.edit_message_text(...)
except TelegramRetryAfter as e:
    await asyncio.sleep(e.retry_after)
    await bot.edit_message_text(...)  # retry once
```

---

## 5. Queue-Based Architecture (Recommended)

### Why a Queue

The key insight: **decouple message production (fast, async) from Telegram delivery (rate-limited, sequential).**

Agent produces tool calls and text at arbitrary speed. Telegram accepts 1 operation every 3 seconds per group. Without a queue, we either:
- Drop messages (bad)
- Hit 429 and get blocked (worse)
- Add `await asyncio.sleep(3)` everywhere (couples all code to TG limits)

With a queue: producer fires-and-forgets into the queue, a single consumer drains at TG-safe speed. If a burst of 20 messages comes, they queue up and drain over ~60 seconds. Eventually queue empties, no messages lost, no flood.

### Architecture

```
Agent work loop                    TG Queue Consumer
──────────────                     ─────────────────
tool_call("git status")     →  queue.put(ToolCall)
tool_call("Read file.py")  →  queue.put(ToolCall)     → edit msg #1: "🖥 git status"
tool_result(text)           →  queue.put(TextStart)    → edit msg #1: "🖥 git status\n📖 Read file.py"
text_chunk("Here is...")    →  queue.put(TextChunk)    → send msg #2: "Here is..."
text_chunk("the fix...")    →  queue.put(TextChunk)    → edit msg #2: "Here is... the fix..."
tool_call("Edit x.py")     →  queue.put(ToolCall)     → edit msg #2: "Here is... the fix..."
                                                        → send msg #3: "✏️ Edit x.py"
```

### Implementation Sketch

```python
import asyncio
from dataclasses import dataclass
from enum import Enum
from typing import Optional

class MsgType(Enum):
    TOOL_CALL = "tool"
    TEXT_START = "text_start"
    TEXT_CHUNK = "text_chunk"

@dataclass
class TgQueueItem:
    type: MsgType
    content: str
    chat_id: int
    thread_id: Optional[int] = None

MIN_INTERVAL = 3.0  # seconds between TG API calls (group-safe)

class TgMessageQueue:
    def __init__(self, bot):
        self.bot = bot
        self._queue: asyncio.Queue[TgQueueItem] = asyncio.Queue()
        self._current_msg_id: Optional[int] = None
        self._current_type: Optional[MsgType] = None
        self._current_text: str = ""
        self._last_sent_text: str = ""

    async def put(self, item: TgQueueItem):
        await self._queue.put(item)

    async def run(self):
        """Single consumer loop — drains queue at TG-safe speed."""
        while True:
            item = await self._queue.get()
            try:
                await self._process(item)
            except Exception as e:
                log.error(f"TG queue error: {e}")
            finally:
                self._queue.task_done()
            await asyncio.sleep(MIN_INTERVAL)

    async def _process(self, item: TgQueueItem):
        needs_new_message = (
            self._current_msg_id is None
            or (item.type == MsgType.TEXT_START)
            or (item.type == MsgType.TOOL_CALL and self._current_type != MsgType.TOOL_CALL)
            or len(self._current_text) > 3800  # approaching 4096 limit
        )

        if item.type == MsgType.TOOL_CALL:
            line = item.content  # e.g. "🖥 git status"
            if needs_new_message:
                self._current_text = line
                msg = await self._safe_send(item.chat_id, item.thread_id, line)
                self._current_msg_id = msg.message_id
            else:
                self._current_text += "\n" + line
                await self._safe_edit(item.chat_id, self._current_msg_id, self._current_text)
            self._current_type = MsgType.TOOL_CALL

        elif item.type in (MsgType.TEXT_START, MsgType.TEXT_CHUNK):
            if needs_new_message:
                self._current_text = item.content
                msg = await self._safe_send(item.chat_id, item.thread_id, item.content)
                self._current_msg_id = msg.message_id
            else:
                self._current_text += item.content
                await self._safe_edit(item.chat_id, self._current_msg_id, self._current_text)
            self._current_type = MsgType.TEXT_CHUNK

    async def _safe_send(self, chat_id, thread_id, text):
        try:
            return await self.bot.send_message(
                chat_id=chat_id,
                message_thread_id=thread_id,
                text=text or "…",
                parse_mode="HTML",
            )
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
            return await self.bot.send_message(
                chat_id=chat_id,
                message_thread_id=thread_id,
                text=text or "…",
                parse_mode="HTML",
            )

    async def _safe_edit(self, chat_id, message_id, text):
        if text == self._last_sent_text:
            return  # avoid "message is not modified"
        try:
            await self.bot.edit_message_text(
                text=text,
                chat_id=chat_id,
                message_id=message_id,
                parse_mode="HTML",
            )
            self._last_sent_text = text
        except TelegramBadRequest as e:
            if "message is not modified" in str(e):
                pass
            else:
                raise
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
            await self._safe_edit(chat_id, message_id, text)
```

### Batching Optimization

The consumer doesn't have to process one item at a time. It can **drain all available items** before making a single TG API call:

```python
async def run(self):
    while True:
        item = await self._queue.get()
        batch = [item]
        # drain everything that's ready right now
        while not self._queue.empty():
            batch.append(self._queue.get_nowait())
        # process batch → single TG API call
        await self._process_batch(batch)
        for _ in batch:
            self._queue.task_done()
        await asyncio.sleep(MIN_INTERVAL)
```

This is critical: if 5 tool calls arrive in 1 second, instead of 5 separate edits (15 seconds!), we batch them into ONE edit with all 5 lines.

---

## 6. Message Grouping Rules

The user's desired flow:

```
User sends TG message(s) →
  Bot puts 👀 reaction on first+last message →
  Bot replies "✅ Получено, в работе" →
  Agent starts working →

  TOOL CALLS → ONE message, edited progressively:
    "🖥 git status
     📖 Read app/session.py
     ✏️ Edit app/session.py"

  TEXT RESPONSE → NEW message, streamed:
    "Here's what I found and fixed..."

  MORE TOOL CALLS → NEW message (never go back to old)
  MORE TEXT → NEW message

  Rule: tools grouped together, text grouped together,
        never edit an old message once a new one starts
```

### State Machine

```
State: IDLE
  on ToolCall → send new msg, state = TOOLS
  on TextStart → send new msg, state = TEXT

State: TOOLS
  on ToolCall → edit current msg (append line)
  on TextStart → send NEW msg, state = TEXT
  on TextChunk → send NEW msg, state = TEXT

State: TEXT
  on TextChunk → edit current msg (append)
  on ToolCall → send NEW msg, state = TOOLS
  on Done → state = IDLE
```

---

## 7. Recommendations for Our Implementation

### Edit Interval: 3 seconds

- 20 ops/min ÷ 60 sec = 1 op per 3 sec (hard limit)
- With batching, we can accumulate multiple tool calls between edits
- 3 seconds feels snappy enough for tool call updates
- Text streaming at 3-second intervals is acceptable (ChatGPT-like feel)

### Queue Architecture: YES

- Single `asyncio.Queue` consumer per chat/group
- Consumer drains + batches before each TG API call
- `MIN_INTERVAL = 3.0` seconds between operations
- Handles flood control automatically via queue backpressure

### Message Splitting: 3800 chars

- TG limit: 4096 chars
- Split threshold: 3800 (safety buffer for formatting/entities)
- Split at paragraph break → line break → hard cut
- On split: finalize current message, send new one

### Error Handling

1. `TelegramBadRequest("message is not modified")` → suppress silently
2. `TelegramRetryAfter` → sleep `retry_after` seconds, retry once
3. Failed placeholder send → fallback to single final message

### Parse Mode

- Use **HTML** (not Markdown) for streaming — avoids incomplete markdown entity errors
- Markdown is fragile when text is mid-stream (unclosed `*`, `` ` ``, etc.)
- HTML tolerates partial content better

---

## Sources

- [Telegram Bot API](https://core.telegram.org/bots/api)
- [Bot API Changelog](https://core.telegram.org/bots/api-changelog)
- [grammY: Scaling Up — Flood Limits](https://grammy.dev/advanced/flood)
- [GramIO: Rate Limits](https://gramio.dev/rate-limits)
- [python-telegram-bot: Avoiding Flood Limits](https://github.com/python-telegram-bot/python-telegram-bot/wiki/Avoiding-flood-limits)
- [aiogram sendMessageDraft docs](https://docs.aiogram.dev/en/dev-3.x/api/methods/send_message_draft.html)
- [aiogram editMessageText docs](https://docs.aiogram.dev/en/latest/api/methods/edit_message_text.html)
- [aiogram TelegramRetryAfter discussion](https://github.com/aiogram/aiogram/discussions/1489)
- [Iris: Streaming AI Responses to Telegram](https://iris.rezaulhreza.co.uk/blog/030-telegram-streaming)
- [Telegram Bot API 9.5 announcement](https://news.aibase.com/news/25881)
- [OpenClaw sendMessageDraft issues](https://github.com/openclaw/openclaw/issues/31061)
- [CCBot: Telegram ↔ tmux bridge](https://github.com/six-ddc/ccbot)
- [claude-telegram-bot-bridge streaming](https://deepwiki.com/terranc/claude-telegram-bot-bridge/5.2-streaming-responses)
- [Streaming costs article](https://durovscode.com/streaming-responses-telegram-bots)
- [tdlib editMessage rate limit discussion](https://github.com/tdlib/td/issues/3034)
