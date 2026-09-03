# Research — intermittent Telegram topic delivery

**Date:** 2026-07-18  
**Scope:** local Orchestra service, `app/tg_bridge.py`, live read-only SQLite data, systemd journals, and both proxychains configurations.

## Question

- **Context:** every active agent has an independent `stream_logs()` task, while all primary topics belong to one Telegram supergroup.
- **Change under test:** make outbound delivery preserve important agent/user/error messages through bursts and transient Telegram/proxy failures.
- **Baseline:** the current `_tg_send_safe()` helper plus direct `bot.send_*` / edit calls.
- **Outcome:** no silent loss after a recoverable 429/network error, every final payload is within the Bot API limit, and important sends are serialized below the group quota.

## Hypotheses considered

### H1 — sender-side control is the primary cause

The bridge loses messages because concurrent stream tasks bypass or race the throttle, final payload validation happens too early, and send errors are swallowed.

**Falsifier:** concurrent `_tg_send_safe()` calls are serialized; the observed failures have no matching journal evidence; final post-Markdown payloads remain within 4096 units; or callers detect `None` and retry/fallback.

### H2 — the current SOCKS5 route or `telegram-bot-api` process is the primary cause

The bridge loses messages because the local API process or its proxy is currently unavailable.

**Falsifier:** service is active without restarts, the configured SOCKS endpoint accepts TCP, and repeated Telegram HTTPS requests through that route succeed.

### H3 — topic routing is the primary cause

Messages land outside their forum topics because `message_thread_id` is absent or the persisted mapping contains null IDs.

**Falsifier:** all configured topic IDs are non-null/non-zero and the stream path passes its persisted ID to every primary text send.

### H4 — the old UTF-16 splitter bug remains unchanged

The bridge splits by Python characters and breaks astral Unicode characters.

**Falsifier:** `_split_message()` measures UTF-16 units and property checks keep each raw chunk within the configured limit.

## Findings

### F1 — group flood control is being exceeded; the limiter defect is a sufficient and likely major cause

**CONFIRMED — official primary documentation, live journal records, SQLite measurement, and a three-iteration concurrency experiment.**

Telegram's official FAQ says to avoid more than one message per second in one chat and that a bot cannot send more than 20 messages per minute in a group [1]. Topics do not create separate group quotas; all 25 primary topics use the same negative `group_id` in the current configuration.

The code enforces only `_TG_MIN_INTERVAL = 1.0`, which permits approximately 60 calls/minute. Git history shows commit `106a439d` originally used 3 seconds for the documented group quota; commit `ee6f61ab` deliberately changed it to 1 second and queued all non-important traffic. Moreover, `_last_send` is read outside any lock. Three runs with three concurrent `_tg_send_safe()` calls produced send spans of `0.000014s`, `0.000010s`, and `0.000009s` against a configured `0.05s` interval: all coroutines slept together and then sent together.

Live SQLite agent-event volume for the last 24 hours provides a candidate count of outbound Bot API operations: 234 active minutes, 60 minutes above 20 candidate calls, and a maximum of 78/minute. This is an approximation because some tool events are skipped or become edits/photos, but the journal directly confirms the result:

```text
TG flood: pausing ...                         11
TG send failed: ... Flood control exceeded   11
GetUpdates flood                              1
```

Observed `retry_after` values included 3–40 seconds. Several high-frequency paths (`_send_expandable`, photos, edits, files, topic-icon changes) call `bot.*` directly and therefore bypass `_tg_send_safe()` entirely. Telegram does not publish every internal flood bucket, so the lock-free limiter is not claimed as the exact explanation of every 429; it is independently sufficient to violate the documented group ceiling and matches the observed `SendMessage` failures.

### F2 — recoverable send failures are silently converted to apparent success

**CONFIRMED — direct code inspection plus live journal records.**

`_tg_send_safe()` retries only `TelegramRetryAfter`, and only once for `important=True`. Every other exception is logged and converted to `None`. The text caller awaits the helper inside a `try` block, but does not inspect the result. Because no exception escapes, its plain-text fallback is unreachable for Bot API send errors; the fallback remains reachable for a `md_convert()` exception itself.

