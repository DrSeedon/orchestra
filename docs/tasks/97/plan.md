# Task #97 — Plan: reliable OpenCode turn completion

## Goal
Replace SSE-`session.idle`-as-turn-boundary (unreliable, missed → 11h stuck) with a
**daemon-authoritative poll of `GET /session/status`**. SSE stays for live streaming only.
Eliminate the hanging-chat-POST class via `prompt_async`. Delete all timeout-patch cruft.

## Design decision (chosen: Option B, refined)

| Concern | Old (broken) | New |
|---|---|---|
| Turn boundary | SSE `session.idle` (missed) + inactivity timeout guesses | poll `GET /session/status` every 3s → idle ⟹ turn done |
| Send | `POST /message` task that can hang forever | `POST /session/{id}/prompt_async` → 204 immediately |
| Live deltas | SSE | SSE (unchanged — still the streaming source) |
| Final cost/tokens | awaited chat POST result | `GET /session/{id}/message` last assistant msg |
| Backstop | INACTIVITY_TIMEOUT/wait_timeout/drain patches | **hard deadline INSIDE events()** + status-poll connection-fail |

**Why poll, not SSE idle:** `/session/status` is a direct daemon query — it cannot be
"missed" the way a fire-once SSE event can. **Why not `/wait`:** probe returned 503, the
`/api/*` namespace is unreliable.

### Idle detection rule (from live probe)
`GET /session/status` → dict of ONLY busy/retry sessions. Session is **done** when:
```
sid not in status  OR  status[sid]["type"] == "idle"
```
`type == "retry"` ⟹ still working (auto-retry), treat as busy.

### False-positive guard (the one real race)
Right after `prompt_async`, the daemon may not yet list the session as busy → polling would
see "idle" and end instantly. Guard: **require one of**
- first busy observation (`status[sid].type in {busy, retry}`), OR
- first SSE part for this session
before "idle" is trusted as completion. Until then, a short `SUBMIT_GRACE` (e.g. 20s) window
applies; if neither busy nor any SSE part appears within grace AND status is idle, treat as
done anyway (covers ultra-fast/empty turns) — but log it.

## File changes

### `app/backend_opencode.py` — the rewrite (only file with logic changes)

**Constants (top):**
- Remove nothing structural; add:
  - `STATUS_POLL_INTERVAL = 3`   # seconds between /session/status polls
  - `SUBMIT_GRACE = 20`          # max wait for first-busy/first-part before trusting idle
  - `STATUS_FAIL_THRESHOLD = 3`  # consecutive status-poll failures before declaring dead (codex #5)
- Keep `TURN_TIMEOUT` (1800, now the HARD in-events deadline), `DAEMON_READY_TIMEOUT`, `PORT_RETRIES`.

