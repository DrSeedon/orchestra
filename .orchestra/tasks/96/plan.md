# Plan #96 — OpenCodeBackend implementation

**Deliverable (Phase 3):** `app/backend_opencode.py` — an `OpenCodeBackend` class satisfying `BackendLike`,
with `AgentEvent` parity to `ClaudeBackend`/`CodexBackend`.

This plan is grounded in **live empirical probing** of the daemon (v1.17.6) + SDK (0.1.0a36), not the
missing RESEARCH doc. Every event shape below was captured from a real turn (see §0).

---

## 0. Empirical ground truth (captured from a live turn)

Ran `opencode serve --port 18085`, created a session, fired a real chat on the free model
`opencode/mimo-v2.5-free`, captured the SSE bus. Findings that **change the design vs research.md**:

1. **`reasoning` parts DO exist** (binary emits them; SDK 0.1.0a36 pydantic types just don't model them).
   → **thinking parity is achievable** — but ONLY if we map from raw JSON dicts, not SDK pydantic models
   (the SDK would silently drop `reasoning`, `message.part.delta`, `session.status`, `session.diff`, etc.).
   **DECISION: parse raw event dicts, not `EventListResponse` pydantic objects.** Use the SDK only for
   the HTTP plumbing (client, session.create, session.chat, session.abort, the raw SSE stream).
2. **`message.part.delta`** exists — token-level streaming (`field:"text"`, `delta:"The"`). For an MVP we
   **map full parts from `message.part.updated`** (which carries the cumulative `text`) and **ignore
   `delta`** (avoids double-emitting). Final `part.updated` for a text/reasoning part has the complete text.
3. **`chat()` POST returns `{info, parts}`** — `info.cost` (float), `info.tokens {input,output,reasoning,
   cache:{read,write}}`, `info.finish` ("stop"), `info.modelID`, `info.providerID`. **Authoritative
   cost/tokens source.** (The reasoning/text is also fully in `.parts`, but we stream via SSE.)
4. **`session.idle` {sessionID}** = clean turn boundary. Fires once when the turn completes.
5. **`abort` endpoint** → `POST /session/{id}/abort` → HTTP 200. SDK: `session.abort(id)`.
6. **provider/model is split**: chat needs `providerID` + `modelID` separately (e.g.
   `opencode` + `mimo-v2.5-free`, or `anthropic` + `claude-...`).

### Exact shapes (verbatim from capture)
```
message.part.updated → properties.part:
  text:        {type:"text",      text, id, messageID, sessionID}
  reasoning:   {type:"reasoning", text, time:{start,end?}, id, ...}
  step-finish: {type:"step-finish", tokens:{total,input,output,reasoning,cache:{read,write}}, cost, reason}
  tool:        {type:"tool", tool, callID, state:{status, input, output?, title?, error?}}   (from SDK types)
session.idle   → properties.sessionID
session.error  → properties.{sessionID, error}
file.edited    → properties.file
chat() return  → {info:{cost, tokens:{...}, finish, modelID, providerID, error?}, parts:[...]}
```

---

## 1. Architecture decisions (answering dev-lead's 5 questions)

### Q1 — Dual-source coordination (P0) → **SSE-stream as the spine, `chat()` as a fire-and-forget task whose result is awaited at `session.idle`**

Mechanism (no extra `asyncio.Event` needed — `session.idle` IS the signal):

```
connect():
  - start daemon, wait for port ready (poll /app or read "listening on" from stdout)
  - client = AsyncOpencode(base_url=...)
  - open ONE persistent raw SSE stream (httpx) — kept for the backend's lifetime
  - session = await client.session.create()  (unless resuming → reuse stored id)

send(message):
  - self._chat_task = asyncio.create_task(client.session.chat(id, providerID, modelID, parts=[text]))
    # chat() blocks until turn end and returns the AssistantMessage — we DON'T await it here

events():   # one call drains exactly one turn, returns after turn_end
  # Monitor BOTH sources concurrently — NOT just SSE. If chat() raises an HTTP
  # error and the SSE bus stays alive (no idle/error for our session), an
  # SSE-only loop would hang forever (Codex review blocking #1).
  sse_iter = self._sse_lines()        # async generator over /event lines
  while True:
    next_line = asyncio.ensure_future(sse_iter.__anext__())
    done, _ = await asyncio.wait(
        {next_line, self._chat_task},
        timeout=TURN_TIMEOUT,           # hard ceiling; on expiry → abort + error turn_end
        return_when=asyncio.FIRST_COMPLETED)
    if not done:                        # timeout
        await self.interrupt()          # session.abort
        yield self._error_turn_end("turn_timeout"); return
    if next_line in done:
        try: raw = next_line.result()
        except StopAsyncIteration:      # SSE stream closed → daemon gone
            break
        d = json.loads(raw)
        if d["properties"].get("sessionID") != self.session_id:
            continue                    # filter global bus
        t = d["type"]
        if   t == "message.part.updated": for e in self._map_part(d): yield e
        elif t == "file.edited":          yield AgentEvent("file_change", ...)
        elif t == "session.error":        yield AgentEvent("error", ...); break   # turn done
        elif t == "session.idle":         break                                   # turn boundary
        # else: ignore (status/heartbeat/plugin/diff/etc.)
    else:
        # _chat_task finished BEFORE idle — almost always an exception (HTTP fail).
        # cancel the dangling SSE read and exit the turn now.
        next_line.cancel()
        if self._chat_task.exception():
            yield AgentEvent("error", str(self._chat_task.exception()))
            yield self._error_turn_end(f"chat_failed: {self._chat_task.exception()}"); return
        break   # rare: chat returned cleanly before idle event arrived → fall through to normal turn_end

  # normal path: turn done → authoritative metadata from the chat task
  try:
    msg = await asyncio.wait_for(self._chat_task, timeout=10)
  except Exception as e:
    yield self._error_turn_end(f"chat_await_failed: {e}"); return
  yield self._turn_end(msg)
```

**Why this is correct & deadlock-free (revised per Codex review):** we `asyncio.wait` on BOTH the next
SSE line AND the `_chat_task` with `FIRST_COMPLETED` + a `TURN_TIMEOUT`. Three exit paths, none can hang:
1. `session.idle`/`session.error` on SSE → break → await already-resolved chat task → `turn_end`.
2. `_chat_task` completes first (HTTP error before idle) → emit error + `_error_turn_end`, cancel SSE read.
3. `TURN_TIMEOUT` expires → `abort()` + `_error_turn_end`.
SSE stream closing (`StopAsyncIteration`, daemon died) → break → await chat task (timeout-guarded).
session.py always re-arms because exactly one `turn_end` is yielded on every path.

`_error_turn_end(reason)` helper → minimal metadata matching Codex's error path (backend_codex.py:199-212
is the *shape* reference — a synthesized error turn_end, though our trigger differs):
`{session_id, ok:False, stop_reason:reason, cost_usd:0, cost_usd_cached:0, context_pct:0,
context_tokens:0, max_tokens:<limit>, cache_hit:0, cache_read:0, cache_create:0, input_tokens:0,
output_tokens:0}`.