The last 24 hours contain these concrete losses/failures:

```text
send_message request timeout                  7
send_file request timeout                     2
result-image request timeout                  2
invalid local-path URL entity                 3
message too long                              1
topic-icon request timeout                   20
```

Network timeouts are transient candidates for bounded retry. Retrying a timed-out `sendMessage` changes delivery from at-most-once toward at-least-once and therefore carries a duplicate-message risk if Telegram accepted the first request but its response was lost.

### F3 — splitting raw Markdown before conversion allows an oversized final payload

**CONFIRMED — reproduced with the exact SQLite row that caused the live Bot API rejection.**

The Bot API accepts 1–4096 characters after entity parsing [2]. In the agent-text path, `_split_message(raw_text)` runs before `md_convert(chunk)`. The real message in log row `265954` measured:

```text
raw_utf16=3720
converted_utf16=5262
preconvert_chunk_count=1
postconvert_lengths=[5262]
```

The Markdown table conversion expanded the payload by 1542 UTF-16 units. The journal recorded `Bad Request: message is too long` four seconds later. The existing UTF-16 function is correct; the remaining bug is validation order. Long converted messages also retain an entity list for the unsplit full text in the `send_message` pretty-format path, which can make entity ranges invalid after splitting.

### F4 — Markdown URL entities can turn local paths into rejected messages

**CONFIRMED — three live Bot API rejections and code behavior.**

The journal contains three `Bad Request: entity URL '/mnt/data/.../research.md' is invalid: URL host is empty` errors. `md_convert()` produced URL entities for local Markdown links. `_tg_send_safe()` swallowed each rejection, so the caller never resent the same visible text without entities.

### F5 — current topic IDs and routing are valid

**REFUTED as root cause — live configuration measurement and call-site inspection.**

`data/tg_bridge.json` contains 25 primary topics and one mirror; there are zero null/zero primary topic IDs and zero null/zero mirror IDs. `stream_logs(name, thread_id)` passes that ID as `message_thread_id` on the primary text path. `send_file_to_tg()` explicitly rejects missing topic IDs instead of silently sending to the general topic. The Bot API documents `message_thread_id` as the forum-topic identifier [2].

### F6 — the proxy and local API are healthy now, but transient network faults occurred

**CONFIRMED for current health; LIKELY as a secondary contributor — direct measurements plus journal history.**

`telegram-bot-api` is currently `active/running`, PID 1535, with `NRestarts=0` since 2026-07-18 09:21:31 +07. Its own journal had no entries in the requested last hour. Both `/etc/proxychains4.conf` and `~/.proxychains/proxychains.conf` currently select `socks5 127.0.0.1 12345`; the TCP endpoint passed 3/3 connection attempts. With inherited HTTP proxy variables removed to avoid double-proxying the diagnostic curl, Telegram HTTPS returned HTTP 302 in 3/3 runs at `0.405s`, `0.413s`, and `0.419s`.

The Orchestra journal nevertheless recorded request timeouts earlier in the 24-hour window. Thus a transient route/API stall contributes to loss only because the bridge performs no bounded retry for important network failures; current proxy outage is not the primary root cause.

### F7 — the old UTF-16 defect is fixed, but a related post-conversion defect remains

**CONFIRMED — direct source inspection and the reproduced long-message failure.**

`_utf16_len()` measures UTF-16LE code units, and `_split_message()` uses it for every fit decision. No null topic or malformed-surrogate evidence appeared. The remaining failure is not the old Python-`len()` bug: `md_convert()` changes the final text after the UTF-16 limit was checked.

## Counter-evidence and limits

- The proxy is healthy now, so current liveness tests cannot reproduce the earlier timeout window. The journal is the evidence for those transient failures.
- SQLite `logs` has no `tg`/`telegram` event type; it stores agent events, not Python logger output. One older tool-result row (`249793`) embeds a copied journal excerpt with a 26-second flood pause, but it is not a first-class delivery record. Root-cause evidence therefore comes primarily from systemd journal plus deterministic code experiments.
- The 78 calls/minute SQLite figure is a candidate Bot API operation count, not packet capture. Direct 429 journal entries independently confirm quota exhaustion.
- Bounded retry after a network timeout can duplicate a message. There is no Bot API idempotency key for `sendMessage`; the fix must explicitly prefer at-least-once delivery for important messages and keep retries small.
- The official FAQ states message limits, but does not fully specify how every edit/topic operation shares internal flood buckets. The observed `GetUpdates` and send flood errors show that the current aggregate traffic is already unsafe regardless of that undocumented detail.

