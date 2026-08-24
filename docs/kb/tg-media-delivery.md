# tg-media-delivery

## Установлено

- `send_file` normal important photos use direct `bot.send_photo`; `_TG_IMPORTANT_ATTEMPTS=3`, each important call is wrapped in a 30 s bridge timeout, and timeout/network/server errors can trigger a new attempt · `app/tg_bridge.py:922-940,1290-1406,2347-2382` · 2026-08-24, #333
- The 2026-08-24 15:05:35 local `send_photo` attempt timed out at 15:06:05 and 15:06:36, then logged `LOST after 3 timed out attempts` and returned `/api/tg/send_file` HTTP 500 at 15:07:08 · sanitized journal in `docs/tasks/333/evidence/journal-tg-1504-1510.txt` · 2026-08-24, #333
- A timeout/retry is delivery-ambiguous: current code carries no event/idempotency key into Bot API calls, so duplicate external effects are possible but not proven by the incident logs · `app/tg_bridge.py:1304-1386`; official API request surface `https://core.telegram.org/bots/api`; no upstream receipt in journal · 2026-08-24, #333
- `/api/tg/send_file` maps any bridge error object to generic HTTP 500, while MCP marks a non-GET 500 as `outcome_unknown=true` and `retryable=false`; no message id/status reconciliation is returned · `app/routes/tg.py:141-157`, `app/mcp_stdio.py:448-474` · 2026-08-24, #333
- The reliable per-chat dispatcher awaits each item before selecting the next; rate-slot waiting is bounded only for admission and cosmetic traffic may drop immediately, so one 3×30 s media item blocks sequential same-chat sends · `app/tg_bridge.py:1258-1276,1623-1699,1816-1869` · 2026-08-24, #333
- Current positive controls recovered: Telegram proxy preflight passed through proxychains/gateway with `EXIT=0`, and three later file sends in the incident window returned message ids `162144`, `162147`, `162148` with HTTP 200 · `docs/tasks/333/evidence/current-controls.txt`, `docs/tasks/333/evidence/journal-tg-1504-1510.txt` · 2026-08-24, #333
- The smallest truthful durable contract is per-file `event_id`/receipt/hash/status with `UNKNOWN` after the provider boundary, no blind retry, bounded outbox/backpressure, and separate primary/mirror outcomes · `docs/tasks/333/contract.md` · 2026-08-24, #333

## Отвергнуто

- «HTTP 500 proves the file was not sent» · the route only sees `msg is None`; timeout can follow a provider-side acceptance, and no message id/upstream receipt is recorded · `app/routes/tg.py:153-157`, journal 15:06:05–15:07:08 · 2026-08-24, #333
- «The whole Telegram route was down for the interval» · proxy preflight passed and individual sends later returned 200/message ids during the same window · `docs/tasks/333/evidence/current-controls.txt`, journal · 2026-08-24, #333
- «Isolated marker/edit already gives exactly-once media» · marker timeout is explicitly not retried, while edit is a second side effect; focused tests prove handoff/ambiguous-marker behavior, not provider exactly-once · `app/tg_bridge.py:2213-2344`, `tests/test_tg_bridge.py:632-840` · 2026-08-24, #333
- «Raising the timeout or blindly retrying a 500 fixes the incident» · a client can disconnect after the provider boundary, and current 500/timeout has no stable key or receipt to make replay safe · `app/mcp_stdio.py:477-498`, `docs/tasks/380/research.md` · 2026-08-24, #333

## Пробелы

- Whether any of the three timed-out `send_photo` attempts reached upstream Telegram and whether a duplicate was actually created · local `telegram-bot-api` journal has no usable method-level receipt and current logs lack event/request ids · 2026-08-24, #333
- Which exact logical file corresponds to successful message ids `162144`, `162147`, `162148` · bridge/access logs do not correlate MCP request id, queue item, and message id · 2026-08-24, #333
- Exact number of the eight batch calls admitted before the caller stopped waiting · incident report explicitly records delivery count as unknown · 2026-08-24, #333

## Источники

- `docs/tasks/333/research.md` — full timeline reconstruction, retry/queue analysis, counter-evidence, and candidate comparison.
- `docs/tasks/333/contract.md` — smallest durable per-file contract and rollback/compatibility-controlled Class-C options.
- `docs/tasks/333/evidence/` — sanitized raw journal, DB rows, commands, current controls, and incident report.
