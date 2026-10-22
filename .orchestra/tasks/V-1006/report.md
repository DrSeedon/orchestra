# V-1006 — Orchestra client for MultiCode Hub MCP

Implemented Phase 1 on 2026-10-22 using the owner-confirmed `/mcp` contract. No Hub call, token issuance, credential inspection, raw relay, or service restart was performed during that implementation phase. Later live verification and OAuth renewal are recorded below.

## Ночь 22.10 — живые результаты (orchestrator)

- **Канал A подтверждён вживую.** Orchestra через SSH-туннель (локальный порт ДОЛЖЕН совпадать с портом serve хаба 14606, иначе Host-404) достаёт `/mcp`, запускает `t3_thread_launch` c `modelSelection`, ждёт `t3_thread_wait`, читает `t3_thread_read`. Sonnet → `PONG`; Grok 4.7 → «I am Grok 4.7, created by xAI». Жжёт пул хаба, не наши подписки.
- **Контракт (живьём):** `MULTICODE_MCP_BASE=http://127.0.0.1:<port>` БЕЗ `/mcp` (клиент добавляет сам); внешнему токену `/mcp` нужен subject `mcp-client`; `t3_thread_read` кладёт сообщения в `items` (не `messages`), без `role` — автор в `createdBy`, текст плоский в `text`.
- **B (full-access автономный воркер) НЕ достижим headless.** `auth session issue`/`pair` с полным scope (terminal/filesystem/source-control) всё равно дают потолок `approval-required`; сервер режет запуск: `runtime_mode_escalation_denied: Child full-access is broader than parent approval-required`. Поднять потолок может только интерактивный OAuth (/oauth/mcp/authorize, PKCE S256). Защита от само-эскалации; обход не делал.
- **Доступы (0600):** ключ `/home/kesha/.ssh/multicode_hub_vps`, токен `data/secrets/multicode-vps.token` (read/operate, до 2026-11-20), `<hub-user>@<hub-host>:22`, `/mcp` `127.0.0.1:14606`. Хаб: 16 CPU, 61 ГБ RAM без per-user лимита, `/mnt/claude-data` 393 ГБ, node/python/git есть, docker/sudo/uv нет.
- **OAuth для B (механика, разобрана по клиенту):** эндпоинты `/oauth/mcp/register|authorize|approval|token`; PKCE S256; `redirect_uri` ОБЯЗАН быть петлевым `http://127.0.0.1:PORT/auth/callback` (static main.cjs:35418, 85904). Потолок full-access выбирается на шаге `/oauth/mcp/approval` (консент человека). Петлевой редирект ⇒ код ловится на машине, где браузер владельца (ноутбук), затем токен переносится на VPS. План утра: на ноутбуке (есть SSH) register→локальный loopback-сервер на /auth/callback→authorize URL (через доступный ноутбуку маршрут к хабу)→владелец подтверждает в браузере, выбирает full-access→loopback ловит code→обмен на token с full-access потолком→перенос на VPS→B. Шаг интерактивный (нужен консент), делается с владельцем.
- **Осталось:** постоянный туннель + `.env` + рестарт (оживит `multicode_run` + мышление V-1007); OAuth для B (утро). Рестарт отложен — ночью заняты другие агенты.

## Integration seam