## Root cause

The missing-topic symptom has three sender-side causes that compound:

1. **Flooding:** a 1-second, lock-free throttle serves many concurrent topic streams in a group limited to 20 messages/minute; numerous high-frequency calls bypass the helper.
2. **False success:** `_tg_send_safe()` catches timeout, bad-request, and other failures, returns `None`, and callers proceed as if delivery succeeded. Important messages retry only one special error class.
3. **Invalid final payload:** raw Markdown is split before conversion, so conversion can exceed 4096 units; invalid Markdown URL entities are not retried as plain text.

The live proxy, bot process, topic IDs, and the repaired raw UTF-16 splitter are not the primary causes.

## Recommended fix

1. Route every message-producing call in the primary group (`sendMessage`, message edits, photos, and files) through a limiter keyed by `chat_id`, then restore a group-safe ~3.05-second interval. Mirror chats get independent per-chat limiters. Under contention/flood, discard low-value tool/status/image traffic before it occupies a slot; preserve important agent/user/error/file messages in arrival order.
2. For important `sendMessage`, retry `TelegramRetryAfter` according to `retry_after` and retry transient `TelegramNetworkError`/server errors with a small bounded backoff. Hold serialization through the wait to prevent a retry stampede.
3. If Telegram rejects formatted entities, retry the same visible text once without entities. Log a distinct `LOST` message only after the final important attempt fails.
4. Convert Markdown first, then check the final UTF-16 length. If it needs multiple chunks, send plain chunks so entity offsets cannot cross chunk boundaries.
5. Hold a per-chat lock through flood/network retry so waiting coroutines cannot stampede. Do not build an unbounded explicit queue: each important `stream_logs()` coroutine blocks on the lock and therefore preserves its own SQLite order; non-important calls are rejected before waiting. This accepts possible cross-topic unfairness after a long flood wait but bounds low-value backlog for the MVP.
6. Add unit tests for concurrent serialization, 429/network retry, entity fallback, final-payload splitting, and topic-ID preservation.

## Affected files, risks, and edge cases

- `app/tg_bridge.py`: outbound throttling/retry and Markdown preparation.
- `tests/test_tg_bridge.py`: deterministic asyncio and formatting regression coverage.
- `docs/tasks/tg-message-delivery/`: research, plan, review, and report artifacts.

Risks: duplicate important message after an ambiguous network timeout; delayed important messages during a real 40-second flood wait; intentionally omitted tool/status chatter during bursts; formatting loss only for multi-chunk or entity-rejected messages. Do not restart Orchestra during implementation—the project requires explicit user approval because restart interrupts active turns.

## Sources

1. [Telegram Bots FAQ — rate limits](https://core.telegram.org/bots/faq#my-bot-is-hitting-limits-how-do-i-avoid-this) — **Tier 2, primary official documentation**, opened 2026-07-18.
2. [Telegram Bot API — `sendMessage`, `message_thread_id`, and `retry_after`](https://core.telegram.org/bots/api) — **Tier 2, primary official specification**, opened 2026-07-18.

## Raw measurement commands

All production data access was read-only. No Telegram message was sent during experiments.

- `sqlite3 -readonly /mnt/data/Projects/Python/orchestra/data/orchestra.db ...`
- `journalctl -u orchestra --since '24 hours ago'`
- `systemctl show telegram-bot-api -p ActiveState -p SubState -p MainPID -p NRestarts`
- three `nc -z 127.0.0.1 12345` checks
- three clean-environment `proxychains4 ... curl https://api.telegram.org` checks
- fake-bot asyncio concurrency experiment, three iterations
- exact-row `md_convert()` reproduction for SQLite log ID `265954`
