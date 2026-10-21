# V-1006 — Orchestra client for MultiCode Hub MCP

Implemented Phase 1 on 2026-10-22 using the owner-confirmed `/mcp` contract. No Hub call, token issuance, credential inspection, raw relay, or service restart was performed.

## Integration seam

This is a delegation/control-plane call, not a streaming model backend. `MultiCodeClient` in [app/multicode_client.py](../../../app/multicode_client.py#L19) owns MCP HTTP initialization, JSON-RPC `tools/call`, token-safe response handling, the launch/wait/read/archive lifecycle, and queued follow-up sends. The Orchestra entry point is `multicode_run` in [app/mcp_stdio.py](../../../app/mcp_stdio.py#L321), exposed to full-access MCP callers. It returns a completed assistant reply as one string. I kept it out of `BackendLike` and `app/models.py`: those represent a token-stream runtime session, while this feature creates and controls a remote Hub thread and returns a bounded result.

The new thread is launched with `scratch: true` and `runtimeMode: "approval-required"`. Wait responses with `timedOut: true` are retried until the configured total timeout; a successful wait reads the latest assistant message and archives that thread. `send_follow_up(thread_id, message)` uses `mode: "queue"` for later turns. A timeout or read failure leaves the remote thread unarchived so that continuing work is not silently hidden.

## Configuration and first live run

Set `MULTICODE_MCP_BASE` to the hub base and `MULTICODE_MCP_TOKEN` to the out-of-band bearer. The client appends `/mcp`; for example, `MULTICODE_MCP_BASE=http://127.0.0.1:43773`. It sends the bearer only in the Authorization header and redacts it from returned text and protocol errors. Do not place the token in the base URL.

For the currently loopback-only Hub, open an outbound tunnel outside this client, for example:

```sh
ssh -N -L 43773:127.0.0.1:<hub-port> <hub-alias>
```

Before a first live run, the owner must provide/configure the bearer, ensure it has `orchestration:read` and `orchestration:operate`, and start the tunnel to the intended Hub. The Hub-side runtime/environment also needs to be appropriate for the task; V-1005 found that an agent may inherit access to the Hub user's on-remote setup, so do not connect a Hub environment that can reach the owner's laptop until that boundary is addressed. After the code is merged, the MCP process that loads `app.mcp_stdio` must be restarted/reconnected by the owner before the new tool appears. None of these live prerequisites were exercised here.

## Verification and remaining work

`uv run --frozen python -m pytest tests/test_multicode_client.py tests/test_mcp_stdio.py -q` → **144 passed** (4 new client/integration tests plus existing stdio coverage). Tests use `httpx.MockTransport`, assert MCP tool registration and initialize/initialized and launch→wait-retry→read-last-assistant→archive ordering, exercise timeout and JSON-RPC error paths, verify env token loading and confirm it is not returned in assistant output or protocol error text. The happy-path test fails if timed-out waits are not retried or if the client picks an older assistant item.

Imported paths: `app` → `/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-multicode-client/app/__init__.py`; client → `/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-multicode-client/app/multicode_client.py`.

Still required for a first live run: owner-provided bearer in the process environment, the outbound tunnel or a reachable configured HTTPS base, confirmation of the target Hub environment boundary, and an owner-authorized MCP process restart/reconnect after merge. The real Hub's response shape, token scope acceptance, and runtime behavior remain unverified by design in Phase 1.

## Follow-up: thread read response shape

The owner captured a live `t3_thread_read` response with messages in `structuredContent.items`; each item has `createdBy` and flat `text`, rather than the assumed `messages` and `role` fields. `_last_assistant_text` now scans `items` newest-first, skips entries marked as user by either `createdBy` or `role`, accepts non-empty text, and joins text blocks from `content` when flat text is absent. It retains `messages` as a compatibility fallback. The mock integration test now models the captured `items` shape with user and agent messages; a separate unit test covers content blocks.

`uv run --frozen python -m pytest tests/test_multicode_client.py tests/test_mcp_stdio.py -q` → **147 passed**. With the committed regression test, restoring the old `messages`/`role` parser makes the happy-path test fail with `MultiCode thread has no assistant reply`. No Hub call or restart was made in this follow-up; the owner will verify PONG live.