**`send()` (244-261) — rewrite:**
- Open SSE stream as today (still need live parts): `self._sse_response = GET /event (stream)`.
- **EXACT payload — confirm against OpenAPI at implement time** (codex #7). Probe of v1.17.6
  `prompt_async` body schema: `parts` required; `model` is `{providerID, modelID}` (NESTED,
  unlike the old `/message` which had them top-level); `system`, `messageID`, `agent` optional.
  So the new body is NOT identical to old `/message` — research.md note "same shape" was wrong.
  ```python
  body = {"model": {"providerID": self.provider_id, "modelID": self.model},
          "parts": [{"type": "text", "text": message}]}
  if self.system_prompt: body["system"] = self.system_prompt
  r = await self._http.post(f"/session/{self._session_id}/prompt_async", json=body)
  r.raise_for_status()    # 204 expected
  ```
- Drop `self._chat_task` entirely. Set a per-turn flag `self._turn_active = True`
  AFTER the prompt_async succeeds (so a raised send() never leaves turn_active set).
- Keep the "turn already in progress" guard via `self._turn_active`.
- **Unit test the exact JSON body** (codex #7) — a 400 from wrong shape would otherwise
  surface only after status=RUNNING.

**`app/session.py:365` — REQUIRED fix (codex #2, verified real):**
- `await backend.send(message)` at 365 is NOT wrapped; `_ensure_backend()` above it IS.
  If `send()` raises (old opencode 404, transient 5xx, bad payload) after status was set
  RUNNING (354) and before the listen task is created (374-379) → **stuck RUNNING forever**.
- Wrap line 365:
  ```python
  try:
      await backend.send(message)
  except Exception:
      if self.status == AgentStatus.RUNNING:
          self.status = AgentStatus.IDLE
          self._persist()
      raise
  ```
  Applies to all backends (harmless for claude/codex). This is the ONLY session.py logic change.

**`events()` (269-447) — rewrite (the big win: ~180 lines → ~70):**
- No more `chat_task`, `asyncio.wait({next_line, chat_task})`, INACTIVITY_TIMEOUT,
  wait_timeout, drain loops, "reuse SSE future".
- Structure: two concurrent awaitables in a clean select loop —
  1. `next_line` = SSE line future (live parts → yield via `_map_part`)
  2. `poll` = `asyncio.sleep(STATUS_POLL_INTERVAL)` tick → then status check
- Loop (with HARD deadline — codex #1, the critical fix):
  ```
  saw_activity = False         # first busy/retry OR any SSE event for our sid
  status_fails = 0
  deadline = loop.time() + TURN_TIMEOUT          # HARD ceiling INSIDE events()
  while True:
      if loop.time() > deadline:                 # ← backstop that ACTUALLY fires
          error_out = "turn_timeout"; break       #   (session.py timeout can't — only runs on yield)
      done = await wait({next_line, poll}, FIRST_COMPLETED, timeout=STATUS_POLL_INTERVAL)
      if next_line in done:
          parse; if event for our sid: saw_activity = True (codex #8: ANY sid event, not just parts); yield mapped
          if SSE 'session.idle' for our sid: poll_now = True   (codex #6: don't break — verify via status)
          re-arm next_line
      if poll fired (or poll_now):
          st = await self._session_status()        # "idle"|"busy"|"retry"|None(error)
          if st is None:
              status_fails += 1
              if status_fails >= STATUS_FAIL_THRESHOLD or self._proc_dead():
                  error_out = "status_poll_failed"; break     # codex #5: N fails OR daemon dead
          else:
              status_fails = 0
              if st in ("busy","retry"): saw_activity = True
              elif st == "idle" and (saw_activity or loop.time()-start > SUBMIT_GRACE):
                  normal_end = True; break          # ← authoritative completion
          re-arm poll
  ```
- **`finally` covers EVERYTHING after turn becomes active (codex #4):** cancel both futures,
  aclose SSE, AND always reset `self._turn_active = False`, `self._sse_response = None` here —
  so a cancel/close mid-`events()` never leaves turn_active stuck (else next send() hits
  "turn already in progress"). No chat_task to reap.
- After loop, build `turn_end` — **total, never raises (codex #3):**
  ```
  if error_out: yield self._error_turn_end(error_out); return
  try:
      msg = await self._fetch_last_message()
      if not msg: yield self._error_turn_end("no_assistant_message"); return
      yield self._turn_end(msg)
  except Exception as e:
      yield self._error_turn_end(f"message_fetch_failed: {e}")
  ```
  Guarantees: events() yields EXACTLY one turn_end on every exit path. No stuck-running.
- `_proc_dead()`: `self._proc is not None and self._proc.returncode is not None`.

**New helpers:**
- `async def _session_status(self) -> str | None`:
  `GET /session/status`; return `"idle"|"busy"|"retry"`; on httpx error return `None`
  (caller counts N consecutive Nones — does NOT end turn on a single transient, codex #5).
  `sid not in dict` → `"idle"` (probe: status lists ONLY busy/retry sessions).
- `async def _fetch_last_message(self) -> dict | None`:
  `GET /session/{id}/message`; return the last element with assistant role (current turn).
  **Normalize shape (codex #7):** `info = msg.get("info") or msg` — the message endpoint may
  return `{info, parts}` per message OR a flat AssistantMessage (probe showed flat keys
  `cost/tokens/error/finish/time`; current `_turn_end` reads `msg["info"]`). Covering both
  avoids zero-cost turn_end. Pick the last assistant message, not the whole history.

**`_turn_end()` (515-544) — minor:**
- First line: `info = msg.get("info") or msg` (normalize both shapes).
- Field reads stay identical (`tokens`, `cache`, `cost`, `error`, `finish`).

**Teardown (`disconnect` 579-604, `interrupt` 566):**
- Remove all `self._chat_task` handling (no longer exists).
- `interrupt` still POSTs `/session/{id}/abort` — unchanged.

**Remove:** `_post_chat` (263-267). `self._chat_task` field (113).

### `app/session.py` — minimal

- `_claude_event_loop` opencode branch (426-431, 459-464): **unchanged** — events()
  returning still means turn-done; the new events() just returns *reliably*. Keep as-is.
- No signature changes to `send()`/`events()` contract (still `AsyncIterator[AgentEvent]`,
  still ends with one `turn_end`).

### `app/session_hibernate.py` — no change needed
- opencode already excluded from listener-reconnect (line 84). The zombie timeout
  (`ZOMBIE_TIMEOUT_CLAUDE=1800`) remains a last-resort backstop. With the poll fix the
  primary path is now reliable, so this rarely fires. Leave it.

## What NOT to touch
- SSE part-mapping (`_map_part`, 471-513) — streaming richness logic is fine, keep verbatim.
- Daemon lifecycle (`connect`, `_start_daemon`, `_wait_ready`, gosu/uid, opencode.json) — untouched.
- `session.py` event-handling, turn manager, hibernate. Claude/Codex backends — untouched.
- `_error_turn_end` — keep.

## Migration / compatibility
- `events()` external contract unchanged: yields AgentEvents, terminates with exactly one
  `turn_end`. `_claude_event_loop` needs no changes.
- `prompt_async` requires opencode ≥ a version exposing it — confirmed present in 1.17.6
  (current bin). If a deployment pins older opencode without `prompt_async`, `send()` will
  get 404 → raises → status flips IDLE (fail loud, not stuck). Acceptable.

## Test strategy
- Unit (mock httpx) — happy + the dangerous contracts (codex #9):
  1. status flips busy→idle ⟹ exactly one `turn_end`, status IDLE.
  2. SSE never yields `session.idle`, only heartbeats ⟹ poll still ends turn (**THE bug**).
  3. `prompt_async` 204 + status idle from absent-in-dict ⟹ turn_end built from message API.
  4. status-poll GET raises ONCE (transient) ⟹ turn does NOT end (codex #5); raises
     STATUS_FAIL_THRESHOLD× OR proc dead ⟹ `error_turn_end`, no hang.
  5. retry state held N polls then idle ⟹ no premature end.
  6. submit-grace: idle-from-start with no activity ⟹ ends after grace, logged.
  7. **perma-busy: status busy forever, no SSE events ⟹ events() yields `turn_timeout`
     error_turn_end at TURN_TIMEOUT** (codex #1 — the in-events deadline; would hang without it).
  8. **`send()` raises after RUNNING set ⟹ session.py resets IDLE** (codex #2).
  9. **`_fetch_last_message()` returns [] / raises ⟹ exactly one `_error_turn_end`** (codex #3).
  10. **generator cancelled mid-`events()` ⟹ `_turn_active` reset, next send() works** (codex #4).
  11. flat AssistantMessage shape AND `{info,parts}` shape ⟹ both give non-zero cost (codex #7).
  12. exact `prompt_async` JSON body (nested `model`) asserted (codex #7).
- Run: `UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest -x -q tests/ -k opencode`
- Manual smoke (if anthropic key available): real turn, confirm IDLE within ~3s of done.

## Estimated diff
`backend_opencode.py`: ~ -160 / +90 (net simpler). Other files: 0.