This is a delegation/control-plane call, not a streaming model backend. `MultiCodeClient` in [app/multicode_client.py](../../../app/multicode_client.py#L19) owns MCP HTTP initialization, JSON-RPC `tools/call`, token-safe response handling, the launch/wait/read/archive lifecycle, and queued follow-up sends. The Orchestra entry point is `multicode_run` in [app/mcp_stdio.py](../../../app/mcp_stdio.py#L321), exposed to full-access MCP callers. It returns a completed assistant reply as one string. I kept it out of `BackendLike` and `app/models.py`: those represent a token-stream runtime session, while this feature creates and controls a remote Hub thread and returns a bounded result.

The new thread is launched with `scratch: true` and `runtimeMode: "approval-required"`. Wait responses with `timedOut: true` are retried until the configured total timeout; a successful wait reads the latest assistant message and archives that thread. `send_follow_up(thread_id, message)` uses `mode: "queue"` for later turns. A timeout or read failure leaves the remote thread unarchived so that continuing work is not silently hidden.

## Configuration used for the initial integration

Set `MULTICODE_MCP_BASE` to the hub base and `MULTICODE_MCP_TOKEN` to the out-of-band bearer. The client appends `/mcp`; for example, `MULTICODE_MCP_BASE=http://127.0.0.1:43773`. It sends the bearer only in the Authorization header and redacts it from returned text and protocol errors. Do not place the token in the base URL.

For the currently loopback-only Hub, open an outbound tunnel outside this client, for example:

```sh
ssh -N -L 43773:127.0.0.1:<hub-port> <hub-alias>
```

Those prerequisites applied before the first live call. The renewal flow later opened its own SSH tunnel and issued its own short-lived pairing code; no Orchestra service was restarted.

## Verification and remaining work

`uv run --frozen python -m pytest tests/test_multicode_client.py tests/test_mcp_stdio.py -q` → **144 passed** (4 new client/integration tests plus existing stdio coverage). Tests use `httpx.MockTransport`, assert MCP tool registration and initialize/initialized and launch→wait-retry→read-last-assistant→archive ordering, exercise timeout and JSON-RPC error paths, verify env token loading and confirm it is not returned in assistant output or protocol error text. The happy-path test fails if timed-out waits are not retried or if the client picks an older assistant item.

Imported paths: `app` → `/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-multicode-client/app/__init__.py`; client → `/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-multicode-client/app/multicode_client.py`.

At the time of Phase 1, the first live call, token scope acceptance, and runtime behavior were unverified. The owner later captured the `items` response shape documented below; OAuth and full-access behavior were verified in the renewal run.

## Follow-up: thread read response shape

The owner captured a live `t3_thread_read` response with messages in `structuredContent.items`; each item has `createdBy` and flat `text`, rather than the assumed `messages` and `role` fields. `_last_assistant_text` now scans `items` newest-first, skips entries marked as user by either `createdBy` or `role`, accepts non-empty text, and joins text blocks from `content` when flat text is absent. It retains `messages` as a compatibility fallback. The mock integration test now models the captured `items` shape with user and agent messages; a separate unit test covers content blocks.

`uv run --frozen python -m pytest tests/test_multicode_client.py tests/test_mcp_stdio.py -q` → **147 passed**. With the committed regression test, restoring the old `messages`/`role` parser makes the happy-path test fail with `MultiCode thread has no assistant reply`. No Hub call or restart was made in this follow-up; the owner will verify PONG live.

## Headless OAuth renewal and live verification

Added `scripts/multicode_oauth_renew.py`. It dynamically registers a PKCE client, creates a 15-minute pairing code over SSH with `orchestration:read`, `orchestration:operate`, `settings:write`, and `source-control:write`, requests `full-access`, receives the callback on `127.0.0.1:18765`, and exchanges the code. It verifies the returned token claims and 30-day lifetime, then runs a full-access Haiku thread that writes and reads a marker file. Only after the thread completes with `pendingRequestCount=0` does the script atomically replace `/home/kesha/orchestra/data/secrets/multicode-oauth.token` at mode `0600` and revoke the previous session. A failed probe revokes its newly issued session without touching the existing token. `--if-expiring-within-days N` now reads `exp` locally and exits before SSH/Hub access when more than `N` days remain; otherwise it performs renewal. Cron output ends with `RENEW_SKIPPED <days-left>`, `RENEWED <expiresAt>`, or `RENEW_FAILED <reason>` (non-zero on failure).

Live run on 2026-10-22 succeeded. The active session is `f528078d-8ece-454c-8573-e15425b715f5`, issued `2026-10-22T03:12:50.242Z`, expires `2026-11-21T03:12:50.242Z`, with the four scopes above. The previous session `ca65da4c-7f4e-4a88-ba2a-1ea93ce91f52` is absent from `t3 auth session list --json`. Probe thread `mcp:90ad5e71-9fa1-4017-97df-b7203cb72d64` completed with `pendingRequestCount=0` and output `orchestra-oauth-renew-ok`. The local token file is owned by `kesha` and mode `0600`. The redacted output is preserved in [renewal-live.json](renewal-live.json); no token was printed or committed.

The live attempts exposed two transport details: the Hub returns `Mcp-Session-Id` with lowercase header keys through `urllib`, and a retry got `EADDRINUSE` binding the callback listener after an earlier request. The client now compares header names case-insensitively; the callback server enables address reuse on its loopback-only listener. Two sessions minted by earlier failed attempts (`94640da5-ff85-436f-b99d-49d092fb0786`, `5ff91def-45d5-485b-a3c3-fb8ab090d409`) were revoked after the successful probe; final session listing confirmed both and the previous session absent while the new session remained active.

`uv run --frozen python -m pytest tests/test_multicode_oauth_renew.py -q` → **6 passed**. The committed tests cover PKCE, OAuth payloads, token claims, atomic mode-`0600` replacement, skip-before-Hub behavior, and the exact `N`-day decision boundary. Mutations changing mode `0600` to `0644` and changing the skip comparison from `>` to `>=` each make a committed test fail. No live renewal was repeated for the cron-flag change; the previously verified Hub session remains the current session.

## 22.10 утро — B доказан вживую

- OAuth-консент владельца 10:03 КРС: `data/mc_oauth_flow.py` (VPS `-L 14606`→хаб; VPS→ноут `-R 14606` и `-R 18765`; браузер ноута открывает `/oauth/mcp/authorize` → `/connect-agent`, нужен одноразовый pairing code `t3 auth pairing create --ttl 15m` на хабе; выбрал Full access). Порт колбэка 8765 на VPS занят чужим Django → 18765. Клиент: dynamic registration, `token_endpoint_auth_method=none`, PKCE S256.
- Токен: `data/secrets/multicode-oauth.token` (0600, не в git), `expires_in=2592000` (30 дней, до ~21.11), scope `orchestration:read orchestration:operate settings:write source-control:write`; потолок режима — Full access (выбран на консенте, в scope не виден).
- Решающий тест `data/mc_b_oauth.sh`: `t3_thread_launch` с `runtimeMode:"full-access"`, Haiku 5.5 → тред `mcp:d59b59f7-…`, `status=completed` за 4 с, `pendingRequestCount=0`, `runtimeMode=full-access`; на хабе файл `/tmp/orchestra_b_test.txt` = `orchestra-b-ok` (03:03:24 UTC). Отказа `runtime_mode_escalation_denied` больше нет.
- Осталось: архитектура «воркер Orchestra на хабе» (где живёт код, как ветка возвращается к нам на мерж) — развилка владельцу; постоянный туннель + `.env` + рестарт по его слову.
