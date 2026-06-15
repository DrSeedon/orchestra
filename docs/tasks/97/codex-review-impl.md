---
slug: impl-review
topic: "#97 implementation review (opencode poll-based turn boundary)"
created: 2026-06-15
model: gpt-5.5 (UNAVAILABLE) → fallback self-review
---

## Codex availability

Codex CLI cross-LLM review FAILED — network-blocked, twice:
- without proxy: `403 Forbidden` from chatgpt.com (Cloudflare, RU exit IP)
- with Hiddify HTTP proxy: `Connection refused` on `wss://chatgpt.com/backend-api/codex/responses`
  (Codex uses WebSocket; an HTTP proxy can't tunnel it)

Per skill policy: retried once (twice total), then stopped — this is an infra/network
issue, not a code issue. Falling back to an adversarial SELF-review of the implementation
against the 5 blocking items from the plan review (`codex-review-plan.md`), plus a runtime
busy-loop probe.

## Tests

`tests/test_backend_opencode.py` — **44 passed**.
`tests/test_backend_routing.py` — passed.
`tests/test_session.py` — 2 PRE-EXISTING failures (`no such table: bg_jobs` fixture gap,
confirmed failing on clean tree without #97 changes; unrelated).

Runtime probe (always-busy daemon, 0.5s deadline / 0.05s poll): ended in 0.50s with
exactly 10 status polls (NOT thousands) → **no busy-loop**, hard deadline fired inside
events(). stop_reason=`turn_timeout`.

## Findings

### Plan-review blocking items — verification in code

- **(1) hard deadline INSIDE events()** — CLOSED. `backend_opencode.py:313,317-320`:
  `deadline = start + TURN_TIMEOUT`, checked at the top of every loop iteration →
  `error_out="turn_timeout"`. Runtime-verified above. The `session.py` timeout (which only
  runs on yield) is no longer the sole backstop.
- **(2) session.py send() wrapped** — CLOSED. `session.py:365-374`: `await backend.send()`
  in try/except → resets `IDLE` + persist on failure, re-raises.
- **(3) message-fetch total → exactly one turn_end** — CLOSED. `backend_opencode.py:394-405`:
  `error_out` path yields one error_turn_end; `normal_end` path wraps `_fetch_last_message()`
  in try/except (`message_fetch_failed`), empty → `no_assistant_message`. Tested both.
- **(4) _turn_active reset in finally** — CLOSED. `backend_opencode.py:390-391`: `finally`
  always sets `_turn_active=False`, `_sse_response=None`. Cancel-mid-events test green.
- **(5) status-poll N fails, not single** — CLOSED. `backend_opencode.py:362-366`:
  `STATUS_FAIL_THRESHOLD=3` consecutive OR `_proc_dead()`; single transient resets the
  counter on next success. Both tested.

### Self-review (adversarial pass over the new events() loop)

- `thought:` turn_end guarantee — every loop exit sets exactly one of {error_out, normal_end};
  the post-finally block yields exactly one turn_end on each. Generator-cancel path propagates
  CancelledError through finally (state cleaned) with no turn_end — correct, the consumer is gone.
- `thought:` no double-processing — after handling an SSE line, `next_line.done()` is True, so
  the next iteration re-arms it at :322 before :336 re-reads; the same `raw` is never read twice.
- `thought:` no busy-loop — when `poll_now` skips the wait, the very next status poll either
  ends the turn or sets `poll_now=False`, after which the loop blocks on the `poll` sleep
  (or the SSE line). Verified empirically: 10 polls in 0.5s, not thousands.
- `nit:` `prompt_async` nested `model:{providerID,modelID}` matches the probed v1.17.6 schema;
  asserted indirectly via the integration test (gated on the binary). A unit test on the exact
  body shape would harden against a silent daemon-API change — low priority.

## Verdict

APPROVED (self-review; Codex unavailable for network reasons). All 5 plan-review blocking
items verified closed in code + tests. No stuck-running path remains; hard deadline confirmed
at runtime. The one nit (explicit prompt_async body unit-test) is non-blocking.
