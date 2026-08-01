# Task #109 — `/limits` in Telegram private chat

## Result

- Added a `/limits` handler restricted to `chat.type == "private"`.
- Shows independent Claude 5h, Claude 7d, and Codex primary remaining quota.
- Shows every reset as an absolute Krasnoyarsk time (`UTC+7`) and a relative
  duration.
- Reports `extra_usage.spend_limit_reached` only as a separate fact and states
  that base windows are independent.
- Sends the response through `_tg_send_safe(..., important=False)` rather than
  bypassing the delivery queue.
- Reports usage failures with the exception class and substitutes
  `(без сообщения)` when `str(exception)` is empty.
- Authorizes only the configured Telegram group's `creator`; administrators and
  regular members receive `⛔ Нет доступа.` without loading usage data.
- Resolves membership only after the exact private `/limits` filter matches. A
  missing sender, missing group/bot, or lookup exception fails closed.

Pinned messages, group-topic commands, and threshold auto-posts were not added.

## Files

- `app/tg_bridge.py` — formatter, usage adapter, and private-chat handler.
- `tests/test_tg_bridge.py` — timezone/format, queue classification, owner-only
  authorization, fail-closed lookup, private-only registration, and empty
  `ReadTimeout` coverage.

## Verification

```text
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_tg_bridge.py -q \
  -k 'LimitsCommand or TgRateAdmission'
```

Result: `11 passed, 142 deselected in 2.22s`.

Full delivery suite:

```text
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_tg_bridge.py -q
```

Result: `153 passed in 8.74s`.

The earlier 56.84-second collection stall was not reproducible. Controlled
checks measured module import at 2.40 seconds, direct collection at 3.00 seconds,
and `uv run` collection at 3.00 seconds; the subsequent complete test run also
finished normally. No deterministic import or collection side effect remains in
the change.

## Breaking changes

None.

## Authorization tradeoff

The existing `group_id` is the authority source, so no new config or environment
variable was added. This requires one Bot API `getChatMember` call per `/limits`
invocation, not per private message, and avoids stale cached authorization when
the group creator changes.