**Rejected alternatives:**
- *SSE-only (no chat await)*: would have to reconstruct cost from `step-finish` parts — fragile, multi-step
  turns sum awkwardly, and `chat()` gives the authoritative total for free. ❌
- *chat-only (no SSE)*: loses real-time streaming — dashboard would freeze until turn end. ❌
- *asyncio.Event handshake*: redundant — `session.idle` already IS the cross-source barrier. ❌

### Q2 — Daemon lifecycle → **one daemon per backend instance, fixed port from a small range, start in `connect()`, kill in `disconnect()`**

- **One daemon per backend** (= per session/worker). Matches Claude's "one client per session" principle,
  no shared-bus event filtering across workers (though we still filter by sessionID defensively), trivial
  teardown. A shared daemon is a future optimization, not MVP.
- **Subprocess**: `opencode serve --port <P> --hostname 127.0.0.1 --log-level ERROR`, launched via
  `asyncio.create_subprocess_exec` (like Codex's `_proc`). **stdout/stderr → `DEVNULL`** to avoid pipe
  back-pressure blocking the daemon (Codex review blocking #2 — don't keep an undrained PIPE). Detect
  readiness by **polling `GET /app` until HTTP 200** (with a timeout ~15s), NOT by parsing stdout (since
  stdout is DEVNULL'd). If not ready in time → kill + raise.
- **Port management**: allocate a free ephemeral port — bind `127.0.0.1:0`, read assigned port, close.
  ⚠️ TOCTOU (port freed→reused). **Mitigation (Codex review suggestion):** if the daemon fails to become
  ready (EADDRINUSE / no `/app` 200), **retry with a fresh port up to 3×** before raising. No `~/ports.md`
  registry (that's for long-lived named services, not per-instance daemons).
- **`disconnect()`** — full teardown, every step guarded so nothing hangs (Codex review blocking #2):
  ```
  try: await asyncio.wait_for(self.interrupt(), timeout=3)      # session.abort, best-effort
  except: pass
  try: await asyncio.wait_for(self._close_sse(), timeout=3)     # close httpx stream + client
  except: pass
  if self._proc and self._proc.returncode is None:
      self._proc.terminate()
      try: await asyncio.wait_for(self._proc.wait(), timeout=5)
      except asyncio.TimeoutError:
          self._proc.kill()
          await self._proc.wait()      # ← REAP after kill (was missing) — no zombie
  self._proc = None
  ```
- **Env**: pass `HTTPS_PROXY` (OpenCode→Anthropic needs the proxy, unlike Codex→OpenAI which strips it).
  Set `OPENCODE_SERVER_PASSWORD`? No — localhost-only bind, MVP skips auth (note the daemon warns but it's
  127.0.0.1). `DISABLE`-style telemetry env if available.

### Q3 — MCP injection → **write `opencode.json` into the worktree `cwd` before daemon start**

- OpenCode loads config from `<cwd>/opencode.json` (+ `opencode.jsonc`) and `~/.config/opencode/`
  (confirmed from serve.log loading order). We write a **per-worker `opencode.json` into the worktree cwd**.
- Translate Orchestra's MCP dict → OpenCode `mcp` block:
  ```json
  "mcp": { "orchestra": { "type":"local",
                          "command":["<python>","/abs/app/mcp_stdio.py"],
                          "environment": { "PYTHONPATH":..., "INTERNAL_TOKEN":..., "ORCHESTRA_URL":...,
                                           "ORCHESTRA_SCOPE":..., "ORCHESTRA_ROLE":..., "WORKER_NAME":... },
                          "enabled": true } }
  ```
  (Claude's `{command, args, env}` → `{type:"local", command:[command,*args], environment:env, enabled:true}`.)
  The backend receives the **already-built Orchestra MCP dict** (same one Claude gets via
  `mcp_servers=self.mcp_servers`) and converts it. Tools surface as `orchestra_<tool>` → `short_name`
  strips the `orchestra_` prefix for display.
- **Don't clobber a user `opencode.json`**: if one exists in cwd, log + merge our `mcp`/`permission` keys
  into it (shallow); else write fresh. MVP: own-file write is fine since worktrees are Orchestra-owned;
  add a "if exists, merge" guard to be safe.
- **Config also carries** `permission` (Q-permissions) and optionally `model`/`provider` defaults.

### Q4 — Thinking gap → **CLOSED, not a gap.** `reasoning` parts exist (empirically confirmed).
Map `message.part.updated` with `part.type=="reasoning"` → `AgentEvent("thinking", part.text)` (only when
text non-empty — the part fires once empty at start, once full at end; emit on the full one). No blocker.
**Codex nit rejected (verified):** `events.py`'s type list comment omits `"thinking"`, but `ClaudeBackend`
already emits it (backend_claude.py:248) AND session.py:488 already consumes it. The contract supports
`thinking` today — only the doc comment is stale. → tiny chore: add `"thinking"` to the events.py comment
list (no consumer change needed). Not a parity problem.

### Q5 — Tool callID dedup → **a `set[str]` of seen `callID`s, gated on `state.status` transitions**

A tool emits multiple `message.part.updated` as it transitions `pending → running → completed`. But a
fast tool may first appear ALREADY `completed` (no prior pending/running) — so we must emit `tool_use`
on the terminal state too if we never emitted it (Codex review suggestion). Track both use AND result:
```python
seen_use:    set[str] = set()   # per-turn, reset each events() call
seen_result: set[str] = set()
on part.type=="tool":
    cid = part.callID; st = part.state.status
    if cid not in seen_use and st in ("pending","running","completed","error"):
        seen_use.add(cid)
        short = part.tool.split("_",1)[-1] if part.tool.startswith("orchestra_") else part.tool
        yield AgentEvent("tool_use", f"{part.tool}: {json(part.state.input)}",
                         metadata={"tool_name": part.tool, "short_name": short})
    if st in ("completed","error") and cid not in seen_result:
        seen_result.add(cid)
        yield AgentEvent("tool_result", part.state.output if st=="completed" else part.state.error)
```
Both sets gated → `tool_use` once, `tool_result` once, even if the first sighting is terminal. Reset
both at the start of each `events()` (per-turn scope).

---

## 2. Class skeleton (`app/backend_opencode.py`)

```python
class OpenCodeBackend:
    def __init__(self, model, cwd, system_prompt="", resume_session_id=None,
                 mcp_servers=None, is_orchestrator=False, provider_id="anthropic"):
        # model here = the OpenCode modelID (provider split passed separately or parsed)
        ...
    @property
    def session_id(self) -> Optional[str]: return self._session_id

    async def connect(self):       # write opencode.json, start daemon, wait ready, open SSE, create/resume session
    async def send(self, message): # spawn chat task (no await)
    async def events(self):        # drain SSE until session.idle, map parts, yield turn_end from chat result
    async def interrupt(self):     # session.abort
    async def disconnect(self):    # abort + terminate daemon + close stream

    # helpers
    def _alloc_port(self) -> int
    def _write_opencode_json(self)            # mcp + permission + model
    async def _wait_daemon_ready(self, timeout)
    def _map_part(self, part) -> list[AgentEvent]
    def _turn_end(self, assistant_msg) -> AgentEvent
```

### `_turn_end` metadata (parity with Claude/Codex)
```python
info = msg["info"]; tok = info["tokens"]; cache = tok.get("cache", {})
input_t  = tok["input"]; output_t = tok["output"]
cache_read = cache.get("read",0); cache_create = cache.get("write",0)
max_tokens = OPENCODE_CONTEXT_LIMITS.get(self.model, 200000)
metadata = {
  "session_id": self._session_id,
  "ok": info.get("error") is None,
  "stop_reason": info.get("finish","end_turn"),
  "cost_usd": info["cost"],            # NATIVE — no TOKEN_PRICES table
  "cost_usd_cached": info["cost"],     # opencode already accounts caching (mirror Codex)
  "context_pct": min(100, int(input_t*100/max_tokens)) if max_tokens else 0,
  "context_tokens": input_t,
  "max_tokens": max_tokens,
  "cache_hit": int(cache_read*100/(cache_read+cache_create)) if (cache_read+cache_create) else 0,
  "cache_read": cache_read, "cache_create": cache_create,
  "input_tokens": input_t, "output_tokens": output_t,
  "cached_input_tokens": cache_read,   # parity with backend_codex.py:178
}
```

### SSE consumption
Use the SDK's async stream: `stream = await client.event.list()` then iterate — BUT it yields pydantic
objects that drop unknown fields. **Instead, open the raw stream via the SDK's underlying httpx client or
a dedicated `httpx.AsyncClient().stream("GET", f"{base}/event")`** and `json.loads` each `data:` line.
(Decision: raw httpx stream to `/event` — full fidelity, confirmed working in the probe.)

---

## 3. Files changed

**Phase 3 (this deliverable):**
- **NEW** `app/backend_opencode.py` (~250–300 lines).

**Phase-2-adjacent wiring — IN SCOPE for the deliverable to be usable (small, surgical):**
- `app/session.py:199` `_make_backend()` — add `elif self.backend_type == "opencode":` branch.
- `app/models.py` — add opencode model(s) to `BACKENDS` (+ `CONTEXT_LIMITS`); define
  `OPENCODE_CONTEXT_LIMITS` in backend_opencode.py (mirror Codex's local table). NO TOKEN_PRICES (native).
- `pyproject.toml` — add `"opencode-ai>=0.1.0a36"`.
- `app/events.py` — add `"thinking"` to the type-values comment list (stale doc, see Q4). Comment-only.

**NOT touched:** db.py (backend_type column already generic), hibernate (opencode behaves like codex — the
`!= "claude"` guards already cover it; verify, don't edit unless a test fails), tg_bridge, frontend.

---

## 4. Test strategy (Phase 3)

- **Unit (mock-free where possible):** `_map_part` over the captured JSON fixtures (text, reasoning, tool
  pending/completed/error, step-finish) → assert correct AgentEvent sequence. `_turn_end` over a captured
  `chat_resp` → assert metadata keys/values. `_alloc_port` returns a usable int.
- **Integration (gated, opt-in):** if `opencode` binary present → real connect→send→events→turn_end on the
  free model `opencode/mimo-v2.5-free`; assert we get text + turn_end with cost/tokens. Skip if no binary
  (CI safety) — `@pytest.mark.skipif(shutil.which("opencode") is None)`.
- Run: `UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest tests/test_backend_opencode.py -x -q`.
- Mirror existing `tests/test_backend_claude.py` structure.

---

## 5. What NOT to do
- ❌ Don't map from SDK pydantic event types (drops reasoning/delta/unknown events). Raw dicts only.
- ❌ Don't map `message.part.delta` (double-emit risk; `part.updated` carries full text). MVP = updated only.
- ❌ Don't build a TOKEN_PRICES table for opencode — native `cost` is authoritative.
- ❌ Don't support mid-turn inject in MVP — mirror Codex (session.py queues for non-claude). Daemon could
  support it later; out of scope.
- ❌ Don't register per-turn daemon ports in `~/ports.md` (dynamic allocation; registry is for named svcs).
- ❌ Don't add `subagent_*` events — OpenCode has no equivalent stream.

---

## 6. Open questions for dev-lead (non-blocking, defaults chosen)
1. **provider/model mapping**: does Orchestra pass `model` as `"anthropic/claude-..."` (split in backend)
   or as a bare modelID with provider implied? **Default assumption:** backend takes `provider_id` ctor
   arg (default `"anthropic"`) + `model` = modelID; if `model` contains `/`, split it. Confirm in review.
2. **Which opencode model(s)** to register in `models.py BACKENDS`? PoC uses the free
   `opencode/mimo-v2.5-free` for tests; production model TBD by orchestrator.
3. **Shared vs per-instance daemon** — plan picks per-instance (simplest). Flag if you want shared-pool.

---

## Risks recap (from research.md, status after probing)
| # | Risk | Status |
|---|------|--------|
| 1 | Dual-source coordination | **SOLVED (revised)** — `asyncio.wait` on SSE+chat_task, FIRST_COMPLETED, TURN_TIMEOUT; 3 non-hanging exit paths (Codex blocking #1) |
| 2 | Global bus leakage | Filter every event by sessionID (per-instance daemon makes it near-moot) |
| 3 | Tool callID dedup | **SOLVED (revised)** — seen_use + seen_result sets, terminal-first safe (Codex suggestion) |
| 4 | Thinking gap | **CLOSED** — reasoning parts exist, mapped; events.py comment stale only |
| 5 | Mid-turn inject | Deferred — Codex-style queue (MVP) |
| 6 | Daemon lifecycle | **HARDENED (Codex blocking #2)** — DEVNULL stdio, /app poll-ready, port retry ×3, terminate→wait→kill→**reap** |
| 7 | provider/model split | ctor `provider_id` + split-on-`/` (open Q1) |
| 8 | Permission schema drift | Write `permission:{edit,bash,webfetch:"allow"}`; verify keys vs v1.17.6 in impl |
| 9 | Config clobber | "if opencode.json exists, merge; else write" guard |
