# Task #97 — Research: OpenCode SSE stuck bug

## The bug (production: 11h stuck running)

OpenCode backend's `events()` coordinates two unreliable sources to detect turn completion:

1. **SSE global bus** (`GET /event`) — fires `session.idle` when the turn ends, but the
   stream is GLOBAL (all sessions), has 30s heartbeats, and **often misses `session.idle`**.
2. **Chat POST** (`POST /session/{id}/message`) — returns the authoritative final message,
   but **sometimes never returns** (HTTP response lost → task hangs forever).

When SSE misses `session.idle` AND the chat POST hangs, `events()` never yields `turn_end`,
the listen task never exits, and `_claude_event_loop` never sets `status=IDLE`. Orchestrator
stuck `running` forever.

## Current architecture (the data flow)

```
session.send(msg)
  └─ backend.send(msg)                       # opens SSE stream + fires chat POST task
  └─ _listen_task = _claude_event_loop()     # session.py:374-379
        └─ async for event in backend.events():   # backend_opencode.py:269
              _handle_event(event)
        # when events() returns → status=IDLE  (session.py:426-431)
```

For **Claude** backend: `events()` runs forever (persistent SSE stream).
For **OpenCode** backend: `events()` returns after each turn (per-turn generator).
`_claude_event_loop` branches on `backend_type == "opencode"` to treat events()-return as
turn-done. This dual-meaning of the same loop is a source of the messiness.

### Files affected
- `app/backend_opencode.py` — **the fix lives here** (events/send/teardown). 615 lines,
  ~150 of them are the tangled SSE+chat coordination in `events()` (lines 269-447).
- `app/session.py` — `_claude_event_loop` (405-478) has opencode-specific branches that
  force IDLE when events() returns. Mostly stays; minor cleanup possible.
- `app/session_hibernate.py` — `heartbeat_loop` (56-104) is the only zombie backstop;
  `ZOMBIE_TIMEOUT_CLAUDE=1800` (30min) is why it took so long to notice. opencode is
  excluded from the listener-reconnect path (line 84).

## Debug-patch archaeology (why current code is a mess)

Last 5 commits piled timeout patches onto `events()`:
- `INACTIVITY_TIMEOUT=15` + `wait_timeout=10` — force turn_end if no meaningful SSE events
- heartbeat-bypass fix — global events (no sessionID) also check inactivity
- "reuse SSE future on timeout" — don't cancel+recreate next_line
- poll daemon on heartbeat silence — but the poll does nothing useful (`/session/{id}` has
  no "idle" field, just logs cost)

These are all **guesses at a timeout that's both safe and fast** — fundamentally fragile
because SSE-idle was never a reliable turn boundary. None address the root cause.

## KEY DISCOVERY — the daemon has authoritative turn state

Probed `opencode serve` v1.17.6 OpenAPI (`GET /doc`). The daemon exposes endpoints the
current code never uses:

| Endpoint | Returns | Use |
|---|---|---|
| `GET /session/status` | `{<sid>: {type: "idle"\|"busy"\|"retry"}}` | **authoritative turn state** |
| `POST /session/{id}/prompt_async` | `204` immediately | send without hanging POST |
| `GET /session/{id}/message` | `[...AssistantMessage]` | final cost/tokens/`time.completed` |
| `POST /api/session/{id}/wait` | `204` (blocks until idle) | ⚠️ **returned 503 — unreliable** |

### Live-probe findings (grounded, not guessed)
1. **`GET /session/status` returns `{}` for idle sessions** — it lists ONLY busy/retry
   sessions. So idle ⟺ `sid not in status` OR `status[sid]["type"] == "idle"`.
   This is the reliable completion signal — a direct daemon query, no SSE dependency.
2. **`POST /api/session/{id}/wait` returned `503 ServiceUnavailableError`** on a fresh idle
   session. The `/api/*` namespace is experimental/unreliable. **→ rules out Option C**
   (can't await a wait-endpoint). Polling `/session/status` is the robust path.
3. **`AssistantMessage`** (from `GET /session/{id}/message`) carries everything `_turn_end`
   needs: `cost`, `tokens` (input/output/cache.read/cache.write), `error`, `finish`,
   `time.completed`. So we can build `turn_end` by **reading the last message**, fully
   decoupled from whether the chat POST ever returned.
4. **`prompt_async`** accepts the same payload shape as `/message` (`parts`, `system`,
   `model`) and returns `204` immediately → eliminates the "chat POST hangs forever" class.

## Risks & edge cases to handle in the plan

- **SSE still wanted for live streaming** — text/tool/reasoning deltas come over SSE. We
  keep SSE for *richness*, but turn *boundary* must come from polling, not SSE idle.
- **Poll interval vs 30s SLA**: requirement is max 30s daemon-done→IDLE. Poll every ~3s
  → worst case ~3s after daemon idle. Comfortable margin.
- **False positive (end turn while daemon busy)**: must require status==idle, AND ideally
  the session was observed busy at least once (avoid the race where we poll status before
  the daemon has registered the just-submitted turn as busy). Probe showed a freshly-created
  session with no turn is absent from status (`{}`) — so "absent" alone is ambiguous right
  after submit. Mitigation: after `prompt_async`, wait for first busy observation (or first
  SSE part) before trusting "idle" as completion. Bounded by a short grace window.
- **retry state**: `type=="retry"` means the daemon is auto-retrying (rate limit etc.) —
  treat as busy, NOT idle. Don't end the turn.
- **Daemon dies mid-turn**: poll GET fails → connection error → end turn with error_turn_end
  (status flips IDLE, not stuck). Already how a dead daemon should behave.
- **TURN_TIMEOUT hard ceiling** stays as the ultimate backstop (1800s in session.py).

## Recommended direction (detail in plan.md)

**Option B refined: SSE for streaming, polling `/session/status` for the boundary.**
- `send()` → `prompt_async` (204, no hanging task) + open SSE for live parts.
- `events()` → stream SSE parts; concurrently poll `/session/status` every ~3s.
  Turn ends when status shows idle (after first-busy observed) OR SSE yields `session.idle`
  (fast path) OR daemon-poll connection dies (error).
- `turn_end` built from `GET /session/{id}/message` (last assistant msg) — authoritative
  cost, independent of the POST.
- Delete all the INACTIVITY_TIMEOUT / wait_timeout / drain-loop patches.
